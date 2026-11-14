"""GPM IMERG Late Run daily precipitation, 0.1°. Needs the GES DISC app approved on the Earthdata account."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from urllib.parse import quote

from ..core import Query, clean, cmr_granules, earthdata_fs, open_remote_h5, result, ttl_cache

SHORT_NAME = "GPM_3IMERGDL"  # Late run: ~14 h latency. (Final run GPM_3IMERGDF lags ~3.5 months.)


@ttl_cache(7 * 24 * 3600)
def _read_opendap(url: str, i: int, j: int) -> float | None:
    """One grid cell via NASA cloud OPeNDAP (≈1–3 s instead of ≈20 s for the 26 MB file)."""
    import io

    import h5py

    ce = f"/precipitation[0:0][{i}:{i}][{j}:{j}]"
    raw = earthdata_fs().cat_file(f"{url}.dap.nc4?dap4.ce={quote(ce, safe='/:')}")
    with h5py.File(io.BytesIO(raw), "r") as h:
        return clean(h["precipitation"][0, 0, 0], 2)


@ttl_cache(7 * 24 * 3600)
def _read_file(url: str, i: int, j: int) -> float | None:
    with open_remote_h5(url) as h:
        return clean(h["precipitation"][0, i, j], 2)  # [time, lon, lat], mm/day


def _read(g, i, j):
    if g.get("opendap"):
        try:
            return _read_opendap(g["opendap"], i, j)
        except Exception:  # noqa: BLE001 — fall back to the (slower) direct file read
            pass
    return _read_file(next(u for u in g["urls"] if u.endswith(".nc4")), i, j)


def fetch(parcel, q: Query) -> dict:
    lat, lon = parcel.centroid
    i, j = int((lon + 180) / 0.1), int((lat + 90) / 0.1)
    if q.history:
        start, end = q.window
    else:
        end = date.today()
        start = end - timedelta(days=35)
    grans = cmr_granules(SHORT_NAME, lat, lon, start, end, n=400, newest_first=False)
    if not grans:
        return result(scale="area", resolution_m=11_000, source="GPM IMERG Late daily", status="no_data")
    with ThreadPoolExecutor(32 if len(grans) > 60 else 10) as ex:
        vals = list(ex.map(lambda g: _read(g, i, j), grans))
    series = [{"date": g["start"][:10], "precip_mm": v} for g, v in zip(grans, vals)]
    valid = [s for s in series if s["precip_mm"] is not None]

    def total(days):
        sub = valid[-days:]
        return clean(sum(s["precip_mm"] for s in sub), 1) if sub else None

    dry = 0
    for s in reversed(valid):
        if s["precip_mm"] >= 1.0:
            break
        dry += 1
    values = {
        "latest_day": valid[-1] if valid else None,
        "total_3d_mm": total(3), "total_7d_mm": total(7), "total_30d_mm": total(30),
        "consecutive_dry_days": dry,  # days < 1 mm
    }
    return result(scale="area", resolution_m=11_000, source="GPM IMERG Late Run V07 daily (GPM_3IMERGDL)",
                  date_=valid[-1]["date"] if valid else None, values=values, units={"precip": "mm"},
                  history=series if q.history else None)
