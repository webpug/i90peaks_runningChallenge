"""Project-wide configuration: corridor extent, thresholds, paths.

The corridor is I-90 from Seattle west to the Columbia River crossing at
Vantage, WA. The analysis *frame* (the DEM bounding box) is padded north and
south of the highway so that whole drainage basins reaching the road are
captured -- there is intentionally NO horizontal distance cap on what counts as
"first row"; adjacency is decided purely by terrain topology.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------
# Analysis bounding box (WGS84 lon/lat). Padded N/S of I-90 to enclose basins.
#   West  : Seattle / I-90 western terminus
#   East  : just past the Columbia River crossing at Vantage (~ -119.99)
#   South/North: wide enough to hold the basins that drain to the highway
WEST, SOUTH, EAST, NORTH = -122.40, 46.75, -119.80, 47.75
BBOX = (WEST, SOUTH, EAST, NORTH)  # (left, bottom, right, top)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
PROM_MIN_FT = 250.0          # minimum topographic prominence to consider a peak
PROM_MIN_M = PROM_MIN_FT * 0.3048

# How far from a peak (in DEM cells) to search for the true local-max cell when
# snapping a Kirmse coordinate onto our DEM grid.
SUMMIT_SNAP_RADIUS_PX = 3

# Buffer (meters) around the I-90 centerline used to seed "highway" DEM cells.
HIGHWAY_SEED_BUFFER_M = 40.0

# ---------------------------------------------------------------------------
# DEM source (AWS Terrain Tiles -- terrarium PNG, global, no API key)
# Ground resolution ~= 156543 * cos(lat) / 2**zoom meters/px.
#   zoom 12 ~= 26 m/px at lat 47   (good detail, ~24M cells for this frame)
#   zoom 11 ~= 52 m/px             (fast, plenty to resolve 250ft-prom ridges)
# ---------------------------------------------------------------------------
DEM_ZOOM = 12
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
# Terrarium occasionally serves blank/white tiles that decode to 32767 m. Anything
# above this (Rainier is 4392 m, the regional max) is masked as nodata.
MAX_PLAUSIBLE_ELEV_M = 4500.0

# ---------------------------------------------------------------------------
# Kirmse global prominence dataset (Google Drive). One peak per line:
#   lat, lon, elevation_ft, key_saddle_lat, key_saddle_lon, prominence_ft
# ---------------------------------------------------------------------------
KIRMSE_DRIVE_ID = "0B3icWNhBosDXZmlEWldSLWVGOE0"
KIRMSE_RESOURCE_KEY = "0-TZC_OGOqI5TFdfPE77Yl3g"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
for _d in (RAW, INTERIM, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

# Cached artifacts
DEM_TIF = INTERIM / f"dem_z{DEM_ZOOM}.tif"
KIRMSE_RAW = RAW / "kirmse_world_prominence.txt"
PEAKS_CORRIDOR = INTERIM / "peaks_corridor.gpkg"     # filtered to bbox + prom
HIGHWAY_GPKG = INTERIM / "i90_centerline.gpkg"
RESULT_GPKG = PROCESSED / "peaks_classified.gpkg"    # front-row vs occluded
RESULT_MAP = PROCESSED / "i90_frontrow_map.html"
