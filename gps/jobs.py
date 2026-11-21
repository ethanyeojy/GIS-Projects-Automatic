"""Sourcing job: runs the 9 stages for a project, with real progress, cancel, resume and retry."""
import csv
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from . import catalog, connectors, package, quality
from .feed import write_json_atomic, read_json
from .net import Cancelled

STAGES = [("requirements", "Checking project requirements"), ("verify", "Verifying sources"),
          ("boundary", "Finding study-area boundaries"), ("download", "Downloading datasets"),
          ("inspect", "Inspecting files"), ("prepare", "Preparing data"), ("compat", "Checking compatibility"),
          ("docs", "Creating project documentation"), ("ready", "Ready for analysis")]

SUBDIRS = ["data/raw", "data/processed", "data/reference", "metadata", "workflows", "maps", "images",
           "storymap", "exports", "logs"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class JobFailed(Exception):
    pass


class Job:
    def __init__(self, store, project, region, folder, job_id=None):
        self.store = store
        self.project = project
        self.region = region
        self.folder = folder
        self.id = job_id or uuid.uuid4().hex[:10]
        self.status = "queued"  # queued running needs_approval cancelled failed ready interrupted
        self.message = ""
        self.approval = None
        self.created = connectors.now_iso()
        self.finished = None
        self.stages = {k: {"label": v, "status": "pending", "message": "", "started": None, "ended": None} for k, v in STAGES}
        self.datasets = {}
        for d in project["datasets"]:
            s = catalog.DATASETS[d]
            self.datasets[d] = {"id": d, "name": s["name"], "publisher": s["publisher"], "source_url": s.get("landing_url"),
                                "role": s["role"], "status": "queued", "bytes": 0, "records": None, "total": None,
                                "warnings": [], "output": None, "processed": None, "error": None, "message": "",
                                "validated": False}
        self.log_lines = []
        self.cancel = threading.Event()
        self.approve = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.data = {"verification": {}, "inspections": {}, "compat": [], "temporal": {}, "downloads": {}, "working": {},
                     "fields": {}, "study_bbox": None, "bbox": None, "region_feature_name": None, "tag_stats": {}, "exclusions": {}}

    # ---------------- plumbing
    def path(self, *p):
        return os.path.join(self.folder, *p)

    def log(self, msg):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        with self.lock:
            self.log_lines.append(line)
            self.log_lines = self.log_lines[-500:]
        try:
            os.makedirs(self.path("logs"), exist_ok=True)
            with open(self.path("logs", "job.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def snapshot(self):
        with self.lock:
            done = sum(1 for s in self.stages.values() if s["status"] == "done")
            return {"id": self.id, "project_id": self.project["id"], "title": self.project["title"], "region": self.region,
                    "folder": self.folder, "status": self.status, "message": self.message, "approval": self.approval,
                    "created": self.created, "finished": self.finished, "stages": self.stages,
                    "stages_done": done, "stages_total": len(STAGES), "datasets": self.datasets,
                    "log": self.log_lines[-120:], "compat": self.data["compat"], "inspections": self.data["inspections"],
                    "temporal": self.data["temporal"], "tag_stats": self.data["tag_stats"]}

    def persist(self):
        try:
            snap = self.snapshot()
            snap["data"] = {k: v for k, v in self.data.items() if k not in ("inspections",)}
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

    def ds(self, d, **kw):
        with self.lock:
            self.datasets[d].update(kw)

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ---------------- control
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancel.clear()
        self.approve.clear()
        self.status = "running"
        self.message = ""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            for key, _ in STAGES:
                self.check_cancel()
                fn = getattr(self, "stage_" + key)
                self.set_stage(key, "running")
                try:
                    msg = fn() or ""
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    self.set_stage(key, "failed", str(e))
                    raise JobFailed(f"{dict(STAGES)[key]}: {e}")
                self.set_stage(key, "done", msg)
            self.status = "ready"
            self.message = "Project package is ready for analysis."
            self.finished = connectors.now_iso()
            self.log("Job finished: ready for analysis.")
        except Cancelled:
            self.status = "cancelled"
            self.message = "Cancelled. Completed files are kept; use Retry/Resume to continue."
            for s in self.stages.values():
                if s["status"] == "running":
                    s["status"] = "pending"
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
        self.log("Datasets: " + "; ".join(catalog.DATASETS[d]['name'] for d in p["datasets"]))
        self.log(f"Folder: {self.folder}")
        self.log(f"Download size limit: {self.store.settings['max_download_mb']} MB")
        return f"{len(p['datasets'])} datasets planned"

    def stage_verify(self):
        for d in self.project["datasets"]:
            self.check_cancel()
            self.ds(d, status="verifying", message="re-checking access")
            res = connectors.make_source(catalog.DATASETS[d]).verify(bbox=None, cancel=self.cancel)
            self.data["verification"][d] = res
            self.store.verification[d] = res
            self.store.save()
            if res["status"] != "verified":
                reasons = "; ".join(f"{c['name']}: {c['detail']}" for c in res["checks"] if not c["ok"])
                self.ds(d, status="failed", error=reasons)
                raise JobFailed(f"'{res['name']}' is no longer verified ({res['status']}): {reasons}. "
                                "No substitute dataset is used automatically; ask the assistant for alternatives.")
            self.ds(d, status="verified_access", message="access re-verified")
            self.log(f"Re-verified {d}: count={res['count']} est_bytes={res['est_bytes']}")
        return "all essential sources re-verified"

    def _ctx(self, d, name, ext, bbox):
        def progress(records=None, total=None, bytes=None, message=""):
            self.ds(d, records=records if records is not None else self.datasets[d]["records"],
                    total=total if total is not None else self.datasets[d]["total"],
                    bytes=bytes if bytes is not None else self.datasets[d]["bytes"], message=message)
        date = datetime.now().strftime("%Y%m%d")
        return {"cancel": self.cancel, "progress": progress, "bbox": bbox,
                "raw_path": self.path("data", "raw", f"{name}_{date}.{ext}"),
                "checkpoint_dir": self.path("data", "raw", ".partial", name)}

    def _manifest(self):
        return read_json(self.path("metadata", ".manifest.json"), {})

    def _save_manifest(self, d, rec):
        m = self._manifest()
        m[d] = rec
        write_json_atomic(self.path("metadata", ".manifest.json"), m)

    def _download_one(self, d, bbox):
        spec = catalog.DATASETS[d]
        man = self._manifest().get(d)
        if man and man.get("bbox") == bbox and all(os.path.exists(self.path("data", "raw", f["file"])) and
                                                   connectors.sha256_file(self.path("data", "raw", f["file"])) == f["sha256"]
                                                   for f in man["raw_files"]):
            self.log(f"Resuming: {d} already downloaded and checksum-verified; skipping.")
            self.data["downloads"][d] = man
            self.ds(d, status="downloaded", output=man["raw_files"][0]["file"], records=man["records"], total=man["records"],
                    bytes=sum(f["bytes"] for f in man["raw_files"]), message="reused from earlier run (checksum matched)")
            return
        ext = {"fdsn": "txt", "gbif": "json"}.get(spec["connector"], "geojson")
        ctx = self._ctx(d, d, ext, bbox)
        self.ds(d, status="downloading", message="starting", error=None)
        last_err = None
        for attempt in range(1, 3):
            try:
                self.log(f"Downloading {d} (attempt {attempt}) …")
                rec = connectors.make_source(spec).download(ctx)
                rec.update({"retrieved_at": connectors.now_iso(), "bbox": bbox})
                self.data["downloads"][d] = rec
                self._save_manifest(d, rec)
                self.ds(d, status="downloaded", output=rec["raw_files"][0]["file"], records=rec["records"],
                        total=rec["records"], bytes=sum(f["bytes"] for f in rec["raw_files"]),
                        warnings=self.datasets[d]["warnings"] + rec.get("warnings", []), message="download complete — not yet validated")
                self.log(f"Downloaded {d}: {rec['records']} records, {sum(f['bytes'] for f in rec['raw_files'])} bytes, sha256 {rec['raw_files'][0]['sha256'][:12]}…")
                return
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.log(f"Download attempt {attempt} for {d} failed: {e}")
                self.ds(d, message=f"attempt {attempt} failed: {e}")
        self.ds(d, status="failed", error=str(last_err))
        raise JobFailed(f"download of '{spec['name']}' failed after retries: {last_err}")

    def stage_boundary(self):
        d = "regc"
        self._download_one(d, None)
        src = connectors.make_source(catalog.DATASETS[d])
        fc = src.load_fc(self.data["downloads"][d]["raw_files"], self.path("data", "raw"))
        ver = self.data["verification"][d]
        name_field = ver.get("name_field") or next((f for f in (fc["features"][0].get("properties") or {}) if re.search("NAME$", f, re.I)), None)
        if not name_field:
            raise JobFailed("Could not identify the region-name field in the boundary layer.")
        self.data["name_field"] = name_field
        self._regc_fc = fc
        allb = [quality.bbox_of_feature(f) for f in fc["features"] if f.get("geometry")]
        allb = [b for b in allb if b]
        self.data["study_bbox"] = [min(b[0] for b in allb), min(b[1] for b in allb), max(b[2] for b in allb), max(b[3] for b in allb)]
        self.data["bbox"] = None
        msg = "using whole New Zealand layer"
        if self.region:
            want = quality.norm_name(self.region)
            # Stats NZ names are "Wellington Region"; the UI offers "Wellington". Accept either form.
            feat = next((f for f in fc["features"] if quality.norm_name((f.get("properties") or {}).get(name_field)) in (want, want + "region")), None)
            if not feat:
                names = sorted(str((f.get("properties") or {}).get(name_field)) for f in fc["features"])
                raise JobFailed(f"Region '{self.region}' not found in boundary layer. Available: {', '.join(names)}")
            self.data["region_feature_name"] = feat["properties"][name_field]
            self.data["bbox"] = [round(v, 5) for v in quality.bbox_of_feature(feat)]
            self.data["study_bbox"] = self.data["bbox"]
            write_json_atomic(self.path("data", "reference", "study_area.geojson"), {"type": "FeatureCollection", "features": [feat]})
            msg = f"study area '{self.data['region_feature_name']}' bbox {self.data['bbox']}"
        self.log("Boundary stage: " + msg)
        # region-specific size/count estimates for server-side subsets
        if self.data["bbox"]:
            for dd in self.project["datasets"]:
                if dd == "regc":
                    continue
                v = connectors.make_source(catalog.DATASETS[dd]).verify(bbox=self.data["bbox"], cancel=self.cancel)
                self.data["verification"][dd] = v
                if v["status"] != "verified":
                    reasons = "; ".join(f"{c['name']}: {c['detail']}" for c in v["checks"] if not c["ok"])
                    self.ds(dd, status="failed", error=reasons)
                    raise JobFailed(f"For {self.data['region_feature_name']}, '{v['name']}' did not verify: {reasons}. Try another region or New Zealand-wide.")
                self.log(f"Regional subset check {dd}: count={v['count']} est_bytes={v['est_bytes']}")
        return msg

    def stage_download(self):
        limit = self.store.settings["max_download_mb"] * 1024 * 1024
        todo = [d for d in self.project["datasets"] if d != "regc"]
        known = sum(self.data["verification"][d]["est_bytes"] or 0 for d in todo)
        unknown = [d for d in todo if self.data["verification"][d]["est_bytes"] is None]
        if known > limit and not self.approve.is_set():
            self.status = "needs_approval"
            self.approval = {"reason": f"Estimated download ≈ {known / 1e6:.0f} MB exceeds your {limit / 1e6:.0f} MB limit "
                                       "(estimate from a small sample — may be inaccurate). Approve to continue, cancel, or restart with a region/smaller scope."}
            self.log("PAUSED for approval: " + self.approval["reason"])
            self.persist()
            while not self.approve.is_set():
                self.check_cancel()
                time.sleep(0.5)
            self.status = "running"
            self.approval = None
            self.log("Approval received; continuing.")
        if unknown:
            self.log("Size unknown before download for: " + ", ".join(unknown))
        for d in todo:
            self.check_cancel()
            self._download_one(d, self.data["bbox"])
        return f"{len(todo)} dataset(s) downloaded (not yet validated)"

    def _fc(self, d):
        if d == "regc" and getattr(self, "_regc_fc", None):
            return self._regc_fc
        src = connectors.make_source(catalog.DATASETS[d])
        return src.load_fc(self.data["downloads"][d]["raw_files"], self.path("data", "raw"))

    def stage_inspect(self):
        self._fcs = {}
        for d in self.project["datasets"]:
            self.check_cancel()
            self.ds(d, status="inspecting", message="reading file and running checks")
            fc = self._fc(d)
            ver = self.data["verification"].get(d) or {}
            hints = {f["name"] for f in ver.get("fields", []) if f.get("type") == "esriFieldTypeDate"}
            ins = quality.inspect_fc(fc, hints)
            self._fcs[d] = fc
            self.data["inspections"][d] = ins
            self.data["fields"][d] = ins.get("fields", [])
            warns = list(self.datasets[d]["warnings"]) + ins["warnings"]
            if ins["blocking"]:
                self.ds(d, status="failed_validation", warnings=warns, error="; ".join(ins["blocking"]), message="validation failed")
                raise JobFailed(f"'{d}' failed validation: {'; '.join(ins['blocking'])}")
            self.ds(d, status="validated", validated=True, warnings=warns, records=ins["records"],
                    message=f"{ins['records']} records inspected, {len(ins['warnings'])} warning(s)")
            self.log(f"Inspected {d}: {ins['records']} records, {len(ins['warnings'])} warnings")
        return "all files inspected"

    def stage_prepare(self):
        name_field = self.data["name_field"]
        regions = quality.prep_regions(self._regc_fc, name_field)
        sel = self.data.get("region_feature_name")
        for d in self.project["datasets"]:
            self.check_cancel()
            fc = self._fcs[d]
            feats = fc["features"]
            self.ds(d, message="preparing working copy")
            if d == "regc":
                for f in feats:
                    f["properties"]["is_study_area"] = (sel is None) or (f["properties"].get(name_field) == sel)
                kept = feats
            else:
                is_pts = self.data["inspections"][d]["geometry_types"].get("Point", 0) > 0
                if is_pts:
                    def prog(i, n, d=d):
                        self.ds(d, message=f"tagging regions: {i}/{n} records processed")
                    tags = quality.tag_points(feats, regions, prog)
                    kept, excluded = [], []
                    for f, t in zip(feats, tags):
                        f["properties"]["calc_region"] = t  # calculated (point-in-polygon), not original
                        if sel and t != sel:
                            excluded.append({"id": (f["properties"].get(self.data["inspections"][d].get("id_field") or "") or ""),
                                             "lon": (f.get("geometry") or {}).get("coordinates", ["", ""])[0],
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
                        self.log(f"{d}: {len(excluded)} records outside the {sel} polygon excluded from working copy (listed in metadata/exclusions_{d}.csv; raw untouched)")
                    if untagged and not sel:
                        self.ds(d, warnings=self.datasets[d]["warnings"] + [f"{untagged} point records fall outside every regional-council polygon (e.g. offshore beyond 12 nm); kept, calc_region empty."])
                else:
                    kept = feats
                    self.ds(d, warnings=self.datasets[d]["warnings"] + [
                        "Lines/polygons are NOT clipped by this tool" + (" (server-side bounding-box subset only)" if sel else "") + "; use Clip/Pairwise Intersect in ArcGIS Pro (see analysis guide)."])
            out = f"{d}_working.geojson"
            with open(self.path("data", "processed", out), "w", encoding="utf-8") as fh:
                json.dump({"type": "FeatureCollection", "name": d, "features": kept}, fh, separators=(",", ":"))
            self.data["working"][d] = out
            self.ds(d, processed=out)
            if d != "regc" and self.data["inspections"][d]["geometry_types"].get("Point", 0) > 0:
                cols = list(kept[0]["properties"].keys()) if kept else []
                with open(self.path("data", "processed", f"{d}_working.csv"), "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(["longitude", "latitude"] + cols)
                    for f in kept:
                        g = f.get("geometry") or {}
                        xy = g.get("coordinates", ["", ""]) if g.get("type") == "Point" else ["", ""]
                        w.writerow([xy[0], xy[1]] + [f["properties"].get(c, "") for c in cols])
            self.log(f"Prepared {d}: {len(kept)} features → data/processed/{out}")
        return "working copies written (raw files unchanged)"

    def stage_compat(self):
        self.data["compat"] = quality.compat_matrix(self.project, self.data["inspections"], self.data["verification"], self.data["study_bbox"])
        self.data["temporal"] = quality.temporal_summary(self.data["inspections"])
        blocking = [r for r in self.data["compat"] if r["status"] == "blocking"]
        for d in self.project["datasets"]:
            self.ds(d, message="raw file kept unchanged; working copy written; checks complete")
        if blocking:
            self.log(f"{len(blocking)} blocking compatibility problem(s) — see compatibility report.")
        return f"{len(blocking)} blocking, {sum(1 for r in self.data['compat'] if r['status'] == 'warning')} warning(s)"

    def stage_docs(self):
        package.write_all(self)
        return "README, brief, catalogue, provenance, reports, guide and StoryMap outline written"

    def stage_ready(self):
        blocking = [r for r in self.data["compat"] if r["status"] == "blocking"]
        if blocking:
            return f"Ready with {len(blocking)} blocking compatibility issue(s) — read compatibility_report.md before analysing."
        return "Package complete. No analysis has been performed."


class JobManager:
    def __init__(self, store):
        self.store = store
        self.jobs = {}
        self.lock = threading.Lock()

    def _folder(self, project, region):
        root = self.store.settings["project_root"]
        os.makedirs(root, exist_ok=True)
        base = slug(project["id"] + ("-" + region if region else "")) + "-" + datetime.now().strftime("%Y%m%d")
        folder, n = os.path.join(root, base), 1
        while os.path.exists(folder):  # never overwrite an existing project
            n += 1
            folder = os.path.join(root, f"{base}-{n}")
        return folder

    def start(self, project_id, region=None):
        project = catalog.PROJECT_BY_ID.get(project_id)
        if not project:
            raise KeyError("unknown project")
        with self.lock:
            job = Job(self.store, project, region or None, self._folder(project, region or None))
            os.makedirs(job.folder, exist_ok=True)
            self.jobs[job.id] = job
        job.start()
        return job

    def retry(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError("unknown job")
        if job.thread and job.thread.is_alive():
            raise RuntimeError("job is still running")
        for s in job.stages.values():
            if s["status"] in ("failed", "running"):
                s["status"], s["message"] = "pending", ""
            elif s["status"] == "done":
                s["status"] = "pending"  # idempotent stages re-run; downloads are reused via checksums
        for d in job.datasets.values():
            if d["status"] in ("failed", "failed_validation"):
                d.update(status="queued", error=None)
        job.log("Retry/resume requested — completed downloads will be reused if checksums match.")
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
            job = Job(self.store, project, st.get("region"), os.path.join(root, name), st["id"])
            job.stages, job.datasets = st["stages"], st["datasets"]
            job.created, job.finished = st.get("created"), st.get("finished")
            job.log_lines = st.get("log", [])
            job.data.update(st.get("data", {}))
            job.data["inspections"] = st.get("inspections", {})
            job.status = st["status"] if st["status"] in ("ready", "cancelled", "failed") else "interrupted"
            job.message = st.get("message") or ("Interrupted when the app closed. Retry to resume." if job.status == "interrupted" else "")
            self.jobs[job.id] = job
