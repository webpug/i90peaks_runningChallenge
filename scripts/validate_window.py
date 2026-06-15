"""Quick correctness check on a small window around Snoqualmie Pass.

Builds a small DEM, computes prominence ourselves, classifies first-row, and
prints the most prominent peaks so we can eyeball them against known summits
(Snoqualmie Mtn ~6278 ft, Red Mtn ~5890, Kendall ~5784, Guye ~5168, etc.).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.i90peaks import config, dem, highway, prominence, frontrow

# Small test frame around Snoqualmie Pass (47.392, -121.413)
BBOX = (-121.55, 47.34, -121.28, 47.50)
ZOOM = 12
TIF = config.INTERIM / "dem_test_window.tif"

print("== building DEM ==")
dem.build_dem(bbox=BBOX, zoom=ZOOM, out_path=TIF, overwrite=False)

print("\n== computing prominence (our GIS) ==")
import src.i90peaks.prominence as P
pk = P.compute_peaks.__wrapped__ if hasattr(P.compute_peaks, "__wrapped__") else P.compute_peaks
peaks = prominence.compute_peaks(dem_path=TIF, prom_min_m=config.PROM_MIN_M, overwrite=True)
# redirect cache file name so we don't collide with full run
print(f"  -> {len(peaks)} peaks >= 250 ft prominence in window")
cols = ["lat", "lon", "elev_ft", "prom_ft"]
print(peaks[cols].head(15).to_string(index=False))

print("\n== fetching I-90 in window ==")
hw = highway.fetch_i90(bbox=BBOX, out_path=config.INTERIM / "i90_test_window.gpkg", overwrite=True)

print("\n== classifying first-row ==")
res = frontrow.classify(dem_path=TIF, highway=hw, peaks=peaks)
fr = res[res.frontrow].sort_values("prom_ft", ascending=False)
print(f"\nFIRST ROW peaks ({len(fr)}):")
print(fr[["lat", "lon", "elev_ft", "prom_ft", "barrier_above_m"]].head(20).to_string(index=False))
occ = res[~res.frontrow].sort_values("prom_ft", ascending=False)
print(f"\nOCCLUDED (top by prom, with barrier height above summit in m):")
print(occ[["lat", "lon", "elev_ft", "prom_ft", "barrier_above_m"]].head(10).to_string(index=False))
