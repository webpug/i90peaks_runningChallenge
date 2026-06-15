"""Download the Kirmse global prominence dataset and clip it to the corridor.

Global file: one peak per line, comma-separated, elevations in FEET:
    lat, lon, elevation_ft, key_saddle_lat, key_saddle_lon, prominence_ft
Sorted by decreasing prominence. We stream it (it is large) and keep only rows
inside the bbox with prominence >= PROM_MIN_FT.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from . import config

_DOWNLOAD = config.RAW / "kirmse_download.bin"


def _download_raw() -> Path:
    """Fetch the dataset from Google Drive (cached). Returns path to a text file.

    The dataset lives in an old resourcekey-protected Drive file that gdown can't
    parse. The modern ``drive.usercontent.google.com/download`` endpoint with
    ``confirm=t`` + ``resourcekey`` serves the bytes directly.
    """
    if config.KIRMSE_RAW.exists():
        return config.KIRMSE_RAW

    if not _DOWNLOAD.exists():
        url = ("https://drive.usercontent.google.com/download"
               f"?id={config.KIRMSE_DRIVE_ID}&export=download&confirm=t"
               f"&resourcekey={config.KIRMSE_RESOURCE_KEY}")
        print("[peaks] downloading Kirmse dataset from Drive (~111 MB, one-time)...")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(_DOWNLOAD, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)

    # Unwrap if it's a zip; otherwise it's already the text file.
    with open(_DOWNLOAD, "rb") as fh:
        magic = fh.read(2)
    if magic == b"PK":
        with zipfile.ZipFile(_DOWNLOAD) as zf:
            inner = max(zf.infolist(), key=lambda i: i.file_size)
            print(f"[peaks] extracting {inner.filename} ({inner.file_size/1e6:.0f} MB)")
            with zf.open(inner) as src, open(config.KIRMSE_RAW, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    else:
        _DOWNLOAD.replace(config.KIRMSE_RAW)
    return config.KIRMSE_RAW


def load_corridor_peaks(overwrite: bool = False) -> gpd.GeoDataFrame:
    """Return peaks within the bbox with prominence >= threshold (cached)."""
    if config.PEAKS_CORRIDOR.exists() and not overwrite:
        print(f"[peaks] cached: {config.PEAKS_CORRIDOR}")
        return gpd.read_file(config.PEAKS_CORRIDOR)

    raw = _download_raw()
    w, s, e, n = config.BBOX
    rows = []
    with open(raw, "r") as fh:
        for line in fh:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                lat = float(parts[0]); lon = float(parts[1]); elev = float(parts[2])
                ks_lat = float(parts[3]); ks_lon = float(parts[4]); prom = float(parts[5])
            except ValueError:
                continue
            if prom < config.PROM_MIN_FT:
                continue
            if not (w <= lon <= e and s <= lat <= n):
                continue
            rows.append((lat, lon, elev, prom, ks_lat, ks_lon))

    df = pd.DataFrame(rows, columns=["lat", "lon", "elev_ft", "prom_ft",
                                     "ksaddle_lat", "ksaddle_lon"])
    gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)],
                           crs="EPSG:4326")
    gdf = gdf.sort_values("prom_ft", ascending=False).reset_index(drop=True)
    gdf["peak_id"] = gdf.index
    gdf.to_file(config.PEAKS_CORRIDOR, driver="GPKG")
    print(f"[peaks] {len(gdf)} peaks >= {config.PROM_MIN_FT:.0f} ft prom in corridor "
          f"-> {config.PEAKS_CORRIDOR}")
    return gdf


if __name__ == "__main__":
    load_corridor_peaks()
