"""Final map in ArcGIS Online — works with ANY login (school / Google / Microsoft), because the app never signs in for you.

1. Live layers: every dataset that comes from a public ArcGIS service is added to Map Viewer straight from its service URL
   (Esri's documented `urls=` + `extent=` URL parameters). Those layers keep the publisher's own symbols, so they have a
   proper legend. You sign in yourself, then press Save.
2. Upload layers: everything else (GBIF, GeoNet, weather tables, files) is written as ArcGIS-Online-ready GeoJSON:
   one geometry type per file (ArcGIS Online rejects mixed files), no empty geometries, coordinates rounded to ~1 m so the
   files are small, and a suggested field to style by — an uploaded file gets ONE plain symbol (a legend with no
   categories) until you style it by a field, which is the usual "layers have no legend" problem.
Docs: https://doc.arcgis.com/en/arcgis-online/reference/use-url-parameters.htm"""
import json
import os
import re
import urllib.parse

from . import catalog

MAPVIEWER = "https://www.arcgis.com/apps/mapviewer/index.html"
ADD_FILE_LIMIT = 10_000_000  # Map Viewer "Add layer from file" limit (~10 MB); Content > New item takes bigger files
GEOM_ORDER = {"Polygon": 0, "MultiPolygon": 0, "LineString": 1, "MultiLineString": 1, "Point": 2, "MultiPoint": 2}
FAMILY = {"Polygon": "polygons", "MultiPolygon": "polygons", "LineString": "lines", "MultiLineString": "lines",
          "Point": "points", "MultiPoint": "points"}
SKIP_FIELDS = re.compile(r"^(objectid|fid|oid|id|globalid|shape_?\w*|st_\w+|\w*longitude\w*|\w*latitude\w*|lon|lat|x|y|gbifid|key|calc_region|\w*_fid|\w*fid|\w*_id|id_\w*|\w*code|"
                         r"coordinate\w*|\w*precision\w*|\w*uncertainty\w*|elevation\w*|depth(accuracy)?|day|month|taxonkey|\w*key|records|\w*_days)$", re.I)
CAT_HINT = re.compile(r"(basisofrecord|type|class|species|scientific|category|status|kind|group|family|genus|zone|level)", re.I)
NUM_HINT = re.compile(r"(magnitude|mag|depth|count|value|height|level|area|length|rain|temp|wave|pm|speed|pop|percent|change|year|sunshine|snow|wind|precip)", re.I)


def _round(c, nd=5):
    if isinstance(c, (int, float)):
        return round(c, nd)
    return [_round(x, nd) for x in c]


NUM_PREFER = re.compile(r"_(mean)$", re.I)


def style_hint(feats):
    """-> {field, how, values?} : the field that gives the clearest legend, chosen from the data itself."""
    if not feats:
        return None
    if len(feats) <= 5:  # only a few points (e.g. 1-2 weather points in a region): a legend can't show much — label them
        nums = [k for k, v in (feats[0].get("properties") or {}).items() if isinstance(v, (int, float)) and not SKIP_FIELDS.match(k)]
        best = next((k for k in nums if NUM_PREFER.search(k) and NUM_HINT.search(k)), next((k for k in nums if NUM_HINT.search(k)), nums[0] if nums else None))
        if best:
            return {"field": best, "how": "keep one symbol and turn on Labels (only a few points, so the values read better as labels)"}
    sample = feats[:5000]
    keys = []
    for f in sample[:200]:
        for k in (f.get("properties") or {}):
            if k not in keys and not SKIP_FIELDS.match(k):
                keys.append(k)
    best_cat, best_num = None, None
    for k in keys:
        vals = [(f.get("properties") or {}).get(k) for f in sample]
        vals = [v for v in vals if v not in (None, "")]
        if len(vals) < max(1, len(sample) // 3):
            continue
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            if len(set(vals)) > 5:
                score = 3 if NUM_PREFER.search(k) and NUM_HINT.search(k) else 2 if NUM_HINT.search(k) or NUM_PREFER.search(k) else 1
                if not best_num or score > best_num[0]:
                    best_num = (score, k)
            continue
        distinct = {str(v) for v in vals}
        if 2 <= len(distinct) <= 12:
            score = 2 if CAT_HINT.search(k) else 1
            if not best_cat or score > best_cat[0] or (score == best_cat[0] and len(distinct) < best_cat[2]):
                best_cat = (score, k, len(distinct), sorted(distinct)[:12])
    if best_num and best_num[0] >= 3:
        return {"field": best_num[1], "how": "Counts and Amounts (color) — or (size) for points"}
    if best_cat and (best_cat[0] >= 2 or not best_num):
        return {"field": best_cat[1], "how": "Types (unique symbols)", "values": best_cat[3]}
    if best_num:
        return {"field": best_num[1], "how": "Counts and Amounts (color) — or (size) for points"}
    if best_cat:
        return {"field": best_cat[1], "how": "Types (unique symbols)", "values": best_cat[3]}
    return None


def summarise_series(feats):
    """Time series at a few fixed places (e.g. 16 weather points x 3,650 days) -> ONE feature per place with the
    average and maximum of each number, the record count and the date range. Small file, and a real graduated legend."""
    by = {}
    for f in feats:
        g = f["geometry"]
        if g.get("type") != "Point":
            return None
        by.setdefault(tuple(round(c, 4) for c in g["coordinates"][:2]), []).append(f.get("properties") or {})
    if not by or len(by) > 500 or len(feats) < 3 * len(by):
        return None  # not a repeated-location time series
    out = []
    for (x, y), rows in by.items():
        props = {"records": len(rows)}
        for k in rows[0]:
            vals = [r.get(k) for r in rows]
            nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums and not SKIP_FIELDS.match(k):
                props[f"{k}_mean"] = round(sum(nums) / len(nums), 3)
                props[f"{k}_max"] = round(max(nums), 3)
                if len(nums) < len(rows):
                    props[f"{k}_days"] = len(nums)  # days that actually have a value
            elif not nums:
                txt = sorted({str(v) for v in vals if v not in (None, "")})
                if len(txt) == 1:
                    props[k] = txt[0]
                elif txt and re.search(r"(date|time|day)", k, re.I):
                    props[f"{k}_first"], props[f"{k}_last"] = txt[0], txt[-1]
        out.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [x, y]}})
    return out


def _live_url(ds, ver):
    """The exact public layer URL (…/FeatureServer/<n>) the app verified, or None if the source is not an ArcGIS service."""
    spec = catalog.DATASETS.get(ds) or {}
    if spec.get("connector") != "arcgis":
        return None
    u = (ver or {}).get("access_url") or spec.get("service_url") or ""
    return u if re.search(r"/(FeatureServer|MapServer)(/\d+)?/?$", u) else None


def _geom_family(ver, insp):
    g = str((ver or {}).get("geometry_type") or "")
    if "Polygon" in g:
        return 0
    if "Polyline" in g or "Line" in g:
        return 1
    if "Point" in g:
        return 2
    types = (insp or {}).get("geometry_types") or {}
    return min((GEOM_ORDER.get(t, 2) for t in types), default=2)


def mapviewer_link(urls, bbox=None, title=None):
    q = {"urls": ",".join(urls)}
    if bbox:
        q["extent"] = ",".join(str(round(v, 4)) for v in bbox)
    if title:
        q["title"] = title
    return MAPVIEWER + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote, safe="")


def build(job):
    """Write maps/arcgis_online/* for a finished job and return the summary (also saved as agol.json)."""
    p, d = job.project, job.data
    out_dir = job.path("maps", "arcgis_online")
    os.makedirs(out_dir, exist_ok=True)
    live, uploads, notes = [], [], []
    for ds in p["datasets"]:
        t = job.datasets.get(ds) or {}
        if t.get("state") != "completed":
            continue
        spec = catalog.DATASETS[ds]
        ver = d["verification"].get(ds) or {}
        insp = d["inspections"].get(ds) or {}
        url = _live_url(ds, ver)
        name = "Study-area boundaries" if ds == "regc" else spec["name"]
        working = d["working"].get(ds)
        fc = None
        if working and working.endswith((".geojson", ".json")):
            try:
                with open(job.path("data", "processed", working), "r", encoding="utf-8") as f:
                    fc = json.load(f)
            except (OSError, ValueError):
                fc = None
        feats = [f for f in (fc or {}).get("features", []) if f.get("geometry") and f["geometry"].get("coordinates") not in (None, [])]
        hint = style_hint(feats)
        if url:
            live.append({"dataset": ds, "name": name, "url": url, "order": _geom_family(ver, insp), "publisher": spec["publisher"],
                         "note": "Publisher's own symbols and legend. Shows ALL of New Zealand — the map opens zoomed to your study area."
                                 if job.region and ds != "regc" else "Publisher's own symbols and legend.",
                         "style": hint})
        if not feats:
            if not url:
                notes.append(f"{name}: no map geometry (a table) — add it as a chart in your StoryMap, or join it to a layer in ArcGIS Pro.")
            continue
        if url and not job.region:
            continue  # nationwide: the live layer IS the data, so a copy would only duplicate it
        series = None if url else summarise_series(feats)
        if series:
            fname = f"{ds}_summary.geojson"
            path = os.path.join(out_dir, fname)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"type": "FeatureCollection", "features": series}, fh, separators=(",", ":"), ensure_ascii=False)
            uploads.append({"dataset": ds, "name": name + " — summary per place", "file": f"maps/arcgis_online/{fname}", "bytes": os.path.getsize(path),
                            "features": len(series), "geometry": "points", "order": 2, "how_to_add": "Map Viewer > Add > Add layer from file",
                            "recommended": True, "style": style_hint(series),
                            "why": f"{len(feats):,} daily rows at {len(series)} places, summarised to one point per place (average and maximum) so the map has a clear legend. "
                                   "Use the full table for charts in your StoryMap."})
            continue
        # upload-ready GeoJSON: one geometry family per file
        groups = {}
        for f in feats:
            fam = FAMILY.get(f["geometry"].get("type"))
            if fam:
                groups.setdefault(fam, []).append({"type": "Feature", "properties": f.get("properties") or {},
                                                   "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}})
        for fam, gfeats in groups.items():
            fname = f"{ds}.geojson" if len(groups) == 1 else f"{ds}_{fam}.geojson"
            path = os.path.join(out_dir, fname)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"type": "FeatureCollection", "features": gfeats}, fh, separators=(",", ":"), ensure_ascii=False)
            size = os.path.getsize(path)
            uploads.append({"dataset": ds, "name": name + ("" if len(groups) == 1 else f" ({fam})"), "file": f"maps/arcgis_online/{fname}",
                            "bytes": size, "features": len(gfeats), "geometry": fam, "order": GEOM_ORDER.get(gfeats[0]["geometry"]["type"], 2),
                            "how_to_add": "Map Viewer > Add > Add layer from file" if size <= ADD_FILE_LIMIT else
                                          "Too big for Map Viewer's 'Add layer from file' (~10 MB): use Content > New item > Your device, tick 'Create a hosted feature layer'",
                            "recommended": not url, "style": style_hint(gfeats) or hint})
    live.sort(key=lambda x: x["order"])
    uploads.sort(key=lambda x: (not x["recommended"], x["order"]))
    bbox = d.get("study_bbox")
    if not bbox or bbox[2] - bbox[0] > 30:
        bbox = [165.8, -47.4, 179.0, -34.0] if not job.region or not bbox else bbox  # mainland NZ (the Chathams cross the 180° line)
    link = mapviewer_link([x["url"] for x in live], bbox) if live else None
    summary = {"mapviewer_link": link, "extent": bbox, "live_layers": live, "uploads": uploads, "notes": notes,
               "how": "Open the link and sign in with your usual (school) ArcGIS login. The live layers appear with their legends. "
                      "Then add the upload files, style each by the suggested field, and Save the map."}
    with open(os.path.join(out_dir, "agol.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    with open(job.path("maps", "arcgis_online_publish.md"), "w", encoding="utf-8") as fh:
        fh.write(render_md(p["title"], summary))
    with open(os.path.join(out_dir, "OPEN_IN_ARCGIS_ONLINE.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(p["title"], summary))
    return summary


def _style_line(s):
    if not s:
        return "keep one symbol (no useful field to style by)"
    v = f" — values: {', '.join(s['values'][:8])}" if s.get("values") else ""
    return f"Styles > choose attribute **{s['field']}** > {s['how']}{v}"


def render_md(title, s):
    L = [f"# Final map in ArcGIS Online — {title}", "",
         "Works with your school / Google / Microsoft login: the app never signs in for you — you sign in when the map opens.", "",
         "## Step 1 — open the map with the live layers (they already have legends)", ""]
    if s["mapviewer_link"]:
        L += [f"[Open in ArcGIS Online Map Viewer]({s['mapviewer_link']})", "", "Layers added by that link (bottom → top):", ""]
        L += [f"- **{x['name']}** ({x['publisher']}) — {x['note']}" for x in s["live_layers"]]
    else:
        L += ["None of this project's datasets is a public ArcGIS service, so start with an empty map: "
              f"[Open Map Viewer]({MAPVIEWER})"]
    L += ["", "## Step 2 — add the files that are not online services", "",
          "| Layer | File | Size | How to add | Style it (gives the legend) |", "|---|---|---|---|---|"]
    for u in s["uploads"]:
        if u["recommended"]:
            L.append(f"| {u['name']} | `{u['file']}` | {u['bytes'] / 1e6:.2f} MB | {u['how_to_add']} | {_style_line(u['style'])} |")
            if u.get("why"):
                L.append(f"| | _{u['why']}_ | | | |")
    extra = [u for u in s["uploads"] if not u["recommended"]]
    if extra:
        L += ["", "Optional — your own filtered copies of the live layers (only if you need exactly your downloaded subset):", ""]
        L += [f"- `{u['file']}` ({u['bytes'] / 1e6:.2f} MB) — {u['how_to_add']}" for u in extra]
    L += ["", "## Step 3 — finish and save", "",
          "1. Layer order: polygons at the bottom, then lines, then points on top (drag in the Layers pane).",
          "2. For each uploaded layer: **Styles** → the field above. A single-symbol layer shows only its name in the legend.",
          "3. Turn on the **Legend** (left toolbar) and check every layer appears with its categories.",
          "4. **Save** (Save and open > Save as), add a summary with your data dates and sources.",
          "5. **Share** the map AND each uploaded layer at the same level (organisation or public) — otherwise others see a blank map.",
          "6. In your StoryMap: Add > Map > choose this saved map."]
    if s["notes"]:
        L += ["", "## Notes", ""] + [f"- {n}" for n in s["notes"]]
    return "\n".join(L) + "\n"


def render_html(title, s):
    import html
    e = html.escape
    rows = "".join(f"<li><b>{e(u['name'])}</b> — <code>{e(u['file'])}</code> ({u['bytes'] / 1e6:.2f} MB). {e(u['how_to_add'])}. "
                   f"Style: {e(_style_line(u['style']).replace('**', ''))}</li>" for u in s["uploads"] if u["recommended"])
    btn = (f'<p><a style="display:inline-block;padding:12px 18px;background:#0079c1;color:#fff;border-radius:6px;text-decoration:none" '
           f'href="{e(s["mapviewer_link"])}">Open in ArcGIS Online Map Viewer</a></p>') if s["mapviewer_link"] else f'<p><a href="{MAPVIEWER}">Open Map Viewer</a></p>'
    return (f"<!doctype html><meta charset=utf-8><title>{e(title)} — ArcGIS Online map</title>"
            f"<body style='font-family:system-ui;max-width:760px;margin:30px auto;padding:0 16px'><h1>{e(title)}</h1>"
            f"<p>Sign in with your usual school login when ArcGIS Online asks.</p>{btn}"
            f"<h2>Then add these files</h2><ul>{rows or '<li>Nothing to upload — all layers are live.</li>'}</ul>"
            f"<p>Full steps: <code>maps/arcgis_online_publish.md</code></p></body>")
