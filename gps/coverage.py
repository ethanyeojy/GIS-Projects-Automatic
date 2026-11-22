"""Does a dataset actually cover the chosen time period? Answers with what is KNOWN (from the source's own behaviour or a
live check) and says "unknown" rather than guessing. Never substitutes a different period on the user's behalf."""
from datetime import date

LABEL = {"ok": "Covers your period", "partial": "Covers part of your period", "gap": "Does not cover your period",
         "static": "Not date-based", "snapshot": "Today's snapshot only", "unknown": "Coverage unknown"}


def info(spec, period, verification=None):
    """-> {status, note}. status ∈ ok | partial | gap | static | snapshot | unknown."""
    c = spec["connector"]
    ti = (verification or {}).get("time_info") or {}
    if not period:
        return {"status": "unknown", "note": "No time period chosen."}
    s, e = period["start"], period["end"]
    if c == "fdsn":
        if verification and verification.get("count") == 0:
            return {"status": "gap", "note": f"GeoNet returned no events between {s} and {e} with these settings."}
        return {"status": "ok", "note": f"Queried for exactly {s} → {e}. How completely small events were recorded varies over the years."}
    if c == "gbif":
        if verification and verification.get("count") == 0:
            return {"status": "gap", "note": f"No georeferenced NZ records with a year between {s[:4]} and {e[:4]}."}
        return {"status": "ok", "note": f"Filtered by each record's year ({s[:4]}–{e[:4]}). Records with no year are left out."}
    if c == "openmeteo":
        av = ti.get("availability")
        if av:
            good = {k: v.get("non_null", 0) > 0 for k, v in av.items()}
            if all(good.values()):
                return {"status": "ok", "note": f"Values returned at both the start and the end of {s} → {e}."}
            if any(good.values()):
                missing = [f"{k} ({av[k]['window']})" for k, g in good.items() if not g]
                return {"status": "partial", "note": "No values returned for: " + ", ".join(missing) + ". This service does not cover that part of your period."}
            return {"status": "gap", "note": f"The service returned no values for {s} → {e}."}
        return {"status": "unknown", "note": "Not checked yet — run the project check to see real availability."}
    if c == "geonet_quake":
        first, last = ti.get("first"), ti.get("last")
        if not first:
            return {"status": "unknown", "note": "GeoNet's felt-quake feed only holds a short recent window it chooses itself; the exact span shows after a check."}
        if last < s or first > e:
            return {"status": "gap", "note": f"This feed only holds {first} → {last}. Your period {s} → {e} does not overlap it."}
        if first > s or last < e:
            return {"status": "partial", "note": f"This feed only holds {first} → {last}; the rest of {s} → {e} is not available from it."}
        return {"status": "ok", "note": f"The feed's window ({first} → {last}) covers your period."}
    if c == "geojson_url":
        if e < date.today().isoformat():
            return {"status": "gap", "note": f"This source only shows today's values, but your period ended on {e}."}
        return {"status": "snapshot", "note": "Shows the current values (today). It is not a historical record, so your start date does not apply."}
    if c == "arcgis":
        return {"status": "static", "note": "A published layer that is not filtered by date, so your time period does not change it."}
    return {"status": "unknown", "note": "This file's date coverage is not known to the app — check its date columns after download."}
