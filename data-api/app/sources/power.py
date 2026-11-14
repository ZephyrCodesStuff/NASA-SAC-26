"""NASA POWER — daily agro-meteorology (~0.5° grid). No auth."""
from datetime import date, timedelta

from ..core import Query, clean, http_get_json, result, ttl_cache

PARAMS = {
    "T2M": "°C", "T2M_MAX": "°C", "T2M_MIN": "°C", "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "MJ/m²/day", "RH2M": "%", "WS2M": "m/s", "EVPTRNS": "mm/day",
}
GDD_BASE_C = 10.0


@ttl_cache(6 * 3600)
def _daily(lat: float, lon: float, start: date, end: date) -> dict[str, dict[str, float]]:
    d = http_get_json(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        parameters=",".join(PARAMS), community="AG", latitude=lat, longitude=lon,
        start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"), format="JSON",
    )
    return d["properties"]["parameter"]


def fetch(parcel, q: Query) -> dict:
    lat, lon = (round(v, 3) for v in parcel.centroid)
    today = date.today()
    h_start, h_end = q.window
    start = min(date(today.year, 1, 1), h_start if q.history else today, today - timedelta(days=30))
    p = _daily(lat, lon, start, today)

    days = sorted(p["T2M_MAX"])
    rows = [{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **{k: clean(p[k].get(d), 2) for k in PARAMS}} for d in days]
    rows = [r for r in rows if r["T2M_MAX"] is not None]  # POWER lags 2–3 days (-999)
    if not rows:
        return result(scale="area", resolution_m=55_000, source="NASA POWER", status="no_data")
    latest = rows[-1]

    def gdd(r):
        if r["T2M_MAX"] is None or r["T2M_MIN"] is None:
            return 0.0
        return max(0.0, (r["T2M_MAX"] + r["T2M_MIN"]) / 2 - GDD_BASE_C)

    year = [r for r in rows if r["date"] >= f"{today.year}-01-01"]
    last7 = rows[-7:]
    last30 = rows[-30:]
    values = {
        "latest": latest,
        "last_7_days": {
            "precip_mm": clean(sum(r["PRECTOTCORR"] or 0 for r in last7), 1),
            "t_max_c": clean(max(r["T2M_MAX"] for r in last7), 1),
            "t_min_c": clean(min(r["T2M_MIN"] for r in last7 if r["T2M_MIN"] is not None), 1),
            "frost_days": sum(1 for r in last7 if r["T2M_MIN"] is not None and r["T2M_MIN"] <= 0),
            "heat_days_over_35c": sum(1 for r in last7 if r["T2M_MAX"] >= 35),
        },
        "last_30_days": {
            "precip_mm": clean(sum(r["PRECTOTCORR"] or 0 for r in last30), 1),
            "evapotranspiration_mm": clean(sum(r["EVPTRNS"] or 0 for r in last30), 1),
        },
        "gdd_since_jan1": {"base_c": GDD_BASE_C, "value": clean(sum(gdd(r) for r in year), 1)},
    }
    history = None
    if q.history:
        history = [r for r in rows if h_start.isoformat() <= r["date"] <= h_end.isoformat()]
    return result(scale="area", resolution_m=55_000, source="NASA POWER (daily, community=AG)", date_=latest["date"],
                  values=values, units=PARAMS | {"gdd": "°C·day"}, history=history,
                  note="Recent 2–3 days are usually not yet available.")
