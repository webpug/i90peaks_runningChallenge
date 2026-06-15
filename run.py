"""End-to-end pipeline: DEM -> our prominence -> first-row classification.

    python run.py

Steps:
  1. Build the corridor DEM from terrain tiles.
  2. Compute peaks + prominence ourselves from the DEM (our source of truth).
  3. Cross-check against the Kirmse reference download.
  4. Fetch the I-90 centerline.
  5. Classify each peak as first-row vs occluded by topology.
  6. Write GeoPackage + interactive HTML map.
"""
from src.i90peaks import (config, dem, prominence, peaks as kirmse_mod, highway,
                          profile_clf, names, validate, viz, export, webapp)


def main():
    print("==[1/7] DEM ==")
    dem.build_dem()

    print("\n==[2/7] prominence (our GIS) ==")
    ours = prominence.compute_peaks()

    print("\n==[3/7] peak names (OSM) ==")
    ours = names.attach_names(ours)

    print("\n==[4/7] cross-check vs Kirmse ==")
    kirmse = kirmse_mod.load_corridor_peaks()
    validate.report(ours, kirmse)

    print("\n==[5/7] I-90 centerline ==")
    hw = highway.fetch_i90()

    print("\n==[6/7] first-row classification (profile to I-90) ==")
    classified, details = profile_clf.classify(dem_path=config.DEM_TIF, highway=hw, peaks=ours)
    classified.to_file(config.RESULT_GPKG, driver="GPKG")
    print(f"  wrote {config.RESULT_GPKG}")

    print("\n==[7/7] map + exports ==")
    viz.make_map(classified, hw)
    webapp.build_app(classified, hw, details=details)
    export.export_all(classified)

    n_fr = int(classified.frontrow.sum())
    print(f"\nDONE: {n_fr} first-row peaks of {len(classified)} (>=250 ft prom) "
          f"along I-90, Seattle -> Columbia River.")


if __name__ == "__main__":
    main()
