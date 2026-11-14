# data-api — satellite data for a field

Give it a field boundary, get back what the satellites and models say about that field — weather, rain,
soil moisture, crop water use and stress, crop health, soil, groundwater, terrain — as one JSON document.

Runs as the `data-api` service in the root `compose.yaml`; the web app reaches it at `http://data-api:8070`
(`DATA_API_URL`). Interactive docs: http://localhost:8070/docs

## Setup

1. Free NASA Earthdata account: https://urs.earthdata.nasa.gov
2. On that account: **Applications → Authorized Apps → Approve More Applications → "NASA GESDISC DATA ARCHIVE"**
   (needed for IMERG rainfall).
3. In the repo root: `cp .env.example .env` and fill `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`.
4. `docker compose up --build -d`

Local dev without Docker: `cd data-api && uv run uvicorn app.main:app --reload --port 8070`
(credentials from `.env` variables or `~/.netrc`). Tests: `uv run pytest` (offline, no credentials needed).

## Endpoints

| Method | Path | Body | Use |
|---|---|---|---|
| POST | `/geojson` | GeoJSON `Feature`, `FeatureCollection` or `Polygon` (WGS84 lon/lat) | what `web/src/providers/catasto.py` produces |
| POST | `/parcel` | raw Catasto WFS GML 3.2 (EPSG:6706, lat/lon order handled) | straight from Agenzia delle Entrate |
| GET | `/point?lat=&lon=` | — | ~30 m square around a point (testing) |
| POST | `/imagery` | GeoJSON parcel | PNG images: true colour, colour-infrared, agriculture (SWIR), SWIR moisture, NDVI, NDMI, NDRE, thermal, ECOSTRESS LST, elevation, hillshade, slope (`?date=`, `?groups=hls,lst,dem`, `?layer=ndvi` → raw PNG) |
| GET | `/imagery/point?lat=&lon=` | — | same, ~120 m square |
| GET | `/layers` | — | NASA GIBS tile layers for the web map (rain, soil moisture, NDVI, LST, relief, HLS 30 m) |
| GET | `/periods` | — | the 24 half-month periods used by `year=true` |
| GET | `/datasets` | — | list of datasets |
| GET | `/health` | — | health check |

Query options on all data endpoints:
- `datasets=weather,crop_health` — only some datasets (faster)
- `history=true` — add time series; `start` / `end` (ISO dates, default last 90 days, max 365)

Up to 20 parcels per request.

## Response

```jsonc
{
  "parcels": [{
    "parcel": { "id": "IT.AGE.PLA.F257_025400.121", "area_ha": 1.58, "centroid": {...}, "geometry": {...} },
    "datasets": {
      "crop_health": {
        "status": "ok",            // ok | no_data | error | timeout | unavailable
        "scale": "field",          // field = measured on the parcel; area = coarser than the parcel
        "resolution_m": 30,
        "date": "2026-10-29",
        "values": { "ndvi": {"mean": 0.75, ...}, "low_vigor_fraction": 0.0, ... },
        "units": {...}, "note": "...", "history": [...]   // history only with ?history=true
      },
      ...
    },
    "timings_s": {...}
  }]
}
```

A dataset that fails never fails the request — check each `status`.

## Datasets

| key | source | scale | what you get |
|---|---|---|---|
| `weather` | NASA POWER (daily, AG community) | area ~55 km | temp, rain, radiation, humidity, wind, ET; last 7/30 days; GDD (base 10 °C) since 1 Jan |
| `rainfall` | NASA GPM IMERG Late daily V07 | area ~11 km | last day, 3/7/30-day totals, consecutive dry days |
| `soil_moisture` | NASA SMAP L4 (SPL4SMGP v8) | area 9 km | surface (0–5 cm) and root-zone (0–100 cm) moisture, wetness |
| `evapotranspiration_field` | NASA ECOSTRESS v2 (JET, ESI, LSTE) | **field 70 m** | daily ET (mm/day), Evaporative Stress Index, surface temp — latest clear daytime overpass |
| `evapotranspiration_area` | NASA MODIS MOD16A2 v6.1 (ORNL DAAC) | area 500 m | 8-day ET, potential ET, ET/PET ratio |
| `crop_health` | NASA HLS v2 (Landsat 8/9 + Sentinel-2) | **field 30 m** | NDVI, NDMI, NDRE (S2), share of field with low vigor; clouds removed (Fmask) |
| `soil` | ISRIC SoilGrids 2.0 | area 250 m | clay/sand/silt, texture class, organic carbon, pH, N, CEC, bulk density at 0–5/5–15/15–30 cm |
| `groundwater` | NASA/JPL GRACE-FO mascon RL06.3 | area ~300 km | water storage anomaly, 12-month trend, percentile vs same month in past years |
| `terrain` | NASA NASADEM | **field 30 m** | elevation, slope, aspect, share > 8°, low-spot (waterlogging) flag |
| `crop_history` | NASA HLS NDVI phenology, 5 years | **field 30 m** | crop group per year (winter cereal, summer crop, rice, double crop, grassland…), 24-point season curve per year |
| `climate_projection` | NASA NEX-GDDP-CMIP6 (2 models, SSP2-4.5 / SSP5-8.5) | area 25 km | 2030s / 2050s rain, PET, water balance, heat/frost days, dry spells, drought risk; 24-period seasonal shape vs today |
| `regional_production` | FAOSTAT bulk (QCL + PP) | country | top 30 crops: area, yield, production, producer price — last 10 years |
| `market_prices` | World Bank Pink Sheet | global | monthly crude oil, gas, fertilizers, grains, vegetable oils — last 60 months |
| `local_prices` | Eurostat + EU Weekly Oil Bulletin (+ EU Agri-food portal) | country (EU only) | farm-gate crop prices, business electricity and gas, weekly diesel and heating oil |
| `erosion` | RUSLE from soil + terrain + POWER normals + HLS | field | R, K, LS, C factors; soil loss bare vs current cover; risk class |
| `crop_type` | ESA WorldCereal 2021 | — | not wired yet |

`?year=true` returns the last 12 months of every time series plus `periods`: 24 half-month summaries
(1st–15th / 16th–end). Field-by-field reference: [docs/data-catalog.md](../docs/data-catalog.md).

## Speed & caching

First request for a new place: ~1–2.5 min (MODIS/ORNL is the slow one, ECOSTRESS/HLS scan recent overpasses).
Repeat requests: ~0–2 s — **also after a restart or redeploy**.

Two cache layers, both inside the service (no PocketBase dependency):
- raw downloads per source (one SMAP cell, one IMERG day, …), shared between neighbouring parcels — hours to 30 days;
- finished per-dataset result per parcel shape and query — 3 h, rolls over daily.

Both live in memory and in SQLite at `/cache/results.sqlite` on the `data_api_cache` volume (with the DEM tiles).
To clear: `docker compose exec data-api rm /cache/results.sqlite*` and restart.
For demos, warm the demo parcels once on the server; they stay warm across redeploys.

## Known limits

- ECOSTRESS covers ~52°N–52°S and overpasses are irregular; values from different dates.
- NASADEM covers 56°S–60°N.
- POWER and SMAP lag 2–4 days; MODIS ET 2–4 weeks; GRACE a few months.
- Area-scale values describe the surroundings, not the parcel — the `scale` field says which.
- SoilGrids REST is rate-limited (~5/min); falls back to reading the maps directly.

Design notes: [DESIGN.md](DESIGN.md).
