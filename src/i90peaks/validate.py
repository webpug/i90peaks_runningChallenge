"""Cross-check our DEM-computed peaks against the Kirmse reference list."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from . import config


def _xy(gdf):
    m = gdf.to_crs("EPSG:3857")
    return np.column_stack([m.geometry.x.values, m.geometry.y.values])


def cross_check(ours, kirmse, match_radius_m: float = 300.0) -> dict:
    """Match each Kirmse peak to the nearest computed peak; report agreement."""
    ot, kt = _xy(ours), _xy(kirmse)
    tree = cKDTree(ot)
    dist, idx = tree.query(kt, k=1)
    matched = dist <= match_radius_m
    stats = {
        "kirmse_peaks": len(kirmse),
        "our_peaks": len(ours),
        "kirmse_matched": int(matched.sum()),
        "kirmse_unmatched": int((~matched).sum()),
        "match_rate": float(matched.mean()),
        "median_pos_err_m": float(np.median(dist[matched])) if matched.any() else None,
    }
    if matched.any():
        kp = kirmse.iloc[np.where(matched)[0]]["prom_ft"].values
        op = ours.iloc[idx[matched]]["prom_ft"].values
        stats["median_prom_diff_ft"] = float(np.median(op - kp))
        stats["mean_abs_prom_diff_ft"] = float(np.mean(np.abs(op - kp)))
    return stats


def report(ours, kirmse=None) -> None:
    from . import peaks as pk_mod
    kirmse = kirmse if kirmse is not None else pk_mod.load_corridor_peaks()
    s = cross_check(ours, kirmse)
    print("\n=== cross-check vs Kirmse ===")
    for k, v in s.items():
        print(f"  {k:>22}: {v}")
    print(f"  ({s['kirmse_unmatched']} Kirmse peaks with no computed match within 300 m "
          f"-- likely resolution/edge differences)")
