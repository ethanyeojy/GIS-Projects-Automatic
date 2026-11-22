#!/usr/bin/env python3
"""GeoProject Studio local backend + UI server (Python 3.9+, standard library only).

Run:   python3 server.py [--port 8765] [--root /path/to/projects]
Open:  http://127.0.0.1:8765
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gps import assistant, catalog, connectors, discovery, package, plan as planner, preview, quality, timeperiod, troubleshoot  # noqa: E402
from gps.feed import Store, read_json, write_json_atomic  # noqa: E402
from gps.jobs import JobManager  # noqa: E402

STORE = None
JOBS = None
TEXT_EXT = {".md", ".csv", ".json", ".txt", ".log", ".geojson"}
THEMES = ["hazards", "freshwater", "wildlife", "outdoors", "marine", "weather", "climate", "environment"]
STATIC_OK = re.compile(r"^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)?$")
_PREVIEW_CACHE = {}


def safe_join(base, rel):
    p = os.path.abspath(os.path.join(base, rel))
    if not (p == base or p.startswith(base + os.sep)):
        raise PermissionError("path escapes project folder")
    return p


def project_folder(slug):
    root = os.path.abspath(STORE.settings["project_root"])
    return safe_join(root, slug)


def job_for_folder(slug):
    f = project_folder(slug)
    return next((j for j in JOBS.jobs.values() if os.path.abspath(j.folder) == f), None)


def period_from(src):
    """Resolve {preset,start,end} (from JSON body or query) into exact dates. Raises ValueError with a plain message."""
    if isinstance(src, dict) and "preset" in src:
        return timeperiod.resolve(src.get("preset"), src.get("start"), src.get("end"))
    if isinstance(src, dict) and src.get("period"):
        p = src["period"]
        return timeperiod.resolve(p.get("preset"), p.get("start"), p.get("end"))
    return timeperiod.resolve(timeperiod.DEFAULT)


class H(BaseHTTPRequestHandler):
    server_version = "GeoProjectStudio/0.2"

    def log_message(self, fmt, *a):
        pass

    # ---- helpers
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40_000_000:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    def _guard(self, post):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self._json({"error": "bad host"}, 403)
            return False
        if post and self.headers.get("X-GPS") != "1":
            self._json({"error": "missing X-GPS header"}, 403)
            return False
        return True

    def _handle(self, method):
        if not self._guard(method == "POST"):
            return
        try:
            self._route(method)
        except PermissionError as e:
            self._json({"error": str(e)}, 403)
        except KeyError as e:
            self._json({"error": f"not found: {e}"}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _file(self, full, ctype=None, download_name=None, cache="no-store"):
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", cache)
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        with open(full, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    # ---- routing
    def _route(self, method):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        q1 = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731
        if method == "GET" and path in ("/", "/index.html"):
            return self._file(os.path.join(HERE, "static", "index.html"), "text/html; charset=utf-8")
        if method == "GET" and path.startswith("/static/"):
            rel = unquote(path[len("/static/"):])
            if not STATIC_OK.match(rel) or ".." in rel:
                raise PermissionError("bad static path")
            full = os.path.join(HERE, "static", rel)
            if not os.path.isfile(full):
                raise KeyError(rel)
            return self._file(full)
        if method == "GET" and path == "/api/state":
            return self._json({"settings": STORE.settings, "refresh": STORE.refresh_status,
                               "capabilities": {"shapely": quality.HAVE_SHAPELY, "claude_api_key": assistant.have_key()},
                               "regions": catalog.REGION_NAMES, "version": package.APP_VERSION, "themes": THEMES,
                               "periods": [{"id": k, "label": v} for k, v in timeperiod.PRESETS], "default_period": timeperiod.DEFAULT,
                               "today": timeperiod.resolve("month")["end"]})
        if method == "GET" and path == "/api/period":
            return self._json(timeperiod.resolve(q1("preset"), q1("start"), q1("end")))
        if method == "GET" and path == "/api/feed":
            per = timeperiod.resolve(q1("preset", timeperiod.DEFAULT), q1("start"), q1("end"))
            return self._json({"projects": STORE.feed(per), "refresh": STORE.refresh_status, "period": per})
        if method == "GET" and path == "/api/outlook":
            proj = catalog.PROJECT_BY_ID.get(q1("project_id"))
            if not proj:
                raise KeyError(q1("project_id"))
            per = timeperiod.resolve(q1("preset", timeperiod.DEFAULT), q1("start"), q1("end"))
            secs = catalog.storymap_sections(proj, {"period": per, "region": q1("region") or None})
            order, imgs, k = ["cover", "q1", "q2", "q3", "conclusion"], [], 0
            for im in proj["case_study"]["images"]:
                sec = "cover" if im["role"] == "cover" else order[min((k := k + 1), len(order) - 1)]
                imgs.append({"file": im["url"].replace("/1920px-", "/960px-"), "section": sec, "alt": im["alt"], "caption": im["alt"],
                             "credit": f"{im['credit']} — {im['licence']} — via Wikimedia Commons", "source_page": im["page"]})
            return self._json({"title": proj["title"], "question": proj["question"], "purpose": proj["purpose"], "sections": secs, "images": imgs, "note": "Rough outlook only: illustrations, no downloaded data yet."})
        if method == "POST" and path == "/api/refresh":
            b = self._body()
            return self._json({"started": STORE.start_refresh(period_from(b) if b else None), "refresh": STORE.refresh_status})
        if method == "POST" and path == "/api/refresh/cancel":
            STORE.cancel_refresh()
            return self._json({"ok": True})
        if method == "POST" and path == "/api/settings":
            STORE.update_settings(self._body())
            return self._json({"settings": STORE.settings})
        if method == "POST" and path == "/api/check":  # refreshes ONE project card only
            b = self._body()
            pid = b.get("project_id")
            if pid not in catalog.PROJECT_BY_ID:
                raise KeyError(pid)
            return self._json({"project": STORE.check_project(pid, period_from(b), b.get("region") or None)})
        if method == "POST" and path == "/api/troubleshoot":
            pid = self._body().get("project_id")
            if pid not in catalog.PROJECT_BY_ID:
                raise KeyError(pid)
            return self._json(troubleshoot.diagnose(pid, STORE))
        if method == "POST" and path == "/api/troubleshoot/apply":
            b = self._body()
            if b.get("dataset_id") not in catalog.DATASETS:
                raise KeyError(b.get("dataset_id"))
            STORE.use_alternative(b["dataset_id"], b.get("service_url", ""))
            return self._json({"ok": True})
        if method == "POST" and path == "/api/plan":
            b = self._body()
            proj = catalog.PROJECT_BY_ID.get(b.get("project_id"))
            if not proj:
                raise KeyError(b.get("project_id"))
            return self._json(planner.build(STORE, proj, b.get("region") or None, period_from(b)))
        if method == "POST" and path == "/api/plan/estimate":
            b = self._body()
            if b.get("dataset_id") not in catalog.DATASETS:
                raise KeyError(b.get("dataset_id"))
            return self._json(planner.estimate(STORE, b["dataset_id"], b.get("region") or None, period_from(b), b.get("filters") or {}))
        if method == "POST" and path == "/api/dataset/values":
            b = self._body()
            spec = catalog.DATASETS.get(b.get("dataset_id"))
            if not spec or spec["connector"] != "arcgis":
                raise ValueError("Category lists are only available for map-service datasets.")
            import threading
            bbox = STORE.region_bbox(b["region"]) if b.get("region") else None
            return self._json({"values": connectors.make_source(spec).distinct_values(b.get("field", ""), bbox, threading.Event())})
        if method == "POST" and path == "/api/discovery":
            b = self._body()
            proj = catalog.PROJECT_BY_ID.get(b.get("project_id"))
            if not proj:
                raise KeyError(b.get("project_id"))
            import threading
            extra = [x for x in b.get("have", []) if x in catalog.DATASETS]
            proj = {**proj, "datasets": list(proj["datasets"]) + [x for x in extra if x not in proj["datasets"]]}
            return self._json(discovery.find(STORE, proj, b.get("query", ""), b.get("region") or None, period_from(b), b.get("mode", "search"), threading.Event()))
        if method == "POST" and path == "/api/discovery/add":
            ids = discovery.register(STORE, self._body().get("ids", []))
            out = []
            for d in ids:
                s = catalog.DATASETS[d]
                out.append({"id": d, "name": s["name"], "publisher": s["publisher"], "connector": s["connector"]})
            return self._json({"datasets": out})
        if method == "POST" and path == "/api/start":
            b = self._body()
            plan = b.get("plan") or {}
            per = period_from(b)
            extras = []
            for x in plan.get("extras", []):
                if x in catalog.DATASETS:
                    extras.append(x)
            job = JOBS.start(b["project_id"], b.get("region") or None, {"period": per, "datasets": plan.get("datasets") or {}, "extras": extras})
            return self._json({"job_id": job.id})
        if method == "GET" and path == "/api/jobs":
            return self._json({"jobs": [{k: j.snapshot()[k] for k in ("id", "title", "region", "status", "created", "folder", "stages_done", "stages_total", "project_id")}
                                        for j in sorted(JOBS.jobs.values(), key=lambda j: j.created, reverse=True)]})
        m = re.fullmatch(r"/api/jobs/([a-f0-9]+)/task/([A-Za-z0-9_\-]+)/(retry|cancel|skip|decide|filters|diagnose|use)", path)
        if m and method == "POST":
            job = JOBS.jobs.get(m.group(1))
            if not job or m.group(2) not in job.datasets:
                raise KeyError("task")
            d, act, b = m.group(2), m.group(3), self._body()
            if act == "retry":
                started = job.task_retry(d)
                return self._json({"started": started, "message": "Restarted." if started else "It is already running normally — use Refresh status, or wait a little."})
            if act == "cancel":
                job.task_cancel(d)
            elif act == "skip":
                job.task_skip(d)
            elif act == "decide":
                job.decide(d, b.get("option", ""), b.get("params"))
            elif act == "filters":
                job.set_filters(d, b.get("filters") or {}, b.get("formats"))
                job.task_retry(d)
            elif act == "use":
                STORE.use_alternative(d, b.get("service_url", ""))
                job.task_retry(d)
            elif act == "diagnose":
                return self._json(troubleshoot.diagnose_one(d, STORE, bbox=job.data.get("bbox")))
            return self._json({"ok": True, "job": job.snapshot()})
        m = re.fullmatch(r"/api/jobs/([a-f0-9]+)(/(cancel|retry))?", path)
        if m:
            job = JOBS.jobs.get(m.group(1))
            if not job:
                raise KeyError("job")
            act = m.group(3)
            if method == "POST" and act == "cancel":
                job.cancel.set()
                for d in list(job.datasets):
                    c = job.ctl.get(d)
                    if c:
                        c["cancel"].set()
            elif method == "POST" and act == "retry":
                JOBS.retry(job.id)
            return self._json(job.snapshot())  # reading status never restarts or duplicates anything
        m = re.fullmatch(r"/api/projects/([^/]+)/(tree|file|img|dl|zip|layer|table|datasets|storymap|storymap/versions|storymap/restore|storymap/image)", path)
        if m:
            return self._project_route(method, unquote(m.group(1)), m.group(2), qs)
        if method == "POST" and path == "/api/assistant":
            b = self._body()
            job = JOBS.jobs.get(b.get("job_id") or "")
            msg = b.get("message", "")
            if re.search(r"\b(missing|find|look for|search|need|gap|gaps|more)\b.*\b(data|dataset|datasets)\b|\bdata(set)?s?\b.*\b(missing|gap|gaps)\b", msg, re.I) and b.get("project_id") in catalog.PROJECT_BY_ID:
                import threading
                proj = catalog.PROJECT_BY_ID[b["project_id"]]
                found = discovery.find(STORE, proj, "" if re.search(r"gap", msg, re.I) else msg, b.get("region") or None, period_from(b),
                                       "gaps" if re.search(r"gap|missing", msg, re.I) else "search", threading.Event())
                n = len(found["candidates"])
                return self._json({"reply": (f"I searched {', '.join(found['searched'])} for “{proj['title']}” and found {n} candidate dataset(s). "
                                             "Review them below and tick the ones you want — nothing is downloaded until you start the download. "
                                             + ("; ".join(f"gap: {g['label']}" for g in found['gaps'][:4]) if found['gaps'] else "")), "mode": "dataset search (no AI)", "discovery": found})
            return self._json(assistant.respond(msg, job, b.get("section")))
        raise KeyError(path)

    # ---- per-project files, downloads, previews, story
    def _project_route(self, method, slug, what, qs):
        folder = project_folder(slug)
        if not os.path.isdir(folder):
            raise KeyError(slug)
        q1 = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731
        job = job_for_folder(slug)
        if what == "tree":
            out = []
            for dp, dn, fn in os.walk(folder):
                dn[:] = [d for d in dn if d != ".partial"]
                for f in fn:
                    full = os.path.join(dp, f)
                    out.append({"path": os.path.relpath(full, folder).replace(os.sep, "/"), "bytes": os.path.getsize(full)})
            return self._json({"files": sorted(out, key=lambda x: x["path"]), "folder": folder})
        if what == "datasets":
            if not job:
                return self._json({"datasets": []})
            items = []
            for d, t in job.datasets.items():
                files = []
                dl = job.data["downloads"].get(d) or {}
                for rf in dl.get("raw_files", []):
                    files.append({"label": "Original download (unchanged)", "format": os.path.splitext(rf["file"])[1].lstrip(".").upper() or "FILE", "path": "data/raw/" + rf["file"],
                                  "bytes": rf["bytes"], "note": "Exactly as the source delivered it."})
                if job.data["working"].get(d):
                    p = "data/processed/" + job.data["working"][d]
                    if os.path.exists(os.path.join(folder, p)):
                        files.append({"label": "Working copy (GeoJSON, WGS84 EPSG:4326)", "format": "GEOJSON", "path": p, "bytes": os.path.getsize(os.path.join(folder, p)),
                                      "note": "Cleaned copy used by the analysis guide; region tagged where applicable."})
                for e in (job.data["exports"].get(d) or {}).get("written", []):
                    files.append({"label": e["label"], "format": e["format"].upper(), "path": e["file"], "bytes": e["bytes"], "note": f"{e['records']:,} records · {e['crs']}"})
                geom = (job.data["inspections"].get(d) or {}).get("with_geometry", 0)
                items.append({"id": d, "name": t["name"], "publisher": t["publisher"], "state": t["state"], "records": t.get("records"), "files": files,
                              "has_geometry": bool(geom), "geometry_types": (job.data["inspections"].get(d) or {}).get("geometry_types", {}),
                              "skipped_exports": (job.data["exports"].get(d) or {}).get("skipped", [])})
            return self._json({"datasets": items})
        if what == "layer":
            d = q1("ds", "")
            fname = job.data["working"].get(d) if job else None
            if not fname:
                raise KeyError(f"layer {d}")
            full = safe_join(os.path.join(folder, "data", "processed"), fname)
            key = (full, os.path.getmtime(full))
            if key not in _PREVIEW_CACHE:
                _PREVIEW_CACHE.clear()
                _PREVIEW_CACHE[key] = preview.make_preview(full)
            return self._json(_PREVIEW_CACHE[key])
        if what == "table":
            d = q1("ds", "")
            fname = job.data["working"].get(d) if job else None
            if not fname:
                raise KeyError(f"table {d}")
            return self._json(preview.table_preview(safe_join(os.path.join(folder, "data", "processed"), fname)))
        if what == "file":
            full = safe_join(folder, qs.get("path", [""])[0])
            ext = os.path.splitext(full)[1].lower()
            size = os.path.getsize(full)
            if ext in TEXT_EXT and size <= 400_000:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    return self._json({"path": qs["path"][0], "text": f.read(), "bytes": size})
            return self._json({"path": qs["path"][0], "text": None, "bytes": size, "note": "Not previewed (binary or > 400 kB). Use the Download button."})
        if what == "dl":  # download any one file as an attachment
            full = safe_join(folder, qs.get("path", [""])[0])
            if not os.path.isfile(full) or ".partial" in full.split(os.sep):
                raise KeyError("file")
            return self._file(full, None, os.path.basename(full))
        if what == "img":
            full = safe_join(os.path.join(folder, "images"), os.path.relpath(safe_join(folder, qs.get("path", [""])[0]), os.path.join(folder, "images")))
            ext = os.path.splitext(full)[1].lower()
            ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(ext)
            if not ctype or not os.path.isfile(full):
                raise KeyError("image")
            return self._file(full, ctype, None, "private, max-age=3600")
        if what == "zip":
            scope, ds = q1("scope", "project"), q1("ds")
            tmp = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
            base = os.path.basename(folder)
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                if scope == "datasets" and job:
                    ids = [ds] if ds else [d for d, t in job.datasets.items() if t["state"] == "completed"]
                    for d in ids:
                        rels = [("raw/" + rf["file"], "data/raw/" + rf["file"]) for rf in (job.data["downloads"].get(d) or {}).get("raw_files", [])]
                        if job.data["working"].get(d):
                            rels.append(("working/" + job.data["working"][d], "data/processed/" + job.data["working"][d]))
                        rels += [("exports/" + os.path.basename(e["file"]), e["file"]) for e in (job.data["exports"].get(d) or {}).get("written", [])]
                        for arc, rel in rels:
                            full = os.path.join(folder, rel)
                            if os.path.isfile(full):
                                z.write(full, f"{base}_datasets/{d}/{arc}")
                    if os.path.isfile(os.path.join(folder, "metadata", "export_manifest.csv")):
                        z.write(os.path.join(folder, "metadata", "export_manifest.csv"), f"{base}_datasets/export_manifest.csv")
                else:
                    for dp, dn, fn in os.walk(folder):
                        dn[:] = [x for x in dn if x != ".partial"]
                        for f in fn:
                            full = os.path.join(dp, f)
                            z.write(full, os.path.join(base, os.path.relpath(full, folder)))
            size = tmp.tell()
            tmp.seek(0)
            name = f"{base}_{ds or ('datasets' if scope == 'datasets' else 'project')}.zip"
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            shutil.copyfileobj(tmp, self.wfile, 1 << 20)
            tmp.close()
            return
        op = os.path.join(folder, "storymap", "outline.json")
        vdir = os.path.join(folder, "storymap", "versions")

        def save_outline(new, note):
            os.makedirs(vdir, exist_ok=True)
            if os.path.exists(op):
                cur = read_json(op, None)
                n = len(os.listdir(vdir)) + 1
                write_json_atomic(os.path.join(vdir, f"v{n:04d}.json"), {"saved_at": connectors.now_iso(), "note": note, "outline": cur})
            write_json_atomic(op, new)
            with open(os.path.join(folder, "storymap", "outline.md"), "w", encoding="utf-8") as f:
                f.write(package.render_outline_md(new))
        if what == "storymap":
            if method == "GET":
                return self._json(read_json(op, None))
            new = self._body()
            if not isinstance(new.get("sections"), list):
                raise ValueError("sections missing")
            save_outline(new, "edit")
            return self._json({"ok": True})
        if what == "storymap/versions":
            vs = []
            if os.path.isdir(vdir):
                for f in sorted(os.listdir(vdir)):
                    v = read_json(os.path.join(vdir, f), {})
                    vs.append({"id": f, "saved_at": v.get("saved_at"), "note": v.get("note")})
            return self._json({"versions": vs})
        if what == "storymap/restore":
            vid = os.path.basename(self._body()["id"])
            v = read_json(os.path.join(vdir, vid), None)
            if not v:
                raise KeyError(vid)
            save_outline(v["outline"], f"restored {vid}")
            return self._json({"ok": True, "outline": v["outline"]})
        if what == "storymap/image":
            b = self._body()
            name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(b["filename"]))[:80] or "image"
            data = base64.b64decode(b["data_base64"])
            if len(data) > 25_000_000:
                raise ValueError("image too large (25 MB max)")
            d = os.path.join(folder, "images", "originals")
            os.makedirs(d, exist_ok=True)
            base, ext = os.path.splitext(name)
            target, i = os.path.join(d, name), 1
            while os.path.exists(target):  # never overwrite an original
                i += 1
                target = os.path.join(d, f"{base}-{i}{ext}")
            with open(target, "wb") as f:
                f.write(data)
            outline = read_json(op, None)
            outline["images"].append({"file": "images/originals/" + os.path.basename(target), "section": b.get("section") or "intro",
                                      "caption": b.get("caption", ""), "credit": b.get("credit", ""), "alt": b.get("alt", "")})
            save_outline(outline, f"added image {os.path.basename(target)}")
            return self._json({"ok": True, "outline": outline})
        raise KeyError(what)


def main():
    global STORE, JOBS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", help="Folder where project folders are created (default ./projects)")
    ap.add_argument("--state", default=os.environ.get("GPS_STATE_DIR", os.path.join(HERE, "state")))
    a = ap.parse_args()
    STORE = Store(os.path.abspath(a.state))
    if a.root:
        STORE.update_settings({"project_root": os.path.abspath(a.root)})
    JOBS = JobManager(STORE)
    JOBS.load_existing()
    JOBS.start_watchdog()
    STORE.start_scheduler()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.daemon_threads = True
    print(f"GeoProject Studio on http://127.0.0.1:{a.port}  (projects: {STORE.settings['project_root']})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
