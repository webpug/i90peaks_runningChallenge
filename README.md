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

**Far lowland hills don't count.** Across the flat Puget lowland nothing ≥ 250 ft stands
between I-90 and hills 5–18 mi away (Shoreline, Bothell, Federal Way), so the topological
rule alone would count them. A first-row peak whose summit is below 1,500 ft must be
within 4 mi of the freeway (the data has a natural gap between 3.4 and 4.6 mi); 15 hills
are excluded this way and shown on the map as "not counted".

Result: **135 first-row peaks** out of 1,172 qualifying peaks in the frame. Granite,
McClellan Butte, Silver, Guye and Kendall are in; Mount Stuart, Chair Peak and Rainier are out.
I-90 is clipped at the Vantage bridge and east-bank peaks are excluded.

Six first-row peaks south of the Kittitas valley (incl. Pt 3752 and Pt 3153) are on the
**Yakima Training Center** (US Army, access restricted). They still count; the map and
the plan flag them (`data/raw/restricted_areas.geojson`, OSM boundary via Nominatim).

## 2 · Completed summits

**Going forward, runs are uploaded on the map** (theblacks.ai/i90peaks → "+ Add runs"):
export the track from CalTopo as GeoJSON and drop it in. The site matches it against
each first-row peak's *summit zone* (below), stores only the privacy-trimmed line in
Supabase and checks the peaks off; hand-confirmed summits can be marked from a peak's card.
`python run.py` pulls those uploads back in (`config.SITE_STATE_URL`) for the similarity
analysis and the pace model.

The historical Strava bulk export (`activities/` + `activities.csv`) and CalTopo JSON in
`data/raw/strava/` are still read. Only **runs** count (Run, Trail Run): no hikes,
skiing (backcountry included), bikes or motors. A run counts for a peak when it passes
within 120 m of the summit **on ground (DEM) within 40 ft of summit height**; that
tolerates GPS/DEM offsets but not a trail contouring below the top. The ground that
passes this test is exported per peak as its summit zone. `config.MANUAL_SUMMITS`
records summits the GPS can't show (Mount Washington on "Two pugs and five peaks").

Published tracks drop everything inside the athlete's privacy zones (+150 m) and the
first/last 300 m of every run; the site applies the same rule to uploads
(`I90_PRIVACY_ZONES` on Railway).

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

- **Pace model** from the athlete's own timed runs: on-trail pace by DEM grade,
  off-trail slowdown per terrain type as the *mean* time ratio (time adds up; on/off
  trail = within 25 m of OSM trails/roads), and steepest ground travelled (routing is
  capped at 45°).
- **Router**: anisotropic least-time Dijkstra on a 40 m grid. Every outing starts on a
  public road ≥ 250 ft below its lowest summit. Neighbouring peaks are chained when that
  beats separate trips and the day stays ≤ 6 h moving (≈ 1.25× the longest peak day so far).
- **Fallback** for peaks that search can't reach: a 16 km search window and a 300 m
  summit-scramble allowance (Bryant Peak's summit block is > 60° on the DEM). These
  outings are flagged "hand-check" and can be refined in the map's route tool.
- Each planned outing reports its distance, gain, predicted time, off-trail share and
  terrain mix, plus the completed run with the closest AlphaEarth fingerprint.

## Outputs (`data/processed/`)

| File | |
|---|---|
| `i90_app.html` | the map: first-row peaks, summit caps, done peaks, tracks, planned routes, GPX/GeoJSON export |
| `similarity.html` | AlphaEarth route similarity, planned routes, pace model |
| `site_seed.json` | peaks + summit zones, published runs and summits for the site's Supabase tables |
| `planned_routes.gpx` / `.geojson` | planned outings (CalTopo-ready) |
| `prominence.png` / `.json` | the map's "prominence islands" layer: each cell assigned to the innermost island (ground above a peak's key col) containing it, stored as an index PNG (RGB = peak id + 1) that the map colours by prominence and reads back on hover (`promraster.py`) |
| `i90_frontrow_peaks.gpx`, `i90_peaks.geojson`, `peaks_classified.gpkg`, `summit_caps.gpkg` | peak data |

To publish, copy `i90_app.html`, `similarity.html`, `planned_routes.gpx`,
`prominence.png` and `site_seed.json` into `webpug/theblacks.ai/content/i90peaks/`, run
`railway run node scripts/i90peaks-import.mjs` there, and push (Railway deploys `main`).

`scripts/home_background.py ../theblacks.ai/public/home` renders the theblacks.ai home
page background (a dithered hillshade of the corridor and its prominence-island colouring).

## The map's route tool

"✎ Draw a route" (or "Edit in the route tool" on any planned or drawn route) is a
CalTopo-style line editor: click to add points, drag to move, drag a faint midpoint to
insert, double-/right-click to delete, Ctrl+Z to undo, snapping to summits. It shows
distance, gain/loss and an elevation profile (AWS terrain tiles, read in the browser)
and a time estimate from the pace model, exports GPX, and (signed in) saves to Supabase.

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
