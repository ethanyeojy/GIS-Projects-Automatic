# GeoProject Studio — prototype v0.1

Data-first GIS project discovery for New Zealand environmental topics. It only recommends a project as actionable
after **live requests** to the real data services confirm access, return a sample, and show the needed fields.

## Run it (Python 3.9+, no installs needed)

    python3 server.py --root ~/GeoProjects
    # open http://127.0.0.1:8765

1. Click **Refresh projects** – the backend contacts GeoNet, Stats NZ, NIWA and GBIF (metadata, counts and small samples only).
2. Pick a *Verified downloadable* project (optionally choose a region first) → **Start project and get data**.
3. Watch **Progress**; read **Quality**; browse **Files**; plan in **StoryMap plan**.

Optional: `pip install shapely` (faster region tagging on big files); `export ANTHROPIC_API_KEY=...` before starting to enable free-form assistant answers (untested).

## Architecture

| Part | Where it runs | Notes |
|---|---|---|
| UI (`static/index.html`) | browser | filters, cards, progress, files, StoryMap planner, assistant panel |
| Connectors (`gps/connectors.py`) | backend | ArcGIS REST, GeoNet FDSN + quake API, GBIF – verify + paged download |
| Jobs (`gps/jobs.py`) | backend threads | 9 stages, cancel, retry/resume (checksums + page cache), size-limit approval |
| Quality (`gps/quality.py`) | backend | geometry/date/duplicate checks, point-in-region tagging, compatibility matrix |
| Package (`gps/package.py`) | backend | writes the folder structure + guide + StoryMap outline |
| Assistant (`gps/assistant.py`) | backend | built-in answers from real state; optional Claude API (server-side key only) |

A Claude artifact/browser page alone cannot do this: it cannot reach most data hosts (CORS/network), write into your folders, or keep
jobs running. The local backend does the network, files and processing; the browser is only the interface.
Auto-refresh and jobs only run while the backend process is running.

## What is verified vs not (as of build)

- Tested offline against a **synthetic mock** of the services' response shapes (`python3 tests/e2e.py`): verification logic, paging, Esri-JSON fallback, region subsets, size-gate approval, cancel/retry/resume, no-overwrite, package files.
- **Not yet run against the real hosts** (the build environment's network blocked them). First run on your machine is the real test.
- Real response shapes were read for GeoNet quake API (GeoJSON) and ArcGIS service descriptions for Stats NZ, NIWA. GeoNet FDSN text format and GBIF API usage are written from documentation, unverified live.
- Assistant Claude-API mode: untested.

## Known limits

- Only 5 curated project templates, all NZ, all vector. Refresh re-verifies them; open-ended discovery of new datasets (e.g. data.govt.nz CKAN, LINZ with API key, regional council portals) is not built yet.
- No raster support, no LINZ/Stats NZ Datafinder (keys), no reprojection (working copies are WGS84; project to NZTM2000 in ArcGIS Pro – the guide says when).
- Lines/polygons are not clipped locally (use ArcGIS); points are clipped to a chosen region.
- Licences are not legally verified; unknown licences are labelled.
- No analysis is performed; guide/outline are instructions only.

## Layout produced per project

README.md, project_brief.md, data/{raw,processed,reference}, metadata/{dataset_catalogue.csv, provenance.json, data_dictionary.csv, quality_report.md, compatibility_report.md},
workflows/analysis_guide.md, storymap/{outline.md, draft_content.md, outline.json, versions/}, maps/, images/originals/, exports/, logs/.
