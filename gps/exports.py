"""Export files: GeoJSON for ArcGIS Pro, CSV and XLSX for Excel. Standard library only (a small XLSX writer is included).

Every file is labelled with its format and coordinate system. A file that would exceed the per-file size limit is NOT
written — it is reported instead, so the limit is never silently broken."""
import csv
import json
import os
import zipfile
from xml.sax.saxutils import escape

XLSX_MAX_ROWS = 1048575
LABELS = {"geojson": "GeoJSON (open in ArcGIS Pro: Conversion Tools > JSON To Features)",
          "csv": "CSV table (open in Excel)", "xlsx": "Excel workbook (.xlsx)"}


def _cols(feats):
    cols = []
    seen = set()
    for f in feats[:5000]:
        for k in (f.get("properties") or {}):
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return cols


def _cell(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def table(fc):
    """FeatureCollection -> (header, rows). Points get longitude/latitude columns; lines/polygons are attribute-only
    (their shapes live in the GeoJSON file)."""
    feats = fc.get("features", [])
    cols = _cols(feats)
    has_pts = any((f.get("geometry") or {}).get("type") == "Point" for f in feats[:2000])
    header = (["longitude", "latitude"] if has_pts else []) + cols
    rows = []
    for f in feats:
        g = f.get("geometry") or {}
        xy = g.get("coordinates", ["", ""])[:2] if g.get("type") == "Point" else ["", ""]
        p = f.get("properties") or {}
        rows.append(([xy[0], xy[1]] if has_pts else []) + [_cell(p.get(c, "")) for c in cols])
    return header, rows, has_pts


def write_csv(fc, path):
    header, rows, _ = table(fc)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads UTF-8 (macrons) correctly
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def _col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(fc, path, sheet="data"):
    header, rows, _ = table(fc)
    if len(rows) > XLSX_MAX_ROWS:
        raise ValueError(f"{len(rows):,} rows is more than an Excel sheet can hold ({XLSX_MAX_ROWS:,}); use CSV or GeoJSON instead")

    def cell(r, c, v):
        ref = f"{_col_letter(c)}{r}"
        if v is None or v == "":
            return ""
        if isinstance(v, bool):
            return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'

    def sheet_xml():
        yield ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>')
        yield f'<row r="1">{"".join(cell(1, j, h) for j, h in enumerate(header))}</row>'
        for i, row in enumerate(rows, start=2):
            yield f'<row r="{i}">{"".join(cell(i, j, v) for j, v in enumerate(row))}</row>'
        yield "</sheetData></worksheet>"

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   f'<sheet name="{escape(sheet[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with z.open("xl/worksheets/sheet1.xml", "w") as f:
            for chunk in sheet_xml():
                f.write(chunk.encode("utf-8"))
    return len(rows)


def write_geojson(fc, path, name):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "name": name, "features": fc.get("features", [])}, fh, separators=(",", ":"))
    return len(fc.get("features", []))


def export_dataset(out_dir, d, fc, formats, limit_bytes, crs_note, allow_exceed=False, rel_base=None):
    """Write the chosen formats. Returns (written, skipped); each item describes one file or why it was not made."""
    os.makedirs(out_dir, exist_ok=True)
    written, skipped = [], []
    has_geom = any(f.get("geometry") for f in fc.get("features", [])[:2000])
    for fmt in formats:
        ext = {"geojson": "geojson", "csv": "csv", "xlsx": "xlsx"}[fmt]
        path = os.path.join(out_dir, f"{d}.{ext}")
        if fmt == "geojson" and not has_geom:
            skipped.append({"format": fmt, "reason": "this dataset has no map geometry, so there is nothing to put in a GeoJSON file — use CSV or Excel"})
            continue
        try:
            n = {"geojson": lambda: write_geojson(fc, path, d), "csv": lambda: write_csv(fc, path), "xlsx": lambda: write_xlsx(fc, path, d)}[fmt]()
        except ValueError as e:
            skipped.append({"format": fmt, "reason": str(e)})
            continue
        size = os.path.getsize(path)
        if limit_bytes and size > limit_bytes and not allow_exceed:
            os.remove(path)
            skipped.append({"format": fmt, "reason": f"the {fmt.upper()} file would be {size / 1e6:.0f} MB, over your {limit_bytes / 1e6:.0f} MB per-file limit — "
                                                     "raise the limit in Settings, filter the dataset, or use another format"})
            continue
        crs = crs_note if fmt == "geojson" else ("longitude/latitude columns in WGS84 (EPSG:4326)" if has_geom else "no coordinates")
        written.append({"format": fmt, "label": LABELS[fmt], "file": os.path.relpath(path, rel_base or os.path.dirname(os.path.dirname(out_dir))).replace(os.sep, "/"),
                        "bytes": size, "records": n, "crs": crs})
    return written, skipped
