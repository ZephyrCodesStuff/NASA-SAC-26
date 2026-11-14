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

from .core import Query, aggregate_periods, flatten_history, half_month_periods, ttl_cache
from .parcel import Parcel, ParcelParseError, parse_cadastre_gml, parse_geojson, point_parcel
from .sources import (crop_history, ecostress, erosion, eu_prices, faostat, grace, hls, imerg, modis_et, nasadem, nexgddp, power,
                      prices, smap, soilgrids)

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
    "crop_history": (crop_history, 300, "HLS NDVI season curves, last 5 years → crop group per year"),
    "climate_projection": (nexgddp, 300, "NEX-GDDP-CMIP6: 2030s/2050s rain, heat, water balance, drought risk"),
    "regional_production": (faostat, 240, "FAOSTAT: national crop area, yield, production, producer prices"),
    "market_prices": (prices, 120, "World Bank Pink Sheet: monthly oil, gas, fertilizer, grain prices"),
    "local_prices": (eu_prices, 120, "EU only — Eurostat crop selling prices, electricity, gas; EU Oil Bulletin diesel"),
}
# computed from other datasets (fetched automatically when needed)
DERIVED = {
    "erosion": (erosion, "RUSLE soil-loss risk from soil + terrain + rainfall normals + NDVI"),
}
HISTORY_TIMEOUT_FACTOR = 3
YEAR_TIMEOUT_FACTOR = 5
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


RESULT_TTL_S = 3 * 3600


@ttl_cache(RESULT_TTL_S)
def _fetch_cached(name: str, wkt: str, q: Query, day: str) -> dict:
    """Finished per-source result for a parcel shape (memory + disk). `day` makes entries roll over daily."""
    from shapely import wkt as W

    return SOURCES[name][0].fetch(Parcel(id="cached", geometry=W.loads(wkt)), q)


async def _run_source(name: str, parcel: Parcel, q: Query) -> tuple[str, dict, float]:
    _, timeout, _ = SOURCES[name]
    t0 = time.perf_counter()
    try:
        factor = YEAR_TIMEOUT_FACTOR if q.periods else HISTORY_TIMEOUT_FACTOR if q.history else 1
        res = await asyncio.wait_for(asyncio.to_thread(_fetch_cached, name, parcel.geometry.wkt, q, date.today().isoformat()),
                                     timeout * factor)
        if (q.periods and "periods" not in res and res.get("history")
                and getattr(SOURCES[name][0], "AGGREGATE_PERIODS", True)):
            start, end = q.window
            res = {**res, "periods": aggregate_periods(flatten_history(res["history"]), start, end)}
    except BaseException as e:  # noqa: BLE001 — one source must never break the response
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        log.warning("source %s failed for %s: %s", name, parcel.id, e)
        res = _error_entry(name, e)
    return name, res, round(time.perf_counter() - t0, 1)


async def _run_parcel(parcel: Parcel, q: Query, names: list[str]) -> dict:
    derived = [n for n in names if n in DERIVED]
    base = [n for n in names if n in SOURCES]
    needed = list(dict.fromkeys(base + [d for n in derived for d in DERIVED[n][0].DEPENDS]))
    out = await asyncio.gather(*(_run_source(n, parcel, q) for n in needed))
    fetched = {n: r for n, r, _ in out}
    datasets = {n: fetched[n] for n in base}
    for n in derived:
        try:
            datasets[n] = DERIVED[n][0].compute(parcel, fetched)
        except Exception as e:  # noqa: BLE001
            datasets[n] = _error_entry(n, e)
    if len(names) == len(SOURCES) + len(DERIVED):  # full request: also list datasets that aren't wired yet
        datasets.update(NOT_YET)
    return {"parcel": parcel.summary(), "datasets": datasets, "timings_s": {n: t for n, _, t in out}}


def year_window(today: date) -> tuple[date, date]:
    """Window covering the 24 half-month periods that end with the current one."""
    if today.day > 15:  # current = H2 → first is H1 of next month, one year ago
        y, m = (today.year, 1) if today.month == 12 else (today.year - 1, today.month + 1)
        return date(y, m, 1), today
    return date(today.year - 1, today.month, 16), today  # current = H1 → first is H2 of this month, one year ago


def _make_query(history: bool, start: date | None, end: date | None, year: bool = False) -> Query:
    if year:
        s, e = year_window(date.today())
        return Query(history=True, start=s, end=e, periods=True)
    if start and end and start > end:
        raise HTTPException(422, "start must be before end")
    if end and end > date.today():
        end = date.today()
    return Query(history=history, start=start, end=end)


def _select(datasets: str | None) -> list[str]:
    available = list(SOURCES) + list(DERIVED)
    if not datasets:
        return available
    names = [d.strip() for d in datasets.split(",") if d.strip()]
    unknown = [n for n in names if n not in available]
    if unknown:
        raise HTTPException(422, f"Unknown dataset(s): {unknown}. Available: {available}")
    return names


async def _respond(parcels: list[Parcel], q: Query, names: list[str]) -> JSONResponse:
    t0 = time.perf_counter()
    results = await asyncio.gather(*(_run_parcel(p, q, names) for p in parcels))
    body = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {"history": q.history, "periods": q.periods,
                  "window": [str(d) for d in q.window] if q.history else None, "datasets": names},
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "parcels": results,
    }
    return JSONResponse(body)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets")
def datasets():
    return ({name: {"description": desc, "timeout_s": t} for name, (_, t, desc) in SOURCES.items()}
            | {name: {"description": desc, "derived_from": m.DEPENDS} for name, (m, desc) in DERIVED.items()}
            | {k: {"description": v["note"]} for k, v in NOT_YET.items()})


@app.post("/parcel", summary="Data for the parcel(s) in an Italian cadastre GML/XML document")
async def parcel_endpoint(
    request: Request,
    history: bool = Q(False, description="Include time series"),
    start: date | None = Q(None, description="History start (default: 90 days before end; max 365 days)"),
    end: date | None = Q(None, description="History end (default: today)"),
    datasets: str | None = Q(None, description="Comma-separated subset, e.g. weather,crop_health"),
    year: bool = Q(False, description="Last 12 months of history + 24 half-month `periods` per dataset (overrides start/end)"),
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
    return await _respond(parcels, _make_query(history, start, end, year), _select(datasets))


@app.post("/geojson", summary="Data for GeoJSON parcel(s) (Feature, FeatureCollection or Polygon; WGS84 lon/lat)")
async def geojson_endpoint(
    request: Request,
    history: bool = Q(False, description="Include time series"),
    start: date | None = Q(None, description="History start (default: 90 days before end; max 365 days)"),
    end: date | None = Q(None, description="History end (default: today)"),
    datasets: str | None = Q(None, description="Comma-separated subset, e.g. weather,crop_health"),
    year: bool = Q(False, description="Last 12 months of history + 24 half-month `periods` per dataset (overrides start/end)"),
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
    return await _respond(parcels, _make_query(history, start, end, year), _select(datasets))


@app.get("/point", summary="Data for a ~30 m square around a lat/lon (testing, non-cadastre callers)")
async def point_endpoint(
    lat: float, lon: float,
    history: bool = False, start: date | None = None, end: date | None = None, datasets: str | None = None,
    year: bool = False,
):
    try:
        p = point_parcel(lat, lon)
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    return await _respond([p], _make_query(history, start, end, year), _select(datasets))


# ---------------------------------------------------------------- imagery + map layers
def _groups(groups: str | None) -> tuple:
    from .imagery import ALL_GROUPS

    if not groups:
        return ALL_GROUPS
    g = tuple(x.strip() for x in groups.split(",") if x.strip())
    bad = [x for x in g if x not in ALL_GROUPS]
    if bad:
        raise HTTPException(422, f"Unknown group(s) {bad}. Available: {list(ALL_GROUPS)}")
    return g


async def _imagery(parcel: Parcel, on: date | None, groups: tuple, layer: str | None, timeout: float = 240):
    from fastapi.responses import Response

    from .imagery import render

    try:
        out = await asyncio.wait_for(asyncio.to_thread(render, parcel.geometry.wkt, on, groups), timeout)
    except (asyncio.TimeoutError, TimeoutError) as e:
        raise HTTPException(504, "Imagery sources did not answer in time; try again (results are cached).") from e
    if layer:  # raw PNG of one layer, for <img src=...>
        for g in out["groups"].values():
            uri = (g.get("layers") or {}).get(layer)
            if uri:
                import base64

                return Response(base64.b64decode(uri.split(",", 1)[1]), media_type="image/png",
                                headers={"Cache-Control": "max-age=3600"})
        raise HTTPException(404, f"Layer '{layer}' not available for this parcel/date.")
    return JSONResponse({"parcel": parcel.summary(), **out})


@app.post("/imagery", summary="Satellite images of a GeoJSON parcel (true colour, infrared, SWIR, NDVI, NDMI, thermal, elevation)")
async def imagery_endpoint(
    request: Request,
    date_: date | None = Q(None, alias="date", description="Use the newest clear scene on/before this date (default: today)"),
    groups: str | None = Q(None, description="Subset of hls,lst,dem"),
    layer: str | None = Q(None, description="Return only this layer as image/png (e.g. ndvi)"),
):
    try:
        parcels = parse_geojson(await request.json())
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "Body must be GeoJSON") from e
    return await _imagery(parcels[0], date_, _groups(groups), layer)


@app.get("/imagery/point", summary="Satellite images around a lat/lon (~120 m square)")
async def imagery_point(lat: float, lon: float, date_: date | None = Q(None, alias="date"),
                        groups: str | None = None, layer: str | None = None):
    try:
        p = point_parcel(lat, lon, half_size_m=60)
    except ParcelParseError as e:
        raise HTTPException(422, str(e)) from e
    return await _imagery(p, date_, _groups(groups), layer)


@app.get("/layers", summary="NASA GIBS map tile layers (precipitation, soil moisture, NDVI, temperature, relief, imagery)")
async def layers_endpoint():
    from .layers import layers

    return await asyncio.to_thread(layers)


@app.get("/periods", summary="The 24 half-month periods used by ?year=true")
def periods_endpoint():
    s, e = year_window(date.today())
    return [{"period": p, "start": a.isoformat(), "end": b.isoformat()} for p, a, b in half_month_periods(s, e)]
