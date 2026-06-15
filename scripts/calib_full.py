"""Calibrate descent tolerance on the FULL corridor and inspect spatial sanity."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd, numpy as np
from src.i90peaks import config, frontrow, highway

ours = gpd.read_file(config.INTERIM / "peaks_computed.gpkg")
hw = highway.fetch_i90()
hw_m = hw.to_crs(3857)
hw_union = hw_m.geometry.union_all()

def dist_to_i90(gdf):
    g = gdf.to_crs(3857)
    return g.geometry.apply(lambda p: p.distance(hw_union)) / 1000.0  # km (3857, ~1.48x inflated)

RAINIER = (46.8529, -121.7604)
for T in [30.0, 76.2]:
    res = frontrow.classify(dem_path=config.DEM_TIF, highway=hw, peaks=ours, descent_tol_m=T)
    fr = res[res.frontrow].copy()
    fr["km"] = dist_to_i90(fr).values
    # nearest computed peak to Rainier summit + its class
    d = np.hypot(res.lat - RAINIER[0], res.lon - RAINIER[1])
    rain = res.iloc[d.idxmin()]
    print(f"\n==== T={T:.1f} m ({T/0.3048:.0f} ft): {len(fr)} first row / {len(res)} ====")
    print(f"  Rainier-nearest peak ({rain.elev_ft:.0f} ft): frontrow={bool(rain.frontrow)}")
    print(f"  first-row dist-to-I90 (3857 km, ~1.48x): "
          f"median {fr.km.median():.1f}, 90th pct {fr.km.quantile(.9):.1f}, max {fr.km.max():.1f}")
    print(f"  first-row by prominence band:")
    for lo, hi in [(250,500),(500,1000),(1000,2000),(2000,1e9)]:
        n = ((fr.prom_ft>=lo)&(fr.prom_ft<hi)).sum()
        print(f"    {lo:>4}-{hi if hi<1e9 else '+':>4} ft prom: {n}")
    print("  top first-row peaks:")
    print(fr.sort_values('prom_ft',ascending=False)[['lat','lon','elev_ft','prom_ft','km']].head(12).to_string(index=False))
