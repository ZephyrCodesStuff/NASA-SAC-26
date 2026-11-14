"""Crop history: what grew on the field in each of the last years, read from the HLS (30 m) NDVI season curve.

No global dataset names the crop on a given field each year, so we infer the *crop group* from phenology:
when the field greens up, peaks and is harvested. One clear HLS scene per half-month per year (24 points/year).
Rules are tuned for temperate northern-hemisphere farmland (Po valley); confidence is reported.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
from shapely.geometry import mapping

from ..core import clean, half_month_periods, read_window, result, stac_search, ttl_cache
from .hls import BAD_FMASK_BITS, BANDS, MIN_CLEAR_FRACTION, _vsi

AGGREGATE_PERIODS = False  # history is not a daily/monthly series of this parcel

YEARS = 5
MAX_TRIES = 3  # candidate scenes per half-month (least cloudy first)


def _ndvi_ndmi(item: dict, geometry) -> tuple[float, float] | None:
    a, b = item["assets"], BANDS[item["collection"]]
    fmask, inside, _, _ = read_window(_vsi(a["Fmask"]["href"]), geometry)
    fm = np.nan_to_num(fmask, nan=255).astype(np.uint16)
    clear = inside & (fm != 255) & ((fm & BAD_FMASK_BITS) == 0)
    n = int(inside.sum())
    if n == 0 or clear.sum() / n < MIN_CLEAR_FRACTION:
        return None
    red, nir, swir = (read_window(_vsi(a[b[k]]["href"]), geometry)[0] * 1e-4 for k in ("red", "nir", "swir1"))
    ok = clear & np.isfinite(red) & np.isfinite(nir) & np.isfinite(swir) & (nir > 0) & (red > 0)
    if not ok.any():
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = float(np.nanmean(((nir - red) / (nir + red))[ok]))
        ndmi = float(np.nanmean(((nir - swir) / (nir + swir))[ok]))
    return ndvi, ndmi


def _period_value(items: list[dict], geometry):
    for it in sorted(items, key=lambda i: i["properties"].get("eo:cloud_cover") or 100)[:MAX_TRIES]:
        try:
            v = _ndvi_ndmi(it, geometry)
        except Exception:  # noqa: BLE001 — one unreadable scene must not lose the period
            v = None
        if v:
            return it["properties"]["datetime"][:10], v
    return None


def classify(ndvi: list[float | None], ndmi: list[float | None]) -> dict:
    """Crop group from 24 half-month NDVI values (index 0 = Jan 1–15). Returns label, confidence, phenology."""
    v = np.array([np.nan if x is None else x for x in ndvi], dtype=float)
    valid = np.isfinite(v)
    if valid.sum() < 8:
        return {"crop_group": "unknown", "confidence": "none", "reason": "too few cloud-free observations"}
    # fill gaps linearly so peaks/troughs are comparable
    idx = np.arange(24)
    f = np.interp(idx, idx[valid], v[valid])
    peak = int(f.argmax())
    vmax, vmin = float(f.max()), float(f.min())
    spring, summer = f[6:11].max(), f[12:17].max()  # Apr–mid Jun, Jul–Aug
    early_summer_low = f[12:15].min()  # Jul (after cereal harvest)
    late_spring_low = f[7:10].min()  # mid-Apr – May (before maize/soy canopy)
    winter = np.r_[f[0:4], f[22:24]].mean()
    peaks = [i for i in range(1, 23) if f[i] >= f[i - 1] and f[i] >= f[i + 1] and f[i] > 0.55]
    # well-separated peaks with a real trough between them
    sep = [p for k, p in enumerate(peaks) if k == 0 or p - peaks[k - 1] >= 5 and f[peaks[k - 1]:p].min() < min(f[p], f[peaks[k - 1]]) - 0.2]
    m = [np.nan if x is None else x for x in ndmi]
    flooded = any(np.isfinite(m[i]) and np.isfinite(v[i]) and v[i] < 0.35 and m[i] > v[i] for i in range(8, 12))

    if vmax < 0.35:
        label, conf = "bare soil / fallow / non-vegetated", "medium"
    elif vmin > 0.45 and vmax - vmin < 0.35:
        label, conf = "permanent grassland, meadow or perennial (alfalfa, orchard with grass cover)", "medium"
    elif flooded and summer > 0.6:
        label, conf = "rice (flooded in spring, green in summer)", "medium"
    elif len(sep) >= 2:
        label, conf = "double crop (e.g. winter cereal followed by summer crop/soy)", "medium"
    elif spring > 0.6 and early_summer_low < 0.4 and peak <= 11:
        label, conf = "winter cereal (wheat / barley) or rapeseed", "medium"
    elif summer > 0.6 and late_spring_low < 0.4 and peak >= 12:
        label, conf = "summer crop (maize, soybean, sunflower, sorghum)", "medium"
    elif winter > 0.4 and peak <= 9:
        label, conf = "winter cover / forage crop", "low"
    elif 0.35 <= vmax <= 0.65:
        label, conf = "vineyard, orchard or sparse crop", "low"
    else:
        label, conf = "mixed / unclear", "low"
    labels = [p[0] for p in half_month_periods(date(2001, 1, 1), date(2001, 12, 31))]
    thr = vmin + 0.5 * (vmax - vmin)  # green season = contiguous stretch around the peak above half-amplitude
    a = b = peak
    while a > 0 and f[a - 1] >= thr:
        a -= 1
    while b < 23 and f[b + 1] >= thr:
        b += 1
    return {
        "crop_group": label, "confidence": conf,
        "peak_ndvi": clean(vmax, 2), "peak_period": labels[peak][5:],
        "green_season": f"{labels[a][5:]} → {labels[b][5:]}",
        "flooded_in_spring": flooded,
    }


@ttl_cache(30 * 24 * 3600)
def _year(geom_wkt: str, year: int, until: date) -> dict:
    from shapely import wkt as W

    geometry = W.loads(geom_wkt)
    end = min(date(year, 12, 31), until)
    items = stac_search(list(BANDS), mapping(geometry), date(year, 1, 1), end)
    items = [i for i in items if (i["properties"].get("eo:cloud_cover") or 0) < 70]
    periods = half_month_periods(date(year, 1, 1), date(year, 12, 31))
    groups = [[i for i in items if ps.isoformat() <= i["properties"]["datetime"][:10] <= pe.isoformat()] for _, ps, pe in periods]
    with ThreadPoolExecutor(8) as ex:
        vals = list(ex.map(lambda g: _period_value(g, geometry) if g else None, groups))
    series = [{"period": lbl, "date": v[0] if v else None, "ndvi": clean(v[1][0], 3) if v else None,
               "ndmi": clean(v[1][1], 3) if v else None} for (lbl, _, _), v in zip(periods, vals)]
    out = {"year": year, "complete": end == date(year, 12, 31),
           "observations": sum(1 for s in series if s["ndvi"] is not None), "ndvi_by_period": series}
    out.update(classify([s["ndvi"] for s in series], [s["ndmi"] for s in series]))
    return out


def fetch(parcel, q) -> dict:
    today = date.today()
    years = list(range(today.year - YEARS + 1, today.year + 1))
    with ThreadPoolExecutor(len(years)) as ex:
        seasons = list(ex.map(lambda y: _year(parcel.geometry.wkt, y, today), years))
    done = [s for s in seasons if s["crop_group"] != "unknown"]
    groups = [s["crop_group"] for s in done if s["complete"]]
    values = {
        "seasons": [{k: v for k, v in s.items() if k != "ndvi_by_period"} for s in seasons],
        "most_common_crop_group": max(set(groups), key=groups.count) if groups else None,
        "rotates": len(set(groups)) > 1 if groups else None,
    }
    return result(scale="field", resolution_m=30, source="NASA HLS v2.0 NDVI phenology (HLSL30 + HLSS30)",
                  date_=today.isoformat(), values=values,
                  history=[{"year": s["year"], "ndvi_by_period": s["ndvi_by_period"]} for s in seasons],
                  units={"ndvi_by_period": "mean NDVI of one clear scene per calendar half-month (H1 = days 1–15)"},
                  note="Crop *group* inferred from the season curve (green-up, peak, harvest). Exact species "
                       "needs farmer input or a regional crop map. The current year is partial.")
