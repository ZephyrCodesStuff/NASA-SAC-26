"""Satellite images of a parcel in several spectral views, as PNGs ready for <img> or a Leaflet ImageOverlay.

- HLS v2 (30 m, Landsat 8/9 + Sentinel-2): true colour, colour-infrared, agriculture (SWIR), SWIR moisture,
  NDVI, NDMI, NDRE (Sentinel-2) and thermal (Landsat) — from the newest scene that is clear over the parcel.
- ECOSTRESS (70 m): land-surface temperature from the newest clear daytime overpass.
- NASADEM (30 m): elevation, hillshade and slope.

Pixels outside the parcel are dimmed and the parcel outline is drawn, so the field stays in context.
"""
from __future__ import annotations

import base64
import io
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
from shapely.geometry import mapping, shape

from .core import clean, read_window, stac_search, ttl_cache
from .sources import ecostress, nasadem
from .sources.hls import BAD_FMASK_BITS, MIN_CLEAR_FRACTION, _vsi

HLS_BANDS = {
    "HLSS30_2.0": {"blue": "B02", "green": "B03", "red": "B04", "rededge": "B05", "nir": "B8A", "swir1": "B11", "swir2": "B12"},
    "HLSL30_2.0": {"blue": "B02", "green": "B03", "red": "B04", "nir": "B05", "swir1": "B06", "swir2": "B07", "thermal": "B10"},
}
PAD = 12  # pixels of surroundings around the parcel
MIN_SIDE = 512  # upscale small images (nearest neighbour) so they stay crisp on screen
OUTSIDE_ALPHA = 120

# colour ramps: list of (position 0–1, (r, g, b))
RAMPS = {
    "ndvi": [(0, (165, 0, 38)), (0.25, (244, 109, 67)), (0.45, (254, 224, 139)), (0.65, (166, 217, 106)), (1, (0, 104, 55))],
    "ndmi": [(0, (140, 81, 10)), (0.4, (246, 232, 195)), (0.6, (199, 234, 229)), (1, (1, 102, 94))],
    "thermal": [(0, (0, 0, 4)), (0.25, (87, 16, 110)), (0.5, (188, 55, 84)), (0.75, (249, 142, 9)), (1, (252, 255, 164))],
    "elevation": [(0, (49, 54, 149)), (0.25, (116, 173, 209)), (0.5, (255, 255, 191)), (0.75, (244, 109, 67)), (1, (165, 0, 38))],
    "slope": [(0, (255, 255, 204)), (0.33, (161, 218, 180)), (0.66, (65, 182, 196)), (1, (37, 52, 148))],
}

DESCRIPTIONS = {
    "true_color": "Natural colour (red, green, blue) — what the eye sees.",
    "color_infrared": "NIR-red-green: healthy vegetation is bright red, bare soil grey/brown, water black.",
    "agriculture": "SWIR1-NIR-blue: crops bright green, bare soil magenta/brown — separates crop types and tillage.",
    "swir_moisture": "SWIR2-SWIR1-red: wet soil and irrigated fields dark, dry soil bright.",
    "ndvi": "Vegetation vigour (−0.2 brown → 0.9 dark green).",
    "ndmi": "Canopy/soil water content (−0.4 dry brown → 0.6 wet teal).",
    "ndre": "Red-edge index (chlorophyll / nitrogen status), Sentinel-2 only.",
    "thermal": "Landsat thermal band (brightness temperature, °C).",
    "lst": "ECOSTRESS land-surface temperature (°C), newest clear daytime overpass.",
    "elevation": "NASADEM elevation (m), colour-stretched over the view.",
    "hillshade": "NASADEM shaded relief (sun from north-west).",
    "slope": "NASADEM slope (0° light → ≥15° dark blue).",
}


# ---------------------------------------------------------------- rendering helpers
def _ramp(x: np.ndarray, name: str) -> np.ndarray:
    stops = RAMPS[name]
    pos = np.array([p for p, _ in stops])
    rgb = np.stack([np.interp(x, pos, [c[i] for _, c in stops]) for i in range(3)], axis=-1)
    return rgb.astype(np.uint8)


def _stretch(a: np.ndarray, lo: float, hi: float, gamma: float = 1.0) -> np.ndarray:
    x = np.clip((a - lo) / (hi - lo), 0, 1)
    return x ** (1 / gamma)


def _auto_range(a: np.ndarray, mask: np.ndarray, p: tuple = (2, 98)) -> tuple[float, float]:
    v = a[mask & np.isfinite(a)]
    if v.size == 0:
        v = a[np.isfinite(a)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(v, p)
    return float(lo), float(hi if hi > lo else lo + 1)


def _png(rgb: np.ndarray, valid: np.ndarray, inside: np.ndarray, outline_px: list | None) -> str:
    from PIL import Image, ImageDraw

    alpha = np.where(valid, np.where(inside, 255, OUTSIDE_ALPHA), 0).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    h, w = alpha.shape
    k = max(1, min(16, math.ceil(MIN_SIDE / max(h, w))))
    img = Image.fromarray(rgba, "RGBA").resize((w * k, h * k), Image.NEAREST)
    if outline_px:
        draw = ImageDraw.Draw(img)
        for ring in outline_px:
            draw.line([(x * k, y * k) for x, y in ring], fill=(255, 255, 255, 255), width=max(2, k // 2))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _outline(geom_raster, transform) -> list:
    """Parcel rings in pixel coordinates of the window."""
    inv = ~transform
    polys = getattr(geom_raster, "geoms", [geom_raster])
    return [[inv * (x, y) for x, y in p.exterior.coords] for p in polys]


def _bounds_latlon(transform, shape_, crs) -> list[list[float]]:
    from rasterio.warp import transform_bounds

    h, w = shape_
    x0, y0 = transform * (0, 0)
    x1, y1 = transform * (w, h)
    west, south, east, north = transform_bounds(crs, "EPSG:4326", min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]]


def _geom_in(crs, geometry):
    from rasterio.warp import transform_geom

    return shape(transform_geom("EPSG:4326", crs, mapping(geometry)))


# ---------------------------------------------------------------- HLS
def _clear(item, geometry) -> bool:
    fmask, inside, _, _ = read_window(_vsi(item["assets"]["Fmask"]["href"]), geometry)
    fm = np.nan_to_num(fmask, nan=255).astype(np.uint16)
    clear = inside & (fm != 255) & ((fm & BAD_FMASK_BITS) == 0)
    n = int(inside.sum())
    return n > 0 and clear.sum() / n >= MIN_CLEAR_FRACTION


def _find_scene(geometry, on: date | None):
    end = on or date.today()
    start = end - timedelta(days=45 if on else 75)
    items = stac_search(list(HLS_BANDS), mapping(geometry), start, end)
    items = [i for i in items if (i["properties"].get("eo:cloud_cover") or 0) < 90][::-1]  # newest first
    for k in range(0, len(items), 6):
        batch = items[k:k + 6]
        with ThreadPoolExecutor(len(batch)) as ex:
            ok = list(ex.map(lambda i: _clear(i, geometry), batch))
        for it, good in zip(batch, ok):
            if good:
                return it
    return None


def _hls_layers(item, geometry) -> tuple[dict, dict]:
    import rasterio

    bands = HLS_BANDS[item["collection"]]
    a = item["assets"]

    def read(key):
        return key, read_window(_vsi(a[bands[key]]["href"]), geometry, pad_pixels=PAD)

    with ThreadPoolExecutor(len(bands) + 1) as ex:
        res = dict(ex.map(read, list(bands)))
        fm = read_window(_vsi(a["Fmask"]["href"]), geometry, pad_pixels=PAD)[0]
    _, inside, wt, crs = res["red"]
    b = {k: v[0] * 1e-4 for k, v in res.items() if k != "thermal"}
    fm = np.nan_to_num(fm, nan=255).astype(np.uint16)
    valid = np.all([np.isfinite(x) for x in b.values()], axis=0) & (fm != 255)
    outline = _outline(_geom_in(crs, geometry), wt)

    def nd(x, y):
        with np.errstate(divide="ignore", invalid="ignore"):
            return (b[x] - b[y]) / (b[x] + b[y])

    def rgb(r, g, bl, hi, gamma=1.3):
        return np.dstack([(_stretch(b[c], 0, hi, gamma) * 255).astype(np.uint8) for c in (r, g, bl)])

    layers, legends = {}, {}
    layers["true_color"] = _png(rgb("red", "green", "blue", 0.25, 1.6), valid, inside, outline)
    layers["color_infrared"] = _png(rgb("nir", "red", "green", 0.45), valid, inside, outline)
    layers["agriculture"] = _png(rgb("swir1", "nir", "blue", 0.45), valid, inside, outline)
    layers["swir_moisture"] = _png(rgb("swir2", "swir1", "red", 0.4), valid, inside, outline)
    indices = {"ndvi": (nd("nir", "red"), -0.2, 0.9, "ndvi"), "ndmi": (nd("nir", "swir1"), -0.4, 0.6, "ndmi")}
    if "rededge" in b:
        indices["ndre"] = (nd("nir", "rededge"), -0.1, 0.6, "ndvi")
    for name, (arr, lo, hi, ramp) in indices.items():
        ok = valid & np.isfinite(arr)
        layers[name] = _png(_ramp(_stretch(np.nan_to_num(arr, nan=lo), lo, hi), ramp), ok, inside, outline)
        v = arr[inside & ok]
        legends[name] = {"min": lo, "max": hi, "ramp": ramp,
                         "parcel_mean": clean(float(v.mean()), 3) if v.size else None}
    if "thermal" in res:
        t = res["thermal"][0] * 0.01  # HLS L30 TIR: °C × 100
        ok = np.isfinite(t) & (fm != 255)
        lo, hi = _auto_range(t, inside & ok)
        layers["thermal"] = _png(_ramp(_stretch(np.nan_to_num(t, nan=lo), lo, hi), "thermal"), ok, inside, outline)
        v = t[inside & ok]
        legends["thermal"] = {"min": clean(lo, 1), "max": clean(hi, 1), "unit": "°C", "ramp": "thermal",
                              "parcel_mean": clean(float(v.mean()), 1) if v.size else None}
    meta = {"bounds": _bounds_latlon(wt, inside.shape, crs), "pixel_size_m": 30,
            "size_px": list(inside.shape[::-1])}
    _ = rasterio  # imported for GDAL env side-effects in worker threads
    return layers, {"legends": legends, **meta}


# ---------------------------------------------------------------- ECOSTRESS LST
def _lst_layer(geometry, on: date | None):
    end = on or date.today()
    items = stac_search(["ECO_L2T_LSTE_002"], mapping(geometry), end - timedelta(days=45), end)
    lon = geometry.centroid.x
    items = [i for i in items if ecostress.DAY_HOURS[0] <= ecostress._local_solar_hour(i, lon) <= ecostress.DAY_HOURS[1]][::-1]
    for it in items[:12]:
        href, cloud = ecostress._asset(it, "_LST"), ecostress._asset(it, "_cloud")
        if not href:
            continue
        lst, inside, wt, crs = read_window("/vsicurl/" + href, geometry, pad_pixels=PAD // 2)
        lst = lst - 273.15
        ok = np.isfinite(lst) & (lst > -60) & (lst < 80)
        if cloud:
            ok &= np.nan_to_num(read_window("/vsicurl/" + cloud, geometry, pad_pixels=PAD // 2)[0], nan=1) == 0
        if (ok & inside).sum() < max(1, 0.6 * inside.sum()):
            continue
        lo, hi = _auto_range(lst, ok)
        png = _png(_ramp(_stretch(np.nan_to_num(lst, nan=lo), lo, hi), "thermal"), ok, inside,
                   _outline(_geom_in(crs, geometry), wt))
        v = lst[inside & ok]
        return {"png": png, "date": it["properties"]["datetime"], "bounds": _bounds_latlon(wt, inside.shape, crs),
                "pixel_size_m": 70, "legend": {"min": clean(lo, 1), "max": clean(hi, 1), "unit": "°C", "ramp": "thermal",
                                               "parcel_mean": clean(float(v.mean()), 1)}}
    return None


# ---------------------------------------------------------------- NASADEM
def _dem_layers(geometry):
    lat, lon = geometry.centroid.y, geometry.centroid.x
    src = nasadem._tile(lat, lon)
    if src is None:
        return None
    pad = PAD * 2
    elev, inside, wt, crs = read_window(src, geometry, pad_pixels=pad)
    elev[elev < -500] = np.nan
    ok = np.isfinite(elev)
    dy = abs(wt.e) * 111_320
    dx = abs(wt.a) * 111_320 * math.cos(math.radians(lat))
    gy, gx = np.gradient(np.nan_to_num(elev, nan=np.nanmean(elev)), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    # hillshade, sun azimuth 315°, altitude 45°
    az, alt = math.radians(315), math.radians(45)
    aspect = np.arctan2(-gx, gy)
    shade = np.sin(alt) * np.cos(np.radians(slope)) + np.cos(alt) * np.sin(np.radians(slope)) * np.cos(az - aspect)
    outline = _outline(_geom_in(crs, geometry), wt)
    lo, hi = _auto_range(elev, ok, (1, 99))
    gray = (np.clip(shade, 0, 1) * 255).astype(np.uint8)
    layers = {
        "elevation": _png(_ramp(_stretch(np.nan_to_num(elev, nan=lo), lo, hi), "elevation"), ok, inside, outline),
        "hillshade": _png(np.dstack([gray] * 3), ok, inside, outline),
        "slope": _png(_ramp(_stretch(slope, 0, 15), "slope"), ok, inside, outline),
    }
    return {"layers": layers, "bounds": _bounds_latlon(wt, inside.shape, crs), "pixel_size_m": 30,
            "legends": {"elevation": {"min": clean(lo, 0), "max": clean(hi, 0), "unit": "m", "ramp": "elevation"},
                        "slope": {"min": 0, "max": 15, "unit": "°", "ramp": "slope"}}}


# ---------------------------------------------------------------- entry point
ALL_GROUPS = ("hls", "lst", "dem")


@ttl_cache(6 * 3600)
def render(geom_wkt: str, on: date | None = None, groups: tuple = ALL_GROUPS) -> dict:
    from shapely import wkt as W

    geometry = W.loads(geom_wkt)
    out: dict = {"date_requested": on.isoformat() if on else None, "groups": {}, "descriptions": DESCRIPTIONS,
                 "ramps": {k: [[p, list(c)] for p, c in v] for k, v in RAMPS.items()}}

    def hls_group():
        item = _find_scene(geometry, on)
        if not item:
            return {"status": "no_data", "note": "No HLS scene with ≥60% clear pixels over the parcel in the last 75 days."}
        layers, meta = _hls_layers(item, geometry)
        return {"status": "ok", "date": item["properties"]["datetime"][:10], "scene": item["id"],
                "sensor": "Sentinel-2" if item["collection"].startswith("HLSS30") else "Landsat 8/9",
                "source": "NASA HLS v2.0", **meta, "layers": layers}

    def lst_group():
        r = _lst_layer(geometry, on)
        if not r:
            return {"status": "no_data", "note": "No clear daytime ECOSTRESS overpass in the last 45 days."}
        return {"status": "ok", "source": "NASA ECOSTRESS L2T LSTE v2", "date": r["date"], "bounds": r["bounds"],
                "pixel_size_m": r["pixel_size_m"], "legends": {"lst": r["legend"]}, "layers": {"lst": r["png"]}}

    def dem_group():
        r = _dem_layers(geometry)
        if not r:
            return {"status": "unavailable", "note": "NASADEM covers 56°S–60°N only."}
        return {"status": "ok", "source": "NASADEM_HGT v001", "date": "static", **r}

    fns = {"hls": hls_group, "lst": lst_group, "dem": dem_group}
    with ThreadPoolExecutor(len(groups)) as ex:
        futs = {g: ex.submit(fns[g]) for g in groups}
        for g, f in futs.items():
            try:
                out["groups"][g] = f.result()
            except Exception as e:  # noqa: BLE001
                out["groups"][g] = {"status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
    return out
