# I-90 First-Row Peaks

Map every peak with **≥ 250 ft of prominence** that is **directly adjacent** to
I-90 between **Seattle and the Columbia River** — where "directly adjacent" means
the *literal first row*: no ridge or higher peak stands between it and the
highway, regardless of distance.

This is phase 1 (mapping). Phase 2 will link the first-row peaks into trail-running
/ scrambling routes under physical-ability constraints.

## The idea

A peak **P** is *first row* if and only if you can travel from I-90 to P's summit
**without ever climbing higher than P itself** — i.e. the highway and the summit
lie in the same connected component of the terrain region `{elevation ≤ elev(P)}`.

- If a ridge or peak *higher than P* sits between P and the road, that barrier is
  excluded from the `≤ elev(P)` region, so the road can't reach P through it → **occluded**.
- If only *lower* saddles lie between → **first row**.

We compute, for every peak, the **minimum ceiling** `MR(P)` you must pass under to
reach it from the road (a minimax / sublevel-connectivity value) via one ascending
union-find sweep over the DEM. `MR(P) == elev(P)` ⇔ first row. `MR(P) − elev(P)` is
how far *above* the summit the blocking ridge sits (the "barrier height").

Prominence itself is also computed from our DEM, via the mirror-image *descending*
union-find sweep (topological persistence) — so the peak list is ours, at our
resolution, and the Kirmse global dataset is used only as an independent cross-check.

## Data sources (all open)

| What | Source | Notes |
|------|--------|-------|
| Terrain (DEM) | [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (terrarium) | No API key; resolution set by tile zoom (z12 ≈ 26 m). 3DEP 10 m is a planned high-res upgrade. |
| Prominence reference | [Kirmse & de Ferranti global prominence](https://www.andrewkirmse.com/prominence) | All peaks ≥ 100 ft prom; used to validate our computation. |
| I-90 centerline | OpenStreetMap via `osmnx` | |
| Peak names *(planned)* | USGS GNIS / OSM `natural=peak` | not yet joined |

## Pipeline

```
python run.py
```

1. `dem.py` — mosaic terrain tiles → corridor GeoTIFF
2. `prominence.py` — compute peaks + prominence ourselves (descending sweep)
3. `validate.py` — cross-check against Kirmse
4. `highway.py` — fetch I-90 from OSM
5. `frontrow.py` — classify first-row vs occluded (ascending sweep)
6. `viz.py` / `webapp.py` / `export.py` — outputs

### Outputs (`data/processed/`)

- `i90_app.html` — **interactive web app**: topo/satellite basemaps, prominence
  slider, occluded toggle, and in-browser **GPX / GeoJSON export of the visible
  peaks** (import straight into **CalTopo**).
- `peaks_classified.gpkg` — full classified table
- `i90_frontrow_peaks.gpx`, `i90_peaks.geojson` — CalTopo-ready exports

## Config

Corridor extent, prominence threshold, and DEM zoom live in `src/i90peaks/config.py`.

## Quick window test

```
python scripts/validate_window.py   # small Snoqualmie Pass frame, fast
```
