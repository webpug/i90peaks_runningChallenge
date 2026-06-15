"""Export classified peaks to CalTopo-ingestible formats (GPX, GeoJSON, KML).

CalTopo imports GPX waypoints, GeoJSON, and KML/KMZ directly. GPX waypoints are
the most reliable for summits (each carries name, elevation, and a symbol).
"""
from __future__ import annotations

import html
from xml.sax.saxutils import escape

from . import config

M_PER_FT = 0.3048


def _wpt_name(p) -> str:
    """Prefer a real name if we have one, else a descriptive label."""
    name = p.get("name") if hasattr(p, "get") else None
    if name and str(name) not in ("", "nan", "None"):
        return str(name)
    return f"{p.elev_ft:.0f}ft pk (P{p.prom_ft:.0f})"


def to_gpx(classified, out_path=None, frontrow_only: bool = True) -> str:
    out_path = out_path or (config.PROCESSED / (
        "i90_frontrow_peaks.gpx" if frontrow_only else "i90_all_peaks.gpx"))
    df = classified[classified.frontrow] if frontrow_only else classified
    df = df.sort_values("prom_ft", ascending=False)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="i90peaks" '
             'xmlns="http://www.topografix.com/GPX/1/1">']
    for _, p in df.iterrows():
        ele_m = p.elev_ft * M_PER_FT
        name = escape(_wpt_name(p))
        cmt = escape(f"elev {p.elev_ft:.0f} ft, prominence {p.prom_ft:.0f} ft"
                     + ("" if p.get("frontrow", True) else
                        f", occluded (+{p.get('barrier_above_m', 0):.0f} m barrier)"))
        parts.append(
            f'  <wpt lat="{p.lat:.6f}" lon="{p.lon:.6f}">\n'
            f'    <ele>{ele_m:.1f}</ele>\n'
            f'    <name>{name}</name>\n'
            f'    <cmt>{cmt}</cmt>\n'
            f'    <desc>{cmt}</desc>\n'
            f'    <sym>Summit</sym>\n'
            f'  </wpt>')
    parts.append('</gpx>\n')
    with open(out_path, "w") as fh:
        fh.write("\n".join(parts))
    print(f"[export] {len(df)} waypoints -> {out_path}")
    return str(out_path)


def to_geojson(classified, out_path=None) -> str:
    out_path = out_path or (config.PROCESSED / "i90_peaks.geojson")
    keep = [c for c in ["lat", "lon", "elev_ft", "prom_ft", "frontrow",
                        "barrier_above_m", "name", "geometry"] if c in classified.columns]
    classified[keep].to_file(out_path, driver="GeoJSON")
    print(f"[export] GeoJSON -> {out_path}")
    return str(out_path)


def export_all(classified) -> dict:
    return {
        "gpx_frontrow": to_gpx(classified, frontrow_only=True),
        "gpx_all": to_gpx(classified, frontrow_only=False),
        "geojson": to_geojson(classified),
    }
