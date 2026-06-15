"""First-ridgeline classification via drainage analysis.

"First row" = the first ridgeline(s) rising from I-90. We compute the catchment
that drains to the highway, then a peak is on the front ridge iff it straddles
that catchment's divide: some terrain around the summit drains TO I-90 and some
drains AWAY. Peaks whose every side drains away are behind the crest (occluded);
peaks buried inside the catchment (all sides drain to I-90) are interior, not on
the front ridgeline.

Pipeline: richdem depression-fill (epsilon) -> D8 steepest-descent receiver ->
mark cells whose downstream path reaches I-90 (path-doubling) -> per-peak divide test.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
import richdem as rd
from rasterio.features import rasterize

from . import config

_DIRS = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
         (-1, -1, 1.41421356), (-1, 1, 1.41421356),
         (1, -1, 1.41421356), (1, 1, 1.41421356)]


def _d8_receiver(fill: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Index of each cell's steepest-descent neighbour; off-grid/invalid -> self."""
    R, C = fill.shape
    N = R * C
    P = np.full((R + 2, C + 2), -np.inf, dtype=np.float64)   # -inf border = drains off grid
    P[1:-1, 1:-1] = np.where(valid, fill, -np.inf)
    idx = np.arange(N).reshape(R, C)
    recv = idx.copy()
    best = np.zeros((R, C), dtype=np.float64)
    center = P[1:-1, 1:-1]
    for dr, dc, dist in _DIRS:
        neigh = P[1 + dr:R + 1 + dr, 1 + dc:C + 1 + dc]
        drop = (center - neigh) / dist
        sel = drop > best
        nbr_idx = idx + dr * C + dc
        ok = np.ones((R, C), dtype=bool)
        if dr == -1: ok[0, :] = False
        if dr == 1:  ok[-1, :] = False
        if dc == -1: ok[:, 0] = False
        if dc == 1:  ok[:, -1] = False
        chosen = np.where(ok, nbr_idx, -1)
        recv[sel] = chosen[sel]
        best[sel] = drop[sel]
    recv = recv.ravel()
    self_idx = np.arange(N)
    recv = np.where(recv < 0, self_idx, recv)          # off-grid -> sink (self)
    recv[~valid.ravel()] = self_idx[~valid.ravel()]
    return recv


def _reaches(seed_flat: np.ndarray, recv: np.ndarray, max_doublings: int = 24) -> np.ndarray:
    """Cells whose downstream (receiver) path passes through a seed cell."""
    rch = seed_flat.copy()
    Rr = recv.copy()
    for _ in range(max_doublings):
        nxt = rch | rch[Rr]
        if np.array_equal(nxt, rch):
            break
        rch = nxt
        Rr = Rr[Rr]
    return rch


def compute_catchment(dem_path=config.DEM_TIF, highway=None, save=True):
    from . import highway as hw_mod
    highway = highway if highway is not None else hw_mod.fetch_i90()
    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float64)
        nodata = float(dem.nodata)
        prof = dem.profile
        hw = highway.to_crs(dem.crs)
        hw_mask = rasterize(((g, 1) for g in hw.geometry), out_shape=(dem.height, dem.width),
                            transform=dem.transform, fill=0, all_touched=True, dtype="uint8").astype(bool)
    valid = elev != nodata

    import contextlib, os
    rda = rd.rdarray(elev, no_data=nodata)
    with contextlib.redirect_stderr(open(os.devnull, "w")):
        rd.FillDepressions(rda, epsilon=True, in_place=True)
    fill = np.asarray(rda, dtype=np.float64)

    with np.errstate(invalid="ignore"):  # -inf - -inf at the padded border
        recv = _d8_receiver(fill, valid)
    catch = _reaches(hw_mask.ravel() & valid.ravel(), recv).reshape(elev.shape)
    catch &= valid

    if save:
        prof.update(dtype="uint8", nodata=255, count=1, compress="deflate")
        with rasterio.open(config.INTERIM / "i90_catchment.tif", "w", **prof) as dst:
            dst.write(catch.astype("uint8"), 1)
    return catch, valid


def classify(dem_path=config.DEM_TIF, highway=None, peaks=None,
             divide_radius_px: int = 5):
    from . import highway as hw_mod, peaks as pk_mod, frontrow
    highway = highway if highway is not None else hw_mod.fetch_i90()
    peaks = peaks if peaks is not None else pk_mod.load_corridor_peaks()

    catch, valid = compute_catchment(dem_path, highway)
    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        srow, scol = frontrow._snap_summits(peaks, elev, dem)
    nrows, ncols = catch.shape

    drains, on_divide = [], []
    r = divide_radius_px
    for rr, cc in zip(srow, scol):
        r0, r1 = max(0, rr - r), min(nrows, rr + r + 1)
        c0, c1 = max(0, cc - r), min(ncols, cc + r + 1)
        cwin = catch[r0:r1, c0:c1]
        vwin = valid[r0:r1, c0:c1]
        n_in = int(cwin.sum())
        n_out = int((vwin & ~cwin).sum())
        drains.append(n_in > 0)
        on_divide.append(n_in > 0 and n_out > 0)

    peaks = peaks.copy()
    peaks["drains_to_i90"] = drains
    peaks["on_divide"] = on_divide                # NOTE: this is the catchment's OUTER
                                                  # rim (far Cascade crest), not the
                                                  # roadside front -- diagnostic only.
    # First row = the peak is on I-90's side of every divide => no ridge between it and
    # the highway (honors "regardless of distance"); behind-the-crest peaks excluded.
    peaks["frontrow"] = peaks["drains_to_i90"]

    n_fr = int(peaks["frontrow"].sum())
    print(f"[watershed] {len(peaks)} peaks -> {n_fr} FIRST ROW (drain to I-90), "
          f"{len(peaks)-n_fr} behind the crest")
    return peaks


if __name__ == "__main__":
    res = classify()
    res.to_file(config.RESULT_GPKG, driver="GPKG")
    print(f"[watershed] wrote {config.RESULT_GPKG}")
