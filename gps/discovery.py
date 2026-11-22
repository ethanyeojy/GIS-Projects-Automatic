"""Project-aware dataset finder ("Find missing datasets").

Searches REAL catalogues only — ArcGIS Online public items, the NZ government open-data catalogue (data.govt.nz), GBIF species
suggestions, and this app's own verified catalogue — using the project, its research question, theme, region, time period and
the datasets it already has. It never invents a source, link, record count or file size: anything not reported by a live
service is labelled "unknown". Gap-spotting is rule-based (no AI key is needed or used)."""
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from . import catalog, connectors, net, timeperiod

NZ_BOX = (165.0, -48.5, 179.5, -33.5)  # minlon, minlat, maxlon, maxlat (incl. Chatham/Kermadec-ish margin)
STOP = set("the a an and or of in on for to with from by at is are was were be this that these those data dataset datasets layer layers new zealand nz find need missing "
           "want some any more please about into over under between across using use get give show i we my our your it its as if "
           "access web map maps app application area areas information service services draft layer layers view views public open".split())

def _fmt_bytes(b):
    if b is None:
        return "unknown"
    return f"{b / 1e6:.1f} MB" if b >= 1e6 else f"{max(1, round(b / 1e3))} kB"

DIMS = {
    "hazard events": ("records of the hazard events themselves", ["earthquake", "flood", "landslide", "eruption", "hazard", "event", "storm", "tsunami"]),
    "exposure": ("who or what is exposed (people, dwellings, buildings)", ["population", "census", "building", "dwelling", "urban", "property", "household"]),
    "infrastructure": ("roads and infrastructure", ["road", "rail", "infrastructure", "bridge", "port", "airport", "network"]),
    "terrain": ("elevation and terrain", ["elevation", "dem", "slope", "terrain", "lidar", "contour", "height"]),
    "weather": ("weather or rainfall drivers", ["rainfall", "rain", "precipitation", "temperature", "wind", "weather", "storm"]),
    "landcover": ("land cover and land use", ["land cover", "land use", "lcdb", "vegetation", "forest", "habitat", "ecosystem"]),
    "waterquality": ("river flow and water quality", ["water quality", "river flow", "discharge", "stream", "catchment", "flow", "river"]),
    "protected": ("protected areas", ["conservation", "reserve", "park", "protected", "sanctuary"]),
    "marine": ("ocean and coastal conditions", ["bathymetry", "sea surface", "ocean", "wave", "tide", "coast", "marine"]),
    "biodiversity": ("species records", ["species", "occurrence", "biodiversity", "threatened", "sighting", "fish", "bird"]),
    "boundaries": ("administrative boundaries", ["boundary", "region", "council", "territorial", "regional"]),
    "visitors": ("visitor numbers and use", ["visitor", "tourism", "recreation", "use", "track", "hut"]),
    "climate": ("long-term climate", ["climate", "normals", "drought", "trend", "temperature"]),
}
THEME_EXPECT = {
    "hazards": ["hazard events", "exposure", "infrastructure", "terrain", "weather"],
    "freshwater": ["waterquality", "weather", "landcover", "biodiversity", "terrain"],
    "wildlife": ["biodiversity", "landcover", "protected", "climate"],
    "outdoors": ["visitors", "infrastructure", "terrain", "exposure"],
    "marine": ["marine", "protected", "biodiversity", "weather"],
    "weather": ["terrain", "exposure", "hazard events"],
    "climate": ["weather", "landcover", "exposure"],
    "environment": ["landcover", "exposure", "terrain", "boundaries"],
}


def _terms(text):
    return [w for w in re.findall(r"[a-zA-Z]{3,}", (text or "").lower()) if w not in STOP]


def _hit(term, text):
    """Whole-word match (so "rain" does not match "terrain" or "training"), allowing simple plurals."""
    return re.search(r"\b" + re.escape(term) + r"(s|es)?\b", text) is not None


def _cid(*parts):
    return "c_" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def _ds_text(spec):
    return " ".join([spec.get("name", ""), spec.get("publisher", ""), " ".join(spec.get("tags", []) if isinstance(spec.get("tags"), list) else [])]).lower()


def find_gaps(project):
    """Which kinds of data the project's theme usually needs that none of its datasets obviously provide (rule-based)."""
    have = " ".join(_ds_text(catalog.DATASETS[d]) for d in project["datasets"] if d in catalog.DATASETS)
    gaps = []
    for dim in THEME_EXPECT.get(project["theme"], []):
        label, kws = DIMS[dim]
        if not any(k in have for k in kws):
            gaps.append({"dim": dim, "label": label, "keywords": kws[:3]})
    return gaps


def _bbox_text(b):
    return f"lon {b[0]:.1f}–{b[2]:.1f}, lat {b[1]:.1f}–{b[3]:.1f}"


def _intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


# ---------------------------------------------------------------- sources
def _search_arcgis(terms, region_name, cancel):
    q = " ".join(terms[:6] + (["New Zealand"] if not region_name else [region_name]))
    st, js = net.get_json("https://www.arcgis.com/sharing/rest/search",
                          {"q": f'{q} type:"Feature Service" access:public', "f": "json", "num": 12, "sortField": "numviews", "sortOrder": "desc"},
                          cancel=cancel, timeout=30, retries=1)
    out = []
    for r in (js or {}).get("results", []):
        url = r.get("url") or ""
        if "/rest/services/" not in url:
            continue
        ext = r.get("extent") or []
        bbox = [ext[0][0], ext[0][1], ext[1][0], ext[1][1]] if len(ext) == 2 else None
        if bbox and not _intersects(bbox, NZ_BOX):
            continue  # clearly outside New Zealand
        out.append({"title": r.get("title", "?"), "owner": r.get("owner", "unknown"), "url": url, "bbox": bbox,
                    "snippet": re.sub(r"<[^>]+>", " ", (r.get("snippet") or r.get("description") or ""))[:240].strip(),
                    "modified": r.get("modified"), "views": r.get("numViews"), "licence": (r.get("licenseInfo") or "")[:160]})
    return out


def _search_ckan(terms, cancel):
    q = " ".join(terms[:5])
    st, js = net.get_json("https://catalogue.data.govt.nz/api/3/action/package_search", {"q": q, "rows": 8}, cancel=cancel, timeout=30, retries=1)
    out = []
    for p in ((js or {}).get("result") or {}).get("results", []):
        extras = {e.get("key", "").lower(): e.get("value") for e in p.get("extras", []) if isinstance(e, dict)}
        res = [r for r in p.get("resources", []) if (r.get("url") or "").startswith("http")]
        out.append({"title": p.get("title", "?"), "org": (p.get("organization") or {}).get("title") or p.get("author") or "unknown",
                    "notes": re.sub(r"<[^>]+>", " ", (p.get("notes") or ""))[:240].strip(), "licence": p.get("license_title") or "not stated",
                    "modified": (p.get("metadata_modified") or "")[:10], "resources": res, "page": f"https://catalogue.data.govt.nz/dataset/{p.get('name')}",
                    "spatial": next((v for k, v in extras.items() if "spatial" in k), None),
                    "temporal": next((v for k, v in extras.items() if "temporal" in k or "coverage" in k), None)})
    return out


def _head(url, cancel):
    try:
        st, h = None, {}
        st, h, _ = net.request(url, method="HEAD", cancel=cancel, retries=0, timeout=15)
        return st, h
    except net.NetError as e:
        return e.status, {}
    except Exception:  # noqa: BLE001
        return None, {}


def _gbif_candidates(terms, cancel):
    out = []
    seen = set()
    for t in terms[:3]:
        try:
            st, js = net.get_json("https://api.gbif.org/v1/species/suggest", {"q": t, "limit": 3, "rank": "SPECIES"}, cancel=cancel, timeout=20, retries=0)
        except Exception:  # noqa: BLE001
            continue
        for r in js or []:
            key = r.get("key")
            if not key or key in seen or r.get("rank") not in ("SPECIES", "GENUS", "FAMILY"):
                continue
            seen.add(key)
            try:
                st, c = net.get_json("https://api.gbif.org/v1/occurrence/search", {"taxonKey": key, "country": "NZ", "hasCoordinate": "true", "limit": 0}, cancel=cancel, timeout=20, retries=0)
            except Exception:  # noqa: BLE001
                continue
            n = (c or {}).get("count", 0)
            if n > 0:
                out.append({"key": key, "name": r.get("scientificName"), "common": (r.get("vernacularNames") or [{}])[0].get("vernacularName") if r.get("vernacularNames") else None,
                            "rank": r.get("rank"), "count": n})
    return out[:4]


# ---------------------------------------------------------------- main entry
def find(store, project, query="", region=None, period=None, mode="search", cancel=None):
    cancel = cancel or threading.Event()
    have_ids = set(project["datasets"])
    gaps = find_gaps(project) if mode == "gaps" or not query.strip() else []
    q_terms = _terms(query)
    if mode == "gaps" and not q_terms:
        terms_sets = [[*g["keywords"], project["theme"]] for g in gaps[:3]] or [_terms(project["question"])[:5]]
    else:
        terms_sets = [q_terms or _terms(project["question"])[:5]]
        if len(q_terms) > 1:  # the catalogues AND all words together, so also try the key words one at a time
            terms_sets += [[w] for w in q_terms[:3]]
    ctx = {"project": project["title"], "question": project["question"], "theme": project["theme"], "region": region or "New Zealand-wide",
           "period": period["text"] if period else "not set", "have": [catalog.DATASETS[d]["name"] for d in project["datasets"] if d in catalog.DATASETS]}
    notes, cands = [], []

    # 1) our own verified catalogue (datasets this project doesn't already include)
    all_terms = {t for ts in terms_sets for t in ts}
    for ds, spec in catalog.DATASETS.items():
        if ds in have_ids or ds.startswith("x_"):
            continue
        text = _ds_text(spec) + " " + " ".join(DIMS[d][1][0] for d in DIMS if any(k in _ds_text(spec) for k in DIMS[d][1][:2]))
        hit = sorted(t for t in all_terms if _hit(t, text))
        if not hit:
            continue
        ver = store.verification.get(ds)
        cov_note = "supports a date range" if connectors.caps(spec).get("period") else "current/static (not date-filtered)"
        cands.append({"id": _cid("cat", ds), "title": spec["name"], "source": spec["publisher"], "origin": "This app's verified catalogue", "kind": "catalogue",
                      "ready": "ready" if ver and ver["status"] == "verified" else "unverified",
                      "ready_note": "Already verified by this app's live checks." if ver and ver["status"] == "verified" else "Not checked recently — it will be verified when you add it.",
                      "why": f"Matches '{', '.join(hit[:3])}'. Your project asks: “{project['question'][:110]}…”",
                      "time_coverage": cov_note, "geo_coverage": "New Zealand (filterable by region)" if spec["connector"] != "openmeteo" else "16 regional centres",
                      "format": {"arcgis": "ArcGIS feature layer → GeoJSON / CSV", "gbif": "GBIF records → GeoJSON / CSV", "openmeteo": "Daily time series → CSV / Excel"}.get(spec["connector"], "GeoJSON / CSV"),
                      "size_text": f"≈{_fmt_bytes(ver['est_bytes'])} (estimate)" if ver and ver.get("est_bytes") else "unknown until checked",
                      "records": ver.get("count") if ver else None, "licence": (ver or {}).get("licence") or spec.get("licence_note") or "unknown",
                      "link": spec.get("landing_url"), "dataset_id": ds})

    # 2) ArcGIS Online + 3) data.govt.nz + 4) GBIF — in parallel
    futures = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, ts in enumerate(terms_sets):
            futures[("agol", i)] = pool.submit(_search_arcgis, ts, region, cancel)
            futures[("ckan", i)] = pool.submit(_search_ckan, ts, cancel)
        if q_terms:
            futures[("gbif", 0)] = pool.submit(_gbif_candidates, q_terms, cancel)
        results = {}
        for k, fu in futures.items():
            try:
                results[k] = fu.result(timeout=60)
            except Exception as e:  # noqa: BLE001
                results[k] = []
                notes.append(f"{'ArcGIS Online' if k[0] == 'agol' else 'data.govt.nz' if k[0] == 'ckan' else 'GBIF'} search failed or timed out: {str(e)[:100]}")

        # verify the most relevant ArcGIS services live (real count + size)
        agol, seen_urls = [], set(catalog.DATASETS[d].get("service_url") for d in have_ids if d in catalog.DATASETS)
        for i in range(len(terms_sets)):
            for r in results.get(("agol", i), []):
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    agol.append((i, r))
        agol = agol[:8]
        checks = {}

        def verify_one(item):
            i, r = item
            spec = {"id": "tmp", "role": "optional", "connector": "arcgis", "name": r["title"], "publisher": r["owner"], "service_url": r["url"], "landing_url": r["url"]}
            try:
                return r["url"], connectors.make_source(spec).verify(bbox=store.region_bbox(region) if region else None, cancel=cancel)
            except Exception as e:  # noqa: BLE001
                return r["url"], {"status": "incomplete", "checks": [{"name": "Verification", "ok": False, "detail": str(e)[:120]}], "count": None, "est_bytes": None}
        for url, v in pool.map(verify_one, agol):
            checks[url] = v
        # HEAD the file-like CKAN resources
        ckan = []
        for i in range(len(terms_sets)):
            ckan += results.get(("ckan", i), [])
        heads = {}
        urls = []
        for p in ckan[:8]:
            for r in p["resources"][:6]:
                if (r.get("format") or "").upper() in ("CSV", "GEOJSON", "JSON", "XLSX", "XLS", "ZIP", "SHP", "KML", "KMZ", "GPKG") and r["url"] not in urls:
                    urls.append(r["url"])
        for url, hd in zip(urls[:16], pool.map(lambda u: _head(u, cancel), urls[:16])):
            heads[url] = hd

    for (i, r) in agol:
        v = checks.get(r["url"]) or {}
        ok = v.get("status") == "verified"
        matched = sorted(t for t in all_terms if _hit(t, (r["title"] + " " + r["snippet"]).lower()))
        if all_terms and not matched:
            continue  # nothing in its title/description relates to what was asked
        spec = {"id": "tmp", "role": "optional", "connector": "arcgis", "name": r["title"], "publisher": r["owner"] + " (ArcGIS Online)", "service_url": r["url"],
                "landing_url": r["url"], "licence_note": r["licence"] or "licence not stated — confirm with the publisher"}
        cands.append({"id": _cid("agol", r["url"]), "title": r["title"], "source": f"{r['owner']} (ArcGIS Online)", "origin": "ArcGIS Online public item", "kind": "arcgis",
                      "ready": "ready" if ok else "manual",
                      "ready_note": "Public service; the live check passed, so it can be downloaded automatically." if ok else
                                    "Live check did not pass: " + "; ".join(c["detail"] for c in v.get("checks", []) if not c["ok"])[:160],
                      "why": (f"Matches '{', '.join(matched[:3])}' in its title/description. " if matched else "Found by your search terms. ") + (r["snippet"][:140] if r["snippet"] else "No description provided."),
                      "time_coverage": (f"last updated {_ymd(r['modified'])}; the dates the data covers are not stated" if r["modified"] else "not stated"),
                      "geo_coverage": _bbox_text(r["bbox"]) if r["bbox"] else "extent not stated",
                      "format": "ArcGIS feature layer → GeoJSON / CSV (geometry: " + str(v.get("geometry_type") or "unknown").replace("esriGeometry", "") + ")",
                      "size_text": f"≈{_fmt_bytes(v['est_bytes'])} (estimate from a 5-feature sample)" if v.get("est_bytes") else "unknown",
                      "records": v.get("count"), "licence": r["licence"] or "not stated", "link": r["url"], "spec": spec, "score": len(matched)})
    for p in ckan:
        best = None
        for r in p["resources"]:
            fmt = (r.get("format") or "").upper()
            if fmt in ("CSV", "GEOJSON", "JSON") and (best is None or fmt != "JSON"):
                best = r
        res = best or next((r for r in p["resources"] if (r.get("format") or "").upper() in ("XLSX", "XLS", "ZIP", "SHP", "KML", "KMZ", "GPKG")), None)
        if not res:
            continue
        fmt = (res.get("format") or "").upper()
        st, hd = heads.get(res["url"], (None, {}))
        size = hd.get("Content-Length")
        direct = fmt in ("CSV", "GEOJSON", "JSON") and st in (200, 206)
        needs = st in (401, 403)
        matched = sorted(t for t in all_terms if _hit(t, (p["title"] + " " + p["notes"]).lower()))
        if all_terms and not matched:
            continue
        spec = None
        if direct and fmt != "JSON":
            spec = {"id": "tmp", "role": "optional", "connector": "file_url", "url": res["url"], "format": "csv" if fmt == "CSV" else "geojson", "tabular": fmt == "CSV",
                    "name": p["title"], "publisher": p["org"] + " (data.govt.nz)", "landing_url": p["page"], "licence_note": p["licence"]}
        cands.append({"id": _cid("ckan", res["url"]), "title": p["title"], "source": f"{p['org']} (data.govt.nz)", "origin": "NZ open-data catalogue", "kind": "file",
                      "ready": "ready" if spec else ("needs_access" if needs else "manual"),
                      "ready_note": ("Direct file link responded (HTTP %s), so it can be downloaded automatically." % st) if spec else
                                    ("The link requires access/authentication (HTTP %s). Get it from the publisher's page." % st) if needs else
                                    f"A {fmt or 'file'} that needs a manual step: open the publisher's page, download it, and add it to your project folder yourself.",
                      "why": (f"Matches '{', '.join(matched[:3])}' in its title/description. " if matched else "Found by your search terms. ") + (p["notes"][:140] or "No description provided."),
                      "time_coverage": str(p["temporal"]) if p["temporal"] else f"not stated (catalogue entry last changed {p['modified']})",
                      "geo_coverage": str(p["spatial"])[:120] if p["spatial"] else "not stated (New Zealand catalogue)", "format": fmt or "unknown",
                      "size_text": f"{_fmt_bytes(int(size))} (reported by the server)" if size and str(size).isdigit() else "unknown",
                      "records": None, "licence": p["licence"], "link": p["page"], "spec": spec, "score": len(matched)})
    for g in results.get(("gbif", 0), []):
        spec = {"id": "tmp", "role": "optional", "connector": "gbif", "taxon_name": g["name"], "taxon_rank": g["rank"], "name": f"GBIF sightings: {g['name']}",
                "publisher": "GBIF and contributing publishers", "landing_url": f"https://www.gbif.org/species/{g['key']}"}
        cands.append({"id": _cid("gbif", g["key"]), "title": f"GBIF sightings: {g['name']}" + (f" ({g['common']})" if g.get("common") else ""), "source": "GBIF and contributing publishers",
                      "origin": "GBIF species search", "kind": "gbif", "ready": "ready" if g["count"] <= connectors.GBIF_PAGING_CAP else "manual",
                      "ready_note": "Public API; downloads automatically." if g["count"] <= connectors.GBIF_PAGING_CAP else
                                    f"{g['count']:,} records is over the {connectors.GBIF_PAGING_CAP:,}-record paging limit: filter by area/years/record type, or keep the first 100,000.",
                      "why": f"Your search mentions this species name; GBIF holds georeferenced New Zealand records of it.",
                      "time_coverage": "filtered by your chosen years (each record's year)", "geo_coverage": "New Zealand (filterable by region)", "format": "GBIF records → GeoJSON / CSV",
                      "size_text": f"≈{g['count'] * 1.4 / 1000:.1f} MB (estimate: 1.4 kB × {g['count']:,} records)", "records": g["count"],
                      "licence": "per-record licences (some non-commercial)", "link": spec["landing_url"], "spec": spec})
    seen_keys, uniq = set(), []
    for c in cands:  # the same catalogue entry can be found by several searches
        k = (c["title"].strip().lower(), c["source"].strip().lower())
        if k not in seen_keys:
            seen_keys.add(k)
            uniq.append(c)
    cands = uniq
    order = {"ready": 0, "unverified": 1, "manual": 2, "needs_access": 3}
    cands.sort(key=lambda c: (order.get(c["ready"], 9), -c.get("score", 5), 0 if c["kind"] == "catalogue" else 1))
    store.discovery = {c["id"]: c for c in cands}
    if not cands:
        notes.append("Nothing relevant was found with these words. Try different or more specific words (e.g. “rainfall stations”, “building footprints”).")
    return {"context": ctx, "mode": mode, "gaps": gaps, "terms": sorted(all_terms)[:12], "candidates": cands[:24], "notes": notes,
            "searched": ["This app's verified catalogue", "ArcGIS Online (public items)", "data.govt.nz (NZ open-data catalogue)"] + (["GBIF species"] if q_terms else []),
            "method": "Rule-based search of the catalogues listed — no AI model is used, and nothing is invented. Values shown as 'unknown' were not reported by the source."}


def _ymd(ms):
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "unknown date"


def register(store, cids):
    """Turn selected candidates into real datasets the job can download. Returns the new dataset ids."""
    out = []
    for cid in cids:
        c = (getattr(store, "discovery", None) or {}).get(cid)
        if not c:
            raise KeyError(f"unknown candidate {cid}")
        if c.get("dataset_id"):
            out.append(c["dataset_id"])
            continue
        if not c.get("spec"):
            raise ValueError(f"'{c['title']}' needs a manual step ({c['ready_note']}) so it can't be added automatically.")
        spec = dict(c["spec"])
        spec["id"] = "x_" + cid[2:]
        spec.setdefault("role", "optional")
        store.add_custom(spec)
        out.append(spec["id"])
    return out
