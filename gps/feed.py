"""Verification store + refresh. A project is 'verified' only if every dataset it needs passed live verification;
otherwise it is conditional/incomplete/unverified."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import catalog, connectors, coverage, timeperiod
from .net import Cancelled


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


DEFAULT_SETTINGS = {"max_file_mb": 2048, "stall_seconds": 90, "schedule_minutes": 0}


class Store:
    def __init__(self, state_dir):
        self.dir = state_dir
        self.lock = threading.RLock()
        self.verification = read_json(os.path.join(state_dir, "verification.json"), {})
        self.seen = set(read_json(os.path.join(state_dir, "seen.json"), []))
        # Per-project check results: refreshing ONE card writes only here, so no other project card can change.
        self.pver = read_json(os.path.join(state_dir, "verification_projects.json"), {})
        self.settings = {"project_root": os.path.abspath(os.path.join(state_dir, "..", "projects")), **DEFAULT_SETTINGS}
        saved = read_json(os.path.join(state_dir, "settings.json"), {})
        if "max_file_mb" not in saved and "max_download_mb" in saved:
            saved["max_file_mb"] = max(float(saved["max_download_mb"]), 1000)  # old setting was a combined limit; start from the new default
        saved.pop("max_download_mb", None)
        if saved.get("max_file_mb") == 1000:
            saved["max_file_mb"] = 2048  # the old default; the new default is a firm 2 GB per file
        self.settings.update(saved)
        # Dataset addresses the user switched to via Troubleshoot (survive restarts)
        self.overrides = read_json(os.path.join(state_dir, "overrides.json"), {})
        for ds, url in self.overrides.items():
            if ds in catalog.DATASETS:
                catalog.DATASETS[ds]["service_url"] = catalog.DATASETS[ds]["landing_url"] = url
        # Extra datasets the user added from "Find missing datasets" (survive restarts)
        self.custom = read_json(os.path.join(state_dir, "custom_datasets.json"), {})
        for ds, spec in self.custom.items():
            catalog.DATASETS[ds] = spec
        self.regions = read_json(os.path.join(state_dir, "regions.json"), {})
        try:  # keep the project set from the last Refresh across restarts
            from . import variants
            variants.apply([tuple(x) for x in read_json(os.path.join(state_dir, "projects_selection.json"), [])])
        except Exception:  # noqa: BLE001
            pass
        # Generated projects (Refresh all) + everything ever shown, so nothing repeats and old jobs still open
        self.history = set(read_json(os.path.join(state_dir, "project_history.json"), []))
        self.generated = read_json(os.path.join(state_dir, "generated_projects.json"), {"projects": {}, "current": []})
        self.generated.setdefault("projects", {})
        for pid, proj in self.generated["projects"].items():
            catalog.PROJECT_BY_ID[pid] = proj
        cur = [catalog.PROJECT_BY_ID[i] for i in self.generated.get("current", []) if i in catalog.PROJECT_BY_ID]
        if cur:
            catalog.PROJECTS[:] = cur
        self.refresh_status = {"state": "idle", "message": "No verification has run yet.", "done": 0, "total": 0,
                               "last_finished": None, "log": []}
        self._cancel = threading.Event()
        self._thread = None
        self._sched = None

    # ---- persistence
    def save(self):
        with self.lock:
            write_json_atomic(os.path.join(self.dir, "verification.json"), self.verification)
            write_json_atomic(os.path.join(self.dir, "verification_projects.json"), self.pver)
            write_json_atomic(os.path.join(self.dir, "seen.json"), sorted(self.seen))
            write_json_atomic(os.path.join(self.dir, "settings.json"), self.settings)

    def update_settings(self, patch):
        with self.lock:
            if "project_root" in patch and str(patch["project_root"]).strip():
                self.settings["project_root"] = str(patch["project_root"]).strip()
            for k, lo, cast in (("max_file_mb", 0.001, float), ("stall_seconds", 15, float), ("schedule_minutes", 0, int)):
                if k in patch:
                    try:
                        self.settings[k] = max(lo, cast(patch[k]))
                    except (TypeError, ValueError):
                        raise ValueError(f"'{k}' must be a number")
            self.save()

    def add_custom(self, spec):
        """Register a user-selected extra dataset (from discovery) so jobs can use it."""
        with self.lock:
            self.custom[spec["id"]] = spec
            catalog.DATASETS[spec["id"]] = spec
            write_json_atomic(os.path.join(self.dir, "custom_datasets.json"), self.custom)

    def region_bbox(self, name):
        """[minx, miny, maxx, maxy] in WGS84 for a regional council, fetched once from Stats NZ and cached."""
        from . import net
        key = name.strip()
        if key in self.regions:
            return self.regions[key]
        base = catalog.REGC["service_url"]
        st, js = net.get_json(base + "/query", {"where": "1=1", "outFields": "REGC2023_V1_00_NAME", "returnGeometry": "false", "f": "json"})
        names = [f["attributes"]["REGC2023_V1_00_NAME"] for f in js.get("features", [])]
        from . import quality
        for full in names:
            st, r = net.get_json(base + "/query", {"where": f"REGC2023_V1_00_NAME='{full}'", "returnExtentOnly": "true", "outSR": "4326", "f": "json"})
            e = (r or {}).get("extent")
            if e:
                bbox = [round(e["xmin"], 5), round(e["ymin"], 5), round(e["xmax"], 5), round(e["ymax"], 5)]
                self.regions[full.replace(" Region", "")] = bbox
                self.regions[full] = bbox
        with self.lock:
            write_json_atomic(os.path.join(self.dir, "regions.json"), self.regions)
        for k in self.regions:
            if quality.norm_name(k) in (quality.norm_name(name), quality.norm_name(name) + "region"):
                return self.regions[k]
        raise KeyError(f"region {name}")

    # ---- refresh (all projects, from scratch)
    def _log(self, msg):
        with self.lock:
            self.refresh_status["log"].append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
            self.refresh_status["log"] = self.refresh_status["log"][-400:]
            self.refresh_status["message"] = msg

    def start_refresh(self, period=None):
        with self.lock:
            if self._thread and self._thread.is_alive():
                return False
            self.seen.update(p["id"] for p in self.feed() if p["availability"] == "verified")  # what the user has been shown
            self.save()
            self._cancel.clear()
            # mark it running NOW, so a status check made straight after the click can't see "idle" and stop waiting
            self.refresh_status.update({"state": "running", "done": 0, "total": 0, "log": [], "message": "Starting a new set of projects…"})
            self._thread = threading.Thread(target=self._refresh, args=(period,), daemon=True)
            self._thread.start()
            return True

    def cancel_refresh(self):
        self._cancel.set()

    def _save_selection(self):
        sel = [[p.get("base_id", p["id"]), p.get("region"), [d for d in p["datasets"] if d.startswith("x_")]] for p in catalog.PROJECTS]
        write_json_atomic(os.path.join(self.dir, "projects_selection.json"), sel)

    def _refresh(self, period=None):
        """Refresh all = a brand-new set of projects built from live sources (see generator.py): new topics, regions,
        questions, photos and card designs. Each is verified live before it is shown; nothing already shown comes back."""
        import random
        from collections import Counter
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from . import generator
        rng = random.Random()
        target = sum(n for _, n in generator.QUOTAS)
        with self.lock:
            self.verification = {}
            self.pver = {}
            self.save()
            self.refresh_status.update({"state": "running", "done": 0, "total": target, "log": []})
        self._log(f"Building a brand-new set of {target} projects from live sources (GBIF species, weather, hazards, DOC, ArcGIS Online) — "
                  "each is checked live with its region applied; anything you have seen before is skipped.")
        try:
            history = set(self.history) | {p.get("sig") for p in catalog.PROJECTS if p.get("sig")}
            cands = generator.candidates(self, history, rng, self._cancel)
            accepted = {f: [] for f, _ in generator.QUOTAS}
            used_regions = Counter()
            used_urls = {h.split(":", 1)[1] for h in history if h.startswith("discovered:")}  # never reuse a layer from an earlier refresh

            def next_item(family):
                with self.lock:
                    lst = cands[family]
                    if not lst:
                        return None
                    i = min(range(min(len(lst), 25)), key=lambda k: used_regions[lst[k][2]])
                    item = lst.pop(i)
                    used_regions[item[2]] += 1  # reserve the region while it is being checked
                    return item

            def work(fq):
                family, quota = fq
                tries = 0
                while len(accepted[family]) < quota and tries < quota * 5:
                    if self._cancel.is_set():
                        raise Cancelled()
                    item = next_item(family)
                    if not item:
                        break
                    tries += 1
                    region = item[2]
                    try:
                        p = generator.build(self, family, item[1], region, rng, used_urls, self._cancel)
                    except Cancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        self._log(f"  (skipped a {family} idea: {str(e)[:100]})")
                        p = None
                    if not p:
                        with self.lock:
                            used_regions[region] -= 1
                        continue
                    for spec in p["_new_datasets"]:
                        catalog.DATASETS[spec["id"]] = spec
                    catalog.PROJECT_BY_ID[p["id"]] = p
                    self._log(f"Verifying: {p['title']}")
                    card = self.check_project(p["id"], period, region)
                    core = self.ver(p["id"], p["datasets"][0]) or {}
                    enough = (core.get("count") or 0) >= (40 if family == "species" else 1)
                    ok = card["availability"] == "verified" and card["possible"] and enough
                    if ok:
                        why = ""
                    elif card["reasons"]:
                        why = " (" + card["reasons"][0] + ")"
                    elif not card["possible"]:
                        why = " (too big for your file-size limit)"
                    else:
                        why = f" (only {core.get('count') or 0} records in {region})"
                    shown = "verified" if ok else (card["availability"] if card["availability"] != "verified" else "skipped")
                    self._log(f"  → {p['title']} — {shown}{why[:150]}")
                    if ok:
                        with self.lock:
                            accepted[family].append(p)
                            self.refresh_status["done"] += 1
                    else:
                        with self.lock:
                            used_regions[region] -= 1
                        catalog.PROJECT_BY_ID.pop(p["id"], None)
                        self.pver.pop(p["id"], None)
                        for spec in p["_new_datasets"]:
                            catalog.DATASETS.pop(spec["id"], None)

            with _TPE(max_workers=3) as pool:
                list(pool.map(work, generator.QUOTAS))
            # interleave families so the list is varied, then give each card its own photos + design
            order, live = [list(accepted[f]) for f, _ in generator.QUOTAS], []
            while any(order):
                for lst in order:
                    if lst:
                        live.append(lst.pop(0))
            if not live:
                raise RuntimeError("no new project passed its live checks — check your internet connection and try again")
            self._log(f"Finding photos and designing {len(live)} project cards…")
            accents = list(generator.ACCENTS)
            rng.shuffle(accents)
            used_photos = set()
            for i, p in enumerate(live):
                if self._cancel.is_set():
                    raise Cancelled()
                for spec in p["_new_datasets"]:
                    self.add_custom(spec)
                p["sig"] = p.pop("_sig")
                generator.finish(p, used_photos, {"accent": accents[i % len(accents)], "layout": generator.LAYOUTS[i % len(generator.LAYOUTS)]}, self._cancel)
            catalog.PROJECTS[:] = live
            with self.lock:
                self.history |= {p["sig"] for p in live}
                self.generated["projects"].update({p["id"]: p for p in live})
                self.generated["current"] = [p["id"] for p in live]
                write_json_atomic(os.path.join(self.dir, "generated_projects.json"), self.generated)
                write_json_atomic(os.path.join(self.dir, "project_history.json"), sorted(self.history))
                self.save()
                self.refresh_status.update({"state": "done", "last_finished": connectors.now_iso()})
            self._log(f"Finished: {len(live)} brand-new projects, all verified live: " + "; ".join(p["title"] for p in live))
        except Cancelled:
            with self.lock:
                self.refresh_status["state"] = "cancelled"
            self._log("Refresh cancelled — your previous projects are unchanged.")
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.refresh_status["state"] = "error"
            self._log(f"Refresh failed: {e} — your previous projects are unchanged.")

    def _add_found_dataset(self, v, region, period, claimed_urls):
        """Search ArcGIS Online again for ONE extra dataset for this regional project. It is only added if it is a public
        ArcGIS service that passes live verification, fits the file-size limit and is not already used by any other project."""
        from . import discovery
        try:
            self._log(f"Searching online for new data: {v['title']}")
            found = discovery.find(self, v, "", region, period, "gaps", self._cancel)
            lim = float(self.settings.get("max_file_mb") or 0) * 1048576
            for c in found["candidates"]:
                spec = c.get("spec")
                if c.get("kind") != "arcgis" or c.get("ready") != "ready" or not spec:
                    continue
                with self.lock:
                    if spec["service_url"] in claimed_urls:
                        continue
                    claimed_urls.add(spec["service_url"])
                    self.discovery = {c["id"]: c}
                    ds = discovery.register(self, [c["id"]])[0]
                res = connectors.make_source(catalog.DATASETS[ds]).verify(bbox=self.region_bbox(region), cancel=self._cancel,
                                                                           opts={"period": period, "filters": {}, "region": region})
                if res["status"] == "verified" and not (lim and res.get("est_bytes") and res["est_bytes"] > lim):
                    self.set_ver(v["id"], ds, res)
                    v["datasets"] = v["datasets"] + [ds]
                    self._log(f"  + found online: {c['title']} ({c['source']})")
                    return
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - a failed search must never break the refresh
            self._log(f"  (online search skipped: {str(e)[:100]})")

    def ver(self, project_id, ds):
        """The check result a project card shows: its own last check if it has one, else the last global refresh."""
        return (self.pver.get(project_id) or {}).get(ds) or self.verification.get(ds)

    def set_ver(self, project_id, ds, res):
        with self.lock:
            if project_id:
                self.pver.setdefault(project_id, {})[ds] = res
            else:
                self.verification[ds] = res

    def check_project(self, project_id, period=None, region=None):
        """Re-verify ONE project's datasets (only that card changes). Uses the chosen time period and region."""
        proj = catalog.PROJECT_BY_ID[project_id]
        bbox = None
        if region:
            try:
                bbox = self.region_bbox(region)
            except Exception:  # noqa: BLE001 - a region lookup problem must not block the check
                bbox = None
        opts = {"period": period, "filters": {}, "region": region}

        def one(ds):
            if ds == "regc":
                return ds, connectors.make_source(catalog.DATASETS[ds]).verify(bbox=None, cancel=threading.Event(), opts=opts)
            return ds, connectors.make_source(catalog.DATASETS[ds]).verify(bbox=bbox, cancel=threading.Event(), opts=opts)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ds, res in pool.map(one, proj["datasets"]):
                self.set_ver(project_id, ds, res)
        with self.lock:
            self.save()
            return self._card(proj, period)

    def use_alternative(self, ds, url):
        """Switch one ArcGIS dataset to a new address — only if it verifies live first."""
        spec = catalog.DATASETS[ds]
        if spec["connector"] != "arcgis":
            raise ValueError("only ArcGIS datasets can be switched")
        if not url.startswith("https://") or "/rest/services/" not in url:
            raise ValueError("not an ArcGIS REST service address")
        old = spec["service_url"]
        spec["service_url"] = spec["landing_url"] = url
        res = connectors.make_source(spec).verify(bbox=None, cancel=threading.Event())
        if res["status"] != "verified":
            spec["service_url"] = spec["landing_url"] = old
            raise ValueError("that address did not pass verification: " + "; ".join(c["detail"][:80] for c in res["checks"] if not c["ok"]))
        with self.lock:
            self.verification[ds] = res
            self.overrides[ds] = url
            write_json_atomic(os.path.join(self.dir, "overrides.json"), self.overrides)
            self.save()
        return res

    # ---- scheduler (only while this process is running)
    def start_scheduler(self):
        if self._sched:
            return

        def loop():
            last = time.time()
            while True:
                time.sleep(20)
                m = self.settings.get("schedule_minutes", 0)
                if m and time.time() - last >= m * 60:
                    last = time.time()
                    self.start_refresh()
        self._sched = threading.Thread(target=loop, daemon=True)
        self._sched.start()

    # ---- feed
    def project_status(self, p):
        res = [self.ver(p["id"], d) for d in p["datasets"]]
        if any(r is None for r in res):
            return "unverified", ["Not yet checked — click “Refresh project” on the card."]
        reasons = []
        for r in res:
            for c in r["checks"]:
                if not c["ok"]:
                    reasons.append(f"{r['name']}: {c['name']} — {c['detail']}")
        if all(r["status"] == "verified" for r in res):
            return "verified", []
        if any(r["status"] == "incomplete" for r in res):
            return "incomplete", reasons
        return "conditional", reasons

    def feed(self, period=None):
        return [self._card(p, period) for p in list(catalog.PROJECTS)]

    def _card(self, p, period=None):
        """One project's card, built from the project itself (so a project that isn't in the live list yet can still be checked)."""
        if True:
            status, reasons = self.project_status(p)
            dss, total, unknown, times, issues = [], 0, False, [], []
            for d in p["datasets"]:
                r = self.ver(p["id"], d)
                spec = catalog.DATASETS[d]
                cov = coverage.info(spec, period, r) if period else None
                if cov and cov["status"] in ("gap", "partial"):
                    issues.append(f"{spec['name']}: {cov['note']}")
                if r:
                    times.append(r["verified_at"])
                    if r.get("est_bytes") is not None:
                        total += r["est_bytes"]
                    else:
                        unknown = True
                dss.append({"id": d, "name": spec["name"], "publisher": spec["publisher"], "role": spec["role"],
                            "landing_url": spec.get("landing_url"), "verification": r, "coverage": cov,
                            "filterable": bool(connectors.filter_schema(spec, r))})
            lim = float(self.settings.get("max_file_mb") or 0) * 1048576
            over = []
            for d in p["datasets"]:
                r = self.ver(p["id"], d)
                if lim and r and r.get("est_bytes") and r["est_bytes"] > lim:
                    over.append({"id": d, "name": catalog.DATASETS[d]["name"], "est_bytes": r["est_bytes"]})
                elif lim and r and (r.get("count") or 0) > 300000 and any(g in str(r.get("geometry_type")) for g in ("Polygon", "Polyline")):
                    # A layer this big can't be sized reliably from a sample (real files of this kind run to many GB): treat as too big
                    # until a smaller study area is chosen, rather than discovering it halfway through a download.
                    over.append({"id": d, "name": f"{catalog.DATASETS[d]['name']} — {r['count']:,} features (too large to size reliably; choose a region)",
                                 "est_bytes": max(r.get("est_bytes") or 0, lim + 1)})
            return ({**{k: p[k] for k in p if k != "needs"}, "oversize": over, "possible": not over, "limit_mb": self.settings.get("max_file_mb"), "availability": status, "reasons": reasons,
                        "dataset_details": dss, "verified_at": min(times) if times else None, "time_issues": issues,
                        "period": period, "est_total_bytes": total, "size_unknown": unknown or not times,
                        "free_open": status == "verified", "is_new": p["id"] not in self.seen})
