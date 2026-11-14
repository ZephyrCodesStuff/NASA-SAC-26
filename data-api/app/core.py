"""Shared plumbing: Earthdata auth, GDAL config, HTTP, caching, result helpers, raster sampling."""
from __future__ import annotations

import functools
import hashlib
import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

log = logging.getLogger("parcel_api")

CACHE_DIR = Path(os.environ.get("PARCEL_API_CACHE", Path(__file__).resolve().parent.parent / ".cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# GDAL settings for reading Cloud-Optimized GeoTIFFs over HTTPS. Earthdata uses a login redirect,
# so GDAL authenticates with ~/.netrc and keeps the session cookie (NASA's recommended setup).
os.environ.update(
    GDAL_HTTP_NETRC="YES",
    GDAL_HTTP_COOKIEFILE=str(CACHE_DIR / "gdal_cookies.txt"),
    GDAL_HTTP_COOKIEJAR=str(CACHE_DIR / "gdal_cookies.txt"),
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.vrt",
    GDAL_HTTP_TIMEOUT="30",
    GDAL_HTTP_MAX_RETRY="3",
    GDAL_HTTP_RETRY_DELAY="1",
    VSI_CACHE="TRUE",
)


# ---------------------------------------------------------------- Earthdata
_auth_lock = threading.Lock()
_fs = None


def _ensure_netrc_from_env() -> None:
    """Allow EARTHDATA_USERNAME/PASSWORD env vars as an alternative to ~/.netrc (GDAL needs a netrc)."""
    user, pw = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if user and pw and not os.environ.get("GDAL_HTTP_NETRC_FILE"):
        path = CACHE_DIR / "netrc"
        path.write_text(f"machine urs.earthdata.nasa.gov login {user} password {pw}\n")
        path.chmod(0o600)
        os.environ["GDAL_HTTP_NETRC_FILE"] = str(path)
        os.environ.setdefault("NETRC", str(path))


_ensure_netrc_from_env()  # GDAL (HLS/ECOSTRESS COG reads) needs the netrc before the first read


def earthdata_fs():
    """Authenticated fsspec HTTPS filesystem for range reads of NASA HDF5/netCDF files."""
    global _fs
    with _auth_lock:
        if _fs is None:
            import earthaccess

            strategy = "environment" if os.environ.get("EARTHDATA_USERNAME") else "netrc"
            auth = earthaccess.login(strategy=strategy)
            if not auth or not auth.authenticated:
                raise RuntimeError("Earthdata login failed: check ~/.netrc or EARTHDATA_USERNAME/PASSWORD")
            _fs = earthaccess.get_fsspec_https_session()
        return _fs


def open_remote_h5(url: str):
    import h5py

    fo = earthdata_fs().open(url, block_size=2**20, cache_type="blockcache")
    return h5py.File(fo, "r")


# ---------------------------------------------------------------- HTTP / CMR
_http = httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=True, headers={"User-Agent": "parcel-data-api/0.1"})


def http_get_json(url: str, retries: int = 3, **params):
    """GET JSON, retrying transient failures (429/5xx, timeouts) with backoff."""
    for attempt in range(retries + 1):
        try:
            r = _http.get(url, params=params or None, headers={"Accept": "application/json"})
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


def cmr_granules(short_name: str, lat: float, lon: float, start: date | None = None, end: date | None = None,
                 n: int = 10, newest_first: bool = True) -> list[dict]:
    """Granules from NASA's CMR covering a point. Returns [{id, start, end, urls}]."""
    params = {"short_name": short_name, "page_size": n, "point": f"{lon},{lat}",
              "sort_key": "-start_date" if newest_first else "start_date"}
    if start or end:
        s0 = (start or date(2000, 1, 1)).isoformat()
        e0 = (end or date.today()).isoformat()
        params["temporal"] = f"{s0}T00:00:00Z,{e0}T23:59:59Z"
    items = _http.get("https://cmr.earthdata.nasa.gov/search/granules.umm_json", params=params).raise_for_status().json()["items"]
    out = []
    for it in items:
        u = it["umm"]
        rng = u.get("TemporalExtent", {}).get("RangeDateTime", {})
        rel = u.get("RelatedUrls", [])
        urls = [x["URL"] for x in rel if x.get("Type") == "GET DATA"]
        opendap = [x["URL"] for x in rel if "opendap.earthdata.nasa.gov" in x["URL"]]
        out.append({"id": u["GranuleUR"], "start": rng.get("BeginningDateTime"), "end": rng.get("EndingDateTime"),
                    "urls": urls, "opendap": opendap[0] if opendap else None})
    return out


def stac_search(collections: list[str], geometry: dict, start: date, end: date, limit: int = 250) -> list[dict]:
    """Search NASA CMR-STAC (LP DAAC cloud) for items intersecting a geometry; oldest first.

    Searches with the geometry's bounding box: detailed cadastre outlines can have hundreds of vertices,
    which CMR rejects (414) once pagination moves the query into the URL. Exact clipping happens at read time.
    """
    from shapely.geometry import mapping, shape

    bbox = list(shape(geometry).bounds)
    body = {"collections": collections, "bbox": bbox, "limit": limit,
            "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"}
    feats: list[dict] = []
    url = "https://cmr.earthdata.nasa.gov/stac/LPCLOUD/search"
    method = "POST"
    while url and len(feats) < 2000:
        r = _http.post(url, json=body) if method == "POST" else _http.get(url)
        data = r.raise_for_status().json()
        feats += data.get("features", [])
        nxt = next((l for l in data.get("links", []) if l.get("rel") == "next"), None)
        if not nxt:
            break
        url, method = nxt["href"], nxt.get("method", "GET").upper()
        body = nxt.get("body", body) if method == "POST" else None
    return sorted(feats, key=lambda f: f["properties"]["datetime"])


# ---------------------------------------------------------------- cache
# Two layers: memory (fast) in front of SQLite on the cache volume (survives restarts/redeploys).
_mem: dict = {}
_mem_lock = threading.Lock()
_key_locks: dict = {}
_db_lock = threading.Lock()
_db = None
DISK_CACHE = os.environ.get("PARCEL_API_DISK_CACHE", "1") == "1"


def _disk():
    global _db
    if _db is None:
        import sqlite3

        _db = sqlite3.connect(CACHE_DIR / "results.sqlite", check_same_thread=False, timeout=30)
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value BLOB NOT NULL)")
        _db.execute("DELETE FROM cache WHERE expires < ?", (time.time(),))
        _db.commit()
    return _db


def _disk_get(key: str):
    if not DISK_CACHE:
        return None
    try:
        with _db_lock:
            row = _disk().execute("SELECT expires, value FROM cache WHERE key = ?", (key,)).fetchone()
        if row and row[0] > time.time():
            return pickle.loads(row[1])
    except Exception as e:  # noqa: BLE001 — a broken cache must never break a request
        log.warning("disk cache read failed: %s", e)
    return None


def _disk_put(key: str, value, seconds: int) -> None:
    if not DISK_CACHE:
        return
    try:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with _db_lock:
            _disk().execute("INSERT OR REPLACE INTO cache (key, expires, value) VALUES (?, ?, ?)",
                            (key, time.time() + seconds, blob))
            _disk().commit()
    except Exception as e:  # noqa: BLE001
        log.warning("disk cache write failed: %s", e)


def ttl_cache(seconds: int):
    """Thread-safe TTL cache keyed by function args (args must be hashable, with a stable repr).

    Memory first, then SQLite on disk (CACHE_DIR/results.sqlite). Concurrent calls with the same key wait
    for the first one instead of downloading the same data twice. Exceptions are not cached.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
            with _mem_lock:
                hit = _mem.get(key)
                if hit and time.time() - hit[0] < seconds:
                    return hit[1]
                lock = _key_locks.setdefault(key, threading.Lock())
            with lock:
                with _mem_lock:
                    hit = _mem.get(key)
                    if hit and time.time() - hit[0] < seconds:
                        return hit[1]
                dkey = hashlib.sha256(repr(key).encode()).hexdigest()
                val = _disk_get(dkey)
                if val is None:
                    val = fn(*args, **kwargs)
                    _disk_put(dkey, val, seconds)
                with _mem_lock:
                    _mem[key] = (time.time(), val)
                return val
        return wrapper
    return deco


# ---------------------------------------------------------------- query + result
@dataclass(frozen=True)
class Query:
    history: bool = False
    start: date | None = None
    end: date | None = None

    @property
    def window(self) -> tuple[date, date]:
        end = self.end or date.today()
        start = self.start or end - timedelta(days=90)
        return max(start, end - timedelta(days=365)), end


def result(*, scale: str, resolution_m: float, source: str, status: str = "ok", date_=None, values=None,
           units=None, history=None, note=None, **extra) -> dict:
    out = {"status": status, "scale": scale, "resolution_m": resolution_m, "source": source}
    if date_ is not None:
        out["date"] = str(date_)
    if values is not None:
        out["values"] = values
    if units:
        out["units"] = units
    if history is not None:
        out["history"] = history
    if note:
        out["note"] = note
    out.update(extra)
    return out


def clean(v, digits: int = 4):
    """Round floats; NaN / fill values -> None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not np.isfinite(f) or f <= -999:  # NASA fill values: -999, -9999, -9999.9 ...
        return None
    return round(f, digits)


# ---------------------------------------------------------------- raster helpers
def stats(data: np.ndarray, ok: np.ndarray, n_inside: int) -> dict:
    """Summary of pixels where `ok` is True. n_inside = pixels whose centre is inside the parcel."""
    vals = data[ok & np.isfinite(data)]
    if vals.size == 0:
        return {"mean": None, "pixels": 0, "pixels_in_parcel": n_inside}
    return {"mean": float(vals.mean()), "min": float(vals.min()), "max": float(vals.max()),
            "std": float(vals.std()), "pixels": int(vals.size), "pixels_in_parcel": n_inside}


def zonal(url: str, geometry, scale: float = 1.0, offset: float = 0.0, band: int = 1) -> dict:
    """Mean/min/max of a remote raster over the parcel (pixel centres inside; tiny parcels → nearest pixel)."""
    data, inside, _, _ = read_window(url, geometry, band=band)
    return stats(data * scale + offset, inside, int(inside.sum()))


def read_window(url: str, geometry, band: int = 1, pad_pixels: int = 1):
    """Read a raster window covering the polygon. Returns (array float64 w/ NaN, inside-mask, transform, crs)."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom
    from rasterio.windows import from_bounds
    from shapely.geometry import mapping, shape

    with rasterio.open(url) as ds:
        g = shape(transform_geom("EPSG:4326", ds.crs, mapping(geometry)))
        minx, miny, maxx, maxy = g.bounds
        res = max(abs(ds.res[0]), abs(ds.res[1])) * pad_pixels
        win = from_bounds(minx - res, miny - res, maxx + res, maxy + res, ds.transform).round_offsets().round_lengths()
        arr = ds.read(band, window=win, masked=True, boundless=True)
        wt = ds.window_transform(win)
        inside = ~geometry_mask([mapping(g)], out_shape=arr.shape, transform=wt, all_touched=False)
        if not inside.any():  # parcel smaller than a pixel → the pixel under its interior point
            p = g.representative_point()
            col, row = ~wt * (p.x, p.y)
            inside[min(max(int(row), 0), arr.shape[0] - 1), min(max(int(col), 0), arr.shape[1] - 1)] = True
        return np.ma.filled(arr.astype("float64"), np.nan), inside, wt, ds.crs
