"""Refresh all = a brand-new set of projects, built from LIVE sources every time.

* Species projects: GBIF's list of New Zealand species that have mapped records (hundreds to choose from); a species is
  never offered twice.
* Weather, hazard and outdoors projects: a real dataset x a region x a question style, never repeated.
* Discovered projects: public ArcGIS Online layers found by a live search for a topic in a region.
* Photos: searched on Wikimedia Commons for each project's own topic and place (free licences; credit kept).
* Design: every card gets its own accent colour and layout.

Every project is verified live (with its region applied) before it is shown, and everything already shown is recorded in
state/project_history.json so a later refresh never brings it back. Nothing is invented: names, counts, photos and
licences all come from the services."""
import hashlib
import html
import json
import os
import random
import re
import threading
import time

from . import catalog, net

COMMONS = "https://commons.wikimedia.org/w/api.php"
GBIF = "https://api.gbif.org/v1"
ACCENTS = ["#e0653a", "#2e86de", "#3aa760", "#b8863b", "#17a2b8", "#6c5ce7", "#d6336c", "#2f9e8f", "#c0392b",
           "#8e44ad", "#16a085", "#d35400", "#2c3e50", "#27ae60", "#e67e22", "#0984e3", "#a0522d", "#00897b"]
LAYOUTS = ["photo", "banner", "split"]
QUOTAS = [("species", 5), ("weather", 2), ("hazard", 2), ("outdoors", 1), ("discovered", 2)]
VOLCANIC = ["Northland", "Auckland", "Waikato", "Bay of Plenty", "Manawatū-Whanganui", "Taranaki"]
BAD_PHOTO = re.compile(r"(\bmap\b|distribution|\brange map|logo|diagram|chart|stamp|coin|specimen|herbarium|skull|drawing|illustration|plate \d|svg|graph|flag|coat of arms|"
                       r"banner|poster|portrait|justice|court|cast member|magazine|newspaper|screenshot|signature|cyber-shot|camera|wikimedian|conference|meeting|award)", re.I)
SCENE = r"(landscape|view|scenery|panorama|beach|river|lake|mountain|hill|coast|valley|bay|harbour|forest|farm|range|peak|sound|gorge|plain|island|bush)"
FREE_LIC = re.compile(r"(cc0|public domain|pd|cc by)", re.I)

_pool_cache = {"at": 0, "species": []}
_lock = threading.Lock()


def _slug(s):
    s = s.lower()
    for a, b in (("ā", "a"), ("ē", "e"), ("ī", "i"), ("ō", "o"), ("ū", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48]


def _cap(name):
    """'forest violet' -> 'Forest Violet' (keeps macrons, hyphens and apostrophes)."""
    return " ".join(w[:1].upper() + w[1:] for w in name.split(" "))


def _strip(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


# ------------------------------------------------------------------ photos (Wikimedia Commons)
def commons_photos(queries, n=3, used=None, cancel=None):
    """Up to n real, freely licensed photos. queries: [(search text, regex the photo's title/description MUST match)].
    Each photo keeps its credit + licence; near-duplicates (same description) are skipped."""
    used = used if used is not None else set()
    out, seen_desc = [], set()
    for q in queries:
        q, must = q if isinstance(q, tuple) else (q, None)
        if len(out) >= n:
            break
        try:
            st, js = net.get_json(COMMONS, {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:bitmap",
                                            "gsrnamespace": 6, "gsrlimit": 15, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                                            "iiurlwidth": 960}, cancel=cancel, timeout=30, retries=1)
        except net.NetError:
            continue
        pages = sorted(((js or {}).get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for p in pages:
            if len(out) >= n:
                break
            title = p.get("title", "")
            ii = (p.get("imageinfo") or [{}])[0]
            m = ii.get("extmetadata") or {}
            lic = _strip((m.get("LicenseShortName") or {}).get("value"))
            if title in used or BAD_PHOTO.search(title) or ii.get("mime") not in ("image/jpeg", "image/png"):
                continue
            if (ii.get("width") or 0) < 900 or (ii.get("width") or 0) < (ii.get("height") or 0) * 0.9 or not FREE_LIC.search(lic or ""):
                continue  # landscape-ish, big enough, and a free licence
            thumb = (ii.get("thumburl") or "").split("?")[0]
            if not thumb:
                continue
            w = ii.get("width") or 0  # Wikimedia only serves standard thumbnail widths (… 960, 1280, 1920); originals get rate-limited
            big = thumb.replace("/960px-", "/1920px-") if w >= 1920 else thumb.replace("/960px-", "/1280px-") if w >= 1280 else thumb
            artist = _strip((m.get("Artist") or {}).get("value"))[:80] or "Unknown (see source page)"
            desc = _strip((m.get("ImageDescription") or {}).get("value"))[:140]
            alt = desc or re.sub(r"\.(jpe?g|png)$", "", title.replace("File:", ""), flags=re.I).replace("_", " ")
            if BAD_PHOTO.search(desc) or (must and not re.search(must, f"{title} {desc}", re.I)):
                continue
            key = re.sub(r"[^a-z]", "", alt.lower())[:40]
            if key in seen_desc:
                continue
            seen_desc.add(key)
            used.add(title)
            out.append({"url": big, "thumb": thumb, "alt": alt, "credit": artist, "licence": lic,
                        "page": "https://commons.wikimedia.org/wiki/" + title.replace(" ", "_"), "role": "cover" if not out else "inline"})
    return out


# ------------------------------------------------------------------ species (GBIF)
GROUPS = {
    "bird": {"icon": "🐦", "theme": "wildlife", "context": ["doc_land", "urban_rural"], "noun": "bird", "photo": "bird"},
    "marine_mammal": {"icon": "🐬", "theme": "marine", "context": ["doc_marine_prot", "niwa_coastline"], "noun": "marine mammal", "photo": "sea"},
    "mammal": {"icon": "🦔", "theme": "wildlife", "context": ["doc_land", "doc_hunting"], "noun": "mammal", "photo": "animal"},
    "fish_fresh": {"icon": "🐟", "theme": "freshwater", "context": ["niwa_flow_gauges", "doc_land"], "noun": "freshwater fish", "photo": "river"},
    "fish_sea": {"icon": "🐠", "theme": "marine", "context": ["doc_marine_reserves", "niwa_coastline"], "noun": "sea fish", "photo": "fish"},
    "marine_inv": {"icon": "🦀", "theme": "marine", "context": ["doc_marine_prot", "niwa_coastline"], "noun": "sea creature", "photo": "shore"},
    "seaweed": {"icon": "🌊", "theme": "marine", "context": ["doc_marine_prot", "niwa_coastline"], "noun": "seaweed", "photo": "shore"},
    "plant": {"icon": "🌿", "theme": "environment", "context": ["doc_eco_districts", "doc_land"], "noun": "plant", "photo": "plant"},
    "insect": {"icon": "🦋", "theme": "wildlife", "context": ["doc_land", "urban_rural"], "noun": "insect", "photo": "insect"},
    "reptile": {"icon": "🦎", "theme": "wildlife", "context": ["doc_land", "doc_eco_districts"], "noun": "reptile", "photo": "lizard"},
    "fungus": {"icon": "🍄", "theme": "environment", "context": ["doc_eco_districts", "doc_land"], "noun": "fungus", "photo": "forest"},
    "other": {"icon": "🔎", "theme": "wildlife", "context": ["doc_land", "urban_rural"], "noun": "species", "photo": "nature"},
}
FRESH_FAMILIES = {"Galaxiidae", "Anguillidae", "Salmonidae", "Eleotridae", "Retropinnidae", "Geotriidae", "Cyprinidae", "Percidae", "Pinguipedidae_x"}
MARINE_MAMMAL = {"Cetacea", "Otariidae", "Phocidae", "Delphinidae"}
MARINE_INV_CLASSES = {"Malacostraca", "Echinoidea", "Asteroidea", "Cephalopoda", "Anthozoa", "Polychaeta", "Bivalvia", "Ascidiacea"}


def species_pool(cancel=None):
    """NZ species ranked by number of mapped records (live from GBIF, cached for 6 h)."""
    with _lock:
        if _pool_cache["species"] and time.time() - _pool_cache["at"] < 6 * 3600:
            return list(_pool_cache["species"])
    st, js = net.get_json(f"{GBIF}/occurrence/search", {"country": "NZ", "hasCoordinate": "true", "occurrenceStatus": "PRESENT", "limit": 0,
                                                         "facet": "speciesKey", "facetLimit": 1000, "speciesKey.facetLimit": 1000},
                          cancel=cancel, timeout=60, retries=2)
    counts = [(int(c["name"]), c["count"]) for c in ((js or {}).get("facets") or [{}])[0].get("counts", [])]
    with _lock:
        _pool_cache.update(at=time.time(), species=counts)
    return counts


def species_info(key, cancel=None):
    st, sp = net.get_json(f"{GBIF}/species/{key}", cancel=cancel, timeout=30, retries=1)
    if not sp or sp.get("rank") != "SPECIES" or not sp.get("canonicalName"):
        return None
    common = None
    try:
        st, v = net.get_json(f"{GBIF}/species/{key}/vernacularNames", {"limit": 60}, cancel=cancel, timeout=30, retries=1)
        names = [x for x in (v or {}).get("results", []) if x.get("vernacularName")]
        mri = next((x["vernacularName"] for x in names if x.get("language") == "mri"), None)
        eng = [x["vernacularName"] for x in names if x.get("language") == "eng"]
        nz = [x["vernacularName"] for x in names if x.get("language") == "eng" and "zealand" in (x.get("source") or "").lower()]
        common = (nz or eng or [None])[0]
        if mri and common and mri.lower() != common.lower():
            common = f"{mri} / {common}"
        elif mri and not common:
            common = mri
    except net.NetError:
        pass
    if not common and sp.get("vernacularName"):
        common = sp["vernacularName"]
    if common:
        common = " / ".join(_cap(x.split(",")[0].split(";")[0].strip()) for x in common.split(" / ") if x.strip())
    cls, order, fam, kingdom = sp.get("class") or "", sp.get("order") or "", sp.get("family") or "", sp.get("kingdom") or ""
    if cls == "Aves":
        g = "bird"
    elif cls == "Mammalia":
        g = "marine_mammal" if order in MARINE_MAMMAL or fam in MARINE_MAMMAL else "mammal"
    elif cls in ("Actinopterygii", "Actinopteri", "Elasmobranchii", "Teleostei", "Petromyzonti", "Chondrichthyes") or (
            sp.get("phylum") == "Chordata" and not cls and (order.endswith("formes") or fam.endswith("idae"))):
        g = "fish_fresh" if fam in FRESH_FAMILIES else "fish_sea"
    elif cls in MARINE_INV_CLASSES:
        g = "marine_inv"
    elif kingdom == "Chromista" or cls in ("Phaeophyceae", "Florideophyceae", "Ulvophyceae"):
        g = "seaweed"
    elif kingdom == "Plantae":
        g = "plant"
    elif cls == "Insecta":
        g = "insect"
    elif cls in ("Squamata", "Reptilia", "Lepidosauria", "Amphibia") or order in ("Squamata", "Rhynchocephalia", "Anura"):
        g = "reptile"
    elif kingdom == "Fungi":
        g = "fungus"
    else:
        g = "other"
    return {"key": key, "canonical": sp["canonicalName"], "common": common, "group": g, "family": fam, "class": cls}


def _q(label, title, text, how, show):
    return {"label": label, "title": title, "text": text, "how": how, "show": show}


def _species_project(info, region, rng):
    g = GROUPS[info["group"]]
    name = info["common"] or info["canonical"]
    nice = f"{name} (<i>{info['canonical']}</i>)" if info["common"] else info["canonical"]
    nice = re.sub(r"</?i>", "", nice)
    ds = f"x_gbif_{info['key']}"
    spec = {"id": ds, "role": "essential", "connector": "gbif", "taxon_name": info["canonical"], "taxon_rank": "SPECIES",
            "name": f"GBIF records: {name}", "publisher": "GBIF and contributing publishers", "landing_url": f"https://www.gbif.org/species/{info['key']}",
            "licence_note": "Per-record licences (CC0 / CC BY / CC BY-NC) — see each record"}
    ctx = [c for c in g["context"] if c in catalog.DATASETS]
    ctx_names = [catalog.DATASETS[c]["name"] for c in ctx]
    style = rng.choice(["protected", "seasons", "hotspots"])
    titles = {"protected": [f"Safe Ground? The {name} in {region}", f"Where the {name} Lives in {region}", f"{name}: Protected in {region}?"],
              "seasons": [f"A Year with the {name} in {region}", f"When and Where: {name} in {region}", f"The {name}'s Calendar — {region}"],
              "hotspots": [f"{name} Hotspots of {region}", f"On the Trail of the {name} — {region}", f"Mapping the {name} across {region}"]}[style]
    title = rng.choice(titles)
    if style == "protected":
        question = f"Where in {region} has the {name} been recorded, and how much of that lies inside {ctx_names[0].lower()}?"
        qs = [_q("Main question", f"Where is the {name} recorded in {region}?",
                 f"Map every georeferenced record of the {name} in {region} and count them by area. Are the records clustered or spread out?",
                 "Summarise Within by region/district → hexbin density.", ["Map 1: records as points", "Table: records per area", "Chart: ranked bar chart"]),
              _q("Contributing factors", f"How much of it is on {ctx_names[0].lower()}?",
                 f"Overlay the records with {ctx_names[0].lower()}{' and ' + ctx_names[1].lower() if len(ctx_names) > 1 else ''}. What share falls inside, and is that because the {g['noun']} prefers those places or because people look there?",
                 f"Spatial Join (Within) with {ctx[0]}; compare inside vs outside counts.", ["Map 2: records + overlay layer", "Table: inside vs outside"]),
              _q("Follow-up question", "Has recording changed over the decades?",
                 "Group the records by decade. Do more recent decades have far more records — and what does that say about observer effort rather than the species?",
                 "Calculate Field (decade = year // 10 * 10) → Summary Statistics.", ["Chart: records per decade"])]
    elif style == "seasons":
        question = f"In which months is the {name} recorded most often in {region}, and does the pattern differ between places?"
        qs = [_q("Main question", "Which months have the most records?",
                 f"Use each record's month to build a calendar of {name} records in {region}. Is there a clear season?",
                 "Summary Statistics by month → chart.", ["Chart: records per month", "Map 1: records coloured by season"]),
              _q("Contributing factors", "Does the season differ from place to place?",
                 f"Compare the monthly pattern inside and outside {ctx_names[0].lower()}, or between districts of {region}.",
                 f"Spatial Join with {ctx[0]} → Summary Statistics by month and inside/outside.", ["Table: month × area", "Map 2: two seasons side by side"]),
              _q("Follow-up question", "Is the season shifting over time?",
                 "Compare the monthly pattern of older records with the last ten years. Be careful: recording habits change too.",
                 "Select by year → repeat the monthly summary.", ["Chart: two lines, early vs recent"])]
    else:
        question = f"Where are the hotspots of {name} records in {region}, and what do those places have in common?"
        qs = [_q("Main question", "Where are the hotspots?",
                 f"Turn the {name} records into a hexbin map of {region}. Which cells stand out?",
                 "Generate Tessellation (hexagons, 5 km) → Summarize Within.", ["Map 1: hexbin density", "Table: top 10 cells"]),
              _q("Contributing factors", "What is in the hotspots?",
                 f"Compare the hotspot cells with {', '.join(n.lower() for n in ctx_names)}. Are hotspots on protected land, near towns, along the coast?",
                 f"Spatial Join of the hexagons with {', '.join(ctx)}.", ["Map 2: hotspots + overlay", "Table: hotspot characteristics"]),
              _q("Follow-up question", "Are the hotspots real or just where people look?",
                 "Check which kinds of record (human observation, specimen, machine) make up the hotspots, and whether they come from a few observers or many.",
                 "Summary Statistics by basisOfRecord within the top cells.", ["Chart: record types in hotspots"])]
    pid = f"g-sp-{info['key']}-{_slug(region)}"
    return {
        "id": pid, "icon": g["icon"], "title": title, "tagline": f"A {g['noun']} story from {region}, built from real records.",
        "theme": g["theme"], "difficulty": "Beginner" if style != "hotspots" else "Intermediate", "workload_h": [6, 10] if style != "hotspots" else [8, 12],
        "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"], "period_class": "historical", "data_type": "vector",
        "summary": f"Map the real GBIF records of the {nice} in {region} and relate them to {', '.join(n.lower() for n in ctx_names)}.",
        "question": question, "study_area": region, "region": region, "topic": f"where and when the {name} is recorded in {region}",
        "time_period": "Records with a year inside your chosen period", "time_note": "Filtered by each record's year; records without a year are left out.",
        "analysis": qs[0]["how"] + " " + qs[1]["how"], "outputs": "Records map, summary chart, overlay map, short StoryMap.",
        "purpose": f"This project investigates where and when the {name} is recorded in {region} and how that relates to {ctx_names[0].lower()}. "
                   f"It matters because knowing where a {g['noun']} actually turns up — and where nobody has looked — guides conservation and further surveys.",
        "datasets": [ds] + ctx + ["regc"],
        "limitations": ["Records show where people observed the species, not where it does or doesn't live (observer effort varies).",
                        "Locations of threatened species may be deliberately blurred by publishers.",
                        "Each record carries its own licence (some non-commercial) — check before publishing.",
                        "The region filter is a rectangle around the region; the analysis tags each point with its real region."],
        "needs": [("Record locations", [(ds, "geometry")]), ("Record year", [(ds, r"^year$")]), ("Region names to summarise by", [("regc", r"NAME$")])],
        "case_study": {"headline": title, "dek": f"Every dot is a real sighting or specimen of the {name}. Together they tell a story about {region} — and about the people who record nature there.",
                       "time_dataset": ds if style == "seasons" else None, "overlay": ctx + ["regc"], "questions": qs, "images": []},
        "_new_datasets": [spec], "_photo_q": [(info["canonical"], re.escape(info["canonical"].split(" ")[0])),
                      (f"{(info['common'] or '').split(' / ')[-1]} New Zealand".strip(), re.escape(info["canonical"].split(" ")[0]) + "|" + re.escape((info["common"] or info["canonical"]).split(" / ")[-1])),
                      (f"{region} New Zealand landscape", re.escape(region.split("-")[0]) + ".*" + SCENE)],
        "_sig": f"species:{info['key']}",
    }


# ------------------------------------------------------------------ weather / hazards / outdoors (curated datasets)
PH_MUST = {"om_temp": r"(heat|hot|summer|drought|dry|sun|frost|cold)", "om_rain": r"(rain|storm|flood|wet|cloud)", "om_wind": r"(wind|storm|gale|gust)",
           "om_sun": r"(sun|sunny|sunset|sunrise|beach|summer)", "om_snow": r"(snow|winter|ski|alpine|frost)"}
WEATHER = {
    "om_temp": ("🌡️", "temperature", "hottest and coldest days", ["urban_rural"], "heat"),
    "om_rain": ("🌧️", "rainfall", "wettest days", ["niwa_flow_gauges", "urban_rural"], "rain"),
    "om_wind": ("💨", "wind", "windiest days", ["niwa_coastline", "urban_rural"], "wind storm"),
    "om_sun": ("☀️", "sunshine", "sunniest and dullest stretches", ["doc_campsites", "urban_rural"], "sunny beach"),
    "om_snow": ("❄️", "snowfall", "snowiest days", ["doc_huts", "doc_tracks"], "snow mountains"),
}


def _weather_project(ds, region, style, rng):
    icon, word, extreme, ctx, ph = WEATHER[ds]
    ctx = [c for c in ctx if c in catalog.DATASETS]
    cn = [catalog.DATASETS[c]["name"].lower() for c in ctx]
    if style == "extremes":
        title = rng.choice([f"{word.title()} Extremes in {region}", f"{region}'s Record {word.title()} Days", f"When {region} Gets Wild: {word.title()}"])
        question = f"When and where did {region} have its {extreme} in your chosen period, and how unusual were they?"
        qs = [_q("Main question", f"When were the {extreme}?", f"Find the top 10 {extreme} at each weather point in {region}. Do they bunch into particular years or seasons?",
                 "Sort the daily table → select the top 10 per location → chart.", ["Chart: daily values with the extremes marked", "Table: top 10 days"]),
              _q("Contributing factors", "What sits near the most extreme places?", f"Compare the weather points with {', '.join(cn)}. Which places feel the extremes most?",
                 f"Near / Spatial Join with {', '.join(ctx)}.", ["Map 1: weather points sized by their extreme", "Table: place characteristics"]),
              _q("Follow-up question", "Are extremes becoming more common?", "Count the extreme days per year. Is there a trend, or just ups and downs?",
                 "Summary Statistics by year → line chart.", ["Chart: extreme days per year"])]
    else:
        title = rng.choice([f"The Seasons of {region}: {word.title()}", f"{word.title()} Through the Year in {region}", f"Reading {region}'s {word.title()} Calendar"])
        question = f"How does {word} in {region} change through the year and between places, over your chosen period?"
        qs = [_q("Main question", "What does a typical year look like?", f"Average the daily {word} by month for each weather point in {region}.",
                 "Calculate Field (month) → Summary Statistics by location and month.", ["Chart: monthly averages per place", "Table: monthly values"]),
              _q("Contributing factors", "Why do places differ?", f"Relate each point's pattern to {', '.join(cn)} nearby.",
                 f"Spatial Join with {', '.join(ctx)}.", ["Map 1: points coloured by annual total/average", "Map 2: overlay layers"]),
              _q("Follow-up question", "Has the pattern shifted?", "Compare the first and the last years of your period. Is the season longer, wetter, hotter?",
                 "Select by date → repeat the monthly summary.", ["Chart: early vs recent years"])]
    pid = f"g-wx-{ds}-{_slug(region)}-{style}"
    return {
        "id": pid, "icon": icon, "title": title, "tagline": f"Daily {word} at real weather points in {region}.",
        "theme": "weather" if style == "extremes" else "climate", "difficulty": "Beginner", "workload_h": [6, 10],
        "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"], "period_class": "multi-year", "data_type": "table + points",
        "summary": f"Explore daily {word} at the weather points in {region} and how it relates to {', '.join(cn)}.",
        "question": question, "study_area": region, "region": region,
        "topic": f"{word} extremes in {region}" if style == "extremes" else f"how {word} changes through the year in {region}",
        "time_period": "Daily values for your chosen period", "time_note": "Daily model/reanalysis values for exactly your chosen period.",
        "analysis": qs[0]["how"] + " " + qs[1]["how"], "outputs": "Time-series charts, weather-point map, short StoryMap.",
        "purpose": f"This project investigates {word} in {region} — its {extreme} and its yearly rhythm. It matters because weather drives floods, droughts, "
                   "farming and outdoor life, and seeing it place by place shows who is most affected.",
        "datasets": [ds] + ctx + ["regc"],
        "limitations": ["Values are model/reanalysis output for the nearest grid cell, not a weather-station reading.",
                        "Only a few weather points per region — they show the pattern, not every valley.",
                        "Some variables start later than others; the app reports the real date range after download."],
        "needs": [("Daily values", [(ds, r"^date$")]), ("Region names", [("regc", r"NAME$")])],
        "case_study": {"headline": title, "dek": f"Years of daily {word} records for {region}, ready to turn into a story about the weather people actually live with.",
                       "time_dataset": ds, "overlay": ctx + ["regc"], "questions": qs, "images": []},
        "_new_datasets": [], "_photo_q": [(f"{region} New Zealand {ph}", _nz(PH_MUST.get(ds, ph.split()[0]), region)), (f"New Zealand {ph}", _nz(PH_MUST.get(ds, ph.split()[0]), region)),
                      (f"{region} New Zealand landscape", re.escape(region.split("-")[0]) + ".*" + SCENE)],
        "_sig": f"weather:{ds}:{region}:{style}",
    }


HAZARDS = {
    "quake": ("🌋", ["geonet_fdsn", "nz_plates", "urban_rural", "ta"], "earthquake", "earthquake damage New Zealand"),
    "flood": ("🌊", ["niwa_flood_stats", "niwa_flow_gauges", "urban_rural"], "flood", "flood New Zealand river"),
    "coast": ("🏖️", ["niwa_coast_erosion", "niwa_esl_1pc", "doc_campsites", "urban_rural"], "coastal erosion", "coastal erosion New Zealand"),
    "volcano": ("🌋", ["geonet_volcano", "geonet_fdsn", "urban_rural"], "volcano", "volcano New Zealand"),
}


def _hazard_project(kind, region, style, rng):
    icon, dsl, word, ph = HAZARDS[kind]
    dsl = [d for d in dsl if d in catalog.DATASETS]
    names = [catalog.DATASETS[d]["name"] for d in dsl]
    town = "towns and cities" if "urban_rural" in dsl else "people"
    if style == "exposure":
        title = rng.choice([f"Who Is Exposed? {word.title()} Risk in {region}", f"{region} on the Front Line: {word.title()}s", f"Living with {word.title()}s in {region}"])
        question = f"Which parts of {region} are most exposed to {word}s, and how close are its {town}?"
        qs = [_q("Main question", f"Where is {word} exposure highest?", f"Map {names[0].lower()} across {region} and rank the areas.",
                 f"Summarise Within / Pairwise Intersect of {dsl[0]} with regc or ta.", ["Map 1: hazard layer by area", "Table: areas ranked", "Chart: ranked bar chart"]),
              _q("Contributing factors", f"How close are {town}?", f"Overlay {', '.join(n.lower() for n in names[1:])} to see what lies inside or near the hazard.",
                 "Spatial Join / Near with urban_rural.", ["Map 2: hazard + urban areas", "Table: urban areas affected"]),
              _q("Follow-up question", "What would you tell the council?", "Pick the two most exposed places and describe what the data says — and what it cannot say.",
                 "Select By Location → summary table.", ["Sidecar: two place profiles"])]
    else:
        title = rng.choice([f"Patterns of {word.title()} in {region}", f"Reading the {word.title()} Record: {region}", f"{region}'s {word.title()} Story"])
        question = f"What spatial pattern do {word}s follow in {region}, and what lines up with it?"
        qs = [_q("Main question", "What is the pattern?", f"Map {names[0].lower()} in {region}. Is it clustered, in a line, or scattered?",
                 "Hexbin or kernel density; Summary Statistics by area.", ["Map 1: density", "Chart: values by area"]),
              _q("Contributing factors", "What lines up with it?", f"Compare with {', '.join(n.lower() for n in names[1:])}.",
                 "Near / Spatial Join with the context layers.", ["Map 2: overlay", "Table: distance classes"]),
              _q("Follow-up question", "What changes over time or between areas?", "Compare two parts of the region (or two time spans if the data has dates).",
                 "Select by area/date → repeat the summary.", ["Swipe: two areas or two periods"])]
    pid = f"g-hz-{kind}-{_slug(region)}-{style}"
    return {
        "id": pid, "icon": icon, "title": title, "tagline": f"{word.title()} hazard seen through real data for {region}.",
        "theme": "hazards", "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "multi-year" if kind in ("quake", "volcano") else "modelled", "data_type": "vector",
        "summary": f"Investigate {word}s in {region} with {', '.join(n.lower() for n in names[:3])}.",
        "question": question, "study_area": region, "region": region, "topic": f"{word} hazard in {region}",
        "time_period": "Events in your chosen period (modelled layers are not date-based)", "time_note": "Earthquake events use your period; modelled hazard layers are static.",
        "analysis": qs[0]["how"] + " " + qs[1]["how"], "outputs": "Hazard map, ranking chart, exposure overlay, short StoryMap.",
        "purpose": f"This project investigates {word} hazard in {region} and which places and people are most exposed. "
                   "It matters because knowing where hazards and communities overlap is the first step in planning for them.",
        "datasets": dsl + ["regc"],
        "limitations": ["Hazard layers are modelled or catalogued events — not damage, and not a prediction.", "Exposure is not impact: nearness alone does not mean harm.",
                        "Line/polygon layers are not clipped by the app; clip them to the region in ArcGIS Pro."],
        "needs": [("Hazard geometry", [(dsl[0], "geometry")]), ("Region names", [("regc", r"NAME$")])],
        "case_study": {"headline": title, "dek": f"{region} lives with {word}s. Real hazard data shows where — and who is closest.",
                       "time_dataset": dsl[0] if kind in ("quake",) else None, "overlay": dsl[1:] + ["regc"], "questions": qs, "images": []},
        "_new_datasets": [], "_photo_q": [(f"{region} New Zealand {word}", _nz(word.split()[0], region)), (ph, _nz(word.split()[0], region)), (f"{region} New Zealand landscape", re.escape(region.split("-")[0]) + ".*" + SCENE)],
        "_sig": f"hazard:{kind}:{region}:{style}",
    }


OUTDOORS = {"doc_huts": ("🛖", "huts"), "doc_tracks": ("🥾", "tracks"), "doc_campsites": ("⛺", "campsites"), "doc_walks": ("🚶", "short walks"),
            "doc_hunting": ("🦌", "hunting areas")}


def _outdoors_project(ds, region, rng):
    icon, word = OUTDOORS[ds]
    ctx = [c for c in ("doc_land", "ta") if c in catalog.DATASETS]
    title = rng.choice([f"Getting Out There: {word.title()} of {region}", f"{region}'s Backcountry {word.title()}", f"Who Can Reach the {word.title()}? {region}"])
    qs = [_q("Main question", f"Where are {region}'s {word}?", f"Map DOC's {word} in {region} and count them by district.",
             "Summarize Within with ta.", ["Map 1: facilities", "Table: count per district"]),
          _q("Contributing factors", "How does it relate to conservation land?", "Compare with public conservation land: which districts have lots of land but few facilities?",
             "Summarize Within doc_land area; Calculate Field (facilities per 100 km²).", ["Map 2: density per district", "Chart: facilities vs land"]),
          _q("Follow-up question", "Who is far from them?", "Measure the distance from towns to the nearest facility.",
             "Near (urban areas → facilities).", ["Map 3: distance classes"])]
    pid = f"g-out-{ds}-{_slug(region)}"
    return {
        "id": pid, "icon": icon, "title": title, "tagline": f"DOC's {word} and the land around them in {region}.",
        "theme": "outdoors", "difficulty": "Beginner", "workload_h": [6, 10], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
        "period_class": "current", "data_type": "vector",
        "summary": f"Map the Department of Conservation's {word} in {region} and compare them with conservation land and districts.",
        "question": f"How are DOC's {word} spread across {region}, and which districts are well or poorly served?", "study_area": region, "region": region,
        "topic": f"DOC's {word} in {region}",
        "time_period": "Current DOC data (not date-based)", "time_note": "Current DOC layers — your time period does not change them.",
        "analysis": qs[0]["how"] + " " + qs[1]["how"], "outputs": "Facility map, density chart, access map, short StoryMap.",
        "purpose": f"This project investigates access to the outdoors in {region} through DOC's {word}. It matters because getting into nature is part of "
                   "New Zealand life, and gaps in provision show where access could improve.",
        "datasets": [ds] + ctx + ["regc"],
        "limitations": ["Facility condition, closures and capacity are not in the data.", "Counts are not visitor numbers."],
        "needs": [("Facility locations", [(ds, "geometry")]), ("District names", [("ta", r"NAME")])],
        "case_study": {"headline": title, "dek": f"{region}'s {word} are a doorway to the backcountry. Where are they, and who can reach them?",
                       "time_dataset": None, "overlay": ctx + ["regc"], "questions": qs, "images": []},
        "_new_datasets": [], "_photo_q": [(f"{region} New Zealand {word.rstrip('s')}", _nz(word.split()[-1].rstrip("s"), region)), (f"{region} New Zealand tramping", _nz(r"tramp|track|hut|walk|hik|camp", region)),
                      (f"{region} New Zealand landscape", re.escape(region.split("-")[0]) + ".*" + SCENE)],
        "_sig": f"outdoors:{ds}:{region}",
    }


# ------------------------------------------------------------------ discovered (ArcGIS Online, live search)
TOPICS = [("wetlands", "environment", "🪷"), ("parks and reserves", "outdoors", "🌳"), ("cycleways", "outdoors", "🚲"), ("heritage sites", "environment", "🏛️"),
          ("notable trees", "environment", "🌳"), ("landslides", "hazards", "⛰️"), ("liquefaction", "hazards", "🏚️"), ("tsunami evacuation zones", "hazards", "🌊"),
          ("water quality monitoring sites", "freshwater", "💧"), ("stormwater", "freshwater", "🌧️"), ("playgrounds", "environment", "🛝"),
          ("walkways", "outdoors", "🥾"), ("coastal hazard", "hazards", "🏖️"), ("flood hazard", "hazards", "🌊"), ("biodiversity sites", "wildlife", "🦜"),
          ("significant natural areas", "wildlife", "🌿"), ("bus stops", "environment", "🚌"), ("schools", "environment", "🏫"), ("drinking water", "freshwater", "🚰"),
          ("public toilets", "outdoors", "🚻"), ("dog exercise areas", "outdoors", "🐕"), ("street trees", "environment", "🌳"), ("bores and wells", "freshwater", "💧"),
          ("contaminated land", "environment", "⚠️"), ("fault lines", "hazards", "🌋"), ("erosion", "hazards", "⛰️"), ("boat ramps", "marine", "⛵")]


def _discovered_project(store, topic, region, rng, used_urls, cancel):
    from . import connectors, discovery
    word, theme, icon = topic
    key = {"parks and reserves": "park|reserve", "heritage sites": "heritage", "notable trees": "tree", "water quality monitoring sites": "water quality",
           "tsunami evacuation zones": "tsunami", "biodiversity sites": "biodiversity", "significant natural areas": "significant natural|sna",
           "bores and wells": "bore|well", "dog exercise areas": "dog", "public toilets": "toilet", "boat ramps": "boat ramp",
           "contaminated land": "contaminat", "fault lines": "fault", "street trees": "tree", "bus stops": "bus stop"}.get(word, word.rstrip("s"))
    try:
        hits = discovery._search_arcgis(word.split(), region, cancel)
    except Exception:  # noqa: BLE001
        return None
    bbox = store.region_bbox(region)
    for r in hits[:6]:
        if r["url"] in used_urls or not re.search(r"/FeatureServer", r["url"]):
            continue
        if not re.search(key, f"{r['title']} {r['snippet']}", re.I):
            continue  # the layer must really be about the topic
        spec = {"id": "x_" + hashlib.sha1(r["url"].encode()).hexdigest()[:10], "role": "essential", "connector": "arcgis", "name": r["title"][:90],
                "publisher": f"{r['owner']} (ArcGIS Online)", "service_url": r["url"], "landing_url": r["url"],
                "licence_note": r["licence"] or "Licence not stated on the item — confirm with the publisher before publishing"}
        try:
            v = connectors.verify_within(spec, 60, bbox=bbox, cancel=cancel)
        except Exception:  # noqa: BLE001
            continue
        if v.get("status") != "verified" or not (15 <= (v.get("count") or 0) <= 60000):
            continue
        used_urls.add(r["url"])
        nm = spec["name"]
        title = rng.choice([f"{word.title()} of {region}", f"Mapping {region}'s {word.title()}", f"{region} Close Up: {word.title()}"])
        ctx = [c for c in ("ta", "urban_rural") if c in catalog.DATASETS]
        qs = [_q("Main question", f"Where are {region}'s {word}?", f"Map “{nm}” and count the features by district.",
                 "Summarize Within with ta.", ["Map 1: the layer by district", "Table: count/area per district"]),
              _q("Contributing factors", "How does it relate to towns and countryside?", "Compare urban and rural areas: where is it concentrated, and where is it missing?",
                 "Spatial Join with urban_rural.", ["Map 2: layer + urban/rural", "Chart: urban vs rural"]),
              _q("Follow-up question", "What would you improve or investigate next?", "Pick one district that stands out and explain why, using the layer's own attributes.",
                 "Select By Attributes → summary.", ["Sidecar: district profile"])]
        geo = str(v.get("geometry_type") or "").replace("esriGeometry", "").lower() or "feature"
        return {
            "id": f"g-ao-{spec['id'][2:]}-{_slug(region)}", "icon": icon, "title": title, "tagline": f"A live ArcGIS Online layer from {r['owner']}, for {region}.",
            "theme": theme, "difficulty": "Intermediate", "workload_h": [8, 12], "software": ["ArcGIS Pro", "ArcGIS Online", "ArcGIS StoryMaps"],
            "period_class": "current", "data_type": "vector",
            "summary": f"Explore “{nm}” ({v.get('count'):,} {geo} features in {region}, published by {r['owner']}) alongside districts and urban areas.",
            "question": f"How are {region}'s {word} distributed, and how does that differ between districts and between town and country?",
            "study_area": region, "region": region, "topic": f"{word} in {region}", "time_period": "Current layer (not date-based)", "time_note": "A published layer — your time period does not change it.",
            "analysis": qs[0]["how"] + " " + qs[1]["how"], "outputs": "District map, urban/rural comparison, short StoryMap.",
            "purpose": f"This project investigates {word} in {region} using a layer found live on ArcGIS Online. It matters because local data like this shows how "
                       "a place is actually organised — and where it could do better.",
            "datasets": [spec["id"]] + ctx + ["regc"],
            "limitations": ["Found by a live ArcGIS Online search: read the item's description to understand how it was made.",
                            "The licence is not confirmed by the app — check it before publishing.", r["snippet"][:160] or "The item has no description."],
            "needs": [("Layer geometry", [(spec["id"], "geometry")]), ("District names", [("ta", r"NAME")])],
            "case_study": {"headline": title, "dek": f"A real layer, found online today: {nm}.", "time_dataset": None, "overlay": ctx + ["regc"], "questions": qs, "images": []},
            "_new_datasets": [spec], "_verified": {spec["id"]: v},
            "_photo_q": [(f"{region} New Zealand {word}", _nz(key, region)), (f"New Zealand {word}", _nz(key, region)), (f"{region} New Zealand landscape", re.escape(region.split("-")[0]) + ".*" + SCENE)],
            "_sig": f"discovered:{r['url']}",
        }
    return None


# ------------------------------------------------------------------ one round
def candidates(store, history, rng, cancel):
    """Lazy candidate builders per family, never repeating anything in history."""
    regions = list(catalog.REGION_NAMES)
    rng.shuffle(regions)
    out = {f: [] for f, _ in QUOTAS}
    pool = [k for k, n in species_pool(cancel) if 300 <= n <= 400000 and f"species:{k}" not in history]
    rng.shuffle(pool)
    for i, key in enumerate(pool[:40]):
        out["species"].append(("species", key, regions[i % len(regions)]))
    for ds in WEATHER:
        for r in regions:
            for st in ("extremes", "seasons"):
                if f"weather:{ds}:{r}:{st}" not in history:
                    out["weather"].append(("weather", (ds, st), r))
    for kind in HAZARDS:
        for r in (VOLCANIC if kind == "volcano" else regions):
            for st in ("exposure", "pattern"):
                if f"hazard:{kind}:{r}:{st}" not in history:
                    out["hazard"].append(("hazard", (kind, st), r))
    for ds in OUTDOORS:
        for r in regions:
            if f"outdoors:{ds}:{r}" not in history:
                out["outdoors"].append(("outdoors", ds, r))
    for t in TOPICS:
        for r in regions[:6]:
            out["discovered"].append(("discovered", t, r))
    for f in out:
        if f != "species":
            rng.shuffle(out[f])
    return out


def build(store, family, arg, region, rng, used_urls, cancel):
    if family == "species":
        info = species_info(arg, cancel)
        return _species_project(info, region, rng) if info else None
    if family == "weather":
        return _weather_project(arg[0], region, arg[1], rng)
    if family == "hazard":
        return _hazard_project(arg[0], region, arg[1], rng)
    if family == "outdoors":
        return _outdoors_project(arg, region, rng)
    return _discovered_project(store, arg, region, rng, used_urls, cancel)


def _nz(topic, region=""):
    """'must mention' pattern: the topic AND New Zealand (or the region) somewhere in the photo's title/description."""
    place = r"New Zealand|Aotearoa|\bNZ\b" + ("|" + re.escape(region.split("-")[0]) if region else "")
    return rf"^(?=[\s\S]*(?:{place}))(?=[\s\S]*(?:{topic}))"


def finish(p, used_photos, design, cancel=None):
    """Attach photos and design to an accepted project."""
    imgs = commons_photos([q for q in p.pop("_photo_q", []) if q], 3, used_photos, cancel)
    if len(imgs) < 3:
        reg = p.get("region", "")
        imgs += commons_photos([(f"{reg} New Zealand", re.escape(reg.split("-")[0]) + ".*" + SCENE), ("New Zealand landscape", SCENE)], 3 - len(imgs), used_photos, cancel)
    for i, im in enumerate(imgs):
        im["role"] = "cover" if i == 0 else "inline"
    p["case_study"]["images"] = imgs
    p["design"] = design
    for k in ("_new_datasets", "_verified"):
        p.pop(k, None)
    return p
