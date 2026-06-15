"""Attach real summit names to our computed peaks via OSM natural=peak."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import osmnx as ox
from scipy.spatial import cKDTree

from . import config

_CACHE = config.INTERIM / "osm_peaks.gpkg"


def _osm_peaks(bbox=config.BBOX) -> gpd.GeoDataFrame:
    if _CACHE.exists():
        return gpd.read_file(_CACHE)
    w, s, e, n = bbox
    feats = ox.features_from_bbox(bbox=(w, s, e, n), tags={"natural": "peak"})
    feats = feats[feats.geometry.type == "Point"]
    cols = [c for c in ["name", "ele", "geometry"] if c in feats.columns]
    out = feats[cols].copy()
    if "name" not in out.columns:
        out["name"] = None
    out = out[out["name"].notna()].reset_index(drop=True)
    out.to_file(_CACHE, driver="GPKG")
    return out


def attach_names(peaks: gpd.GeoDataFrame, match_radius_m: float = 200.0) -> gpd.GeoDataFrame:
    """Add a `name` column from the nearest OSM peak within match_radius_m."""
    osm = _osm_peaks()
    peaks = peaks.copy()
    if osm.empty:
        peaks["name"] = ""
        return peaks
    pm = peaks.to_crs(3857); om = osm.to_crs(3857)
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
