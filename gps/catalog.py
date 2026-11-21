"""Project templates. A template is NOT a recommendation: it is only shown as actionable
after every essential dataset passes live verification (see feed.py).

Each template names the datasets it needs; datasets are located by the connectors at runtime
(service/layer discovery, taxon resolution), not assumed to work.
"""

REGC = {
    "id": "regc", "role": "boundary", "connector": "arcgis",
    "name": "Regional Council boundaries 2023", "publisher": "Stats NZ – Tatauranga Aotearoa",
    "service_url": "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/Regional_Council_2023/FeatureServer/0",
    "geometry": "esriGeometryPolygon", "name_field_re": r"NAME$", "required_field_res": [r"NAME$"],
    "landing_url": "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/Regional_Council_2023/FeatureServer/0",
    "licence_note": "Stats NZ boundary data — believed CC BY 4.0 (NOT verified by this app; confirm on Stats NZ page)",
    "server_subset": False,
}

FDSN_M5 = {
    "id": "geonet_fdsn", "role": "essential", "connector": "fdsn", "years": 10, "minmag": 5,
    "name": "GeoNet earthquake catalogue (FDSN event service), M ≥ 5, last 10 years",
    "publisher": "GeoNet (GNS Science / Toka Tū Ake EQC)",
    "landing_url": "https://www.geonet.org.nz/data/access/FDSN",
}

QUAKE_API = {
    "id": "geonet_quake_api", "role": "essential", "connector": "geonet_quake", "mmi": 3,
    "name": "GeoNet recent felt earthquakes (quake API, MMI ≥ 3)",
    "publisher": "GeoNet (GNS Science / Toka Tū Ake EQC)",
    "landing_url": "https://api.geonet.org.nz/",
}

ESL = {
    "id": "niwa_esl_1pc", "role": "essential", "connector": "arcgis",
    "name": "NZ 1% AEP extreme sea level flooding map", "publisher": "NIWA",
    "service_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer",
    "layer_name_re": r"CoastalFlood", "geometry": "esriGeometryPolygon",
    "landing_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer",
    "licence_note": "NIWA — copyright NIWA 2023; service says further scenarios are available on request/licence",
    "page_size": 500,
}

FLOODSTATS = {
    "id": "niwa_flood_stats", "role": "essential", "connector": "arcgis",
    "name": "NZ modelled flood frequency on river lines (Henderson & Collins v2)", "publisher": "NIWA",
    # NIWA's own server (gis.niwa.co.nz) returns HTTP 500; this is NIWA's hosted ArcGIS Online copy of the same layer.
    "service_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/arcgis/rest/services/NZ_Flood_Statistics_Henderson_Collins_V2_REC1_Layer_WFL1/FeatureServer",
    "geometry": "esriGeometryPolyline", "required_field_res": [r"100y"],
    "landing_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/arcgis/rest/services/NZ_Flood_Statistics_Henderson_Collins_V2_REC1_Layer_WFL1/FeatureServer",
    "licence_note": "NIWA — licence not confirmed by this app", "page_size": 1000,
}

GALAXIID = {
    "id": "gbif_galaxiidae", "role": "essential", "connector": "gbif",
    "taxon_name": "Galaxiidae", "taxon_rank": "FAMILY",
    "name": "GBIF occurrence records: Galaxiidae (galaxiid fishes), New Zealand, georeferenced",
    "publisher": "GBIF and contributing publishers",
    "landing_url": "https://www.gbif.org/",
}

DATASETS = {d["id"]: d for d in (REGC, FDSN_M5, QUAKE_API, ESL, FLOODSTATS, GALAXIID)}

COMMON_LIMITS = [
    "Spatial overlap or co-occurrence does not establish causation.",
    "This tool verifies access and runs basic checks only; it does not perform the analysis.",
]

PROJECTS = [
    {
        "id": "nz-quake-decade",
        "title": "Where have M5+ earthquakes clustered around New Zealand's regions over the last decade?",
        "theme": "earthquakes", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "multi-year", "data_type": "vector",
        "summary": "Map ten years of M5+ events from the GeoNet catalogue, count them by regional council area, and look at how depth varies across the country.",
        "question": "Which regions have had the most M5+ earthquakes since the start of the window, and how does focal depth vary spatially?",
        "study_area": "New Zealand region (or one regional council area you pick)",
        "time_period": "Rolling 10 years to the date of download (catalogue query is built at run time)",
        "analysis": "Summarise Within by regional council; depth classification; optional kernel density.",
        "outputs": "Event map, region count chart, depth histogram, short StoryMap.",
        "datasets": ["geonet_fdsn", "regc"],
        "limitations": [
            "Counts describe catalogued events, not hazard or damage.",
            "Magnitude types (e.g. ML, Mw) may be mixed in the catalogue; check the magtype field before comparing events.",
            "Regional boundaries stop at the 12-nautical-mile limit; offshore events beyond it will not fall in any region.",
            "Catalogue completeness and magnitude estimation can change over time.",
        ],
        "needs": [
            ("Event locations (point geometry)", [("geonet_fdsn", "geometry")]),
            ("Magnitude per event", [("geonet_fdsn", r"^magnitude$")]),
            ("Depth per event", [("geonet_fdsn", r"^depth_km$")]),
            ("Event time", [("geonet_fdsn", r"^time$")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Assign events to regions (spatial overlap)", [("geonet_fdsn", "geometry"), ("regc", "geometry")]),
        ],
    },
    {
        "id": "nz-felt-recent",
        "title": "Recent felt earthquakes: which regions have recorded the strongest shaking intensity?",
        "theme": "earthquakes", "difficulty": "Beginner", "workload_h": [3, 5], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "recent", "data_type": "vector",
        "summary": "Use GeoNet's recent felt-earthquake feed (MMI ≥ 3) to compare maximum reported intensity and event counts by region.",
        "question": "Among recent felt earthquakes, how do maximum MMI and event counts differ between regions?",
        "study_area": "New Zealand region (or one regional council area)",
        "time_period": "Window is set by the GeoNet API (determined at download and recorded in the package)",
        "analysis": "Summarise Within by region (count, max mmi); graduated symbols by mmi; optional time view.",
        "outputs": "Intensity map, region summary table, one-page dashboard or StoryMap.",
        "datasets": ["geonet_quake_api", "regc"],
        "limitations": [
            "Short, API-defined window: not representative of long-term seismicity.",
            "The mmi value is as supplied by GeoNet (check GeoNet's definition before interpreting); it is not a damage measure.",
            "No server-side spatial subset exists for this API; regional clipping happens locally after download.",
        ],
        "needs": [
            ("Event locations (point geometry)", [("geonet_quake_api", "geometry")]),
            ("MMI per event", [("geonet_quake_api", r"^mmi$")]),
            ("Magnitude and depth", [("geonet_quake_api", r"^magnitude$"), ("geonet_quake_api", r"^depth$")]),
            ("Event time", [("geonet_quake_api", r"^time$")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Assign events to regions (spatial overlap)", [("geonet_quake_api", "geometry"), ("regc", "geometry")]),
        ],
    },
    {
        "id": "nz-coastal-esl-exposure",
        "title": "Which regions have the most land area inside the modelled 1% AEP extreme sea level flood extent?",
        "theme": "flood risk", "difficulty": "Intermediate", "workload_h": [8, 14], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "modelled", "data_type": "vector",
        "summary": "Intersect NIWA's modelled 1% AEP extreme sea level flood extent with regional council boundaries and compare exposed area by region.",
        "question": "How much area falls within the modelled 1% AEP extreme sea level flood extent in each region?",
        "study_area": "New Zealand coastline (or one regional council area)",
        "time_period": "Static modelled layer (scenario defined in the service description — read before interpreting)",
        "analysis": "Repair Geometry, Pairwise Intersect, Calculate Geometry (NZTM), Summary Statistics by region.",
        "outputs": "Exposure map, area-by-region chart, methods note on model scope.",
        "datasets": ["niwa_esl_1pc", "regc"],
        "limitations": [
            "Modelled hazard extent, not observed flooding and not damage; exposure is not impact.",
            "Region polygons include sea out to 12 nm, so percentages must use land area, not total polygon area.",
            "The service states other scenarios are available only on licence request; this project uses the openly queryable layer only.",
            "No licence statement was found in service metadata — confirm reuse terms with NIWA before publishing.",
        ],
        "needs": [
            ("Flood extent polygons", [("niwa_esl_1pc", "geometry")]),
            ("Region polygons", [("regc", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Region land area (for percentages)", [("regc", r"LAND.*AREA")]),
            ("Compatible CRS for area maths", [("niwa_esl_1pc", "crs"), ("regc", "crs")]),
        ],
    },
    {
        "id": "nz-river-flood-flows",
        "title": "How do modelled 100-year river flood flows vary across New Zealand's river reaches and regions?",
        "theme": "rivers", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "modelled", "data_type": "vector",
        "summary": "Summarise NIWA's modelled flood-frequency estimates on river lines by region and map the highest 100-year flows.",
        "question": "Which regions contain the river reaches with the highest modelled 100-year flood flow, and how are flows distributed?",
        "study_area": "New Zealand rivers (strongly recommended: pick one region — national layer may be very large)",
        "time_period": "Static modelled statistics",
        "analysis": "Summarise Within (line length, mean/max flow), graduated symbology, bar chart by region.",
        "outputs": "Flow map, region comparison chart, notes on model uncertainty.",
        "datasets": ["niwa_flood_stats", "regc"],
        "limitations": [
            "Modelled flood-frequency estimates, not gauged observations; read NIWA's caveats in the service description.",
            "The national layer may be hundreds of MB — the size limit will pause the job for approval unless you choose a region.",
            "Flow magnitude is not flood extent or risk to people/infrastructure.",
        ],
        "needs": [
            ("River line geometry", [("niwa_flood_stats", "geometry")]),
            ("100-year flow field", [("niwa_flood_stats", r"100")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Compatible CRS for length maths", [("niwa_flood_stats", "crs"), ("regc", "crs")]),
        ],
    },
    {
        "id": "nz-galaxiid-records",
        "title": "Where have native galaxiid (freshwater fish) records been reported, and how has recording effort changed?",
        "theme": "biodiversity", "difficulty": "Intermediate", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Map georeferenced GBIF occurrence records for the family Galaxiidae in New Zealand and compare recording effort across regions and decades.",
        "question": "Where are galaxiid occurrence records concentrated, and how does the number of records vary by region and decade?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Historical records; years are whatever the data contain (reported in quality summary)",
        "analysis": "Filter by coordinate uncertainty (documented), Summarise Within by region and decade, hex-bin density.",
        "outputs": "Occurrence map, records-per-decade chart, bias/limitations section.",
        "datasets": ["gbif_galaxiidae", "regc"],
        "limitations": [
            "Occurrence records are not individual movement tracks, migration, abundance or habitat suitability.",
            "Record density reflects survey effort and observer access as well as fish distribution.",
            "Coordinate uncertainty varies widely; records have per-record licences (some non-commercial).",
            "Without a river network layer, this project cannot assess river connectivity or barriers.",
        ],
        "needs": [
            ("Record locations (point geometry)", [("gbif_galaxiidae", "geometry")]),
            ("Record date/year", [("gbif_galaxiidae", r"^year$"), ("gbif_galaxiidae", r"^eventDate$")]),
            ("Coordinate uncertainty", [("gbif_galaxiidae", r"coordinateUncertaintyInMeters")]),
            ("Species name", [("gbif_galaxiidae", r"^scientificName$")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Assign records to regions (spatial overlap)", [("gbif_galaxiidae", "geometry"), ("regc", "geometry")]),
        ],
    },
]

PROJECT_BY_ID = {p["id"]: p for p in PROJECTS}

REGION_NAMES = ["Northland", "Auckland", "Waikato", "Bay of Plenty", "Gisborne", "Hawke's Bay", "Taranaki",
                "Manawatū-Whanganui", "Wellington", "Tasman", "Nelson", "Marlborough", "West Coast",
                "Canterbury", "Otago", "Southland"]


# ------------------------------------------------------------------ analysis guide
def _fields(ctx, ds, rx):
    import re
    return [f for f in ctx.get("fields", {}).get(ds, []) if re.search(rx, f, re.I)]


def step(phase, title, purpose, inputs, tool, params, output, validation, limits):
    return {"phase": phase, "title": title, "purpose": purpose, "inputs": inputs, "tool": tool,
            "params": params, "output": output, "validation": validation, "limits": limits}


def guide_steps(project, ctx):
    """ctx: {'working': {ds_id: filename}, 'fields': {ds_id: [names]}, 'region': str|None}"""
    w = ctx.get("working", {})
    regc = w.get("regc", "regc_working.geojson")
    P = "Preparation"
    A = "Analysis"
    V = "Validation"
    steps = [
        step(P, "Create the project and geodatabase",
             "Give ArcGIS Pro one place to hold converted data.",
             "None (new project)", "ArcGIS Pro > New Project (Map template); Catalog > New File Geodatabase",
             "Name: project folder name; location: this package's /maps folder",
             "Project .aprx and a file geodatabase", "Project opens; geodatabase visible in Catalog",
             "Needs ArcGIS Pro (student licence is fine)."),
    ]
    for ds in project["datasets"]:
        steps.append(step(P, f"Convert {ds} working copy to a feature class",
                          "GeoJSON working copies must become feature classes before analysis.",
                          f"data/processed/{w.get(ds, ds + '_working.geojson')}",
                          "Conversion Tools > JSON To Features",
                          "Input JSON File = working copy; Geometry Type = match layer (points / lines / polygons)",
                          f"Feature class '{ds}' in the geodatabase",
                          "Feature count equals 'records' for this dataset in metadata/dataset_catalogue.csv",
                          "Working copies are in WGS84 (EPSG:4326); do not measure area/length until projected (next step)."))
    steps.append(step(P, "Project to NZTM2000 for measurement",
                      "Areas, lengths and distances need a projected metric CRS.",
                      "All feature classes from the previous step", "Data Management > Project",
                      "Output Coordinate System = NZGD2000 / New Zealand Transverse Mercator 2000 (WKID 2193); keep default geographic transformation unless prompted",
                      "<name>_nztm feature classes", "Describe > Spatial Reference shows WKID 2193 on every layer",
                      "Offshore Kermadec/Chatham features distort or fall outside the NZTM zone — note if you use them."))

    pid = project["id"]
    if pid == "nz-quake-decade":
        mag = _fields(ctx, "geonet_fdsn", r"^magnitude$") or ["magnitude"]
        steps += [
            step(A, "Count events and summarise magnitude/depth by region",
                 "Answers 'which regions have the most M5+ events?'",
                 "geonet_fdsn_nztm (points), regc_nztm (polygons); fields: magnitude, depth_km",
                 "Analysis Tools > Summarize Within",
                 "Input Polygons = regc_nztm; Input Summary Features = geonet_fdsn_nztm; Add Shape Summary = Yes; statistics: Mean/Max of magnitude, Mean/Median of depth_km; group by = none",
                 "region_quake_summary table/layer", "Sum of Point_Count over regions + events outside all regions (see quality_report.md 'untagged') = total records",
                 "Events beyond the 12 nm boundary are excluded from region counts; report them separately."),
            step(A, "Classify events by depth",
                 "Shows how depth varies spatially (e.g. shallow vs deeper events).",
                 "geonet_fdsn_nztm; field depth_km", "Layer Properties > Symbology > Graduated Colors (or Reclassify via Calculate Field)",
                 "Method = Manual Interval; example breaks 15, 40, 100 km are suggestions — choose and justify your own",
                 "Depth-classified event layer", "Compare class counts to a histogram of depth_km (Chart view)",
                 "Break values are your analytical choice, not a GeoNet classification."),
            step(A, "(Optional) Kernel density of events",
                 "Smooth visualisation of clustering.", "geonet_fdsn_nztm", "Spatial Analyst > Kernel Density",
                 "Population field = None; Cell size = 5000 m; Search radius = try 25 km and 75 km; Area units = square kilometres",
                 "Density raster", "Re-run with a second radius and confirm the main pattern persists",
                 "Needs Spatial Analyst extension; density depends strongly on radius."),
        ]
    elif pid == "nz-felt-recent":
        steps += [
            step(A, "Summarise count and maximum MMI by region", "Compares recent shaking between regions.",
                 "geonet_quake_api_nztm; regc_nztm; field mmi", "Analysis Tools > Summarize Within",
                 "Statistics: Max/Mean of mmi, Count; Input Polygons = regc_nztm", "region_felt_summary",
                 "Totals reconcile with record count; check events with mmi = -1 (see quality report for value range)",
                 "Short window; MMI is as supplied by GeoNet."),
            step(A, "Map events by intensity", "Visual comparison of shaking across space.",
                 "geonet_quake_api_nztm; fields mmi, magnitude", "Symbology > Graduated Symbols",
                 "Field = mmi; size by magnitude optional", "Intensity map layer", "Spot-check three events against GeoNet's website",
                 "Do not interpret MMI as damage."),
        ]
    elif pid == "nz-coastal-esl-exposure":
        steps += [
            step(A, "Repair geometry", "Intersect fails or misbehaves on invalid polygons.", "niwa_esl_1pc_nztm",
                 "Data Management > Repair Geometry", "Delete Null Geometry = No", "Repaired layer",
                 "Re-run Check Geometry; compare feature counts before/after", "Repair edits a copy; keep the raw file untouched."),
            step(A, "Intersect flood extent with regions", "Splits flood polygons by region.",
                 "niwa_esl_1pc_nztm (repaired), regc_nztm", "Analysis Tools > Pairwise Intersect",
                 "Join Attributes = All; Output Type = Same as input", "esl_by_region",
                 "Total intersected area ≈ total flood area inside regions (small offshore remainder is expected)",
                 "Flood areas outside the region polygons (beyond 12 nm) are dropped by intersect."),
            step(A, "Calculate area and summarise by region", "Quantifies exposure per region.",
                 "esl_by_region; regc_nztm", "Data Management > Calculate Geometry Attributes, then Analysis Tools > Summary Statistics",
                 "Area unit = square kilometres; Summary: SUM area; Case field = region name field (" + (", ".join(_fields(ctx, "regc", r"NAME$")) or "see data_dictionary.csv") + ")",
                 "Table: exposed km² per region", "Sum equals Calculate Geometry total", "Report as area inside a modelled extent, not as 'at risk'."),
            step(A, "(Optional) Percent of land area", "Normalises by region size.", "Summary table + regc land area field",
                 "Calculate Field", "Use a land-area field if present (fields found: " + (", ".join(_fields(ctx, "regc", r"AREA")) or "none found") + ")",
                 "exposed_pct_of_land", "Check percentages are < 100", "Do not divide by total polygon area (includes sea)."),
        ]
    elif pid == "nz-river-flood-flows":
        flow = _fields(ctx, "niwa_flood_stats", r"100")
        steps += [
            step(A, "Summarise 100-year flow by region", "Compares flow magnitude between regions.",
                 "niwa_flood_stats_nztm; fields: " + (", ".join(flow) or "100-year field (see data_dictionary.csv)"),
                 "Analysis Tools > Summarize Within", "Input Polygons = regc_nztm; statistics: Max, Mean, Median of the 100-year field; Add Shape Summary = Yes (line length)",
                 "region_flow_summary", "Check units and null counts in quality_report.md first", "Modelled estimates; read NIWA's caveats in the service description."),
            step(A, "Symbolise reaches by flow", "Highlights high-flow reaches.", "niwa_flood_stats_nztm", "Symbology > Graduated Colors",
                 "Method = Quantile or Natural Breaks; consider log scale for skewed data", "Flow map layer",
                 "Compare class breaks against a histogram", "Flow is not flood extent."),
        ]
    elif pid == "nz-galaxiid-records":
        steps += [
            step(A, "Decide and document a coordinate-uncertainty filter", "Imprecise records can fall in the wrong region/catchment.",
                 "gbif_galaxiidae_nztm; field coordinateUncertaintyInMeters", "Select Layer By Attribute",
                 "Example: coordinateUncertaintyInMeters <= 1000 OR missing flagged separately — choose and justify your own threshold",
                 "Selection → exported subset (keep the full layer)", "Record how many features each choice keeps",
                 "Missing uncertainty is common; excluding it changes the story."),
            step(A, "Records per region and decade", "Shows distribution of records and recording effort.",
                 "gbif_galaxiidae_nztm; regc_nztm; field year", "Calculate Field (decade = year // 10 * 10) then Summarize Within with case field decade",
                 "Group by = decade", "region_decade_counts", "Totals reconcile with filtered feature count",
                 "Counts reflect recording effort."),
            step(A, "Hexbin density map", "Reduces overplotting.", "gbif_galaxiidae_nztm", "Data Management > Generate Tessellation; then Summarize Within",
                 "Shape = Hexagon, 10 km size, extent = regc_nztm", "Hexbin layer with counts", "Counts sum to number of points inside regions",
                 "Density ≠ abundance."),
        ]
    steps += [
        step(V, "Reconcile counts and sanity-check", "Make sure outputs match what was downloaded.",
             "Your output tables; metadata/quality_report.md", "Manual + Statistics",
             "Compare totals with dataset_catalogue.csv 'records' and quality_report 'untagged/outside' counts", "A short validation note in your methods",
             "Every discrepancy explained", "Document any records you excluded (never delete originals)."),
        step(V, "Check against the source", "Catch systematic problems.", "3–5 records or features",
             "Source website / service viewer", "Pick samples across the study area", "Spot-check notes", "Values match the publisher's view",
             "Publisher viewers may use newer data than your snapshot (see retrieval dates)."),
        step("Storytelling", "Build the StoryMap from the outline", "Communicate only what you have actually produced.",
             "storymap/outline.md; your exported maps/charts", "ArcGIS StoryMaps (storymaps.arcgis.com) > New Story",
             "Follow the section order; add alt text and credits (use the planning tab)", "Draft story", "Every number in the story traces to a table you made",
             "Needs an ArcGIS Online account (student/organisational) to create and publish."),
    ]
    return steps


def storymap_sections(project, ctx=None):
    t = project["title"]
    return [
        {"id": "intro", "title": "Title and introduction", "text": "", "suggest": "Hero map or striking photo credit; 2–3 sentence hook. Working title: " + t},
        {"id": "question", "title": "Research question", "text": project["question"], "suggest": "Short text block; optional sidecar map of the study area."},
        {"id": "study_area", "title": "Study area map", "text": "", "suggest": "Map of the study area with region boundaries. Caption: " + project["study_area"]},
        {"id": "data_methods", "title": "Data and methods", "text": "", "suggest": "Table of datasets (publisher, retrieval date, licence) and a step diagram of your ArcGIS workflow."},
        {"id": "results", "title": "Results", "text": "", "suggest": "Map + chart from YOUR analysis outputs. Leave blank until analysis is done — nothing here is auto-generated."},
        {"id": "interpretation", "title": "Interpretation", "text": "", "suggest": "What the pattern might mean, with explicit uncertainty; avoid causal claims."},
        {"id": "limitations", "title": "Limitations", "text": "\n".join("- " + l for l in project["limitations"]), "suggest": "Plain bullet list; mention dataset currency and coverage."},
        {"id": "conclusion", "title": "Conclusion", "text": "", "suggest": "Answer the research question in 2–4 sentences; next steps."},
        {"id": "sources", "title": "Sources and credits", "text": "", "suggest": "Auto-filled in outline.md from dataset_catalogue.csv; add image credits."},
    ]
