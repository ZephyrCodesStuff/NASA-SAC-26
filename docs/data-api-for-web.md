# Calling the data API from the web app

How `web/` gets satellite data for the parcel the farmer clicked.
Every field explained: [data-catalog.md](data-catalog.md). Full API reference: [api/data-api/README.md](../api/data-api/README.md) (or http://localhost:8070/docs when running).

## How it fits together

```
browser ──► web (NiceGUI :8080) ──► data-api (:8070) ──► NASA / ISRIC
                 │                        (in-memory cache)
                 └──► pocketbase (:8090)  user_plots.nasa_snapshot: stored data-api results
```

- Inside Docker, `web` reaches the API at **`http://data-api:8070`**, given in the env var `DATA_API_URL`.
  For local dev outside Docker, use `http://localhost:8070`.
- The API needs the Earthdata login in the root `.env` (see `.env.example`). Without it, most datasets return `error`.

## The call

`catasto.fetch_parcel_at_point()` already returns the parcel as a GeoJSON Feature.
Send that Feature, as it is, to `POST /geojson`:

```python
parcel = result["parcel"]  # from client.fetch_parcel_at_point(lat, lon)
r = await http.post(f"{DATA_API_URL}/geojson", json=parcel, timeout=300)
data = r.json()["parcels"][0]["datasets"]
ndvi = data["crop_health"]["values"]["ndvi"]["mean"]
```

Optional query parameters:
- `?datasets=weather,soil,terrain` returns only some datasets, which is faster.
- `?history=true&start=2026-05-01&end=2026-10-31` adds time series for charts.
- `?year=true` gives the last 12 months plus `periods` (24 half-months), for the season charts. The first call per parcel takes several minutes.
- Images: `POST /imagery` (same GeoJSON body) returns PNG layers with `bounds` for `L.imageOverlay`.
- Map layers: `GET /layers` returns NASA GIBS tile URLs (rain, soil moisture, NDVI, relief…).

## Ready-made provider (suggested `web/src/providers/nasa.py`)

Superseded by `web/src/providers/data_api.py`, which stores results in `user_plots.nasa_snapshot`. Kept as a minimal example.

```python
"""Client for the data-api service (satellite data for a parcel)."""
import hashlib
import json
import os
from datetime import date
from typing import Any

import httpx

DATA_API_URL = os.getenv("DATA_API_URL", "http://localhost:8070").rstrip("/")
PB_URL = os.getenv("PB_URL", "http://127.0.0.1:8090").rstrip("/")


class DataApiClient:
    def __init__(self, base_url: str = DATA_API_URL, pb_url: str | None = PB_URL):
        self.base_url = base_url
        self.pb_url = pb_url
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5))

    async def parcel_data(self, parcel: dict[str, Any], datasets: list[str] | None = None,
                          history: bool = False) -> dict[str, Any]:
        """All datasets for one GeoJSON parcel Feature. Cached in PocketBase for the day."""
        key = self._key(parcel, datasets, history)
        if (hit := await self._pb_get(key)) is not None:
            return hit
        params = {"history": str(history).lower()}
        if datasets:
            params["datasets"] = ",".join(datasets)
        r = await self._http.post(f"{self.base_url}/geojson", json=parcel, params=params)
        r.raise_for_status()
        result = r.json()["parcels"][0]
        if all(d.get("status") in ("ok", "no_data", "unavailable") for d in result["datasets"].values()):
            await self._pb_put(key, result)  # don't cache partial results (errors/timeouts)
        return result

    @staticmethod
    def _key(parcel, datasets, history) -> str:
        pid = parcel.get("id") or json.dumps(parcel["geometry"], sort_keys=True)
        raw = f"{pid}|{','.join(sorted(datasets or []))}|{history}|{date.today()}"
        return "data_api_" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def _pb_get(self, key: str):
        if not self.pb_url:
            return None
        try:
            r = await self._http.get(f"{self.pb_url}/api/collections/field_cache/records",
                                     params={"filter": f'cache_key="{key}"', "perPage": 1}, timeout=2)
            items = (r.json().get("items") or []) if r.status_code == 200 else []
            if items:
                p = items[0]["payload"]
                return json.loads(p) if isinstance(p, str) else p
        except Exception:
            pass
        return None

    async def _pb_put(self, key: str, payload: dict) -> None:
        if not self.pb_url:
            return
        try:
            await self._http.post(f"{self.pb_url}/api/collections/field_cache/records",
                                  json={"cache_key": key, "payload": payload}, timeout=2)
        except Exception:
            pass
```

## Using it in the UI (NiceGUI)

A first request for a new parcel takes **1–2.5 minutes**. A repeat request for the same parcel (cached) takes about 1–2 s.
The call is async, so it doesn't freeze the UI. Still, show a spinner, and never put this call on page load.

In `map_picker.py`, after `state["selected_parcel"] = parcel`:

```python
data_client = DataApiClient()

async def load_field_data(parcel):
    spinner.visible = True
    try:
        result = await data_client.parcel_data(parcel)
    except httpx.HTTPError as exc:
        ui.notify(f"Satellite data unavailable: {exc}", type="warning")
        return
    finally:
        spinner.visible = False
    render_cards(result["datasets"])  # your UI

background_tasks.create(load_field_data(parcel))  # from nicegui import background_tasks
```

Tip: load the fast datasets first (`datasets=weather,soil,terrain,rainfall`, a few seconds),
then the rest in a second call.

## Reading the response

Every dataset has the same envelope:

| field | meaning |
|---|---|
| `status` | `ok` · `no_data` (nothing valid, e.g. clouds) · `error` · `timeout` · `unavailable`. **Always check before reading `values`.** |
| `scale` | `field` = measured on the parcel itself; `area` = describes the surroundings (≥ 250 m). Show this to the farmer. |
| `date` | date of the observation (`static` for soil and terrain) |
| `values` | the numbers (below) |
| `units`, `note`, `source` | for the "How this was calculated & NASA sources" section |

## Which values feed which formula (`src/formulas.py`)

| Formula input | Take it from |
|---|---|
| Rainfall P (FAO-56) | `rainfall.values.total_30d_mm` / `total_7d_mm` (or `weather.values.last_30_days.precip_mm`) |
| Actual ET | `evapotranspiration_field.values.et_daily.mean` (mm/day, field); backup: `evapotranspiration_area.values.et_mm_per_day` |
| Reference / potential ET (ET₀ proxy) | `evapotranspiration_area.values.pet_mm_8day / 8` |
| Water stress | `evapotranspiration_field.values.esi.mean` (0–1, low = stressed), `evapotranspiration_area.values.et_pet_ratio` |
| Soil moisture | `soil_moisture.values.rootzone_m3m3`, `rootzone_wetness` (0–1) |
| GDD / frost / heat | `weather.values.gdd_since_jan1.value`, `last_7_days.frost_days`, `heat_days_over_35c` |
| RUSLE K (erodibility) | `soil.values["0-5cm"]`: `clay`, `silt`, `sand` (%), `soc` (g/kg), `texture_class` |
| RUSLE LS (slope) | `terrain.values.slope_deg.mean`, `share_steeper_than_8deg` |
| RUSLE C (cover) | `crop_health.values.ndvi.mean`; for bare vs. vegetated months use `?history=true` → `crop_health.history[].ndvi` |
| Nitrogen budget | `soil.values["0-5cm"].nitrogen` (g/kg), `bdod` (g/cm³), `crop_health.values.ndre.mean` (crop N status, Sentinel-2 only) |
| Waterlogging risk | `terrain.values.low_spot`, `relative_elevation_m` |
| Patchy field | `crop_health.values.low_vigor_fraction` |
| Regional drought context | `groundwater.values.interpretation`, `percentile_vs_same_month_all_years` |

## Demo tip

Warm the demo parcels before going on stage. Each one needs one call, after which repeat calls are instant:

```bash
curl -s -X POST "http://<server>:8070/geojson" -H 'Content-Type: application/json' -d @parcel.json > /dev/null
```

The API keeps its cache on disk, so warmed parcels stay fast across restarts and redeploys.

## Quick test from the command line

```bash
curl "http://localhost:8070/point?lat=45.0921&lon=7.5735&datasets=weather,soil"
```
