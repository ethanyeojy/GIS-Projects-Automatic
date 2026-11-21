"""Dataset connectors. Each connector can (a) verify access + inspect a sample and
(b) download a regional subset with real progress callbacks.

Nothing here fabricates results: every check records what was actually returned by the
remote service, or the error that occurred.
"""
import hashlib
import html
import shutil
import json
import os
import re
from datetime import datetime, timedelta, timezone

from . import net
from .net import Cancelled, NetError


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AuthRequired(Exception):
    pass


def new_result(spec):
    return {
        "dataset_id": spec["id"], "name": spec["name"], "publisher": spec["publisher"],
        "role": spec.get("role", "essential"), "status": "incomplete", "verified_at": now_iso(),
        "checks": [], "count": None, "est_bytes": None, "est_note": None, "fields": [],
        "geometry_type": None, "crs": None, "licence": spec.get("licence_note"),
        "licence_verified": False, "access_url": None, "landing_url": spec.get("landing_url"),
        "notes": [], "error": None,
    }


def check(res, name, ok, detail):
    res["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    return ok


def finish(res, essential_checks_ok=True):
    if res["error"] == "auth":
        res["status"] = "conditional"
    elif essential_checks_ok and res["checks"] and all(c["ok"] for c in res["checks"]):
        res["status"] = "verified"
    else:
        res["status"] = "incomplete"
    return res


# ----------------------------------------------------------------- Esri JSON -> GeoJSON
def _ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return a / 2.0


def esri_geom_to_geojson(g):
    if not g:
        return None
    if "x" in g and "y" in g:
        if g["x"] in (None, "NaN") or g["y"] in (None, "NaN"):
            return None
        return {"type": "Point", "coordinates": [g["x"], g["y"]]}
    if "points" in g:
        return {"type": "MultiPoint", "coordinates": g["points"]}
    if "paths" in g:
        p = g["paths"]
        return {"type": "LineString", "coordinates": p[0]} if len(p) == 1 else {"type": "MultiLineString", "coordinates": p}
    if "rings" in g:
        polys = []
        for ring in g["rings"]:
            if len(ring) < 4:
                continue
            if _ring_area(ring) <= 0:  # clockwise (negative signed area) = outer ring in Esri
                polys.append([ring])
            elif polys:
                polys[-1].append(ring)
            else:
                polys.append([ring])
        if not polys:
            return None
        return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}
    return None


def esri_to_fc(js):
    feats = []
    for f in js.get("features", []):
        feats.append({"type": "Feature", "properties": f.get("attributes") or {},
                      "geometry": esri_geom_to_geojson(f.get("geometry"))})
    return {"type": "FeatureCollection", "features": feats}


def raise_esri_error(js):
    err = js.get("error") if isinstance(js, dict) else None
    if err:
        code = err.get("code")
        if code in (498, 499, 403, 401):
            raise AuthRequired(f"Service requires a token/credentials (code {code}): {err.get('message')}")
        raise NetError(f"ArcGIS error {code}: {err.get('message')} {err.get('details')}")


# ----------------------------------------------------------------- ArcGIS REST
class ArcGISSource:
    kind = "arcgis"

    def __init__(self, spec):
        self.spec = spec
        self._layer_url = None
        self._meta = None

    def _get(self, url, params, cancel=None):
        p = dict(params)
        p.setdefault("f", "json")
        try:
            st, js = net.get_json(url, p, cancel=cancel)
        except NetError as e:
            if e.status in (401, 403):
                raise AuthRequired(f"HTTP {e.status} from service")
            raise
        raise_esri_error(js)
        return js

    def resolve(self, cancel=None):
        if self._layer_url:
            return self._layer_url, self._meta
        base = self.spec["service_url"].rstrip("/")
        if re.search(r"/\d+$", base):
            url = base
            meta = self._get(url, {}, cancel)
        else:
            js = self._get(base, {}, cancel)
            layers = js.get("layers") or []
            if not layers:
                raise NetError("Service lists no layers")
            pat = re.compile(self.spec.get("layer_name_re") or ".*", re.I)
            cands = [l for l in layers if pat.search(l.get("name", ""))] or layers
            url = meta = None
            for l in cands:
                u = f"{base}/{l['id']}"
                m = self._get(u, {}, cancel)
                want = self.spec.get("geometry")
                if m.get("subLayerIds"):
                    continue
                if want and m.get("geometryType") != want:
                    continue
                url, meta = u, m
                break
            if not url:
                raise NetError(f"No layer in service matched name~{pat.pattern!r} and geometry={self.spec.get('geometry')}")
        self._layer_url, self._meta = url, meta
        return url, meta

    def _geom_params(self, bbox):
        if not bbox:
            return {}
        return {"geometry": ",".join(str(round(v, 6)) for v in bbox), "geometryType": "esriGeometryEnvelope",
                "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"}

    def _fmt(self, meta):
        return "geojson" if "geojson" in (meta.get("supportedQueryFormats") or "").lower() else "json"

    def _query(self, url, meta, extra, bbox, cancel=None):
        fmt = self._fmt(meta)
        p = {"where": self.spec.get("where", "1=1"), "outFields": "*", "outSR": "4326", "f": fmt}
        p.update(self._geom_params(bbox))
        p.update(extra)
        js = self._get(url + "/query", p, cancel)
        fc = js if (fmt == "geojson" and js.get("type") == "FeatureCollection") else esri_to_fc(js)
        return fc, js, fmt

    def _count(self, url, bbox, cancel=None):
        p = {"where": self.spec.get("where", "1=1"), "returnCountOnly": "true"}
        p.update(self._geom_params(bbox))
        js = self._get(url + "/query", p, cancel)
        if "count" not in js:
            raise NetError(f"Count query returned no 'count': {str(js)[:150]}")
        return int(js["count"])

    def verify(self, bbox=None, cancel=None):
        res = new_result(self.spec)
        try:
            url, meta = self.resolve(cancel)
            res["access_url"] = url
            check(res, "Layer metadata reachable", True, f"{meta.get('name')} (type {meta.get('type')}, server v{meta.get('currentVersion')})")
            res["fields"] = [{"name": f["name"], "type": f.get("type", ""), "alias": f.get("alias", "")} for f in meta.get("fields", [])]
            res["geometry_type"] = meta.get("geometryType")
            sr = meta.get("extent", {}).get("spatialReference") or {}
            wkid = sr.get("latestWkid") or sr.get("wkid")
            res["crs"] = f"EPSG:{wkid}" if wkid else None
            check(res, "Native CRS identified", bool(wkid), res["crs"] or "not stated in layer metadata")
            caps = meta.get("capabilities", "")
            check(res, "Query operation supported", ("Query" in caps) or not caps, f"capabilities={caps or 'not listed'}")
            fmts = meta.get("supportedQueryFormats", "") or "not listed"
            res["notes"].append(f"Supported query formats: {fmts}; max records/request: {meta.get('maxRecordCount')}")
            n = self._count(url, bbox, cancel)
            res["count"] = n
            check(res, "Record count > 0 for study extent", n > 0, f"{n} features")
            if n > 0:
                fc, _, fmt = self._query(url, meta, {"resultRecordCount": 5}, bbox, cancel)
                feats = fc.get("features", [])
                check(res, "Sample inspected (≤5 features)", len(feats) > 0, f"{len(feats)} features parsed via f={fmt}")
                if feats:
                    gts = {(f.get("geometry") or {}).get("type") for f in feats}
                    check(res, "Sample geometry present", None not in gts, f"geometry types: {sorted(map(str, gts))}")
                    avg = len(json.dumps(feats)) / len(feats)
                    res["est_bytes"] = int(avg * n)
                    res["est_note"] = "Rough estimate from a 5-feature sample; polygon/line size varies a lot."
            names = [f["name"] for f in res["fields"]]
            for rx in self.spec.get("required_field_res", []):
                hits = [x for x in names if re.search(rx, x, re.I)]
                check(res, f"Required field matching /{rx}/", bool(hits), ", ".join(hits[:6]) or "no matching field")
            lic_src = " ".join([meta.get("copyrightText") or "", strip_html(meta.get("description"))])
            m = re.search(r"(CC[ -]BY[^.;,\n]{0,30}|Creative Commons[^.;\n]{0,60}|licen[cs]ed? [^.;\n]{0,60})", lic_src, re.I)
            if m:
                res["licence"] = f"Stated in service metadata: {m.group(0).strip()}"
                res["licence_verified"] = True
            else:
                res["licence"] = (self.spec.get("licence_note") or "") + " | Service metadata states: " + (meta.get("copyrightText") or "no copyright text") + ". No licence statement found in metadata — confirm before sharing."
            res["last_edit"] = (meta.get("editingInfo") or {}).get("lastEditDate")
            res["meta_description"] = strip_html(meta.get("description"))[:600]
            res["name_field"] = self.spec.get("name_field_re") and next((x for x in names if re.search(self.spec["name_field_re"], x, re.I) and "ASCII" not in x.upper()), None)
            return finish(res)
        except AuthRequired as e:
            res["error"] = "auth"
            check(res, "Open access (no credentials)", False, e)
            return finish(res)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - recorded verbatim as a failed check
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress = ctx["cancel"], ctx["progress"]
        url, meta = self.resolve(cancel)
        bbox = ctx.get("bbox") if self.spec.get("server_subset", True) else None
        total = self._count(url, bbox, cancel)
        maxrec = int(meta.get("maxRecordCount") or 1000)
        page = max(1, min(maxrec, self.spec.get("page_size", 1000)))
        adv = meta.get("advancedQueryCapabilities") or {}
        paginated = adv.get("supportsPagination", True)
        os.makedirs(ctx["checkpoint_dir"], exist_ok=True)
        oid = meta.get("objectIdField") or next((f["name"] for f in meta.get("fields", []) if f.get("type") == "esriFieldTypeOID"), None)
        feats, warnings, nbytes, fmt_used = [], [], 0, None
        ids = None
        if not paginated:
            js = self._get(url + "/query", {"where": self.spec.get("where", "1=1"), "returnIdsOnly": "true", **self._geom_params(bbox)}, cancel)
            ids = js.get("objectIds") or []
            warnings.append("Service does not support pagination; fetched by object-ID batches.")
        n_pages = (total + page - 1) // page
        for i in range(n_pages):
            if cancel.is_set():
                raise Cancelled()
            cp = os.path.join(ctx["checkpoint_dir"], f"page_{i:06d}.json")
            if os.path.exists(cp):
                with open(cp, "r", encoding="utf-8") as f:
                    fc = json.load(f)
            else:
                if paginated:
                    extra = {"resultOffset": i * page, "resultRecordCount": page}
                    if oid:
                        extra["orderByFields"] = oid
                else:
                    batch = ids[i * page:(i + 1) * page]
                    extra = {"objectIds": ",".join(map(str, batch))}
                fc, _, fmt_used = self._query(url, meta, extra, None if not paginated else bbox, cancel)
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(fc, f)
            feats.extend(fc.get("features", []))
            nbytes += os.path.getsize(cp)
            progress(records=len(feats), total=total, bytes=nbytes, message=f"page {i + 1}/{n_pages}")
            if not fc.get("features"):
                warnings.append(f"Empty page at offset {i * page}; stopping early.")
                break
        if len(feats) != total:
            warnings.append(f"Fetched {len(feats)} features but count query reported {total}.")
        out = ctx["raw_path"]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
        shutil.rmtree(ctx["checkpoint_dir"], ignore_errors=True)  # merged file written; page cache no longer needed
        return {
            "raw_files": [{"file": os.path.basename(out), "bytes": os.path.getsize(out), "sha256": sha256_file(out)}],
            "records": len(feats), "warnings": warnings, "source_urls": [url + "/query"],
            "native_crs": None, "note": "Server-side reprojected to EPSG:4326 (outSR=4326); original CRS is " + str((meta.get('extent') or {}).get('spatialReference')),
            "format_requested": fmt_used or self._fmt(meta),
        }

    def load_fc(self, ctx_files, base_dir):
        with open(os.path.join(base_dir, ctx_files[0]["file"]), "r", encoding="utf-8") as f:
            return json.load(f)


# ----------------------------------------------------------------- GeoNet FDSN event service
FDSN_BASE = "https://service.geonet.org.nz/fdsnws/event/1/query"


def parse_fdsn_text(text):
    cols, rows, skipped = None, [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            cols = [c.strip() for c in line.lstrip("#").split("|")]
            continue
        if cols is None:
            continue
        parts = line.split("|")
        if len(parts) != len(cols):
            skipped += 1
            continue
        rows.append(dict(zip(cols, [p.strip() for p in parts])))
    return cols, rows, skipped


def fdsn_rows_to_fc(rows):
    feats = []
    for r in rows:
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except (KeyError, ValueError):
            continue
        def num(k):
            try:
                return float(r[k])
            except (KeyError, ValueError):
                return None
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"eventid": r.get("EventID"), "time": r.get("Time"), "depth_km": num("Depth/km"),
                                     "magnitude": num("Magnitude"), "magtype": r.get("MagType"),
                                     "location": r.get("EventLocationName"), "author": r.get("Author"),
                                     "catalog": r.get("Catalog")}})
    return {"type": "FeatureCollection", "features": feats}


class GeoNetFDSN:
    kind = "fdsn"

    def __init__(self, spec):
        self.spec = spec

    # New Zealand region incl. Kermadec/Chatham; without a box GeoNet returns worldwide events.
    NZ_BOX = (165.0, -49.0, 180.0, -28.0)  # minlon, minlat, maxlon, maxlat

    def _params(self, bbox, years=None):
        # NB: GeoNet's FDSN service rejects the standard "limit" parameter (HTTP 400), so it is never sent.
        # Verification keeps the response small by using a shorter time window instead.
        end = datetime.now(timezone.utc) + timedelta(days=1)
        start = datetime.now(timezone.utc) - timedelta(days=int(365.25 * (years or self.spec.get("years", 10))))
        b = bbox or self.NZ_BOX
        return {"starttime": start.strftime("%Y-%m-%dT00:00:00"), "endtime": end.strftime("%Y-%m-%dT00:00:00"),
                "minmagnitude": self.spec.get("minmag", 5), "orderby": "time", "format": "text",
                "minlongitude": b[0], "minlatitude": b[1], "maxlongitude": b[2], "maxlatitude": b[3]}

    def verify(self, bbox=None, cancel=None):
        res = new_result(self.spec)
        res["access_url"] = FDSN_BASE
        try:
            st, hdrs, body = net.request(FDSN_BASE, self._params(bbox, years=2), cancel=cancel)
            check(res, "FDSN event service reachable", st in (200, 204), f"HTTP {st}")
            if st == 204 or not body:
                check(res, "Events returned for window", False, "HTTP 204: no events for this window/extent")
                return finish(res)
            cols, rows, skipped = parse_fdsn_text(body.decode("utf-8", "replace"))
            res["fields"] = [{"name": c, "type": "string", "alias": ""} for c in (cols or [])]
            need = {"EventID", "Time", "Latitude", "Longitude", "Depth/km", "Magnitude"}
            missing = sorted(need - set(cols or []))
            check(res, "Expected columns present", not missing, f"missing: {missing}" if missing else ", ".join(cols or []))
            check(res, "Sample rows parsed (last 2 years)", len(rows) > 0, f"{len(rows)} rows, {skipped} malformed")
            fc = fdsn_rows_to_fc(rows)
            mags = [f["properties"]["magnitude"] for f in fc["features"] if f["properties"]["magnitude"] is not None]
            check(res, "Magnitudes numeric and ≥ requested minimum", bool(mags) and min(mags) >= self.spec.get("minmag", 5) - 1e-9,
                  f"min={min(mags) if mags else None}")
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (lat/lon as served)"
            res["notes"].append("FDSN event service does not report a total count; actual number of events is known only after download.")
            res["est_note"] = "Size unknown until download (text catalogue; expected small)."
            res["licence"] = "GeoNet data policy — believed CC BY 4.0 (NOT verified by this app; confirm at geonet.org.nz)"
            return finish(res)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress = ctx["cancel"], ctx["progress"]
        progress(records=None, total=None, bytes=0, message="requesting catalogue (single request, size unknown)")
        st, hdrs, body = net.request(FDSN_BASE, self._params(ctx.get("bbox")), cancel=cancel, timeout=180)
        if st == 204 or not body:
            raise NetError("GeoNet FDSN returned no events for this window/extent")
        raw = ctx["raw_path"]
        with open(raw, "wb") as f:
            f.write(body)
        cols, rows, skipped = parse_fdsn_text(body.decode("utf-8", "replace"))
        warns = []
        if skipped:
            warns.append(f"{skipped} malformed rows skipped during parsing (originals preserved in raw text).")
        if len(rows) >= 20000:
            warns.append("Row count is large; the service may have truncated results — verify against GeoNet.")
        progress(records=len(rows), total=len(rows), bytes=len(body), message="catalogue received")
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": len(body), "sha256": sha256_file(raw)}],
                "records": len(rows), "warnings": warns, "source_urls": [net.build_url(FDSN_BASE, self._params(ctx.get('bbox')))],
                "note": "Original FDSN pipe-delimited text preserved; GeoJSON working copy derived from it.", "format_requested": "text"}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8", errors="replace") as f:
            cols, rows, _ = parse_fdsn_text(f.read())
        return fdsn_rows_to_fc(rows)


# ----------------------------------------------------------------- GeoNet quake API (GeoJSON)
QUAKE_URL = "https://api.geonet.org.nz/quake"


class GeoNetQuakeAPI:
    kind = "geonet_quake"
    HDR = {"Accept": "application/vnd.geo+json;version=2"}

    def __init__(self, spec):
        self.spec = spec

    def verify(self, bbox=None, cancel=None):
        res = new_result(self.spec)
        res["access_url"] = QUAKE_URL
        try:
            st, js = net.get_json(QUAKE_URL, {"MMI": self.spec.get("mmi", 3)}, headers=self.HDR, cancel=cancel)
            check(res, "GeoNet quake API reachable", st == 200, f"HTTP {st}")
            feats = (js or {}).get("features", [])
            check(res, "FeatureCollection with features", bool(feats), f"{len(feats)} features")
            if feats:
                keys = set(feats[0].get("properties", {}))
                need = {"publicID", "time", "depth", "magnitude", "mmi", "locality"}
                check(res, "Expected properties present", need <= keys, f"found: {sorted(keys)}")
                times = sorted(f["properties"].get("time", "") for f in feats)
                res["notes"].append(f"Sample time span returned by API: {times[0]} → {times[-1]} (determined by GeoNet, not chosen by this app)")
                res["fields"] = [{"name": k, "type": "", "alias": ""} for k in sorted(keys)]
            res["count"] = len(feats)
            res["est_bytes"] = len(json.dumps(feats)) if feats else None
            res["est_note"] = "Exact size of current response."
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (GeoJSON)"
            res["licence"] = "GeoNet data policy — believed CC BY 4.0 (NOT verified by this app; confirm at geonet.org.nz)"
            res["notes"].append("API returns a fixed recent window; no server-side bounding-box subset — regional clipping happens locally.")
            return finish(res)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        st, hdrs, body = net.request(QUAKE_URL, {"MMI": self.spec.get("mmi", 3)}, headers=self.HDR, cancel=ctx["cancel"])
        raw = ctx["raw_path"]
        with open(raw, "wb") as f:
            f.write(body)
        fc = json.loads(body.decode("utf-8"))
        n = len(fc.get("features", []))
        ctx["progress"](records=n, total=n, bytes=len(body), message="received")
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": len(body), "sha256": sha256_file(raw)}],
                "records": n, "warnings": [], "source_urls": [net.build_url(QUAKE_URL, {"MMI": self.spec.get("mmi", 3)})],
                "note": "Raw API response preserved unchanged.", "format_requested": "geojson"}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8") as f:
            return json.load(f)


# ----------------------------------------------------------------- GBIF occurrence search API
GBIF = "https://api.gbif.org/v1"
GBIF_KEEP = ["gbifID", "occurrenceID", "scientificName", "species", "family", "decimalLatitude", "decimalLongitude",
             "coordinateUncertaintyInMeters", "eventDate", "year", "month", "day", "basisOfRecord", "datasetKey",
             "datasetName", "publishingOrgKey", "license", "countryCode", "stateProvince", "locality", "issues",
             "individualCount", "samplingProtocol", "recordedBy", "institutionCode", "occurrenceStatus"]


def gbif_to_fc(records):
    feats = []
    for r in records:
        lat, lon = r.get("decimalLatitude"), r.get("decimalLongitude")
        geom = {"type": "Point", "coordinates": [lon, lat]} if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None
        props = {k: r.get(k) for k in GBIF_KEEP if k in r}
        if isinstance(props.get("issues"), list):
            props["issues"] = ";".join(props["issues"])
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


class GBIFSource:
    kind = "gbif"

    def __init__(self, spec):
        self.spec = spec
        self._key = None

    def _taxon_key(self, cancel=None):
        if self._key:
            return self._key
        st, js = net.get_json(f"{GBIF}/species/match", {"name": self.spec["taxon_name"], "rank": self.spec["taxon_rank"]}, cancel=cancel)
        if not js or js.get("matchType") in (None, "NONE") or not js.get("usageKey"):
            raise NetError(f"GBIF backbone has no match for {self.spec['taxon_name']} ({self.spec['taxon_rank']})")
        if str(js.get("rank", "")).upper() != self.spec["taxon_rank"].upper():
            raise NetError(f"GBIF matched {js.get('canonicalName')} at rank {js.get('rank')}, expected {self.spec['taxon_rank']}")
        self._key = js["usageKey"]
        self._match = js
        return self._key

    def _params(self, bbox, **extra):
        p = {"taxonKey": self._key, "country": "NZ", "hasCoordinate": "true"}
        if bbox:
            x0, y0, x1, y1 = bbox
            p["geometry"] = f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"
        p.update(extra)
        return p

    def verify(self, bbox=None, cancel=None):
        res = new_result(self.spec)
        res["access_url"] = f"{GBIF}/occurrence/search"
        try:
            key = self._taxon_key(cancel)
            check(res, "Taxon resolved in GBIF backbone", True, f"{self._match.get('canonicalName')} ({self._match.get('rank')}) key={key}, match={self._match.get('matchType')}")
            st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, limit=0), cancel=cancel)
            n = (js or {}).get("count", 0)
            res["count"] = n
            check(res, "Georeferenced NZ records > 0", n > 0, f"{n} records matching taxon + country=NZ + hasCoordinate" + (" + study extent" if bbox else ""))
            if n > 0:
                st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, limit=50), cancel=cancel)
                recs = js.get("results", [])
                fc = gbif_to_fc(recs)
                withgeom = [f for f in fc["features"] if f["geometry"]]
                check(res, "Sample inspected (≤50 records)", len(withgeom) > 0, f"{len(withgeom)}/{len(recs)} have coordinates")
                lons = [f["geometry"]["coordinates"][0] for f in withgeom]
                lats = [f["geometry"]["coordinates"][1] for f in withgeom]
                inz = all(-56 <= la <= -26 and (lo >= 160 or lo <= -170) for la, lo in zip(lats, lons))
                check(res, "Sample coordinates plausible for NZ region", inz, "all within NZ-region envelope" if inz else "some sample records fall outside the NZ-region envelope")
                lic = sorted({str(r.get("license")) for r in recs})
                res["licence"] = "Per-record licences in sample: " + ", ".join(lic) + " (GBIF records carry individual licences; some may be non-commercial)"
                res["licence_verified"] = True
                res["est_bytes"] = int(n * 1400)
                res["est_note"] = "Estimate: ~1.4 kB per raw record JSON (not measured)."
                if n > 100000:
                    res["error"] = "auth"
                    res["notes"].append("More than 100,000 records: the search API cannot page beyond that. A GBIF download request requires a free GBIF account (manual step).")
                    check(res, "Within search-API paging limit (100,000)", False, f"{n} records")
            res["fields"] = [{"name": k, "type": "", "alias": ""} for k in GBIF_KEEP]
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (WGS84 decimal degrees per Darwin Core)"
            res["notes"].append("These are occurrence records (observations/specimens), not movement tracks or abundance.")
            return finish(res)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress = ctx["cancel"], ctx["progress"]
        self._taxon_key(cancel)
        bbox = ctx.get("bbox")
        st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, limit=0), cancel=cancel)
        total = js.get("count", 0)
        if total > 100000:
            raise NetError(f"{total} records exceeds the 100,000-record search paging limit; a GBIF download (account needed) is required.")
        os.makedirs(ctx["checkpoint_dir"], exist_ok=True)
        page, recs, nbytes = 300, [], 0
        n_pages = (total + page - 1) // page
        for i in range(n_pages):
            if cancel.is_set():
                raise Cancelled()
            cp = os.path.join(ctx["checkpoint_dir"], f"page_{i:06d}.json")
            if os.path.exists(cp):
                with open(cp, "r", encoding="utf-8") as f:
                    pg = json.load(f)
            else:
                st, pg = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, limit=page, offset=i * page), cancel=cancel)
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(pg, f)
            recs.extend(pg.get("results", []))
            nbytes += os.path.getsize(cp)
            progress(records=len(recs), total=total, bytes=nbytes, message=f"page {i + 1}/{n_pages}")
            if pg.get("endOfRecords"):
                break
        raw = ctx["raw_path"]
        with open(raw, "w", encoding="utf-8") as f:
            json.dump({"query": self._params(bbox), "retrieved_at": now_iso(), "count_reported": total, "results": recs}, f)
        shutil.rmtree(ctx["checkpoint_dir"], ignore_errors=True)
        warns = [] if len(recs) == total else [f"Fetched {len(recs)} records but GBIF reported {total}."]
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": os.path.getsize(raw), "sha256": sha256_file(raw)}],
                "records": len(recs), "warnings": warns, "source_urls": [net.build_url(f"{GBIF}/occurrence/search", self._params(bbox))],
                "note": "Original GBIF JSON records preserved; GeoJSON working copy derived (subset of Darwin Core fields).",
                "format_requested": "json"}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8") as f:
            return gbif_to_fc(json.load(f).get("results", []))


SOURCES = {"arcgis": ArcGISSource, "fdsn": GeoNetFDSN, "geonet_quake": GeoNetQuakeAPI, "gbif": GBIFSource}


def make_source(spec):
    return SOURCES[spec["connector"]](spec)
