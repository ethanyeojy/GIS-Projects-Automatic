"""Dataset connectors. Each connector can (a) verify access + inspect a sample, (b) estimate what a filtered download
would contain, and (c) download a filtered subset with real progress, per-file size monitoring and cancellation.

Nothing here fabricates results: every check records what was actually returned by the remote service, or the error.

Common arguments
  opts = {"period": {start,end,...} | None, "filters": {...}}   (see filter_schema for what each source supports)
  ctx  = {cancel, progress, bbox, raw_path, checkpoint_dir, opts, limit_bytes, split, allow_exceed, region}
"""
import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone

from . import net, timeperiod
from .net import Cancelled, NetError, SizeExceeded


class RecordLimitError(Exception):
    """The source cannot deliver this many records (e.g. GBIF paging cap) — the user must choose how to reduce."""

    def __init__(self, total, limit, reason):
        super().__init__(f"{total:,} records match, but {reason} (limit {limit:,})")
        self.total, self.limit, self.reason = total, limit, reason


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
        "notes": [], "error": None, "time_info": None,
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


# What each source type can do — used to decide which recovery options are honest to offer.
CAPS = {
    "arcgis": {"count_before": True, "server_limit": True, "split": True, "period": False, "attr": True},
    "fdsn": {"count_before": False, "server_limit": False, "split": False, "period": True, "attr": False},
    "geonet_quake": {"count_before": True, "server_limit": False, "split": False, "period": False, "attr": False},
    "geojson_url": {"count_before": True, "server_limit": False, "split": False, "period": False, "attr": False},
    "gbif": {"count_before": True, "server_limit": True, "split": True, "period": True, "attr": False},
    "openmeteo": {"count_before": True, "server_limit": False, "split": False, "period": True, "attr": False},
    "file_url": {"count_before": False, "server_limit": False, "split": False, "period": False, "attr": False},
}


def caps(spec):
    return CAPS[spec["connector"]]


def _flt(opts):
    return (opts or {}).get("filters") or {}


def _period(opts):
    p = (opts or {}).get("period")
    return p if p and _flt(opts).get("use_period", True) else None


def _first_n(opts):
    """Record cap, only when the user explicitly chose to keep the first N (never applied silently)."""
    f = _flt(opts)
    n = f.get("max_records")
    return int(n) if n and f.get("on_exceed") == "first_n" else None


def _sql_quote(v):
    return "'" + str(v).replace("'", "''") + "'"


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


# ----------------------------------------------------------------- splitting a result into several files
def write_parts(items, raw_path, limit, wrap):
    """Write `items` as several files, each <= limit bytes. Returns raw_files records. Raises SizeExceeded if one
    single item alone is bigger than the limit (it cannot be split further)."""
    base, ext = os.path.splitext(raw_path)
    n = len(items)
    sample = items[: min(200, n)] or [{}]
    avg = max(1, len(json.dumps(sample, separators=(",", ":"))) // max(1, len(sample)))
    per = max(1, int(limit * 0.9 // avg))
    parts, i, k = [], 0, 1
    while i < n:
        size_n = per
        while True:
            chunk = items[i:i + size_n]
            body = json.dumps(wrap(chunk), separators=(",", ":")).encode("utf-8")
            if len(body) <= limit:
                break
            if size_n == 1:
                raise SizeExceeded(len(body), limit)
            size_n = max(1, size_n // 2)
        path = f"{base}_part{k:03d}{ext}"
        with open(path, "wb") as f:
            f.write(body)
        parts.append({"file": os.path.basename(path), "bytes": len(body), "sha256": sha256_file(path)})
        i += len(chunk)
        k += 1
    return parts


# ----------------------------------------------------------------- ArcGIS REST
class ArcGISSource:
    kind = "arcgis"

    def __init__(self, spec):
        self.spec = spec
        self._layer_url = None
        self._meta = None

    def _get(self, url, params, cancel=None, on_bytes=None):
        p = dict(params)
        p.setdefault("f", "json")
        try:
            st, js = net.get_json(url, p, cancel=cancel, on_bytes=on_bytes)
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

    def _where(self, meta, opts):
        base = self.spec.get("where", "1=1")
        attr = _flt(opts).get("attr")
        if not attr or not attr.get("field") or not attr.get("values"):
            return base
        fld = next((f for f in meta.get("fields", []) if f["name"] == attr["field"]), None)
        if not fld:
            raise NetError(f"Filter field '{attr['field']}' is not in this layer")
        numeric = fld.get("type") in ("esriFieldTypeInteger", "esriFieldTypeSmallInteger", "esriFieldTypeDouble", "esriFieldTypeSingle", "esriFieldTypeOID")
        vals = []
        for v in attr["values"]:
            if numeric:
                try:
                    vals.append(str(float(v)) if "." in str(v) else str(int(v)))
                except ValueError:
                    raise NetError(f"'{v}' is not a number, but field {fld['name']} is numeric")
            else:
                vals.append(_sql_quote(v))
        return f"({base}) AND ({fld['name']} IN ({','.join(vals)}))"

    def _fmt(self, meta):
        return "geojson" if "geojson" in (meta.get("supportedQueryFormats") or "").lower() else "json"

    def _query(self, url, meta, extra, bbox, cancel=None, where=None, on_bytes=None):
        fmt = self._fmt(meta)
        p = {"where": where or self.spec.get("where", "1=1"), "outFields": "*", "outSR": "4326", "f": fmt}
        p.update(self._geom_params(bbox))
        p.update(extra)
        js = self._get(url + "/query", p, cancel, on_bytes)
        fc = js if (fmt == "geojson" and js.get("type") == "FeatureCollection") else esri_to_fc(js)
        return fc, js, fmt

    def _count(self, url, bbox, cancel=None, where=None):
        p = {"where": where or self.spec.get("where", "1=1"), "returnCountOnly": "true"}
        p.update(self._geom_params(bbox))
        js = self._get(url + "/query", p, cancel)
        if "count" not in js:
            raise NetError(f"Count query returned no 'count': {str(js)[:150]}")
        return int(js["count"])

    def distinct_values(self, field, bbox=None, cancel=None, limit=200):
        url, meta = self.resolve(cancel)
        if not any(f["name"] == field for f in meta.get("fields", [])):
            raise NetError(f"No field '{field}' in this layer")
        p = {"where": self.spec.get("where", "1=1"), "outFields": field, "returnDistinctValues": "true", "returnGeometry": "false",
             "orderByFields": field, "resultRecordCount": limit}
        p.update(self._geom_params(bbox))
        js = self._get(url + "/query", p, cancel)
        vals = [f["attributes"].get(field) for f in js.get("features", []) if f["attributes"].get(field) not in (None, "")]
        return vals

    def verify(self, bbox=None, cancel=None, opts=None):
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
            caps_ = meta.get("capabilities", "")
            check(res, "Query operation supported", ("Query" in caps_) or not caps_, f"capabilities={caps_ or 'not listed'}")
            fmts = meta.get("supportedQueryFormats", "") or "not listed"
            res["notes"].append(f"Supported query formats: {fmts}; max records/request: {meta.get('maxRecordCount')}")
            where = self._where(meta, opts)
            n = self._count(url, bbox, cancel, where)
            res["count"] = n
            check(res, "Record count > 0 for study extent" + (" and filters" if _flt(opts).get("attr") else ""), n > 0, f"{n} features")
            if n > 0:
                fc, _, fmt = self._query(url, meta, {"resultRecordCount": 5}, bbox, cancel, where)
                feats = fc.get("features", [])
                sample = list(feats)
                oid_f = meta.get("objectIdField")
                if n > 60 and oid_f and (meta.get("advancedQueryCapabilities") or {}).get("supportsPagination", True):
                    for frac in (0.5, 0.9):  # feature size varies a lot along a layer: also sample the middle and near the end
                        try:
                            f2, _, _ = self._query(url, meta, {"resultOffset": int(n * frac), "resultRecordCount": 5, "orderByFields": oid_f}, bbox, cancel, where)
                            sample += f2.get("features", [])
                        except Exception:  # noqa: BLE001
                            pass
                check(res, "Sample inspected (≤5 features)", len(feats) > 0, f"{len(feats)} features parsed via f={fmt}")
                if feats:
                    gts = {(f.get("geometry") or {}).get("type") for f in feats}
                    check(res, "Sample geometry present", None not in gts, f"geometry types: {sorted(map(str, gts))}")
                    avg = len(json.dumps(sample)) / len(sample)
                    res["est_bytes"] = int(avg * min(n, _first_n(opts) or n))
                    res["est_note"] = f"Estimate from {len(sample)} sampled features (start, middle, end); polygon/line size varies a lot."
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
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001 - recorded verbatim as a failed check
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress, opts = ctx["cancel"], ctx["progress"], ctx.get("opts")
        limit, split, allow = ctx.get("limit_bytes"), ctx.get("split"), ctx.get("allow_exceed")
        url, meta = self.resolve(cancel)
        bbox = ctx.get("bbox") if self.spec.get("server_subset", True) else None
        where = self._where(meta, opts)
        total = self._count(url, bbox, cancel, where)
        cap_n = _first_n(opts)
        if cap_n:
            total = min(total, cap_n)
        maxrec = int(meta.get("maxRecordCount") or 1000)
        page = max(1, min(maxrec, self.spec.get("page_size", 1000)))
        adv = meta.get("advancedQueryCapabilities") or {}
        paginated = adv.get("supportsPagination", True)
        os.makedirs(ctx["checkpoint_dir"], exist_ok=True)
        oid = meta.get("objectIdField") or next((f["name"] for f in meta.get("fields", []) if f.get("type") == "esriFieldTypeOID"), None)
        feats, warnings, nbytes, fmt_used = [], [], 0, None
        ids = None
        if not paginated:
            js = self._get(url + "/query", {"where": where, "returnIdsOnly": "true", **self._geom_params(bbox)}, cancel)
            ids = (js.get("objectIds") or [])[: cap_n or None]
            warnings.append("Service does not support pagination; fetched by object-ID batches.")
        n_pages = (total + page - 1) // page
        for i in range(n_pages):
            if cancel.is_set():
                raise Cancelled()
            cp = os.path.join(ctx["checkpoint_dir"], f"page_{i:06d}.json")
            want = min(page, total - i * page)
            fc = _cp_load(cp)
            if fc is None:
                if paginated:
                    extra = {"resultOffset": i * page, "resultRecordCount": want}
                    if oid:
                        extra["orderByFields"] = oid
                else:
                    batch = ids[i * page:(i + 1) * page]
                    extra = {"objectIds": ",".join(map(str, batch))}
                fc, _, fmt_used = self._query(url, meta, extra, None if not paginated else bbox, cancel, where,
                                              on_bytes=lambda n, i=i: progress(message=f"page {i + 1}/{n_pages}: receiving {n / 1e6:.1f} MB"))
                _cp_save(cp, fc)
            feats.extend(fc.get("features", []))
            nbytes += os.path.getsize(cp)
            progress(records=len(feats), total=total, bytes=nbytes, message=f"page {i + 1}/{n_pages}")
            if limit and not split and not allow and nbytes > limit:
                raise SizeExceeded(nbytes, limit)
            if not fc.get("features"):
                warnings.append(f"Empty page at offset {i * page}; stopping early.")
                break
        if len(feats) != total:
            warnings.append(f"Fetched {len(feats)} features but the query reported {total}.")
        if cap_n:
            warnings.append(f"Kept the first {cap_n:,} features in the service's own order (as you chose); not a random sample.")
        out = ctx["raw_path"]
        if split and limit:
            raw_files = write_parts(feats, out, limit, lambda ch: {"type": "FeatureCollection", "features": ch})
            if len(raw_files) > 1:
                warnings.append(f"Split into {len(raw_files)} files of at most {limit / 1e6:.0f} MB each (as you chose).")
        else:
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
            size = os.path.getsize(out)
            if limit and not allow and size > limit:
                os.remove(out)
                raise SizeExceeded(size, limit)
            raw_files = [{"file": os.path.basename(out), "bytes": size, "sha256": sha256_file(out)}]
        shutil.rmtree(ctx["checkpoint_dir"], ignore_errors=True)  # merged file written; page cache no longer needed
        return {
            "raw_files": raw_files, "records": len(feats), "warnings": warnings, "source_urls": [url + "/query"],
            "native_crs": None, "note": "Server-side reprojected to EPSG:4326 (outSR=4326); original CRS is " + str((meta.get('extent') or {}).get('spatialReference')),
            "format_requested": fmt_used or self._fmt(meta),
        }

    def load_fc(self, ctx_files, base_dir):
        feats = []
        for rf in ctx_files:
            with open(os.path.join(base_dir, rf["file"]), "r", encoding="utf-8") as f:
                feats.extend(json.load(f).get("features", []))
        return {"type": "FeatureCollection", "features": feats}


def _cp_load(cp):
    """A saved download page, or None if it is missing or was cut off (e.g. the attempt was stopped mid-write)."""
    try:
        with open(cp, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        try:
            os.remove(cp)  # damaged page: fetch it again
        except OSError:
            pass
        return None


def _cp_save(cp, obj):
    """Write a page all-or-nothing, so a stopped attempt can never leave half a file behind."""
    tmp = f"{cp}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, cp)


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
    # New Zealand region incl. Kermadec/Chatham; without a box GeoNet returns worldwide events.
    NZ_BOX = (165.0, -49.0, 180.0, -28.0)  # minlon, minlat, maxlon, maxlat

    def __init__(self, spec):
        self.spec = spec

    def _params(self, bbox, opts=None, years=None):
        # NB: GeoNet's FDSN service rejects the standard "limit" parameter (HTTP 400), so it is never sent.
        f = _flt(opts)
        p = _period(opts)
        if years is not None or not p:  # verification sample / no period chosen: a fixed trailing window
            end = datetime.now(timezone.utc) + timedelta(days=1)
            start = datetime.now(timezone.utc) - timedelta(days=int(365.25 * (years or self.spec.get("years", 10))))
            s, e = start.strftime("%Y-%m-%dT00:00:00"), end.strftime("%Y-%m-%dT00:00:00")
        else:
            s = p["start"] + "T00:00:00"
            e = (datetime.strptime(p["end"], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        b = bbox or self.NZ_BOX
        q = {"starttime": s, "endtime": e, "minmagnitude": f.get("minmag") if f.get("minmag") not in (None, "") else self.spec.get("minmag", 5),
             "orderby": "time", "format": "text",
             "minlongitude": b[0], "minlatitude": b[1], "maxlongitude": b[2], "maxlatitude": b[3]}
        if f.get("maxdepth") not in (None, ""):
            q["maxdepth"] = f["maxdepth"]
        return q

    def verify(self, bbox=None, cancel=None, opts=None):
        res = new_result(self.spec)
        res["access_url"] = FDSN_BASE
        try:
            minmag = float(self._params(bbox, opts)["minmagnitude"])
            # With a sensible magnitude floor the whole answer is small, so fetch it: an exact count and size.
            exact = minmag >= 4.0
            st, hdrs, body = net.request(FDSN_BASE, self._params(bbox, opts, years=None if exact else 2), cancel=cancel, timeout=90)
            check(res, "FDSN event service reachable", st in (200, 204), f"HTTP {st}")
            if st == 204 or not body:
                res["count"] = 0
                check(res, "Events returned for window", False, "HTTP 204: no events for this window/extent")
                return finish(res)
            cols, rows, skipped = parse_fdsn_text(body.decode("utf-8", "replace"))
            res["fields"] = [{"name": c, "type": "string", "alias": ""} for c in (cols or [])]
            need = {"EventID", "Time", "Latitude", "Longitude", "Depth/km", "Magnitude"}
            missing = sorted(need - set(cols or []))
            check(res, "Expected columns present", not missing, f"missing: {missing}" if missing else ", ".join(cols or []))
            check(res, "Sample rows parsed", len(rows) > 0, f"{len(rows)} rows, {skipped} malformed")
            fc = fdsn_rows_to_fc(rows)
            mags = [f["properties"]["magnitude"] for f in fc["features"] if f["properties"]["magnitude"] is not None]
            check(res, "Magnitudes numeric and ≥ requested minimum", bool(mags) and min(mags) >= minmag - 1e-9, f"min={min(mags) if mags else None}")
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (lat/lon as served)"
            if exact:
                res["count"] = len(rows)
                res["est_bytes"] = len(body)
                res["est_note"] = "Exact: the catalogue query was run to count it."
            else:
                res["notes"].append("Magnitude floor is low, so the total is only known after download; the check used a 2-year sample.")
                res["est_note"] = "Size unknown until download (text catalogue)."
            res["licence"] = "GeoNet data policy — believed CC BY 4.0 (NOT verified by this app; confirm at geonet.org.nz)"
            res["time_info"] = {"supports_period": True}
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress, opts = ctx["cancel"], ctx["progress"], ctx.get("opts")
        limit = None if ctx.get("allow_exceed") else ctx.get("limit_bytes")
        progress(records=None, total=None, bytes=0, message="requesting catalogue (one request; total size unknown until it arrives)")
        params = self._params(ctx.get("bbox"), opts)
        st, hdrs, body = net.request(FDSN_BASE, params, cancel=cancel, timeout=180, max_bytes=limit,
                                     on_bytes=lambda n: progress(bytes=n, message=f"receiving catalogue: {n / 1e6:.2f} MB so far"))
        if st == 204 or not body:
            raise NetError("GeoNet FDSN returned no events for this period/area")
        cols, rows, skipped = parse_fdsn_text(body.decode("utf-8", "replace"))
        warns = []
        cap_n = _first_n(opts)
        if cap_n and len(rows) > cap_n:
            lines = body.decode("utf-8", "replace").splitlines()
            head = [l for l in lines if l.startswith("#")]
            data = [l for l in lines if l.strip() and not l.startswith("#")][:cap_n]
            body = ("\n".join(head + data) + "\n").encode("utf-8")
            rows = rows[:cap_n]
            warns.append(f"Kept the newest {cap_n:,} events (as you chose); older matching events were left out.")
        raw = ctx["raw_path"]
        with open(raw, "wb") as f:
            f.write(body)
        if skipped:
            warns.append(f"{skipped} malformed rows skipped during parsing (originals preserved in raw text).")
        progress(records=len(rows), total=len(rows), bytes=len(body), message="catalogue received")
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": len(body), "sha256": sha256_file(raw)}],
                "records": len(rows), "warnings": warns, "source_urls": [net.build_url(FDSN_BASE, params)],
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

    def verify(self, bbox=None, cancel=None, opts=None):
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
                res["time_info"] = {"first": times[0][:10], "last": times[-1][:10]}
                res["fields"] = [{"name": k, "type": "", "alias": ""} for k in sorted(keys)]
            res["count"] = len(feats)
            res["est_bytes"] = len(json.dumps(feats)) if feats else None
            res["est_note"] = "Exact size of current response."
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (GeoJSON)"
            res["licence"] = "GeoNet data policy — believed CC BY 4.0 (NOT verified by this app; confirm at geonet.org.nz)"
            res["notes"].append("API returns a fixed recent window; no server-side bounding-box subset — regional clipping happens locally.")
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        limit = None if ctx.get("allow_exceed") else ctx.get("limit_bytes")
        st, hdrs, body = net.request(QUAKE_URL, {"MMI": self.spec.get("mmi", 3)}, headers=self.HDR, cancel=ctx["cancel"], max_bytes=limit,
                                     on_bytes=lambda n: ctx["progress"](bytes=n, message=f"receiving: {n / 1e3:.0f} kB"))
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


# ----------------------------------------------------------------- generic GeoJSON-over-HTTP endpoint
class GeoJSONURL:
    """Any open endpoint that returns a GeoJSON FeatureCollection (e.g. GeoNet volcano alert levels)."""
    kind = "geojson_url"

    def __init__(self, spec):
        self.spec = spec

    def _get(self, cancel=None, **kw):
        return net.request(self.spec["url"], self.spec.get("params"), headers=self.spec.get("headers"), cancel=cancel, **kw)

    def verify(self, bbox=None, cancel=None, opts=None):
        res = new_result(self.spec)
        res["access_url"] = self.spec["url"]
        try:
            st, hdrs, body = self._get(cancel)
            check(res, "Endpoint reachable", st == 200, f"HTTP {st}")
            js = json.loads(body.decode("utf-8", "replace"))
            feats = js.get("features", []) if isinstance(js, dict) else []
            check(res, "FeatureCollection with features", bool(feats), f"{len(feats)} features")
            if feats:
                keys = set(feats[0].get("properties") or {})
                need = set(self.spec.get("required_props", []))
                check(res, "Expected properties present", need <= keys, f"found: {sorted(keys)}")
                gts = {(f.get("geometry") or {}).get("type") for f in feats}
                check(res, "Geometry present", None not in gts, f"geometry types: {sorted(map(str, gts))}")
                res["fields"] = [{"name": k, "type": "", "alias": ""} for k in sorted(keys)]
            res["count"] = len(feats)
            res["est_bytes"] = len(body)
            res["est_note"] = "Exact size of current response."
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (GeoJSON)"
            res["licence"] = self.spec.get("licence_note", "not stated")
            res["notes"].extend(self.spec.get("notes", []))
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        limit = None if ctx.get("allow_exceed") else ctx.get("limit_bytes")
        st, hdrs, body = self._get(ctx["cancel"], max_bytes=limit, on_bytes=lambda n: ctx["progress"](bytes=n, message=f"receiving: {n / 1e3:.0f} kB"))
        raw = ctx["raw_path"]
        with open(raw, "wb") as f:
            f.write(body)
        n = len(json.loads(body.decode("utf-8")).get("features", []))
        ctx["progress"](records=n, total=n, bytes=len(body), message="received")
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": len(body), "sha256": sha256_file(raw)}],
                "records": n, "warnings": [], "source_urls": [net.build_url(self.spec["url"], self.spec.get("params"))],
                "note": "Raw response preserved unchanged.", "format_requested": "geojson"}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8") as f:
            return json.load(f)


# ----------------------------------------------------------------- direct file link (CSV / GeoJSON) from a catalogue
_LAT = ("lat", "latitude", "y", "lat_wgs84", "decimallatitude")
_LON = ("lon", "lng", "long", "longitude", "x", "lon_wgs84", "decimallongitude")


def csv_to_fc(text):
    """CSV -> FeatureCollection. Rows become Points if recognisable lat/lon columns exist, else geometry-less records."""
    rd = csv.DictReader(io.StringIO(text))
    cols = rd.fieldnames or []
    low = {c.lower().strip(): c for c in cols}
    la = next((low[k] for k in _LAT if k in low), None)
    lo = next((low[k] for k in _LON if k in low), None)
    feats = []
    for row in rd:
        g = None
        if la and lo:
            try:
                g = {"type": "Point", "coordinates": [float(row[lo]), float(row[la])]}
            except (ValueError, TypeError):
                g = None
        feats.append({"type": "Feature", "geometry": g, "properties": dict(row)})
    return {"type": "FeatureCollection", "features": feats}


class FileURL:
    """A direct link to a CSV or GeoJSON file. Size is read from the server before downloading (HEAD)."""
    kind = "file_url"

    def __init__(self, spec):
        self.spec = spec

    def _head(self, cancel=None):
        try:
            st, h, _ = net.request(self.spec["url"], method="HEAD", cancel=cancel, retries=1, timeout=30)
            return st, h
        except NetError as e:
            if e.status in (403, 405, 501):  # some hosts refuse HEAD; fall back to a tiny ranged GET
                try:
                    st, h, _ = net.request(self.spec["url"], headers={"Range": "bytes=0-1023"}, cancel=cancel, retries=1, timeout=30)
                    return st, h
                except NetError:
                    pass
            raise

    def verify(self, bbox=None, cancel=None, opts=None):
        res = new_result(self.spec)
        res["access_url"] = self.spec["url"]
        try:
            st, h = self._head(cancel)
            check(res, "File link reachable", st in (200, 206), f"HTTP {st}")
            size = h.get("Content-Length") or (h.get("Content-Range", "").split("/")[-1] if "/" in h.get("Content-Range", "") else None)
            if size and str(size).isdigit():
                res["est_bytes"] = int(size)
                res["est_note"] = "Exact: file size reported by the server."
            else:
                res["est_note"] = "The server did not report a file size."
            res["notes"].append(f"Content type: {h.get('Content-Type', 'not stated')}; format: {self.spec.get('format', 'unknown')}")
            res["licence"] = self.spec.get("licence_note", "not stated — confirm with the publisher")
            res["geometry_type"] = None
            res["notes"].append("Direct file download: no server-side filtering — filter after download.")
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        limit = None if ctx.get("allow_exceed") else ctx.get("limit_bytes")
        fmt = self.spec.get("format", "csv")
        st, h, body = net.request(self.spec["url"], cancel=ctx["cancel"], timeout=120, max_bytes=limit,
                                  on_bytes=lambda n: ctx["progress"](bytes=n, message=f"receiving: {n / 1e6:.2f} MB"))
        raw = ctx["raw_path"]
        with open(raw, "wb") as f:
            f.write(body)
        text = body.decode("utf-8-sig", "replace")
        n = len(csv_to_fc(text)["features"]) if fmt == "csv" else len(json.loads(text).get("features", []))
        ctx["progress"](records=n, total=n, bytes=len(body), message="received")
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": len(body), "sha256": sha256_file(raw)}], "records": n, "warnings": [],
                "source_urls": [self.spec["url"]], "note": "Original file preserved unchanged.", "format_requested": fmt}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        return csv_to_fc(text) if self.spec.get("format", "csv") == "csv" else json.loads(text)


# ----------------------------------------------------------------- GBIF occurrence search API
GBIF = "https://api.gbif.org/v1"
GBIF_PAGING_CAP = 100000
GBIF_KEEP = ["gbifID", "occurrenceID", "scientificName", "species", "family", "decimalLatitude", "decimalLongitude",
             "coordinateUncertaintyInMeters", "eventDate", "year", "month", "day", "basisOfRecord", "datasetKey",
             "datasetName", "publishingOrgKey", "license", "countryCode", "stateProvince", "locality", "issues",
             "individualCount", "samplingProtocol", "recordedBy", "institutionCode", "occurrenceStatus"]
GBIF_BASIS = ["HUMAN_OBSERVATION", "PRESERVED_SPECIMEN", "MACHINE_OBSERVATION", "MATERIAL_SAMPLE", "OBSERVATION", "LIVING_SPECIMEN", "FOSSIL_SPECIMEN"]


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

    def _params(self, bbox, opts=None, **extra):
        p = {"taxonKey": self._key, "country": "NZ", "hasCoordinate": "true"}
        if bbox:
            x0, y0, x1, y1 = bbox
            p["geometry"] = f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"
        per, f = _period(opts), _flt(opts)
        if per:
            y0_, y1_ = timeperiod.years(per)
            p["year"] = f"{y0_},{y1_}"
        if f.get("basis"):
            p["basisOfRecord"] = f["basis"]
        if f.get("max_uncertainty") not in (None, ""):
            p["coordinateUncertaintyInMeters"] = f"0,{int(float(f['max_uncertainty']))}"
        p.update(extra)
        return p

    def verify(self, bbox=None, cancel=None, opts=None):
        res = new_result(self.spec)
        res["access_url"] = f"{GBIF}/occurrence/search"
        try:
            key = self._taxon_key(cancel)
            check(res, "Taxon resolved in GBIF backbone", True, f"{self._match.get('canonicalName')} ({self._match.get('rank')}) key={key}, match={self._match.get('matchType')}")
            st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, opts, limit=0), cancel=cancel)
            n = (js or {}).get("count", 0)
            res["count"] = n
            per = _period(opts)
            what = "taxon + country=NZ + hasCoordinate" + (" + study extent" if bbox else "") + (f" + years {timeperiod.years(per)[0]}–{timeperiod.years(per)[1]}" if per else "") + (" + your filters" if _flt(opts).get("basis") or _flt(opts).get("max_uncertainty") else "")
            check(res, "Georeferenced NZ records > 0", n > 0, f"{n} records matching {what}")
            if n > 0:
                st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, opts, limit=50), cancel=cancel)
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
                shown = min(n, _first_n(opts) or n)
                res["est_bytes"] = int(shown * 1400)
                res["est_note"] = "Estimate: ~1.4 kB per raw record JSON (not measured)."
                years = sorted(r["year"] for r in recs if r.get("year"))
                if years:
                    res["time_info"] = {"sample_years": [years[0], years[-1]]}
                if n > GBIF_PAGING_CAP and not _first_n(opts):
                    res["error"] = "auth"
                    res["notes"].append(f"More than {GBIF_PAGING_CAP:,} records: the search API cannot page beyond that. Narrow the area, years or record type — or keep only the first {GBIF_PAGING_CAP:,}. (A full GBIF download needs a free GBIF account: manual step.)")
                    check(res, f"Within search-API paging limit ({GBIF_PAGING_CAP:,})", False, f"{n:,} records")
            res["fields"] = [{"name": k, "type": "", "alias": ""} for k in GBIF_KEEP]
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (WGS84 decimal degrees per Darwin Core)"
            res["notes"].append("These are occurrence records (observations/specimens), not movement tracks or abundance.")
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress, opts = ctx["cancel"], ctx["progress"], ctx.get("opts")
        limit, split, allow = ctx.get("limit_bytes"), ctx.get("split"), ctx.get("allow_exceed")
        self._taxon_key(cancel)
        bbox = ctx.get("bbox")
        st, js = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, opts, limit=0), cancel=cancel)
        total = js.get("count", 0)
        cap_n = _first_n(opts)
        if total > GBIF_PAGING_CAP and not (cap_n and cap_n <= GBIF_PAGING_CAP):
            raise RecordLimitError(total, GBIF_PAGING_CAP, "the GBIF search API cannot page beyond this many records")
        if cap_n:
            total = min(total, cap_n)
        os.makedirs(ctx["checkpoint_dir"], exist_ok=True)
        page, recs, nbytes = 300, [], 0
        n_pages = (total + page - 1) // page
        for i in range(n_pages):
            if cancel.is_set():
                raise Cancelled()
            cp = os.path.join(ctx["checkpoint_dir"], f"page_{i:06d}.json")
            pg = _cp_load(cp)
            if pg is None:
                st, pg = net.get_json(f"{GBIF}/occurrence/search", self._params(bbox, opts, limit=min(page, total - i * page), offset=i * page), cancel=cancel)
                _cp_save(cp, pg)
            recs.extend(pg.get("results", []))
            nbytes += os.path.getsize(cp)
            progress(records=len(recs), total=total, bytes=nbytes, message=f"page {i + 1}/{n_pages}")
            if limit and not split and not allow and nbytes > limit:
                raise SizeExceeded(nbytes, limit)
            if pg.get("endOfRecords"):
                break
        recs = recs[:total]
        raw = ctx["raw_path"]
        warns = [] if len(recs) == total else [f"Fetched {len(recs)} records but GBIF reported {total}."]
        if cap_n:
            warns.append(f"Kept the first {cap_n:,} records in GBIF's own order (as you chose); not a random sample.")
        q = self._params(bbox, opts)
        meta = {"query": q, "retrieved_at": now_iso(), "count_reported": total}
        if split and limit:
            raw_files = write_parts(recs, raw, limit, lambda ch: {**meta, "results": ch})
            if len(raw_files) > 1:
                warns.append(f"Split into {len(raw_files)} files of at most {limit / 1e6:.0f} MB each (as you chose).")
        else:
            with open(raw, "w", encoding="utf-8") as f:
                json.dump({**meta, "results": recs}, f)
            size = os.path.getsize(raw)
            if limit and not allow and size > limit:
                os.remove(raw)
                raise SizeExceeded(size, limit)
            raw_files = [{"file": os.path.basename(raw), "bytes": size, "sha256": sha256_file(raw)}]
        shutil.rmtree(ctx["checkpoint_dir"], ignore_errors=True)
        return {"raw_files": raw_files, "records": len(recs), "warnings": warns, "source_urls": [net.build_url(f"{GBIF}/occurrence/search", q)],
                "note": "Original GBIF JSON records preserved; GeoJSON working copy derived (subset of Darwin Core fields).",
                "format_requested": "json"}

    def load_fc(self, files, base_dir):
        recs = []
        for rf in files:
            with open(os.path.join(base_dir, rf["file"]), "r", encoding="utf-8") as f:
                recs.extend(json.load(f).get("results", []))
        return gbif_to_fc(recs)


# ----------------------------------------------------------------- Open-Meteo (weather, marine, air quality)
OPENMETEO = {"archive": "https://archive-api.open-meteo.com/v1/archive",
             "marine": "https://marine-api.open-meteo.com/v1/marine",
             "air": "https://air-quality-api.open-meteo.com/v1/air-quality"}
TZ = "Pacific/Auckland"
# Regional centres (name, region, lat, lon). Marine uses a nearby sea point so the model grid cell is ocean.
NZ_CITIES = [
    ("Whangārei", "Northland", -35.73, 174.32, -35.70, 174.55), ("Auckland", "Auckland", -36.85, 174.76, -36.80, 174.95),
    ("Hamilton", "Waikato", -37.79, 175.28, -37.00, 175.60), ("Tauranga", "Bay of Plenty", -37.69, 176.17, -37.55, 176.35),
    ("Gisborne", "Gisborne", -38.66, 178.02, -38.70, 178.20), ("Napier", "Hawke's Bay", -39.49, 176.91, -39.50, 177.05),
    ("New Plymouth", "Taranaki", -39.06, 174.08, -39.00, 173.95), ("Palmerston North", "Manawatū-Whanganui", -40.36, 175.61, -40.40, 175.20),
    ("Wellington", "Wellington", -41.29, 174.78, -41.40, 174.85), ("Richmond", "Tasman", -41.34, 173.18, -41.15, 173.05),
    ("Nelson", "Nelson", -41.27, 173.28, -41.20, 173.40), ("Blenheim", "Marlborough", -41.51, 173.96, -41.35, 174.10),
    ("Greymouth", "West Coast", -42.45, 171.21, -42.45, 171.05), ("Christchurch", "Canterbury", -43.53, 172.64, -43.55, 172.85),
    ("Dunedin", "Otago", -45.87, 170.50, -45.95, 170.75), ("Invercargill", "Southland", -46.41, 168.35, -46.55, 168.40),
]


def _norm(s):
    from . import quality
    return quality.norm_name(s)


class OpenMeteo:
    """Daily weather / marine / air-quality time series for 16 NZ regional centres (https://open-meteo.com, free for
    non-commercial use, CC BY 4.0). Each output record = one location on one day, as a Point feature."""
    kind = "openmeteo"

    def __init__(self, spec):
        self.spec = spec

    def _locations(self, opts, region=None):
        region = region or (opts or {}).get("region")
        locs = NZ_CITIES
        if region:
            r = _norm(region)
            locs = [c for c in NZ_CITIES if _norm(c[1]) in (r, r.replace("region", ""))] or []
        return locs

    def _vars(self, opts):
        chosen = _flt(opts).get("variables")
        allv = self.spec["variables"]
        return [v for v in allv if (not chosen or v in chosen)] or allv

    def _chunks(self, period):
        """Hourly air-quality requests are split by year; daily ones are a single request."""
        s, e = period["start"], period["end"]
        if self.spec["api"] != "air":
            return [(s, e)]
        out, y = [], int(s[:4])
        while y <= int(e[:4]):
            a = max(s, f"{y}-01-01")
            b = min(e, f"{y}-12-31")
            out.append((a, b))
            y += 1
        return out

    def _req(self, loc, start, end, variables, cancel, on_bytes=None, max_bytes=None):
        api = self.spec["api"]
        lat, lon = (loc[4], loc[5]) if api == "marine" else (loc[2], loc[3])
        p = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "timezone": TZ,
             ("hourly" if api == "air" else "daily"): ",".join(variables)}
        return net.get_json(OPENMETEO[api], p, cancel=cancel, timeout=90, retries=2)

    def verify(self, bbox=None, cancel=None, opts=None):
        res = new_result(self.spec)
        res["access_url"] = OPENMETEO[self.spec["api"]]
        try:
            per = (opts or {}).get("period") or timeperiod.resolve("year")
            locs = self._locations(opts)
            variables = self._vars(opts)
            if not locs:
                check(res, "Locations in the study area", False, f"No weather location is inside {(opts or {}).get('region')} — Record count 0")
                res["count"] = 0
                return finish(res)
            check(res, "Locations in the study area", True, f"{len(locs)} location(s): {', '.join(c[0] for c in locs[:6])}{'…' if len(locs) > 6 else ''}")
            # Probe the first and last 30 days of the chosen period at one location: this shows real availability.
            s, e = per["start"], per["end"]
            from datetime import date, timedelta as td
            sd, ed = date.fromisoformat(s), date.fromisoformat(e)
            first_end = min(ed, sd + td(days=29))
            last_start = max(sd, ed - td(days=29))
            avail = {}
            for tag, (a, b) in {"start": (s, first_end.isoformat()), "end": (last_start.isoformat(), e)}.items():
                try:
                    st, js = self._req(locs[0], a, b, variables[:1], cancel)
                    block = (js.get("daily") or js.get("hourly") or {})
                    vals = block.get(variables[0], [])
                    avail[tag] = {"window": f"{a} → {b}", "values": len(vals), "non_null": sum(1 for v in vals if v is not None)}
                except NetError as ex:
                    avail[tag] = {"window": f"{a} → {b}", "error": str(ex)[:160]}
            ok_any = any(v.get("non_null", 0) > 0 for v in avail.values())
            check(res, "Weather service reachable", all("error" not in v for v in avail.values()) or ok_any,
                  "; ".join(f"{k} {v['window']}: " + (v.get("error") or f"{v['non_null']}/{v['values']} values") for k, v in avail.items()))
            check(res, "Data exists in your time period", ok_any, "no values returned for the start or end of your period" if not ok_any else "values present")
            days = per["days"]
            rows = len(locs) * days
            res["count"] = rows
            res["est_bytes"] = rows * 230
            res["est_note"] = "Estimate: ~230 bytes per location-day record (not measured)."
            res["geometry_type"] = "esriGeometryPoint"
            res["crs"] = "EPSG:4326 (location points)"
            res["fields"] = [{"name": v, "type": "", "alias": ""} for v in ["location", "region", "date"] + variables]
            res["licence"] = "Open-Meteo: CC BY 4.0 data, free for non-commercial use (attribute Open-Meteo.com; ERA5 / CAMS source data)"
            res["licence_verified"] = False
            res["time_info"] = {"availability": avail, "period": per["text"]}
            res["notes"].append("Values are model/reanalysis output for the nearest grid cell, not a weather-station reading.")
            return finish(res)
        except (Cancelled, SizeExceeded):
            raise
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:300]
            check(res, "Verification completed without error", False, e)
            return finish(res)

    def download(self, ctx):
        cancel, progress, opts = ctx["cancel"], ctx["progress"], ctx.get("opts") or {}
        per = opts.get("period") or timeperiod.resolve("year")
        locs = self._locations(opts, ctx.get("region"))
        variables = self._vars(opts)
        total = len(locs) * per["days"]
        os.makedirs(ctx["checkpoint_dir"], exist_ok=True)
        results, nbytes, rows = [], 0, 0
        limit, allow = ctx.get("limit_bytes"), ctx.get("allow_exceed")
        for i, loc in enumerate(locs):
            if cancel.is_set():
                raise Cancelled()
            cp = os.path.join(ctx["checkpoint_dir"], f"loc_{i:03d}.json")
            item = _cp_load(cp)
            if item is None:
                parts = []
                for (a, b) in self._chunks(per):
                    st, js = self._req(loc, a, b, variables, cancel)
                    parts.append(js)
                    progress(message=f"{loc[0]}: {a} → {b}")
                item = {"location": loc[0], "region": loc[1], "lat": loc[2], "lon": loc[3], "responses": parts}
                _cp_save(cp, item)
            results.append(item)
            nbytes += os.path.getsize(cp)
            rows += per["days"]
            progress(records=rows, total=total, bytes=nbytes, message=f"{i + 1}/{len(locs)} locations")
            if limit and not allow and nbytes > limit:
                raise SizeExceeded(nbytes, limit)
        raw = ctx["raw_path"]
        with open(raw, "w", encoding="utf-8") as f:
            json.dump({"source": OPENMETEO[self.spec["api"]], "retrieved_at": now_iso(), "period": per, "variables": variables, "locations": results}, f)
        size = os.path.getsize(raw)
        if limit and not allow and size > limit:
            os.remove(raw)
            raise SizeExceeded(size, limit)
        shutil.rmtree(ctx["checkpoint_dir"], ignore_errors=True)
        n = sum(len(f["properties"]) > 0 for f in self.load_fc([{"file": os.path.basename(raw)}], os.path.dirname(raw))["features"])
        return {"raw_files": [{"file": os.path.basename(raw), "bytes": size, "sha256": sha256_file(raw)}], "records": n,
                "warnings": ["Model/reanalysis values for the nearest grid cell — not station observations."],
                "source_urls": [OPENMETEO[self.spec["api"]]], "note": "Original Open-Meteo responses preserved; one point record per location per day derived.",
                "format_requested": "json"}

    def load_fc(self, files, base_dir):
        with open(os.path.join(base_dir, files[0]["file"]), "r", encoding="utf-8") as f:
            raw = json.load(f)
        api, feats = self.spec["api"], []
        for loc in raw["locations"]:
            by_day = {}
            for js in loc["responses"]:
                block = js.get("daily") or js.get("hourly") or {}
                times = block.get("time", [])
                for var in raw["variables"]:
                    vals = block.get(var, [])
                    for t, v in zip(times, vals):
                        day = t[:10]
                        if api == "air":
                            by_day.setdefault(day, {}).setdefault(var, []).append(v)
                        else:
                            by_day.setdefault(day, {})[var] = v
            for day in sorted(by_day):
                props = {"location": loc["location"], "region": loc["region"], "date": day}
                for var, v in by_day[day].items():
                    if api == "air":
                        nn = [x for x in v if x is not None]
                        props[var + "_daily_mean"] = round(sum(nn) / len(nn), 2) if nn else None
                        props[var + "_daily_max"] = max(nn) if nn else None
                    else:
                        props[var] = v
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [loc["lon"], loc["lat"]]}, "properties": props})
        return {"type": "FeatureCollection", "features": feats}


SOURCES = {"arcgis": ArcGISSource, "fdsn": GeoNetFDSN, "geonet_quake": GeoNetQuakeAPI, "gbif": GBIFSource,
           "geojson_url": GeoJSONURL, "openmeteo": OpenMeteo, "file_url": FileURL}


def make_source(spec):
    return SOURCES[spec["connector"]](spec)


# ----------------------------------------------------------------- what the user may filter, per source
def filter_schema(spec, verification=None):
    """Controls the plan page can offer for this dataset. Only filters the source genuinely supports are listed."""
    c = spec["connector"]
    out = []
    if c == "fdsn":
        out += [{"key": "minmag", "label": "Minimum magnitude", "type": "number", "default": spec.get("minmag", 5), "step": 0.1},
                {"key": "maxdepth", "label": "Maximum depth (km)", "type": "number", "default": None, "step": 1}]
    elif c == "gbif":
        out += [{"key": "basis", "label": "Record type", "type": "select", "options": [""] + GBIF_BASIS, "default": ""},
                {"key": "max_uncertainty", "label": "Max coordinate uncertainty (m)", "type": "number", "default": None, "step": 100}]
    elif c == "arcgis":
        fields = [f for f in (verification or {}).get("fields", []) if f["type"] in ("esriFieldTypeString", "esriFieldTypeInteger", "esriFieldTypeSmallInteger")]
        out += [{"key": "attr", "label": "Only records where an attribute is…", "type": "attr", "fields": [f["name"] for f in fields]}]
    elif c == "openmeteo":
        out += [{"key": "variables", "label": "Variables to include", "type": "multi", "options": spec["variables"], "default": spec["variables"]}]
    return out


def default_formats(spec):
    """Export formats offered: spatial data -> GeoJSON (+ CSV table); tabular -> CSV + XLSX."""
    c = spec["connector"]
    tabular = c in ("openmeteo",) or (c == "file_url" and spec.get("tabular"))
    return ["csv", "xlsx"] if tabular else ["geojson", "csv"]
