"""Regional versions of the project templates.

Each Refresh builds a completely different set of projects: every template is re-focused on a different New Zealand region
(e.g. "Shaky Isles — Wellington"), with its question, purpose and story rewritten for that place. The datasets are the same
verified sources but are filtered to the region, so each version is a genuinely different case study and its files are much
smaller. Nothing is invented: every version is re-verified live (with the region applied) before it is shown."""
import copy
import random
import re

from . import catalog

# templates that only make sense in some regions (otherwise any region may be used)
ONLY = {
    "nz-volcano-watch": ["Northland", "Auckland", "Waikato", "Bay of Plenty", "Manawatū-Whanganui", "Taranaki"],
    "nz-quake-decade": None,
}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("ā", "a").replace("ū", "u").replace("ō", "o")).strip("-")


def _regionalise(text, region):
    t = text
    t = re.sub(r"\bwhich regions\b", f"which parts of {region}", t, flags=re.I)
    t = re.sub(r"\beach region\b", f"each part of {region}", t, flags=re.I)
    t = re.sub(r"\bregions\b", f"areas of {region}", t)
    t = re.sub(r"\bby region\b", f"by area within {region}", t)
    if region not in t:
        t = f"In {region}: " + (t[:1].lower() + t[1:] if not t[:2].isupper() else t)
    elif text[:1].isupper():
        t = t[:1].upper() + t[1:]
    return t


def make_variant(base, region):
    pid = f"{base['id']}@{_slug(region)}"
    if pid in catalog.PROJECT_BY_ID:
        return catalog.PROJECT_BY_ID[pid]
    v = {k: (copy.copy(val) if isinstance(val, (list, dict)) else val) for k, val in base.items()}
    cs = copy.deepcopy(base["case_study"])
    cs["headline"] = f"{cs['headline']}: {region}"
    cs["dek"] = f"{cs['dek']} Here the focus is {region}."
    for q in cs["questions"]:
        q["text"] = _regionalise(q["text"], region)
    v.update(
        id=pid, base_id=base["id"], base_title=base["title"], region=region, case_study=cs,
        title=f"{base['title']} — {region}",
        summary=f"{base['summary']} This version focuses on {region}.",
        question=_regionalise(base["question"], region),
        purpose=f"{base['purpose']} This version looks at {region} specifically, so the story is local and the files are much smaller.",
        study_area=region,
    )
    catalog.PROJECT_BY_ID[pid] = v
    return v


def candidates(base, taken, rng, n=3):
    """Up to n candidate regions for a template, preferring ones not yet used in this round."""
    pool = ONLY.get(base["id"]) or list(catalog.REGION_NAMES)
    fresh = [r for r in pool if r not in taken]
    rng.shuffle(fresh)
    rest = [r for r in pool if r in taken]
    rng.shuffle(rest)
    return (fresh + rest)[:n]


def plan_round(seed=None, avoid=()):
    """-> list of (base, [candidate regions]) with regions spread out so the set looks different from last time."""
    rng = random.Random(seed)
    taken, out = set(avoid), []
    bases = list(catalog.BASES)
    rng.shuffle(bases)
    for b in bases:
        c = candidates(b, taken, rng)
        if c:
            taken.add(c[0])
        out.append((b, c))
    order = {b["id"]: i for i, b in enumerate(catalog.BASES)}
    out.sort(key=lambda x: order[x[0]["id"]])
    return out


def apply(selection):
    """selection: list of (base_id, region|None). Makes it the live project list."""
    live = []
    for item in selection:
        base_id, region = item[0], item[1]
        extras = item[2] if len(item) > 2 else []
        base = catalog.BASE_BY_ID.get(base_id)
        if not base:
            continue
        proj = make_variant(base, region) if region else base
        proj["datasets"] = list(base["datasets"]) + [d for d in extras if d in catalog.DATASETS]
        live.append(proj)
    if live:
        catalog.PROJECTS[:] = live
    return live
