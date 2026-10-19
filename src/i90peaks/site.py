"""Phase 2: completed tracks -> AlphaEarth similarity -> predicted routes -> pages.

    build_all(classified, highway, details, caps)

writes data/processed/
    i90_app.html        the map (done peaks, my tracks, planned routes, drawing tool)
    similarity.html     the AlphaEarth route-similarity analysis + route plan
    tracks_public.geojson, planned_routes.geojson, planned_routes.gpx
    site_seed.json      peaks (+ summit zones), published runs and summits for the
                        family site's Supabase tables (theblacks.ai scripts/i90peaks-import.mjs)
"""
from __future__ import annotations

import json
import pickle

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from shapely.geometry import Point

from . import config, planner, similarity as S, terrain, tracks as T, webapp, analysis_page
from .embeddings import Embeddings

MAX_DAY_H = 6.0
SITE_MAP_URL = "/i90peaks"
SITE_SIM_URL = "/i90peaks/similarity"

# 10 embedding classes -> 8 display groups (fits the validated 8-slot palette)
GROUPS = [  # (key, label, light, dark, member classes)
    ("water", "Open water", "#2a78d6", "#3987e5", ["water"]),
    ("dry", "Dry steppe & sage", "#eb6834", "#d95926", ["steppe", "sage"]),
    ("westfor", "Westside lowland forest", "#1baf7a", "#199e70", ["westfor"]),
    ("rural", "Rural lowland mosaic", "#eda100", "#c98500", ["rural"]),
    ("urban", "City & suburbs", "#e87ba4", "#d55181", ["urban"]),
    ("montane", "Montane forest", "#008300", "#008300", ["montane"]),
    ("alpine", "Alpine rock, snow & steep", "#6250d6", "#9085e9", ["alpine", "steep"]),
    ("eastfor", "Eastside pine & fir", "#e34948", "#e66767", ["eastfor"]),
]
REGIONS = [(-122.0, "Seattle & Eastside"), (-121.84, "Issaquah Alps"), (-121.6, "North Bend"),
           (-121.3, "Snoqualmie Pass"), (-121.0, "Kachess & Easton"), (-120.6, "Cle Elum foothills"),
           (-120.3, "Kittitas Valley"), (99, "Whiskey Dick & Vantage")]


def _fold(comp, names):
    out = np.zeros(len(GROUPS))
    for c, v in enumerate(comp):
        for g, grp in enumerate(GROUPS):
            if names[c] in grp[4]:
                out[g] += v
    return [round(float(x), 3) for x in out]


def _barcode(prof, n=90):
    rgb = prof["rgb"][prof["ok"]]
    if len(rgb) == 0:
        return []
    idx = np.linspace(0, len(rgb) - 1, min(n, len(rgb))).astype(int)
    return ["#%02x%02x%02x" % tuple((rgb[i] * 255).astype(int)) for i in idx]


def _region(lon):
    return next(name for edge, name in REGIONS if lon < edge)


def build_all(classified, highway, details, caps):
    print("\n==[8] my tracks ==")
    classified, tracks, full = T.match(classified)
    acts = {a["id"]: a for a in T.load_all()}

    print("\n==[9] AlphaEarth route similarity ==")
    models = S.fit_models()
    E, D = Embeddings(), terrain.DEM()
    tree = pickle.load(open(config.INTERIM / "trails_kdtree.pkl", "rb")) \
        if (config.INTERIM / "trails_kdtree.pkl").exists() else S.trails_kdtree()
    names = models["names"]
    routes, fps = [], []
    tracks = tracks.sort_values("date").reset_index(drop=True)
    for i, r in tracks.iterrows():
        pts = full[r.act_id]
        prof = S.route_profile(pts[:, :2], E, D, models, tree)
        fps.append(S.fingerprint(prof, models))
        t = pts[:, 3]
        moving = np.nan
        if np.isfinite(t).sum() > 20:
            x, y = terrain._TO_UTM.transform(pts[:, 0], pts[:, 1])
            d, dt = np.hypot(np.diff(x), np.diff(y)), np.diff(t)
            m = (dt > 0) & (dt < 300) & (d / np.maximum(dt, 1e-6) > 0.3)
            moving = float(dt[m].sum() / 3600)
        pk = [int(p) for p in r.peaks.split(",")]
        routes.append({
            "id": i, "name": r["name"], "type": r["type"], "date": _date(r["date"]),
            "dist_mi": r.dist_mi, "gain_ft": r.gain_ft, "moving_h": round(moving, 1) if np.isfinite(moving) else None,
            "peaks": [_pname(classified.loc[p]) for p in pk],
            "off_trail_pct": round(100 * (1 - float(prof["on_trail"].mean()))),
            "comp": _fold(S.composition(prof, models), names),
            "barcode": _barcode(prof),
        })
    sim = S.similarity_matrix(fps)
    order = leaves_list(linkage(squareform(np.clip(1 - sim, 0, 2), checks=False), "average")).tolist() \
        if len(fps) > 2 else list(range(len(fps)))
    F = np.vstack(fps)
    U, s_, Vt = np.linalg.svd(F - F.mean(0), full_matrices=False)
    xy = U[:, :2] * s_[:2]
    for r, p in zip(routes, xy):
        r["xy"] = [round(float(p[0]), 3), round(float(p[1]), 3)]

    print("\n==[10] predicted routes ==")
    pm = planner.fit_pace(list(acts.values()))
    todo, outings, R = planner.plan(classified, pm, max_day_s=MAX_DAY_H * 3600)
    planned = planner.describe(outings, todo, R, models, pm, E, D, fps,
                               [f"{r['name']} ({r['date']})" for r in routes])
    # a route with almost no climbing is an artefact (e.g. clipped at the data edge)
    planned = planned[planned.gain_ft >= 150].reset_index(drop=True)
    planned["region"] = [_region(todo.loc[int(p.split(",")[0]), "lon"]) for p in planned.peaks]
    planned["comp8"] = [_fold(c, names) for c in planned.comp]
    planned["restricted"] = [_restricted_note(g) for g in planned.geometry]
    classified["access_note"] = [_restricted_note(Point(lo, la)) for lo, la in zip(classified.lon, classified.lat)]
    reg_order = {name: k for k, (_, name) in enumerate(REGIONS)}
    planned = planned.sort_values(["region", "est_hours"], key=lambda s: s.map(reg_order) if s.name == "region" else s)
    planned = planned.reset_index(drop=True)
    planned["route_id"] = planned.index

    # ---- publishable layers
    pub = T.privacy_trim(tracks)
    tracks_gj = json.loads(pub.assign(id=pub.index, key="strava-" + pub.act_id.astype(str))[
        ["id", "key", "name", "date", "type", "dist_mi", "gain_ft", "geometry"]]
                           .assign(date=lambda d: d["date"].map(_date)).to_json())
    routes_gj = json.loads(planned[["route_id", "name", "region", "n_peaks", "fallback", "dist_mi", "gain_ft", "est_hours",
                                    "off_trail_pct", "shuttle_mi", "like_run", "like_sim", "restricted", "geometry"]].to_json())
    for f in routes_gj["features"]:
        p = f["properties"]
        p["desc"] = (f"{p['region']} · {p['dist_mi']} mi · {p['gain_ft']:,} ft · ~{p['est_hours']} h · "
                     f"{p['off_trail_pct']}% off-trail" + (f" · ends {p['shuttle_mi']} mi from start"
                                                         if p["shuttle_mi"] >= 1 else "")
                     + (" · hand-check: no normal route (long approach or summit scramble)" if p["fallback"] else "")
                     + (f" · crosses the {p['restricted']}" if p["restricted"] else ""))
    (config.PROCESSED / "tracks_public.geojson").write_text(json.dumps(tracks_gj))
    _site_seed(classified, pub, config.PROCESSED / "site_seed.json")
    (config.PROCESSED / "planned_routes.geojson").write_text(json.dumps(routes_gj))
    _routes_gpx(planned, config.PROCESSED / "planned_routes.gpx")

    pace = {"centers": [round(float(g), 3) for g in pm["centers"]],
            "base": [round(float(b), 4) for b in pm["base"]], "off": round(pm["overall_off"], 2)}
    links = [{"href": SITE_SIM_URL, "label": "Route similarity (AlphaEarth) →"},
             {"href": SITE_SIM_URL + "#plan", "label": "Planned routes →"}]
    webapp.build_app(classified, highway, details=details, caps=caps, tracks=tracks_gj,
                     routes=routes_gj, links=links, pace=pace)

    done_ct = int(classified[classified.frontrow].done.sum())
    analysis_page.build({
        "routes": routes, "sim": np.round(sim, 3).tolist(), "order": order,
        "groups": [{"key": g[0], "label": g[1], "light": g[2], "dark": g[3]} for g in GROUPS],
        "planned": [{k: (v if not isinstance(v, (np.floating, np.integer)) else v.item())
                     for k, v in row.items() if k not in ("geometry", "fp", "comp")}
                    for row in planned.to_dict("records")],
        "pace": {"grade": [round(float(g), 3) for g in pm["centers"]],
                 "min_per_mi": [round(float(b) * 1609.344 / 60, 2) for b in pm["base"]],
                 "n": pm["nbin"],
                 "off": [{"label": names_to_label(names[c]), "mult": round(float(pm["offtrail_mult"][c]), 2),
                          "n": int(pm["offtrail_n"][c])} for c in range(len(names))
                         if np.isfinite(pm["offtrail_mult"][c])],
                 "overall_off": round(pm["overall_off"], 2), "max_slope": round(pm["max_slope"]),
                 "n_chunks": pm["n_chunks"], "n_off": pm["n_off"]},
        "stats": {"front": int(classified.frontrow.sum()), "done": done_ct,
                  "left": int(classified.frontrow.sum()) - done_ct, "n_planned": len(planned),
                  "max_day_h": MAX_DAY_H,
                  "unrouted": [_pname(todo.loc[i]) for i in todo.index
                               if i not in {int(x) for p in planned.peaks for x in p.split(",")}]},
        "map_url": SITE_MAP_URL,
    })
    return classified


_RESTRICTED = None


def _restricted_note(geom):
    """Name of the restricted area `geom` touches ('' if none)."""
    global _RESTRICTED
    if _RESTRICTED is None:
        import geopandas as gpd
        _RESTRICTED = gpd.read_file(config.RESTRICTED_GEOJSON) if config.RESTRICTED_GEOJSON.exists() else []
    for _, a in (_RESTRICTED.iterrows() if len(_RESTRICTED) else []):
        if a.geometry.intersects(geom):
            return f"{a['name']} (Army: access restricted)"
    return ""


def summit_zones(classified):
    """Per first-row peak, the ground that counts as 'on top': within
    tracks.SUMMIT_RADIUS_M of the summit and within tracks.SUMMIT_DZ_M of its height
    (the same test tracks.match applies), as a WGS84 polygon. The site matches
    uploaded runs against these, so it needs no DEM."""
    import rasterio
    from rasterio.features import shapes
    from rasterio.windows import Window
    from shapely.geometry import shape
    from shapely.ops import unary_union, transform as shp_transform
    from pyproj import Transformer
    out = {}
    with rasterio.open(config.DEM_TIF) as dem:
        to_dem = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
        to_wgs = Transformer.from_crs(dem.crs, "EPSG:4326", always_xy=True)
        for i, p in classified[classified.frontrow].iterrows():
            mx, my = to_dem.transform(p.lon, p.lat)
            r, c = dem.index(mx, my)
            k = 12   # cells; > SUMMIT_RADIUS_M at ~26 m and the latitude stretch of 3857
            win = Window(c - k, r - k, 2 * k + 1, 2 * k + 1)
            z = dem.read(1, window=win, boundless=True, fill_value=-9999)
            wt = dem.window_transform(win)
            rr, cc = np.mgrid[0:z.shape[0], 0:z.shape[1]]
            xs, ys = rasterio.transform.xy(wt, rr.ravel(), cc.ravel())
            lon, lat = to_wgs.transform(np.asarray(xs), np.asarray(ys))
            ux, uy = terrain._TO_UTM.transform(lon, lat)
            sx, sy = terrain._TO_UTM.transform(p.lon, p.lat)
            near = (np.hypot(ux - sx, uy - sy) <= T.SUMMIT_RADIUS_M).reshape(z.shape)
            mask = near & (z >= p.summit_elev_m - T.SUMMIT_DZ_M)
            if not mask.any():
                continue
            polys = [shape(g) for g, v in shapes(mask.astype(np.uint8), mask=mask, transform=wt) if v]
            g = shp_transform(lambda x, y, z=None: to_wgs.transform(x, y), unary_union(polys))
            out[int(i)] = g.simplify(0.00005).__geo_interface__
    return out


def _site_seed(classified, pub, path):
    zones = summit_zones(classified)
    peaks = []
    for i, p in classified.iterrows():
        peaks.append({
            "peak_id": int(i), "name": _pname(p) if isinstance(p.get("name"), str) and p.get("name") else None,
            "lat": round(float(p.lat), 6), "lon": round(float(p.lon), 6),
            "elev_ft": round(float(p.elev_ft), 1), "prom_ft": round(float(p.prom_ft), 1),
            "prom_kirmse_ft": None if not np.isfinite(p.get("prom_kirmse_ft") or np.nan) else round(float(p.prom_kirmse_ft), 1),
            "saddle_lat": float(p.saddle_lat) if np.isfinite(p.saddle_lat) else None,
            "saddle_lon": float(p.saddle_lon) if np.isfinite(p.saddle_lon) else None,
            "frontrow": bool(p.frontrow), "frame_limited": bool(p.frame_limited),
            "block_kind": p.block_kind or None, "nearest_i90_m": float(p.nearest_i90_m),
            "summit_elev_ft": round(float(p.summit_elev_m) / 0.3048, 1),
            "summit_zone": zones.get(int(i)),
        })
    tracks, summits = [], []
    for i, r in pub.iterrows():
        if str(r.act_id).startswith("site-"):    # uploaded on the site: already in Supabase
            continue
        pk = [int(x) for x in r.peaks.split(",")]
        tracks.append({"key": f"strava-{r.act_id}", "source": "strava", "name": r["name"],
                       "run_date": _iso(r["date"]), "dist_mi": r.dist_mi,
                       "gain_ft": None if r.gain_ft is None or not np.isfinite(r.gain_ft) else float(r.gain_ft),
                       "peaks": pk, "geojson": _round_geom(r.geometry.__geo_interface__)})
        for pid in pk:
            manual = any(classified.loc[pid, "name"] == n and r["name"] == a
                         for n, a in config.MANUAL_SUMMITS.items())
            summits.append({"peak_id": pid, "track_key": f"strava-{r.act_id}",
                            "how": "manual" if manual else "gps", "summit_date": _iso(r["date"])})
    path.write_text(json.dumps({"peaks": peaks, "tracks": tracks, "summits": summits}))
    print(f"[site] wrote {path} ({len(peaks)} peaks, {len(zones)} summit zones, {len(tracks)} runs)")


def _round_geom(g, nd=5):
    def r(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def _iso(s):
    from datetime import datetime
    s = str(s)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.strptime(", ".join(s.split(", ")[:2]), "%b %d, %Y").date().isoformat()


def names_to_label(key):
    return S.CLASS_INFO[key][0]


def _pname(p):
    n = p.get("name")
    return n if isinstance(n, str) and n else f"Pt {p['elev_ft']:.0f}"


def _date(s):
    s = str(s)
    if s[:4].isdigit():
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%b %-d, %Y")
    return ", ".join(s.split(", ")[:2])


def _routes_gpx(planned, path):
    from xml.sax.saxutils import escape
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="i90peaks" xmlns="http://www.topografix.com/GPX/1/1">']
    for _, r in planned.iterrows():
        pts = "".join(f'<trkpt lat="{y:.6f}" lon="{x:.6f}"/>' for x, y in r.geometry.coords)
        out.append(f"<trk><name>{escape(r['name'])}</name><desc>{escape(r.region)}, ~{r.est_hours} h</desc>"
                   f"<trkseg>{pts}</trkseg></trk>")
    out.append("</gpx>")
    path.write_text("\n".join(out))
