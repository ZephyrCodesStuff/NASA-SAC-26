"""GRACE/GRACE-FO JPL mascon — monthly terrestrial water storage anomaly (~300 km effective resolution)."""
from datetime import date, timedelta

import numpy as np

from ..core import Query, clean, cmr_granules, open_remote_h5, result, ttl_cache

SHORT_NAME = "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
EPOCH = date(2002, 1, 1)


@ttl_cache(24 * 3600)
def _series(url: str, lat: float, lon: float) -> list[dict]:
    with open_remote_h5(url) as h:
        lats, lons = h["lat"][:], h["lon"][:]
        j = int(np.abs(lats - lat).argmin())
        i = int(np.abs(lons - (lon % 360)).argmin())
        vals = h["lwe_thickness"][:, j, i]
        times = h["time"][:]
    return [{"month": (EPOCH + timedelta(days=float(t))).strftime("%Y-%m"), "anomaly_cm": clean(v, 2)}
            for t, v in zip(times, vals)]


def fetch(parcel, q: Query) -> dict:
    lat, lon = parcel.centroid
    g = cmr_granules(SHORT_NAME, lat, lon, n=1)[0]
    url = next(u for u in g["urls"] if u.endswith(".nc"))
    s = _series(url, round(lat, 2), round(lon, 2))
    s = [x for x in s if x["anomaly_cm"] is not None]
    latest = s[-1]
    month = latest["month"][5:]
    same_month = [x["anomaly_cm"] for x in s if x["month"][5:] == month]
    pct = float((np.array(same_month) < latest["anomaly_cm"]).mean() * 100) if len(same_month) > 3 else None
    last12 = s[-12:]
    values = {
        "latest": latest,
        "trend_last_12_months_cm": clean(last12[-1]["anomaly_cm"] - last12[0]["anomaly_cm"], 2),
        "percentile_vs_same_month_all_years": clean(pct, 0),
        "interpretation": ("drier than usual" if pct is not None and pct < 30 else
                           "wetter than usual" if pct is not None and pct > 70 else "near normal"),
    }
    history = s if q.history else None
    return result(scale="area", resolution_m=300_000, source="JPL GRACE/GRACE-FO Mascon RL06.3 CRI",
                  date_=latest["month"], values=values,
                  units={"anomaly_cm": "cm of equivalent water thickness vs 2004–2009 mean"},
                  history=history,
                  note="Regional water storage (groundwater + soil + surface). Not field-level; months behind real time.")
