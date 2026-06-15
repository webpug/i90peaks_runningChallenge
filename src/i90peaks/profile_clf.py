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

`classify` also returns, per peak, the data needed to *show* this reasoning in the web
app: the approach line, the sampled elevation profile, and the blocking ridge location.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Geod, Transformer
from scipy.spatial import cKDTree

from . import config, frontrow

TOL_M = config.PROM_MIN_M   # a "barrier" only counts if it's >= the 250 ft criterion
_GEOD = Geod(ellps="WGS84")
_MAX_PROFILE_PTS = 80       # downsample embedded profiles for the web app


def _sample_profile(elev, transform, x0, y0, x1, y1, step_px, nodata):
    inv = ~transform
    c0, r0 = inv * (x0, y0)
    c1, r1 = inv * (x1, y1)
    n = max(2, int(np.hypot(c1 - c0, r1 - r0) / step_px) + 1)
    cc = np.clip(np.linspace(c0, c1, n).astype(int), 0, elev.shape[1] - 1)
    rr = np.clip(np.linspace(r0, r1, n).astype(int), 0, elev.shape[0] - 1)
    prof = elev[rr, cc].astype(np.float64)
    if nodata is not None:
        prof[prof == nodata] = np.nan
    return prof


def _analyze(prof, tol):
    """Return (blocked, lo_idx, barrier_idx). barrier_idx = the low point of the
    deepest qualifying dip after the valley floor; -1 if none (first row)."""
    good = np.isfinite(prof)
    if good.sum() < 2:
        return True, 0, -1
    lo = int(np.nanargmin(prof))
    climb = prof[lo:]
    running_max = np.fmax.accumulate(np.where(np.isfinite(climb), climb, -np.inf))
    deficit = running_max - climb           # how far below the running high we are
    deficit[~np.isfinite(climb)] = 0
    blocked = bool(np.nanmax(deficit) >= tol)
    barrier = lo + int(np.nanargmax(deficit)) if blocked else -1
    return blocked, lo, barrier


def _candidate_points(highway, crs, step_m=200.0):
    """Sample points every step_m along I-90 (so we can try several approaches)."""
    hw = highway.to_crs(crs)
    pts = []
    for geom in hw.geometry:
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for ln in lines:
            d, L = 0.0, ln.length
            while d < L:
                p = ln.interpolate(d); pts.append((p.x, p.y)); d += step_m
            x, y = ln.coords[-1][0], ln.coords[-1][1]
            pts.append((x, y))
    return np.asarray(pts)


def classify(dem_path=config.DEM_TIF, highway=None, peaks=None, tol_m: float = TOL_M,
             n_candidates: int = 30, with_detail: bool = True):
    """A peak is first row iff *some* nearby point on I-90 has a clear straight-line
    approach (no >= tol_m ridge between). We test the n_candidates nearest I-90 points
    so a peak that faces the road across a lake/valley isn't wrongly blocked by the
    single closest point's line clipping a side ridge.
    """
    from . import highway as hw_mod, peaks as pk_mod
    highway = highway if highway is not None else hw_mod.fetch_i90()
    peaks = peaks if peaks is not None else pk_mod.load_corridor_peaks()

    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        nodata = dem.nodata
        transform = dem.transform
        crs = dem.crs
        srow, scol = frontrow._snap_summits(peaks, elev, dem)

    pk = peaks.to_crs(crs)
    sx, sy = rasterio.transform.xy(transform, srow, scol)
    sx = np.asarray(sx); sy = np.asarray(sy)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    cand = _candidate_points(highway, crs)
    tree = cKDTree(cand)
    K = min(n_candidates, len(cand))
    _, nn = tree.query(np.column_stack([pk.geometry.x.values, pk.geometry.y.values]), k=K)
    if K == 1:
        nn = nn[:, None]

    flags, details = [], []
    for i in range(len(pk)):
        nearest = best = None      # (length, prof, lo, barrier, blocked, hx, hy)
        for j in nn[i]:
            hx, hy = cand[j]
            prof = _sample_profile(elev, transform, hx, hy, sx[i], sy[i], 1.0, nodata)
            blocked, lo, barrier = _analyze(prof, tol_m)
            length = float(np.hypot(hx - sx[i], hy - sy[i]))
            rec = (length, prof, lo, barrier, blocked, hx, hy)
            if nearest is None:
                nearest = rec                      # nn is distance-sorted -> first is closest
            if not blocked and (best is None or length < best[0]):
                best = rec                         # most direct clear approach
        chosen = best if best is not None else nearest
        flags.append(best is not None)
        if with_detail:
            length, prof, lo, barrier, blocked, hx, hy = chosen
            hlon, hlat = to_wgs.transform(hx, hy)
            slon, slat = to_wgs.transform(sx[i], sy[i])
            length_m = float(_GEOD.line_length([hlon, slon], [hlat, slat]))
            z = prof.copy()
            if z.size > _MAX_PROFILE_PTS:
                idx = np.linspace(0, z.size - 1, _MAX_PROFILE_PTS).astype(int)
                z = z[idx]
                blocked, lo, barrier = _analyze(z, tol_m)
            details.append({
                "h": [round(hlon, 6), round(hlat, 6)],
                "s": [round(slon, 6), round(slat, 6)],
                "len": round(length_m),
                "z": [None if not np.isfinite(v) else round(float(v)) for v in z],
                "lo": int(lo), "bar": int(barrier), "blk": bool(blocked),
            })

    peaks = peaks.copy()
    peaks["frontrow"] = np.array(flags)
    n_fr = int(peaks["frontrow"].sum())
    print(f"[profile] {len(peaks)} peaks -> {n_fr} FIRST ROW "
          f"(no >= {tol_m/0.3048:.0f} ft ridge between peak and I-90), "
          f"{len(peaks)-n_fr} blocked")
    return (peaks, details) if with_detail else peaks


if __name__ == "__main__":
    res, _ = classify()
    res.to_file(config.RESULT_GPKG, driver="GPKG")
