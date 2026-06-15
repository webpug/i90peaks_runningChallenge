"""First-row classification by the straight-line terrain profile to I-90.

This is the most literal encoding of the rule: a peak is first row iff there is
"no ridge or other peak meeting the 250 ft criterion between it and the highway."

For each peak we take the nearest point H on I-90 and sample the terrain elevation
profile along the straight segment H -> summit. You're allowed to drop from the road
into the valley (the profile's low point), but from that low point the climb to the
summit must never cross a barrier >= TOL below a running high -- i.e. no intervening
ridge/peak as tall as the 250 ft prominence criterion. Distance is irrelevant: a far
peak with a clean rising approach qualifies; a closer peak hidden behind a ridge does
not. Mt Stuart (dozens of qualifying peaks between it and I-90) is excluded; Granite
Mtn (rises straight from the road) qualifies.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio

from . import config, frontrow

TOL_M = config.PROM_MIN_M   # a "barrier" only counts if it's >= the 250 ft criterion


def _profile_blocked(elev, transform, x0, y0, x1, y1, step_px, nodata, tol):
    """True if a qualifying ridge sits between road point (x0,y0) and summit (x1,y1)."""
    inv = ~transform
    c0, r0 = inv * (x0, y0)
    c1, r1 = inv * (x1, y1)
    n = max(2, int(np.hypot(c1 - c0, r1 - r0) / step_px) + 1)
    cc = np.linspace(c0, c1, n).astype(int)
    rr = np.linspace(r0, r1, n).astype(int)
    nr, ncol = elev.shape
    rr = np.clip(rr, 0, nr - 1); cc = np.clip(cc, 0, ncol - 1)
    prof = elev[rr, cc].astype(np.float64)
    if nodata is not None:
        prof = prof[prof != nodata]
    if prof.size < 2:
        return True
    # from the profile's low point, the climb to the summit must not drop >= tol
    lo = int(np.argmin(prof))
    climb = prof[lo:]
    running_max = np.maximum.accumulate(climb)
    return bool(np.any(running_max - climb >= tol))


def classify(dem_path=config.DEM_TIF, highway=None, peaks=None, tol_m: float = TOL_M):
    from . import highway as hw_mod, peaks as pk_mod
    highway = highway if highway is not None else hw_mod.fetch_i90()
    peaks = peaks if peaks is not None else pk_mod.load_corridor_peaks()

    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        nodata = dem.nodata
        transform = dem.transform
        crs = dem.crs
        srow, scol = frontrow._snap_summits(peaks, elev, dem)
        step_px = 1.0

    hw_line = highway.to_crs(crs).geometry.union_all()
    pk = peaks.to_crs(crs)

    # summit coords snapped to the local-max cell (true summit on our grid)
    sx, sy = rasterio.transform.xy(transform, srow, scol)
    sx = np.asarray(sx); sy = np.asarray(sy)

    frontrow_flags = []
    for i, geom in enumerate(pk.geometry):
        H = hw_line.interpolate(hw_line.project(geom))   # nearest point on I-90
        blocked = _profile_blocked(elev, transform, H.x, H.y, sx[i], sy[i],
                                   step_px, nodata, tol_m)
        frontrow_flags.append(not blocked)

    peaks = peaks.copy()
    peaks["frontrow"] = np.array(frontrow_flags)
    n_fr = int(peaks["frontrow"].sum())
    print(f"[profile] {len(peaks)} peaks -> {n_fr} FIRST ROW "
          f"(no >= {tol_m/0.3048:.0f} ft ridge between peak and I-90), "
          f"{len(peaks)-n_fr} blocked")
    return peaks


if __name__ == "__main__":
    res = classify()
    res.to_file(config.RESULT_GPKG, driver="GPKG")
