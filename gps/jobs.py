"""Sourcing job. Every dataset is an independent TASK with its own real state, so one dataset failing, stalling or waiting
for a decision never blocks the others, and a retry keeps everything that already finished.

Task lifecycle (all real, nothing simulated):
  state : queued | running | retrying | waiting_input | completed | failed | cancelled | skipped
  stage : queued → searching → filtering → downloading → converting → completed   (what it is doing right now)
A watchdog flags tasks with no activity for `stall_seconds`: it restarts them automatically a limited number of times,
then asks the user what to do. A superseded attempt can never overwrite a newer one (attempt numbers)."""
import csv
import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from . import catalog, connectors, coverage, exports, package, quality, timeperiod, troubleshoot
from .feed import write_json_atomic, read_json
from .net import Cancelled, NetError, SizeExceeded

STAGES = [("requirements", "Checking project requirements"), ("boundary", "Finding study-area boundaries"),
          ("download", "Searching, filtering and downloading datasets"), ("compat", "Checking compatibility"),
          ("docs", "Creating project documentation"), ("ready", "Ready for analysis")]

SUBDIRS = ["data/raw", "data/processed", "data/reference", "metadata", "workflows", "maps", "images",
           "storymap", "exports", "logs"]

MAX_PARALLEL = 3
MAX_AUTO_RETRIES = 2
TERMINAL = {"completed", "failed", "cancelled", "skipped"}
ACTIVE = {"running", "retrying"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class JobFailed(Exception):
    pass


class TaskFailed(Exception):
    """A dataset cannot continue for a non-temporary reason (shown to the user with options)."""


class TaskSkip(Exception):
    pass


def _short(e, n=220):
    return str(e).replace("\n", " ")[:n]


class Job:
    def __init__(self, store, project, region, folder, job_id=None, plan=None):
        self.store = store
        self.project = {**project, "datasets": list(project["datasets"])}
        self.planned = list(project["datasets"])
        self.region = region
        self.folder = folder
        self.id = job_id or uuid.uuid4().hex[:10]
        self.status = "queued"  # queued running ready failed cancelled interrupted
        self.message = ""
        self.created = connectors.now_iso()
        self.finished = None
        self.plan = plan or {"period": None, "datasets": {}}
        self.plan.setdefault("datasets", {})
        self.stages = {k: {"label": v, "status": "pending", "message": "", "started": None, "ended": None} for k, v in STAGES}
        self.datasets = {}
        for d in list(self.project["datasets"]):
            if d != "regc" and not self.dplan(d).get("include", True):
                self.project["datasets"].remove(d)
                continue
            self._new_task(d)
        self.ctl = {}
        self.log_lines = []
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self._pkg_lock = threading.Lock()
        self._regions = None
        self._regc_fc = None
        self.data = {"verification": {}, "inspections": {}, "compat": [], "temporal": {}, "downloads": {}, "working": {}, "exports": {},
                     "fields": {}, "study_bbox": None, "bbox": None, "region_feature_name": None, "tag_stats": {}, "exclusions": {}}

    # ---------------- plan helpers
    def dplan(self, d):
        return self.plan["datasets"].setdefault(d, {"include": True, "filters": {}, "formats": None})

    def period(self, spec=None):
        p = self.plan.get("period")
        if not p:
            return None
        if spec is not None and not connectors.caps(spec).get("period"):
            return p  # still passed along (coverage uses it); connectors ignore it when unsupported
        return p

    def opts(self, d):
        f = dict(self.dplan(d).get("filters") or {})
        return {"period": self.plan.get("period"), "filters": f, "region": self.region}

    def limit_bytes(self):
        mb = float(self.store.settings.get("max_file_mb") or 0)
        return int(mb * 1024 * 1024) if mb > 0 else None

    def _new_task(self, d):
        s = catalog.DATASETS[d]
        self.datasets[d] = {"id": d, "name": s["name"], "publisher": s["publisher"], "source_url": s.get("landing_url"),
                            "role": s["role"], "state": "queued", "stage": "queued", "status": "queued", "bytes": 0, "records": None,
                            "total": None, "measurable": False, "warnings": [], "output": None, "processed": None, "error": None,
                            "message": "Waiting to start", "validated": False, "attempt": 0, "auto_retries": 0, "decision": None,
                            "stalled": False, "last_activity": None, "last_activity_ts": None, "coverage": None, "diagnosis": [],
                            "est_bytes": None, "exports": [], "skipped_exports": [], "can": {}}

    # ---------------- plumbing
    def path(self, *p):
        return os.path.join(self.folder, *p)

    def log(self, msg):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        with self.lock:
            self.log_lines.append(line)
            self.log_lines = self.log_lines[-600:]
        try:
            os.makedirs(self.path("logs"), exist_ok=True)
            with open(self.path("logs", "job.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def snapshot(self):
        with self.lock:
            done = sum(1 for s in self.stages.values() if s["status"] == "done")
            tasks = {}
            for d, t in self.datasets.items():
                t = dict(t)
                t["can"] = self._can(d)
                tasks[d] = t
            return {"id": self.id, "project_id": self.project["id"], "title": self.project["title"], "question": self.project.get("question"),
                    "region": self.region, "folder": self.folder, "status": self.status, "message": self.message, "approval": None,
                    "created": self.created, "finished": self.finished, "stages": self.stages, "stages_done": done, "stages_total": len(STAGES),
                    "datasets": tasks, "log": self.log_lines[-150:], "compat": self.data["compat"], "inspections": self.data["inspections"],
                    "temporal": self.data["temporal"], "tag_stats": self.data["tag_stats"], "exports": self.data["exports"],
                    "period": self.plan.get("period"), "limit_mb": self.store.settings.get("max_file_mb"), "now": time.time(),
                    "stall_seconds": self.store.settings.get("stall_seconds", 90)}

    def _can(self, d):
        spec = catalog.DATASETS.get(d, {})
        c = connectors.caps(spec) if spec else {}
        return {"split": bool(c.get("split")), "reduce": bool(c.get("server_limit")),
                "filters": bool(connectors.filter_schema(spec, self.data["verification"].get(d))) if spec else False}

    def persist(self):
        try:
            snap = self.snapshot()
            snap["data"] = {k: v for k, v in self.data.items() if k not in ("inspections",)}
            snap["plan"] = self.plan
            snap["planned"] = self.planned
            write_json_atomic(self.path("logs", "job_state.json"), snap)
        except OSError:
            pass

    def set_stage(self, key, status, message=""):
        with self.lock:
            st = self.stages[key]
            if status == "running":
                st["started"] = connectors.now_iso()
            if status in ("done", "failed"):
                st["ended"] = connectors.now_iso()
            st["status"], st["message"] = status, message
        self.persist()

    # ---------------- task state (attempt-guarded so a stale thread can never overwrite a newer attempt)
    def current(self, d, attempt):
        c = self.ctl.get(d)
        return bool(c) and c["attempt"] == attempt

    def tset(self, d, attempt, quiet=False, **kw):
        if attempt is not None and not self.current(d, attempt):
            return False
        with self.lock:
            t = self.datasets[d]
            t.update(kw)
            if "state" in kw:
                t["status"] = kw["state"] if kw["state"] != "completed" else "validated"
            if not quiet:
                t["last_activity"] = connectors.now_iso()
                t["last_activity_ts"] = time.time()
                if "stalled" not in kw:
                    t["stalled"] = False
        return True

    def ds(self, d, **kw):  # unguarded update (boundary stage / manual actions)
        self.tset(d, None, **kw)

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ---------------- control
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancel.clear()
        self.status = "running"
        self.message = ""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            for key, _ in STAGES:
                self.check_cancel()
                self.set_stage(key, "running")
                try:
                    msg = getattr(self, "stage_" + key)() or ""
                except Cancelled:
                    raise
                except JobFailed as e:
                    self.set_stage(key, "failed", str(e))
                    raise
                except Exception as e:  # noqa: BLE001
                    self.set_stage(key, "failed", str(e))
                    raise JobFailed(f"{dict(STAGES)[key]}: {e}")
                self.set_stage(key, "done", msg)
            done = [d for d, t in self.datasets.items() if t["state"] == "completed"]
            left = [d for d, t in self.datasets.items() if t["state"] != "completed"]
            self.status = "ready"
            self.message = ("Project package is ready for analysis." if not left else
                            f"Package ready with {len(done)} dataset(s). {len(left)} dataset(s) are not included — open Progress to retry, troubleshoot or skip them.")
            self.finished = connectors.now_iso()
            self.log("Job finished: " + self.message)
        except Cancelled:
            self.status = "cancelled"
            self.message = "Cancelled. Completed files are kept; use Retry to continue."
            self.log("Cancelled by user.")
        except JobFailed as e:
            self.status = "failed"
            self.message = str(e)
            self.log("FAILED: " + str(e))
        except Exception as e:  # noqa: BLE001
            self.status = "failed"
            self.message = f"Unexpected error: {e}"
            self.log("UNEXPECTED ERROR: " + repr(e))
        self.persist()

    # ---------------- stages
    def stage_requirements(self):
        for s in SUBDIRS:
            os.makedirs(self.path(s), exist_ok=True)
        p = self.project
        self.log(f"Project: {p['title']}")
        self.log(f"Study area: {self.region or 'New Zealand (no regional subset)'}")
        per = self.plan.get("period")
        self.log(f"Time period: {per['label'] + ' — ' + per['text'] if per else 'not set'}")
        self.log("Datasets: " + "; ".join(catalog.DATASETS[d]['name'] for d in p["datasets"]))
        self.log(f"Folder: {self.folder}")
        mb = self.store.settings.get("max_file_mb")
        self.log(f"Maximum file size per download: {mb} MB (applies to each file separately)")
        return f"{len(p['datasets'])} datasets planned"

    def _manifest(self):
        return read_json(self.path("metadata", ".manifest.json"), {})

    def _save_manifest(self, d, rec):
        m = self._manifest()
        m[d] = rec
        write_json_atomic(self.path("metadata", ".manifest.json"), m)

    def _ext(self, spec):
        return {"fdsn": "txt", "gbif": "json", "openmeteo": "json", "file_url": spec.get("format", "csv")}.get(spec["connector"], "geojson")

    def _ctx(self, d, attempt, cancel, spec, opts, limit):
        h = hashlib.sha1(json.dumps([opts.get("filters"), opts.get("period"), self.data["bbox"] if d != "regc" else None],
                                    sort_keys=True, default=str).encode()).hexdigest()[:8]
        dp = self.dplan(d)

        def progress(records=None, total=None, bytes=None, message=""):
            t = self.datasets[d]
            ok = self.tset(d, attempt, stage="downloading", state="running",
                           records=records if records is not None else t["records"], total=total if total is not None else t["total"],
                           bytes=bytes if bytes is not None else t["bytes"], message=message or t["message"],
                           measurable=(total if total is not None else t["total"]) is not None)
            if not ok:
                raise Cancelled()  # a newer attempt took over: stop this stale one
        date = datetime.now().strftime("%Y%m%d")
        return {"cancel": cancel, "progress": progress, "bbox": self.data["bbox"] if d != "regc" else None, "opts": opts, "region": self.region,
                "limit_bytes": limit, "split": bool(dp.get("split")), "allow_exceed": bool(dp.get("allow_exceed")),
                "raw_path": self.path("data", "raw", f"{d}_{date}.{self._ext(spec)}"),
                "checkpoint_dir": self.path("data", "raw", ".partial", f"{d}_{h}"), "hash": h}

    # ---- boundary (study area). Runs first and synchronously: everything else depends on it.
    def stage_boundary(self):
        d = "regc"
        spec = catalog.DATASETS[d]
        cancel = self.cancel
        self.ctl[d] = {"attempt": 1, "cancel": cancel, "event": threading.Event(), "thread": threading.current_thread()}
        self.tset(d, 1, state="running", stage="downloading", message="downloading study-area boundaries")
        src = connectors.make_source(spec)
        ver = None
        for attempt in range(1, 4):
            self.check_cancel()
            try:
                ver = src.verify(bbox=None, cancel=cancel)
                if ver["status"] != "verified":
                    raise JobFailed("Boundary layer failed verification: " + "; ".join(c["detail"] for c in ver["checks"] if not c["ok"]))
                self.data["verification"][d] = ver
                ctx = self._ctx(d, 1, cancel, spec, {"filters": {}}, None)
                rec = src.download(ctx)
                break
            except (Cancelled, JobFailed):
                raise
            except Exception as e:  # noqa: BLE001
                self.log(f"Boundary download attempt {attempt} failed: {e}")
                if attempt == 3:
                    raise JobFailed(f"Could not download the study-area boundaries after 3 tries: {e}")
                time.sleep(2 * attempt)
        rec.update({"retrieved_at": connectors.now_iso(), "bbox": None})
        self.data["downloads"][d] = rec
        fc = src.load_fc(rec["raw_files"], self.path("data", "raw"))
        name_field = ver.get("name_field") or next((f for f in (fc["features"][0].get("properties") or {}) if re.search("NAME$", f, re.I)), None)
        if not name_field:
            raise JobFailed("Could not identify the region-name field in the boundary layer.")
        self.data["name_field"] = name_field
        self._regc_fc = fc
        allb = [b for b in (quality.bbox_of_feature(f) for f in fc["features"] if f.get("geometry")) if b]
        self.data["study_bbox"] = [min(b[0] for b in allb), min(b[1] for b in allb), max(b[2] for b in allb), max(b[3] for b in allb)]
        self.data["bbox"] = None
        msg = "using whole New Zealand"
        if self.region:
            want = quality.norm_name(self.region)
            feat = next((f for f in fc["features"] if quality.norm_name((f.get("properties") or {}).get(name_field)) in (want, want + "region")), None)
            if not feat:
                names = sorted(str((f.get("properties") or {}).get(name_field)) for f in fc["features"])
                raise JobFailed(f"Region '{self.region}' not found in boundary layer. Available: {', '.join(names)}")
            self.data["region_feature_name"] = feat["properties"][name_field]
            self.data["bbox"] = [round(v, 5) for v in quality.bbox_of_feature(feat)]
            self.data["study_bbox"] = self.data["bbox"]
            write_json_atomic(self.path("data", "reference", "study_area.geojson"), {"type": "FeatureCollection", "features": [feat]})
            msg = f"study area '{self.data['region_feature_name']}' bbox {self.data['bbox']}"
        self._regions = quality.prep_regions(fc, name_field)
        sel = self.data.get("region_feature_name")
        for f in fc["features"]:
            f["properties"]["is_study_area"] = (sel is None) or (f["properties"].get(name_field) == sel)
        out = "regc_working.geojson"
        with open(self.path("data", "processed", out), "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "name": d, "features": fc["features"]}, fh, separators=(",", ":"))
        self.data["working"][d] = out
        self.data["inspections"][d] = quality.inspect_fc(fc, set())
        self.data["fields"][d] = self.data["inspections"][d].get("fields", [])
        written, skipped = exports.export_dataset(self.path("exports", d), d, fc, ["geojson"], None, "EPSG:4326 (WGS84)")
        self.data["exports"][d] = {"written": written, "skipped": skipped}
        self.tset(d, 1, state="completed", stage="completed", message="study-area boundaries ready", records=len(fc["features"]), total=len(fc["features"]),
                  validated=True, processed=out, output=rec["raw_files"][0]["file"], bytes=sum(f["bytes"] for f in rec["raw_files"]), exports=written)
        self.log("Boundary stage: " + msg)
        return msg

    # ---- datasets: independent tasks
    def stage_download(self):
        todo = [d for d in self.project["datasets"] if d != "regc"]
        pending = list(todo)
        while True:
            self.check_cancel()
            with self.lock:
                running = [d for d in todo if self.datasets[d]["state"] in ACTIVE]
                waiting = [d for d in todo if self.datasets[d]["state"] == "waiting_input"]
                unfinished = [d for d in todo if self.datasets[d]["state"] not in TERMINAL]
            # waiting tasks don't hold a slot: other datasets keep going while they wait for the user
            while pending and len(running) < MAX_PARALLEL:
                d = pending.pop(0)
                self.task_start(d, auto=True)
                running.append(d)
            if not unfinished and not pending:
                break
            if not pending and not running and waiting and len(waiting) == len(unfinished):
                # Everything that can run has finished; the rest only need YOUR decision. Don't hold the whole package hostage:
                # finish with what is ready. When you answer, those datasets complete and the package refreshes itself.
                waited = getattr(self, "_idle_since", None) or time.time()
                self._idle_since = waited
                if time.time() - waited > 6:
                    self.log(f"{len(waiting)} dataset(s) are waiting for your decision; finishing the package with the rest (it updates when you answer).")
                    break
            else:
                self._idle_since = None
            self.status = "running"
            time.sleep(0.4)
        ok = [d for d in todo if self.datasets[d]["state"] == "completed"]
        bad = [d for d in todo if self.datasets[d]["state"] != "completed"]
        self._idle_since = None
        self.project["datasets"] = ["regc"] + ok
        if not ok and todo:
            raise JobFailed("None of the datasets could be downloaded. Open Progress to troubleshoot each one.")
        return f"{len(ok)} of {len(todo)} dataset(s) downloaded and prepared" + (f"; {len(bad)} need attention" if bad else "")

    def task_start(self, d, auto=False, force=False):
        """Start (or restart) a dataset task. Refuses duplicates: a healthy running task is never started twice."""
        with self.lock:
            c = self.ctl.get(d)
            t = self.datasets[d]
            if c and c["thread"].is_alive() and t["state"] in ACTIVE | {"waiting_input"} and not force and not t.get("stalled"):
                return False
            if c:
                c["cancel"].set()  # retire any older attempt
            attempt = (c["attempt"] if c else 0) + 1
            cancel = threading.Event()
            th = threading.Thread(target=self._run_task, args=(d, attempt, cancel), daemon=True)
            self.ctl[d] = {"attempt": attempt, "cancel": cancel, "event": threading.Event(), "thread": th}
            t.update(attempt=attempt, stalled=False, decision=None, error=None, diagnosis=[], state="running", status="running", stage="searching",
                     message="Starting…", last_activity=connectors.now_iso(), last_activity_ts=time.time())
        th.start()
        return True

    def _run_task(self, d, attempt, cancel):
        try:
            self._task_body(d, attempt, cancel)
        except Cancelled:
            if self.current(d, attempt) and self.datasets[d]["state"] not in TERMINAL:
                self.tset(d, attempt, state="cancelled", stage="cancelled", message="Cancelled")
        except TaskSkip as e:
            self.tset(d, attempt, state="skipped", stage="skipped", message=str(e), decision=None)
            self.log(f"{d}: skipped — {e}")
        except Exception as e:  # noqa: BLE001
            self._fail(d, attempt, e)
        finally:
            if self.current(d, attempt):
                self.persist()
                if self.status in ("ready", "failed") and self.datasets[d]["state"] in TERMINAL:
                    threading.Thread(target=self.refresh_package, daemon=True).start()

    def _transient(self, e):
        if isinstance(e, NetError):
            return e.status is None or e.status in (429, 500, 502, 503, 504)
        return isinstance(e, (TimeoutError, ConnectionError, OSError))

    def _sleep(self, d, attempt, cancel, secs, msg):
        end = time.time() + secs
        while time.time() < end:
            if cancel.is_set() or not self.current(d, attempt):
                raise Cancelled()
            self.tset(d, attempt, message=f"{msg} ({int(end - time.time())}s)")
            time.sleep(0.5)

    def _task_body(self, d, attempt, cancel):
        auto = 0
        while True:
            try:
                return self._pipeline(d, attempt, cancel)
            except (Cancelled, TaskSkip):
                raise
            except Exception as e:  # noqa: BLE001
                if self._transient(e) and auto < MAX_AUTO_RETRIES:
                    auto += 1
                    self.log(f"{d}: temporary problem ({_short(e)}) — automatic retry {auto} of {MAX_AUTO_RETRIES}")
                    self.tset(d, attempt, state="retrying", stage="searching", auto_retries=auto,
                              message=f"Temporary problem: {_short(e, 120)}. Retrying automatically ({auto} of {MAX_AUTO_RETRIES})")
                    self._sleep(d, attempt, cancel, 3 * auto, f"Retry {auto} of {MAX_AUTO_RETRIES} starting")
                    continue
                self._fail(d, attempt, e, auto)
                return

    def _fail(self, d, attempt, e, auto=0):
        text = _short(e, 400)
        fake = {"error": text, "checks": [{"name": "Task", "ok": False, "detail": text}]}
        diag = troubleshoot._explain(catalog.DATASETS[d], fake)
        if auto:
            diag = [f"It was retried automatically {auto} time(s) and still failed."] + diag
        self.tset(d, attempt, state="failed", stage="failed", error=text, diagnosis=diag, message="Failed — see the options below", decision=None)
        self.log(f"{d}: FAILED — {text}")

    # ---- decisions (the task thread pauses here until the user answers; progress so far is kept)
    def _ask(self, d, attempt, cancel, decision):
        c = self.ctl[d]
        c["event"].clear()
        decision["dataset"] = d
        self.tset(d, attempt, state="waiting_input", decision=decision, message=decision["title"])
        self.log(f"{d}: waiting for your decision — {decision['title']}")
        self.persist()
        while not c["event"].is_set():
            if cancel.is_set() or not self.current(d, attempt):
                raise Cancelled()
            time.sleep(0.3)
        self.tset(d, attempt, state="running", decision=None, message="Continuing with your choice…")

    def decide(self, d, option, params=None):
        """Apply the user's choice to the plan, then wake the paused task (or start a new attempt if none is paused)."""
        params = params or {}
        t = self.datasets[d]
        dec = t.get("decision")
        if dec and option not in [o["id"] for o in dec["options"]]:
            raise ValueError("That option is not available for this question.")
        dp = self.dplan(d)
        f = dp.setdefault("filters", {})
        if option == "skip":
            dp["skip"] = True
        elif option == "allow":
            dp["allow_exceed"] = True
            f["on_exceed"] = "all" if f.get("max_records") else f.get("on_exceed")
        elif option == "split":
            dp["split"] = True
        elif option in ("first_n", "reduce"):
            n = int(params.get("n") or f.get("max_records") or 0)
            if n < 1:
                raise ValueError("Enter how many records to keep (a whole number of 1 or more).")
            f["max_records"], f["on_exceed"] = n, "first_n"
        elif option == "all":
            f["on_exceed"] = "all"
        elif option == "filter":
            newf = params.get("filters") or {}
            f.update({k: v for k, v in newf.items()})
            if "max_records" in newf:
                f["on_exceed"] = "ask"
            for k in ("allow_exceed", "split"):
                dp.pop(k, None)
        elif option == "use_available":
            dp["accept_gap"] = True
        elif option in ("wait", "alternative"):
            pass
        self.log(f"{d}: you chose '{option}'" + (f" {params}" if params else ""))
        if option == "wait":
            self.tset(d, None, message="Waiting a little longer, as you chose", stalled=False, decision=None)
            return
        if option == "alternative":
            return  # the page opens Troubleshoot; the task stays paused until another choice is made
        c = self.ctl.get(d)
        if c and c["thread"].is_alive() and t["state"] == "waiting_input":
            c["event"].set()
        else:
            self.task_start(d, force=True)

    def task_retry(self, d):
        t = self.datasets[d]
        dp = self.dplan(d)
        dp.pop("skip", None)
        c = self.ctl.get(d)
        healthy = c and c["thread"].is_alive() and t["state"] in ACTIVE | {"waiting_input"} and not t.get("stalled")
        if healthy:
            return False
        self.log(f"{d}: retry requested — completed pieces (checkpoints, checksummed files) are reused")
        return self.task_start(d, force=True)

    def task_cancel(self, d):
        c = self.ctl.get(d)
        if c:
            c["cancel"].set()
        if self.datasets[d]["state"] not in TERMINAL:
            self.ds(d, state="cancelled", stage="cancelled", message="Cancelled by you", decision=None)
        self.log(f"{d}: cancelled by you")

    def task_skip(self, d):
        self.dplan(d)["skip"] = True
        c = self.ctl.get(d)
        if c:
            c["cancel"].set()
        self.ds(d, state="skipped", stage="skipped", message="Skipped at your request — the other datasets continue", decision=None)
        self.log(f"{d}: skipped by you")

    def set_filters(self, d, filters, formats=None):
        dp = self.dplan(d)
        dp["filters"] = {**(dp.get("filters") or {}), **(filters or {})}
        if formats is not None:
            dp["formats"] = formats
        dp.pop("skip", None)

    # ---- the per-dataset pipeline
    def _pipeline(self, d, attempt, cancel):
        spec = catalog.DATASETS[d]
        cp = connectors.caps(spec)
        src = connectors.make_source(spec)
        while True:
            dp = self.dplan(d)
            if dp.get("skip"):
                raise TaskSkip("Skipped at your request")
            opts = self.opts(d)
            f = opts["filters"]
            limit = self.limit_bytes()
            self.tset(d, attempt, state="running", stage="searching", message="Checking the source against your filters and time period…",
                      measurable=False, decision=None)
            ver = src.verify(bbox=self.data["bbox"], cancel=cancel, opts=opts)
            self.data["verification"][d] = ver
            self.tset(d, attempt, stage="filtering", est_bytes=ver.get("est_bytes"), total=ver.get("count"),
                      message=self._count_msg(ver), coverage=coverage.info(spec, self.plan.get("period"), ver))
            cov = self.datasets[d]["coverage"]
            failed = [c for c in ver["checks"] if not c["ok"]]
            paging = [c for c in failed if c["name"].startswith("Within search-API paging limit")]
            empty = ver.get("count") == 0 or any(c["name"].startswith(("Record count", "Georeferenced NZ records", "Locations in the study area", "Events returned"))
                                                 for c in failed)
            if paging:
                self._ask(d, attempt, cancel, self._decision_record_limit(d, spec, cp, ver.get("count"), "the GBIF search service can't hand over more than 100,000 records at a time"))
                continue
            if cov["status"] in ("gap", "partial") and not dp.get("accept_gap"):
                self._ask(d, attempt, cancel, self._decision_gap(d, spec, cov))
                continue
            if empty and ver.get("count") in (0, None):
                why = cov["note"] if cov["status"] in ("gap", "partial") else "No records match this area, time period and filters."
                raise TaskSkip(why + " It was left out of this package; widen the filters or choose New Zealand-wide to include it.")
            if failed and not empty:
                raise TaskFailed("; ".join(f"{c['name']}: {c['detail']}" for c in failed))
            n = ver.get("count")
            maxrec = f.get("max_records")
            if maxrec and f.get("on_exceed", "ask") == "ask":
                if n is not None and n > int(maxrec):
                    self._ask(d, attempt, cancel, self._decision_record_limit(d, spec, cp, n, f"you set a limit of {int(maxrec):,} records for this dataset"))
                    continue
                if n is None:
                    self._ask(d, attempt, cancel, self._decision_record_unknown(d, spec, int(maxrec)))
                    continue
            est = ver.get("est_bytes")
            if limit and est and est > limit and not dp.get("allow_exceed") and not dp.get("split"):
                self._ask(d, attempt, cancel, self._decision_size(d, spec, cp, est, limit, actual=False, exact=bool(ver.get("est_note", "").startswith("Exact"))))
                continue
            # ---- download
            man = self._manifest().get(d)
            ctx = self._ctx(d, attempt, cancel, spec, opts, limit)
            reuse = man and man.get("hash") == ctx["hash"] and all(os.path.exists(self.path("data", "raw", x["file"])) and
                                                                    connectors.sha256_file(self.path("data", "raw", x["file"])) == x["sha256"]
                                                                    for x in man["raw_files"])
            if reuse:
                rec = man
                self.log(f"{d}: already downloaded with the same filters; checksum matched — reusing it")
                self.tset(d, attempt, stage="downloading", message="Reusing an earlier download (checksum matched)", records=man["records"], total=man["records"],
                          bytes=sum(x["bytes"] for x in man["raw_files"]), measurable=True)
            else:
                self.tset(d, attempt, stage="downloading", message="Starting download…", bytes=0, records=None)
                try:
                    rec = src.download(ctx)
                except SizeExceeded as e:
                    self._ask(d, attempt, cancel, self._decision_size(d, spec, cp, e.size, e.limit, actual=True, exact=True, known_in_advance=e.known_in_advance))
                    continue
                except connectors.RecordLimitError as e:
                    self._ask(d, attempt, cancel, self._decision_record_limit(d, spec, cp, e.total, e.reason))
                    continue
                rec.update({"retrieved_at": connectors.now_iso(), "bbox": self.data["bbox"], "hash": ctx["hash"]})
                self._save_manifest(d, rec)
            self.data["downloads"][d] = rec
            nb = sum(x["bytes"] for x in rec["raw_files"])
            self.tset(d, attempt, stage="converting", message=f"Downloaded {rec['records']:,} records ({nb / 1e6:.2f} MB). Checking and converting…", records=rec["records"],
                      total=rec["records"], bytes=nb, output=rec["raw_files"][0]["file"], measurable=True,
                      warnings=list(rec.get("warnings", [])))
            self._process(d, attempt, cancel, spec, src, rec)
            return

    def _count_msg(self, ver):
        n, b = ver.get("count"), ver.get("est_bytes")
        bits = [f"{n:,} records" if n is not None else "record count unknown until download"]
        bits.append(f"≈{b / 1e6:.2f} MB" if b else "size unknown")
        return "After your filters: " + ", ".join(bits)

    # ---- decision builders
    def _decision_size(self, d, spec, cp, size, limit, actual, exact, known_in_advance=False):
        opts = [{"id": "filter", "label": "Apply more filters", "needs": "filters"}]
        if cp.get("server_limit"):
            opts.append({"id": "reduce", "label": "Keep only the first N records", "needs": "number", "default": 10000})
        if cp.get("split"):
            opts.append({"id": "split", "label": f"Split into files of at most {limit / 1e6:.0f} MB"})
        opts += [{"id": "skip", "label": "Skip this dataset"}, {"id": "allow", "label": "Allow this one file to exceed the limit"}]
        how = ("The server reported this size before downloading." if known_in_advance else
               "The download reached this size while it was running, so it was paused." if actual else "This is an estimate from a small sample and may be off.")
        extra = "" if cp.get("split") else " This source cannot be split into several files."
        if not cp.get("server_limit"):
            extra += " This source cannot return just the first N records."
        return {"kind": "size_limit", "title": "This file is over your per-file size limit",
                "message": f"{spec['name']}: {size / 1e6:.0f} MB, but your limit is {limit / 1e6:.0f} MB per file. {how}{extra} How would you like to continue?",
                "options": opts}

    def _decision_record_limit(self, d, spec, cp, n, reason):
        opts = [{"id": "filter", "label": "Apply more filters", "needs": "filters"}]
        if cp.get("server_limit") or spec["connector"] == "fdsn":
            opts.append({"id": "first_n", "label": "Keep only the first N records", "needs": "number", "default": 100000 if spec["connector"] == "gbif" else 10000})
        opts.append({"id": "skip", "label": "Skip this dataset"})
        if spec["connector"] != "gbif":
            opts.append({"id": "all", "label": "Download all of them anyway"})
        return {"kind": "record_limit", "title": "More records than your limit allows",
                "message": f"{spec['name']}: {n:,} records match, but {reason}. Choose how to reduce it — nothing is dropped unless you say so. "
                           "“First N” keeps the first records in the source's own order, not a random sample.", "options": opts}

    def _decision_record_unknown(self, d, spec, maxrec):
        return {"kind": "record_limit", "title": "The number of records is unknown until it downloads",
                "message": f"{spec['name']}: you set a limit of {maxrec:,} records, but this source can't say how many it will return before downloading. "
                           f"Download and keep only the newest {maxrec:,}, download everything, change the filters, or skip?",
                "options": [{"id": "first_n", "label": f"Keep the newest {maxrec:,}", "needs": "number", "default": maxrec},
                            {"id": "all", "label": "Download everything"}, {"id": "filter", "label": "Apply more filters", "needs": "filters"},
                            {"id": "skip", "label": "Skip this dataset"}]}

    def _decision_gap(self, d, spec, cov):
        per = self.plan.get("period") or {}
        opts = []
        if cov["status"] == "partial":
            opts.append({"id": "use_available", "label": "Use the dates that are available"})
        opts += [{"id": "alternative", "label": "Find an alternative dataset"}, {"id": "skip", "label": "Skip this dataset"}]
        return {"kind": "time_gap", "title": "This dataset does not fully cover your time period",
                "message": f"{spec['name']}: {cov['note']} Your chosen period is {per.get('text', 'not set')}. Nothing has been substituted — what would you like to do?",
                "options": opts}

    # ---- inspect + prepare + export for one dataset
    def _process(self, d, attempt, cancel, spec, src, rec):
        def alive():
            if cancel.is_set() or not self.current(d, attempt):
                raise Cancelled()
        ver = self.data["verification"].get(d) or {}
        fc = src.load_fc(rec["raw_files"], self.path("data", "raw"))
        alive()
        hints = {x["name"] for x in ver.get("fields", []) if x.get("type") == "esriFieldTypeDate"}
        ins = quality.inspect_fc(fc, hints)
        self.data["inspections"][d] = ins
        self.data["fields"][d] = ins.get("fields", [])
        warns = list(self.datasets[d]["warnings"]) + ins["warnings"]
        if ins["blocking"]:
            self.tset(d, attempt, warnings=warns)
            raise TaskFailed("failed validation: " + "; ".join(ins["blocking"]))
        feats = fc["features"]
        sel = self.data.get("region_feature_name")
        is_pts = ins["geometry_types"].get("Point", 0) > 0
        kept = feats
        if is_pts and self._regions:
            def prog(i, n):
                alive()
                self.tset(d, attempt, stage="converting", message=f"Tagging each point with its region: {i:,} of {n:,}", records=i, total=n, measurable=True)
            tags = quality.tag_points(feats, self._regions, prog)
            kept, excluded = [], []
            for f, t in zip(feats, tags):
                f["properties"]["calc_region"] = t
                if sel and t != sel:
                    excluded.append({"id": (f["properties"].get(ins.get("id_field") or "") or ""), "lon": (f.get("geometry") or {}).get("coordinates", ["", ""])[0],
                                     "lat": (f.get("geometry") or {}).get("coordinates", ["", ""])[1],
                                     "reason": f"inside server-side bbox of {sel} but outside its boundary polygon (or region unmatched)"})
                else:
                    kept.append(f)
            untagged = sum(1 for t in tags if t is None)
            counts = {}
            for t in tags:
                counts[t or "(outside all regions)"] = counts.get(t or "(outside all regions)", 0) + 1
            self.data["tag_stats"][d] = {"untagged": untagged, "by_region": counts, "total": len(tags), "excluded_by_clip": len(excluded)}
            if excluded:
                with open(self.path("metadata", f"exclusions_{d}.csv"), "w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, ["id", "lon", "lat", "reason"])
                    w.writeheader()
                    w.writerows(excluded)
                self.log(f"{d}: {len(excluded)} records outside the {sel} polygon left out of the working copy (listed in metadata/exclusions_{d}.csv; raw untouched)")
            if untagged and not sel:
                warns.append(f"{untagged} point records fall outside every regional-council polygon (e.g. offshore beyond 12 nm); kept, calc_region empty.")
        elif not is_pts and ins["with_geometry"]:
            warns.append("Lines/polygons are NOT clipped by this tool" + (" (server-side bounding-box subset only)" if sel else "") + "; use Clip/Pairwise Intersect in ArcGIS Pro (see analysis guide).")
        alive()
        out = f"{d}_working.geojson"
        outp = self.path("data", "processed", out)
        with open(outp, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "name": d, "features": kept}, fh, separators=(",", ":"))
        self.data["working"][d] = out
        limit = self.limit_bytes()
        if limit and os.path.getsize(outp) > limit and not self.dplan(d).get("allow_exceed"):
            warns.append(f"The working GeoJSON copy is {os.path.getsize(outp) / 1e6:.0f} MB, over your {limit / 1e6:.0f} MB per-file limit. "
                         "It is kept because the analysis steps read it; raise the limit or filter the dataset to make it smaller.")
        self.tset(d, attempt, stage="converting", message="Creating your export files…")
        formats = self.dplan(d).get("formats") or connectors.default_formats(spec)
        written, skipped = exports.export_dataset(self.path("exports", d), d, {"features": kept}, formats, limit, "EPSG:4326 (WGS84), as returned by the source/server-side reprojected",
                                                  self.dplan(d).get("allow_exceed", False))
        self.data["exports"][d] = {"written": written, "skipped": skipped}
        for s in skipped:
            warns.append(f"{s['format'].upper()} export not created: {s['reason']}.")
        self.tset(d, attempt, state="completed", stage="completed", validated=True, warnings=warns, processed=out, exports=written, skipped_exports=skipped,
                  records=len(kept), message=f"Done: {len(kept):,} records prepared; {len(written)} export file(s) created.", measurable=True)
        self.log(f"{d}: completed — {len(kept):,} records; exports: {', '.join(w['format'] for w in written) or 'none'}")

    # ---- package-level stages (use only datasets that completed)
    def _done_ids(self):
        return ["regc"] + [d for d in self.planned if d != "regc" and d in self.datasets and self.datasets[d]["state"] == "completed"]

    def stage_compat(self):
        self.project["datasets"] = self._done_ids()
        self.data["compat"] = quality.compat_matrix(self.project, self.data["inspections"], self.data["verification"], self.data["study_bbox"])
        self.data["temporal"] = quality.temporal_summary(self.data["inspections"])
        blocking = [r for r in self.data["compat"] if r["status"] == "blocking"]
        if blocking:
            self.log(f"{len(blocking)} blocking compatibility problem(s) — see the Quality tab and compatibility report.")
        return f"{len(blocking)} blocking, {sum(1 for r in self.data['compat'] if r['status'] == 'warning')} warning(s)"

    def stage_docs(self):
        package.write_all(self)
        return "README, brief, catalogue, provenance, reports, guide and StoryMap outline written"

    def stage_ready(self):
        blocking = [r for r in self.data["compat"] if r["status"] == "blocking"]
        if blocking:
            return f"Ready with {len(blocking)} blocking compatibility issue(s) — read the Quality tab before analysing."
        return "Package complete. No analysis has been performed."

    def refresh_package(self):
        """After a late retry finishes: rebuild the compatibility + documentation so the package includes the new dataset."""
        if not self._pkg_lock.acquire(blocking=False):
            return
        try:
            self.stage_compat()
            self.stage_docs()
            done = [d for d, t in self.datasets.items() if t["state"] == "completed"]
            left = [d for d, t in self.datasets.items() if t["state"] != "completed"]
            self.message = ("Project package is ready for analysis." if not left else f"Package ready with {len(done)} dataset(s). {len(left)} not included.")
            self.status = "ready"
            self.log("Package refreshed after a retry.")
            self.persist()
        except Exception as e:  # noqa: BLE001
            self.log(f"Package refresh failed: {e}")
        finally:
            self._pkg_lock.release()

    # ---- stall watchdog (called every few seconds by the JobManager)
    def check_stalls(self):
        stall = float(self.store.settings.get("stall_seconds") or 90)
        now = time.time()
        for d, t in list(self.datasets.items()):
            if t["state"] != "running" or not t.get("last_activity_ts"):
                continue
            idle = now - t["last_activity_ts"]
            if idle < stall or t.get("stalled"):
                continue
            c = self.ctl.get(d)
            if not c or not c["thread"].is_alive():
                continue
            if t["auto_retries"] < MAX_AUTO_RETRIES:
                n = t["auto_retries"] + 1
                self.log(f"{d}: no activity for {int(idle)}s — restarting automatically ({n} of {MAX_AUTO_RETRIES})")
                self.task_start(d, force=True)
                self.ds(d, auto_retries=n, state="retrying", message=f"No activity for {int(idle)}s, so it was restarted automatically ({n} of {MAX_AUTO_RETRIES}). Finished pieces are reused.")
            else:
                self.log(f"{d}: STALLED — no activity for {int(idle)}s and automatic restarts are used up")
                self.tset(d, None, quiet=True, stalled=True, message=f"Appears stalled: no activity for {int(idle)}s",
                          decision={"kind": "stalled", "dataset": d, "title": "This download appears stalled",
                                    "message": f"{t['name']} has shown no activity for {int(idle)} seconds and the automatic restarts are used up. "
                                               "It may just be a slow server. What would you like to do?",
                                    "options": [{"id": "retry", "label": "Retry now"}, {"id": "wait", "label": "Keep waiting"},
                                                {"id": "alternative", "label": "Choose another source"}, {"id": "skip", "label": "Skip this dataset"}]})


class JobManager:
    def __init__(self, store):
        self.store = store
        self.jobs = {}
        self.lock = threading.Lock()
        self._wd = None

    def start_watchdog(self):
        if self._wd:
            return

        def loop():
            while True:
                time.sleep(5)
                for j in list(self.jobs.values()):
                    try:
                        j.check_stalls()
                    except Exception:  # noqa: BLE001
                        pass
        self._wd = threading.Thread(target=loop, daemon=True)
        self._wd.start()

    def _folder(self, project, region):
        root = self.store.settings["project_root"]
        os.makedirs(root, exist_ok=True)
        base = slug(project["id"] + ("-" + region if region else "")) + "-" + datetime.now().strftime("%Y%m%d")
        folder, n = os.path.join(root, base), 1
        while os.path.exists(folder):  # never overwrite an existing project
            n += 1
            folder = os.path.join(root, f"{base}-{n}")
        return folder

    def start(self, project_id, region=None, plan=None):
        project = catalog.PROJECT_BY_ID.get(project_id)
        if not project:
            raise KeyError("unknown project")
        plan = plan or {}
        # normalise the plan: extras (user-selected extra datasets) join the project
        extras = [x for x in plan.get("extras", []) if x in catalog.DATASETS]
        proj = {**project, "datasets": list(project["datasets"]) + [x for x in extras if x not in project["datasets"]]}
        with self.lock:
            job = Job(self.store, proj, region or None, self._folder(project, region or None), plan=plan)
            os.makedirs(job.folder, exist_ok=True)
            self.jobs[job.id] = job
        job.start()
        return job

    def retry(self, job_id):
        """Resume a failed/cancelled/interrupted job: unfinished datasets restart, finished ones are kept."""
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError("unknown job")
        if job.thread and job.thread.is_alive():
            raise RuntimeError("job is still running")
        for k, s in job.stages.items():
            if s["status"] in ("failed", "running", "done") and k in ("boundary", "download", "compat", "docs", "ready", "requirements"):
                s["status"], s["message"] = "pending", ""
        for d, t in job.datasets.items():
            if t["state"] in ("failed", "cancelled", "queued", "running", "retrying", "waiting_input"):
                t.update(state="queued", status="queued", stage="queued", error=None, decision=None, stalled=False)
            if t["state"] == "completed" and d != "regc":
                t["state"] = "queued"  # re-checked cheaply: a checksum-matched download is reused, not repeated
        job.ctl = {}
        job.cancel.clear()
        job.log("Retry/resume requested — completed downloads are reused when their checksums match.")
        job.start()
        return job

    def load_existing(self):
        root = self.store.settings["project_root"]
        if not os.path.isdir(root):
            return
        for name in sorted(os.listdir(root)):
            st = read_json(os.path.join(root, name, "logs", "job_state.json"), None)
            if not st or st["id"] in self.jobs:
                continue
            project = catalog.PROJECT_BY_ID.get(st["project_id"])
            if not project:
                continue
            ds_ids = list((st.get("datasets") or {}).keys()) or project["datasets"]
            proj = {**project, "datasets": [d for d in ds_ids if d in catalog.DATASETS]}
            job = Job(self.store, proj, st.get("region"), os.path.join(root, name), st["id"], plan=st.get("plan"))
            for d, t in (st.get("datasets") or {}).items():
                if d in job.datasets:
                    t.pop("can", None)
                    job.datasets[d].update(t)
                    if job.datasets[d].get("state") in ("running", "retrying", "waiting_input", "queued"):
                        job.datasets[d].update(state="failed", status="failed", stage="failed", decision=None,
                                               message="Interrupted when the app closed — press Retry to resume.")
            job.stages = st["stages"]
            job.planned = st.get("planned") or proj["datasets"]
            job.created, job.finished = st.get("created"), st.get("finished")
            job.log_lines = st.get("log", [])
            job.data.update(st.get("data", {}))
            job.data["inspections"] = st.get("inspections", {})
            job.status = st["status"] if st["status"] in ("ready", "cancelled", "failed") else "interrupted"
            job.message = st.get("message") or ("Interrupted when the app closed. Retry to resume." if job.status == "interrupted" else "")
            self.jobs[job.id] = job
