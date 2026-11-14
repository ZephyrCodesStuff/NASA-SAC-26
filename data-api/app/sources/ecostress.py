"""ECOSTRESS v2 (ISS, 70 m): daily evapotranspiration, Evaporative Stress Index, land-surface temperature.

Overpasses are irregular (ISS orbit, ~52°N–52°S) and often cloudy, so for each product we use the most
recent overpass with valid pixels on the parcel.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
from shapely.geometry import mapping

from ..core import Query, clean, read_window, result, stac_search, stats

LOOKBACK_DAYS = 45
DAY_HOURS = (9.0, 16.0)  # local solar time
BATCH = 6
# product key -> (STAC collection, asset suffix, scale, offset, valid range, unit)
PRODUCTS = {
    "et_daily": ("ECO_L3T_JET_002", "_ETdaily", 1.0, 0.0, (0, 30), "mm/day"),
    "esi": ("ECO_L4T_ESI_002", "_ESI", 1.0, 0.0, (0, 1.5), "0–1 (actual / potential ET; low = water stress)"),
    "lst": ("ECO_L2T_LSTE_002", "_LST", 1.0, -273.15, (-60, 80), "°C (canopy/soil surface temperature)"),
}


def _asset(item, suffix):
    return next((a["href"] for k, a in item["assets"].items() if k.endswith(suffix) and a["href"].endswith(".tif")), None)


def _value(item, product, geometry):
    _, suffix, scale, offset, (lo, hi), _ = PRODUCTS[product]
    href = _asset(item, suffix)
    if not href:
        return None
    data, inside, _, _ = read_window("/vsicurl/" + href, geometry)
    data = data * scale + offset
    ok = inside & np.isfinite(data) & (data >= lo) & (data <= hi)
    if product == "lst":  # drop cloudy pixels
        cloud = _asset(item, "_cloud")
        if cloud:
            c, _, _, _ = read_window("/vsicurl/" + cloud, geometry)
            ok &= np.nan_to_num(c, nan=1) == 0
    s = stats(data, ok, int(inside.sum()))
    if s["mean"] is None:
        return None
    return {"datetime": item["properties"]["datetime"], "mean": clean(s["mean"], 3), "min": clean(s.get("min"), 3),
            "max": clean(s.get("max"), 3), "pixels": s["pixels"]}


def _local_solar_hour(item, lon: float) -> float:
    t = datetime.fromisoformat(item["properties"]["datetime"].replace("Z", "+00:00"))
    return (t.hour + t.minute / 60 + lon / 15) % 24


def _product(product, geometry, start, end, history: bool):
    coll = PRODUCTS[product][0]
    lon = geometry.centroid.x
    items = stac_search([coll], mapping(geometry), start, end)
    # ET and stress are only meaningful while plants transpire: keep daytime overpasses
    items = [i for i in items if DAY_HOURS[0] <= _local_solar_hour(i, lon) <= DAY_HOURS[1]]
    if history:
        with ThreadPoolExecutor(6) as ex:
            vals = [v for v in ex.map(lambda i: _value(i, product, geometry), items) if v]
        return (vals[-1] if vals else None), vals
    # newest first, a batch at a time in parallel; return the newest valid one
    items = items[::-1]
    with ThreadPoolExecutor(BATCH) as ex:
        for k in range(0, len(items), BATCH):
            for v in ex.map(lambda i: _value(i, product, geometry), items[k:k + BATCH]):
                if v:
                    return v, None
    return None, None


def fetch(parcel, q: Query) -> dict:
    if q.history:
        start, end = q.window
    else:
        end = date.today()
        start = end - timedelta(days=LOOKBACK_DAYS)
    with ThreadPoolExecutor(len(PRODUCTS)) as ex:
        res = dict(zip(PRODUCTS, ex.map(lambda p: _product(p, parcel.geometry, start, end, q.history), PRODUCTS)))
    values = {p: r[0] for p, r in res.items()}
    if not any(values.values()):
        lat = parcel.centroid[0]
        why = "outside ISS coverage (~52°N–52°S)" if abs(lat) > 52 else "no cloud-free overpass in the window"
        return result(scale="field", resolution_m=70, source="ECOSTRESS v2", status="no_data", note=why)
    dates = [v["datetime"][:10] for v in values.values() if v]
    history = {p: r[1] for p, r in res.items()} if q.history else None
    return result(scale="field", resolution_m=70, source="NASA ECOSTRESS v2 (L3T JET, L4T ESI, L2T LSTE)",
                  date_=max(dates), values=values, units={p: v[5] for p, v in PRODUCTS.items()}, history=history,
                  note="Each value comes from the most recent overpass with valid pixels on the parcel; dates differ.")
