"""HLS v2 (Landsat 8/9 + Sentinel-2) 30 m surface reflectance → NDVI / NDMI / NDRE over the parcel.

Clouds, cloud shadow, adjacent cloud and snow are removed with the Fmask layer.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
from shapely.geometry import mapping

from ..core import Query, clean, read_window, result, stac_search, stats

# Band names per sensor (Sentinel-2 uses the narrow NIR B8A to match Landsat's NIR)
BANDS = {
    "HLSS30_2.0": {"red": "B04", "nir": "B8A", "swir1": "B11", "rededge": "B05"},
    "HLSL30_2.0": {"red": "B04", "nir": "B05", "swir1": "B06"},
}
BAD_FMASK_BITS = 0b11110  # bits 1 cloud, 2 adjacent cloud, 3 shadow, 4 snow/ice
MIN_CLEAR_FRACTION = 0.6
LOOKBACK_DAYS = 60


def _vsi(href: str) -> str:
    return "/vsicurl/" + href


def _scene(item: dict, geometry) -> dict | None:
    """Indices for one scene over the parcel, or None if the parcel is mostly cloudy there."""
    coll = item["collection"]
    a = item["assets"]
    fmask, inside, _, _ = read_window(_vsi(a["Fmask"]["href"]), geometry)
    fm = np.nan_to_num(fmask, nan=255).astype(np.uint16)
    clear = inside & (fm != 255) & ((fm & BAD_FMASK_BITS) == 0)
    n_inside = int(inside.sum())
    if n_inside == 0 or clear.sum() / n_inside < MIN_CLEAR_FRACTION:
        return None

    bands = BANDS[coll]
    with ThreadPoolExecutor(len(bands)) as ex:
        refl = dict(zip(bands, ex.map(lambda b: read_window(_vsi(a[bands[b]]["href"]), geometry)[0] * 1e-4, bands)))
    ok = clear & np.all([np.isfinite(r) & (r > 0) & (r <= 1) for r in refl.values()], axis=0)
    if not ok.any():
        return None

    def nd(x, y):
        with np.errstate(divide="ignore", invalid="ignore"):
            return (x - y) / (x + y)

    ndvi = nd(refl["nir"], refl["red"])
    idx = {"ndvi": stats(ndvi, ok, n_inside), "ndmi": stats(nd(refl["nir"], refl["swir1"]), ok, n_inside)}
    if "rededge" in refl:
        idx["ndre"] = stats(nd(refl["nir"], refl["rededge"]), ok, n_inside)

    # Within-field variability: share of clear pixels clearly below the field's median NDVI
    v = ndvi[ok]
    low = float((v < np.median(v) - 0.1).mean()) if v.size >= 4 else None
    out = {
        "date": item["properties"]["datetime"][:10],
        "scene": item["id"],
        "sensor": "Sentinel-2" if coll.startswith("HLSS30") else "Landsat 8/9",
        "clear_fraction": clean(clear.sum() / n_inside, 2),
        "pixels": int(ok.sum()),
        "low_vigor_fraction": clean(low, 3),
    }
    for k, s in idx.items():
        out[k] = {kk: clean(vv, 3) for kk, vv in s.items() if kk in ("mean", "median", "min", "max", "std")}
    return out


def fetch(parcel, q: Query) -> dict:
    geom = mapping(parcel.geometry)
    if q.history:
        start, end = q.window
    else:
        end = date.today()
        start = end - timedelta(days=LOOKBACK_DAYS)
    items = stac_search(list(BANDS), geom, start, end)
    # Skip scenes the provider already flags as almost fully cloudy over the tile
    items = [i for i in items if (i["properties"].get("eo:cloud_cover") or 0) < (70 if q.periods else 95)]

    latest = None
    history = None
    if q.history:
        with ThreadPoolExecutor(10) as ex:
            scenes = [s for s in ex.map(lambda i: _scene(i, parcel.geometry), items) if s]
        history = [{"date": s["date"], "sensor": s["sensor"], "ndvi": s["ndvi"]["mean"], "ndvi_median": s["ndvi"]["median"],
                    "ndmi": s["ndmi"]["mean"], "ndmi_median": s["ndmi"]["median"],
                    "ndre": s.get("ndre", {}).get("mean"), "ndre_median": s.get("ndre", {}).get("median")} for s in scenes]
        latest = scenes[-1] if scenes else None
    else:
        for i in reversed(items):  # newest first, stop at the first clear one
            latest = _scene(i, parcel.geometry)
            if latest:
                break

    if not latest:
        return result(scale="field", resolution_m=30, source="HLS v2.0", status="no_data", history=history,
                      note=f"No scene with ≥{int(MIN_CLEAR_FRACTION * 100)}% clear pixels over the parcel in the window.")
    return result(scale="field", resolution_m=30, source="NASA HLS v2.0 (HLSL30 + HLSS30)", date_=latest["date"],
                  values=latest, history=history,
                  units={"ndvi": "−1…1 vegetation vigor", "ndmi": "−1…1 canopy water (NIR/SWIR, a.k.a. NDWI-Gao)",
                         "ndre": "−1…1 chlorophyll/nitrogen (Sentinel-2 only)",
                         "low_vigor_fraction": "share of field with NDVI > 0.1 below the field median"})
