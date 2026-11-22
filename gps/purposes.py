"""Plain-language purpose of each project (what it investigates and why it matters) and how the chosen time period applies."""

PURPOSES = {
    "nz-quake-decade": "This project investigates where New Zealand's earthquakes happen, how deep they are and how they line up with the plate boundary and the volcanoes GeoNet monitors. "
                       "It matters because the country sits on the edge of two tectonic plates, and knowing where the ground moves most helps communities, councils and engineers plan for it.",
    "nz-coastal-esl-exposure": "This project investigates which parts of the coast and which rivers are most exposed to flooding in NIWA's models. "
                               "It matters because floods are one of New Zealand's costliest hazards, and seeing exposure region by region shows where planning and protection are needed first.",
    "nz-galaxiid-records": "This project investigates where native freshwater fish such as whitebait and longfin eels have been recorded, and how that compares with introduced trout. "
                           "It matters because many native fish are declining, and sightings reveal both where they survive and where nobody has looked.",
    "nz-native-birds": "This project investigates where kiwi, kea, kākāpō and hoiho are seen and how much of that falls inside public conservation land. "
                       "It matters because these birds are national icons and several are threatened, so knowing where they live and how well that land is protected guides conservation.",
    "nz-outdoor-recreation": "This project investigates where DOC's huts, campsites, tracks and hunting areas are, and how they relate to public conservation land. "
                             "It matters because access to nature is a big part of New Zealand life, and spotting gaps helps people and planners see who is well served and who is not.",
    "nz-marine-life": "This project investigates where Hector's dolphins and New Zealand sea lions are seen and how much of that lies inside marine reserves and sanctuaries. "
                      "It matters because both species are rare, and the question 'are the places they use actually protected?' decides whether protection is working.",
    "nz-volcano-watch": "This project investigates which volcanoes are restless right now, the earthquakes around them, and the towns and conservation land nearby. "
                        "It matters because many communities live close to active volcanoes, and understanding proximity is the first step in understanding risk.",
    "nz-pests-predators": "This project investigates where introduced predators (stoats, rats) and game animals (red deer) have been recorded, and how that compares with conservation land and hunting areas. "
                          "It matters because introduced animals are a leading threat to native wildlife, and records show where the pressure is.",
    "nz-seabirds": "This project investigates where penguins and gannets are recorded around the coast and how much falls inside marine protection. "
                   "It matters because seabirds depend on both land and sea, and protection has to cover the places they actually use.",
    "nz-native-forests": "This project investigates where kauri, pōhutukawa and tōtara have been recorded and which ecological districts and conservation land they sit in. "
                         "It matters because these trees define New Zealand's forests, and some (like kauri) face serious disease threats.",
    "nz-coastline": "This project investigates which stretches of coast are sensitive to erosion, which are in the modelled flood extent, and where people camp and live. "
                    "It matters because the coast is where hazards and human use meet, so sensitive and busy places need attention first.",
    "nz-weather-extremes": "This project investigates where the wettest, windiest and hottest days occurred in the period you choose, and how they relate to recorded flood impacts. "
                           "It matters because extreme weather drives most of New Zealand's natural-hazard damage, and seeing it region by region shows where the risks are real.",
    "nz-climate-trends": "This project investigates how temperature, rainfall and snowfall have changed over the period you choose at sixteen regional centres. "
                         "It matters because telling lasting climate change apart from ordinary weather helps people prepare for what is coming.",
    "nz-air-sea": "This project investigates wave conditions off the coast and fine-particle air quality in the cities, and how they relate to where people live and where the sea is protected. "
                  "It matters because air and sea conditions affect health, safety and ecosystems, and few people see them side by side.",
}

TIME_NOTES = {
    "nz-quake-decade": "Earthquakes follow your time period exactly. Volcano alert levels are today's snapshot, and the felt-quake feed holds only a short recent window set by GeoNet. Plate and boundary layers are static.",
    "nz-coastal-esl-exposure": "These are modelled, static layers (not date-based), so your time period does not change them.",
    "nz-galaxiid-records": "Sightings are filtered by the year of each record. Boundaries and river-gauge layers are static.",
    "nz-native-birds": "Sightings are filtered by the year of each record. Conservation land is today's layer.",
    "nz-outdoor-recreation": "These are current DOC layers (not date-based), so your time period does not change them.",
    "nz-marine-life": "Sightings are filtered by the year of each record. Marine protection layers are current.",
    "nz-volcano-watch": "Earthquakes follow your time period. Volcano alert levels are today's snapshot only.",
    "nz-pests-predators": "Sightings are filtered by the year of each record. Hunting areas and conservation land are current layers.",
    "nz-seabirds": "Sightings are filtered by the year of each record. Protection and coastline layers are current.",
    "nz-native-forests": "Tree records are filtered by the year of each record. Ecological districts and conservation land are static.",
    "nz-coastline": "These are modelled and current layers (not date-based), so your time period does not change them.",
    "nz-weather-extremes": "Daily weather values follow your time period exactly. Flood-impact records are for January 2023 only and station locations are static.",
    "nz-climate-trends": "Daily climate values follow your time period exactly — use 10 years or more to see trends.",
    "nz-air-sea": "Daily wave and air-quality values follow your time period; the air-quality model may not reach back as far as the weather data.",
}
