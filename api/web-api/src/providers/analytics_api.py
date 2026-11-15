"""Async client for the `analytics-api` (3-year rotation plan + Gemini advisory) and the adapter
that turns a plot's data-api `nasa_snapshot` + user overrides into an `analysis-api` ingestion payload.

Data-layering rule (the whole point): user-supplied ground truth (soil overrides, in-situ sensor
readings, prices) is placed in `local_user_data` / `economic_prices` so the analytics-api's parser
layers it *on top of* the NASA baseline in `nasa_data` — user data wins when present.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date
from typing import Any

import httpx

from src.crop_preferences import crop_preferences

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


_MONTH_INFO = [
    ("jan", 31, 15), ("feb", 28.25, 46), ("mar", 31, 75), ("apr", 30, 105),
    ("may", 31, 135), ("jun", 30, 166), ("jul", 31, 196), ("aug", 31, 227),
    ("sep", 30, 258), ("oct", 31, 288), ("nov", 30, 319), ("dec", 31, 349),
]
_WARM_MONTHS_NORTH = {"apr", "may", "jun", "jul", "aug", "sep"}
_EUR_TO_USD = 1.08


def _extraterrestrial_ra_mm_day(lat_deg: float, doy: int) -> float:
    """FAO-56 Eq. 21 extraterrestrial radiation converted to equivalent evaporation (mm/day)."""
    lat_rad = math.radians(max(-66.0, min(66.0, lat_deg)))
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
    delta = 0.409 * math.sin((2.0 * math.pi * doy / 365.0) - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(delta))))
    ra_mj = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat_rad) * math.sin(delta) + math.cos(lat_rad) * math.cos(delta) * math.sin(ws)
    )
    return ra_mj * 0.408  # 1 MJ/m2/day = 0.408 mm/day


def _monthly_climate_breakdown(normals: Any, lat: float) -> dict[str, float]:
    """Compute annual, warm-season, and cool-season precipitation and Hargreaves ET0 from POWER normals."""
    if not isinstance(normals, dict):
        return {}
    warm_months = _WARM_MONTHS_NORTH if lat >= 0 else {"oct", "nov", "dec", "jan", "feb", "mar"}
    ann_p = ann_et0 = warm_p = warm_et0 = cool_p = cool_et0 = 0.0
    months_seen = 0
    for m_key, days, doy in _MONTH_INFO:
        m = normals.get(m_key)
        if not isinstance(m, dict):
            continue
        p_day = m.get("PRECTOTCORR")
        tmax = m.get("T2M_MAX")
        tmin = m.get("T2M_MIN")
        tmean = m.get("T2M")
        if p_day is None and tmean is None:
            continue
        months_seen += 1
        m_precip = max(0.0, float(p_day or 0.0) * days)
        if tmax is not None and tmin is not None:
            tm = float(tmean) if tmean is not None else (float(tmax) + float(tmin)) / 2.0
            tdiff = max(1.0, float(tmax) - float(tmin))
            ra_mm = _extraterrestrial_ra_mm_day(lat, doy)
            # Hargreaves-Samani (1985) FAO-56 Eq. 52 ET0 (mm/day)
            et_day = max(0.2, 0.0023 * (tm + 17.8) * math.sqrt(tdiff) * ra_mm)
        else:
            et_day = max(0.3, 0.12 * max(0.0, float(tmean or 12.0) + 5.0))
        m_et0 = et_day * days
        ann_p += m_precip
        ann_et0 += m_et0
        if m_key in warm_months:
            warm_p += m_precip
            warm_et0 += m_et0
        else:
            cool_p += m_precip
            cool_et0 += m_et0
    if months_seen < 6:
        return {}
    out = {
        "annual_precip_mm": round(ann_p, 1),
        "annual_et0_mm": round(ann_et0, 1),
        "warm_season_precip_mm": round(warm_p, 1),
        "warm_season_et0_mm": round(warm_et0, 1),
        "cool_season_precip_mm": round(cool_p, 1),
        "cool_season_et0_mm": round(cool_et0, 1),
    }
    ann = normals.get("ann")
    if isinstance(ann, dict) and isinstance(ann.get("T2M"), (int, float)):
        out["ann_t2m_c"] = round(float(ann["T2M"]), 2)
    return out


def _extract_market_and_regional(
    datasets: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Extract live fertilizer USD/kg, regional FAOSTAT yields (t/ha), and crop prices (USD/t)."""
    fert_usd_kg: dict[str, float] = {}
    crop_prices: dict[str, float] = {}
    crop_yields: dict[str, float] = {}

    mkt = _values(datasets.get("market_prices"))
    commodities = mkt.get("commodities") if isinstance(mkt.get("commodities"), dict) else {}
    if isinstance(commodities, dict):
        urea = _first(commodities, "urea.latest_price")
        if urea and urea > 0:
            fert_usd_kg["nitrogen_price_usd_kg"] = round((urea / 1000.0) / 0.46, 3)
        tsp = _first(commodities, "tsp.latest_price", "dap.latest_price")
        if tsp and tsp > 0:
            fert_usd_kg["phosphorus_price_usd_kg"] = round((tsp / 1000.0) / 0.46, 3)
        kcl = _first(commodities, "potassium_chloride.latest_price")
        if kcl and kcl > 0:
            fert_usd_kg["potassium_price_usd_kg"] = round((kcl / 1000.0) / 0.60, 3)
        for wb_key, cid in (
            ("maize", "corn"),
            ("wheat_us_hrw", "winter_wheat"),
            ("soybeans", "soybeans"),
            ("sorghum", "grain_sorghum"),
        ):
            p_wb = _first(commodities, f"{wb_key}.latest_price")
            if p_wb and p_wb > 10.0:
                crop_prices[cid] = round(p_wb, 1)

    # FAOSTAT national producer prices (USD/t) & average yields (t/ha)
    reg = _values(datasets.get("regional_production"))
    for entry in (reg.get("crops") if isinstance(reg.get("crops"), list) else []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("crop") or "").lower()
        latest = entry.get("latest") if isinstance(entry.get("latest"), dict) else {}
        cid = None
        if "maize" in name or "corn" in name:
            cid = "corn"
        elif "wheat" in name:
            cid = "winter_wheat"
        elif "soya" in name or "soybean" in name:
            cid = "soybeans"
        elif "sorghum" in name:
            cid = "grain_sorghum"
        elif "sunflower" in name:
            cid = "sunflowers"
        elif "rape" in name or "colza" in name:
            cid = "canola"
        elif "peas" in name:
            cid = "field_peas"
        elif "tomato" in name:
            cid = "processing_tomatoes"
        elif "pepper" in name or "chilli" in name:
            cid = "bell_peppers"
        elif "spinach" in name:
            cid = "spinach"
        if not cid:
            continue
        y_kg_ha = latest.get("yield_kg_per_ha")
        if isinstance(y_kg_ha, (int, float)) and y_kg_ha > 0:
            crop_yields[cid] = round(float(y_kg_ha) / 1000.0, 2)
        p_usd_t = latest.get("producer_price_usd_per_t")
        if isinstance(p_usd_t, (int, float)) and p_usd_t > 10.0:
            crop_prices[cid] = round(float(p_usd_t), 1)

    # EU Eurostat farm-gate prices (EUR/t -> USD/t) take local European precedence when present
    eu = _values(datasets.get("local_prices"))
    for entry in (eu.get("crop_selling_prices") if isinstance(eu.get("crop_selling_prices"), list) else []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("crop") or "").lower()
        eur_t = entry.get("latest_eur_per_t")
        if not isinstance(eur_t, (int, float)) or eur_t <= 10.0:
            continue
        cid = None
        if "maize" in name or "corn" in name:
            cid = "corn"
        elif "wheat" in name:
            cid = "winter_wheat"
        elif "soya" in name or "soybean" in name:
            cid = "soybeans"
        elif "sorghum" in name:
            cid = "grain_sorghum"
        elif "sunflower" in name:
            cid = "sunflowers"
        elif "rape" in name or "colza" in name:
            cid = "canola"
        elif "pea" in name:
            cid = "field_peas"
        elif "tomato" in name:
            cid = "processing_tomatoes"
        elif "pepper" in name:
            cid = "bell_peppers"
        elif "spinach" in name:
            cid = "spinach"
        if cid:
            crop_prices[cid] = round(float(eur_t) * _EUR_TO_USD, 1)

    return fert_usd_kg, crop_prices, crop_yields


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

    # Climate / water scalars: prefer 30-year NASA POWER normals + 365d extremes over 30-day extrapolation
    normals = w.get("normals_1991_2020")
    ext = w.get("extremes_last_365_days") if isinstance(w.get("extremes_last_365_days"), dict) else {}
    monthly_clim = _monthly_climate_breakdown(normals, lat)

    mean_temp = (
        monthly_clim.get("ann_t2m_c")
        or _first(w, "last_30_days.t_mean_c", "latest.T2M")
        or 14.0
    )
    rain_ann_norm = monthly_clim.get("annual_precip_mm")
    rain_ext = ext.get("total_precip_mm") if isinstance(ext.get("total_precip_mm"), (int, float)) else None
    if rain_ann_norm and rain_ext:
        annual_precip = round((rain_ann_norm + float(rain_ext)) / 2.0, 1)
    elif rain_ann_norm or rain_ext:
        annual_precip = round(float(rain_ann_norm or rain_ext), 1)
    else:
        rain_30d = _first(rain, "total_30d_mm") or _first(w, "last_30_days.precip_mm") or 60.0
        annual_precip = round(rain_30d * 12.2, 1)

    et_daily_field = _first(etf, "et_daily.mean")
    et_8d_area = _first(eta, "et_mm_8day")
    et_daily_power = _first(w, "last_30_days.evapotranspiration_mm")
    if monthly_clim.get("annual_et0_mm"):
        et0_annual = monthly_clim["annual_et0_mm"]
    elif et_daily_field is not None:
        et0_annual = round(et_daily_field * 365.0, 1)
    elif et_8d_area is not None:
        et0_annual = round((et_8d_area / 8.0) * 365.0, 1)
    else:
        et0_annual = round((et_daily_power or 3.2) * 365.0, 1)

    # Volumetric moisture (m3/m3): read rootzone_m3m3 directly; only scale fractional wetness (0-1) if absent
    rz_m3m3 = _first(smap, "rootzone_m3m3")
    if rz_m3m3 is None:
        rz_wet = _first(smap, "rootzone_wetness")
        rz_m3m3 = round(rz_wet * 0.44, 3) if rz_wet is not None else 0.26
    ndvi = _first(hls, "ndvi.mean")
    ndmi = _first(hls, "ndmi.mean")
    ndre = _first(hls, "ndre.mean")
    gdd = _first(w, "gdd_since_jan1.value") or 1650.0

    # SoilGrids properties
    clay = _first(topsoil, "clay")
    sand = _first(topsoil, "sand")
    silt = _first(topsoil, "silt")
    soc_g_kg = _first(topsoil, "soc")  # SoilGrids reports soil organic carbon in g/kg; analytics-api wants %
    soc = round(soc_g_kg / 10.0, 2) if soc_g_kg is not None else None
    soil_ph = _first(topsoil, "phh2o") or 6.7
    bdod = _first(topsoil, "bdod")
    total_n_g_kg = _first(topsoil, "nitrogen")
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

    # Economic prices: World Bank + Eurostat + FAOSTAT, overridden by user inputs
    fert_usd_kg, crop_prices_usd_t, regional_yields_t_ha = _extract_market_and_regional(datasets)
    fuel = prices.get("fuel") if isinstance(prices.get("fuel"), dict) else {}
    diesel_series = fuel.get("diesel") if isinstance(fuel.get("diesel"), dict) else {}
    diesel = _first(diesel_series, "latest_without_taxes.eur_per_litre")
    elec = _first(prices, "energy.electricity.MWH500-1999.excl_taxes")
    elec_series = prices.get("energy", {}).get("electricity", {}).get("MWH500-1999", {}).get("excl_taxes") if isinstance(prices.get("energy"), dict) else None
    if isinstance(elec_series, list) and elec_series:
        last = elec_series[-1]
        if isinstance(last, dict):
            elec = _num(last, "price")

    user_water = ov.get("water_price_eur_m3")
    user_elec = ov.get("electricity_price_eur_kwh")
    user_ph = ov.get("ph")

    nasa_power_block: dict[str, Any] = {
        "t2m_mean_c": round(mean_temp, 2),
        "fao56_et0_annual_mm": et0_annual,
        "solar_radiation_mj_m2": _first(w, "latest.ALLSKY_SFC_SW_DWN") or 18.0,
        "growing_degree_days_base10": round(gdd, 1),
    }
    if monthly_clim:
        for k in ("warm_season_et0_mm", "warm_season_precip_mm", "cool_season_et0_mm", "cool_season_precip_mm"):
            if k in monthly_clim:
                nasa_power_block[k] = monthly_clim[k]
    if isinstance(ext.get("frost_days"), (int, float)):
        nasa_power_block["frost_days_count"] = int(ext["frost_days"])
    if isinstance(ext.get("heat_days_over_35c"), (int, float)):
        nasa_power_block["heatwave_days_count"] = int(ext["heat_days_over_35c"])
    if isinstance(ext.get("longest_dry_spell_days"), (int, float)):
        nasa_power_block["longest_dry_spell_days"] = int(ext["longest_dry_spell_days"])
    cold_night = _num(ext, "coldest_night.t_min_c")
    if cold_night is not None:
        nasa_power_block["coldest_night_c"] = round(cold_night, 1)
    hot_day = _num(ext, "hottest_day.t_max_c")
    if hot_day is not None:
        nasa_power_block["hottest_day_c"] = round(hot_day, 1)

    econ_block: dict[str, Any] = {
        "diesel_fuel_price_usd_liter": round((diesel * _EUR_TO_USD) if diesel else 1.15, 3),
        "irrigation_water_price_usd_m3": float(user_water) if user_water is not None else 0.08,
        "electricity_pumping_tariff_usd_kwh": float(user_elec) if user_elec is not None else (round(elec * _EUR_TO_USD, 3) if elec else 0.14),
        "labor_hourly_wage_usd": 22.0,
    }
    econ_block.update(fert_usd_kg)
    if crop_prices_usd_t:
        econ_block["crop_market_prices_usd_t"] = crop_prices_usd_t
    if regional_yields_t_ha:
        econ_block["regional_crop_yields_t_ha"] = regional_yields_t_ha

    soilgrids_block: dict[str, Any] = {
        "texture_class": texture,
        "soil_organic_carbon_pct": soc,
        "soil_ph_h2o": soil_ph,
        "clay_percentage": clay,
        "sand_percentage": sand,
        "silt_percentage": silt,
    }
    if bdod is not None:
        soilgrids_block["bulk_density_g_cm3"] = bdod
    if total_n_g_kg is not None:
        soilgrids_block["total_nitrogen_g_kg"] = total_n_g_kg

    payload: dict[str, Any] = {
        "parcel_info": {
            "parcel_id": str(plot.get("cadastral_ref") or plot.get("label") or plot.get("id") or "plot"),
            "field_name": plot.get("label"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "boundary_geojson": plot.get("geometry"),
            "area_hectares": round(area_ha, 2),
            "soil_type": texture,
        },
        "harvest_history": {"historical_seasons": historical_seasons},
        "economic_prices": econ_block,
        "nasa_data": {
            "nasa_power": nasa_power_block,
            "gpm_imerg": {"annual_rainfall_mm": annual_precip},
            "smap_moisture": {"rootzone_moisture_m3_m3": round(rz_m3m3, 3)},
            "hls_vegetation": {
                "ndvi_peak": ndvi if ndvi is not None else 0.6,
                "ndwi_peak": ndmi,
                "ndre_peak": ndre,
            },
            "soilgrids": soilgrids_block,
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
    if ov.get("annual_water_quota_m3") is not None:
        lud["local_water_quota_m3"] = float(ov["annual_water_quota_m3"])
    if isinstance(ov.get("irrigation_system"), str) and ov["irrigation_system"]:
        lud["irrigation_system"] = ov["irrigation_system"]
    if isinstance(ov.get("tillage_practice"), str) and ov["tillage_practice"]:
        lud["tillage_practice"] = ov["tillage_practice"]

    # Farmer crop choices: "only grow" (needs >= 3 crops to apply) and "never grow"
    whitelist, blacklist = crop_preferences(ov)
    if whitelist:
        lud["preferred_candidate_crops"] = whitelist
    if blacklist:
        lud["excluded_crops"] = blacklist

    # Paired ESP32 IoT sensor readings (soil moisture + air temp/humidity) as dated ground truth
    if isinstance(sensor_readings, list) and sensor_readings:
        dated_readings: list[dict[str, Any]] = []
        for idx, r in enumerate(sensor_readings):
            if not isinstance(r, dict):
                continue
            ts = str(r.get("ts") or r.get("recorded_at") or r.get("timestamp") or f"reading-{idx}")
            item: dict[str, Any] = {
                "timestamp": ts,
                "sensor_id": str(r.get("device_id") or r.get("serial_number") or "esp32-probe"),
            }
            if isinstance(r.get("soil_moisture"), (int, float)):
                item["soil_moisture_vol_pct"] = max(0.0, min(100.0, float(r["soil_moisture"])))
            if isinstance(r.get("temperature_c"), (int, float)):
                item["ambient_temperature_c"] = float(r["temperature_c"])
            if isinstance(r.get("humidity"), (int, float)):
                item["ambient_humidity_pct"] = max(0.0, min(100.0, float(r["humidity"])))
            if len(item) > 2:
                dated_readings.append(item)
        if dated_readings:
            dated_readings.sort(key=lambda x: x["timestamp"])
            lud["dated_sensor_readings"] = dated_readings
            latest_item = dated_readings[-1]
            if "soil_moisture_vol_pct" in latest_item:
                lud["in_situ_soil_moisture_vol_pct"] = latest_item["soil_moisture_vol_pct"]

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


_CRITICAL_WORLDCOVER = {
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    100: "Moss and lichen",
}
_CAUTION_WORLDCOVER = {
    10: "Tree cover",
    20: "Shrubland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    95: "Mangroves",
}


def assess_plot_feasibility(
    plot: dict[str, Any],
    datasets: dict[str, Any],
    soil_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect non-cultivable or physically extreme plots (water, urban, alpine, cliff)."""
    ov = soil_override or {}
    has_greenhouse = bool(ov.get("greenhouse_available") or plot.get("greenhouse_available"))
    has_soil_override = any(ov.get(k) is not None for k in ("soil_type", "ph", "soc_pct", "clay_pct"))

    wc_raw = plot.get("worldcover_class")
    wc_class = int(wc_raw) if wc_raw is not None else None
    wc_label = plot.get("worldcover_label") or (
        _CRITICAL_WORLDCOVER.get(wc_class) or _CAUTION_WORLDCOVER.get(wc_class) if wc_class is not None else None
    )

    soil_vals = _values(datasets.get("soil"))
    has_soilgrids = any(
        _first(soil_vals, k) is not None
        for k in ("clay_pct", "sand_pct", "silt_pct", "ph_h2o", "ph", "soc_g_kg")
    )

    terr = _values(datasets.get("terrain"))
    elev_m = _first(terr, "elevation_m.mean")
    slope_deg = _first(terr, "slope_deg.mean", "field_gradient_deg")
    slope_pct = round(slope_deg * 1.75, 1) if slope_deg is not None else None

    pwr = _values(datasets.get("power"))
    pwr_ts = _values(datasets.get("power_timeseries"))
    t_mean = _first(pwr, "temp_c.mean") or _first(pwr_ts, "temp_c.mean")
    frost_days = _first(pwr_ts, "frost_days_count", "frost_days")

    critical: list[str] = []
    warnings: list[str] = []

    if wc_class in _CRITICAL_WORLDCOVER:
        critical.append(
            f"ESA WorldCover 10m land cover classifies this polygon as '{wc_label}' (Class {wc_class}), which is non-arable."
        )
    elif wc_class in (50, 60) and not has_soilgrids and not has_soil_override and not has_greenhouse:
        critical.append(
            f"ESA WorldCover classifies this site as '{wc_label}' (Class {wc_class}) and SoilGrids returned no topsoil data."
        )
    elif wc_class in _CAUTION_WORLDCOVER and not has_greenhouse:
        warnings.append(
            f"ESA WorldCover 10m land cover indicates '{wc_label}' (Class {wc_class}) rather than open cropland."
        )

    if not has_soilgrids and not has_soil_override and datasets.get("soil") is not None:
        msg = "ISRIC SoilGrids returned no soil horizon data at these coordinates (common over water bodies, bare rock, or paved areas)."
        if wc_class in _CRITICAL_WORLDCOVER or wc_class in (50, 60):
            if msg not in critical:
                critical.append(msg)
        else:
            warnings.append(msg)

    if slope_pct is not None:
        if slope_pct > 30.0:
            critical.append(
                f"Extreme terrain slope ({slope_pct:.1f}%) exceeds safe mechanized cultivation thresholds."
            )
        elif slope_pct > 15.0:
            warnings.append(
                f"Steep terrain slope ({slope_pct:.1f}%) introduces severe erosion risk and limits machinery access."
            )

    if elev_m is not None and elev_m > 2400.0:
        critical.append(
            f"High-alpine elevation ({elev_m:.0f} m) sits outside standard open-field arable crop zones."
        )

    if not has_greenhouse and (
        (t_mean is not None and t_mean < 2.0) or (frost_days is not None and frost_days > 220)
    ):
        parts = []
        if t_mean is not None:
            parts.append(f"mean {t_mean:.1f}°C")
        if frost_days is not None:
            parts.append(f"{int(frost_days)} frost days/yr")
        critical.append(
            f"Extreme cold regime ({', '.join(parts)}) makes open-field arable cropping unviable without a greenhouse."
        )

    reasons = critical + warnings
    return {
        "likely_invalid": bool(reasons),
        "severity": "critical" if critical else ("warning" if warnings else "ok"),
        "reasons": reasons,
        "worldcover_class": wc_class,
        "worldcover_label": wc_label,
    }
