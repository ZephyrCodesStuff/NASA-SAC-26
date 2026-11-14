"""NASA NEX-GDDP-CMIP6 — bias-corrected, downscaled (0.25°) daily climate projections. No auth.

Point subsets come from NASA NCCS THREDDS (NetCDF Subset Service → CSV, one file per model/variable/year).
We sample a few years per 30-year window and two models, which is enough for a coarse trend but is not a
full ensemble: treat the numbers as "direction and rough size of change".
"""
import csv
import io
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from ..core import _http, clean, extraterrestrial_radiation as _ra_mj, half_month_periods, result, ttl_cache

AGGREGATE_PERIODS = False  # history is not a daily/monthly series of this parcel

BASE = "https://ds.nccs.nasa.gov/thredds"
MODELS = [("ACCESS-CM2", "r1i1p1f1"), ("MPI-ESM1-2-HR", "r1i1p1f1")]
VARS = ("pr", "tasmax", "tasmin")
WINDOWS = {  # label -> (experiment(s), sampled years)
    "baseline_2000s": ("historical", (2000, 2010)),
    "near_2030s": (None, (2030, 2035)),
    "mid_2050s": (None, (2050, 2055)),
}
SCENARIOS = {"ssp245": "middle of the road (SSP2-4.5)", "ssp585": "high emissions (SSP5-8.5)"}


@ttl_cache(30 * 24 * 3600)
def _files(model: str, member: str, experiment: str, var: str) -> dict[int, str]:
    xml = _http.get(f"{BASE}/catalog/AMES/NEX/GDDP-CMIP6/{model}/{experiment}/{member}/{var}/catalog.xml").raise_for_status().text
    out = {}
    for path in re.findall(r'urlPath="([^"]+\.nc)"', xml):
        m = re.search(r"_(\d{4})(?:_v[\d.]+)?\.nc$", path)
        if m:
            y = int(m.group(1))
            if y not in out or "_v2" in path:  # prefer the newest file version
                out[y] = path
    return out


@ttl_cache(90 * 24 * 3600)
def _year(model: str, member: str, experiment: str, var: str, year: int, lat: float, lon: float) -> list[float]:
    path = _files(model, member, experiment, var)[year]
    r = _http.get(f"{BASE}/ncss/grid/{path}", params={
        "var": var, "latitude": lat, "longitude": lon, "accept": "csv",
        "time_start": f"{year}-01-01T00:00:00Z", "time_end": f"{year}-12-31T23:59:59Z"}, timeout=120)
    rows = list(csv.reader(io.StringIO(r.raise_for_status().text)))[1:]
    vals = [float(x[-1]) for x in rows if x]
    if var == "pr":
        return [v * 86400 for v in vals]  # kg m-2 s-1 → mm/day
    return [v - 273.15 for v in vals]  # K → °C



def _year_stats(year: int, pr: list[float], tx: list[float], tn: list[float], lat: float) -> dict:
    n = min(len(pr), len(tx), len(tn))
    pet = []
    for i in range(n):
        tmean = (tx[i] + tn[i]) / 2
        pet.append(max(0.0, 0.0023 * 0.408 * _ra_mj(lat, i + 1) * (tmean + 17.8) * math.sqrt(max(0.0, tx[i] - tn[i]))))
    dry = run = 0
    for v in pr[:n]:
        run = run + 1 if v < 1 else 0
        dry = max(dry, run)
    summer = range(151, 243)  # Jun–Aug (day-of-year index)
    halves = []
    for _, ps, pe in half_month_periods(date(year, 1, 1), date(year, 12, 31)):
        a, b = (ps - date(year, 1, 1)).days, (pe - date(year, 1, 1)).days + 1
        b = min(b, n)
        halves.append({"precip_mm": sum(pr[a:b]), "t_max_c": sum(tx[a:b]) / max(1, b - a),
                       "water_balance_mm": sum(pr[a:b]) - sum(pet[a:b])})
    return {
        "precip_mm": sum(pr[:n]),
        "pet_mm": sum(pet),
        "water_balance_mm": sum(pr[:n]) - sum(pet),
        "summer_precip_mm": sum(pr[i] for i in summer if i < n),
        "t_max_summer_c": sum(tx[i] for i in summer if i < n) / len(summer),
        "heat_days_over_35c": sum(1 for v in tx[:n] if v >= 35),
        "frost_days": sum(1 for v in tn[:n] if v <= 0),
        "longest_dry_spell_days": dry,
        "max_1day_precip_mm": max(pr[:n]),
        "halves": halves,
    }


def _mean(dicts: list[dict]) -> dict:
    keys = [k for k in dicts[0] if k != "halves"]
    out = {k: clean(sum(d[k] for d in dicts) / len(dicts), 1) for k in keys}
    out["by_period"] = [
        {k: clean(sum(d["halves"][i][k] for d in dicts) / len(dicts), 1) for k in dicts[0]["halves"][i]}
        for i in range(24)]
    return out


def _risk(base: dict, fut: dict) -> dict:
    """Drought risk class from the change in summer water balance and dry spells (simple, explainable rule)."""
    d_wb = fut["water_balance_mm"] - base["water_balance_mm"]
    d_summer = (fut["summer_precip_mm"] - base["summer_precip_mm"]) / max(1.0, base["summer_precip_mm"]) * 100
    d_dry = fut["longest_dry_spell_days"] - base["longest_dry_spell_days"]
    d_heat = fut["heat_days_over_35c"] - base["heat_days_over_35c"]
    score = (d_wb < -50) + (d_wb < -150) + (d_summer < -10) + (d_summer < -25) + (d_dry >= 5) + (d_heat >= 5)
    return {
        "water_balance_change_mm": clean(d_wb, 0),
        "summer_precip_change_pct": clean(d_summer, 0),
        "dry_spell_change_days": clean(d_dry, 0),
        "heat_days_change": clean(d_heat, 0),
        "drought_risk": ["low", "low", "moderate", "moderate", "high", "high", "very high"][min(6, score)],
    }


def fetch(parcel, q) -> dict:
    lat, lon = (round(v * 4) / 4 for v in parcel.centroid)  # snap to the 0.25° grid → shared cache
    jobs = []
    for model, member in MODELS:
        for label, (exp, years) in WINDOWS.items():
            for scen in ([exp] if exp else list(SCENARIOS)):
                for y in years:
                    for v in VARS:
                        jobs.append((model, member, scen, v, y, label))
    with ThreadPoolExecutor(12) as ex:
        data = list(ex.map(lambda j: _year(j[0], j[1], j[2], j[3], j[4], lat, lon), jobs))
    series = {(j[0], j[2], j[4], j[3]): d for j, d in zip(jobs, data)}

    per_window: dict[str, list[dict]] = {}
    for model, _ in MODELS:
        for label, (exp, years) in WINDOWS.items():
            for scen in ([exp] if exp else list(SCENARIOS)):
                key = "baseline" if exp else f"{scen}_{label}"
                for y in years:
                    s = _year_stats(y, series[(model, scen, y, "pr")], series[(model, scen, y, "tasmax")],
                                    series[(model, scen, y, "tasmin")], lat)
                    per_window.setdefault(key, []).append(s)
    windows = {k: _mean(v) for k, v in per_window.items()}
    base = windows["baseline"]
    projections = {}
    for scen in SCENARIOS:
        for label in ("near_2030s", "mid_2050s"):
            w = windows[f"{scen}_{label}"]
            projections[f"{scen}_{label}"] = {**{k: v for k, v in w.items() if k != "by_period"}, **_risk(base, w)}
    periods = [{"period": f"{i // 2 + 1:02d}-{'H1' if i % 2 == 0 else 'H2'}",
                "baseline": base["by_period"][i],
                "ssp245_mid_2050s": windows["ssp245_mid_2050s"]["by_period"][i],
                "ssp585_mid_2050s": windows["ssp585_mid_2050s"]["by_period"][i]} for i in range(24)]
    values = {
        "baseline_2000s": {k: v for k, v in base.items() if k != "by_period"},
        "projections": projections,
        "headline": projections["ssp245_mid_2050s"]["drought_risk"],
    }
    return result(scale="area", resolution_m=25_000, source="NASA NEX-GDDP-CMIP6 v2 (NCCS THREDDS)",
                  date_="projection", values=values, periods=periods,
                  units={"precip_mm": "mm/year", "pet_mm": "mm/year, Hargreaves reference ET",
                         "water_balance_mm": "precip − PET (negative = deficit)", "t_max_summer_c": "°C Jun–Aug mean",
                         "periods": "calendar half-months (MM-H1 = days 1–15); sums in mm, t_max mean °C"},
                  note=f"Models {', '.join(m for m, _ in MODELS)}; years sampled per window "
                       f"({', '.join(f'{k}: {v[1]}' for k, v in WINDOWS.items())}). Trend indicator, not a forecast.")
