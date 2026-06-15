"""Build a seamless DEM for the corridor from AWS Terrain Tiles (terrarium).

Terrarium tiles encode elevation in PNG RGB:
    elevation_m = (R * 256 + G + B / 256) - 32768

They're global, need no API key, and resolution is chosen via the tile zoom.
We mosaic every tile covering the bounding box into one Web-Mercator GeoTIFF.
Horizontal CRS distortion is irrelevant to the front-row topology (it only
compares neighbouring cell elevations), so we keep the native EPSG:3857 grid.
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, as_completed

import mercantile
import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.transform import from_bounds
from tqdm import tqdm

from . import config

_TILE = 256
_NODATA = -32768.0


def _fetch_tile(session: requests.Session, tile: mercantile.Tile) -> tuple[mercantile.Tile, np.ndarray]:
    url = config.TERRARIUM_URL.format(z=tile.z, x=tile.x, y=tile.y)
    for attempt in range(4):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            arr = np.asarray(img, dtype=np.float64)
            elev = (arr[..., 0] * 256.0 + arr[..., 1] + arr[..., 2] / 256.0) - 32768.0
            return tile, elev.astype(np.float32)
        except Exception:
            if attempt == 3:
                raise
    raise RuntimeError("unreachable")


def build_dem(bbox=config.BBOX, zoom=config.DEM_ZOOM, out_path=config.DEM_TIF,
              overwrite: bool = False) -> str:
    """Download + mosaic terrarium tiles covering ``bbox`` into a GeoTIFF."""
    if out_path.exists() and not overwrite:
        print(f"[dem] cached: {out_path}")
        return str(out_path)

    w, s, e, n = bbox
    tiles = list(mercantile.tiles(w, s, e, n, zooms=[zoom]))
    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    ncols = (xmax - xmin + 1) * _TILE
    nrows = (ymax - ymin + 1) * _TILE
    print(f"[dem] {len(tiles)} tiles at z{zoom} -> mosaic {nrows} x {ncols} "
          f"(~{nrows * ncols / 1e6:.1f}M cells)")

    mosaic = np.full((nrows, ncols), _NODATA, dtype=np.float32)
    with requests.Session() as session, ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(_fetch_tile, session, t): t for t in tiles}
        for fut in tqdm(as_completed(futs), total=len(futs), desc="tiles"):
            tile, elev = fut.result()
            r0 = (tile.y - ymin) * _TILE
            c0 = (tile.x - xmin) * _TILE
            mosaic[r0:r0 + _TILE, c0:c0 + _TILE] = elev

    # Mask blank/white tiles (decode to 32767 m) and other impossible spikes.
    bad = int((mosaic > config.MAX_PLAUSIBLE_ELEV_M).sum())
    if bad:
        mosaic[mosaic > config.MAX_PLAUSIBLE_ELEV_M] = _NODATA
        print(f"[dem] masked {bad} implausible cells (>{config.MAX_PLAUSIBLE_ELEV_M:.0f} m)")

    # Geotransform from the mercator bounds of the tile block (3857 meters).
    ul = mercantile.xy_bounds(mercantile.Tile(xmin, ymin, zoom))  # top-left tile
    lr = mercantile.xy_bounds(mercantile.Tile(xmax, ymax, zoom))  # bottom-right tile
    transform = from_bounds(ul.left, lr.bottom, lr.right, ul.top, ncols, nrows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=nrows, width=ncols, count=1,
        dtype="float32", crs="EPSG:3857", transform=transform, nodata=_NODATA,
        compress="deflate", predictor=2, tiled=True,
    ) as dst:
        dst.write(mosaic, 1)
    print(f"[dem] wrote {out_path}")
    return str(out_path)


if __name__ == "__main__":
    build_dem()
