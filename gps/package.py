"""Writes the local project package documents. Everything stated here comes from the job's
real results; analysis sections are explicitly left for the student to complete."""
import csv
import json
import os
import platform
import sys
from datetime import datetime

from . import catalog, connectors
from .feed import write_json_atomic

APP_VERSION = "0.2.0"  # the page checks this: if the server is older than the page, it tells the user to restart


def _w(job, rel, text):
    p = job.path(*rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _mb(b):
    return f"{b / 1e6:.2f} MB" if b else "0 MB"


def _fetch_story_images(job, p):
    """Download the project's credited photos into images/originals and attach them to story sections."""
    import re
    from . import net
    cs = p.get("case_study") or {}
    order = ["cover", "q1", "q2", "q3", "conclusion"]
    out, inline_i = [], 0
    os.makedirs(job.path("images", "originals"), exist_ok=True)
    for im in cs.get("images", []):
        if im["role"] == "cover":
            sec = "cover"
        else:
            inline_i += 1
            sec = order[min(inline_i, len(order) - 1)]
        name = f"{sec}_" + re.sub(r"[^A-Za-z0-9]+", "-", im["alt"])[:40].strip("-").lower() + ".jpg"
        target = job.path("images", "originals", name)
        status = "downloaded"
        try:
            if not os.path.exists(target):
                st, _, body = net.request(im["url"], timeout=90, retries=2)
                with open(target, "wb") as f:
                    f.write(body)
        except Exception as e:  # noqa: BLE001 - keep the credit + source link so the image can be fetched by hand
            status = f"download failed ({str(e)[:80]}) — use the source page link"
            job.log(f"Image not downloaded ({name}): {e}")
        out.append({"file": "images/originals/" + name if status == "downloaded" else "", "section": sec, "alt": im["alt"],
                    "caption": im["alt"], "credit": f"{im['credit']} — {im['licence']} — via Wikimedia Commons",
                    "licence": im["licence"], "source_page": im["page"], "status": status})
    return out


def render_outline_md(outline):
    lines = [f"# StoryMap outline — {outline.get('title', '')}", "",
             "> Planning outline. This is NOT a live ArcGIS StoryMap, and no section contains analysis results unless you wrote them.", ""]
    for s in outline["sections"]:
        lines += [f"## {s['title']}", ""]
        if s.get("parts"):
            for part in s["parts"]:
                lines += [f"**{part['label']}**", "", (part["text"].strip() or "_(to be written)_"), ""]
        elif s.get("text", "").strip():
            lines += [s["text"].strip(), ""]
        else:
            lines += ["_(empty — to be written)_", ""]
        if s.get("layout"):
            lines += [f"*StoryMaps layout:* {s['layout']}", ""]
        lines += [f"*Suggested content:* {s.get('suggest', '')}", ""]
        for ph in s.get("placeholders", []):
            lines += [f"- **[{ph['kind'].upper()} PLACEHOLDER — illustration only]** {ph['label']} — build this from your own analysis"]
        for im in outline.get("images", []):
            if im.get("section") == s["id"]:
                lines += [f"- Image: `{im.get('file') or im.get('source_page')}` — caption: {im.get('caption') or '(none)'}; credit: {im.get('credit') or '(none)'}; alt text: {im.get('alt') or '(MISSING)'}"]
        lines.append("")
    return "\n".join(lines)


def write_all(job):
    p, d = job.project, job.data
    now = connectors.now_iso()
    ds_ids = p["datasets"]
    rows = []
    for ds in ds_ids:
        spec = catalog.DATASETS[ds]
        ver = d["verification"].get(ds) or {}
        dl = d["downloads"].get(ds) or {}
        ins = d["inspections"].get(ds) or {}
        rows.append({
            "dataset_id": ds, "name": spec["name"], "publisher": spec["publisher"], "role": spec["role"],
            "landing_url": spec.get("landing_url") or "", "access_url": ver.get("access_url") or "",
            "licence": (ver.get("licence") or "")[:300], "licence_verified": ver.get("licence_verified", False),
            "retrieved_at": dl.get("retrieved_at", ""), "verified_at": ver.get("verified_at", ""),
            "raw_file": "; ".join(f["file"] for f in dl.get("raw_files", [])),
            "raw_bytes": sum(f["bytes"] for f in dl.get("raw_files", [])),
            "sha256": "; ".join(f["sha256"] for f in dl.get("raw_files", [])),
            "records": ins.get("records", dl.get("records", "")), "working_file": d["working"].get(ds, ""),
            "download_status": job.datasets[ds]["status"],
        })
    with open(job.path("metadata", "dataset_catalogue.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # export manifest: every file a student can open, with its format and coordinate system (and why any format was not made)
    with open(job.path("metadata", "export_manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "format", "file", "records", "bytes", "coordinate_system", "status"])
        for ds in ds_ids:
            ex = d.get("exports", {}).get(ds) or {}
            for e in ex.get("written", []):
                w.writerow([ds, e["format"], e["file"], e["records"], e["bytes"], e["crs"], "written"])
            for s in ex.get("skipped", []):
                w.writerow([ds, s["format"], "", "", "", "", "NOT created: " + s["reason"]])
    # data dictionary
    with open(job.path("metadata", "data_dictionary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "field", "inferred_type", "null_count", "example_value", "origin", "service_alias_or_type"])
        for ds in ds_ids:
            ins = d["inspections"].get(ds) or {}
            alias = {x["name"]: (x.get("alias") or x.get("type") or "") for x in (d["verification"].get(ds) or {}).get("fields", [])}
            for k, st in (ins.get("field_stats") or {}).items():
                w.writerow([ds, k, st["type"], st["nulls"], st["example"], "original (as published)", alias.get(k, "")])
            if ds == "regc":
                w.writerow([ds, "is_study_area", "bool", 0, "", "calculated by this tool", "flag: selected study area"])
            elif (job.data["inspections"].get(ds) or {}).get("geometry_types", {}).get("Point"):
                w.writerow([ds, "calc_region", "str", (job.data["tag_stats"].get(ds) or {}).get("untagged", ""), "", "calculated by this tool (point-in-polygon against Stats NZ regional council layer)", "empty = outside all region polygons"])

    # provenance
    prov = {"app": "GeoProject Studio", "app_version": APP_VERSION, "python": sys.version.split()[0], "platform": platform.platform(),
            "job_id": job.id, "project_id": p["id"], "project_title": p["title"], "region": job.region, "study_bbox_wgs84": d["study_bbox"],
            "created": job.created, "documented_at": now, "datasets": {}, "processing": [
                "Raw files saved unchanged in data/raw (FDSN text / GBIF JSON / API GeoJSON / merged paged ArcGIS GeoJSON).",
                "ArcGIS services were queried with outSR=4326 so merged GeoJSON is WGS84 (native CRS recorded in verification).",
                "Working copies in data/processed are GeoJSON (+CSV for points) derived from raw; calc_region added by point-in-polygon.",
                "No records were deleted from raw; records excluded from a working copy (study-area clip) are listed in metadata/exclusions_*.csv.",
            ], "limits_of_this_tool": ["No licence text was legally verified.", "No analysis has been performed."]}
    for ds in ds_ids:
        prov["datasets"][ds] = {"verification": d["verification"].get(ds), "download": d["downloads"].get(ds),
                                "inspection_summary": {k: v for k, v in (d["inspections"].get(ds) or {}).items() if k not in ("field_stats",)}}
    write_json_atomic(job.path("metadata", "provenance.json"), prov)

    # quality report
    q = [f"# Quality report — {p['title']}", "", f"Generated {now}. Checks are mechanical; they do **not** confirm the data is accurate or complete in the real world.", "",
         "| Dataset | Downloaded | Validated | Records | Raw size |", "|---|---|---|---|---|"]
    for ds in ds_ids:
        j = job.datasets[ds]
        q.append(f"| {j['name']} | {'yes' if j['status'] in ('downloaded', 'inspecting', 'validated') else j['status']} | {'yes (checks ran)' if j['validated'] else 'no'} | {j['records']} | {_mb(j['bytes'])} |")
    q.append("")
    for ds in ds_ids:
        ins = d["inspections"].get(ds) or {}
        j = job.datasets[ds]
        q += [f"## {j['name']}", f"- Publisher: {j['publisher']}", f"- Geometry types: {ins.get('geometry_types')}", f"- Features with geometry: {ins.get('with_geometry')}",
              f"- Invalid geometries: {ins.get('invalid_geometry', 0)}; duplicate ids: {ins.get('duplicate_ids', 'n/a')}; possible duplicate records: {ins.get('duplicate_point_records', 0)}"]
        if ins.get("bbox"):
            q.append(f"- Bounding box (lon/lat): {[round(x, 3) for x in ins['bbox']]}")
        for k, v in (ins.get("date_fields") or {}).items():
            q.append(f"- Date field `{k}`: parsed {v['parsed']}, unparsed {v['unparsed']}, range {v['min']} → {v['max']}")
        for k, v in (ins.get("special") or {}).items():
            q.append(f"- {k}: {json.dumps(v, ensure_ascii=False)}")
        ts = d["tag_stats"].get(ds)
        if ts:
            q.append(f"- Region tagging (calculated): {ts['total'] - ts['untagged']} of {ts['total']} points inside a regional-council polygon; {ts['untagged']} outside all polygons; {ts['excluded_by_clip']} excluded from working copy by study-area clip")
            q.append(f"  - by region: {json.dumps(ts['by_region'], ensure_ascii=False)}")
        q.append("")
        q.append("**Warnings**" if j["warnings"] else "**Warnings:** none raised")
        for wmsg in j["warnings"]:
            q.append(f"- {wmsg}")
        q.append("")
    q += ["## Not checked", "- Whether values are correct, complete, or representative.", "- Licence terms beyond what the services state (see dataset_catalogue.csv).",
          "- Attribute units except where the publisher documents them — read the source descriptions."]
    _w(job, "metadata/quality_report.md", "\n".join(q))

    # compatibility report
    c = [f"# Compatibility report — {p['title']}", "", "Links each part of the research question to the datasets and fields needed. **Blocking** = cannot answer that part with this package; **warning** = manageable limitation.", "",
         "| Need | Datasets | Status | Evidence |", "|---|---|---|---|"]
    for r in d["compat"]:
        c.append(f"| {r['need']} | {', '.join(r['datasets'])} | {r['status'].upper()} | {r['detail']} |")
    c += ["", "## Coordinate systems", "- Working copies: EPSG:4326 (lon/lat). Native CRS per dataset: " +
          "; ".join(f"{ds}: {(d['verification'].get(ds) or {}).get('crs') or 'unknown'}" for ds in ds_ids),
          "- Reproject to NZTM2000 (EPSG:2193) in ArcGIS Pro before measuring area/length (see the 'Project to NZTM2000' step in the analysis guide).", "",
          "## Time coverage (from the data)"]
    for k, v in d["temporal"].items():
        c.append(f"- `{k}`: {v[0]} → {v[1]}")
    if not d["temporal"]:
        c.append("- No date fields (static/modelled layers).")
    c += ["", "## Limitations that remain", *["- " + x for x in p["limitations"] + catalog.COMMON_LIMITS]]
    _w(job, "metadata/compatibility_report.md", "\n".join(c))

    # analysis guide
    ctx = {"working": d["working"], "fields": d["fields"], "region": job.region}
    steps = catalog.guide_steps(p, ctx)
    write_json_atomic(job.path("workflows", "analysis_guide.json"), steps)
    g = [f"# Analysis guide — {p['title']}", "", "These are **instructions**. No analysis has been run by this tool; nothing below is a result.", "",
         f"Study area: {job.region or 'New Zealand'} · Software: {', '.join(p['software'])} · Estimated workload: {p['workload_h'][0]}–{p['workload_h'][1]} hours (estimate)", ""]
    n = 0
    cur = None
    for s in steps:
        if s["phase"] != cur:
            cur = s["phase"]
            g += [f"## {cur}", ""]
        n += 1
        g += [f"### Step {n}: {s['title']}", f"- **Purpose:** {s['purpose']}", f"- **Inputs:** {s['inputs']}", f"- **Tool:** {s['tool']}",
              f"- **Key parameters:** {s['params']}", f"- **Expected output:** {s['output']}", f"- **Validation:** {s['validation']}", f"- **Limitations/licensing:** {s['limits']}", ""]
    _w(job, "workflows/analysis_guide.md", "\n".join(g))

    # storymap
    story_images = _fetch_story_images(job, p)  # must exist before the credits text below uses it
    sections = catalog.storymap_sections(p, {"rows": rows, "period": job.plan.get("period"), "region": job.region})
    srcs = "\n".join(f"- {r['name']} — {r['publisher']}. Retrieved {r['retrieved_at'][:10]}. {r['landing_url']}" for r in rows)
    photo_credits = "\n".join(f"- Photo ({im['section']}): {im['credit']} — {im['source_page']}" for im in story_images if im.get("source_page"))
    for s in sections:
        if s["id"] == "sources":
            s["text"] = srcs + ("\n\nPhotos:\n" + photo_credits if photo_credits else "")
            s["parts"] = [{"label": "Sources", "text": s["text"]}]
    outline = {"title": p["title"], "sections": sections, "images": story_images, "question": p["question"], "purpose": p.get("purpose", "")}
    write_json_atomic(job.path("storymap", "outline.json"), outline)
    _w(job, "storymap/outline.md", render_outline_md(outline))
    os.makedirs(job.path("images", "originals"), exist_ok=True)
    dc = [f"# Draft content — {p['title']}", "", "> Skeleton only. Replace every `[TO WRITE]` after you have run your analysis. Nothing here is a finding.", "",
          "## Introduction", f"[TO WRITE: why this question matters.] Research question: {p['question']}", "",
          "## Data", *[f"- {r['name']} ({r['publisher']}), {r['records']} records, retrieved {r['retrieved_at'][:10]}." for r in rows], "",
          "## Methods", "[TO WRITE: describe the steps you actually carried out — see workflows/analysis_guide.md.]", "",
          "## Results", "[TO WRITE: only report numbers from your own outputs.]", "",
          "## Limitations", *["- " + x for x in p["limitations"]], "", "## Conclusion", "[TO WRITE]"]
    _w(job, "storymap/draft_content.md", "\n".join(dc))

    # Final map in ArcGIS Online: live-layer link + upload-ready files + style hints (never blocks the rest of the package)
    from . import agol
    try:
        d["agol"] = agol.build(job)
    except Exception as e:  # noqa: BLE001
        d["agol"] = {"error": str(e)}
        job.log(f"ArcGIS Online map files could not be made: {e}")

    # brief + README
    brief = [f"# Project brief — {p['title']}", "", f"**Summary:** {p['summary']}", "", f"**Research question:** {p['question']}", f"**Study area:** {job.region or p['study_area']}",
             f"**Time period:** {p['time_period']}", f"**Proposed analysis:** {p['analysis']}", f"**Expected outputs:** {p['outputs']}",
             f"**Difficulty:** {p['difficulty']} · **Workload (estimate):** {p['workload_h'][0]}–{p['workload_h'][1]} h", "", "## Datasets"] + \
            [f"- {r['name']} — {r['publisher']} (verified {r['verified_at'][:19]}, retrieved {r['retrieved_at'][:19]})" for r in rows] + ["", "## Important limitations"] + ["- " + x for x in p["limitations"] + catalog.COMMON_LIMITS]
    _w(job, "project_brief.md", "\n".join(brief))
    readme = [f"# {p['title']}", "", f"Created by GeoProject Studio {APP_VERSION} on {now}.", "",
              "**Status:** data sourced, inspected and organised. **No analysis has been done.**", "",
              "## Folder map", "- `data/raw/` original files exactly as received (never edit)", "- `data/processed/` working copies (GeoJSON/CSV)", "- `data/reference/` study-area boundary",
              "- `metadata/` catalogue, provenance, data dictionary, quality + compatibility reports", "- `workflows/` ArcGIS analysis guide", "- `storymap/` outline and draft skeleton",
              "- `maps/` ArcGIS Online map: `arcgis_online_publish.md`, `arcgis_online/OPEN_IN_ARCGIS_ONLINE.html` and upload-ready layers", "- `images/ exports/` yours to fill", "- `logs/` job log and resumable state", "",
              "## Start here", "1. Read `metadata/quality_report.md` and `metadata/compatibility_report.md`.", "2. Follow `workflows/analysis_guide.md` in ArcGIS Pro.", "3. Plan your story in `storymap/outline.md`.", "",
              "## Reuse", "Check each dataset's licence in `metadata/dataset_catalogue.csv`; credit publishers in your StoryMap."]
    _w(job, "README.md", "\n".join(readme))
