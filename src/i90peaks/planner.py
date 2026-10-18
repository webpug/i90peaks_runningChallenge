"""Predict new routes for the unfinished first-row peaks from the athlete's own data.

1. PACE MODEL (fit_pace): every timed on-foot activity in the corridor is cut
   into ~100 m chunks with DEM grade, AlphaEarth terrain class, and on/off-trail
   (OSM within 25 m). We learn
     - base(grade): on-trail seconds per metre by grade bin (binned medians),
     - off-trail slowdown per terrain class (median observed / base, shrunk to
       the overall off-trail factor when a class has little data),
     - the steepest ground actually travelled (99th pct slope) -> anything steeper
       is treated as impassable when routing.
2. ROUTER: least-time Dijkstra on a 40 m UTM grid aligned with the embedding
   mosaic, using that pace model (anisotropic: up and down cost differently).
   Each unfinished peak gets its best road access; nearby peaks are chained into
   traverses when linking beats separate trips and the outing stays within the
   athlete's demonstrated longest day.
"""
from __future__ import annotations

import pickle

import geopandas as gpd
import numpy as np
import rasterio
from numba import njit
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from shapely.geometry import LineString

from . import config, similarity as S, terrain
from .embeddings import MOSAIC_TIF, Embeddings

GRID_PKL = config.INTERIM / "plan_grid.npz"
PACE_PKL = config.INTERIM / "pace_model.pkl"
GRADE_BINS = np.arange(-0.60, 0.61, 0.05)
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
_FROM_UTM = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True)


# ---------------------------------------------------------------------------
# Pace model
# ---------------------------------------------------------------------------
def _chunks(pts, prof_fn, chunk_m=100.0):
    """Cut a timed track into ~chunk_m pieces -> rows of (grade, s/m, on_trail, cls, slope)."""
    t = pts[:, 3]
    if np.isfinite(t).sum() < 20:
        return []
    good = np.isfinite(t)
    pts = pts[good]
    x, y = _TO_UTM.transform(pts[:, 0], pts[:, 1])
    d = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    edges = np.searchsorted(d, np.arange(0, d[-1], chunk_m))
    prof = prof_fn(pts[:, :2])
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < 2:
            continue
        dist = d[b] - d[a]
        dt = pts[b, 3] - pts[a, 3]
        if dist < 50 or dt <= 0 or dt > 1800:
            continue
        spd = dist / dt
        if not (0.25 < spd < 7.0):
            continue
        # profile is densified at 40 m: map chunk midpoint distance onto it
        k0 = min(int(d[a] / 40), len(prof["dist"]) - 1); k1 = min(int(d[b] / 40), len(prof["dist"]) - 1)
        dz = float(prof["elev"][k1] - prof["elev"][k0])
        seg = slice(k0, max(k0 + 1, k1))
        cls = prof["cls"][seg]; cls = cls[cls >= 0]
        rows.append((dz / dist, dt / dist, float(prof["on_trail"][seg].mean()) >= 0.5,
                     int(np.bincount(cls).argmax()) if len(cls) else -1,
                     float(np.nanmax(prof["slope"][seg]))))
    return rows


def fit_pace(activities, overwrite=False):
    if PACE_PKL.exists() and not overwrite:
        return pickle.load(open(PACE_PKL, "rb"))
    from .tracks import ON_FOOT
    models = S.fit_models()
    E, D = Embeddings(), terrain.DEM()
    tree = pickle.load(open(config.INTERIM / "trails_kdtree.pkl", "rb"))
    w, s, e, n = config.BBOX
    rows = []
    for act in activities:
        if act["type"] not in ON_FOOT or act["type"] in ("Backcountry Ski", "Snowshoe"):
            continue
        pts = np.asarray(act["pts"], dtype=float)
        if len(pts) < 20 or pts.shape[1] < 4:
            continue
        if not ((pts[:, 0] > w) & (pts[:, 0] < e) & (pts[:, 1] > s) & (pts[:, 1] < n)).mean() > 0.5:
            continue
        rows += _chunks(pts, lambda ll: S.route_profile(ll, E, D, models, tree))
    R = np.array(rows, dtype=float)
    grade, pace, on, cls, slope = R.T
    on = on.astype(bool)

    # base(grade): on-trail medians per bin, filled by a Tobler curve scaled to the data
    centers = (GRADE_BINS[:-1] + GRADE_BINS[1:]) / 2
    tob = lambda g: 1 / (6 * np.exp(-3.5 * np.abs(g + 0.05)) / 3.6)
    flat = on & (np.abs(grade) < 0.03)
    scale = np.median(pace[flat]) / tob(0.0) if flat.sum() > 20 else 1.0
    base, nbin = [], []
    for lo, hi, c in zip(GRADE_BINS[:-1], GRADE_BINS[1:], centers):
        m = on & (grade >= lo) & (grade < hi)
        nbin.append(int(m.sum()))
        prior = tob(c) * scale
        base.append((np.median(pace[m]) * m.sum() + prior * 15) / (m.sum() + 15) if m.any() else prior)
    # enforce a unimodal curve: slower the further the grade is from the fastest bin
    base = np.array(base)
    best = int(np.argmin(base))
    for i in range(best + 1, len(base)):
        base[i] = max(base[i], base[i - 1])
    for i in range(best - 1, -1, -1):
        base[i] = max(base[i], base[i + 1])

    def base_fn(g):
        return np.interp(g, centers, base)

    off = ~on & (cls >= 0)
    ratio = pace[off] / base_fn(grade[off])
    overall = float(np.median(ratio)) if off.sum() > 10 else 1.6
    k = models["km"].n_clusters
    mult = np.full(k, overall)
    nclass = np.zeros(k, int)
    for c in range(k):
        m = cls[off] == c
        nclass[c] = int(m.sum())
        if m.any():
            mult[c] = (np.median(ratio[m]) * m.sum() + overall * 20) / (m.sum() + 20)
    names = models["names"]
    water = [c for c in range(k) if names[c] == "water"]
    mult[water] = np.inf
    max_slope = float(np.nanpercentile(slope[off], 99)) if off.sum() > 20 else 40.0
    pm = {"centers": centers, "base": base, "nbin": nbin, "offtrail_mult": mult,
          "offtrail_n": nclass, "overall_off": overall,
          # a 26 m DEM smooths cliffs: never route steeper than 45° even if the data says so
          "max_slope": float(np.clip(max_slope, 35.0, 45.0)), "max_slope_seen": max_slope,
          "n_chunks": len(R), "n_off": int(off.sum())}
    print(f"[pace] {len(R)} chunks ({int(off.sum())} off-trail); flat on-trail "
          f"{1609.344 * base_fn(0) / 60:.1f} min/mi; off-trail x{overall:.2f}; "
          f"max slope travelled {pm['max_slope']:.0f}°")
    pickle.dump(pm, open(PACE_PKL, "wb"))
    return pm


def pace_fn(pm):
    return lambda g: np.interp(g, pm["centers"], pm["base"])


# ---------------------------------------------------------------------------
# Routing grid (40 m, aligned with the embedding mosaic)
# ---------------------------------------------------------------------------
def build_grid(overwrite=False):
    if GRID_PKL.exists() and not overwrite:
        g = np.load(GRID_PKL)
        return {k: g[k] for k in g.files}
    from . import osm
    with rasterio.open(MOSAIC_TIF) as src:
        T, h, w = src.transform, src.height, src.width
    with rasterio.open(config.DEM_TIF) as dem:
        z = np.full((h, w), np.nan, np.float32)
        reproject(dem.read(1), z, src_transform=dem.transform, src_crs=dem.crs,
                  src_nodata=dem.nodata, dst_transform=T, dst_crs="EPSG:32610",
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
    tr = osm.trails().to_crs(32610)
    rd = osm.roads().to_crs(32610)
    trail = rasterize(((g, 1) for g in list(tr.geometry) + list(rd.geometry)),
                      out_shape=(h, w), transform=T, all_touched=True, dtype="uint8")
    road = rasterize(((g, 1) for g in rd[rd.highway.isin(
        ["primary", "secondary", "tertiary", "unclassified", "residential"])].geometry),
                     out_shape=(h, w), transform=T, all_touched=False, dtype="uint8")
    models = S.fit_models()
    E = Embeddings()
    cls = np.full(h * w, -1, np.int8)
    q = E.q.reshape(-1, 64)
    for i in range(0, h * w, 2_000_000):
        qq = q[i:i + 2_000_000].astype(np.float32)
        ok = qq[:, 0] != -128
        if ok.any():
            v = (qq[ok] / 127.5) ** 2 * np.sign(qq[ok])
            cls[i:i + 2_000_000][ok] = models["km"].predict(v)
    cls = cls.reshape(h, w)
    gy, gx = np.gradient(z, 40.0)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    grid = {"z": z, "trail": trail, "road": road, "cls": cls, "slope": slope,
            "transform": np.array(T)[:6]}
    np.savez_compressed(GRID_PKL, **grid)
    return grid


@njit(cache=True)
def _dijkstra(z, mult, slope_ok, seeds, cx, cy, gc, gp, cell):
    """Least-time search from seed cells; returns (time_s, parent). Edge time =
    horizontal metres x pace(grade) x terrain multiplier of the destination."""
    h, w = z.shape
    N = h * w
    tt = np.full(N, np.inf)
    par = np.full(N, -1, np.int64)
    # simple binary heap
    hk = np.empty(N * 8, np.float64); hv = np.empty(N * 8, np.int64); n = 0
    for s in seeds:
        tt[s] = 0.0
        hk[n] = 0.0; hv[n] = s; i = n; n += 1
        while i > 0:
            p = (i - 1) // 2
            if hk[p] <= hk[i]: break
            hk[p], hk[i] = hk[i], hk[p]; hv[p], hv[i] = hv[i], hv[p]; i = p
    dr = np.array([-1, -1, -1, 0, 0, 1, 1, 1]); dc = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    while n > 0:
        key = hk[0]; u = hv[0]
        n -= 1; hk[0] = hk[n]; hv[0] = hv[n]; i = 0
        while True:
            l = 2 * i + 1; r = l + 1; m = i
            if l < n and hk[l] < hk[m]: m = l
            if r < n and hk[r] < hk[m]: m = r
            if m == i: break
            hk[m], hk[i] = hk[i], hk[m]; hv[m], hv[i] = hv[i], hv[m]; i = m
        if key > tt[u]: continue
        ur, uc = u // w, u % w
        for k in range(8):
            vr, vc = ur + dr[k], uc + dc[k]
            if vr < 0 or vr >= h or vc < 0 or vc >= w: continue
            v = vr * w + vc
            if not slope_ok[vr, vc]: continue
            mv = mult[vr, vc]
            if not np.isfinite(mv): continue
            dist = cell * (1.41421356 if dr[k] != 0 and dc[k] != 0 else 1.0)
            g = (z[vr, vc] - z[ur, uc]) / dist
            p = np.interp(g, gc, gp)
            nt = tt[u] + dist * p * mv
            if nt < tt[v]:
                tt[v] = nt; par[v] = u
                if n >= hk.size: continue
                hk[n] = nt; hv[n] = v; i = n; n += 1
                while i > 0:
                    pp = (i - 1) // 2
                    if hk[pp] <= hk[i]: break
                    hk[pp], hk[i] = hk[i], hk[pp]; hv[pp], hv[i] = hv[i], hv[pp]; i = pp
    return tt, par


class Router:
    def __init__(self, grid, pm, models):
        self.g, self.pm = grid, pm
        a, b, c, d, e, f = grid["transform"]
        self.T = rasterio.Affine(a, b, c, d, e, f)
        cls = grid["cls"]
        offm = pm["offtrail_mult"][np.clip(cls, 0, None)]
        offm[cls < 0] = np.inf
        self.mult = np.where(grid["trail"] > 0, 1.0, offm).astype(np.float64)
        z = grid["z"]
        self.ok = np.isfinite(z) & ((grid["slope"] <= pm["max_slope"]) | (grid["trail"] > 0))

    def rc(self, lon, lat):
        x, y = _TO_UTM.transform(lon, lat)
        c, r = ~self.T * (x, y)
        return int(r), int(c)

    def window(self, rows, cols, pad=150):
        h, w = self.g["z"].shape
        r0, r1 = max(0, min(rows) - pad), min(h, max(rows) + pad)
        c0, c1 = max(0, min(cols) - pad), min(w, max(cols) + pad)
        return r0, r1, c0, c1

    def search(self, win, seeds_rc):
        r0, r1, c0, c1 = win
        z = np.ascontiguousarray(np.nan_to_num(self.g["z"][r0:r1, c0:c1], nan=0.0).astype(np.float64))
        w = c1 - c0
        seeds = np.array([(r - r0) * w + (c - c0) for r, c in seeds_rc], np.int64)
        tt, par = _dijkstra(z, np.ascontiguousarray(self.mult[r0:r1, c0:c1]),
                            np.ascontiguousarray(self.ok[r0:r1, c0:c1]), seeds,
                            0, 0, self.pm["centers"], self.pm["base"], 40.0)
        return tt, par, w

    @staticmethod
    def backtrack(par, idx):
        path = [idx]
        while par[path[-1]] >= 0:
            path.append(par[path[-1]])
        return path[::-1]

    def to_lonlat(self, win, w, path):
        r0, _, c0, _ = win
        rr = np.array([p // w for p in path]) + r0
        cc = np.array([p % w for p in path]) + c0
        x, y = rasterio.transform.xy(self.T, rr, cc)
        lon, lat = _FROM_UTM.transform(np.asarray(x), np.asarray(y))
        return np.column_stack([lon, lat]), rr, cc


def plan(classified, pm, max_day_s, link_km=5.0):
    """Plan outings covering every first-row peak not yet done."""
    grid = build_grid()
    models = S.fit_models()
    R = Router(grid, pm, models)
    todo = classified[classified.frontrow & ~classified.done].copy()
    todo["rc"] = [R.rc(lo, la) for lo, la in zip(todo.lon, todo.lat)]
    x, y = _TO_UTM.transform(todo.lon.values, todo.lat.values)
    todo["x"], todo["y"] = x, y
    road = grid["road"]

    def access(idx_list):
        """Least-time path road -> first peak, through all peaks in order, -> any road."""
        rcs = [todo.loc[i, "rc"] for i in idx_list]
        win = R.window([r for r, _ in rcs], [c for _, c in rcs])
        r0, r1, c0, c1 = win
        # start/finish only on public roads >= 250 ft below the lowest summit:
        # driving to the top is not running a peak
        zmin = min(R.g["z"][r, c] for r, c in rcs) - config.PROM_MIN_M
        sub = (road[r0:r1, c0:c1] > 0) & (np.nan_to_num(R.g["z"][r0:r1, c0:c1], nan=1e9) <= zmin)
        seeds = [(r0 + r, c0 + c) for r, c in zip(*np.nonzero(sub))]
        if not seeds:
            return None
        legs, total, coords = [], 0.0, []
        tt, par, w = R.search(win, seeds)
        tgt = (rcs[0][0] - r0) * w + (rcs[0][1] - c0)
        if not np.isfinite(tt[tgt]):
            return None
        p = R.backtrack(par, tgt); total += tt[tgt]; legs.append(p)
        for a, b in zip(rcs[:-1], rcs[1:]):
            tt, par, w = R.search(win, [a])
            tgt = (b[0] - r0) * w + (b[1] - c0)
            if not np.isfinite(tt[tgt]):
                return None
            legs.append(R.backtrack(par, tgt)); total += tt[tgt]
        # descent: from the last summit to the nearest-by-time road cell
        tt, par, w = R.search(win, [rcs[-1]])
        sub_idx = np.flatnonzero(sub.ravel())
        if len(sub_idx) == 0:
            return None
        best = sub_idx[np.argmin(tt[sub_idx])]
        if not np.isfinite(tt[best]):
            return None
        legs.append(R.backtrack(par, best)); total += tt[best]
        for leg in legs:
            ll, rr, cc = R.to_lonlat(win, w, leg)
            coords.append((ll, rr, cc))
        return total, coords

    # 1) single-peak outings (also the building blocks for linking)
    single = {}
    for i in todo.index:
        res = access([i])
        if res is not None:
            single[i] = res[0]
    # 2) greedy chaining west->east of peaks within link_km when it beats separate trips
    order = todo.loc[list(single)].sort_values("lon").index.tolist()
    outings, used = [], set()
    for i in order:
        if i in used:
            continue
        chain, t_chain = [i], single[i]
        res_chain = access(chain)
        while True:
            last = chain[-1]
            cands = [j for j in order if j not in used and j not in chain and
                     np.hypot(todo.x[j] - todo.x[last], todo.y[j] - todo.y[last]) < link_km * 1000]
            cands.sort(key=lambda j: np.hypot(todo.x[j] - todo.x[last], todo.y[j] - todo.y[last]))
            added = False
            for j in cands[:3]:
                res = access(chain + [j])
                if res is None:
                    continue
                if res[0] < t_chain + single[j] * 0.9 and res[0] <= max_day_s:
                    chain, t_chain, res_chain = chain + [j], res[0], res
                    added = True
                    break
            if not added:
                break
        used.update(chain)
        if res_chain is not None:
            outings.append((chain, res_chain))
    missing = [i for i in todo.index if i not in single]
    if missing:
        print("[plan] no route found for:", [todo.loc[i, "name"] or f"Pt {todo.loc[i, 'elev_ft']:.0f}" for i in missing])
    print(f"[plan] {len(todo)} peaks to go -> {len(outings)} planned outings "
          f"({len(todo) - sum(len(c) for c, _ in outings)} unreachable within limits)")
    return todo, outings, R


def describe(outings, todo, R, models, pm, E, D, past_fps, past_names):
    """GeoDataFrame of planned outings with predicted stats + nearest past run."""
    rows = []
    trail = R.g["trail"]; cls_grid = R.g["cls"]
    for k, (chain, (t_s, legs)) in enumerate(outings):
        ll = np.vstack([leg[0] for leg in legs])
        rr = np.concatenate([leg[1] for leg in legs]); cc = np.concatenate([leg[2] for leg in legs])
        x, y = _TO_UTM.transform(ll[:, 0], ll[:, 1])
        dist = float(np.hypot(np.diff(x), np.diff(y)).sum())
        z = R.g["z"][rr, cc]
        gain = float(np.nansum(np.clip(np.diff(z), 0, None)))
        on = trail[rr, cc] > 0
        prof = S.route_profile(ll, E, D, models)
        fp = S.fingerprint(prof, models)
        sims = np.array([float(fp @ f) for f in past_fps]) if past_fps else np.array([])
        best = int(np.argmax(sims)) if len(sims) else -1
        comp = S.composition(prof, models)
        cl = cls_grid[rr[~on], cc[~on]]
        novel = [models["names"][c] for c in np.unique(cl[cl >= 0]) if pm["offtrail_n"][c] < 5]
        names = [todo.loc[i, "name"] or f"Pt {todo.loc[i, 'elev_ft']:.0f}" for i in chain]
        rows.append({
            "route_id": k, "name": " → ".join(names), "peaks": ",".join(str(int(i)) for i in chain),
            "n_peaks": len(chain), "dist_mi": round(dist / 1609.344, 1),
            "gain_ft": round(gain / 0.3048), "est_hours": round(t_s / 3600, 1),
            "off_trail_pct": round(100 * (1 - on.mean())),
            "shuttle_mi": round(float(np.hypot(x[-1] - x[0], y[-1] - y[0])) / 1609.344, 1),
            "like_run": past_names[best] if best >= 0 else "", "like_sim": round(float(sims[best]), 2) if best >= 0 else None,
            "new_terrain": ",".join(sorted(set(novel))),
            "comp": [round(float(v), 3) for v in comp],
            "fp": fp,
            "geometry": LineString(ll).simplify(0.00005),
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
