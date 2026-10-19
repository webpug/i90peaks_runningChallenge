"""Background art for the theblacks.ai home page (the "etch trail" hero).

Two aligned images of the I-90 corridor, Issaquah -> Snoqualmie Pass:
  etch.png    ordered-dither hillshade in two greys: the resting "etched" layer
  reveal.webp the same hillshade tinted by prominence island (promraster.py),
              which the cursor trail uncovers

    .venv/bin/python scripts/home_background.py ../theblacks.ai/public/home
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.windows import from_bounds
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.i90peaks import config, promraster  # noqa: E402

BBOX = (-122.08, 47.34, -121.36, 47.62)       # lon/lat: Issaquah -> Snoqualmie Pass
WIDTH = 1920
ETCH = ((255, 255, 255), (170, 170, 170))      # paper, ink
UNOWNED = (238, 234, 226)                      # ground outside every island


def hillshade(z, cell, az=315, alt=40):
    dy, dx = np.gradient(z, cell)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    a, b = np.radians(az), np.radians(alt)
    hs = np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect)
    return np.clip(hs, 0, 1)


def main(out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    peaks = gpd.read_file(config.RESULT_GPKG).reset_index(drop=True)
    with rasterio.open(config.DEM_TIF) as dem:
        elev = dem.read(1).astype(np.float32)
        to_dem = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
        x0, y0 = to_dem.transform(BBOX[0], BBOX[1]); x1, y1 = to_dem.transform(BBOX[2], BBOX[3])
        win = from_bounds(x0, y0, x1, y1, dem.transform).round_offsets().round_lengths()
        r0, c0, h, w = int(win.row_off), int(win.col_off), int(win.height), int(win.width)
        transform, cell = dem.transform, dem.res[0]

    # owner of each cell = innermost prominence island (same rule as the map layer)
    owner = np.zeros(elev.shape, dtype=np.int32)
    for i, p in peaks.sort_values("prom_ft", ascending=False).iterrows():
        if p.frame_limited:
            continue
        r, c = rasterio.transform.rowcol(transform, *to_dem.transform(p.lon, p.lat))
        if not (r0 - 2000 < r < r0 + h + 2000 and c0 - 2000 < c < c0 + w + 2000):
            continue
        col_m = float(elev[r, c]) - float(p.prom_ft) * 0.3048
        (a, b), comp = promraster._island(elev, r, c, col_m)
        owner[a:a + comp.shape[0], b:b + comp.shape[1]][comp] = i + 1
    z, own = elev[r0:r0 + h, c0:c0 + w], owner[r0:r0 + h, c0:c0 + w]

    scale = WIDTH / w
    H = round(h * scale)
    z = ndimage.zoom(z, scale, order=1)[:H, :WIDTH]
    own = ndimage.zoom(own, scale, order=0)[:H, :WIDTH]
    hs = hillshade(z, cell / scale)

    # etch: 8x8 Bayer ordered dither of the hillshade (darker ground -> more ink)
    bayer = np.array([[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
                      [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
                      [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
                      [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]) / 64
    thr = np.tile(bayer, (H // 8 + 1, WIDTH // 8 + 1))[:H, :WIDTH]
    ink = np.clip((0.82 - hs) * 1.6, 0, 1) > thr
    etch = np.where(ink[..., None], ETCH[1], ETCH[0]).astype(np.uint8)
    Image.fromarray(etch).convert("L").save(out / "etch.png", optimize=True)

    # reveal: prominence palette (as on the map), shaded
    stops = np.array([250, 400, 600, 1000, 2000, 4000])
    pal = np.array([(252, 253, 191), (254, 176, 120), (241, 96, 93), (182, 54, 121),
                    (114, 31, 129), (44, 17, 95)], dtype=np.float32)
    prom = np.r_[0, peaks.prom_ft.values][own]
    col = pal[np.clip(np.searchsorted(stops, prom, side="right") - 1, 0, 5)]
    col[own == 0] = UNOWNED
    shade = (0.45 + 0.75 * hs)[..., None]
    Image.fromarray(np.clip(col * shade, 0, 255).astype(np.uint8)).save(out / "reveal.webp", quality=82)
    print(f"{WIDTH}x{H} -> {out}/etch.png ({(out / 'etch.png').stat().st_size / 1e3:.0f} kB), "
          f"reveal.webp ({(out / 'reveal.webp').stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else config.PROCESSED / "home")
