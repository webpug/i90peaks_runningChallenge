"""Phase 2: completed tracks -> AlphaEarth similarity -> predicted routes -> pages.

    build_all(classified, highway, details, caps)

writes data/processed/
    i90_app.html        the map (done peaks, my tracks, planned routes)
    similarity.html     the AlphaEarth route-similarity analysis + route plan
    tracks_public.geojson, planned_routes.geojson, planned_routes.gpx
"""
from __future__ import annotations

import json
import pickle

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

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
    reg_order = {name: k for k, (_, name) in enumerate(REGIONS)}
    planned = planned.sort_values(["region", "est_hours"], key=lambda s: s.map(reg_order) if s.name == "region" else s)
    planned = planned.reset_index(drop=True)
    planned["route_id"] = planned.index

    # ---- publishable layers
    pub = T.privacy_trim(tracks)
    tracks_gj = json.loads(pub.assign(id=pub.index)[["id", "name", "date", "type", "dist_mi", "gain_ft", "geometry"]]
                           .assign(date=lambda d: d["date"].map(_date)).to_json())
    routes_gj = json.loads(planned[["route_id", "name", "region", "n_peaks", "dist_mi", "gain_ft", "est_hours",
                                    "off_trail_pct", "shuttle_mi", "like_run", "like_sim", "geometry"]].to_json())
    for f in routes_gj["features"]:
        p = f["properties"]
        p["desc"] = (f"{p['region']} · {p['dist_mi']} mi · {p['gain_ft']:,} ft · ~{p['est_hours']} h · "
                     f"{p['off_trail_pct']}% off-trail" + (f" · ends {p['shuttle_mi']} mi from start"
                                                         if p["shuttle_mi"] >= 1 else ""))
    (config.PROCESSED / "tracks_public.geojson").write_text(json.dumps(tracks_gj))
    (config.PROCESSED / "planned_routes.geojson").write_text(json.dumps(routes_gj))
    _routes_gpx(planned, config.PROCESSED / "planned_routes.gpx")

    links = [{"href": SITE_SIM_URL, "label": "Route similarity (AlphaEarth) →"},
             {"href": SITE_SIM_URL + "#plan", "label": "Planned routes →"}]
    webapp.build_app(classified, highway, details=details, caps=caps, tracks=tracks_gj,
                     routes=routes_gj, links=links)

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
