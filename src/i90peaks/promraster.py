"""Prominence islands: the map's prominence raster.

A peak's prominence island is the ground connected to its summit that stands
above its key col (summit elevation - prominence). Walk off the island in any
direction and you have dropped the full prominence. Islands nest (a small peak's
island lies inside the island of the bigger peak it hangs off), so each cell is
assigned to the innermost island containing it, i.e. the least prominent peak
that "owns" it. Ground outside every island (valley floors below all key cols)
is left empty.

The raster is written as an index PNG: each pixel's RGB holds (peak index + 1) as
r*65536 + g*256 + b, 0 = no island, where the peak index is the row of the
classified table (= the map's feature id). The map colours it by prominence in
the browser and reads it back on hover, so one file gives both the picture and
"whose ground is this". It is aligned to the DEM's Web Mercator grid, which is
what Leaflet's imageOverlay expects.
"""
from __future__ import annotations

import json

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from scipy import ndimage

from . import config

OUT_PNG = config.PROCESSED / "prominence.png"
OUT_JSON = config.PROCESSED / "prominence.json"   # bounds + size for the map
STEP = 2              # export every 2nd DEM cell (~76 m) to keep the PNG small
EIGHT = np.ones((3, 3), dtype=bool)


def _island(elev, r, c, col_m):
    """Cells connected to (r, c) above col_m, labelled in a window grown until the
    island no longer touches a window edge that is not the DEM edge."""
    nr, nc = elev.shape
    half = 48
    while True:
        r0, r1 = max(0, r - half), min(nr, r + half + 1)
        c0, c1 = max(0, c - half), min(nc, c + half + 1)
        lab, _ = ndimage.label(elev[r0:r1, c0:c1] > col_m, structure=EIGHT)
        comp = lab == lab[r - r0, c - c0]
        clipped = ((r0 > 0 and comp[0].any()) or (r1 < nr and comp[-1].any()) or
                   (c0 > 0 and comp[:, 0].any()) or (c1 < nc and comp[:, -1].any()))
        if not clipped:
            return (r0, c0), comp
        half *= 2


def build(classified, dem_path=config.DEM_TIF):
    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        transform, crs, bounds = dem.transform, dem.crs, dem.bounds
    to_dem = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    owner = np.zeros(elev.shape, dtype=np.int32)
    # biggest first, so nested (smaller) islands overwrite the ones they sit in
    order = classified.reset_index(drop=True).sort_values("prom_ft", ascending=False)
    n = 0
    for i, p in order.iterrows():
        if p.get("frame_limited"):      # Rainier: its "island" is the whole frame
            continue
        x, y = to_dem.transform(p.lon, p.lat)
        r, c = rasterio.transform.rowcol(transform, x, y)
        col_m = float(elev[r, c]) - float(p.prom_ft) * 0.3048
        (r0, c0), comp = _island(elev, r, c, col_m)
        owner[r0:r0 + comp.shape[0], c0:c0 + comp.shape[1]][comp] = i + 1
        n += 1

    small = owner[::STEP, ::STEP]
    rgb = np.stack([(small >> 16) & 255, (small >> 8) & 255, small & 255], axis=-1).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(OUT_PNG, optimize=True)

    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    w, s = to_wgs.transform(bounds.left, bounds.bottom)
    e, nn = to_wgs.transform(bounds.right, bounds.top)
    meta = {"bounds": [[s, w], [nn, e]], "size": [small.shape[1], small.shape[0]]}
    OUT_JSON.write_text(json.dumps(meta))
    print(f"[promraster] {n} islands, {(small > 0).mean():.0%} of the frame covered -> "
          f"{OUT_PNG} ({OUT_PNG.stat().st_size / 1e6:.1f} MB)")
    return meta


def load_meta():
    return json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else None
