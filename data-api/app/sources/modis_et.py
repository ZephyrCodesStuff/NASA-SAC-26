"""MODIS MOD16A2 v6.1 — 8-day actual and potential evapotranspiration, 500 m. ORNL DAAC subset API, no auth.

The ORNL service is slow (~30–60 s per call) but synchronous; results are cached.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from ..core import Query, clean, http_get_json, result, ttl_cache

API = "https://modis.ornl.gov/rst/api/v1/MOD16A2"
BANDS = {"et_mm_8day": "ET_500m", "pet_mm_8day": "PET_500m"}


def _modis_date(d: date) -> str:
    return f"A{d.year}{d.timetuple().tm_yday:03d}"


@ttl_cache(12 * 3600)
def _band(lat: float, lon: float, band: str, start: date, end: date) -> dict[str, float | None]:
    out = {}
    # the API returns at most 10 composites per call
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=79))
        d = http_get_json(f"{API}/subset", latitude=lat, longitude=lon, band=band, startDate=_modis_date(s),
                          endDate=_modis_date(e), kmAboveBelow=0, kmLeftRight=0)
        for row in d.get("subset", []):
            v = row["data"][0]
            out[row["calendar_date"]] = clean(v * 0.1, 1) if v < 32700 else None  # 327xx = fill/water/urban
        s = e + timedelta(days=1)
    return out


def fetch(parcel, q: Query) -> dict:
    lat, lon = (round(v, 4) for v in parcel.centroid)
    if q.history:
        start, end = q.window
    else:
        end = date.today()
        start = end - timedelta(days=60)  # product lags ~2–4 weeks
    with ThreadPoolExecutor(2) as ex:
        res = dict(zip(BANDS, ex.map(lambda b: _band(lat, lon, b, start, end), BANDS.values())))
    dates = sorted(set(res["et_mm_8day"]) | set(res["pet_mm_8day"]))
    series = [{"date": d, **{k: res[k].get(d) for k in BANDS}} for d in dates]
    valid = [r for r in series if r["et_mm_8day"] is not None]
    if not valid:
        return result(scale="area", resolution_m=500, source="MODIS MOD16A2", status="no_data",
                      note="No valid ET (non-vegetated pixel, or composites not yet published).")
    latest = valid[-1]
    ratio = latest["et_mm_8day"] / latest["pet_mm_8day"] if latest.get("pet_mm_8day") else None
    values = {**latest, "et_mm_per_day": clean(latest["et_mm_8day"] / 8, 2), "et_pet_ratio": clean(ratio, 2)}
    return result(scale="area", resolution_m=500, source="MODIS MOD16A2 v6.1 via ORNL DAAC", date_=latest["date"],
                  values=values, units={"et_mm_8day": "mm per 8-day composite (start date)", "et_pet_ratio": "0–1, low = water-limited"},
                  history=series if q.history else None)
