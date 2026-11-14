"""NASADEM 1-arcsecond (~30 m) elevation → elevation, slope, aspect, and low-spot indicator for the parcel.

Tiles (≈12 MB zip each) are downloaded once from LP DAAC and cached on disk.
"""
import math
import threading

import numpy as np
from shapely.geometry import mapping

from ..core import CACHE_DIR, Query, clean, earthdata_fs, read_window, result, stac_search, stats

TILE_DIR = CACHE_DIR / "nasadem"
_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()


def _tile_name(lat: float, lon: float) -> str:
    la, lo = math.floor(lat), math.floor(lon)
    return f"{'n' if la >= 0 else 's'}{abs(la):02d}{'e' if lo >= 0 else 'w'}{abs(lo):03d}"


def _tile(lat: float, lon: float):
    name = _tile_name(lat, lon)
    path = TILE_DIR / f"NASADEM_HGT_{name}.zip"
    with _glock:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:
        if not path.exists():
            if not (-56 <= lat < 60):
                return None
            from datetime import date

            from shapely.geometry import Point

            items = stac_search(["NASADEM_HGT_001"], mapping(Point(lon, lat)), date(2000, 1, 1), date(2001, 12, 31), limit=5)
            href = next((a["href"] for it in items for a in it["assets"].values() if a["href"].endswith(f"{name}.zip")), None)
            if not href:
                return None
            TILE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            earthdata_fs().get_file(href, str(tmp))
            tmp.rename(path)
    return f"/vsizip/{path}/{name}.hgt"


def fetch(parcel, q: Query) -> dict:
    lat, lon = parcel.centroid
    src = _tile(lat, lon)
    if src is None:
        return result(scale="field", resolution_m=30, source="NASADEM", status="unavailable",
                      note="NASADEM covers 56°S–60°N only.")
    # read with ~300 m of surroundings to compute slope and the low-spot indicator
    elev, inside, wt, _ = read_window(src, parcel.geometry, pad_pixels=10)
    elev[elev < -500] = np.nan
    res_deg = abs(wt.a)
    dy = res_deg * 111_320
    dx = dy * math.cos(math.radians(lat))
    gy, gx = np.gradient(elev, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(-gx, gy)) + 360) % 360  # 0 = north-facing (downslope direction), clockwise
    n = int(inside.sum())

    e = stats(elev, inside, n)
    s = stats(slope, inside, n)
    surround = elev[~inside & np.isfinite(elev)]
    rel = e["mean"] - float(surround.mean()) if surround.size and e["mean"] is not None else None
    asp = aspect[inside & np.isfinite(aspect)]
    mean_aspect = float(np.degrees(np.arctan2(np.sin(np.radians(asp)).mean(), np.cos(np.radians(asp)).mean())) % 360) if asp.size else None
    steep = float((slope[inside] > 8).mean()) if n else None

    values = {
        "elevation_m": {k: clean(e.get(k), 1) for k in ("mean", "min", "max")},
        "slope_deg": {k: clean(s.get(k), 2) for k in ("mean", "max")},
        "aspect_deg": clean(mean_aspect, 0),
        "share_steeper_than_8deg": clean(steep, 3),
        "relative_elevation_m": clean(rel, 2),
        "low_spot": rel is not None and rel < -1.0,
    }
    return result(scale="field", resolution_m=30, source="NASADEM_HGT v001", date_="static", values=values,
                  units={"relative_elevation_m": "parcel mean minus mean of ~300 m surroundings (negative = lower, waterlogging risk)",
                         "aspect_deg": "direction the slope faces, 0 = north"})
