"""Async client for the `data-api` satellite & Earth-observation microservice."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

DATA_API_URL = os.getenv("DATA_API_URL", "http://127.0.0.1:8000").rstrip("/")

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
