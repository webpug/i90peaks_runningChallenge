"""Compute peaks and their topographic prominence directly from the DEM.

Method: topological persistence via a *descending* union-find sweep -- the
standard prominence algorithm (Kirmse/Ferranti use the same idea).

    Process cells from highest to lowest. Each new local maximum opens a
    "component" whose summit is that cell. When a cell touches two or more
    existing components it is a SADDLE: every component except the one with the
    highest summit dies there, and
            prominence(dead peak) = elev(dead peak) - elev(saddle).
    The highest summit survives and absorbs the others. The final survivor in
    each connected region is the regional high point; its prominence is measured
    to the lowest point of the frame (reported, but flagged as frame-limited).

This yields, for *our* terrain at *our* resolution, the full peak list with
prominence + key-saddle location -- which we then filter to >= PROM_MIN and
cross-check against the Kirmse download.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from numba import njit
from shapely.geometry import Point

from . import config

M_PER_FT = 0.3048


@njit(cache=True)
def _find(parent, i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


@njit(cache=True)
def _sweep(elev_flat, valid_flat, order, ncols, eight):
    """Descending union-find over the activation order (numba-compiled)."""
    N = elev_flat.size
    parent = np.arange(N).astype(np.int64)
    activated = np.zeros(N, dtype=np.bool_)
    comp_peak = np.zeros(N, dtype=np.int64)        # root -> summit cell
    comp_pelev = np.full(N, -np.inf, np.float32)   # root -> summit elevation
    is_peak = np.zeros(N, dtype=np.bool_)
    prom = np.full(N, np.nan, dtype=np.float64)    # indexed by summit cell
    saddle_cell = np.full(N, -1, dtype=np.int64)
    dr = np.array([-1, 1, 0, 0, -1, -1, 1, 1])
    dc = np.array([0, 0, -1, 1, -1, 1, -1, 1])
    nn = 8 if eight else 4
    roots = np.empty(8, dtype=np.int64)
    for k in range(order.size):
        idx = order[k]
        e = elev_flat[idx]
        r, c = idx // ncols, idx % ncols
        activated[idx] = True
        nr = 0
        for j in range(nn):
            rr, cc = r + dr[j], c + dc[j]
            if rr < 0 or cc < 0 or cc >= ncols or rr * ncols + cc >= N:
                continue
            nb = rr * ncols + cc
            if valid_flat[nb] and activated[nb]:
                rt = _find(parent, nb)
                dup = False
                for q in range(nr):
                    if roots[q] == rt:
                        dup = True
                if not dup:
                    roots[nr] = rt
                    nr += 1
        if nr == 0:                       # brand new local maximum -> a peak
            comp_peak[idx] = idx
            comp_pelev[idx] = e
            is_peak[idx] = True
            continue
        winner = roots[0]                 # join the highest-summit neighbour
        for q in range(1, nr):
            if comp_pelev[roots[q]] > comp_pelev[winner]:
                winner = roots[q]
        parent[idx] = winner
        for q in range(nr):
            rt = roots[q]
            if rt == winner:
                continue
            pk = comp_peak[rt]
            prom[pk] = comp_pelev[rt] - e     # dies at this saddle
            saddle_cell[pk] = idx
            parent[rt] = winner
    return is_peak, prom, saddle_cell, comp_pelev


def compute_peaks(dem_path=config.DEM_TIF, prom_min_m=config.PROM_MIN_M,
                  connectivity: int = 8, overwrite: bool = False) -> gpd.GeoDataFrame:
    out = config.INTERIM / f"peaks_computed_p{prom_min_m / M_PER_FT:.0f}.gpkg"
    if out.exists() and not overwrite:
        print(f"[prominence] cached: {out}")
        return gpd.read_file(out)

    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        nodata = dem.nodata
        transform = dem.transform
        crs = dem.crs
        nrows, ncols = elev.shape

    N = elev.size
    elev_flat = elev.ravel()
    valid_flat = np.ones(N, dtype=bool)
    if nodata is not None:
        valid_flat &= elev_flat != nodata
    frame_min = float(elev_flat[valid_flat].min())

    # Descending activation order.
    sort_key = np.where(valid_flat, elev_flat, -np.inf)
    order = np.argsort(sort_key, kind="stable")[::-1]
    n_valid = int(valid_flat.sum())
    order = order[:n_valid]

    is_peak, prom, saddle_cell, comp_pelev = _sweep(
        elev_flat, valid_flat, order.astype(np.int64), ncols, connectivity == 8)

    # Regional survivors: peaks that never died -> measure to frame floor.
    peak_cells = np.flatnonzero(is_peak)
    survivor = peak_cells[np.isnan(prom[peak_cells])]
    prom[survivor] = comp_pelev[survivor] - frame_min
    frame_limited = np.zeros(N, dtype=bool)
    frame_limited[survivor] = True

    # Keep peaks above threshold.
    keep = peak_cells[prom[peak_cells] >= prom_min_m]
    rows = (keep // ncols).astype(np.int64)
    cols = (keep % ncols).astype(np.int64)
    # cell-center coords in DEM crs -> lon/lat
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon, lat = to_wgs.transform(np.asarray(xs), np.asarray(ys))

    sad = saddle_cell[keep]
    has_sad = sad >= 0
    s_lon = np.full(len(keep), np.nan); s_lat = np.full(len(keep), np.nan)
    if has_sad.any():
        sr = (sad[has_sad] // ncols); sc = (sad[has_sad] % ncols)
        sx, sy = rasterio.transform.xy(transform, sr, sc)
        slon, slat = to_wgs.transform(np.asarray(sx), np.asarray(sy))
        s_lon[has_sad] = slon; s_lat[has_sad] = slat

    prom_m = prom[keep]
    df = pd.DataFrame({
        "lat": lat, "lon": lon,
        "elev_m": elev_flat[keep], "elev_ft": elev_flat[keep] / M_PER_FT,
        "prom_m": prom_m, "prom_ft": prom_m / M_PER_FT,
        "saddle_lat": s_lat, "saddle_lon": s_lon,
        "frame_limited": frame_limited[keep],
    })
    gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)],
                           crs="EPSG:4326")
    gdf = gdf.sort_values("prom_ft", ascending=False).reset_index(drop=True)
    gdf["peak_id"] = gdf.index
    gdf.to_file(out, driver="GPKG")
    print(f"[prominence] {len(gdf)} peaks >= {prom_min_m/M_PER_FT:.0f} ft prom "
          f"computed at our resolution -> {out}")
    return gdf


if __name__ == "__main__":
    compute_peaks()
