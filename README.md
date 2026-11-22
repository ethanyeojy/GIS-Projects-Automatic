# GeoProject Studio

Real New Zealand datasets, verified before you begin. Pick a project idea, review and filter each dataset, download them, check
them on a map, and get a draft case study laid out like an ArcGIS StoryMap.

## Run it

Double-click **start.bat**, or in a terminal:

```
cd <this folder>
py server.py
```

Then open http://127.0.0.1:8765 (press Ctrl+F5 after an update). The server only listens on your own computer. Python 3.9+, no
extra packages needed (optional: `pip install shapely` for faster region tagging).

## The workflow

1. **Projects** – 14 project ideas (hazards, freshwater, wildlife, outdoors, marine, weather, climate, environment). Each card has a
   photo, description and a dropdown of its datasets. **Refresh project** re-checks only that card.
2. **Project** – the main research question and why it matters, a rough outlook of the finished project, then every dataset with the
   expected records and size *after* your area, time period and filters. **Find missing datasets** searches real catalogues.
3. **Progress** – each dataset is its own task with a real state, stage, progress and last-activity time. Over-limit, too-many-records,
   time-gap and stalled situations pause only that dataset and ask you what to do. Retry / Skip / Cancel / Troubleshoot / Refresh status.
4. **Quality** – a plain-language check of what was downloaded.
5. **Files & maps** – download each dataset (GeoJSON, CSV, Excel, original) or everything at once; view any layer on a basemap.
6. **StoryMap plan** – a draft case study with StoryMaps-style layouts, photos and clearly labelled illustrations.

## Settings / Filters (top bar)

* **Time period** presets (this month … past 10 years, custom) show exact dates and are used for searching and filtering.
* **Maximum file size per download (MB)** – applies to each file separately (default 2048 MB). A project containing a file over the
  limit is marked *not possible* and hidden by default; choose a smaller study area to shrink big layers.

## Honesty rules

* Sources are only used if a live check passes; sizes and counts come from the source (estimates are labelled).
* Nothing is invented: unknown values are shown as unknown. Time gaps are explained, never silently replaced.
* Maps, charts and tables in the StoryMap plan are illustrations of layout, not results. No analysis is performed by this tool.
* Photos come from Wikimedia Commons with their credits; weather/climate/air/wave values come from Open-Meteo (CC BY 4.0, free for
  non-commercial use; model/reanalysis values, not station readings).

## Tests

`py tests/test_workflow.py` runs the workflow against the live services (plus a small local stand-in used only to force stalls).
`node tests/ui_check.mjs <url> <outdir>` drives the page in headless Edge/Chrome.
