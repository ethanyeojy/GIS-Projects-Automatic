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
    "name": "GeoNet earthquake catalogue (FDSN event service), M ≥ 5",
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
    "id": "niwa_esl_1pc", "simplify_m": 5, "role": "essential", "connector": "arcgis",
    "name": "NZ 1% AEP extreme sea level flooding map", "publisher": "NIWA",
    "service_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer",
    "layer_name_re": r"CoastalFlood", "geometry": "esriGeometryPolygon",
    "landing_url": "https://services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer",
    "licence_note": "NIWA — copyright NIWA 2023; service says further scenarios are available on request/licence",
    "page_size": 500,
}

FLOODSTATS = {
    "id": "niwa_flood_stats", "simplify_m": 5, "role": "essential", "connector": "arcgis",
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

# ---------------------------------------------------------------- more datasets (all openly queryable)
_DOC_B = "https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/{}/FeatureServer"
_STATS_B = "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/{}/FeatureServer"
_NIWA_B = "https://services3.arcgis.com/fp1tibNcN9mbExhG/arcgis/rest/services/{}/FeatureServer"
DOC = "Department of Conservation – Te Papa Atawhai"
STATS = "Stats NZ – Tatauranga Aotearoa"
NIWA = "NIWA – Taihoro Nukurangi"
GEONET = "GeoNet (GNS Science / Toka Tū Ake EQC)"


def _arc(id_, name, publisher, url, geometry=None, licence=None, **kw):
    d = {"id": id_, "role": "essential", "connector": "arcgis", "name": name, "publisher": publisher,
         "service_url": url, "landing_url": url, "licence_note": licence or f"{publisher} — licence not confirmed by this app"}
    if geometry:
        d["geometry"] = geometry
    d.update(kw)
    return d


def _gbif(id_, name, taxon, rank):
    return {"id": id_, "role": "essential", "connector": "gbif", "taxon_name": taxon, "taxon_rank": rank,
            "name": f"GBIF sightings: {name}", "publisher": "GBIF and contributing publishers", "landing_url": "https://www.gbif.org/"}


POLY, LINE, PT = "esriGeometryPolygon", "esriGeometryPolyline", "esriGeometryPoint"
_EXTRA = [
    _arc("ta", "Territorial Authority (city & district council) boundaries 2023", STATS, _STATS_B.format("Territorial_Authority_2023"), POLY,
         "Stats NZ boundary data — believed CC BY 4.0 (NOT verified by this app)"),
    _arc("census_ta", "2023 Census population change by age group, by council area", STATS, _STATS_B.format("2023_Census_population_change_by_age_group_and_TALB"), POLY,
         "Stats NZ census data — believed CC BY 4.0 (NOT verified by this app)"),
    _arc("urban_rural", "Urban and rural areas 2022", STATS, _STATS_B.format("Urban_Rural_Areas_2022"), POLY,
         "Stats NZ boundary data — believed CC BY 4.0 (NOT verified by this app)", page_size=100),
    {"id": "geonet_volcano", "role": "essential", "connector": "geojson_url", "url": "https://api.geonet.org.nz/volcano/val",
     "headers": {"Accept": "application/vnd.geo+json;version=2"}, "required_props": ["volcanoTitle", "level", "acc"],
     "name": "GeoNet volcanic alert levels (current)", "publisher": GEONET, "landing_url": "https://www.geonet.org.nz/volcano",
     "licence_note": "GeoNet data policy — believed CC BY 4.0 (NOT verified by this app)",
     "notes": ["A live snapshot: alert levels change as volcanoes change."]},
    _arc("nz_plates", "New Zealand tectonic plate boundaries", "Esri NZ (as published on ArcGIS Online)", "https://services1.arcgis.com/NIkwK16KnqB4PR1J/arcgis/rest/services/New_Zealand_Tectonic_Plate_Boundaries/FeatureServer", LINE),
    _arc("niwa_flow_gauges", "River flow gauges with at-site flood statistics", NIWA, _NIWA_B.format("NZ_Flood_Statistics_Henderson_Collins_V2_FlowGauges_Layer_WFL2"), PT),
    _arc("niwa_coast_erosion", "Coastal sensitivity index (erosion)", NIWA, _NIWA_B.format("NZ_Coastal_Sensitivity_Index_CSI_erosion")),
    _arc("niwa_coastline", "NZ coastlines and islands (1:50k topo)", NIWA, _NIWA_B.format("NZ_Coastlines_and_Islands_Polygons_Topo_1_50k"), POLY),
    # freshwater & wildlife (GBIF = sightings, DOC = managed layers)
    _gbif("gbif_longfin", "longfin eel (tuna)", "Anguilla dieffenbachii", "SPECIES"),
    _gbif("gbif_inanga", "inanga (whitebait)", "Galaxias maculatus", "SPECIES"),
    _gbif("gbif_bullies", "bullies (Gobiomorphus)", "Gobiomorphus", "GENUS"),
    _gbif("gbif_trout", "brown trout (introduced)", "Salmo trutta", "SPECIES"),
    _gbif("gbif_kiwi", "kiwi (Apteryx)", "Apteryx", "GENUS"),
    _gbif("gbif_kakapo", "kākāpō", "Strigops habroptilus", "SPECIES"),
    _gbif("gbif_kea", "kea", "Nestor notabilis", "SPECIES"),
    _gbif("gbif_penguin", "yellow-eyed penguin (hoiho)", "Megadyptes antipodes", "SPECIES"),
    _gbif("gbif_hectors", "Hector's dolphin", "Cephalorhynchus hectori", "SPECIES"),
    _gbif("gbif_sealion", "New Zealand sea lion", "Phocarctos hookeri", "SPECIES"),
    _arc("doc_fish", "Freshwater fish distribution (non-migratory)", DOC, _DOC_B.format("NonMigratoryFreshwaterFishDistribution")),
    _arc("doc_stoat", "Stoat distribution 2014", DOC, _DOC_B.format("Stoat_Distribution_2014")),
    _arc("doc_possum", "Possum distribution 2014", DOC, _DOC_B.format("Possum_Distribution_2014")),
    _arc("doc_kea_habitat", "Kea habitat 2019", DOC, _DOC_B.format("Kea_Habitat_2019")),
    _arc("doc_land", "Public conservation land", DOC, "https://services1.arcgis.com/3JjYDyG3oajxU6HO/ArcGIS/rest/services/DOC_Public_Conservation_Land/FeatureServer/0", POLY, page_size=200),
    _arc("doc_huts", "DOC huts", DOC, _DOC_B.format("DOC_Huts_Open_Data")),
    _arc("doc_campsites", "DOC campsites", DOC, _DOC_B.format("DOC_Campsites_Open_Data")),
    _arc("doc_tracks", "DOC walking & tramping tracks", DOC, _DOC_B.format("DOC_Tracks_Open_Data"), LINE),
    _arc("doc_walks", "DOC walking experiences", DOC, _DOC_B.format("DOC_Walking_Experiences")),
    _arc("doc_hunting", "DOC recreational hunting areas", DOC, _DOC_B.format("DOC_Recreational_Hunting_Areas"), POLY),
    _arc("doc_marine_reserves", "Marine reserves", DOC, _DOC_B.format("DOC_Marine_Reserves"), POLY),
    _arc("doc_mammal_sanct", "Marine mammal sanctuaries", DOC, _DOC_B.format("DOC_Marine_Mammal_Sanctuaries"), POLY),
    _arc("doc_marine_prot", "All marine protection areas", DOC, _DOC_B.format("DOC_Marine_Protections")),
    _arc("eez", "Exclusive Economic Zone outer limits", DOC, _DOC_B.format("EEZ_OuterLimits")),
    _arc("doc_eco_districts", "Ecological districts", DOC, _DOC_B.format("Ecological_Districts"), POLY),
    _gbif("gbif_stoat", "stoat (introduced predator)", "Mustela erminea", "SPECIES"),
    _gbif("gbif_shiprat", "ship rat (introduced predator)", "Rattus rattus", "SPECIES"),
    _gbif("gbif_norway_rat", "Norway rat (introduced predator)", "Rattus norvegicus", "SPECIES"),
    _gbif("gbif_red_deer", "red deer (introduced game animal)", "Cervus elaphus", "SPECIES"),
    _gbif("gbif_little_penguin", "little penguin (kororā)", "Eudyptula minor", "SPECIES"),
    _gbif("gbif_gannet", "Australasian gannet (tākapu)", "Morus serrator", "SPECIES"),
    _gbif("gbif_kauri", "kauri", "Agathis australis", "SPECIES"),
    _gbif("gbif_pohutukawa", "pōhutukawa", "Metrosideros excelsa", "SPECIES"),
    _gbif("gbif_totara", "tōtara", "Podocarpus totara", "SPECIES"),
    # ---- weather / climate / environment (Open-Meteo reanalysis + NIWA station and event layers)
    {"id": "om_temp", "role": "essential", "connector": "openmeteo", "api": "archive", "variables": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"],
     "name": "Daily temperature (16 NZ regional centres)", "publisher": "Open-Meteo.com (ERA5 reanalysis)",
     "landing_url": "https://open-meteo.com/en/docs/historical-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_rain", "role": "essential", "connector": "openmeteo", "api": "archive", "variables": ["precipitation_sum", "rain_sum", "precipitation_hours"],
     "name": "Daily rainfall (16 NZ regional centres)", "publisher": "Open-Meteo.com (ERA5 reanalysis)",
     "landing_url": "https://open-meteo.com/en/docs/historical-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_wind", "role": "essential", "connector": "openmeteo", "api": "archive", "variables": ["wind_speed_10m_max", "wind_gusts_10m_max"],
     "name": "Daily wind speed and gusts (16 NZ regional centres)", "publisher": "Open-Meteo.com (ERA5 reanalysis)",
     "landing_url": "https://open-meteo.com/en/docs/historical-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_snow", "role": "essential", "connector": "openmeteo", "api": "archive", "variables": ["snowfall_sum"],
     "name": "Daily snowfall (16 NZ regional centres)", "publisher": "Open-Meteo.com (ERA5 reanalysis)",
     "landing_url": "https://open-meteo.com/en/docs/historical-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_sun", "role": "essential", "connector": "openmeteo", "api": "archive", "variables": ["sunshine_duration", "et0_fao_evapotranspiration"],
     "name": "Daily sunshine and evapotranspiration (16 NZ regional centres)", "publisher": "Open-Meteo.com (ERA5 reanalysis)",
     "landing_url": "https://open-meteo.com/en/docs/historical-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_marine", "role": "essential", "connector": "openmeteo", "api": "marine", "variables": ["wave_height_max", "wave_period_max"],
     "name": "Daily wave height and period (sea off 16 NZ centres)", "publisher": "Open-Meteo.com (marine model)",
     "landing_url": "https://open-meteo.com/en/docs/marine-weather-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    {"id": "om_air", "role": "essential", "connector": "openmeteo", "api": "air", "variables": ["pm2_5", "pm10"],
     "name": "Air quality: fine particles PM2.5 and PM10 (16 NZ centres)", "publisher": "Open-Meteo.com (CAMS global air-quality model)",
     "landing_url": "https://open-meteo.com/en/docs/air-quality-api", "licence_note": "Open-Meteo: CC BY 4.0, free for non-commercial use — attribute Open-Meteo.com"},
    _arc("cliflo_rain", "Rain-gauge station locations (CliFlo network)", NIWA, _NIWA_B.format("Cliflo_Rain_Stations_WFL1"), PT),
    _arc("auck_floods", "Auckland January 2023 flood impact records", NIWA, _NIWA_B.format("Auck_Floods_Jan23_Merged_GeoJSON"), PT),
]
DATASETS = {d["id"]: d for d in (REGC, FDSN_M5, QUAKE_API, ESL, FLOODSTATS, GALAXIID, *_EXTRA)}

COMMON_LIMITS = [
    "Spatial overlap or co-occurrence does not establish causation.",
    "This tool verifies access and runs basic checks only; it does not perform the analysis.",
]

PROJECTS = [
    {
        "id": "nz-quake-decade", "icon": "🌋",
        "title": "Shaky Isles: Earthquakes & Volcanoes",
        "tagline": "Where the ground moves, and why.",
        "theme": "hazards", "difficulty": "Beginner", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "multi-year", "data_type": "vector",
        "summary": "Explore where New Zealand's earthquakes happen, which ones people actually felt, how the plate boundary lines up with them, and which volcanoes are restless right now.",
        "question": "Which regions have had the most M5+ earthquakes in the last decade, how does that compare with recent felt shaking, and how do events line up with plate boundaries and volcanoes?",
        "study_area": "All of New Zealand (or one region you pick)",
        "time_period": "Ten years of M5+ events, plus GeoNet's recent felt-quake window and today's volcano alert levels",
        "analysis": "Summarise Within by region; depth classes; distance to plate boundary; count by urban vs rural area; optional kernel density.",
        "outputs": "Event map, region count chart, depth histogram, volcano alert map, short StoryMap.",
        "datasets": ["geonet_fdsn", "geonet_quake_api", "geonet_volcano", "nz_plates", "urban_rural", "regc"],
        "limitations": [
            "Counts describe catalogued events, not hazard or damage.",
            "Magnitude types (e.g. ML, Mw) may be mixed in the catalogue; check the magtype field before comparing events.",
            "Regional boundaries stop at the 12-nautical-mile limit; offshore events beyond it will not fall in any region.",
            "The felt-quake feed covers a short, GeoNet-defined window; volcano alert levels are a snapshot of today.",
        ],
        "needs": [
            ("Event locations, magnitude, depth and time", [("geonet_fdsn", "geometry"), ("geonet_fdsn", r"^magnitude$"), ("geonet_fdsn", r"^depth_km$"), ("geonet_fdsn", r"^time$")]),
            ("Felt intensity (MMI) per recent event", [("geonet_quake_api", r"^mmi$")]),
            ("Volcano alert level", [("geonet_volcano", r"^level$")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Assign events to regions (spatial overlap)", [("geonet_fdsn", "geometry"), ("regc", "geometry")]),
        ],
    },
    {
        "id": "nz-coastal-esl-exposure", "icon": "🌊",
        "title": "Rising Waters: Floods & Sea Level",
        "tagline": "Which coasts and rivers are most exposed.",
        "theme": "hazards", "difficulty": "Intermediate", "workload_h": [10, 16], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "modelled", "data_type": "vector",
        "summary": "Compare modelled sea-level flooding along the coast with modelled river flood flows and the gauges that measure them, then see how exposed each region is.",
        "question": "How much area falls within the modelled 1% AEP extreme sea level flood extent in each region, and where are river flood flows highest?",
        "study_area": "New Zealand coastline and rivers (strongly recommended: pick one region — the national layers are very large)",
        "time_period": "Static modelled layers (scenarios are defined in each service description — read before interpreting)",
        "analysis": "Repair Geometry, Pairwise Intersect, Calculate Geometry (NZTM), Summarise Within for river flow, join gauges, compare to coastal erosion sensitivity.",
        "outputs": "Exposure map, area-by-region chart, river flow map, methods note on model scope.",
        "datasets": ["niwa_esl_1pc", "niwa_flood_stats", "niwa_flow_gauges", "niwa_coast_erosion", "niwa_coastline", "regc"],
        "limitations": [
            "Modelled hazard extent, not observed flooding and not damage; exposure is not impact.",
            "Region polygons include sea out to 12 nm, so percentages must use land area, not total polygon area.",
            "The national flood layers are huge (hundreds of MB to GB): choose a region, or the size limit will pause the job for approval.",
            "No licence statement was found for some NIWA layers — confirm reuse terms before publishing.",
        ],
        "needs": [
            ("Sea-level flood extent polygons", [("niwa_esl_1pc", "geometry")]),
            ("River line geometry + 100-year flow field", [("niwa_flood_stats", "geometry"), ("niwa_flood_stats", r"100y")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
            ("Region land area (for percentages)", [("regc", r"LAND.*AREA")]),
            ("Compatible CRS for area maths", [("niwa_esl_1pc", "crs"), ("regc", "crs")]),
        ],
    },
    {
        "id": "nz-galaxiid-records", "icon": "🐟",
        "title": "Freshwater Fish & Rivers",
        "tagline": "Whitebait, eels and the rivers they live in.",
        "theme": "freshwater", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Map where native fish (galaxiids, inanga, longfin eels) have been recorded, compare them with introduced trout and DOC's fish distribution layer, and relate it all to river flow gauges.",
        "question": "Where are native freshwater fish records concentrated, how do they overlap with introduced trout, and how has recording effort changed over decades?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Historical records; years are whatever the data contain (reported in the quality summary)",
        "analysis": "Filter by coordinate uncertainty (documented), Summarise Within by region and decade, hex-bin density, compare native vs introduced.",
        "outputs": "Occurrence map, records-per-decade chart, native vs introduced comparison, bias/limitations section.",
        "datasets": ["gbif_galaxiidae", "gbif_longfin", "gbif_inanga", "gbif_trout", "doc_fish", "niwa_flow_gauges", "regc"],
        "limitations": [
            "Occurrence records are not movement tracks, migration, abundance or habitat suitability.",
            "Record density reflects survey effort and observer access as well as fish distribution.",
            "Coordinate uncertainty varies widely; records have per-record licences (some non-commercial).",
        ],
        "needs": [
            ("Record locations", [("gbif_galaxiidae", "geometry"), ("gbif_longfin", "geometry"), ("gbif_inanga", "geometry"), ("gbif_trout", "geometry")]),
            ("Record year", [("gbif_galaxiidae", r"^year$")]),
            ("Coordinate uncertainty", [("gbif_galaxiidae", r"coordinateUncertaintyInMeters")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-native-birds", "icon": "🦜",
        "title": "Birds of Aotearoa",
        "tagline": "Kiwi, kea, kākāpō and hoiho — and the land that protects them.",
        "theme": "wildlife", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Map sightings of four iconic native birds and see how many fall inside public conservation land.",
        "question": "Where are sightings of kiwi, kea, kākāpō and yellow-eyed penguins concentrated, and how much of that is inside public conservation land?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Historical records; years are whatever the data contain",
        "analysis": "Spatial Join to conservation land, Summarise Within by region, compare species, hex-bin density.",
        "outputs": "Species maps, inside/outside conservation land chart, region comparison, StoryMap.",
        "datasets": ["gbif_kiwi", "gbif_kakapo", "gbif_kea", "gbif_penguin", "doc_land", "regc"],
        "limitations": [
            "Sightings depend on where people look; rare or secretive birds are under-recorded.",
            "Some locations of threatened species may be deliberately generalised by data publishers.",
            "Records are not population counts or abundance.",
        ],
        "needs": [
            ("Sighting locations", [("gbif_kiwi", "geometry"), ("gbif_kakapo", "geometry"), ("gbif_kea", "geometry"), ("gbif_penguin", "geometry")]),
            ("Conservation land polygons", [("doc_land", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-outdoor-recreation", "icon": "🥾",
        "title": "Getting Out There: Huts, Tracks & Conservation Land",
        "tagline": "Where New Zealand keeps its wild places open to visit.",
        "theme": "outdoors", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "static", "data_type": "vector",
        "summary": "Map DOC's huts, campsites, tracks and walking experiences against public conservation land and hunting areas to see which regions offer the most access to the outdoors.",
        "question": "Which regions have the most huts, campsites and tracks per area of conservation land, and where are the gaps?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Current DOC datasets (publisher update dates are in the quality report)",
        "analysis": "Summarise Within by region, track length per region, density of huts per km² of conservation land, access gaps.",
        "outputs": "Facilities map, per-region comparison chart, short StoryMap or trip-planner view.",
        "datasets": ["doc_land", "doc_huts", "doc_campsites", "doc_tracks", "doc_walks", "doc_hunting", "regc"],
        "limitations": [
            "Facility records are as published by DOC; closures and condition are not part of these layers.",
            "Counts show provision, not visitor numbers or quality.",
            "Track and land layers are large; choose a region for a lighter download.",
        ],
        "needs": [
            ("Hut and campsite locations", [("doc_huts", "geometry"), ("doc_campsites", "geometry")]),
            ("Track lines", [("doc_tracks", "geometry")]),
            ("Conservation land polygons", [("doc_land", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-marine-life", "icon": "🐬",
        "title": "Life in Our Seas",
        "tagline": "Marine reserves, dolphins and sea lions.",
        "theme": "marine", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Compare protected marine areas with sightings of Hector's dolphins and New Zealand sea lions, inside the Exclusive Economic Zone.",
        "question": "How much of where Hector's dolphins and sea lions are seen lies inside marine reserves or mammal sanctuaries?",
        "study_area": "New Zealand's marine area (or one regional council area)",
        "time_period": "Historical sightings; protection layers are current",
        "analysis": "Spatial Join sightings to protection areas, count by protection type, density maps, EEZ context.",
        "outputs": "Protection overlay map, inside/outside comparison chart, limitations note.",
        "datasets": ["doc_marine_reserves", "doc_mammal_sanct", "doc_marine_prot", "eez", "gbif_hectors", "gbif_sealion", "regc"],
        "limitations": [
            "Sightings follow where observers go (coasts, boat routes), not where animals actually are.",
            "Protection boundaries are legal areas, not proof of effective protection.",
            "Regional council boundaries stop at 12 nm, so offshore records fall outside every region.",
        ],
        "needs": [
            ("Marine protection polygons", [("doc_marine_reserves", "geometry"), ("doc_mammal_sanct", "geometry"), ("doc_marine_prot", "geometry")]),
            ("Dolphin and sea lion sightings", [("gbif_hectors", "geometry"), ("gbif_sealion", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
]

PROJECTS.extend([
    {
        "id": "nz-volcano-watch", "icon": "🗻",
        "title": "Living Beside a Volcano",
        "tagline": "Alert levels, earthquakes and the towns in the shadow.",
        "theme": "hazards", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "recent", "data_type": "vector",
        "summary": "See which volcanoes GeoNet is watching right now, how much earthquake activity surrounds them, and which towns, cities and conservation land lie close by.",
        "question": "Which volcanoes currently carry elevated alert levels, and how many people, towns and protected areas lie within reach of them?",
        "study_area": "All of New Zealand (or one region)",
        "time_period": "Today's volcano alert levels, plus ten years of M5+ earthquakes and GeoNet's recent felt-quake window",
        "analysis": "Buffer volcanoes (10 / 30 km), Summarise Within for earthquakes and urban areas, intersect with conservation land.",
        "outputs": "Volcano map with buffers, nearby-urban-area table, alert-level summary, short StoryMap.",
        "datasets": ["geonet_volcano", "geonet_fdsn", "geonet_quake_api", "nz_plates", "urban_rural", "doc_land", "regc"],
        "limitations": [
            "Alert levels describe current unrest, not eruption forecasts; they are a snapshot of today.",
            "Buffer distances are your analytical choice, not official hazard zones.",
            "Urban area boundaries show where people live, not how many or how exposed they are.",
        ],
        "needs": [
            ("Volcano locations and alert level", [("geonet_volcano", "geometry"), ("geonet_volcano", r"^level$")]),
            ("Earthquake locations", [("geonet_fdsn", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-pests-predators", "icon": "🐀",
        "title": "Pests & Predators",
        "tagline": "Where introduced animals have been recorded.",
        "theme": "wildlife", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Map recorded sightings of stoats, rats and red deer, compare them with DOC hunting areas and conservation land, and see which regions carry the most records.",
        "question": "Where have introduced predators and game animals been recorded, and how much of that lies inside conservation land?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Historical records; years are whatever the data contain",
        "analysis": "Spatial Join to conservation land, Summarise Within by region and species, hex-bin density, compare predators vs game animals.",
        "outputs": "Species maps, inside/outside conservation land chart, regional comparison table, StoryMap.",
        "datasets": ["gbif_stoat", "gbif_shiprat", "gbif_norway_rat", "gbif_red_deer", "doc_hunting", "doc_land", "regc"],
        "limitations": [
            "Records show where people noticed or reported an animal — not how many there are or where they are absent.",
            "Pests are under-recorded in remote areas and over-recorded near towns and tracks.",
            "Possums are left out: GBIF holds over 500,000 NZ records, too many for this tool's paging limit.",
        ],
        "needs": [
            ("Sighting locations", [("gbif_stoat", "geometry"), ("gbif_shiprat", "geometry"), ("gbif_red_deer", "geometry")]),
            ("Conservation land polygons", [("doc_land", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-seabirds", "icon": "🐧",
        "title": "Seabirds of the Southern Ocean",
        "tagline": "Penguins, gannets and the coasts they return to.",
        "theme": "marine", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Compare sightings of yellow-eyed penguins, little penguins and Australasian gannets with marine protection areas, the coastline and the Exclusive Economic Zone.",
        "question": "Where are these seabirds recorded around the New Zealand coast, and how much of that falls inside marine protection?",
        "study_area": "New Zealand coast (or one regional council area)",
        "time_period": "Historical records; protection layers are current",
        "analysis": "Spatial Join to protection areas, distance to coast, Summarise Within by region and decade, density maps.",
        "outputs": "Species maps, inside/outside protection chart, records-per-decade chart, StoryMap.",
        "datasets": ["gbif_penguin", "gbif_little_penguin", "gbif_gannet", "doc_marine_prot", "eez", "niwa_coastline", "regc"],
        "limitations": [
            "Sightings cluster where people can easily see birds (colonies, beaches), not where birds forage at sea.",
            "Regional council boundaries stop at 12 nm, so offshore records fall outside every region.",
            "Albatrosses are left out: their GBIF record count is above this tool's paging limit.",
        ],
        "needs": [
            ("Sighting locations", [("gbif_penguin", "geometry"), ("gbif_little_penguin", "geometry"), ("gbif_gannet", "geometry")]),
            ("Marine protection polygons", [("doc_marine_prot", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-native-forests", "icon": "🌳",
        "title": "Native Forests & Giant Trees",
        "tagline": "Kauri, pōhutukawa and tōtara across the landscape.",
        "theme": "wildlife", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "historical", "data_type": "vector",
        "summary": "Map recorded kauri, pōhutukawa and tōtara, then see how they relate to DOC's ecological districts and public conservation land.",
        "question": "Where are kauri, pōhutukawa and tōtara recorded, and how do those records sit within ecological districts and conservation land?",
        "study_area": "New Zealand (or one regional council area)",
        "time_period": "Historical records; years are whatever the data contain",
        "analysis": "Summarise Within by ecological district and region, inside/outside conservation land, compare the three species.",
        "outputs": "Species map, ecological-district count table, conservation-land comparison, StoryMap.",
        "datasets": ["gbif_kauri", "gbif_pohutukawa", "gbif_totara", "doc_eco_districts", "doc_land", "regc"],
        "limitations": [
            "Planted trees (gardens, street trees) are mixed in with wild ones; GBIF does not always say which is which.",
            "Records are not forest cover or tree counts.",
            "Ecological district boundaries are a classification, not a measure of forest health.",
        ],
        "needs": [
            ("Tree record locations", [("gbif_kauri", "geometry"), ("gbif_pohutukawa", "geometry"), ("gbif_totara", "geometry")]),
            ("Ecological district polygons", [("doc_eco_districts", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-coastline", "icon": "🏖️",
        "title": "Our Changing Coastline",
        "tagline": "Erosion, protection and the places people go to the beach.",
        "theme": "hazards", "difficulty": "Intermediate", "workload_h": [10, 14], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "modelled", "data_type": "vector",
        "summary": "Combine NIWA's coastal erosion sensitivity with modelled sea-level flooding, marine protection, DOC campsites and urban areas to see which stretches of coast matter most to people and nature.",
        "question": "Which parts of the New Zealand coast combine high erosion sensitivity, flood exposure and heavy human use?",
        "study_area": "New Zealand coastline (strongly recommended: pick one region — the flood layer is very large)",
        "time_period": "Static modelled layers (read each service description before interpreting)",
        "analysis": "Summarise Within coastal segments, overlay flood extent, count campsites and urban areas near the coast, compare with marine protection.",
        "outputs": "Coastal sensitivity map, region comparison table, hot-spot list, StoryMap.",
        "datasets": ["niwa_coast_erosion", "niwa_coastline", "niwa_esl_1pc", "doc_marine_prot", "doc_campsites", "urban_rural", "regc"],
        "limitations": [
            "Modelled indices describe sensitivity, not actual erosion or damage.",
            "The sea-level flood layer is very large; choose a region or the size limit will pause the job for approval.",
            "Campsite and urban layers show provision and location, not visitor numbers or population.",
        ],
        "needs": [
            ("Coastal erosion sensitivity", [("niwa_coast_erosion", "geometry")]),
            ("Coastline polygons", [("niwa_coastline", "geometry")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
])

PROJECTS.extend([
    {
        "id": "nz-weather-extremes", "icon": "⛈️",
        "title": "Rain, Wind & Heat Across New Zealand",
        "tagline": "How wild has the weather been, place by place?",
        "theme": "weather", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "recent", "data_type": "mixed",
        "summary": "Compare daily rainfall, temperature and wind gusts at 16 regional centres over the time period you choose, see where the rain gauges are, and look at the damage records from the Auckland floods of January 2023.",
        "question": "Which regions had the wettest, windiest and hottest days in the chosen period, and how do the extremes line up with recorded flood impacts?",
        "study_area": "New Zealand's regional centres (or one region)",
        "time_period": "Whatever period you choose (daily values); flood impact records are for January 2023 only",
        "analysis": "Summarise daily values by region (max, mean, days above a threshold), chart extremes through time, overlay flood impact points with rain gauges.",
        "outputs": "Time-series charts, a region comparison table, a rain-gauge map with flood impacts, short StoryMap.",
        "datasets": ["om_rain", "om_temp", "om_wind", "cliflo_rain", "auck_floods", "niwa_flow_gauges", "regc"],
        "limitations": [
            "Rainfall, temperature and wind come from a global weather reanalysis model (nearest grid cell), not from weather-station readings.",
            "Only 16 regional centres are covered, so local microclimates and rural areas are not represented.",
            "The flood-impact records cover one event in Auckland, so they cannot be compared nationally.",
        ],
        "needs": [
            ("Daily rainfall by place", [("om_rain", r"precipitation_sum")]),
            ("Daily temperature by place", [("om_temp", r"temperature_2m_max")]),
            ("Daily wind gusts by place", [("om_wind", r"wind_gusts_10m_max")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-climate-trends", "icon": "🌡️",
        "title": "A Changing Climate? Temperature, Rain & Snow",
        "tagline": "Long records at 16 places show what is shifting.",
        "theme": "climate", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "multi-year", "data_type": "mixed",
        "summary": "Use daily temperature, rainfall, snowfall and sunshine records at 16 regional centres to look for trends across the period you choose (the longer the period, the clearer the picture), and relate them to where people live.",
        "question": "Over the chosen period, how have temperature, rainfall and snowfall changed at New Zealand's regional centres, and do the changes differ between regions?",
        "study_area": "New Zealand's regional centres (or one region)",
        "time_period": "Whatever period you choose; at least 5–10 years is recommended for trends",
        "analysis": "Annual means and totals per centre, trend lines, compare first and last years of the period, map the change by region.",
        "outputs": "Trend charts, change-by-region table, map of change, StoryMap.",
        "datasets": ["om_temp", "om_rain", "om_snow", "om_sun", "cliflo_rain", "urban_rural", "regc"],
        "limitations": [
            "Short periods (a month or a year) show weather, not climate: use 10 years or more before talking about trends.",
            "Reanalysis models can drift over time, so small trends should be checked against station records.",
            "Sixteen centres are not a national average.",
        ],
        "needs": [
            ("Daily temperature by place", [("om_temp", r"temperature_2m_mean")]),
            ("Daily rainfall by place", [("om_rain", r"precipitation_sum")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
    {
        "id": "nz-air-sea", "icon": "🌬️",
        "title": "Air & Sea Conditions Around Our Coast",
        "tagline": "Waves, air quality and the places people live.",
        "theme": "environment", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS StoryMaps"],
        "period_class": "recent", "data_type": "mixed",
        "summary": "Compare wave heights off the coast with fine-particle air quality in the cities over the period you choose, alongside urban areas, the coastline and marine protection.",
        "question": "How do wave conditions and air quality vary around New Zealand's coastal centres, and where do the worst conditions coincide with where people live?",
        "study_area": "New Zealand's coastal centres (or one region)",
        "time_period": "Whatever period you choose; air-quality model data does not go back as far as weather data",
        "analysis": "Summarise daily values by centre and season, rank worst days, relate to urban areas and coast, compare with marine protection areas.",
        "outputs": "Time-series charts, ranking table, coast map, StoryMap.",
        "datasets": ["om_marine", "om_air", "niwa_coastline", "doc_marine_prot", "urban_rural", "eez", "regc"],
        "limitations": [
            "Air quality and wave values are model estimates for the nearest grid cell, not measurements at a monitoring site.",
            "Wave values are for open sea near each centre, not for the sheltered harbour itself.",
            "Air-quality model coverage may start later than your chosen period — the app tells you if so.",
        ],
        "needs": [
            ("Daily wave height by place", [("om_marine", r"wave_height_max")]),
            ("Daily fine-particle air quality by place", [("om_air", r"pm2_5")]),
            ("Region names to summarise by", [("regc", r"NAME$")]),
        ],
    },
])

# Every dataset gets a basic "usable geometry" requirement so the compatibility report covers all of them.
for _p in PROJECTS:
    _seen = {ds for _, reqs in _p["needs"] for ds, _ in reqs}
    for _d in _p["datasets"]:
        if _d not in _seen:
            _p["needs"].append((f"{DATASETS[_d]['name']}: usable geometry", [(_d, "geometry")]))

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

    pid = project.get("base_id", project["id"])  # regional versions use their template's tailored steps
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
    elif pid == "nz-native-birds":
        steps += [
            step(A, "Compare the four species", "Shows each species' footprint.", "gbif_kiwi_nztm, gbif_kakapo_nztm, gbif_kea_nztm, gbif_penguin_nztm",
                 "Merge (or Append) with a species field, then Symbology > Unique Values", "Species field = scientificName", "Combined sightings layer",
                 "Feature count = sum of the four inputs", "Sightings reflect observer effort."),
            step(A, "Sightings inside conservation land", "Answers 'how much is protected?'", "combined sightings; doc_land_nztm",
                 "Analysis Tools > Spatial Join (or Summarize Within)", "Join operation = one-to-one; match option = Within; keep all targets", "Sightings flagged inside / outside",
                 "Inside + outside = total", "Land boundaries are legal areas, not habitat quality."),
            step(A, "Count by region", "Regional comparison.", "combined sightings; regc_nztm", "Analysis Tools > Summarize Within",
                 "Group by species", "region_species_counts", "Totals reconcile with calc_region tagging in the quality report", "Counts are not abundance."),
        ]
    elif pid == "nz-outdoor-recreation":
        steps += [
            step(A, "Count huts, campsites and walks per region", "Compares provision of facilities.", "doc_huts_nztm, doc_campsites_nztm, doc_walks_nztm; regc_nztm",
                 "Analysis Tools > Summarize Within", "Run once per point layer; statistic = count", "Per-region facility counts", "Totals reconcile with record counts",
                 "Closures and condition are not in the data."),
            step(A, "Total track length per region", "Measures path network by region.", "doc_tracks_nztm; regc_nztm",
                 "Summarize Within with Add Shape Summary = Yes", "Length unit = kilometres", "region_track_km", "Spot-check three regions against DOC's website",
                 "Tracks crossing region borders are split by the tool."),
            step(A, "Facilities per km² of conservation land", "Normalises by how much public land each region has.", "Summaries above; doc_land_nztm",
                 "Summarize Within (land area) then Calculate Field", "Density = facilities / conservation land km²", "access_density", "No division by zero; check regions with little land",
                 "Density is not visitor demand."),
        ]
    elif pid == "nz-marine-life":
        steps += [
            step(A, "Combine protection areas", "One layer showing every protected marine area.", "doc_marine_reserves_nztm, doc_mammal_sanct_nztm, doc_marine_prot_nztm",
                 "Data Management > Merge", "Add a protection_type field before merging", "Merged protection layer", "Feature count = sum of inputs",
                 "Layers may overlap; do not add their areas without Dissolve."),
            step(A, "Sightings inside protection", "Answers 'how much is protected?'", "gbif_hectors_nztm, gbif_sealion_nztm; merged protection layer",
                 "Analysis Tools > Spatial Join", "Match option = Within; one-to-one", "Sightings with protection_type", "Inside + outside = total",
                 "Sightings are where observers are, not where animals are."),
            step(A, "Density maps and EEZ context", "Visualises hot spots against the EEZ outline.", "Sightings; eez",
                 "Spatial Analyst > Kernel Density (or Generate Tessellation hexbins)", "Run per species; search radius = try two values", "Density rasters / hexbins",
                 "Pattern persists with a second radius", "Density depends strongly on radius."),
        ]
    else:  # projects without a bespoke guide: a sound generic workflow built from the project's own datasets
        pts = [d for d in project["datasets"] if d != "regc" and (DATASETS[d]["connector"] in ("gbif", "fdsn", "geonet_quake", "geojson_url"))]
        polys = [d for d in project["datasets"] if d != "regc" and d not in pts]
        steps += [
            step(A, "Count records by region", "Shows where each point dataset is concentrated.",
                 "; ".join(f"{d}_nztm" for d in pts) + "; regc_nztm" if pts else "regc_nztm and your layers",
                 "Analysis Tools > Summarize Within", "Input Polygons = regc_nztm; run once per point layer; statistic = count; group by species/type if present",
                 "One summary table per layer", "Totals reconcile with the record counts in metadata/dataset_catalogue.csv",
                 "Records show observation effort, not abundance; points beyond 12 nm fall outside every region."),
            step(A, "Overlay with the area layers", "Relates the points to the polygon/line layers in this project.",
                 "; ".join(f"{d}_nztm" for d in polys) or "your polygon layers", "Analysis Tools > Spatial Join (Match option = Within / Intersect)",
                 "Join one-to-one; keep all target features; note which layer is the target", "Points flagged inside / outside each area",
                 "Inside + outside = total points", "Boundaries are legal or modelled areas, not proof of habitat or risk."),
            step(A, "Compare and summarise", "Turns the overlays into numbers you can chart.", "Outputs of the previous two steps",
                 "Summary Statistics, then Chart (bar / histogram)", "Choose one clear comparison per question in the case study outline", "Tables and charts for the StoryMap",
                 "Every number traces to a table you made", "Use neutral wording: association, not cause."),
        ]
    steps += [
        step(V, "Reconcile counts and sanity-check", "Make sure outputs match what was downloaded.",
             "Your output tables; metadata/quality_report.md", "Manual + Statistics",
             "Compare totals with dataset_catalogue.csv 'records' and quality_report 'untagged/outside' counts", "A short validation note in your methods",
             "Every discrepancy explained", "Document any records you excluded (never delete originals)."),
        step(V, "Check against the source", "Catch systematic problems.", "3–5 records or features",
             "Source website / service viewer", "Pick samples across the study area", "Spot-check notes", "Values match the publisher's view",
             "Publisher viewers may use newer data than your snapshot (see retrieval dates)."),
        step("Final map (ArcGIS Online)", "Publish your result layers to ArcGIS Online",
             "Put your finished layers online so a web map can use them.",
             "Your finished result layers from ArcGIS Pro (not the raw downloads); maps/arcgis_online_publish.md lists this package's files and sizes",
             "ArcGIS Pro > Share > Web Layer > Publish Web Layer (Feature layer, hosted) — or ArcGIS Online > Content > New item > Your device (zipped shapefile or GeoJSON)",
             "Name layers clearly; Summary + Tags + Terms of use filled in; Folder = project name; keep each file under your org's upload limit (Map Viewer 'Add layer from file' is limited to about 10 MB, so use Content > New item for bigger files)",
             "Hosted feature layers in your ArcGIS Online Content", "Open each layer's item page: feature count matches the layer in Pro; the layer draws in the Map Viewer",
             "Needs an ArcGIS Online account. Publishing hosted layers can use credits; layers must be in WGS84/Web Mercator for web display (Pro reprojects on publish)."),
        step("Final map (ArcGIS Online)", "Build and style the final web map",
             "One clear map that answers the research question.",
             "Hosted layers from the previous step", "ArcGIS Online > Map Viewer > Add layers; Styles, Pop-ups, Filter, Labels, Basemap",
             "Basemap = Light Gray Canvas or Imagery Hybrid; style the layer that carries the answer first; set scale ranges so layers don't crowd; pop-ups show 3-5 fields only; "
             "never stack two layers that cover the same features at the same scale",
             "A saved web map with a legend and pop-ups", "Zoom to each region of interest: no layers overlap or hide each other; legend entries are readable at the final map size",
             "A map shows association, not cause; state the data dates in the map description."),
        step("Final map (ArcGIS Online)", "Save, share and embed the map",
             "Make the final map viewable by your audience.",
             "The saved web map", "Map Viewer > Save and open > Save as; Share (Everyone/public or your organisation); then StoryMaps > Add map",
             "Map title + summary + tags; share the map AND each layer it uses at the same level (a shared map with private layers appears blank to others)",
             "Shared web map link and an embeddable map", "Open the link in a private/incognito window: all layers draw and pop-ups work",
             "Public sharing exposes the data publicly: check each dataset's licence in metadata/dataset_catalogue.csv first."),
        step("Storytelling", "Build the StoryMap from the outline", "Communicate only what you have actually produced.",
             "storymap/outline.md; your exported maps/charts", "ArcGIS StoryMaps (storymaps.arcgis.com) > New Story",
             "Follow the section order; add alt text and credits (use the planning tab)", "Draft story", "Every number in the story traces to a table you made",
             "Needs an ArcGIS Online account (student/organisational) to create and publish."),
    ]
    return steps


def _kind(label):
    l = label.lower()
    if "map" in l or "symbol" in l or l.startswith("gap"):
        return "map"
    if "chart" in l or "histogram" in l:
        return "chart"
    if "table" in l or "ranking" in l or "list" in l:
        return "table"
    return "text"


# Which kinds of layers each project's illustrative maps show (used only to draw the mock-up).
MAP_STYLES = {
    "nz-quake-decade": ["points", "lines"], "nz-coastal-esl-exposure": ["polygons", "lines"], "nz-galaxiid-records": ["points", "lines"],
    "nz-native-birds": ["points", "polygons"], "nz-outdoor-recreation": ["lines", "points"], "nz-marine-life": ["polygons", "points"],
    "nz-volcano-watch": ["points", "polygons"], "nz-pests-predators": ["points", "polygons"], "nz-seabirds": ["points", "polygons"],
    "nz-native-forests": ["points", "polygons"], "nz-coastline": ["lines", "polygons"], "nz-weather-extremes": ["choropleth", "points"],
    "nz-climate-trends": ["choropleth", "points"], "nz-air-sea": ["points", "choropleth"],
}


def _chart_kind(label):
    l = label.lower()
    if "through time" in l or "time" in l and "month" not in l:
        return "line"
    if "month" in l or "decade" in l or "year" in l:
        return "column"
    if "histogram" in l or "depth" in l:
        return "histogram"
    if "species" in l or "by region" in l:
        return "stacked"
    return "bar"


def _table_cols(label):
    l = label.lower()
    if "dataset" in l:
        return ["Dataset", "Publisher", "Records", "Retrieved"]
    if "gauge" in l or "near" in l:
        return ["Place", "Nearest gauge", "Distance (km)", "Notes"]
    if "per species" in l or "species" in l:
        return ["Species", "Records", "Regions", "Share inside protection"]
    if "month" in l or "season" in l:
        return ["Month", "Count", "Largest value", "Notes"]
    if "rank" in l:
        return ["Rank", "Place", "Value", "Notes"]
    return ["Region", "Count", "Largest / mean", "Share of total"]


def _sentence(s):
    s = (s or "").strip()
    return s[:1].lower() + s[1:] if s else s


def storymap_sections(project, ctx=None):
    """Draft case study in the layout of an ArcGIS StoryMap: cover, introduction, main question, approach (timeline),
    data table, three linked question sections (sidecars / swipe), limitations, conclusion, sources.

    Every map / chart / table is a labelled ILLUSTRATION of what it could look like (never real results). Text states what the
    project did and plans to do; findings are left as prompts for the student to complete from their own analysis."""
    ctx = ctx or {}
    cs = project["case_study"]
    qs = cs["questions"]
    ids = [d for d in project["datasets"] if d != "regc"]
    names = [DATASETS[d]["name"] for d in ids]
    pubs = sorted({DATASETS[d]["publisher"].split(" (")[0].split(" – ")[0] for d in ids})
    per, region = ctx.get("period"), ctx.get("region")
    area = region or "all of New Zealand"
    period_txt = per["text"] if per else "the time period we choose"
    styles = MAP_STYLES.get(project["id"], ["points", "polygons"])
    steps = [s for s in guide_steps(project, {}) if s["phase"] == "Analysis"]
    tools = [s["tool"].split(">")[-1].split(",")[0].strip() for s in steps[:4]]
    how_txt = ("In ArcGIS Pro we " + ", then ".join(f"{_sentence(s['title'])} ({t})" for s, t in zip(steps[:4], tools)) + ".") if steps else "We follow the analysis guide step by step in ArcGIS Pro."
    rows = ctx.get("rows") or []
    real_rows = [[r["name"], r["publisher"], f"{r['records']:,}" if isinstance(r.get("records"), int) else str(r.get("records") or "—"),
                  (r.get("retrieved_at") or "—")[:10]] for r in rows]
    table_rows = real_rows or [[n, DATASETS[d]["publisher"], "—", "—"] for d, n in zip(ids, names)]

    def vis(label, i=0):
        k = _kind(label)
        if k == "map":
            return {"kind": "map", "label": label, "mock": {"style": styles[i % len(styles)], "note": "Illustration of how this map could look — not real data."}}
        if k == "chart":
            return {"kind": "chart", "label": label, "mock": {"chart": _chart_kind(label), "note": "Illustration of the chart shape — your own numbers go here."}}
        if k == "table":
            return {"kind": "table", "label": label, "mock": {"columns": _table_cols(label), "rows": 4, "note": "Suggested columns — fill with your own results."}}
        return None

    secs = [
        {"id": "cover", "title": "Cover", "layout": "cover", "text": "", "suggest": "Full-width cover photo with the headline over it (StoryMaps 'Cover').",
         "parts": [{"label": "Headline", "text": cs["headline"]}, {"label": "Subtitle", "text": project["title"]}], "visuals": []},
        {"id": "intro", "title": "Introduction", "layout": "immersive", "text": "", "suggest": "Short hook (2–3 sentences). In StoryMaps use an Immersive block or a Sidecar with the photo on one side.",
         "parts": [{"label": "Introduction", "text": f"{cs['dek']} In this case study we explore {project.get('base_title', project['title']).lower()} for {area}, working with {len(ids)} real, openly published datasets from {', '.join(pubs[:4])}{' and others' if len(pubs) > 4 else ''}, over {period_txt}."},
                   {"label": "Why it matters", "text": project["purpose"]}],
         "visuals": [{"kind": "image", "label": "Photo", "mock": {}}]},
        {"id": "question", "title": "Our main question", "layout": "callout", "text": "", "suggest": "A big quote or text block so the question is the first thing readers remember.",
         "parts": [{"label": "Main research question", "text": project["question"]},
                   {"label": "How the story is organised", "text": f"We answer it in three linked steps: {_sentence(qs[0]['title'])} Then, {_sentence(qs[1]['title'])} Finally, {_sentence(qs[2]['title'])}"}],
         "visuals": []},
        {"id": "approach", "title": "What we did, what we plan to do, and how", "layout": "timeline", "text": "", "suggest": "A StoryMaps Timeline block works well for the workflow.",
         "parts": [{"label": "What we did", "text": f"We chose this project because {_sentence(project['summary'])} We then checked that every dataset could be reached and downloaded ({'; '.join(names[:4])}{'…' if len(names) > 4 else ''}), filtered them to {area} and {period_txt}, and ran basic checks for missing values and invalid shapes."},
                   {"label": "What we plan to do", "text": f"Next we will {_sentence(project['analysis'])}"},
                   {"label": "How we do it", "text": how_txt}],
         "visuals": [{"kind": "timeline", "label": "Workflow timeline", "mock": {"steps": ["Choose project", "Source & check data", "Prepare in ArcGIS Pro", "Analyse", "Map & chart", "Write the story"],
                                                                                   "done": 2, "note": "First two steps are done by this tool; the rest are yours."}}]},
        {"id": "data_methods", "title": "The data", "layout": "table", "text": "", "suggest": "A table block with one row per dataset, plus a short line on the time period and area.",
         "parts": [{"label": "Datasets", "text": f"We used {len(ids)} datasets. The table lists each one with its publisher, how many records we retrieved and when."},
                   {"label": "Time period and area", "text": f"Time period: {period_txt}. Study area: {area}. {project['time_note']}"}],
         "visuals": [{"kind": "table", "label": "Dataset table", "mock": {"columns": ["Dataset", "Publisher", "Records", "Retrieved"], "rows": 4, "data": table_rows,
                                                                       "real": bool(real_rows), "note": "Real dataset information" if real_rows else "Fills in with real numbers after the download."}}]},
    ]
    layouts = ["sidecar-right", "sidecar-stack", "swipe" if len(cs.get("overlay", [])) >= 3 else "sidecar-down"]
    for i, qq in enumerate(qs):
        visuals = [v for v in (vis(s, i + j) for j, s in enumerate(qq["show"])) if v]
        if i == 0 and cs.get("time_dataset"):
            visuals.insert(0, {"kind": "timeseries", "label": "Time-series map (time slider)", "mock": {"style": styles[0], "note": "Illustration — in ArcGIS Online this uses the Time slider on a map layer."}})
        secs.append({"id": f"q{i + 1}", "title": f"{qq['label']}: {qq['title']}", "layout": layouts[i], "text": "",
                     "suggest": {"sidecar-right": "StoryMaps Sidecar, scrolling to the right: map stays fixed while the narrative scrolls.",
                                 "sidecar-stack": "StoryMaps Sidecar with several maps (or a map and a chart) stacked in the same panel.",
                                 "swipe": "StoryMaps Swipe block to compare two layers side by side.",
                                 "sidecar-down": "StoryMaps Sidecar, scrolling down: panels slide over the map."}[layouts[i]],
                     "parts": [{"label": "The question", "text": qq["text"]},
                               {"label": "What we did", "text": f"We gathered the datasets this step needs ({', '.join(names[:3])}{'…' if len(names) > 3 else ''}), cut them to {area} and {period_txt}, and checked that the fields we need are there."},
                               {"label": "What we plan to do", "text": f"We will {_sentence(qq['how'])}"},
                               {"label": "What we found", "text": "[Write 2–3 sentences with your own numbers once the analysis is finished — name the top regions or the main pattern, and say how sure you are.]"}],
                     "visuals": visuals})
    secs += [
        {"id": "limitations", "title": "Limitations", "layout": "text", "text": "", "suggest": "A plain bullet list is clearest; then one sentence on how each limit affects your conclusion.",
         "parts": [{"label": "What the data cannot tell us", "text": "\n".join("- " + l for l in project["limitations"])},
                   {"label": "How this affects our conclusions", "text": "[Write 2–3 sentences: which limitation matters most for your answer, and what you did to reduce its effect.]"}], "visuals": []},
        {"id": "conclusion", "title": "Conclusion", "layout": "text", "text": "", "suggest": "Answer the main question first, then the factors, then next steps.",
         "parts": [{"label": "Answer to the main question", "text": f"Our main question was: {project['question']} [Answer it in 2–3 sentences using your own results.]"},
                   {"label": "What the contributing factors added", "text": "[Say what looking at the factors and the follow-up question changed or confirmed.]"},
                   {"label": "What we would do next", "text": "[Name one improvement — for example a longer time period, a finer area, or another dataset.]"}], "visuals": []},
        {"id": "sources", "title": "Sources and credits", "layout": "text", "text": "", "suggest": "Auto-filled from the dataset catalogue; photo credits are listed with each image.",
         "parts": [{"label": "Sources", "text": ""}], "visuals": []},
    ]
    for s in secs:
        s["text"] = "\n\n".join(p["text"] for p in s["parts"] if p["text"])
        s["placeholders"] = [{"kind": v["kind"], "label": v["label"]} for v in s["visuals"] if v["kind"] in ("map", "chart", "table", "timeseries")]
    return secs


# Case-study outlines (3 questions + photos) are kept in their own module.
from .casestudies import CASE_STUDIES  # noqa: E402
for _p in PROJECTS:
    _p["case_study"] = CASE_STUDIES[_p["id"]]


from .purposes import PURPOSES, TIME_NOTES  # noqa: E402
for _p in PROJECTS:
    _p["purpose"] = PURPOSES[_p["id"]]
    _p["time_note"] = TIME_NOTES[_p["id"]]


# The original templates (a Refresh builds regional versions of these; see variants.py).
BASES = list(PROJECTS)
BASE_BY_ID = {p["id"]: p for p in BASES}
