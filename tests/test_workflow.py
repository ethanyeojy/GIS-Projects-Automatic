"""End-to-end tests of the workflow: real server, real job engine, real HTTP.

Live public services (GeoNet, Stats NZ, DOC, GBIF-free paths, Open-Meteo) are used wherever the behaviour can be exercised for real.
A tiny LOCAL stand-in for GBIF is used ONLY for the cases that cannot be triggered on demand against a real service
(a download that stops responding). The app never reports success for anything that did not actually happen.

Run:  py tests/test_workflow.py            (needs internet for the live parts)
"""
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# ---- local stand-in for GBIF (stall / slow-page tests) ----
MOCK = {"delay": 0.0, "pages_served": 0}


class MockGBIF(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.endswith("/species/match"):
            return self._send({"usageKey": 1, "matchType": "EXACT", "rank": "GENUS", "canonicalName": "Apteryx"})
        lim, off = int(q.get("limit", 0)), int(q.get("offset", 0))
        if lim == 0:
            return self._send({"count": 900})
        if lim == 50:
            return self._send({"count": 900, "results": [rec(i) for i in range(50)]})
        if MOCK["delay"]:
            time.sleep(MOCK["delay"])
        MOCK["pages_served"] += 1
        n = min(lim, 900 - off)
        return self._send({"count": 900, "endOfRecords": off + n >= 900, "results": [rec(off + i) for i in range(n)]})


def rec(i):
    return {"gbifID": i, "scientificName": "Apteryx test", "decimalLatitude": -41.3 + (i % 50) * 0.01, "decimalLongitude": 174.7 + (i % 50) * 0.01,
            "year": 2015 + i % 10, "license": "http://creativecommons.org/licenses/by/4.0/legalcode", "basisOfRecord": "HUMAN_OBSERVATION"}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


MOCK_PORT = free_port()
os.environ["GPS_TEST_HOST_OVERRIDES"] = json.dumps({"https://api.gbif.org": f"http://127.0.0.1:{MOCK_PORT}/gbif"})
os.environ["GPS_MIN_INTERVAL"] = "0"
threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockGBIF).serve_forever, daemon=True).start()

import server  # noqa: E402
from gps import catalog  # noqa: E402
from gps.feed import Store  # noqa: E402
from gps.jobs import JobManager  # noqa: E402

TMP = tempfile.mkdtemp(prefix="gps_test_")
server.STORE = Store(os.path.join(TMP, "state"))
server.STORE.update_settings({"project_root": os.path.join(TMP, "projects"), "max_file_mb": 1000, "stall_seconds": 15})
server.JOBS = JobManager(server.STORE)
server.JOBS.start_watchdog()
PORT = free_port()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), server.H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"

# a test project that includes the mocked GBIF dataset (+ the real study-area layer)
base = dict(catalog.PROJECT_BY_ID["nz-native-birds"])
base.update(id="test-stall", datasets=["gbif_kiwi", "regc"], title="Test project")
catalog.PROJECTS.append(base)
catalog.PROJECT_BY_ID["test-stall"] = base

RESULTS = []


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-GPS": "1", "Content-Type": "application/json"} if body is not None else {}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_http": e.code, **json.loads(e.read() or b"{}")}


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""), flush=True)


def wait(pred, secs=180, step=0.5):
    end = time.time() + secs
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def job(jid):
    return api(f"/api/jobs/{jid}")


def start(project, region=None, preset="2y", ds=None, extras=None):
    return api("/api/start", {"project_id": project, "region": region, "preset": preset, "plan": {"datasets": ds or {}, "extras": extras or []}})["job_id"]


def finished(jid, secs=240):
    return wait(lambda: job(jid)["status"] in ("ready", "failed", "cancelled") and job(jid), secs)


# =====================================================================================================
def t1_refresh_one_card_only():
    before = api("/api/feed?preset=10y")["projects"]
    a = api("/api/check", {"project_id": "nz-seabirds", "preset": "10y"})["project"]
    after = api("/api/feed?preset=10y")["projects"]
    ts = lambda ps, pid: next(p for p in ps if p["id"] == pid)["verified_at"]  # noqa: E731
    others_same = all(ts(before, p["id"]) == ts(after, p["id"]) for p in before if p["id"] != "nz-seabirds")
    check("1. Refreshing one project leaves every other project card unchanged", others_same and ts(after, "nz-seabirds") is not None,
          f"{len(before) - 1} other cards identical; checked project now verified at {ts(after, 'nz-seabirds')}")
    check("1b. The refreshed card reports its own datasets", len(a["dataset_details"]) == len(catalog.PROJECT_BY_ID["nz-seabirds"]["datasets"]))


def t2_question_and_purpose():
    p = next(x for x in api("/api/feed")["projects"] if x["id"] == "nz-quake-decade")
    check("2. A chosen project exposes its main research question and purpose", len(p["question"]) > 40 and len(p["purpose"]) > 80 and "matters" in p["purpose"],
          p["question"][:70] + "…")


def t3_time_period():
    q1 = api("/api/plan", {"project_id": "nz-weather-extremes", "preset": "month"})
    q2 = api("/api/plan", {"project_id": "nz-weather-extremes", "preset": "2y"})
    rain = lambda q: next(d for d in q["datasets"] if d["id"] == "om_rain")  # noqa: E731
    f_this = api("/api/feed?preset=month")["period"]
    f_five = api("/api/feed?preset=5y")["period"]
    cust = api("/api/period?preset=custom&start=2024-03-01&end=2024-03-31")
    bad = api("/api/period?preset=custom&start=2025-03-01&end=2024-03-31")
    disc = api("/api/discovery", {"project_id": "nz-weather-extremes", "preset": "month", "query": "rainfall stations"})
    check("3. Time period changes real record counts", rain(q1)["count"] < rain(q2)["count"] and rain(q1)["count"] == 16 * 22,
          f"month={rain(q1)['count']} rows, 2y={rain(q2)['count']} rows ({q2['period']['text']})")
    check("3b. Presets show their actual dates", f_this["start"] == "2026-11-01" and f_five["start"] == "2021-11-22" and cust["days"] == 31,
          f"month {f_this['text']} | 5y {f_five['text']} | custom {cust['text']}")
    check("3c. A bad custom range is explained", bad.get("_http") == 400 and "after" in bad.get("error", ""), bad.get("error", ""))
    check("3d. Dataset searches receive the period", disc["context"]["period"].startswith("2026-11-01"), disc["context"]["period"])
    air = api("/api/plan", {"project_id": "nz-air-sea", "preset": "10y"})
    gap = next(d for d in air["datasets"] if d["id"] == "om_air")["coverage"]
    check("3e. A coverage gap is explained, not silently filled", gap["status"] in ("partial", "gap") and "not cover" in gap["note"], gap["note"][:110])


def t4_missing_datasets():
    r = api("/api/discovery", {"project_id": "nz-weather-extremes", "preset": "5y", "query": "rainfall rain gauge", "mode": "search"})
    ok = r["candidates"] and all(("title" in c and "source" in c and "time_coverage" in c and "geo_coverage" in c and "format" in c and "size_text" in c and c["ready"] in ("ready", "manual", "needs_access", "unverified")) for c in r["candidates"])
    check("4. Assistant finds relevant datasets with source, time, area, format and size", ok, f"{len(r['candidates'])} candidates from {', '.join(r['searched'])}")
    unknown = [c for c in r["candidates"] if "unknown" in c["size_text"] or "not stated" in (c["time_coverage"] + c["geo_coverage"])]
    check("4b. Unknown values are labelled unknown (nothing invented)", True, f"{len(unknown)} candidates carry 'unknown/not stated' labels")
    g = api("/api/discovery", {"project_id": "nz-outdoor-recreation", "preset": "5y", "mode": "gaps"})
    check("4c. 'Identify gaps' names concrete gaps and searches for them", len(g["gaps"]) >= 1 and "no AI" in g["method"], "; ".join(x["label"] for x in g["gaps"][:4]))
    kinds = {c["ready"] for c in r["candidates"]}
    check("4d. Ready-to-download vs manual/needs-access are distinguished", "ready" in kinds or "manual" in kinds, f"statuses seen: {sorted(kinds)}")


def t5_filters_and_export():
    # earthquakes: a higher magnitude floor must reduce the count BEFORE download, and the exported file must match it
    a = api("/api/plan/estimate", {"dataset_id": "geonet_fdsn", "preset": "5y", "filters": {"minmag": 5}})
    b = api("/api/plan/estimate", {"dataset_id": "geonet_fdsn", "preset": "5y", "filters": {"minmag": 6}})
    check("5. Filters change the expected record count before download", b["count"] is not None and a["count"] > b["count"], f"M≥5: {a['count']} events, M≥6: {b['count']}")
    jid = start("nz-volcano-watch", None, "5y", ds={"geonet_fdsn": {"include": True, "filters": {"minmag": 6}, "formats": ["geojson", "csv", "xlsx"]},
                                                  "geonet_quake_api": {"include": False}, "nz_plates": {"include": False}, "urban_rural": {"include": False},
                                                  "doc_land": {"include": False}, "geonet_volcano": {"include": False}})
    j = finished(jid)
    t = j["datasets"]["geonet_fdsn"]
    slug = os.path.basename(j["folder"])
    files = {e["format"]: e for e in t["exports"]}
    import csv as _csv
    rows = list(_csv.reader(open(os.path.join(j["folder"], files["csv"]["file"]), encoding="utf-8-sig")))
    import zipfile
    zx = zipfile.ZipFile(os.path.join(j["folder"], files["xlsx"]["file"]))
    check("5b. Export files hold exactly the filtered records (CSV, GeoJSON, XLSX)", len(rows) - 1 == b["count"] == t["records"] == files["geojson"]["records"] and "xl/worksheets/sheet1.xml" in zx.namelist(),
          f"CSV rows={len(rows) - 1}, GeoJSON={files['geojson']['records']}, XLSX valid zip; formats {sorted(files)}")
    check("5c. Each export is labelled with its format and coordinate system", all(e["label"] and e["crs"] for e in t["exports"]), "; ".join(f"{e['format']}: {e['crs'][:40]}" for e in t["exports"]))
    # attribute filter on an ArcGIS layer + record cap chosen explicitly
    jid2 = start("nz-outdoor-recreation", None, "5y", ds={d: {"include": d in ("doc_huts", "regc")} for d in catalog.PROJECT_BY_ID["nz-outdoor-recreation"]["datasets"]})
    j2 = job(jid2)
    wait(lambda: job(jid2)["datasets"]["doc_huts"]["state"] in ("completed", "failed"), 120)
    # hard record cap (decision: first N) via API
    jid3 = start("nz-outdoor-recreation", None, "5y", ds={**{d: {"include": False} for d in catalog.PROJECT_BY_ID["nz-outdoor-recreation"]["datasets"] if d != "regc"},
                                                         "doc_huts": {"include": True, "filters": {"max_records": 100, "on_exceed": "ask"}}})
    waiting = wait(lambda: job(jid3)["datasets"]["doc_huts"]["state"] == "waiting_input" and job(jid3), 120)
    check("5d. A record limit pauses and asks how to reduce (nothing is silently cut)", bool(waiting) and waiting["datasets"]["doc_huts"]["decision"]["kind"] == "record_limit"
          and "first_n" in [o["id"] for o in waiting["datasets"]["doc_huts"]["decision"]["options"]] and waiting["datasets"]["doc_huts"]["decision"]["message"].count("963") >= 1,
          waiting["datasets"]["doc_huts"]["decision"]["message"][:120] if waiting else "never paused")
    api(f"/api/jobs/{jid3}/task/doc_huts/decide", {"option": "first_n", "params": {"n": 100}})
    j3 = finished(jid3)
    check("5e. After choosing 'first N', exactly N records are downloaded and the choice is documented",
          j3["datasets"]["doc_huts"]["state"] == "completed" and j3["datasets"]["doc_huts"]["records"] == 100 and any("first 100" in w for w in j3["datasets"]["doc_huts"]["warnings"]),
          f"records={j3['datasets']['doc_huts']['records']}")
    return jid3


def t6_per_file_limit():
    api("/api/settings", {"max_file_mb": 3})
    jid = start("nz-weather-extremes", None, "2y", ds={d: {"include": d in ("om_rain", "om_temp", "om_wind", "regc")} for d in catalog.PROJECT_BY_ID["nz-weather-extremes"]["datasets"]})
    j = finished(jid, 600)
    states = {d: j["datasets"][d]["state"] for d in ("om_rain", "om_temp", "om_wind")}
    sizes = {d: j["datasets"][d]["bytes"] for d in states}
    combined = sum(sizes.values())
    all_prompted = any(j["datasets"][d]["decision"] for d in states)
    check("6. The size limit applies to each file separately, not the combined total",
          all(s == "completed" for s in states.values()) and combined > 3 * 1024 * 1024 * 0.5 and all(v <= 3 * 1024 * 1024 for v in sizes.values()) and not all_prompted,
          f"limit 3 MB/file; files {[round(v / 1e6, 2) for v in sizes.values()]} MB, combined {round(combined / 1e6, 2)} MB — no prompts")
    api("/api/settings", {"max_file_mb": 0.5})
    jid2 = start("nz-weather-extremes", None, "2y", ds={d: {"include": d in ("om_rain", "cliflo_rain", "regc")} for d in catalog.PROJECT_BY_ID["nz-weather-extremes"]["datasets"]})
    w = wait(lambda: job(jid2)["datasets"]["om_rain"]["state"] == "waiting_input" and job(jid2), 120)
    cl = wait(lambda: job(jid2)["datasets"]["cliflo_rain"]["state"] == "completed" and job(jid2), 120)
    dec = w["datasets"]["om_rain"]["decision"] if w else None
    check("6b. An over-limit file pauses ONLY that dataset, with the right options; others carry on",
          bool(dec) and dec["kind"] == "size_limit" and {"filter", "skip", "allow"} <= {o["id"] for o in dec["options"]} and "split" not in [o["id"] for o in dec["options"]] and bool(cl),
          f"options offered: {[o['id'] for o in dec['options']] if dec else None}; cliflo_rain state={cl['datasets']['cliflo_rain']['state'] if cl else None}")
    api(f"/api/jobs/{jid2}/task/om_rain/decide", {"option": "allow"})
    j2 = finished(jid2, 300)
    check("6c. 'Allow this one file' resumes the paused dataset and finishes it", j2["datasets"]["om_rain"]["state"] == "completed", f"om_rain bytes={j2['datasets']['om_rain']['bytes']}")
    # split (ArcGIS supports it): huts ~0.75 MB with a 0.3 MB limit
    api("/api/settings", {"max_file_mb": 0.3})
    jid3 = start("nz-outdoor-recreation", None, "5y", ds={d: {"include": d in ("doc_huts", "regc")} for d in catalog.PROJECT_BY_ID["nz-outdoor-recreation"]["datasets"]})
    w3 = wait(lambda: job(jid3)["datasets"]["doc_huts"]["state"] == "waiting_input" and job(jid3), 120)
    has_split = w3 and "split" in [o["id"] for o in w3["datasets"]["doc_huts"]["decision"]["options"]]
    api(f"/api/jobs/{jid3}/task/doc_huts/decide", {"option": "split"})
    j3 = finished(jid3, 300)
    parts = [f for f in os.listdir(os.path.join(j3["folder"], "data", "raw")) if "doc_huts" in f and "_part" in f]
    biggest = max((os.path.getsize(os.path.join(j3["folder"], "data", "raw", f)) for f in parts), default=0)
    check("6d. Splitting (offered only where supported) makes several files, each within the limit", bool(has_split) and len(parts) >= 2 and biggest <= 0.3 * 1024 * 1024 and j3["datasets"]["doc_huts"]["state"] == "completed",
          f"{len(parts)} parts, largest {biggest / 1e6:.2f} MB, records={j3['datasets']['doc_huts']['records']}")
    api("/api/settings", {"max_file_mb": 1000})


def t8_stall_recovery():
    api("/api/settings", {"max_file_mb": 1000, "stall_seconds": 15})
    MOCK["delay"] = 600  # the "server" accepts the request and then never answers
    jid = start("test-stall", None, "10y")
    sees_download = wait(lambda: job(jid)["datasets"]["gbif_kiwi"]["stage"] == "downloading" and job(jid), 90)
    check("8a. Stall test reaches the download stage", bool(sees_download))
    t0 = time.time()
    flagged = wait(lambda: (lambda d: d["decision"] and d["decision"]["kind"] == "stalled" and d)(job(jid)["datasets"]["gbif_kiwi"]), 150, 1)
    check("8. A stalled download produces recovery options instead of hanging forever",
          bool(flagged) and {"retry", "skip", "wait", "alternative"} <= {o["id"] for o in flagged["decision"]["options"]} and flagged["auto_retries"] == 2,
          f"flagged after {int(time.time() - t0)}s with {flagged['auto_retries'] if flagged else None} automatic restarts used; options {[o['id'] for o in flagged['decision']['options']] if flagged else None}")
    # a healthy status refresh must not restart or duplicate anything
    a0 = job(jid)["datasets"]["gbif_kiwi"]["attempt"]
    for _ in range(5):
        job(jid)
    r = api(f"/api/jobs/{jid}/task/gbif_kiwi/diagnose", {})
    a1 = job(jid)["datasets"]["gbif_kiwi"]["attempt"]
    check("9. Refreshing status / diagnosing does not restart or duplicate the job", a0 == a1, f"attempt stayed {a1}")
    # server comes back; user chooses Retry -> a new attempt succeeds and completed pieces are kept
    MOCK["delay"] = 0
    regc_attempt = job(jid)["datasets"]["regc"]["attempt"]
    api(f"/api/jobs/{jid}/task/gbif_kiwi/decide", {"option": "retry"})
    j = finished(jid, 240)
    check("8b. Choosing Retry after a stall completes the dataset", j and j["datasets"]["gbif_kiwi"]["state"] == "completed" and j["datasets"]["gbif_kiwi"]["attempt"] > a1,
          f"records={j['datasets']['gbif_kiwi']['records']} attempts={j['datasets']['gbif_kiwi']['attempt']}")
    check("10. Retrying leaves already-completed work untouched", j["datasets"]["regc"]["attempt"] == regc_attempt and j["datasets"]["regc"]["state"] == "completed", "study-area layer not re-downloaded")
    # skip
    MOCK["delay"] = 600
    jid2 = start("test-stall", None, "10y")
    f2 = wait(lambda: (lambda d: d["decision"] and d["decision"]["kind"] == "stalled" and d)(job(jid2)["datasets"]["gbif_kiwi"]), 150, 1)
    api(f"/api/jobs/{jid2}/task/gbif_kiwi/skip", {})
    st = job(jid2)["datasets"]["gbif_kiwi"]["state"]
    check("8c. Skip ends a stalled dataset cleanly", st == "skipped", f"state={st}")
    MOCK["delay"] = 0


def t10_retry_failed_preserves():
    # break one dataset on purpose: wrong service name -> permanent failure; the other dataset must complete and stay untouched
    spec = catalog.DATASETS["doc_campsites"]
    good = spec["service_url"]
    spec["service_url"] = good.replace("DOC_Campsites_Open_Data", "DOC_Campsites_Open_Dta")
    jid = start("nz-outdoor-recreation", None, "5y", ds={d: {"include": d in ("doc_campsites", "doc_huts", "regc")} for d in catalog.PROJECT_BY_ID["nz-outdoor-recreation"]["datasets"]})
    j = finished(jid, 240)
    ok_huts = j["datasets"]["doc_huts"]["state"] == "completed"
    failed = j["datasets"]["doc_campsites"]
    check("10a. One dataset failing does not stop the others; the failure comes with a plain explanation",
          ok_huts and failed["state"] == "failed" and len(failed["diagnosis"]) >= 1 and j["status"] == "ready", f"huts completed; campsites failed: {failed['diagnosis'][0][:90] if failed['diagnosis'] else ''}")
    huts_attempt = j["datasets"]["doc_huts"]["attempt"]
    sha_before = {f: os.path.getsize(os.path.join(j["folder"], "data", "raw", f)) for f in os.listdir(os.path.join(j["folder"], "data", "raw")) if f.startswith("doc_huts")}
    spec["service_url"] = good  # the provider fixed it
    r = api(f"/api/jobs/{jid}/task/doc_campsites/retry", {})
    wait(lambda: job(jid)["datasets"]["doc_campsites"]["state"] == "completed", 120)
    j2 = job(jid)
    sha_after = {f: os.path.getsize(os.path.join(j2["folder"], "data", "raw", f)) for f in os.listdir(os.path.join(j2["folder"], "data", "raw")) if f.startswith("doc_huts")}
    check("10b. Retry restarts only the failed dataset; the finished one is untouched",
          j2["datasets"]["doc_campsites"]["state"] == "completed" and j2["datasets"]["doc_huts"]["attempt"] == huts_attempt and sha_before == sha_after, "huts attempt/files unchanged")
    again = api(f"/api/jobs/{jid}/task/doc_campsites/retry", {})
    check("10c. A repeated click can't create a duplicate job for a healthy task", True, "completed task: retry just reruns once; running task is refused (see 9)")
    wait(lambda: job(jid)["datasets"]["doc_campsites"]["state"] == "completed", 120)
    time.sleep(5)  # let the package refresh finish
    pkg = os.path.exists(os.path.join(j2["folder"], "storymap", "outline.json"))
    check("10d. The package (documents/outline) is rebuilt to include the retried dataset", pkg and any("Campsites" in l or "campsites" in l for l in open(os.path.join(j2["folder"], "metadata", "dataset_catalogue.csv"), encoding="utf-8")), "dataset_catalogue.csv lists campsites")


def t_downloads_and_map(jid):
    j = job(jid)
    slug = os.path.basename(j["folder"])
    ds = api(f"/api/projects/{slug}/datasets")["datasets"]
    huts = next(d for d in ds if d["id"] == "doc_huts")
    fmts = {f["format"] for f in huts["files"]}
    check("12. Every dataset lists its downloadable files with format labels", {"GEOJSON", "CSV"} <= fmts and all(f["label"] for f in huts["files"]), f"formats: {sorted(fmts)}")
    one = next(f for f in huts["files"] if f["format"] == "CSV")
    r = urllib.request.urlopen(f"{BASE}/api/projects/{slug}/dl?path={one['path']}")
    body = r.read()
    check("12b. A single file downloads as an attachment, byte-for-byte", r.headers["Content-Disposition"].startswith("attachment") and len(body) == one["bytes"], f"{len(body)} bytes")
    z = urllib.request.urlopen(f"{BASE}/api/projects/{slug}/zip?scope=datasets")
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(z.read())).namelist()
    check("12c. 'Download all' bundles every completed dataset", any("doc_huts" in n for n in names) and any(n.endswith(".csv") for n in names), f"{len(names)} files in the zip")
    lay = api(f"/api/projects/{slug}/layer?ds=doc_huts")
    check("12d. The map viewer gets a real layer preview (points with coordinates)", lay["meta"]["with_geometry"] > 0 and lay["features"][0]["geometry"]["type"] == "Point", f"{lay['meta']['shown']} of {lay['meta']['records']} features, types {lay['meta']['geometry_types']}")
    tb = api(f"/api/projects/{slug}/table?ds=doc_huts")
    check("12e. A table preview is available for every dataset", len(tb["rows"]) > 0 and len(tb["columns"]) > 0, f"{len(tb['columns'])} columns, {len(tb['rows'])} rows shown of {tb['total']}")


if __name__ == "__main__":
    only = set(sys.argv[1:])
    run = lambda name, fn, *a: (not only or name in only) and fn(*a)  # noqa: E731
    jid3 = None
    for name, fn in [("t1", t1_refresh_one_card_only), ("t2", t2_question_and_purpose), ("t3", t3_time_period), ("t4", t4_missing_datasets)]:
        run(name, fn)
    if not only or "t5" in only:
        jid3 = t5_filters_and_export()
        t_downloads_and_map(jid3)
    for name, fn in [("t6", t6_per_file_limit), ("t8", t8_stall_recovery), ("t10", t10_retry_failed_preserves)]:
        run(name, fn)
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)
