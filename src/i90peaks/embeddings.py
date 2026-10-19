"""AlphaEarth Foundations (AEF) satellite embeddings for the corridor.

Same data as Earth Engine's GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL (used by the
alpha_earth_embeddings_demo notebook): a 64-d unit-length vector per 10 m pixel
summarising a year of optical, radar, LiDAR, climate and elevation inputs. We
read the public Source Cooperative COG mirror (no Earth Engine account needed,
and no track coordinates are sent anywhere -- only tile byte ranges are fetched).

`build_mosaic` resamples the corridor (I-90 +/- BUFFER_M) to a local int8 GeoTIFF
at RES_M using the COG overviews; `sample` de-quantises vectors at points.

De-quantisation (from the dataset README):  v = (q / 127.5)**2 * sign(q),
q = -128 is nodata.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.windows import Window

from . import config

AEF_INDEX_URL = "https://data.source.coop/tge-labs/aef/v1/annual/aef_index.parquet"
AEF_DIR = config.RAW / "aef"
YEAR = 2025
RES_M = 40.0            # COG overview level 1 (4 x 10 m)
BUFFER_M = 15000.0
CRS = "EPSG:32610"
MOSAIC_TIF = config.INTERIM / f"aef_{YEAR}_{int(RES_M)}m.tif"
NODATA = -128

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", str(512 * 1024 * 1024))


def _url(path: str) -> str:
    return "/vsicurl/" + path.replace("s3://us-west-2.opendata.source.coop/",
                                      "https://data.source.coop/")


def corridor_tiles(year=YEAR):
    idx = AEF_DIR / "aef_index.parquet"
    if not idx.exists():
        import requests
        AEF_DIR.mkdir(parents=True, exist_ok=True)
        idx.write_bytes(requests.get(AEF_INDEX_URL, timeout=300).content)
    from shapely.geometry import box
    g = gpd.read_parquet(idx)
    return g[g.intersects(box(*config.BBOX)) & (g.year == year)]


def _target_grid(highway):
    area = highway.to_crs(CRS).buffer(BUFFER_M).union_all()
    x0, y0, x1, y1 = area.bounds
    x0, y0 = np.floor(x0 / RES_M) * RES_M, np.floor(y0 / RES_M) * RES_M
    w, h = int(np.ceil((x1 - x0) / RES_M)), int(np.ceil((y1 - y0) / RES_M))
    return from_origin(x0, y0 + h * RES_M, RES_M, RES_M), w, h


def _read_tile(path, dst_transform, w, h):
    """Reproject one tile (overview matching RES_M) onto the target grid."""
    out = np.full((64, h, w), NODATA, dtype=np.int8)
    level = int(np.log2(RES_M / 10.0)) - 1          # overviews are [2, 4, 8, ...]
    with rasterio.open(_url(path), overview_level=level) as src:
        data = src.read()                           # south-up raster; reproject handles it
        reproject(data, out, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=NODATA, dst_transform=dst_transform, dst_crs=CRS,
                  dst_nodata=NODATA, resampling=Resampling.nearest)
    return out


def build_mosaic(highway, overwrite=False):
    if MOSAIC_TIF.exists() and not overwrite:
        print(f"[aef] cached: {MOSAIC_TIF}")
        return MOSAIC_TIF
    transform, w, h = _target_grid(highway)
    tiles = corridor_tiles()
    print(f"[aef] {len(tiles)} AEF {YEAR} tiles -> {w} x {h} @ {RES_M:.0f} m")
    mosaic = np.full((64, h, w), NODATA, dtype=np.int8)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for part in ex.map(lambda p: _read_tile(p, transform, w, h), tiles.path):
            fill = (mosaic[0] == NODATA) & (part[0] != NODATA)
            mosaic[:, fill] = part[:, fill]
    with rasterio.open(MOSAIC_TIF, "w", driver="GTiff", width=w, height=h, count=64,
                       dtype="int8", crs=CRS, transform=transform, nodata=NODATA,
                       compress="zstd", tiled=True, interleave="pixel") as dst:
        dst.write(mosaic)
    print(f"[aef] wrote {MOSAIC_TIF}")
    return MOSAIC_TIF


class Embeddings:
    """In-memory corridor embeddings; `sample(lon, lat)` -> (n, 64) float32 (nan = nodata)."""

    def __init__(self, path=MOSAIC_TIF):
        with rasterio.open(path) as src:
            self.q = np.moveaxis(src.read(), 0, -1)       # (h, w, 64) int8
            self.inv = ~src.transform
        from pyproj import Transformer
        self.to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)

    def sample(self, lon, lat):
        x, y = self.to_utm.transform(np.asarray(lon), np.asarray(lat))
        c, r = self.inv * (x, y)
        r = np.clip(r.astype(int), 0, self.q.shape[0] - 1)
        c = np.clip(c.astype(int), 0, self.q.shape[1] - 1)
        q = self.q[r, c].astype(np.float32)
        v = (q / 127.5) ** 2 * np.sign(q)
        v[q[:, 0] == NODATA] = np.nan
        return v
