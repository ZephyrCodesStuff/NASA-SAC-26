"""Deterministic agronomic equations (FAO-56, RUSLE, IPCC N-budget, Rotation Matrix).

Pure Python math only: no network calls, no LLM calls, no UI imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class CropProfile:
    """Agronomic parameters for a crop in 3-year rotation modeling."""

    name: str
    family: str
    root_type: str  # "deep_taproot" | "shallow_fibrous" | "medium"
    kc_mid: float  # FAO-56 mid-season crop coefficient
    season_days: int
    n_fix_kg_ha: float
    n_uptake_kg_ha: float
    residue_n_kg_ha: float
    cover_c_factor: float  # RUSLE C factor (lower = better erosion protection)
    flood_sensitive: bool


CROPS: dict[str, CropProfile] = {
    "Maize": CropProfile("Maize", "Poaceae", "medium", 1.15, 130, 0.0, 185.0, 35.0, 0.38, False),
    "Winter Wheat": CropProfile("Winter Wheat", "Poaceae", "shallow_fibrous", 1.05, 180, 0.0, 140.0, 30.0, 0.18, False),
    "Soybean": CropProfile("Soybean", "Fabaceae", "deep_taproot", 1.05, 115, 145.0, 160.0, 45.0, 0.28, True),
    "Alfalfa": CropProfile("Alfalfa", "Fabaceae", "deep_taproot", 0.95, 210, 210.0, 190.0, 65.0, 0.08, True),
    "Barley": CropProfile("Barley", "Poaceae", "shallow_fibrous", 1.00, 160, 0.0, 115.0, 25.0, 0.20, False),
    "Sunflower": CropProfile("Sunflower", "Asteraceae", "deep_taproot", 1.05, 120, 0.0, 125.0, 25.0, 0.34, False),
    "Cover Clover": CropProfile("Cover Clover", "Fabaceae", "deep_taproot", 0.85, 150, 130.0, 95.0, 55.0, 0.07, True),
}

CANDIDATE_ROTATIONS: list[tuple[str, list[str]]] = [
    ("Legume-Cereal Balanced", ["Soybean", "Winter Wheat", "Maize"]),
    ("Erosion-Shield Perennial", ["Alfalfa", "Winter Wheat", "Sunflower"]),
    ("Low-Water Cover Break", ["Winter Wheat", "Cover Clover", "Barley"]),
    ("Intensive Cereal Baseline", ["Maize", "Maize", "Winter Wheat"]),
]


def _val(ds: dict[str, Any] | None, *keys: str, default: float) -> float:
    if not ds or ds.get("status") != "ok":
        return default
    values = ds.get("values") or {}
    for k in keys:
        v = values.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict) and isinstance(v.get("mean"), (int, float)):
            return float(v["mean"])
    return default


def extract_agronomic_inputs(
    datasets: dict[str, dict[str, Any]],
    area_ha: float = 1.0,
    soil_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize `data-api` datasets + optional `soil_override` into deterministic inputs."""
    weather = datasets.get("weather") or {}
    rainfall = datasets.get("rainfall") or {}
    smap = datasets.get("soil_moisture") or {}
    et_field = datasets.get("evapotranspiration_field") or {}
    et_area = datasets.get("evapotranspiration_area") or {}
    hls = datasets.get("crop_health") or {}
    soil = datasets.get("soil") or {}
    terrain = datasets.get("terrain") or {}

    # ET0 / daily ET fallback chain: ECOSTRESS (field) -> MODIS (area) -> POWER (weather)
    if et_field.get("status") == "ok":
        et0_mm_day = _val(et_field, "et_mm_day", "et", default=3.2)
        et_source = "ECOSTRESS (70m)"
    elif et_area.get("status") == "ok":
        et0_mm_day = _val(et_area, "et_mm_day", "pet_mm_day", default=3.2)
        et_source = "MODIS MOD16A2 (500m)"
    else:
        et0_mm_day = _val(weather, "et0_mm_day", "et_mm_day", "evapotranspiration", default=3.2)
        et_source = "NASA POWER (55km)"

    rain_30d_mm = _val(rainfall, "total_30d_mm", "rain_30d_mm", default=_val(weather, "rain_30d_mm", default=62.0))
    dry_days = _val(rainfall, "consecutive_dry_days", default=5.0)
    rz_moisture = _val(smap, "root_zone_wetness", "rootzone_moisture", default=0.42)
    ndvi = _val(hls, "ndvi", default=0.45)
    slope_deg = _val(terrain, "slope_deg", "slope_mean_deg", default=1.5)
    steep_share = _val(terrain, "share_gt_8deg", "steep_fraction", default=0.0)
    low_spot = bool((terrain.get("values") or {}).get("low_spot_flag", False)) if terrain.get("status") == "ok" else False

    soil_vals = dict(soil.get("values") or {}) if soil.get("status") == "ok" else {}
    if soil_override:
        for k, v in soil_override.items():
            if v is not None and v != "":
                soil_vals[k] = v

    clay_pct = float(soil_vals.get("clay_pct") or soil_vals.get("clay") or 24.0)
    sand_pct = float(soil_vals.get("sand_pct") or soil_vals.get("sand") or 36.0)
    oc_g_kg = float(soil_vals.get("organic_carbon_g_kg") or soil_vals.get("soc") or 14.0)
    ph = float(soil_vals.get("ph") or 6.8)
    soil_n = float(soil_vals.get("nitrogen_g_kg") or 1.3)

    return {
        "area_ha": max(float(area_ha or 1.0), 0.05),
        "et0_mm_day": et0_mm_day,
        "et_source": et_source,
        "rain_30d_mm": rain_30d_mm,
        "consecutive_dry_days": dry_days,
        "root_zone_moisture": rz_moisture,
        "ndvi": ndvi,
        "slope_deg": slope_deg,
        "steep_share": steep_share,
        "low_spot_flag": low_spot,
        "clay_pct": clay_pct,
        "sand_pct": sand_pct,
        "organic_carbon_g_kg": oc_g_kg,
        "ph": ph,
        "soil_n_g_kg": soil_n,
    }


def score_rotation(
    name: str,
    crops_seq: Sequence[str],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Compute FAO-56 water balance, RUSLE erosion, N-budget, and rotation score."""
    profiles = [CROPS.get(c, CROPS["Maize"]) for c in crops_seq]
    area_ha = inputs["area_ha"]

    # 1. FAO-56 Water Balance (seasonal average across 3 years)
    # Approximate seasonal effective rainfall from 30d rate scaled to season + soil buffer
    mean_kc = sum(p.kc_mid for p in profiles) / len(profiles)
    mean_days = sum(p.season_days for p in profiles) / len(profiles)
    etc_mm = mean_kc * inputs["et0_mm_day"] * mean_days
    p_eff_mm = (inputs["rain_30d_mm"] * (mean_days / 30.0) * 0.80) + (inputs["root_zone_moisture"] * 120.0)
    water_balance_mm = round(p_eff_mm - etc_mm, 1)
    water_deficit_m3 = round(max(0.0, -water_balance_mm) * 10.0 * area_ha, 0)

    # 2. RUSLE Topsoil Erosion: A = R * K * LS * C * P (t/ha/yr)
    r_factor = max(120.0, inputs["rain_30d_mm"] * 10.5)
    k_factor = max(0.015, min(0.055, 0.038 - (inputs["organic_carbon_g_kg"] * 0.0005) + (0.0002 * (100.0 - inputs["clay_pct"] - inputs["sand_pct"]))))
    ls_factor = max(0.15, (inputs["slope_deg"] / 5.0) ** 1.2 + inputs["steep_share"] * 1.5)
    ndvi_adj = 1.15 if inputs["ndvi"] < 0.25 else 0.95
    c_factor = (sum(p.cover_c_factor for p in profiles) / len(profiles)) * ndvi_adj
    p_factor = 1.0
    erosion_t_ha_yr = round(r_factor * k_factor * ls_factor * c_factor * p_factor, 2)

    # 3. FAO/IPCC Nitrogen Budget (kg N/ha/yr)
    n_fix = sum(p.n_fix_kg_ha for p in profiles) / len(profiles)
    n_res = sum(p.residue_n_kg_ha for p in profiles) / len(profiles)
    n_uptake = sum(p.n_uptake_kg_ha for p in profiles) / len(profiles)
    n_leach = max(10.0, (inputs["rain_30d_mm"] * 0.25) * (inputs["sand_pct"] / 40.0))
    n_budget_kg_ha = round(n_fix + n_res - n_uptake - n_leach, 1)

    # 4. Agronomic Rotation Matrix penalties & bonuses
    penalty = 0.0
    notes: list[str] = []
    for i in range(len(profiles) - 1):
        if profiles[i].family == profiles[i + 1].family:
            penalty += 18.0
            notes.append(f"Back-to-back {profiles[i].family} ({profiles[i].name} → {profiles[i+1].name})")

    root_types = {p.root_type for p in profiles}
    if "deep_taproot" in root_types and "shallow_fibrous" in root_types:
        bonus = 10.0
        notes.append("Alternates deep taproot & shallow fibrous roots")
    else:
        bonus = 0.0

    if inputs["low_spot_flag"] and any(p.flood_sensitive for p in profiles):
        penalty += 12.0
        notes.append("Waterlogging risk on flood-sensitive legume")

    # Composite 0-100 resilience score
    water_pen = min(35.0, max(0.0, -water_balance_mm) * 0.12)
    erosion_pen = min(30.0, erosion_t_ha_yr * 2.5)
    n_pen = min(20.0, max(0.0, -n_budget_kg_ha - 40.0) * 0.25)
    score = round(max(5.0, min(98.0, 92.0 + bonus - penalty - water_pen - erosion_pen - n_pen)), 1)

    return {
        "name": name,
        "rotation": list(crops_seq),
        "score": score,
        "water_balance_mm": water_balance_mm,
        "water_deficit_m3": water_deficit_m3,
        "erosion_t_ha_yr": erosion_t_ha_yr,
        "n_budget_kg_ha": n_budget_kg_ha,
        "notes": notes,
    }


def evaluate_plot_strategies(
    datasets: dict[str, dict[str, Any]],
    area_ha: float = 1.0,
    baseline_rotation: Sequence[str] | None = None,
    soil_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all deterministic agronomic models and rank rotation strategies."""
    inputs = extract_agronomic_inputs(datasets, area_ha=area_ha, soil_override=soil_override)
    base_seq = list(baseline_rotation) if baseline_rotation and len(baseline_rotation) >= 2 else ["Maize", "Maize", "Winter Wheat"]
    baseline = score_rotation("Current / Baseline", base_seq, inputs)

    ranked = sorted(
        (score_rotation(name, seq, inputs) for name, seq in CANDIDATE_ROTATIONS),
        key=lambda s: s["score"],
        reverse=True,
    )
    return {
        "inputs": inputs,
        "baseline": baseline,
        "strategies": ranked[:3],
    }
