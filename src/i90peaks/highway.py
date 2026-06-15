"""Fetch the I-90 centerline within the corridor from OpenStreetMap (osmnx 2.x)."""
from __future__ import annotations

import geopandas as gpd
import osmnx as ox
from shapely.geometry import LineString, MultiLineString

from . import config


def _is_i90(ref) -> bool:
    """OSM `ref` for an Interstate way looks like 'I 90' (may be a ;-list/array)."""
    if ref is None:
        return False
    vals = ref if isinstance(ref, (list, tuple)) else str(ref).split(";")
    return any("90" in str(v) and "I" in str(v).upper() for v in vals)


def fetch_i90(bbox=config.BBOX, out_path=config.HIGHWAY_GPKG, overwrite: bool = False) -> gpd.GeoDataFrame:
    if out_path.exists() and not overwrite:
        print(f"[highway] cached: {out_path}")
        return gpd.read_file(out_path)

    w, s, e, n = bbox
    # osmnx 2.x: bbox is (left, bottom, right, top)
    feats = ox.features_from_bbox(bbox=(w, s, e, n),
                                  tags={"highway": ["motorway", "motorway_link", "trunk"]})
    feats = feats[feats.geometry.type.isin(["LineString", "MultiLineString"])]
    ref_col = feats["ref"] if "ref" in feats.columns else None
    if ref_col is None:
        raise RuntimeError("No 'ref' tags returned; cannot isolate I-90.")
    i90 = feats[ref_col.apply(_is_i90)].copy()
    if i90.empty:
        raise RuntimeError("No I-90 segments found in bbox.")

    # Dissolve all segments into a single (multi)line for clean seeding.
    merged = i90.geometry.union_all()
    if isinstance(merged, LineString):
        merged = MultiLineString([merged])
    out = gpd.GeoDataFrame({"name": ["I-90"]}, geometry=[merged], crs="EPSG:4326")
    out.to_file(out_path, driver="GPKG")
    print(f"[highway] {len(i90)} OSM segments -> {out_path}")
    return out


if __name__ == "__main__":
    fetch_i90()
