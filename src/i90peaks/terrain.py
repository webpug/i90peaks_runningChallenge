"""DEM sampling helpers (elevation + slope at lon/lat) and route densification."""
from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer

from . import config

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
_FROM_UTM = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True)


class DEM:
    def __init__(self, path=config.DEM_TIF):
        with rasterio.open(path) as src:
            self.z = src.read(1).astype(np.float32)
            self.inv = ~src.transform
            px = src.transform.a
            self.nodata = src.nodata
        self.to = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        # ground cell size varies with latitude in web mercator; use the corridor mid-lat
        g = px * np.cos(np.radians((config.SOUTH + config.NORTH) / 2))
        gy, gx = np.gradient(np.where(self.z == self.nodata, np.nan, self.z), g)
        self.slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)

    def _rc(self, lon, lat):
        x, y = self.to.transform(np.asarray(lon), np.asarray(lat))
        c, r = self.inv * (x, y)
        return (np.clip(r.astype(int), 0, self.z.shape[0] - 1),
                np.clip(c.astype(int), 0, self.z.shape[1] - 1))

    def elev(self, lon, lat):
        r, c = self._rc(lon, lat)
        return self.z[r, c]

    def slope_deg(self, lon, lat):
        r, c = self._rc(lon, lat)
        return self.slope[r, c]


def densify(lonlat: np.ndarray, step_m: float = 40.0):
    """Resample a lon/lat polyline at ~step_m spacing. Returns (lon, lat, dist_m)."""
    x, y = _TO_UTM.transform(lonlat[:, 0], lonlat[:, 1])
    d = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    if d[-1] == 0:
        return lonlat[:1, 0], lonlat[:1, 1], np.array([0.0])
    s = np.arange(0, d[-1], step_m)
    xs, ys = np.interp(s, d, x), np.interp(s, d, y)
    lon, lat = _FROM_UTM.transform(xs, ys)
    return np.asarray(lon), np.asarray(lat), s
