"""Compare routes by AlphaEarth embeddings (after alpha_earth_embeddings_demo.ipynb).

The notebook's core move -- every 10 m patch is a 64-d unit vector; two places
are alike when their vectors point the same way (cosine similarity) -- applied to
whole routes:

  * fingerprint: mean embedding sampled every 40 m along the route, centred on
    the corridor mean (otherwise every Cascade forest run looks ~0.95 alike), and
    re-normalised -> cosine similarity matrix between routes.
  * terrain mix: k-means "terrain types" fit on the corridor's own embeddings
    (the notebook's unsupervised sorting step); each route gets a composition, and
    the mixes explain *why* two routes match.
  * colour barcode: the corridor's top-3 principal components as RGB along the
    route (the notebook's "paint the Earth in the AI's own colours").
"""
from __future__ import annotations

import pickle

import numpy as np
import rasterio
from pyproj import Transformer
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

from . import config, terrain
from .embeddings import MOSAIC_TIF, Embeddings

MODELS_PKL = config.INTERIM / "aef_models.pkl"
N_CLASSES = 10

# Names inferred from each class's elevation / slope / location statistics on the
# corridor (see fit_models' printout) -- interpretive labels, not ground truth.
CLASS_INFO = {
    "water":    ("Open water", "#3b7dd8"),
    "steppe":   ("Columbia Basin flats", "#d9c27a"),
    "alpine":   ("Alpine rock & snow", "#c9ccd6"),
    "urban":    ("City & suburbs", "#8e8e8e"),
    "westfor":  ("Westside lowland forest", "#2f6b3a"),
    "sage":     ("Sagebrush hills", "#b59a5b"),
    "steep":    ("Steep mountainside", "#7a6a8e"),
    "montane":  ("Montane forest", "#4d8a57"),
    "rural":    ("Rural lowland mosaic", "#9bb36a"),
    "eastfor":  ("Eastside pine & fir", "#8a9a4d"),
}


def _corridor_sample(E, n=400_000, seed=0):
    rng = np.random.default_rng(seed)
    h, w, _ = E.q.shape
    r, c = rng.integers(0, h, n), rng.integers(0, w, n)
    q = E.q[r, c].astype(np.float32)
    ok = q[:, 0] != -128
    r, c, q = r[ok], c[ok], q[ok]
    with rasterio.open(MOSAIC_TIF) as s:
        x, y = rasterio.transform.xy(s.transform, r, c)
    lon, lat = Transformer.from_crs(32610, 4326, always_xy=True).transform(np.array(x), np.array(y))
    return (q / 127.5) ** 2 * np.sign(q), lon, lat


def _auto_name(stats):
    """Map k-means clusters to CLASS_INFO keys from their terrain statistics."""
    keys, left = {}, dict(stats)
    def take(key, score):
        i = max(left, key=lambda k: score(left[k])); keys[i] = key; left.pop(i)
    take("water",   lambda s: -s["slope"] - s["elev"] / 100)
    take("alpine",  lambda s: s["elev"])
    take("urban",   lambda s: -abs(s["elev"] - 120) / 50 - abs(s["lon"] + 122.25) * 10)
    take("steppe",  lambda s: s["lon"] - s["slope"])
    take("sage",    lambda s: s["lon"])
    take("rural",   lambda s: -s["elev"])
    take("westfor", lambda s: -s["lon"])
    take("eastfor", lambda s: s["lon"] - s["slope"] / 5)
    take("steep",   lambda s: s["slope"])
    take("montane", lambda s: 0)
    return keys


def fit_models(overwrite=False):
    if MODELS_PKL.exists() and not overwrite:
        return pickle.load(open(MODELS_PKL, "rb"))
    E, D = Embeddings(), terrain.DEM()
    V, lon, lat = _corridor_sample(E)
    km = KMeans(N_CLASSES, n_init=6, random_state=0).fit(V)
    z, sl = D.elev(lon, lat), D.slope_deg(lon, lat)
    stats = {}
    for i in range(N_CLASSES):
        m = km.labels_ == i
        stats[i] = {"elev": float(np.nanmedian(z[m])), "slope": float(np.nanmedian(sl[m])),
                    "lon": float(np.median(lon[m])), "share": float(m.mean())}
    names = _auto_name(stats)
    for i in range(N_CLASSES):
        s = stats[i]
        print(f"[aef] class {i} -> {CLASS_INFO[names[i]][0]:26s} {s['share']*100:4.1f}%  "
              f"elev {s['elev']/0.3048:5.0f} ft  slope {s['slope']:4.1f}°  lon {s['lon']:.2f}")
    pca = PCA(3).fit(V)
    proj = pca.transform(V)
    lo, hi = np.percentile(proj, 2, axis=0), np.percentile(proj, 98, axis=0)
    models = {"km": km, "names": names, "stats": stats, "pca": pca, "pca_lo": lo, "pca_hi": hi,
              "mean": V.mean(0)}
    pickle.dump(models, open(MODELS_PKL, "wb"))
    return models


def route_profile(lonlat, E, D, models, trails_tree=None, step_m=40.0):
    """Densify a route and sample embeddings + terrain along it."""
    lon, lat, dist = terrain.densify(np.asarray(lonlat)[:, :2], step_m)
    V = E.sample(lon, lat)
    ok = np.isfinite(V[:, 0])
    cls = np.full(len(lon), -1)
    cls[ok] = models["km"].predict(V[ok])
    rgb = np.zeros((len(lon), 3))
    rgb[ok] = np.clip((models["pca"].transform(V[ok]) - models["pca_lo"]) /
                      (models["pca_hi"] - models["pca_lo"]), 0, 1)
    out = {"lon": lon, "lat": lat, "dist": dist, "V": V, "ok": ok, "cls": cls, "rgb": rgb,
           "elev": D.elev(lon, lat), "slope": D.slope_deg(lon, lat)}
    if trails_tree is not None:
        x, y = terrain._TO_UTM.transform(lon, lat)
        d, _ = trails_tree.query(np.column_stack([x, y]), distance_upper_bound=200)
        out["on_trail"] = d <= 25.0
    return out


def fingerprint(prof, models):
    V = prof["V"][prof["ok"]]
    f = V.mean(0) - models["mean"]
    return f / (np.linalg.norm(f) + 1e-9)


def composition(prof, models):
    k = models["km"].n_clusters
    c = prof["cls"][prof["cls"] >= 0]
    h = np.bincount(c, minlength=k).astype(float)
    return h / max(1.0, h.sum())


def similarity_matrix(fps):
    F = np.vstack(fps)
    return np.clip(F @ F.T, -1, 1)


def trails_kdtree():
    """KD-tree over OSM trail + road vertices densified to ~20 m (UTM 10N)."""
    from scipy.spatial import cKDTree
    from . import osm
    pts = []
    for g in list(osm.trails().geometry) + list(osm.roads().geometry):
        xy = np.asarray(g.coords)
        x, y = terrain._TO_UTM.transform(xy[:, 0], xy[:, 1])
        seg = np.hypot(np.diff(x), np.diff(y))
        for i in range(len(seg)):
            n = max(1, int(seg[i] // 20))
            t = np.arange(n) / n
            pts.append(np.column_stack([x[i] + (x[i + 1] - x[i]) * t, y[i] + (y[i + 1] - y[i]) * t]))
    return cKDTree(np.vstack(pts))
