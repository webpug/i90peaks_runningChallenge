"""First-row classification by *summit caps* and straight approaches from I-90.

The rule: a peak P (>= 250 ft prominence) is first row iff there is no other
>= 250 ft-prominence peak between it and I-90 -- where a peak "includes its
connected ridges that do not descend > 250 ft from the summit".

That parenthetical defines a region, which we call the peak's CAP:

    cap(Q) = connected component containing Q's summit of {elev >= elev(Q) - 250 ft}

Because Q has >= 250 ft of prominence, its key col lies below that level, so the
cap never contains higher ground -- and two qualifying peaks' caps can never touch
(if they did, the lower one would have < 250 ft of prominence). The caps are thus
disjoint footprints, one per qualifying peak.

P is FIRST ROW iff some straight line from a point on I-90 toward P's summit
reaches cap(P) while
    (a) never crossing another qualifying peak's cap;
    (b) never crossing an intervening RIDGE: a point that rises >= 250 ft above
        everything before it on the line and is then followed by a >= 250 ft drop.
        This is the "connected ridges" half of the rule read from P's side: a
        ridge that does NOT drop 250 ft before P is just P's own ridge reaching
        toward the road; one that does is a separate barrier. Dropping from the
        road into a valley is always allowed (nothing has risen 250 ft yet);
    (c) never crossing ground higher than P itself outside cap(P).
Distance is irrelevant; a far peak with a clean approach across an open valley
qualifies, a close peak hidden behind a ridge does not.
"""
from __future__ import annotations

import numpy as np
import rasterio
from numba import njit
from pyproj import Geod, Transformer
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import LineString, shape
from rasterio.features import shapes as rio_shapes

from . import config

TOL_M = config.PROM_MIN_M
_GEOD = Geod(ellps="WGS84")
_MAX_PROFILE_PTS = 90
_STRUCT8 = np.ones((3, 3), dtype=bool)


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------
def compute_caps(elev, valid, srow, scol, selev, depth_m):
    """Label raster: cap_id[r, c] = 1 + peak index whose cap holds the cell (0 = none).

    depth_m[i] is how far below summit i its cap reaches -- the 250 ft rule, but
    never down to the key col (near-threshold peaks rescued by the Kirmse check
    have < 250 ft of prominence on our DEM)."""
    nrows, ncols = elev.shape
    cap = np.zeros(elev.shape, dtype=np.int32)
    sizes = np.zeros(len(srow), dtype=np.int64)
    for i in np.argsort(-selev):                    # highest first (ties are harmless)
        r, c, thr = int(srow[i]), int(scol[i]), float(selev[i]) - float(depth_m[i])
        half = 48
        while True:
            r0, r1 = max(0, r - half), min(nrows, r + half + 1)
            c0, c1 = max(0, c - half), min(ncols, c + half + 1)
            win = (elev[r0:r1, c0:c1] >= thr) & valid[r0:r1, c0:c1]
            lab, _ = ndimage.label(win, structure=_STRUCT8)
            comp = lab == lab[r - r0, c - c0]
            touches = (comp[0].any() and r0 > 0) or (comp[-1].any() and r1 < nrows) or \
                      (comp[:, 0].any() and c0 > 0) or (comp[:, -1].any() and c1 < ncols)
            if not touches or half >= 4096:
                break
            half *= 2
        sub = cap[r0:r1, c0:c1]
        sub[comp & (sub == 0)] = i + 1
        sizes[i] = int(comp.sum())
    return cap, sizes


def cap_polygons(cap, transform, crs, ids, simplify_m=30.0):
    """Vectorise the caps of the given peak indices -> {idx: shapely geom (WGS84)}."""
    import geopandas as gpd
    keep = np.isin(cap, np.asarray(ids) + 1)
    data = np.where(keep, cap, 0).astype(np.int32)
    geoms, vals = [], []
    for g, v in rio_shapes(data, mask=data > 0, transform=transform, connectivity=8):
        geoms.append(shape(g)); vals.append(int(v) - 1)
    gdf = gpd.GeoDataFrame({"idx": vals}, geometry=geoms, crs=crs).dissolve("idx")
    gdf["geometry"] = gdf.geometry.simplify(simplify_m)
    return gdf.to_crs(4326)


# ---------------------------------------------------------------------------
# Approach lines
# ---------------------------------------------------------------------------
@njit(cache=True)
def _walk(elev, cap, valid, r0, c0, r1, c1, me, emax, road_slack, tol):
    """Walk the straight line (r0,c0)->(r1,c1). Returns (status, stop_k, n, blocker).

    status 1 = reached own cap cleanly; 0 = blocked by another cap (blocker = its id);
    2 = blocked by ground higher than the peak; 4 = blocked by an intervening ridge
    (>= tol relief on both sides along the line); 3 = never reached (no data).
    """
    n = int(max(abs(r1 - r0), abs(c1 - c0))) + 1
    zroad = elev[int(r0), int(c0)]
    lo = np.inf          # lowest point so far
    ridge = -np.inf      # highest point so far that rose >= tol above everything before it
    for k in range(n):
        t = k / (n - 1) if n > 1 else 1.0
        r = int(round(r0 + (r1 - r0) * t)); c = int(round(c0 + (c1 - c0) * t))
        if not valid[r, c]:
            continue
        cid = cap[r, c]
        if cid == me:
            return 1, k, n, 0
        if cid != 0:
            return 0, k, n, cid
        z = elev[r, c]
        if z > emax and z > zroad + road_slack:
            return 2, k, n, 0
        if z <= ridge - tol:
            return 4, k, n, 0
        if z < lo:
            lo = z
        elif z - lo >= tol and z > ridge:
            ridge = z
    return 3, n - 1, n, 0


def _candidate_points(highway, crs, step_m=200.0):
    hw = highway.to_crs(crs)
    pts = []
    for geom in hw.geometry:
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for ln in lines:
            d, L = 0.0, ln.length
            while d < L:
                p = ln.interpolate(d); pts.append((p.x, p.y)); d += step_m
            pts.append(ln.coords[-1][:2])
    return np.asarray(pts)


def _profile(elev, r0, c0, r1, c1, n_out):
    t = np.linspace(0, 1, n_out)
    rr = np.round(r0 + (r1 - r0) * t).astype(int)
    cc = np.round(c0 + (c1 - c0) * t).astype(int)
    return elev[rr, cc]


def classify(dem_path=config.DEM_TIF, highway=None, peaks=None, tol_m=TOL_M,
             max_candidates=160, with_detail=True):
    """Return (peaks with `frontrow`, `blocked_by`, ..., details list, caps gdf)."""
    with rasterio.open(dem_path) as dem:
        elev = dem.read(1).astype(np.float32)
        nodata = dem.nodata
        transform, crs = dem.transform, dem.crs
        pk = peaks.to_crs(crs)
        rc = [dem.index(x, y) for x, y in zip(pk.geometry.x, pk.geometry.y)]
    valid = elev != nodata if nodata is not None else np.ones(elev.shape, bool)
    srow = np.clip(np.array([a for a, _ in rc]), 0, elev.shape[0] - 1)
    scol = np.clip(np.array([b for _, b in rc]), 0, elev.shape[1] - 1)
    # summits are DEM cells already; nudge to the local max in case of rounding
    for i in range(len(srow)):
        r, c = srow[i], scol[i]
        w = elev[max(0, r - 1):r + 2, max(0, c - 1):c + 2]
        dr, dc = np.unravel_index(np.argmax(w), w.shape)
        srow[i], scol[i] = max(0, r - 1) + dr, max(0, c - 1) + dc
    selev = elev[srow, scol]

    print(f"[adjacency] computing summit caps for {len(srow)} peaks ...")
    depth = np.minimum(tol_m, peaks["prom_m"].to_numpy() - 1.0)
    cap, sizes = compute_caps(elev, valid, srow, scol, selev, depth)

    cand = _candidate_points(highway, crs)
    inv = ~transform
    cc_h, rr_h = inv * (cand[:, 0], cand[:, 1])
    cand_rc = np.column_stack([rr_h, cc_h])
    inside = (cand_rc[:, 0] >= 0) & (cand_rc[:, 0] < elev.shape[0]) & \
             (cand_rc[:, 1] >= 0) & (cand_rc[:, 1] < elev.shape[1])
    cand, cand_rc = cand[inside], cand_rc[inside]
    tree = cKDTree(cand)
    sx, sy = rasterio.transform.xy(transform, srow, scol)
    sxy = np.column_stack([sx, sy])
    dmin, _ = tree.query(sxy, k=1)

    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    frontrow, blocked_by, block_kind, approach_m = [], [], [], []
    details = []
    for i in range(len(srow)):
        radius = max(5000.0, 1.6 * dmin[i] + 3000.0)
        js = np.array(tree.query_ball_point(sxy[i], radius))
        d = np.hypot(cand[js, 0] - sxy[i, 0], cand[js, 1] - sxy[i, 1])
        js = js[np.argsort(d)]
        if len(js) > max_candidates:      # keep the nearest third + an even spread
            near = js[:max_candidates // 3]
            rest = js[max_candidates // 3:]
            js = np.concatenate([near, rest[np.linspace(0, len(rest) - 1,
                                                        max_candidates - len(near)).astype(int)]])
        best = first = None
        for j in js:
            r0, c0 = cand_rc[j]
            st, k, n, who = _walk(elev, cap, valid, r0, c0, float(srow[i]), float(scol[i]),
                                  i + 1, float(selev[i]), 30.0, float(tol_m))
            rec = (st, k, n, who, j)
            if first is None:
                first = rec
            if st == 1:
                best = rec
                break                      # candidates are distance-sorted
        chosen = best or first
        ok = best is not None
        frontrow.append(ok)
        st, k, n, who, j = chosen
        blocked_by.append(-1 if ok or st != 0 else who - 1)
        block_kind.append("" if ok else {0: "peak", 2: "higher", 3: "nodata", 4: "ridge"}[st])
        hx, hy = cand[j]
        hlon, hlat = to_wgs.transform(hx, hy)
        slon, slat = to_wgs.transform(sxy[i, 0], sxy[i, 1])
        L = float(_GEOD.line_length([hlon, slon], [hlat, slat]))
        approach_m.append(L)
        if with_detail:
            r0, c0 = cand_rc[j]
            npts = min(_MAX_PROFILE_PTS, n)
            z = _profile(elev, r0, c0, srow[i], scol[i], npts)
            details.append({
                "h": [round(hlon, 5), round(hlat, 5)],
                "s": [round(slon, 5), round(slat, 5)],
                "len": round(L),
                "z": [None if not np.isfinite(v) or v == nodata else round(float(v))
                      for v in z],
                "stop": round(k / max(1, n - 1), 3),  # fraction along line: cap entry / block
                "ok": ok,
                "by": blocked_by[-1],
                "kind": block_kind[-1],
            })

    out = peaks.copy()
    out["summit_elev_m"] = selev
    out["cap_cells"] = sizes
    out["frontrow"] = np.array(frontrow)
    out["blocked_by"] = np.array(blocked_by)
    out["block_kind"] = np.array(block_kind)
    out["nearest_i90_m"] = np.round(dmin * np.cos(np.radians(out.lat.values)))  # 3857 -> ground
    out["approach_m"] = np.round(approach_m)
    n_fr = int(out.frontrow.sum())
    print(f"[adjacency] {len(out)} peaks -> {n_fr} FIRST ROW, {len(out) - n_fr} behind")
    caps = cap_polygons(cap, transform, crs, np.arange(len(out)))
    return out, details, caps
