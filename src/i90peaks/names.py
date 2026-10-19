"""Attach real summit names to our computed peaks via OSM natural=peak."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree

from . import config

_CACHE = config.INTERIM / "osm_peaks.gpkg"


def _osm_peaks(bbox=config.BBOX) -> gpd.GeoDataFrame:
    if _CACHE.exists():
        return gpd.read_file(_CACHE)
    from .highway import overpass
    w, s, e, n = bbox
    elems = overpass(f'node["natural"~"^(peak|hill)$"]["name"]({s},{w},{n},{e});out;')
    out = gpd.GeoDataFrame(
        {"name": [el["tags"]["name"] for el in elems],
         "ele": [el["tags"].get("ele") for el in elems]},
        geometry=gpd.points_from_xy([el["lon"] for el in elems], [el["lat"] for el in elems]),
        crs="EPSG:4326")
    out.to_file(_CACHE, driver="GPKG")
    return out


def attach_names(peaks: gpd.GeoDataFrame, match_radius_m: float = 350.0) -> gpd.GeoDataFrame:
    """Add a `name` column from the nearest OSM peak within match_radius_m."""
    osm = _osm_peaks()
    peaks = peaks.copy()
    if osm.empty:
        peaks["name"] = ""
        return peaks
    pm = peaks.to_crs(32610); om = osm.to_crs(32610)   # true metres (UTM 10N)
    otree = cKDTree(np.column_stack([om.geometry.x, om.geometry.y]))
    dist, idx = otree.query(np.column_stack([pm.geometry.x, pm.geometry.y]), k=1)
    names = om["name"].to_numpy()[idx]
    peaks["name"] = np.where(dist <= match_radius_m, names, "")
    n = int((peaks["name"] != "").sum())
    print(f"[names] matched {n}/{len(peaks)} peaks to OSM names")
    return peaks


if __name__ == "__main__":
    from . import peaks as pk
    g = attach_names(pk.load_corridor_peaks())
    print(g[g.name != ""][["name", "elev_ft", "prom_ft"]].head(20).to_string(index=False))
