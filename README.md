# I-90 First-Row Peaks

A running challenge: summit every peak with **≥ 250 ft of prominence** that stands
**directly adjacent** to I-90 between **Seattle and the Columbia River**, meaning no
other qualifying peak or ridge sits between it and the highway, at any distance.

Live: **[theblacks.ai/i90peaks](https://theblacks.ai/i90peaks)** (map) ·
**[theblacks.ai/i90peaks/similarity](https://theblacks.ai/i90peaks/similarity)** (route analysis & plan)

```
python run.py      # ~5 min with caches warm
```

## 1 · Which peaks count

**Prominence.** Computed from our own DEM (AWS Terrain Tiles, z12 ≈ 26 m) with a
descending union-find sweep (topological persistence, numba-compiled, ~20 s for 33 M
cells). It's cross-checked against the Kirmse & de Ferranti global list: 93% of
reference peaks match within 300 m, median position error 26 m, median prominence
difference −7 ft. Near-threshold peaks (180–250 ft on our DEM) are kept when Kirmse
puts them at ≥ 250 ft; Mount Si is the classic case.

**"Directly adjacent."** A qualifying peak's **cap** is the part of its massif within
250 ft of its summit: the peak *plus connected ridges that don't descend more than 250 ft*.
Caps never overlap (if two touched, the lower peak would have < 250 ft of prominence).
A peak **P is first row** iff some straight line from a point on I-90 toward P reaches
cap(P) while never crossing

1. another qualifying peak's cap,
2. an **intervening ridge**: a point that rises ≥ 250 ft above everything before it on
   the line and is then followed by a ≥ 250 ft drop (a ridge that *doesn't* drop 250 ft
   before P is just P's own ridge reaching toward the road), or
3. ground higher than P itself.

Result: **150 first-row peaks** out of 1,172 qualifying peaks in the frame. Granite,
McClellan Butte, Silver, Guye and Kendall are in; Mount Stuart, Chair Peak and Rainier are out.
I-90 is clipped at the Vantage bridge and east-bank peaks are excluded.

**Judgment call to review:** across the flat Puget lowland a few hills 10–18 mi from
the freeway (Shoreline, Bothell, Federal Way) qualify literally, because nothing ≥ 250 ft
stands in between. They show their distance in the app.

## 2 · Completed summits

Put a Strava bulk export's `activities/` + `activities.csv` (and any CalTopo GeoJSON
tracks) in `data/raw/strava/`. An activity counts when it is **on foot and human-powered**
(Run, Trail Run, Hike, Walk, Backcountry Ski, Snowshoe; no lifts, bikes or motors) and
passes within 120 m of a first-row summit **on ground (DEM) within 40 ft of summit
height**. That tolerates GPS/DEM offsets but not a trail contouring below the top.

Published tracks drop everything inside the athlete's Strava privacy zones (+150 m) and
the first/last 300 m of every run.

## 3 · Route similarity: AlphaEarth embeddings

Following `webpug/geospatial/alpha_earth_embeddings_demo.ipynb`: the 2025 AlphaEarth
Foundations annual embeddings (= Earth Engine `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`),
read from the public Source Cooperative COG mirror (no Earth Engine account, no track
coordinates sent anywhere) into a 40 m corridor mosaic. Each route is sampled every 40 m;

- **fingerprint** = mean vector − corridor mean, normalised → cosine similarity matrix;
- **terrain mix** = k-means (k = 10) "terrain types" fit on corridor pixels, named from
  their elevation/slope/location statistics;
- **colour barcode** = top-3 PCA directions as RGB along the route.

## 4 · Predicted routes

- **Pace model** from the athlete's own timed activities: on-trail pace by DEM grade,
  off-trail slowdown per terrain type (on/off trail = within 25 m of OSM trails/roads),
  and steepest ground travelled (routing is capped at 45°).
- **Router**: anisotropic least-time Dijkstra on a 40 m grid. Every outing starts on a
  public road ≥ 250 ft below its lowest summit. Neighbouring peaks are chained when that
  beats separate trips and the day stays ≤ 6 h moving (≈ 1.25× the longest peak day so far).
- Each planned outing reports its distance, gain, predicted time, off-trail share and
  terrain mix, plus the completed run with the closest AlphaEarth fingerprint.

## Outputs (`data/processed/`)

| File | |
|---|---|
| `i90_app.html` | the map: first-row peaks, summit caps, done peaks, tracks, planned routes, GPX/GeoJSON export |
| `similarity.html` | AlphaEarth route similarity, planned routes, pace model |
| `planned_routes.gpx` / `.geojson` | planned outings (CalTopo-ready) |
| `i90_frontrow_peaks.gpx`, `i90_peaks.geojson`, `peaks_classified.gpkg`, `summit_caps.gpkg` | peak data |

To publish, copy `i90_app.html`, `similarity.html` and `planned_routes.gpx` into
`webpug/theblacks.ai/content/i90peaks/` and push (Railway deploys `main`).

## Modules (`src/i90peaks/`)

`dem` terrain tiles → GeoTIFF · `prominence` our prominence · `peaks`/`validate` Kirmse
check + reconcile · `highway`/`osm`/`names` OpenStreetMap via Overpass · `adjacency`
caps + first-row test · `tracks` activity parsing, summit matching, privacy trim ·
`embeddings` AlphaEarth mosaic · `similarity` fingerprints & terrain types · `planner`
pace model + router · `site`/`webapp`/`analysis_page` pages · `export`/`viz` extras.

## Data sources

AWS Terrain Tiles · Kirmse & de Ferranti prominence · © OpenStreetMap contributors ·
The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google
DeepMind (CC-BY 4.0), via Source Cooperative (`tge-labs/aef`).
