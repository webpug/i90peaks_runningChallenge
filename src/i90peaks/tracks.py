"""Load completed GPS tracks, keep the ones relevant to the challenge, mark summits.

Sources (all under data/raw/strava/):
  * a Strava bulk export's `activities/` folder (+ `activities.csv` for names/types):
    .gpx, .fit, .tcx(.gz)
  * CalTopo GeoJSON exports (*.json) dropped next to it, e.g. Kent_spurs.json

A track is RELEVANT iff it is a human-powered, on-foot ascent (ON_FOOT types)
and tops out on at least one first-row peak: some track point within
SUMMIT_RADIUS_M of the summit that stands (on the DEM) within SUMMIT_DZ_M of the
summit elevation -- GPS + 26 m DEM cells blur position by tens of metres, but a
point on the summit block is still at summit height, while a trail traversing
below the top is not. Those peaks are marked done. Lift-served skiing,
bikes and motorised activities never count.
"""
from __future__ import annotations

import gzip
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString

from . import config

STRAVA_DIR = config.RAW / "strava"
TRACKS_GPKG = config.PROCESSED / "tracks_relevant.gpkg"
SUMMIT_RADIUS_M = 120.0
SUMMIT_DZ_M = 40 * 0.3048
ON_FOOT = {"Run", "Trail Run", "Hike", "Walk", "Backcountry Ski", "Snowshoe", ""}
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)


# ---------------------------------------------------------------------------
# Parsers -> [(lon, lat, ele_m|nan, unix_s|nan)] + start time
# ---------------------------------------------------------------------------
def _epoch(s):
    if not s:
        return np.nan
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return np.nan


def _gpx(path):
    root = ET.parse(path).getroot()
    ns = {"g": root.tag.split("}")[0][1:]} if root.tag.startswith("{") else {"g": ""}
    pts, t0 = [], None
    for pt in root.iter(f"{{{ns['g']}}}trkpt"):
        e = pt.find("g:ele", ns)
        t = pt.find("g:time", ns)
        pts.append((float(pt.get("lon")), float(pt.get("lat")),
                    float(e.text) if e is not None else np.nan, _epoch(t.text if t is not None else None)))
        if t0 is None and t is not None:
            t0 = t.text
    return pts, t0


def _tcx(path):
    raw = gzip.open(path).read() if str(path).endswith(".gz") else open(path, "rb").read()
    root = ET.fromstring(raw.strip())
    pts, t0 = [], None
    for tp in root.iter():
        if not tp.tag.endswith("Trackpoint"):
            continue
        lat = lon = ele = tt = None
        for ch in tp.iter():
            tag = ch.tag.split("}")[-1]
            if tag == "LatitudeDegrees": lat = float(ch.text)
            elif tag == "LongitudeDegrees": lon = float(ch.text)
            elif tag == "AltitudeMeters": ele = float(ch.text)
            elif tag == "Time":
                tt = ch.text
                t0 = t0 or tt
        if lat is not None:
            pts.append((lon, lat, ele if ele is not None else np.nan, _epoch(tt)))
    return pts, t0


def _fit(path):
    import fitparse
    raw = gzip.open(path).read() if str(path).endswith(".gz") else open(path, "rb").read()
    f = fitparse.FitFile(raw)
    pts, t0 = [], None
    for m in f.get_messages("record"):
        v = m.get_values()
        if v.get("position_lat") is None:
            continue
        lat = v["position_lat"] * (180 / 2 ** 31)
        lon = v["position_long"] * (180 / 2 ** 31)
        ele = v.get("enhanced_altitude", v.get("altitude"))
        ts = v.get("timestamp")
        pts.append((lon, lat, float(ele) if ele is not None else np.nan,
                    ts.replace(tzinfo=timezone.utc).timestamp() if ts else np.nan))
        if t0 is None and v.get("timestamp"):
            t0 = v["timestamp"].isoformat()
    return pts, t0


def _caltopo(path):
    out = []
    for f in json.load(open(path))["features"]:
        g = f["geometry"]
        lines = [g["coordinates"]] if g["type"] == "LineString" else (
            g["coordinates"] if g["type"] == "MultiLineString" else [])
        for ln in lines:
            pts = [(c[0], c[1], c[2] if len(c) > 2 else np.nan,
                    c[3] / 1000 if len(c) > 3 else np.nan) for c in ln]
            t0 = None
            if ln and len(ln[0]) > 3:
                t0 = datetime.fromtimestamp(ln[0][3] / 1000, timezone.utc).isoformat()
            out.append((f["properties"].get("title") or Path(path).stem, pts, t0))
    return out


def load_all(src=STRAVA_DIR):
    """Yield dicts {id, name, type, date, pts} for every parsable activity."""
    meta = {}
    csv = src / "activities.csv"
    if csv.exists():
        df = pd.read_csv(csv)
        df = df.loc[:, ~df.columns.duplicated()]
        for _, r in df.iterrows():
            if isinstance(r.get("Filename"), str):
                meta[Path(r["Filename"]).name] = r
    for p in sorted((src / "activities").glob("*")):
        try:
            if p.name.endswith((".gpx", ".gpx.gz")):
                pts, t0 = _gpx(gzip.open(p) if p.name.endswith(".gz") else p)
            elif ".tcx" in p.name:
                pts, t0 = _tcx(p)
            elif ".fit" in p.name:
                pts, t0 = _fit(p)
            else:
                continue
        except Exception as e:      # noqa: BLE001 -- one corrupt file shouldn't stop the batch
            print(f"[tracks] skip {p.name}: {e}")
            continue
        m = meta.get(p.name)
        yield {"id": p.name.split(".")[0],
               "name": str(m["Activity Name"]) if m is not None else p.stem,
               "desc": str(m.get("Activity Description") or "") if m is not None else "",
               "type": str(m["Activity Type"]) if m is not None else "",
               "date": str(m["Activity Date"]) if m is not None else (t0 or ""),
               "pts": pts}
    for p in sorted(src.glob("*.json")):
        for i, (name, pts, t0) in enumerate(_caltopo(p)):
            yield {"id": f"caltopo-{p.stem}-{i}", "name": name, "type": "Run",
                   "date": t0 or "", "pts": pts}


# ---------------------------------------------------------------------------
# Relevance + summit marking
# ---------------------------------------------------------------------------
def match(classified, src=STRAVA_DIR):
    """Return (classified + done/done_by, relevant-tracks GeoDataFrame)."""
    fr = classified[classified.frontrow]
    sx, sy = _TO_UTM.transform(fr.lon.values, fr.lat.values)
    stree = cKDTree(np.column_stack([sx, sy]))
    fr_idx = fr.index.to_numpy()

    import rasterio
    dem = rasterio.open(config.DEM_TIF)
    zdem = dem.read(1)
    to_dem = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
    s_elev = fr.summit_elev_m.to_numpy()

    w, s, e, n = config.BBOX
    rows, done_by, full = [], {}, {}
    n_total = 0
    for act in load_all(src):
        n_total += 1
        pts = np.asarray(act["pts"], dtype=float)
        if len(pts) < 10 or act["type"] not in ON_FOOT:
            continue
        inbox = (pts[:, 0] > w) & (pts[:, 0] < e) & (pts[:, 1] > s) & (pts[:, 1] < n)
        if not inbox.any():
            continue
        x, y = _TO_UTM.transform(pts[:, 0], pts[:, 1])
        hits = stree.query_ball_point(np.column_stack([x, y]), SUMMIT_RADIUS_M)
        cand = [(k, j) for k, h in enumerate(hits) for j in h]
        peaks_hit = set()
        if cand:
            k = np.array([c[0] for c in cand]); j = np.array([c[1] for c in cand])
            mx, my = to_dem.transform(pts[k, 0], pts[k, 1])
            r, c = rasterio.transform.rowcol(dem.transform, mx, my)
            z = zdem[np.clip(r, 0, zdem.shape[0] - 1), np.clip(c, 0, zdem.shape[1] - 1)]
            peaks_hit = {fr_idx[jj] for jj in j[z >= s_elev[j] - SUMMIT_DZ_M]}
        peaks_hit = sorted(peaks_hit)
        if not peaks_hit:
            continue
        date = act["date"][:12].strip()
        for pid in peaks_hit:
            done_by.setdefault(pid, []).append(date)
        dist_km = float(np.hypot(np.diff(x), np.diff(y)).sum() / 1000)
        ele = pts[:, 2]
        gain = float(np.nansum(np.clip(np.diff(_smooth(ele)), 0, None))) / 0.3048 \
            if np.isfinite(ele).sum() > 10 else np.nan
        rows.append({
            "act_id": act["id"], "name": act["name"], "type": act["type"], "date": act["date"],
            "peaks": ",".join(str(int(p)) for p in peaks_hit), "n_peaks": len(peaks_hit),
            "dist_mi": round(dist_km / 1.609344, 2), "gain_ft": round(gain) if np.isfinite(gain) else None,
            "geometry": LineString(pts[:, :2]).simplify(0.00003),
        })
        full[act["id"]] = pts
    tracks = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    out = classified.copy()
    out["done"] = [i in done_by for i in out.index]
    out["done_by"] = [done_by.get(i, []) for i in out.index]
    print(f"[tracks] {n_total} activities scanned -> {len(tracks)} relevant "
          f"(top out on a first-row peak); {len(done_by)} first-row peaks summited")
    return out, tracks, full


def privacy_trim(tracks, src=STRAVA_DIR, trim_ends_m=300.0, margin_m=150.0):
    """Copy of `tracks` safe to publish: drops points inside the athlete's Strava
    privacy zones (+ margin) and the first/last `trim_ends_m` of every track."""
    zones = []
    pz = src / "privacy_zones.csv"
    if pz.exists():
        for _, z in pd.read_csv(pz).iterrows():
            lat, lon = (float(v) for v in str(z["Latitude & Longitude"]).split(","))
            r = float(str(z["Radius"]).split()[0]) * (1000 if "kilomet" in str(z["Radius"]) else 1)
            zx, zy = _TO_UTM.transform(lon, lat)
            zones.append((zx, zy, r + margin_m))
    geoms = []
    for g in tracks.geometry:
        xy = np.asarray(g.coords)
        x, y = _TO_UTM.transform(xy[:, 0], xy[:, 1])
        d = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        keep = (d > trim_ends_m) & (d < d[-1] - trim_ends_m)
        for zx, zy, r in zones:
            keep &= np.hypot(x - zx, y - zy) > r
        # split into runs of kept points so no segment bridges a removed zone
        parts, cur = [], []
        for k, pt in zip(keep, xy):
            if k:
                cur.append(pt)
            elif cur:
                parts.append(cur); cur = []
        if cur:
            parts.append(cur)
        parts = [p for p in parts if len(p) > 1]
        geoms.append(MultiLineString(parts) if parts else None)
    out = tracks.copy()
    out["geometry"] = geoms
    return out[out.geometry.notna()]


def _smooth(z, k=5):
    z = np.where(np.isfinite(z), z, np.nan)
    s = pd.Series(z).interpolate(limit_direction="both").rolling(k, center=True, min_periods=1).mean()
    return s.to_numpy()
