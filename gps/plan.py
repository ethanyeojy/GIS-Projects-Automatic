"""The pre-download plan: for each dataset of the chosen project, what it will contain AFTER the chosen area, time period and
filters — real counts and sizes from live checks, the filters that source supports, time coverage, and export formats."""
import threading
from concurrent.futures import ThreadPoolExecutor

from . import catalog, connectors, coverage


def _item(store, ds, bbox, region, period, filters=None):
    spec = catalog.DATASETS[ds]
    opts = {"period": period, "filters": filters or {}, "region": region}
    try:
        ver = connectors.make_source(spec).verify(bbox=bbox, cancel=threading.Event(), opts=opts)
    except Exception as e:  # noqa: BLE001
        ver = {"status": "incomplete", "checks": [{"name": "Check", "ok": False, "detail": str(e)[:200]}], "count": None, "est_bytes": None, "fields": [], "notes": []}
    cov = coverage.info(spec, period, ver)
    limit = float(store.settings.get("max_file_mb") or 0) * 1024 * 1024
    failed = [c for c in ver["checks"] if not c["ok"]]
    warn = []
    if limit and ver.get("est_bytes") and ver["est_bytes"] > limit:
        warn.append(f"Estimated {ver['est_bytes'] / 1e6:.0f} MB — over your {limit / 1e6:.0f} MB per-file limit, so you'll be asked how to handle it.")
    if cov["status"] in ("gap", "partial"):
        warn.append(cov["note"])
    c = connectors.caps(spec)
    return {"id": ds, "name": spec["name"], "publisher": spec["publisher"], "landing_url": spec.get("landing_url"), "connector": spec["connector"],
            "status": ver["status"], "count": ver.get("count"), "est_bytes": ver.get("est_bytes"), "est_note": ver.get("est_note"),
            "failed": [{"name": x["name"], "detail": x["detail"]} for x in failed], "coverage": cov, "warnings": warn,
            "schema": connectors.filter_schema(spec, ver), "fields": [f["name"] for f in ver.get("fields", [])][:80],
            "formats": ["geojson", "csv", "xlsx"], "default_formats": connectors.default_formats(spec),
            "caps": {"split": bool(c.get("split")), "server_limit": bool(c.get("server_limit")), "period": bool(c.get("period")), "attr": bool(c.get("attr"))},
            "licence": ver.get("licence"), "notes": ver.get("notes", []), "geometry": ver.get("geometry_type")}


def build(store, project, region, period):
    bbox = None
    if region:
        try:
            bbox = store.region_bbox(region)
        except Exception:  # noqa: BLE001
            bbox = None
    ids = [d for d in project["datasets"] if d != "regc"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda d: _item(store, d, bbox, region, period), ids))
    return {"project_id": project["id"], "region": region, "period": period, "limit_mb": store.settings.get("max_file_mb"), "datasets": items}


def estimate(store, ds, region, period, filters):
    bbox = store.region_bbox(region) if region else None
    return _item(store, ds, bbox, region, period, filters)
