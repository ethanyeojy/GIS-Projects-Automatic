"""Basic quality checks, region tagging and compatibility matrix. Pure Python;
uses shapely automatically if installed for faster point-in-polygon."""
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

try:  # optional accelerator
    from shapely.geometry import shape, Point  # type: ignore
    from shapely.prepared import prep  # type: ignore
    from shapely.strtree import STRtree  # type: ignore
    HAVE_SHAPELY = True
except Exception:  # noqa: BLE001
    HAVE_SHAPELY = False

ID_FIELDS = ["gbifID", "eventid", "publicID", "OBJECTID", "FID", "ObjectId", "objectid"]


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def in_nz_envelope(lon, lat):
    return -56 <= lat <= -26 and (lon >= 160 or lon <= -170)


def iter_coords(g):
    if not g:
        return
    t, c = g.get("type"), g.get("coordinates")
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        yield from c
    elif t in ("MultiLineString", "Polygon"):
        for part in c:
            yield from part
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


def geom_problems(g):
    if not g:
        return ["null geometry"]
    t, c = g.get("type"), g.get("coordinates")
    probs = []
    try:
        for xy in iter_coords(g):
            x, y = xy[0], xy[1]
            if not (isinstance(x, (int, float)) and isinstance(y, (int, float))) or math.isnan(x) or math.isnan(y):
                probs.append("non-numeric coordinate")
                break
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                probs.append("coordinate outside lon/lat range")
                break
        polys =[c] if t == "Polygon" else (c if t == "MultiPolygon" else [])
        for poly in polys:
            for ring in poly:
                if len(ring) < 4:
                    probs.append("polygon ring has < 4 points")
                    break
                if ring[0] != ring[-1]:
                    probs.append("polygon ring not closed")
                    break
        if t == "LineString" and len(c) < 2:
            probs.append("line has < 2 points")
    except Exception as e:  # noqa: BLE001
        probs.append(f"malformed geometry: {e}")
    return probs


def parse_date(v, ms_epoch=False):
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            if ms_epoch or v > 1e11:
                return datetime.fromtimestamp(v / 1000, tz=timezone.utc).replace(tzinfo=None)
            return None
        s = str(v).strip().split("/")[0]
        s = s.replace("Z", "")
        if re.fullmatch(r"\d{4}", s):
            return datetime(int(s), 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", s):
            return datetime(int(s[:4]), int(s[5:7]), 1)
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def infer_type(vals):
    c = Counter(type(v).__name__ for v in vals if v is not None)
    return c.most_common(1)[0][0] if c else "null"


def inspect_fc(fc, date_field_hints=()):
    feats = fc.get("features", [])
    n = len(feats)
    out = {"records": n, "warnings": [], "blocking": [], "checks": []}
    gt = Counter((f.get("geometry") or {}).get("type") or "null" for f in feats)
    out["geometry_types"] = dict(gt)
    out["with_geometry"] = n - gt.get("null", 0)
    if n == 0:
        out["blocking"].append("Dataset contains zero features after download.")
        out["fields"] = []
        return out
    if gt.get("null"):
        out["warnings"].append(f"{gt['null']} features have no geometry (kept in raw; excluded from mapping).")
    invalid, ex = 0, []
    outside, zero = 0, 0
    minx = miny = 1e9
    maxx = maxy = -1e9
    for i, f in enumerate(feats):
        g = f.get("geometry")
        if not g:
            continue
        pr = [p for p in geom_problems(g) if p != "null geometry"]
        if pr:
            invalid += 1
            if len(ex) < 5:
                ex.append({"index": i, "problem": pr[0]})
            continue
        if g["type"] == "Point":
            x, y = g["coordinates"][:2]
            if x == 0 and y == 0:
                zero += 1
            if not in_nz_envelope(x, y):
                outside += 1
        for xy in iter_coords(g):
            minx, maxx = min(minx, xy[0]), max(maxx, xy[0])
            miny, maxy = min(miny, xy[1]), max(maxy, xy[1])
    out["invalid_geometry"], out["invalid_examples"] = invalid, ex
    if invalid:
        out["warnings"].append(f"{invalid} features have invalid geometry (e.g. {ex[0]['problem']}); flagged, not removed.")
    if zero:
        out["warnings"].append(f"{zero} point records sit at (0,0) — suspicious placeholder coordinates; flagged, not removed.")
    if outside:
        out["warnings"].append(f"{outside} point records fall outside a generous NZ-region envelope (lat -56..-26, lon 160..-170); flagged, not removed.")
    out["outside_nz_envelope"] = outside
    out["bbox"] = [minx, miny, maxx, maxy] if minx < 1e9 else None
    # fields
    names = []
    for f in feats[:2000]:
        for k in (f.get("properties") or {}):
            if k not in names:
                names.append(k)
    fields, date_info = {}, {}
    for k in names:
        vals = [(f.get("properties") or {}).get(k) for f in feats]
        nulls = sum(1 for v in vals if v is None or v == "")
        ex_v = next((v for v in vals if v not in (None, "")), None)
        fields[k] = {"type": infer_type(vals), "nulls": nulls, "example": str(ex_v)[:60] if ex_v is not None else ""}
        if re.search(r"(time|date)", k, re.I) or k in date_field_hints:
            ok = [parse_date(v, ms_epoch=k in date_field_hints) for v in vals if v not in (None, "")]
            parsed = [d for d in ok if d]
            if parsed or ok:
                date_info[k] = {"parsed": len(parsed), "unparsed": len(ok) - len(parsed),
                                "min": min(parsed).isoformat() if parsed else None, "max": max(parsed).isoformat() if parsed else None}
                if len(ok) - len(parsed):
                    out["warnings"].append(f"Field '{k}': {len(ok) - len(parsed)} values could not be parsed as dates.")
        if nulls == n:
            out["warnings"].append(f"Field '{k}' is empty for all records.")
    out["fields"] = names
    out["field_stats"] = fields
    out["date_fields"] = date_info
    # duplicates
    idf = next((k for k in ID_FIELDS if k in fields), None)
    out["id_field"] = idf
    if idf:
        c = Counter((f.get("properties") or {}).get(idf) for f in feats)
        dups = sum(v - 1 for v in c.values() if v > 1 and True)
        out["duplicate_ids"] = dups
        if dups:
            out["warnings"].append(f"{dups} duplicate values in id field '{idf}' (kept; investigate).")
    pts = Counter()
    for f in feats:
        g = f.get("geometry")
        if g and g.get("type") == "Point":
            p = f.get("properties") or {}
            pts[(round(g["coordinates"][0], 6), round(g["coordinates"][1], 6), str(p.get("time") or p.get("eventDate") or ""), str(p.get("magnitude") or p.get("scientificName") or ""))] += 1
    d = sum(v - 1 for v in pts.values() if v > 1)
    out["duplicate_point_records"] = d
    if d:
        out["warnings"].append(f"{d} records share identical location + time + magnitude/species with another record (possible duplicates; kept).")

    def col(k):
        return [(f.get("properties") or {}).get(k) for f in feats]

    def num(k):
        return [v for v in col(k) if isinstance(v, (int, float))]
    special = {}
    for k in ("magnitude", "depth_km", "depth", "mmi"):
        if k in fields:
            v = num(k)
            if v:
                special[k] = {"min": min(v), "max": max(v), "n": len(v)}
    if "mmi" in special and any(v < 0 for v in num("mmi")):
        out["warnings"].append(f"mmi has {sum(1 for v in num('mmi') if v < 0)} negative values (treat as 'no intensity' only after checking GeoNet documentation).")
    if "magtype" in fields:
        special["magtype_counts"] = dict(Counter(col("magtype")).most_common(8))
        if len([k for k in special["magtype_counts"] if k]) > 1:
            out["warnings"].append("Mixed magnitude types present — do not compare magnitudes across types without care.")
    if "coordinateUncertaintyInMeters" in fields:
        miss = sum(1 for v in col("coordinateUncertaintyInMeters") if v in (None, ""))
        v = num("coordinateUncertaintyInMeters")
        special["coordinate_uncertainty"] = {"missing": miss, "gt_1km": sum(1 for x in v if x > 1000), "gt_10km": sum(1 for x in v if x > 10000)}
        if miss > 0.3 * n:
            out["warnings"].append(f"{miss} of {n} records have no coordinate uncertainty.")
        if special["coordinate_uncertainty"]["gt_10km"]:
            out["warnings"].append(f"{special['coordinate_uncertainty']['gt_10km']} records have coordinate uncertainty > 10 km.")
    if "issues" in fields:
        iss = Counter()
        for v in col("issues"):
            for t in str(v or "").split(";"):
                if t:
                    iss[t] += 1
        special["gbif_issue_flags"] = dict(iss.most_common(10))
        if iss:
            out["warnings"].append("GBIF issue flags present (top: " + ", ".join(f"{k}×{v}" for k, v in iss.most_common(3)) + ").")
    for k, label in (("license", "licence_counts"), ("basisOfRecord", "basis_counts"), ("datasetKey", "dataset_keys")):
        if k in fields:
            c = Counter(col(k))
            special[label] = dict(c.most_common(8)) if k != "datasetKey" else {"distinct": len(c)}
    if "year" in fields:
        ys = [v for v in num("year") if 1500 < v < 2200]
        if ys:
            special["year_range"] = [min(ys), max(ys)]
    out["special"] = special
    out["checks"] = [{"name": "geometry validity", "ok": invalid == 0}, {"name": "coordinates plausible for NZ", "ok": outside == 0 and zero == 0},
                     {"name": "no duplicate ids", "ok": not out.get("duplicate_ids")}]
    return out


# ------------------------------------------------------------------ regions
def _ring_inside(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _thin_ring(ring, max_vertices=2500):
    """Keep at most ~max_vertices points of a ring (used only for the slow pure-Python point test)."""
    if len(ring) <= max_vertices:
        return ring
    step = -(-len(ring) // max_vertices)
    out = ring[::step]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def prep_regions(regc_fc, name_field):
    regions = []
    for f in regc_fc.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        name = (f.get("properties") or {}).get(name_field)
        polys = [g["coordinates"]] if g["type"] == "Polygon" else (g["coordinates"] if g["type"] == "MultiPolygon" else [])
        parts = []
        for poly in polys:
            xs = [p[0] for p in poly[0]]
            ys = [p[1] for p in poly[0]]
            if not HAVE_SHAPELY:
                # Pure-Python point-in-polygon is slow on full-resolution coastlines (hundreds of thousands of vertices per region), so use
                # simplified rings for tagging. Accuracy is roughly a kilometre or two right at the coast; shapely (optional) is exact.
                poly = [_thin_ring(ring) for ring in poly]
            parts.append((min(xs), min(ys), max(xs), max(ys), poly))
        if parts:
            r = {"name": name, "parts": parts, "feature": f}
            if HAVE_SHAPELY:
                try:
                    r["prep"] = prep(shape(g))
                except Exception:  # noqa: BLE001
                    pass
            regions.append(r)
    return regions


def find_region(x, y, regions):
    for r in regions:
        if "prep" in r:
            if r["prep"].contains(Point(x, y)):
                return r["name"]
            continue
        for x0, y0, x1, y1, poly in r["parts"]:
            if x0 <= x <= x1 and y0 <= y <= y1 and _ring_inside(x, y, poly[0]) and not any(_ring_inside(x, y, h) for h in poly[1:]):
                return r["name"]
    return None


def tag_points(feats, regions, progress=None):
    """Returns list of region names (or None) for each feature; None for non-point/null."""
    out = []
    last = None
    for i, f in enumerate(feats):
        g = f.get("geometry")
        if not g or g.get("type") != "Point":
            out.append(None)
            continue
        x, y = g["coordinates"][:2]
        name = None
        if last is not None:
            name = find_region(x, y, [last])
        if name is None:
            name = find_region(x, y, regions)
        if name is not None:
            last = next((r for r in regions if r["name"] == name), None)
        out.append(name)
        if progress and i % 500 == 0:
            progress(i, len(feats))
    if progress:
        progress(len(feats), len(feats))
    return out


def bbox_of_feature(feat):
    xs, ys = [], []
    for xy in iter_coords(feat.get("geometry")):
        xs.append(xy[0])
        ys.append(xy[1])
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def bbox_overlap(a, b):
    return bool(a and b and a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3])


# ------------------------------------------------------------------ compatibility
OPTIONAL_NEEDS = {"Region land area (for percentages)"}


def compat_matrix(project, inspections, verification, study_bbox):
    rows = []
    for need, reqs in project["needs"]:
        status, detail = "ok", []
        for ds, rx in reqs:
            ins = inspections.get(ds)
            if not ins:
                status = "blocking"
                detail.append(f"{ds}: not inspected")
                continue
            if rx == "geometry":
                ok = ins.get("with_geometry", 0) > 0
                detail.append(f"{ds}: {ins.get('with_geometry', 0)} features with geometry")
            elif rx == "crs":
                crs = (verification.get(ds) or {}).get("crs")
                ok = bool(crs)
                detail.append(f"{ds}: native CRS {crs or 'unknown'}")
            else:
                m = [f for f in ins.get("fields", []) if re.search(rx, f, re.I)]
                ok = bool(m)
                detail.append(f"{ds}: " + (", ".join(m[:4]) if m else f"no field matching /{rx}/"))
            if not ok:
                status = "warning" if need in OPTIONAL_NEEDS else "blocking"
        rows.append({"need": need, "datasets": sorted({d for d, _ in reqs}), "status": status, "detail": "; ".join(detail)})
    extra = []
    for ds, ins in inspections.items():
        if ds == "regc" or not study_bbox:
            continue
        if ins.get("bbox") and not bbox_overlap(ins["bbox"], study_bbox):
            extra.append({"need": f"Spatial overlap: {ds} vs study area", "datasets": [ds, "regc"], "status": "blocking",
                          "detail": f"bbox {ins['bbox']} does not intersect study area bbox {study_bbox}"})
        else:
            extra.append({"need": f"Spatial overlap: {ds} vs study area", "datasets": [ds, "regc"], "status": "ok",
                          "detail": "bounding boxes intersect (bbox test only; polygon overlap tested in region tagging)" if ins.get("bbox") else "no bbox (no geometry)"})
    rows.extend(extra)
    return rows


def temporal_summary(inspections):
    out = {}
    for ds, ins in inspections.items():
        df = ins.get("date_fields") or {}
        for k, v in df.items():
            if v.get("min"):
                out[f"{ds}.{k}"] = [v["min"], v["max"]]
    return out
