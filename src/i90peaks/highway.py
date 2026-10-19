"""Fetch the I-90 centerline within the corridor from OpenStreetMap (Overpass)."""
from __future__ import annotations

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiLineString, box

from . import config

OVERPASS_URLS = ("https://overpass-api.de/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter",
                 "https://maps.mail.ru/osm/tools/overpass/api/interpreter")


def overpass(query: str, timeout: int = 180) -> list[dict]:
    """Run one Overpass QL query (tries a couple of public mirrors)."""
    err = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": f"[out:json][timeout:{timeout}];{query}"},
                              timeout=timeout + 30, headers={"User-Agent": "i90peaks/1.0"})
            r.raise_for_status()
            return r.json()["elements"]
        except Exception as e:      # noqa: BLE001 -- fall through to the next mirror
            err = e
    raise RuntimeError(f"Overpass failed on all mirrors: {err}")


def _is_i90(ref) -> bool:
    """OSM `ref` for an Interstate way looks like 'I 90' (may be a ;-list)."""
    if ref is None:
        return False
    return any(v.strip().upper() == "I 90" for v in str(ref).split(";"))


def fetch_i90(bbox=config.BBOX, out_path=config.HIGHWAY_GPKG, overwrite: bool = False) -> gpd.GeoDataFrame:
    if out_path.exists() and not overwrite:
        print(f"[highway] cached: {out_path}")
        return gpd.read_file(out_path)

    w, s, e, n = bbox
    elems = overpass(f'way["highway"="motorway"]["ref"~"I 90"]({s},{w},{n},{e});out geom;')
    i90 = [LineString([(p["lon"], p["lat"]) for p in el["geometry"]])
           for el in elems if _is_i90(el.get("tags", {}).get("ref"))]
    if not i90:
        raise RuntimeError("No I-90 segments found in bbox.")

    # Dissolve into one (multi)line, clipped at the Columbia (Vantage bridge).
    merged = gpd.GeoSeries(i90, crs="EPSG:4326").union_all().intersection(
        box(w, s, config.COLUMBIA_LON, n))
    if isinstance(merged, LineString):
        merged = MultiLineString([merged])
    elif merged.geom_type == "GeometryCollection":
        merged = MultiLineString([g for g in merged.geoms if g.geom_type == "LineString"])
    out = gpd.GeoDataFrame({"name": ["I-90"]}, geometry=[merged], crs="EPSG:4326")
    out.to_file(out_path, driver="GPKG")
    print(f"[highway] {len(i90)} OSM ways -> {out_path}")
    return out


if __name__ == "__main__":
    fetch_i90()
