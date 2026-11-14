"""Parcel Data API — one call returns every global dataset for an Italian cadastre parcel (or a point)."""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import FastAPI, HTTPException, Query as Q, Request
from fastapi.responses import JSONResponse

from .core import Query
from .parcel import Parcel, ParcelParseError, parse_cadastre_gml, parse_geojson, point_parcel
from .sources import ecostress, grace, hls, imerg, modis_et, nasadem, power, smap, soilgrids

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("parcel_api")

# name -> (module, timeout seconds for current / history, what it is for)
SOURCES = {
    "weather": (power, 60, "NASA POWER: temperature, rain, radiation, humidity, wind, GDD"),
    "rainfall": (imerg, 90, "GPM IMERG: satellite rainfall totals and dry spells"),
    "soil_moisture": (smap, 120, "SMAP L4: surface and root-zone soil moisture"),
    "evapotranspiration_field": (ecostress, 150, "ECOSTRESS: field ET, evaporative stress index, surface temperature"),
    "evapotranspiration_area": (modis_et, 180, "MODIS MOD16A2: 8-day ET / potential ET (backup for ECOSTRESS)"),
    "crop_health": (hls, 120, "HLS: NDVI, NDMI, NDRE over the field"),
    "soil": (soilgrids, 90, "SoilGrids: texture, organic carbon, pH, N, CEC, bulk density"),
    "groundwater": (grace, 90, "GRACE-FO: regional water storage anomaly"),
    "terrain": (nasadem, 90, "NASADEM: elevation, slope, aspect, low spots"),
}
HISTORY_TIMEOUT_FACTOR = 3
MAX_PARCELS = 20
NOT_YET = {
    "crop_type": {"status": "unavailable", "scale": "field", "source": "ESA WorldCereal 2021",
                  "note": "Not wired yet: only available as 15–25 GB global archives or via Google Earth Engine."},
}

@asynccontextmanager
async def lifespan(_app):
    # sources block on network I/O in threads; give them room beyond the default pool size
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=64))
    yield


app = FastAPI(title="Parcel Data API", version="0.1.0", lifespan=lifespan,
              description="Satellite and model data for a farm parcel, from NASA and partner global datasets.")


def _error_entry(name: str, exc: BaseException) -> dict:
    msg = f"{type(exc).__name__}: {exc}"[:400]
    entry = {"status": "error", "error": msg}
    if "403" in msg and "gesdisc" in msg.lower():
        entry.update(status="unavailable",
                     note="Earthdata account must approve the 'NASA GESDISC DATA ARCHIVE' application "
                          "(urs.earthdata.nasa.gov → Applications → Authorized Apps).")
    elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        entry.update(status="timeout", error="Source did not answer in time; try again (results are cached once they arrive).")
    return entry


async def _run_source(name: str, parcel: Parcel, q: Query) -> tuple[str, dict, float]:
    module, timeout, _ = SOURCES[name]
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(asyncio.to_thread(module.fetch, parcel, q),
                                     timeout * (HISTORY_TIMEOUT_FACTOR if q.history else 1))
    except BaseException as e:  # noqa: BLE001 — one source must never break the response
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        log.warning("source %s failed for %s: %s", name, parcel.id, e)
        res = _error_entry(name, e)
    return name, res, round(time.perf_counter() - t0, 1)


async def _run_parcel(parcel: Parcel, q: Query, names: list[str]) -> dict:
    out = await asyncio.gather(*(_run_source(n, parcel, q) for n in names))
    datasets = {n: r for n, r, _ in out}
    if len(names) == len(SOURCES):  # full request: also list datasets that aren't wired yet
        datasets.update(NOT_YET)
    return {"parcel": parcel.summary(), "datasets": datasets, "timings_s": {n: t for n, _, t in out}}


def _make_query(history: bool, start: date | None, end: date | None) -> Query:
    if start and end and start > end:
        raise HTTPException(422, "start must be before end")
    if end and end > date.today():
        end = date.today()
    return Query(history=history, start=start, end=end)


def _select(datasets: str | None) -> list[str]:
    if not datasets:
        return list(SOURCES)
    names = [d.strip() for d in datasets.split(",") if d.strip()]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise HTTPException(422, f"Unknown dataset(s): {unknown}. Available: {list(SOURCES)}")
    return names


async def _respond(parcels: list[Parcel], q: Query, names: list[str]) -> JSONResponse:
    t0 = time.perf_counter()
    results = await asyncio.gather(*(_run_parcel(p, q, names) for p in parcels))
    body = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {"history": q.history, "window": [str(d) for d in q.window] if q.history else None, "datasets": names},
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "parcels": results,
    }
    return JSONResponse(body)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets")
def datasets():
    return {name: {"description": desc, "timeout_s": t} for name, (_, t, desc) in SOURCES.items()} | {
        k: {"description": v["note"]} for k, v in NOT_YET.items()}


@app.post("/parcel", summary="Data for the parcel(s) in an Italian cadastre GML/XML document")
async def parcel_endpoint(
    request: Request,
    history: bool = Q(False, description="Include time series"),
    start: date | None = Q(None, description="History start (default: 90 days before end; max 365 days)"),
    end: date | None = Q(None, description="History end (default: today)"),
    datasets: str | None = Q(None, description="Comma-separated subset, e.g. weather,crop_health"),
):
    body = await request.body()
    if not body:
        raise HTTPException(400, "Send the cadastre XML (WFS GetFeature response) as the request body.")
    try:
        parcels = parse_cadastre_gml(body)
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    if len(parcels) > MAX_PARCELS:
        raise HTTPException(413, f"Too many parcels ({len(parcels)}); max {MAX_PARCELS} per request.")
    return await _respond(parcels, _make_query(history, start, end), _select(datasets))


@app.post("/geojson", summary="Data for GeoJSON parcel(s) (Feature, FeatureCollection or Polygon; WGS84 lon/lat)")
async def geojson_endpoint(
    request: Request,
    history: bool = Q(False, description="Include time series"),
    start: date | None = Q(None, description="History start (default: 90 days before end; max 365 days)"),
    end: date | None = Q(None, description="History end (default: today)"),
    datasets: str | None = Q(None, description="Comma-separated subset, e.g. weather,crop_health"),
):
    try:
        obj = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "Body must be JSON (GeoJSON)") from e
    try:
        parcels = parse_geojson(obj)
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    if len(parcels) > MAX_PARCELS:
        raise HTTPException(413, f"Too many parcels ({len(parcels)}); max {MAX_PARCELS} per request.")
    return await _respond(parcels, _make_query(history, start, end), _select(datasets))


@app.get("/point", summary="Data for a ~30 m square around a lat/lon (testing, non-cadastre callers)")
async def point_endpoint(
    lat: float, lon: float,
    history: bool = False, start: date | None = None, end: date | None = None, datasets: str | None = None,
):
    try:
        p = point_parcel(lat, lon)
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    return await _respond([p], _make_query(history, start, end), _select(datasets))
