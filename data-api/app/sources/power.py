"""NASA POWER — daily agro-meteorology (~0.5° grid) plus 30-year monthly normals. No auth."""
import math
from datetime import date, timedelta

from ..core import Query, aggregate_periods, clean, extraterrestrial_radiation, http_get_json, result, ttl_cache

PARAMS = {
    "T2M": "°C", "T2M_MAX": "°C", "T2M_MIN": "°C", "T2MDEW": "°C dew point", "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "MJ/m²/day", "RH2M": "%",
    "WS2M": "m/s", "WS2M_MAX": "m/s", "EVPTRNS": "mm/day",
}
NORMAL_PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "ALLSKY_SFC_SW_DWN"]
GDD_BASE_C = 10.0
HEAT_C, FROST_C, GALE_MS, HEAVY_RAIN_MM = 35.0, 0.0, 10.8, 30.0
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@ttl_cache(6 * 3600)
def _daily(lat: float, lon: float, start: date, end: date) -> dict[str, dict[str, float]]:
    d = http_get_json(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        parameters=",".join(PARAMS), community="AG", latitude=lat, longitude=lon,
        start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"), format="JSON",
    )
    return d["properties"]["parameter"]


@ttl_cache(30 * 24 * 3600)
def _normals(lat: float, lon: float) -> dict:
    """1991–2020 monthly climatology (POWER climatology endpoint)."""
    d = http_get_json("https://power.larc.nasa.gov/api/temporal/climatology/point",
                      parameters=",".join(NORMAL_PARAMS), community="AG", latitude=lat, longitude=lon, format="JSON")
    p = d["properties"]["parameter"]
    return {m.lower(): {k: clean(p[k].get(m), 2) for k in NORMAL_PARAMS} for m in MONTHS + ["ANN"]}


def day_length_hours(lat: float, d: date) -> float:
    """Astronomical day length (sunrise→sunset, incl. refraction), CBM model (Forsythe et al. 1995)."""
    j = d.timetuple().tm_yday
    theta = 0.2163108 + 2 * math.atan(0.9671396 * math.tan(0.00860 * (j - 186)))
    phi = math.asin(0.39795 * math.cos(theta))
    p = 0.8333
    x = (math.sin(math.radians(p)) + math.sin(math.radians(lat)) * math.sin(phi)) / (
        math.cos(math.radians(lat)) * math.cos(phi))
    return 24 - (24 / math.pi) * math.acos(max(-1.0, min(1.0, x)))


def _enrich(r: dict, lat: float) -> dict:
    d = date.fromisoformat(r["date"])
    r["daylight_h"] = round(day_length_hours(lat, d), 2)
    rso = 0.75 * extraterrestrial_radiation(lat, d.timetuple().tm_yday)  # FAO-56 clear-sky radiation
    if r["ALLSKY_SFC_SW_DWN"] is not None and rso > 0:
        r["sunshine_fraction"] = clean(min(1.0, r["ALLSKY_SFC_SW_DWN"] / rso), 2)
    if r["T2M_MAX"] is not None and r["T2M_MIN"] is not None:
        r["gdd"] = round(max(0.0, (r["T2M_MAX"] + r["T2M_MIN"]) / 2 - GDD_BASE_C), 2)
        r["frost_days"] = int(r["T2M_MIN"] <= FROST_C)
        r["heat_days_over_35c"] = int(r["T2M_MAX"] >= HEAT_C)
    return r


def _avg(rows: list[dict], key: str):
    v = [r[key] for r in rows if r.get(key) is not None]
    return clean(sum(v) / len(v), 2) if v else None


def _extremes(rows: list[dict]) -> dict:
    if not rows:
        return {}
    hot = max(rows, key=lambda r: r["T2M_MAX"])
    cold = min((r for r in rows if r["T2M_MIN"] is not None), key=lambda r: r["T2M_MIN"], default=None)
    wet = max(rows, key=lambda r: r["PRECTOTCORR"] or 0)
    windy = max(rows, key=lambda r: r["WS2M_MAX"] or 0)
    dry = run = 0
    for r in rows:
        run = run + 1 if (r["PRECTOTCORR"] or 0) < 1 else 0
        dry = max(dry, run)
    return {
        "from": rows[0]["date"], "to": rows[-1]["date"],
        "hottest_day": {"date": hot["date"], "t_max_c": hot["T2M_MAX"]},
        "coldest_night": {"date": cold["date"], "t_min_c": cold["T2M_MIN"]} if cold else None,
        "wettest_day": {"date": wet["date"], "precip_mm": wet["PRECTOTCORR"]},
        "windiest_day": {"date": windy["date"], "wind_max_ms": windy["WS2M_MAX"]},
        "frost_days": sum(r.get("frost_days", 0) for r in rows),
        "heat_days_over_35c": sum(r.get("heat_days_over_35c", 0) for r in rows),
        "heavy_rain_days_over_30mm": sum(1 for r in rows if (r["PRECTOTCORR"] or 0) >= HEAVY_RAIN_MM),
        "gale_days_wind_over_10_8ms": sum(1 for r in rows if (r["WS2M_MAX"] or 0) >= GALE_MS),
        "longest_dry_spell_days": dry,
        "total_precip_mm": clean(sum(r["PRECTOTCORR"] or 0 for r in rows), 1),
    }


def fetch(parcel, q: Query) -> dict:
    lat, lon = (round(v, 3) for v in parcel.centroid)
    today = date.today()
    h_start, h_end = q.window
    start = min(date(today.year, 1, 1), h_start if q.history else today, today - timedelta(days=365))
    p = _daily(lat, lon, start, today)
    try:
        normals = _normals(lat, lon)
    except Exception:  # noqa: BLE001 — normals are a nice-to-have
        normals = None

    days = sorted(p["T2M_MAX"])
    rows = [{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **{k: clean(p[k].get(d), 2) for k in PARAMS}} for d in days]
    rows = [_enrich(r, lat) for r in rows if r["T2M_MAX"] is not None]  # POWER lags 2–3 days (-999)
    if not rows:
        return result(scale="area", resolution_m=55_000, source="NASA POWER", status="no_data")
    latest = rows[-1]

    year = [r for r in rows if r["date"] >= f"{today.year}-01-01"]
    last7, last30 = rows[-7:], rows[-30:]
    last365 = [r for r in rows if r["date"] > (today - timedelta(days=365)).isoformat()]
    month_normal = (normals or {}).get(MONTHS[today.month - 1].lower())
    values = {
        "latest": latest,
        "today": {"daylight_h": round(day_length_hours(lat, today), 2),
                  "daylight_h_longest_day": round(day_length_hours(lat, date(today.year, 6, 21)), 2),
                  "daylight_h_shortest_day": round(day_length_hours(lat, date(today.year, 12, 21)), 2)},
        "last_7_days": {
            "precip_mm": clean(sum(r["PRECTOTCORR"] or 0 for r in last7), 1),
            "t_max_c": clean(max(r["T2M_MAX"] for r in last7), 1),
            "t_min_c": clean(min(r["T2M_MIN"] for r in last7 if r["T2M_MIN"] is not None), 1),
            "rh_mean_pct": _avg(last7, "RH2M"),
            "frost_days": sum(r.get("frost_days", 0) for r in last7),
            "heat_days_over_35c": sum(r.get("heat_days_over_35c", 0) for r in last7),
        },
        "last_30_days": {
            "precip_mm": clean(sum(r["PRECTOTCORR"] or 0 for r in last30), 1),
            "evapotranspiration_mm": clean(sum(r["EVPTRNS"] or 0 for r in last30), 1),
            "t_mean_c": clean(sum(r["T2M"] for r in last30) / len(last30), 1),
            "rh_mean_pct": _avg(last30, "RH2M"),
            "sunshine_fraction": _avg(last30, "sunshine_fraction"),
            "normal_t_mean_c_this_month": month_normal["T2M"] if month_normal else None,
            "normal_precip_mm_per_day_this_month": month_normal["PRECTOTCORR"] if month_normal else None,
        },
        "gdd_since_jan1": {"base_c": GDD_BASE_C, "value": clean(sum(r.get("gdd", 0) for r in year), 1)},
        "extremes_last_365_days": _extremes(last365),
        "normals_1991_2020": normals,
    }
    history = periods = None
    if q.history:
        history = [r for r in rows if h_start.isoformat() <= r["date"] <= h_end.isoformat()]
    if q.periods:
        periods = aggregate_periods(history or [], h_start, h_end)
    units = PARAMS | {"gdd": "°C·day (base 10 °C)", "daylight_h": "hours sunrise→sunset",
                      "sunshine_fraction": "0–1, measured / FAO-56 clear-sky radiation (cloudiness proxy)",
                      "normals_1991_2020": "monthly means; PRECTOTCORR in mm/day"}
    return result(scale="area", resolution_m=55_000, source="NASA POWER (daily + climatology, community=AG)",
                  date_=latest["date"], values=values, units=units, history=history, periods=periods,
                  note="Recent 2–3 days are usually not yet available.")
