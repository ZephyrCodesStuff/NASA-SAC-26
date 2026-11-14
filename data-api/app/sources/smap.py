"""SMAP L4 (SPL4SMGP) — modelled surface (0–5 cm) and root-zone (0–100 cm) soil moisture, 9 km, 3-hourly."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import zlib

import numpy as np
from pyproj import Transformer

from ..core import Query, clean, cmr_granules, earthdata_fs, result, ttl_cache

# EASE-Grid 2.0 global 9 km (EPSG:6933)
_CELL = 9008.055210146
_X0, _Y0 = -17367530.44516138, 7314540.830638504
_TO_EASE = Transformer.from_crs(4326, 6933, always_xy=True)


def _cell(lat, lon):
    x, y = _TO_EASE.transform(lon, lat)
    return int((_Y0 - y) // _CELL), int((x - _X0) // _CELL)


def _h5_url(g):
    return next(u for u in g["urls"] if u.endswith(".h5"))


VARS = {"surface_m3m3": "sm_surface", "rootzone_m3m3": "sm_rootzone", "rootzone_wetness": "sm_rootzone_wetness"}


@ttl_cache(24 * 3600)
def _read(url: str, row: int, col: int) -> dict:
    """Each SMAP L4 variable is one gzip-compressed 4 MB chunk covering the globe. Read the HDF5 index once,
    then download the three chunks in parallel and decompress them ourselves (≈3x faster than h5py)."""
    import h5py

    fs = earthdata_fs()
    with fs.open(url, block_size=16 * 2**20, cache_type="blockcache") as fo, h5py.File(fo, "r") as h:
        g = h["Geophysical_Data"]
        meta = {}
        for key, var in VARS.items():
            d = g[var]
            if d.chunks != d.shape or d.compression != "gzip" or d.shuffle or d.id.get_num_chunks() != 1:
                meta = None  # unexpected layout → fall back to plain h5py reads
                break
            ci = d.id.get_chunk_info(0)
            meta[key] = (ci.byte_offset, ci.size, d.dtype, d.shape)
        if meta is None:
            return {k: clean(g[v][row, col]) for k, v in VARS.items()}

    def one(item):
        key, (off, size, dtype, shape) = item
        raw = zlib.decompress(fs.cat_file(url, start=off, end=off + size))
        return key, clean(np.frombuffer(raw, dtype=dtype).reshape(shape)[row, col])

    with ThreadPoolExecutor(3) as ex:
        return dict(ex.map(one, meta.items()))


def fetch(parcel, q: Query) -> dict:
    lat, lon = parcel.centroid
    row, col = _cell(lat, lon)
    g = cmr_granules("SPL4SMGP", lat, lon, n=1)[0]
    clon, clat = _TO_EASE.transform(_X0 + (col + 0.5) * _CELL, _Y0 - (row + 0.5) * _CELL, direction="INVERSE")
    latest = {"time": g["start"], **_read(_h5_url(g), row, col),
              "cell_center": {"lat": clean(clat), "lon": clean(clon)}}

    history = None
    if q.history:
        start, end = q.window
        # one granule per sampled day (~30 points, ~2 per half-month for a year: each read downloads ~12 MB)
        step = max(1, (end - start).days // (24 if q.periods else 30))
        grans = cmr_granules("SPL4SMGP", lat, lon, start, end, n=2000, newest_first=False)
        daily = {}
        for gr in grans:
            d = datetime.fromisoformat(gr["start"].replace("Z", "+00:00")).date()
            if (d - start).days % step == 0 and gr["start"][11:13] >= "10":  # first granule from 10:30 UTC
                daily.setdefault(d, gr)
        items = sorted(daily.items())
        with ThreadPoolExecutor(12) as ex:
            vals = list(ex.map(lambda it: _read(_h5_url(it[1]), row, col), items))
        history = [{"date": d.isoformat(), "surface_m3m3": v["surface_m3m3"], "rootzone_m3m3": v["rootzone_m3m3"]}
                   for (d, _), v in zip(items, vals)]

    return result(scale="area", resolution_m=9000, source="SMAP L4 Global 3-hourly 9 km (SPL4SMGP v8)",
                  date_=g["start"], values=latest,
                  units={"surface_m3m3": "m³/m³", "rootzone_m3m3": "m³/m³", "rootzone_wetness": "0–1 (fraction of saturation)"},
                  history=history, note="Model-assimilated product; ~3–4 days latency.")
