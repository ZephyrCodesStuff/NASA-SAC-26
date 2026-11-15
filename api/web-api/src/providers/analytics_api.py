"""Async client for the `analytics-api` (3-year rotation plan + Gemini advisory) and the adapter
that turns a plot's data-api `nasa_snapshot` + user overrides into an `analysis-api` ingestion payload.

Data-layering rule (the whole point): user-supplied ground truth (soil overrides, in-situ sensor
readings, prices) is placed in `local_user_data` / `economic_prices` so the analytics-api's parser
layers it *on top of* the NASA baseline in `nasa_data` — user data wins when present.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

import httpx

ANALYTICS_API_URL = os.getenv("ANALYTICS_API_URL", "http://127.0.0.1:8000").rstrip("/")


# --------------------------------------------------------------------------- helpers
def _values(ds: dict[str, Any] | None) -> dict[str, Any]:
    if ds and isinstance(ds, dict) and ds.get("status") == "ok":
        vals = ds.get("values")
        return vals if isinstance(vals, dict) else {}
    return {}


def _num(values: dict[str, Any], *paths: str) -> float | None:
    for p in paths:
        v: Any = values
        for key in p.split("."):
            if not isinstance(v, dict):
                v = None
                break
            v = v.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _first(values: dict[str, Any], *paths: str) -> float | None:
    for p in paths:
        v = _num(values, p)
        if v is not None:
            return v
    return None


def _centroid(geometry: Any) -> tuple[float, float]:
    try:
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not coords:
            return 45.07, 7.68
        ring = coords[0] if isinstance(coords[0], list) and isinstance(coords[0][0], (list, tuple)) else coords
        lons = [pt[0] for pt in ring]
        lats = [pt[1] for pt in ring]
        if lons and lats:
            return sum(lats) / len(lats), sum(lons) / len(lons)
    except Exception:
        pass
    return 45.07, 7.68


_CROP_NAMES = {
    "maize": "Corn (Maize)",
    "corn": "Corn (Maize)",
    "winter wheat": "Winter Wheat",
    "wheat": "Winter Wheat",
    "barley": "Barley (Low-Input Cereal)",
    "soybean": "Soybeans",
    "soy": "Soybeans",
    "alfalfa": "Alfalfa / Clover (Perennial Legume)",
    "cover clover": "Alfalfa / Clover (Perennial Legume)",
    "sunflower": "Sunflowers",
    "rice": "Rice",
    "sorghum": "Grain Sorghum",
}


def _crop_name(raw: str) -> str:
    s = (raw or "").lower()
    for key, name in _CROP_NAMES.items():
        if key in s:
            return name
    if "winter cereal" in s or "rapeseed" in s:
        return "Winter Wheat"
    if "summer crop" in s:
        return "Corn (Maize)"
    if "grass" in s or "meadow" in s or "perennial" in s or "orchard" in s or "vineyard" in s:
        return "Alfalfa / Clover (Perennial Legume)"
    return "Corn (Maize)"


# --------------------------------------------------------------------------- adapter
def build_ingestion_payload(
    plot: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
    soil_override: dict[str, Any] | None = None,
    sensor_readings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map data-api datasets + plot user data → `analysis-api` `FullFieldIngestionPayload`."""
    ov = soil_override if isinstance(soil_override, dict) else {}

    w = _values(datasets.get("weather"))
    rain = _values(datasets.get("rainfall"))
    smap = _values(datasets.get("soil_moisture"))
    etf = _values(datasets.get("evapotranspiration_field"))
    eta = _values(datasets.get("evapotranspiration_area"))
    hls = _values(datasets.get("crop_health"))
    soil = _values(datasets.get("soil"))
    terr = _values(datasets.get("terrain"))
    prices = _values(datasets.get("local_prices"))
    hist = _values(datasets.get("crop_history"))
    gw = _values(datasets.get("groundwater"))

    topsoil = soil.get("0-5cm") if isinstance(soil.get("0-5cm"), dict) else {}

    lat, lon = _centroid(plot.get("geometry"))
    area_ha = float(plot.get("area_ha") or 1.0)

    # Climate / water scalars
    mean_temp = _first(w, "last_30_days.t_mean_c", "latest.T2M") or 14.0
    rain_30d = _first(rain, "total_30d_mm") or _first(w, "last_30_days.precip_mm") or 60.0
    annual_precip = round(rain_30d * 12.2, 1)
    et_daily = _first(etf, "et_daily.mean") or _first(eta, "et_mm_8day") or _first(w, "last_30_days.evapotranspiration_mm")
    et0_annual = round((et_daily or 3.2) * 365.0, 1)
    rz_wetness = _first(smap, "rootzone_wetness", "rootzone_m3m3")
    rz_moisture = round((rz_wetness or 0.26) * 100.0, 1)
    ndvi = _first(hls, "ndvi.mean")
    ndmi = _first(hls, "ndmi.mean")
    ndre = _first(hls, "ndre.mean")
    gdd = _first(w, "gdd_since_jan1.value") or 1650.0

    # Soil
    clay = _first(topsoil, "clay")
    sand = _first(topsoil, "sand")
    silt = _first(topsoil, "silt")
    soc = _first(topsoil, "soc")
    soil_ph = _first(topsoil, "phh2o") or 6.7
    texture = topsoil.get("texture_class") if isinstance(topsoil.get("texture_class"), str) else None

    # Terrain
    elev = _first(terr, "elevation_m.mean") or 250.0
    slope_deg = _first(terr, "slope_deg.mean", "field_gradient_deg") or 2.0
    slope_pct = round(slope_deg * 1.75, 2)
    low_spot = bool(terr.get("low_spot") or terr.get("low_spot_flag"))

    # Crop history (preceding crops) from data-api crop_history, or baseline_rotation
    seasons = hist.get("seasons") if isinstance(hist.get("seasons"), list) else []
    historical_seasons: list[dict[str, Any]] = []
    for s in seasons:
        if not isinstance(s, dict):
            continue
        year = s.get("year")
        if not isinstance(year, int):
            continue
        historical_seasons.append({"year": year, "crop_name": _crop_name(str(s.get("crop_group") or ""))})
    if not historical_seasons:
        base = plot.get("baseline_rotation") if isinstance(plot.get("baseline_rotation"), list) else []
        crops = [_crop_name(str(c)) for c in base if c] or ["Corn (Maize)"]
        this_year = date.today().year
        historical_seasons = [{"year": this_year - (len(crops) - i), "crop_name": c} for i, c in enumerate(crops)]

    # Economic prices: NASA/local prices, overridden by user inputs
    diesel = None
    fuel = prices.get("fuel") if isinstance(prices.get("fuel"), dict) else {}
    diesel_series = fuel.get("diesel") if isinstance(fuel.get("diesel"), dict) else {}
    diesel = _first(diesel_series, "latest_without_taxes.eur_per_litre")
    elec = _first(prices, "energy.electricity.MWH500-1999.excl_taxes")
    # electricity series last price
    elec_series = prices.get("energy", {}).get("electricity", {}).get("MWH500-1999", {}).get("excl_taxes") if isinstance(prices.get("energy"), dict) else None
    if isinstance(elec_series, list) and elec_series:
        last = elec_series[-1]
        if isinstance(last, dict):
            elec = _num(last, "price")

    user_water = ov.get("water_price_eur_m3")
    user_elec = ov.get("electricity_price_eur_kwh")
    user_ph = ov.get("ph")

    payload: dict[str, Any] = {
        "parcel_info": {
            "parcel_id": str(plot.get("id") or "plot"),
            "field_name": plot.get("label"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "boundary_geojson": plot.get("geometry"),
            "area_hectares": round(area_ha, 2),
            "soil_type": texture,
        },
        "harvest_history": {"historical_seasons": historical_seasons},
        "economic_prices": {
            "diesel_fuel_price_usd_liter": round(diesel or 1.15, 3),
            "irrigation_water_price_usd_m3": float(user_water) if user_water is not None else 0.08,
            "electricity_pumping_tariff_usd_kwh": float(user_elec) if user_elec is not None else (round(elec or 0.12, 3)),
            "labor_hourly_wage_usd": 22.0,
        },
        "nasa_data": {
            "nasa_power": {
                "t2m_mean_c": round(mean_temp, 2),
                "fao56_et0_annual_mm": et0_annual,
                "solar_radiation_mj_m2": _first(w, "latest.ALLSKY_SFC_SW_DWN") or 18.0,
                "growing_degree_days_base10": round(gdd, 1),
            },
            "gpm_imerg": {"annual_rainfall_mm": annual_precip},
            "smap_moisture": {"rootzone_moisture_m3_m3": round((rz_wetness or 0.26), 3)},
            "hls_vegetation": {
                "ndvi_peak": ndvi if ndvi is not None else 0.6,
                "ndwi_peak": ndmi,
                "ndre_peak": ndre,
            },
            "soilgrids": {
                "texture_class": texture,
                "soil_organic_carbon_pct": soc,
                "soil_ph_h2o": soil_ph,
                "clay_percentage": clay,
                "sand_percentage": sand,
                "silt_percentage": silt,
            },
        },
        "elevation_maps": {
            "elevation_mean_m": round(elev, 1),
            "slope_mean_pct": slope_pct,
            "waterlogging_depression_present": low_spot,
        },
        "local_user_data": {},
    }

    # User overrides layer on top of the NASA baseline (user wins).
    lud = payload["local_user_data"]
    if isinstance(ov.get("soil_type"), str) and ov["soil_type"]:
        lud["soil_type"] = ov["soil_type"]
    elif isinstance(ov.get("texture_class"), str) and ov["texture_class"]:
        lud["soil_type"] = ov["texture_class"]
    if user_ph is not None:
        lud["lab_soil_ph"] = float(user_ph)
    if ov.get("organic_matter_pct") is not None:
        lud["lab_soil_organic_matter_pct"] = float(ov["organic_matter_pct"])
    if ov.get("compaction_psi") is not None:
        lud["penetrometer_compaction_psi"] = float(ov["compaction_psi"])

    # In-situ sensor readings (latest soil moisture) as user ground truth
    if isinstance(sensor_readings, list) and sensor_readings:
        latest = sensor_readings[-1]
        moisture = latest.get("soil_moisture") if isinstance(latest, dict) else None
        if isinstance(moisture, (int, float)):
            lud["in_situ_soil_moisture_vol_pct"] = float(moisture)

    # Groundwater trend note
    gw_trend = str(gw.get("interpretation") or "") if gw else ""
    if gw_trend:
        payload["nasa_data"]["grace_groundwater"] = {"terrestrial_water_storage_trend": gw_trend}

    return payload


# --------------------------------------------------------------------------- client
class AnalyticsApiClient:
    """Async client for the `analytics-api` (`POST /api/projections/plan-3year`)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or ANALYTICS_API_URL).rstrip("/")
        self.timeout = timeout

    async def plan_3year(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(f"{self.base_url}/api/projections/plan-3year", json=payload)
            resp.raise_for_status()
            return resp.json()


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    return parts or [text]


def shape_projection_response(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize the analytics-api response for the UI.

    The projection panel expects the advisory's benefits/drawbacks/risks/rewards as string
    *lists*, while the analytics-api emits prose strings — split them into bullets.
    """
    adv = result.get("gemini_advisory")
    if isinstance(adv, dict):
        adv = dict(adv)
        breakdowns = adv.get("strategies_breakdown")
        if isinstance(breakdowns, list):
            for b in breakdowns:
                if not isinstance(b, dict):
                    continue
                for key in ("benefits_plain_words", "drawbacks_plain_words", "risks_taken", "expected_rewards"):
                    val = b.get(key)
                    if isinstance(val, str):
                        b[key] = _split_sentences(val)
            adv["strategies_breakdown"] = breakdowns
        result["gemini_advisory"] = adv
    return result
