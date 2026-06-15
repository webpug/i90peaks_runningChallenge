"""Classify peaks as 'first row' vs occluded by terrain topology.

Model = TOLERANT MONOTONIC-ASCENT REACHABILITY.

    Stand on I-90 and climb toward a peak. You keep a "high-water mark" = the
    highest elevation you've reached so far. You may step anywhere as long as you
    never drop more than a tolerance T below that high-water mark. The peaks you
    can reach this way are the *first row*.

Why the tolerance: with T = 0 (pure uphill-only), a real DEM is so noisy that
ascent stalls on every minor bench, so almost nothing qualifies. T lets you cross
*insignificant* dips while still being blocked by any ridge taller than T. Setting
T to the prominence threshold (250 ft) means: "you are blocked only by a ridge
that is itself a 250-ft-significant feature" -- exactly the user's rule. A 6,000 ft
peak behind the ridge joining a 5,000/4,000 ft pair stays occluded, because getting
behind that ridge requires dropping far more than 250 ft.

Algorithm: a Dijkstra that, for every cell, finds the *minimum* high-water mark
needed to reach it from I-90 under the tolerance constraint (a lower mark is always
better -- it makes every onward step easier). A peak is first row iff its summit is
reachable (finite mark). The summit's mark - its elevation also tells us how high a
pass the easiest approach crests.
"""
from __future__ import annotations

import heapq

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

from . import config


def _seed_mask_from_highway(highway: gpd.GeoDataFrame, dem) -> np.ndarray:
    hw = highway.to_crs(dem.crs)
    shapes = ((geom, 1) for geom in hw.geometry)
    mask = rasterize(shapes, out_shape=(dem.height, dem.width),
                     transform=dem.transform, fill=0, all_touched=True, dtype="uint8")
    return mask.astype(bool)


def _snap_summits(peaks: gpd.GeoDataFrame, elev: np.ndarray, dem,
                  radius=config.SUMMIT_SNAP_RADIUS_PX):
    """Map each peak lon/lat to the highest DEM cell within `radius` px."""
    pk = peaks.to_crs(dem.crs)
    nrows, ncols = elev.shape
    rows, cols = [], []
    for geom in pk.geometry:
        r, c = dem.index(geom.x, geom.y)
        r = min(max(r, 0), nrows - 1); c = min(max(c, 0), ncols - 1)
        r0, r1 = max(0, r - radius), min(nrows, r + radius + 1)
        c0, c1 = max(0, c - radius), min(ncols, c + radius + 1)
        window = elev[r0:r1, c0:c1]
        dr, dc = np.unravel_index(np.argmax(window), window.shape)
        rows.append(r0 + dr); cols.append(c0 + dc)
    return np.array(rows), np.array(cols)


def _reach_mark(elev_flat, valid_flat, seed_flat, N, ncols, T):
    """Dijkstra: minimum high-water mark to reach each cell under tolerance T.

    From a cell reached with mark h, you may step to neighbour d iff
    elev[d] >= h - T; the new mark is max(h, elev[d]). Unreached cells stay inf.
    """
    hmin = np.full(N, np.inf, dtype=np.float32)
    ev = elev_flat
    heap = []
    for s in np.flatnonzero(seed_flat):
        hmin[s] = ev[s]
        heap.append((float(ev[s]), int(s)))
    heapq.heapify(heap)

    while heap:
        h, idx = heapq.heappop(heap)
        if h > hmin[idx]:
            continue
        c = idx % ncols
        nbrs = ()
        if idx - ncols >= 0:  nbrs += (idx - ncols,)
        if idx + ncols < N:   nbrs += (idx + ncols,)
        if c > 0:             nbrs += (idx - 1,)
        if c < ncols - 1:     nbrs += (idx + 1,)
        thresh = h - T
        for nb in nbrs:
            if not valid_flat[nb]:
                continue
            ed = ev[nb]
            if ed < thresh:
                continue
            cand = h if ed <= h else ed
            if cand < hmin[nb]:
                hmin[nb] = cand
                heapq.heappush(heap, (cand, nb))
    return hmin


def classify(dem_path=config.DEM_TIF, highway=None, peaks=None,
             descent_tol_m: float = config.PROM_MIN_M) -> gpd.GeoDataFrame:
    from . import highway as hw_mod, peaks as pk_mod
    highway = highway if highway is not None else hw_mod.fetch_i90()
    peaks = peaks if peaks is not None else pk_mod.load_corridor_peaks()

    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        nodata = dem.nodata
        seed_mask = _seed_mask_from_highway(highway, dem)
        srow, scol = _snap_summits(peaks, elev, dem)
        nrows, ncols = elev.shape

    N = elev.size
    elev_flat = np.ascontiguousarray(elev.ravel())
    valid_flat = np.ones(N, dtype=bool)
    if nodata is not None:
        valid_flat &= elev_flat != nodata
    seed_flat = seed_mask.ravel() & valid_flat

    hmin = _reach_mark(elev_flat, valid_flat, seed_flat, N, ncols, float(descent_tol_m))

    summit_idx = srow.astype(np.int64) * ncols + scol.astype(np.int64)
    summit_elev = elev_flat[summit_idx]
    summit_mark = hmin[summit_idx]
    peaks = peaks.copy()
    peaks["summit_elev_m"] = summit_elev
    peaks["frontrow"] = np.isfinite(summit_mark)
    # how high above the summit the easiest approach has to crest (0 if you can
    # walk straight up); a useful "how buried" diagnostic for occluded peaks.
    peaks["approach_crest_above_m"] = np.where(
        np.isfinite(summit_mark), summit_mark - summit_elev, np.nan)

    n_fr = int(peaks["frontrow"].sum())
    print(f"[frontrow] {len(peaks)} peaks -> {n_fr} FIRST ROW, "
          f"{len(peaks) - n_fr} occluded (tolerant ascent, T={descent_tol_m:.1f} m)")
    return peaks


if __name__ == "__main__":
    res = classify()
    res.to_file(config.RESULT_GPKG, driver="GPKG")
    print(f"[frontrow] wrote {config.RESULT_GPKG}")
