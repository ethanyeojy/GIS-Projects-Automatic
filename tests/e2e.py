"""Offline end-to-end test against tests/mock_server.py (synthetic fixtures). Run: python3 tests/e2e.py"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mock_server  # noqa: E402

srv = mock_server.start(0)
port = srv.server_address[1]
os.environ["GPS_TEST_HOST_OVERRIDES"] = json.dumps(mock_server.overrides(port))
os.environ["GPS_MIN_INTERVAL"] = "0"

from gps import catalog  # noqa: E402
from gps.feed import Store  # noqa: E402
from gps.jobs import JobManager  # noqa: E402

tmp = tempfile.mkdtemp(prefix="gps_test_")
store = Store(os.path.join(tmp, "state"))
store.update_settings({"project_root": os.path.join(tmp, "projects")})
fails = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def wait(fn, t=60):
    s = time.time()
    while time.time() - s < t:
        if fn():
            return True
        time.sleep(0.2)
    return False


# before refresh: nothing verified
ok(all(p["availability"] == "unverified" for p in store.feed()), "before refresh every project is 'unverified' (no fabricated state)")
store.start_refresh()
ok(wait(lambda: store.refresh_status["state"] in ("done", "error")), "refresh finished")
feed = {p["id"]: p for p in store.feed()}
for pid, p in feed.items():
    ok(p["availability"] == "verified", f"{pid} verified: {p['reasons'][:1]}")

jm = JobManager(store)
results = {}
for pid in catalog.PROJECT_BY_ID:
    job = jm.start(pid, None)
    ok(wait(lambda: job.status in ("ready", "failed", "cancelled", "needs_approval"), 120), f"{pid} job ended: {job.status} {job.message}")
    results[pid] = job
    ok(job.status == "ready", f"{pid} ready")
    for rel in ["README.md", "project_brief.md", "metadata/dataset_catalogue.csv", "metadata/provenance.json", "metadata/data_dictionary.csv",
                "metadata/quality_report.md", "metadata/compatibility_report.md", "workflows/analysis_guide.md", "storymap/outline.md", "storymap/draft_content.md", "logs/job.log"]:
        ok(os.path.exists(job.path(*rel.split("/"))), f"{pid}: {rel} exists")
    ok(all(d["validated"] for d in job.datasets.values()), f"{pid}: all datasets validated")

j = results["nz-quake-decade"]
print("tag_stats", json.dumps(j.data["tag_stats"]))
ok(j.data["tag_stats"]["geonet_fdsn"]["untagged"] > 0, "quake: some offshore/untagged points counted, not removed")
ok(j.data["inspections"]["geonet_fdsn"]["records"] == j.datasets["geonet_fdsn"]["records"], "quake: records inspected == downloaded")
j = results["nz-coastal-esl-exposure"]
ok(j.datasets["niwa_esl_1pc"]["records"] == 230, "ESL paged download got all 230 (pages of 100)")
j = results["nz-river-flood-flows"]
ok(j.datasets["niwa_flood_stats"]["records"] == 120, "flood stats via Esri JSON fallback + conversion got 120")
print("compat", [(r["need"], r["status"]) for r in j.data["compat"]])
j = results["nz-galaxiid-records"]
ok(j.datasets["gbif_galaxiidae"]["records"] == 650, "GBIF paging 300/page got all 650")

# region study area
job = jm.start("nz-galaxiid-records", "Test North")
ok(wait(lambda: job.status in ("ready", "failed"), 120), f"region job ended: {job.status} {job.message}")
ok(os.path.exists(job.path("data", "reference", "study_area.geojson")), "region: study_area.geojson written")
print("region tag", job.data["tag_stats"], job.data["bbox"])
ok(job.datasets["gbif_galaxiidae"]["records"] < 650, "region: server-side bbox subset reduced record count")
ok(job.folder != results["nz-galaxiid-records"].folder, "second run created a NEW folder (no overwrite)")
bad = jm.start("nz-galaxiid-records", "Atlantis")
ok(wait(lambda: bad.status in ("ready", "failed"), 60) and bad.status == "failed" and "not found" in bad.message, "unknown region fails with explanation: " + bad.message[:80])

# size gate approval
store.update_settings({"max_download_mb": 0.001})
job = jm.start("nz-coastal-esl-exposure", None)
ok(wait(lambda: job.status == "needs_approval", 60), "size gate pauses for approval")
job.approve.set()
ok(wait(lambda: job.status in ("ready", "failed"), 60) and job.status == "ready", "job continues after approval")

# cancel + resume
store.update_settings({"max_download_mb": 500})
job = jm.start("nz-galaxiid-records", None)
job.cancel.set()
wait(lambda: job.status in ("cancelled", "ready", "failed"), 30)
print("cancel status:", job.status)
jm.retry(job.id)
ok(wait(lambda: job.status in ("ready", "failed"), 120) and job.status == "ready", "retry after cancel completes")
# resume reuse
jm.retry(job.id)
ok(wait(lambda: job.status in ("ready", "failed"), 120), "second retry ok")
ok(any("Resuming" in l for l in job.log_lines), "resume reuses checksum-verified downloads")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
