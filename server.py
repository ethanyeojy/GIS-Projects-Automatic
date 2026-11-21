#!/usr/bin/env python3
"""GeoProject Studio local backend + UI server (Python 3.9+, standard library only).

Run:   python3 server.py [--port 8765] [--root /path/to/projects]
Open:  http://127.0.0.1:8765
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gps import assistant, catalog, connectors, package, quality  # noqa: E402
from gps.feed import Store, read_json, write_json_atomic  # noqa: E402
from gps.jobs import JobManager  # noqa: E402

STORE = None
JOBS = None
TEXT_EXT = {".md", ".csv", ".json", ".txt", ".log", ".geojson"}


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


class H(BaseHTTPRequestHandler):
    server_version = "GeoProjectStudio/0.1"

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

    def do_GET(self):
        if not self._guard(False):
            return
        try:
            self._route("GET")
        except PermissionError as e:
            self._json({"error": str(e)}, 403)
        except KeyError as e:
            self._json({"error": f"not found: {e}"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        if not self._guard(True):
            return
        try:
            self._route("POST")
        except PermissionError as e:
            self._json({"error": str(e)}, 403)
        except KeyError as e:
            self._json({"error": f"not found: {e}"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ---- routing
    def _route(self, method):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        if method == "GET" and path in ("/", "/index.html"):
            with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                b = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if method == "GET" and path == "/api/state":
            return self._json({"settings": STORE.settings, "refresh": STORE.refresh_status,
                               "capabilities": {"shapely": quality.HAVE_SHAPELY, "claude_api_key": assistant.have_key()},
                               "regions": catalog.REGION_NAMES, "version": package.APP_VERSION})
        if method == "GET" and path == "/api/feed":
            return self._json({"projects": STORE.feed(), "refresh": STORE.refresh_status})
        if method == "POST" and path == "/api/refresh":
            return self._json({"started": STORE.start_refresh(), "refresh": STORE.refresh_status})
        if method == "POST" and path == "/api/check":
            pid = self._body().get("project_id")
            if pid not in catalog.PROJECT_BY_ID:
                raise KeyError(pid)
            return self._json({"project": STORE.check_project(pid)})
        if method == "POST" and path == "/api/refresh/cancel":
            STORE.cancel_refresh()
            return self._json({"ok": True})
        if method == "POST" and path == "/api/settings":
            STORE.update_settings(self._body())
            return self._json({"settings": STORE.settings})
        if method == "POST" and path == "/api/start":
            b = self._body()
            job = JOBS.start(b["project_id"], b.get("region") or None)
            return self._json({"job_id": job.id})
        if method == "GET" and path == "/api/jobs":
            return self._json({"jobs": [{k: j.snapshot()[k] for k in ("id", "title", "region", "status", "created", "folder", "stages_done", "stages_total")}
                                        for j in sorted(JOBS.jobs.values(), key=lambda j: j.created, reverse=True)]})
        m = re.fullmatch(r"/api/jobs/([a-f0-9]+)(/(cancel|retry|approve))?", path)
        if m:
            job = JOBS.jobs.get(m.group(1))
            if not job:
                raise KeyError("job")
            act = m.group(3)
            if method == "POST" and act == "cancel":
                job.cancel.set()
            elif method == "POST" and act == "approve":
                job.approve.set()
            elif method == "POST" and act == "retry":
                JOBS.retry(job.id)
            return self._json(job.snapshot())
        m = re.fullmatch(r"/api/projects/([^/]+)/(tree|file|zip|storymap|storymap/versions|storymap/restore|storymap/image)", path)
        if m:
            return self._project_route(method, unquote(m.group(1)), m.group(2), qs)
        if method == "POST" and path == "/api/assistant":
            b = self._body()
            job = JOBS.jobs.get(b.get("job_id") or "")
            return self._json(assistant.respond(b.get("message", ""), job, b.get("section")))
        raise KeyError(path)

    def _project_route(self, method, slug, what, qs):
        folder = project_folder(slug)
        if not os.path.isdir(folder):
            raise KeyError(slug)
        if what == "tree":
            out = []
            for dp, dn, fn in os.walk(folder):
                dn[:] = [d for d in dn if d != ".partial"]
                for f in fn:
                    full = os.path.join(dp, f)
                    out.append({"path": os.path.relpath(full, folder).replace(os.sep, "/"), "bytes": os.path.getsize(full)})
            return self._json({"files": sorted(out, key=lambda x: x["path"]), "folder": folder})
        if what == "file":
            full = safe_join(folder, qs.get("path", [""])[0])
            ext = os.path.splitext(full)[1].lower()
            size = os.path.getsize(full)
            if ext in TEXT_EXT and size <= 400_000:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    return self._json({"path": qs["path"][0], "text": f.read(), "bytes": size})
            return self._json({"path": qs["path"][0], "text": None, "bytes": size, "note": "Not previewed (binary or > 400 kB). Open it from the project folder."})
        if what == "zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for dp, dn, fn in os.walk(folder):
                    dn[:] = [d for d in dn if d != ".partial"]
                    for f in fn:
                        full = os.path.join(dp, f)
                        z.write(full, os.path.join(os.path.basename(folder), os.path.relpath(full, folder)))
            b = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(folder)}.zip"')
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
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
    STORE.start_scheduler()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"GeoProject Studio on http://127.0.0.1:{a.port}  (projects: {STORE.settings['project_root']})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
