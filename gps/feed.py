"""Verification store + refresh. A project is 'verified' only if every dataset it needs
passed live verification; otherwise it is conditional/incomplete/unverified and is kept
out of the default feed."""
import json
import os
import threading
import time
from datetime import datetime, timezone

from . import catalog, connectors
from .net import Cancelled


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


class Store:
    def __init__(self, state_dir):
        self.dir = state_dir
        self.lock = threading.RLock()
        self.verification = read_json(os.path.join(state_dir, "verification.json"), {})
        self.seen = set(read_json(os.path.join(state_dir, "seen.json"), []))
        self.settings = {"project_root": os.path.abspath(os.path.join(state_dir, "..", "projects")), "max_download_mb": 200,
                         "schedule_minutes": 0}
        self.settings.update(read_json(os.path.join(state_dir, "settings.json"), {}))
        self.refresh_status = {"state": "idle", "message": "No verification has run yet.", "done": 0, "total": 0,
                               "last_finished": None, "log": []}
        self._cancel = threading.Event()
        self._thread = None
        self._sched = None

    # ---- persistence
    def save(self):
        with self.lock:
            write_json_atomic(os.path.join(self.dir, "verification.json"), self.verification)
            write_json_atomic(os.path.join(self.dir, "seen.json"), sorted(self.seen))
            write_json_atomic(os.path.join(self.dir, "settings.json"), self.settings)

    def update_settings(self, patch):
        with self.lock:
            for k in ("project_root", "max_download_mb", "schedule_minutes"):
                if k in patch:
                    self.settings[k] = patch[k]
            self.settings["max_download_mb"] = max(0.001, float(self.settings["max_download_mb"]))
            self.settings["schedule_minutes"] = max(0, int(self.settings["schedule_minutes"]))
            self.save()

    # ---- refresh
    def _log(self, msg):
        with self.lock:
            self.refresh_status["log"].append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
            self.refresh_status["log"] = self.refresh_status["log"][-60:]
            self.refresh_status["message"] = msg

    def start_refresh(self):
        with self.lock:
            if self._thread and self._thread.is_alive():
                return False
            self.seen.update(p["id"] for p in self.feed() if p["availability"] == "verified")  # what the user has been shown
            self.save()
            self._cancel.clear()
            self._thread = threading.Thread(target=self._refresh, daemon=True)
            self._thread.start()
            return True

    def cancel_refresh(self):
        self._cancel.set()

    def _refresh(self):
        ids = []
        for p in catalog.PROJECTS:
            for d in p["datasets"]:
                if d not in ids:
                    ids.append(d)
        with self.lock:
            self.refresh_status.update({"state": "running", "done": 0, "total": len(ids), "log": []})
        self._log(f"Checking {len(ids)} dataset sources with live requests (metadata, counts and small samples only — no full downloads).")
        try:
            for i, ds in enumerate(ids):
                if self._cancel.is_set():
                    raise Cancelled()
                spec = catalog.DATASETS[ds]
                self._log(f"Verifying: {spec['name']}")
                res = connectors.make_source(spec).verify(bbox=None, cancel=self._cancel)
                with self.lock:
                    self.verification[ds] = res
                    self.refresh_status["done"] = i + 1
                    self.save()
                bad = [c for c in res["checks"] if not c["ok"]]
                self._log(f"  → {res['status']}" + (f" ({bad[0]['name']}: {bad[0]['detail']})" if bad else ""))
            with self.lock:
                self.refresh_status.update({"state": "done", "last_finished": connectors.now_iso()})
            n_ok = sum(1 for p in self.feed() if p["availability"] == "verified")
            self._log(f"Finished: {n_ok} of {len(catalog.PROJECTS)} project templates are fully verified.")
        except Cancelled:
            with self.lock:
                self.refresh_status["state"] = "cancelled"
            self._log("Refresh cancelled.")
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.refresh_status["state"] = "error"
            self._log(f"Refresh failed: {e}")

    def check_project(self, project_id):
        """Live-verify just one project's datasets (metadata, counts, small samples; no downloads)."""
        proj = catalog.PROJECT_BY_ID[project_id]
        for ds in proj["datasets"]:
            res = connectors.make_source(catalog.DATASETS[ds]).verify(bbox=None, cancel=threading.Event())
            with self.lock:
                self.verification[ds] = res
                self.save()
        with self.lock:
            return next(p for p in self.feed() if p["id"] == project_id)

    # ---- scheduler (only while this process is running)
    def start_scheduler(self):
        if self._sched:
            return

        def loop():
            last = time.time()
            while True:
                time.sleep(20)
                m = self.settings.get("schedule_minutes", 0)
                if m and time.time() - last >= m * 60:
                    last = time.time()
                    self.start_refresh()
        self._sched = threading.Thread(target=loop, daemon=True)
        self._sched.start()

    # ---- feed
    def project_status(self, p):
        res = [self.verification.get(d) for d in p["datasets"]]
        if any(r is None for r in res):
            return "unverified", ["Not yet checked — click “Refresh projects”."]
        reasons = []
        for r in res:
            for c in r["checks"]:
                if not c["ok"]:
                    reasons.append(f"{r['name']}: {c['name']} — {c['detail']}")
        if all(r["status"] == "verified" for r in res):
            return "verified", []
        if any(r["status"] == "incomplete" for r in res):
            return "incomplete", reasons
        return "conditional", reasons

    def feed(self):
        out = []
        for p in catalog.PROJECTS:
            status, reasons = self.project_status(p)
            dss, total, unknown, times = [], 0, False, []
            for d in p["datasets"]:
                r = self.verification.get(d)
                spec = catalog.DATASETS[d]
                if r:
                    times.append(r["verified_at"])
                    if r.get("est_bytes") is not None:
                        total += r["est_bytes"]
                    else:
                        unknown = True
                dss.append({"id": d, "name": spec["name"], "publisher": spec["publisher"], "role": spec["role"],
                            "landing_url": spec.get("landing_url"), "verification": r})
            out.append({**{k: p[k] for k in p if k != "needs"}, "availability": status, "reasons": reasons,
                        "dataset_details": dss, "verified_at": min(times) if times else None,
                        "est_total_bytes": total, "size_unknown": unknown or not times,
                        "free_open": status == "verified", "is_new": p["id"] not in self.seen})
        # prefer unseen first among verified
        out.sort(key=lambda x: (x["availability"] != "verified", not x["is_new"]))
        return out
