"""TEST FIXTURE ONLY. A mock of the remote services' response SHAPES, with synthetic data
(regions are called 'Test North'/'Test South'). Used to exercise the code paths offline.
It is never imported by the app and its data must never be presented as real."""
import json
import math
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

REG = {"Test North": (170, -38, 176, -34), "Test South": (168, -46, 174, -42)}


def rect(b):
    x0, y0, x1, y1 = b
    return [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]  # clockwise


def pts(n, seed=1):
    out = []
    for i in range(n):
        reg = list(REG.values())[i % 3 % 2] if i % 7 else (160, -50, 162, -49)  # some outside both
        x0, y0, x1, y1 = reg
        fx = ((i * 37 + seed) % 100) / 100
        fy = ((i * 53 + seed) % 100) / 100
        out.append((x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)))
    return out


def esri_layer_meta(name, geom, fields, formats, maxrec=100, pag=True):
    return {"currentVersion": 11.1, "id": 0, "name": name, "type": "Feature Layer", "geometryType": geom, "displayField": fields[0][0],
            "capabilities": "Map,Query,Data", "supportedQueryFormats": formats, "maxRecordCount": maxrec,
            "copyrightText": "TEST FIXTURE copyright", "description": "<p>synthetic test layer</p>", "objectIdField": "OBJECTID",
            "advancedQueryCapabilities": {"supportsPagination": pag},
            "fields": [{"name": n, "type": t, "alias": n} for n, t in fields],
            "extent": {"xmin": 160, "ymin": -50, "xmax": 180, "ymax": -30, "spatialReference": {"wkid": 2193, "latestWkid": 2193}}}


def feats_regions():
    out = []
    for i, (n, b) in enumerate(REG.items()):
        out.append({"attributes": {"OBJECTID": i + 1, "REGC2023_V1_00": str(i + 1), "REGC2023_V1_00_NAME": n, "REGC2023_V1_00_NAME_ASCII": n, "LAND_AREA_SQ_KM": 1000.0 * (i + 1)},
                    "geometry": {"rings": [rect(b)]}})
    return out


def feats_polys(n):
    out = []
    for i, (x, y) in enumerate(pts(n, 3)):
        out.append({"attributes": {"OBJECTID": i + 1, "NAME": f"poly{i}"}, "geometry": {"rings": [[[x, y], [x, y + .01], [x + .01, y + .01], [x + .01, y], [x, y]]]}})
    return out


def feats_lines(n):
    out = []
    for i, (x, y) in enumerate(pts(n, 5)):
        out.append({"attributes": {"OBJECTID": i + 1, "NZREACH": 1000 + i, "Data_100y": 10.0 + i, "Data_50y": 8.0 + i, "Region": "x"}, "geometry": {"paths": [[[x, y], [x + .02, y + .02]]]}})
    return out


def to_geojson(feats, gtype):
    out = []
    for f in feats:
        g = f["geometry"]
        if "rings" in g:
            geom = {"type": "Polygon", "coordinates": g["rings"]}
        elif "paths" in g:
            geom = {"type": "LineString", "coordinates": g["paths"][0]}
        else:
            geom = None
        out.append({"type": "Feature", "properties": f["attributes"], "geometry": geom})
    return {"type": "FeatureCollection", "features": out}


LAYERS = {
    "services2.arcgis.com/vKb0s8tBIA3bdocZ/ArcGIS/rest/services/REGC_2023/FeatureServer/0":
        (esri_layer_meta("Regional Council 2023", "esriGeometryPolygon", [("REGC2023_V1_00_NAME", "esriFieldTypeString"), ("OBJECTID", "esriFieldTypeOID"), ("REGC2023_V1_00_NAME_ASCII", "esriFieldTypeString"), ("LAND_AREA_SQ_KM", "esriFieldTypeDouble")], "JSON, geoJSON"), feats_regions()),
    "services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer/17":
        (esri_layer_meta("CoastalFloodLayersARI100", "esriGeometryPolygon", [("NAME", "esriFieldTypeString"), ("OBJECTID", "esriFieldTypeOID")], "JSON, geoJSON"), feats_polys(230)),
    "gis.niwa.co.nz/arcgis/rest/services/HYDRO/Flood_Statistics_Henderson_Collins_V2/MapServer/0":
        (esri_layer_meta("Flood stats", "esriGeometryPolyline", [("NZREACH", "esriFieldTypeInteger"), ("OBJECTID", "esriFieldTypeOID"), ("Data_100y", "esriFieldTypeDouble"), ("Data_50y", "esriFieldTypeDouble"), ("Region", "esriFieldTypeString")], "JSON", 100), feats_lines(120)),
}
SERVICES = {
    "services3.arcgis.com/fp1tibNcN9mbExhG/ArcGIS/rest/services/CoastalFloodLayersARI100/FeatureServer": [{"id": 17, "name": "CoastalFloodLayersARI100"}],
    "gis.niwa.co.nz/arcgis/rest/services/HYDRO/Flood_Statistics_Henderson_Collins_V2/MapServer": [{"id": 0, "name": "Flood stats"}],
}


def fdsn_text(limit, bbox, minmag):
    now = datetime.now(timezone.utc)
    rows = ["#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName"]
    for i, (x, y) in enumerate(pts(120, 9)):
        if bbox and not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
            continue
        t = (now - timedelta(days=30 * i + 1)).strftime("%Y-%m-%dT%H:%M:%S.000000")
        rows.append(f"2020p{i:06d}|{t}|{y:.4f}|{x:.4f}|{5 + i % 40}.0|AUTH|GNS|GNS|c{i}|{'ML' if i % 3 else 'Mw'}|{5.0 + (i % 20) / 10:.2f}|a|Somewhere {i}")
    if limit:
        rows = rows[:limit + 1]
    return "\n".join(rows) if len(rows) > 1 else ""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj=None, text=None, code=200):
        b = (text if text is not None else json.dumps(obj)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain" if text is not None else "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.lstrip("/")
        if p == "service.geonet.org.nz/fdsnws/event/1/query":
            bbox = [float(q[k]) for k in ("minlongitude", "minlatitude", "maxlongitude", "maxlatitude")] if "minlongitude" in q else None
            t = fdsn_text(int(q["limit"]) if "limit" in q else None, bbox, float(q.get("minmagnitude", 0)))
            return self.send(text=t, code=200 if t else 204)
        if p == "api.geonet.org.nz/quake":
            now = datetime.now(timezone.utc)
            fs = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
                   "properties": {"publicID": f"2026p{i}", "time": (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "depth": 10 + i, "magnitude": 3 + i / 10, "mmi": i % 5 - 0 if i % 9 else -1, "locality": f"loc {i}", "quality": "best"}}
                  for i, (x, y) in enumerate(pts(30, 2))]
            return self.send({"type": "FeatureCollection", "features": fs})
        if p == "api.gbif.org/v1/species/match":
            return self.send({"usageKey": 4242, "matchType": "EXACT", "rank": "FAMILY", "canonicalName": q.get("name")})
        if p == "api.gbif.org/v1/occurrence/search":
            allr = []
            for i, (x, y) in enumerate(pts(650, 4)):
                allr.append({"gbifID": str(1000 + i), "scientificName": "Galaxias test", "decimalLatitude": y, "decimalLongitude": x,
                             "coordinateUncertaintyInMeters": None if i % 4 == 0 else 50.0 * (i % 300), "eventDate": f"{1980 + i % 40}-05-0{1 + i % 9}",
                             "year": 1980 + i % 40, "basisOfRecord": "HUMAN_OBSERVATION", "datasetKey": f"ds{i % 3}", "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
                             "countryCode": "NZ", "issues": ["COORDINATE_ROUNDED"] if i % 10 == 0 else []})
            if "geometry" in q:
                nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", q["geometry"])]
                xs, ys = nums[0::2], nums[1::2]
                allr = [r for r in allr if min(xs) <= r["decimalLongitude"] <= max(xs) and min(ys) <= r["decimalLatitude"] <= max(ys)]
            lim, off = int(q.get("limit", 20)), int(q.get("offset", 0))
            return self.send({"count": len(allr), "offset": off, "limit": lim, "endOfRecords": off + lim >= len(allr), "results": allr[off:off + lim]})
        # ArcGIS
        base = p
        for key in list(SERVICES) + list(LAYERS):
            if p == key or p == key + "/query":
                base = key
        if p in SERVICES:
            return self.send({"currentVersion": 11.1, "layers": SERVICES[p]})
        if base in LAYERS:
            meta, feats = LAYERS[base]
            if p == base:
                return self.send(meta)
            if q.get("returnCountOnly") == "true":
                return self.send({"count": len(feats)})
            if q.get("returnIdsOnly") == "true":
                return self.send({"objectIds": [f["attributes"]["OBJECTID"] for f in feats]})
            off, n = int(q.get("resultOffset", 0)), int(q.get("resultRecordCount", meta["maxRecordCount"]))
            n = min(n, meta["maxRecordCount"])
            sel = feats[off:off + n]
            if q.get("f") == "geojson":
                if "geoJSON" not in meta["supportedQueryFormats"]:
                    return self.send({"error": {"code": 400, "message": "f=geojson unsupported"}})
                return self.send(to_geojson(sel, meta["geometryType"]))
            return self.send({"features": sel, "exceededTransferLimit": off + n < len(feats)})
        self.send({"error": "not mocked: " + p}, 404)


def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


HOSTS = ["service.geonet.org.nz", "api.geonet.org.nz", "api.gbif.org", "services2.arcgis.com", "services3.arcgis.com", "gis.niwa.co.nz"]


def overrides(port):
    return {f"https://{h}": f"http://127.0.0.1:{port}/{h}" for h in HOSTS}
