"""End-to-end pipeline: DEM -> our prominence -> first-row classification.

    python run.py

Steps:
  1. Build the corridor DEM from terrain tiles.
  2. Compute peaks + prominence ourselves from the DEM (our source of truth).
  3. Cross-check against the Kirmse reference download.
  4. Fetch the I-90 centerline.
  5. Classify each peak as first-row vs behind (summit caps + straight approaches).
  6. Write GeoPackage + interactive HTML map.
"""
import pickle

from src.i90peaks import (config, dem, prominence, peaks as kirmse_mod, highway,
                          adjacency, names, validate, viz, export, webapp)


def main():
    print("==[1/7] DEM ==")
    dem.build_dem()

    print("\n==[2/7] prominence (our GIS) ==")
    ours = prominence.compute_peaks(prom_min_m=config.PROM_SEARCH_FT * 0.3048)
    ours = ours[ours.lon < config.COLUMBIA_LON].reset_index(drop=True)   # west bank only

    print("\n==[3/7] peak names (OSM) ==")
    ours = names.attach_names(ours)

    print("\n==[4/7] cross-check vs Kirmse ==")
    kirmse = kirmse_mod.load_corridor_peaks()
    validate.report(ours[ours.prom_ft >= config.PROM_MIN_FT], kirmse)
    ours = validate.reconcile(ours, kirmse)

    print("\n==[5/7] I-90 centerline ==")
    hw = highway.fetch_i90()

    print("\n==[6/7] first-row classification (summit caps + approaches) ==")
    classified, details, caps = adjacency.classify(dem_path=config.DEM_TIF, highway=hw, peaks=ours)
    classified, details = adjacency.exclude_far_lowland(classified, details)
    classified.to_file(config.RESULT_GPKG, driver="GPKG")
    caps.to_file(config.CAPS_GPKG, driver="GPKG")
    with open(config.DETAILS_PKL, "wb") as fh:
        pickle.dump(details, fh)
    print(f"  wrote {config.RESULT_GPKG}, {config.CAPS_GPKG}")

    print("\n==[7/7] map + exports ==")
    viz.make_map(classified, hw)
    webapp.build_app(classified, hw, details=details, caps=caps)
    export.export_all(classified)

    # Phase 2 (needs data/raw/strava/: a Strava bulk export's activities/ + CalTopo JSON)
    if (config.RAW / "strava").exists():
        from src.i90peaks import site
        classified = site.build_all(classified, hw, details, caps)

    n_fr = int(classified.frontrow.sum())
    n_done = int(classified.get("done", classified.frontrow & False)[classified.frontrow].sum())
    print(f"\nDONE ({n_done} summited): {n_fr} first-row peaks of {len(classified)} (>=250 ft prom) "
          f"along I-90, Seattle -> Columbia River.")


if __name__ == "__main__":
    main()
