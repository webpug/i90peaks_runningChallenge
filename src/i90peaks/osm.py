"""OSM trails and drivable roads for the corridor (one Overpass query each).

trails: highway=path|footway|track|bridleway|steps (anything you can run on)
roads:  public drivable roads -- possible trailhead/approach start points
"""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from . import config
from .highway import overpass

TRAILS_GPKG = config.INTERIM / "osm_trails.gpkg"
ROADS_GPKG = config.INTERIM / "osm_roads.gpkg"
_ROAD_TYPES = "motorway_link|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street"


def _fetch(selector: str, out_path, overwrite=False) -> gpd.GeoDataFrame:
    if out_path.exists() and not overwrite:
        return gpd.read_file(out_path)
    w, s, e, n = config.BBOX
    elems = overpass(f'way{selector}({s},{w},{n},{e});out tags geom;', timeout=600)
    rows = [{"highway": el["tags"].get("highway"), "name": el["tags"].get("name"),
             "access": el["tags"].get("access"),
             "geometry": LineString([(p["lon"], p["lat"]) for p in el["geometry"]])}
            for el in elems if len(el.get("geometry", [])) > 1]
    g = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    g.to_file(out_path, driver="GPKG")
    print(f"[osm] {len(g)} ways -> {out_path}")
    return g


def trails(overwrite=False):
    return _fetch('["highway"~"^(path|footway|track|bridleway|steps)$"]', TRAILS_GPKG, overwrite)


def roads(overwrite=False):
    g = _fetch(f'["highway"~"^({_ROAD_TYPES})$"]', ROADS_GPKG, overwrite)
    return g[~g["access"].isin(["private", "no"])]
