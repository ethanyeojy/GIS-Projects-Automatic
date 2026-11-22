"""Troubleshooter: re-checks one project's datasets, explains each failure in plain words, and looks for
working alternatives (similar service names in the same ArcGIS directory + an ArcGIS Online search).
Every suggestion is test-verified live before it is offered. Nothing is changed until the user clicks 'Use this'."""
import copy
import difflib
import json
import re
import threading
import urllib.parse

from . import catalog, connectors, net


def _raw(url, params=None):
    """Return (status, text) without raising — for diagnosis only."""
    try:
        st, _, body = net.request(url, params, retries=1, timeout=30)
        return st, body.decode("utf-8", "replace")
    except net.NetError as e:
        return e.status, str(e)
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def internet_ok():
    st, _ = _raw("https://api.gbif.org/v1/")
    return st is not None and st < 500


def _words(name):
    return [w for w in re.split(r"[^A-Za-z0-9]+", name) if len(w) > 2 and w.lower() not in ("the", "and", "for", "nz")]


def _candidate_urls(spec):
    """Services with similar names in the same ArcGIS directory, plus ArcGIS Online search hits."""
    cands = []
    base = spec["service_url"]
    m = re.match(r"(https://[^/]+/[^/]+/(?:arcgis|ArcGIS)/rest/services)/(.+?)/(FeatureServer|MapServer)", base, re.I)
    if m:
        st, txt = _raw(m.group(1), {"f": "json"})
        try:
            names = [s for s in json.loads(txt).get("services", []) if s.get("type") in ("FeatureServer", "MapServer")]
            want = m.group(2).lower()
            near = difflib.get_close_matches(want, [n["name"].lower() for n in names], n=3, cutoff=0.5)
            for n in names:
                if n["name"].lower() in near:
                    cands.append((n["name"], f"{m.group(1)}/{n['name']}/{n['type']}"))
        except (ValueError, TypeError):
            pass
    q = " ".join(_words(spec["name"])[:6]) + ' type:"Feature Service"'
    st, txt = _raw("https://www.arcgis.com/sharing/rest/search", {"q": q, "f": "json", "num": 8})
    try:
        for r in json.loads(txt).get("results", []):
            if r.get("url") and "/rest/services/" in r["url"]:
                cands.append((r.get("title", "?"), r["url"]))
    except (ValueError, TypeError):
        pass
    seen, out = set(), []
    for t, u in cands:
        if u.rstrip("/") != base.rstrip("/") and u not in seen:
            seen.add(u)
            out.append((t, u))
    return out[:6]


def _try_candidates(spec, cands, limit=3):
    found = []
    for title, url in cands:
        if len(found) >= limit:
            break
        s2 = copy.deepcopy(spec)
        s2["service_url"], s2["landing_url"] = url, url
        r = connectors.make_source(s2).verify(bbox=None, cancel=threading.Event())
        found.append({"title": title, "service_url": url, "status": r["status"], "count": r.get("count"),
                      "problems": [c["name"] + ": " + c["detail"][:100] for c in r["checks"] if not c["ok"]][:2]})
    return found


def _explain(spec, res):
    """Plain-language reasons from what the service actually returned."""
    out, err = [], (res.get("error") or "")
    failed = [c for c in res["checks"] if not c["ok"]]
    blob = " ".join([err] + [c["detail"] for c in failed])
    if re.search(r"HTTP 5\d\d|Internal Server Error|502|503|504", blob):
        out.append("The data provider's server is returning an error (HTTP 5xx). That is on their side, not yours — it is often temporary. Try again later, or use an alternative below.")
    if re.search(r"Invalid URL|HTTP 404|not found|No layer in service", blob, re.I):
        out.append("The service address no longer exists or was renamed. The provider probably moved or republished the layer — see alternatives below.")
    if re.search(r"HTTP 400", blob):
        out.append("The provider rejected the request (HTTP 400). The query format may have changed, or this service does not support one of the parameters used.")
    if re.search(r"HTTP 40[13]|token|credentials", blob, re.I):
        out.append("This service now asks for a login or API key. Only openly queryable sources are used, so it can't be fetched automatically.")
    if re.search(r"Network error|timed out|Name or service|getaddrinfo|Connection", blob, re.I):
        out.append("Could not reach the server at all. Check your internet connection, VPN or firewall — some networks block these services.")
    if re.search(r"IncompleteRead", blob):
        out.append("The download was cut off part-way. The layer is probably too large for a quick check — try again, or pick a single region.")
    for c in failed:
        if re.search(r"Required field", c["name"]):
            out.append(f"The data loaded but a needed field is missing ({c['name']}). The provider may have renamed it.")
        if re.search(r"Record count", c["name"]):
            out.append("The layer is reachable but returned no records for the study area.")
    if not out:
        out.append("No single cause identified; the raw error is shown below.")
    return out


def diagnose_one(ds, store, online=None, bbox=None, project_id=None):
    """Re-check one dataset, explain any failure in plain words, and look for tested replacements."""
    online = internet_ok() if online is None else online
    spec = catalog.DATASETS[ds]
    res = connectors.make_source(spec).verify(bbox=bbox, cancel=threading.Event())
    store.set_ver(project_id, ds, res)
    with store.lock:
        store.save()
    item = {"dataset_id": ds, "name": spec["name"], "status": res["status"], "count": res.get("count"),
            "failed": [{"name": c["name"], "detail": c["detail"]} for c in res["checks"] if not c["ok"]],
            "explain": [], "alternatives": []}
    if res["status"] != "verified":
        item["explain"] = _explain(spec, res) if online else ["No internet connection detected — check your network first."]
        if online and spec["connector"] == "arcgis":
            item["alternatives"] = _try_candidates(spec, _candidate_urls(spec))
        elif online and spec["connector"] == "gbif":
            item["explain"].append("GBIF matches species by scientific name; check the name/rank in the catalogue if no match was found.")
        elif online and spec["connector"] == "openmeteo":
            item["explain"].append("Open-Meteo is a free service with daily request limits; if it reports a limit, wait and retry. Its air-quality model also starts later than its weather data.")
    return item


def diagnose(project_id, store):
    proj = catalog.PROJECT_BY_ID[project_id]
    online = internet_ok()
    items = [diagnose_one(ds, store, online, project_id=project_id) for ds in proj["datasets"]]
    bad = [i for i in items if i["status"] != "verified"]
    return {"project_id": project_id, "internet": online, "ok": not bad, "datasets": items,
            "summary": ("All datasets are reachable and passed checks." if not bad else
                        f"{len(bad)} of {len(items)} datasets have problems."),
            "project": next(p for p in store.feed() if p["id"] == project_id)}