"""Browser-friendly previews of downloaded layers for the map viewer and table viewer.

Previews are thinned (every Nth feature / vertex) so even big layers stay fast in the browser. They are for LOOKING at
only: the full-resolution files are never touched, and the response says exactly how much was thinned."""
import json
import math

MAX_VERTICES = 60000


def _iter_lines(geom):
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "LineString":
        yield c
    elif t in ("MultiLineString", "Polygon"):
        yield from c
    elif t == "MultiPolygon":
        for poly in c:
            yield from poly


def _vertex_count(geom):
    t = geom.get("type")
    if t == "Point":
        return 1
    if t == "MultiPoint":
        return len(geom["coordinates"])
    return sum(len(l) for l in _iter_lines(geom))


def _thin(line, step, closed):
    if step <= 1 or len(line) <= 4:
        return [[round(p[0], 4), round(p[1], 4)] for p in line]
    out = line[::step]
    if out[-1] != line[-1]:
        out.append(line[-1])
    if closed and out[0] != out[-1]:
        out.append(out[0])
    return [[round(p[0], 4), round(p[1], 4)] for p in out]


def _thin_geom(g, step):
    t, c = g.get("type"), g.get("coordinates")
    if t == "Point":
        return {"type": t, "coordinates": [round(c[0], 5), round(c[1], 5)]}
    if t == "MultiPoint":
        return {"type": t, "coordinates": [[round(p[0], 5), round(p[1], 5)] for p in c]}
    if t == "LineString":
        return {"type": t, "coordinates": _thin(c, step, False)}
    if t == "MultiLineString":
        return {"type": t, "coordinates": [_thin(l, step, False) for l in c]}
    if t == "Polygon":
        return {"type": t, "coordinates": [_thin(r, step, True) for r in c]}
    if t == "MultiPolygon":
        return {"type": t, "coordinates": [[_thin(r, step, True) for r in poly] for poly in c]}
    return None


def _small_props(p, n=12):
    out = {}
    for k, v in (p or {}).items():
        if len(out) >= n:
            break
        if isinstance(v, (int, float)) or v is None or (isinstance(v, str) and len(v) <= 120):
            out[k] = v
    return out


def make_preview(path, max_features=5000):
    with open(path, "r", encoding="utf-8") as f:
        fc = json.load(f)
    allf = fc.get("features", [])
    feats = [x for x in allf if x.get("geometry")]
    total = len(feats)
    stride = max(1, math.ceil(total / max_features))
    shown = feats[::stride]
    step = max(1, math.ceil(sum(_vertex_count(x["geometry"]) for x in shown) / MAX_VERTICES))
    out = []
    for x in shown:
        g = _thin_geom(x["geometry"], step)
        if g:
            out.append({"type": "Feature", "geometry": g, "properties": _small_props(x.get("properties"))})
    return {"type": "FeatureCollection", "features": out,
            "meta": {"records": len(allf), "with_geometry": total, "shown": len(out), "sampled": stride > 1, "simplified": step > 1,
                     "geometry_types": sorted({x["geometry"]["type"] for x in out}),
                     "note": "Preview only: thinned so the browser stays fast. The files you download are complete and unchanged."}}


def table_preview(path, n=100):
    with open(path, "r", encoding="utf-8") as f:
        fc = json.load(f)
    feats = fc.get("features", [])[:n]
    cols = []
    for x in feats:
        for k in (x.get("properties") or {}):
            if k not in cols:
                cols.append(k)
    return {"columns": cols[:30], "rows": [[_small_props({c: (x.get("properties") or {}).get(c) for c in cols[:30]}, 30).get(c) for c in cols[:30]] for x in feats],
            "total": len(fc.get("features", []))}
