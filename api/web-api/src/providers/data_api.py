"""Async client for the `data-api` satellite & Earth-observation microservice."""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

DATA_API_URL = os.getenv("DATA_API_URL", "http://127.0.0.1:8070").rstrip("/")

FAST_DATASETS = (
    "crop_health,evapotranspiration_field,terrain,"
    "weather,rainfall,soil_moisture,soil,groundwater"
)
SLOW_DATASETS = "evapotranspiration_area"


def is_snapshot_fresh(snapshot: dict[str, Any] | None, max_age_hours: int = 24) -> bool:
    """Return True if `nasa_snapshot` exists and was fetched within `max_age_hours`."""
    if not snapshot or not isinstance(snapshot, dict):
        return False
    fetched_at = snapshot.get("fetched_at")
    if not fetched_at:
        return False
    try:
        dt = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(hours=max_age_hours)
    except Exception:
        return False


def extract_datasets(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Extract the first parcel's `datasets` dict from a `data-api` response."""
    if not snapshot or not isinstance(snapshot, dict):
        return {}
    parcels = snapshot.get("parcels") or []
    if not parcels:
        return {}
    return parcels[0].get("datasets") or {}


def merge_telemetry_snapshots(
    base: dict[str, Any],
    enrichment: dict[str, Any],
) -> dict[str, Any]:
    """Merge Stage 2 dataset(s) (e.g. `evapotranspiration_area`) into a Stage 1 snapshot."""
    merged = dict(base)
    base_parcels = list(base.get("parcels") or [])
    enrich_parcels = enrichment.get("parcels") or []
    if base_parcels and enrich_parcels:
        p0 = dict(base_parcels[0])
        ds = dict(p0.get("datasets") or {})
        ds.update(enrich_parcels[0].get("datasets") or {})
        p0["datasets"] = ds
        timings = dict(p0.get("timings_s") or {})
        timings.update(enrich_parcels[0].get("timings_s") or {})
        p0["timings_s"] = timings
        base_parcels[0] = p0
        merged["parcels"] = base_parcels
    merged["enriched_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def summarize_sensor_gaps(
    datasets: dict[str, dict[str, Any]],
    soil_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect dataset `status` and `scale` to surface fallbacks and uncertainty flags."""
    fallbacks: list[str] = []
    alerts: list[str] = []

    et_field = datasets.get("evapotranspiration_field") or {}
    if et_field.get("status") != "ok":
        et_area = datasets.get("evapotranspiration_area") or {}
        if et_area.get("status") == "ok":
            fallbacks.append(
                "Field-level ECOSTRESS thermal data unavailable; using 500 m MODIS MOD16A2 evapotranspiration."
            )
        else:
            fallbacks.append(
                "Field-level ECOSTRESS thermal data unavailable for recent dates; using 55 km regional NASA POWER evapotranspiration."
            )

    hls = datasets.get("crop_health") or {}
    if hls.get("status") != "ok":
        fallbacks.append(
            "Recent cloud-free HLS 30 m optical pass unavailable; vegetation cover estimated from seasonal baseline."
        )

    grace = datasets.get("groundwater") or {}
    smap = datasets.get("soil_moisture") or {}
    grace_pct = (grace.get("values") or {}).get("percentile")
    smap_rz = (smap.get("values") or {}).get("root_zone_wetness") or (smap.get("values") or {}).get("rootzone_moisture")
    if grace.get("status") == "ok" and grace_pct is not None and float(grace_pct) < 25.0:
        if smap.get("status") == "ok" and smap_rz is not None and float(smap_rz) >= 0.35:
            alerts.append(
                f"Aquifer alert: GRACE-FO regional groundwater is low ({float(grace_pct):.0f}th percentile) "
                "despite adequate surface/root-zone moisture—avoid water-intensive summer crops relying on deep irrigation."
            )
        else:
            alerts.append(
                f"Regional groundwater is below normal ({float(grace_pct):.0f}th percentile, 300 km GRACE-FO)."
            )

    soil_verified = bool(soil_override and any(v is not None for v in soil_override.values()))
    return {
        "fallbacks": fallbacks,
        "alerts": alerts,
        "soil_badge": "Lab-Verified Soil" if soil_verified else "Satellite Estimate (250m)",
    }


def compute_soil_override_flags(soil_override: dict[str, Any] | None) -> list[str]:
    """Return sorted field paths (`soil.<key>`) for non-None manual soil overrides."""
    if not soil_override or not isinstance(soil_override, dict):
        return []
    return sorted(f"soil.{k}" for k, v in soil_override.items() if v is not None)


def merge_plot_with_overrides(
    datasets: dict[str, dict[str, Any]],
    soil_override: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Deep-copy `datasets` and apply manual overrides without mutating `nasa_snapshot`."""
    effective = copy.deepcopy(datasets or {})
    if soil_override and isinstance(soil_override, dict):
        soil_ds = dict(effective.get("soil") or {})
        soil_vals = dict(soil_ds.get("values") or {})
        applied = False
        for key, val in soil_override.items():
            if val is not None:
                soil_vals[key] = val
                applied = True
        if applied:
            soil_ds["values"] = soil_vals
            soil_ds.setdefault("status", "ok")
            soil_ds["overridden"] = True
            effective["soil"] = soil_ds
    return effective


def build_analysis_payload(plot: dict[str, Any]) -> dict[str, Any]:
    """Build an `analysis-api`-ready payload combining `nasa_snapshot` and manual overrides."""
    snapshot = plot.get("nasa_snapshot")
    soil_override = plot.get("soil_override") if isinstance(plot.get("soil_override"), dict) else {}
    raw_datasets = extract_datasets(snapshot)
    overridden_fields = plot.get("overridden_fields")
    if not isinstance(overridden_fields, list):
        overridden_fields = compute_soil_override_flags(soil_override)
    return {
        "plot_id": plot.get("id"),
        "cadastral_ref": plot.get("cadastral_ref"),
        "label": plot.get("label"),
        "area_ha": plot.get("area_ha"),
        "geometry": plot.get("geometry"),
        "baseline_rotation": plot.get("baseline_rotation"),
        "nasa_snapshot": snapshot,
        "soil_override": soil_override,
        "overridden_fields": overridden_fields,
        "effective_datasets": merge_plot_with_overrides(raw_datasets, soil_override),
    }


class DataApiClient:
    """Async client for `data-api` (`POST /geojson`, `GET /health`)."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 65.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("DATA_API_URL", DATA_API_URL)).rstrip("/")
        self.timeout = timeout
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout)

    async def fetch_plot_telemetry(
        self,
        geojson_feature: dict[str, Any],
        datasets: str = FAST_DATASETS,
        history: bool = True,
    ) -> dict[str, Any]:
        """Fetch satellite & model telemetry for a GeoJSON Feature/Polygon."""
        close_after = self._client is None
        http = await self._http()
        try:
            resp = await http.post(
                f"{self.base_url}/geojson",
                params={"datasets": datasets, "history": "true" if history else "false"},
                json=geojson_feature,
            )
            resp.raise_for_status()
            payload = resp.json()
            payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
            return payload
        finally:
            if close_after:
                await http.aclose()

    # --- Raw data-api passthroughs for the visualizer (long timeouts: cold sources can take minutes) ---
    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                       json: Any = None, timeout: float = 600.0) -> dict[str, Any]:
        close_after = self._client is None
        http = await self._http()
        try:
            resp = await http.request(method, f"{self.base_url}{path}", params=params, json=json, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        finally:
            if close_after:
                await http.aclose()

    async def fetch_datasets(
        self, geojson_feature: dict[str, Any], datasets: str, year: bool = False, history: bool = False
    ) -> dict[str, Any]:
        """Any data-api datasets for one parcel; returns the parcel entry (`datasets`, `timings_s`)."""
        params = {"datasets": datasets, "history": "true" if history else "false"}
        if year:
            params["year"] = "true"
        body = await self._request("POST", "/geojson", params=params, json=geojson_feature)
        parcel = (body.get("parcels") or [{}])[0]
        return {**parcel, "query": body.get("query"), "generated_at": body.get("generated_at")}

    async def fetch_imagery(
        self, geojson_feature: dict[str, Any], groups: str | None = None, date: str | None = None
    ) -> dict[str, Any]:
        """PNG layers (data URIs + bounds) for a parcel: HLS bands/indices, ECOSTRESS LST, NASADEM terrain."""
        params = {k: v for k, v in {"groups": groups, "date": date}.items() if v}
        return await self._request("POST", "/imagery", params=params, json=geojson_feature, timeout=300.0)

    async def fetch_layers(self) -> dict[str, Any]:
        """NASA GIBS tile layer templates for the web map."""
        return await self._request("GET", "/layers", timeout=120.0)
