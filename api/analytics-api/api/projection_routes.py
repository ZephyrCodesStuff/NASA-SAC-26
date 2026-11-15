"""
REST API Routes for 3-Year Crop Planning & Ground Impact Simulation.
Provides endpoints to:
1. Generate 5 distinct 3-year planting plans with year-by-year ground impacts and Gemini AI advisory.
2. Query the scientific 12-crop agronomic catalog.
3. Query soil physical and hydraulic reference profiles.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status, Body

from projection_api.models.input_parser_schemas import FullFieldIngestionPayload
from projection_api.services.input_parser import FieldIngestionParser
from projection_api.models.crops_catalog import MASTER_CROPS_CATALOG
from projection_api.services.soil_physics import SOIL_PHYSICAL_PROPERTIES
from projection_api.models.simulation_models import (
    ThreeYearPlanResponse, ThreeYearCultivationPlan, GeminiAdvisoryReport
)
from projection_api.services.plan_optimizer import PlanOptimizerEngine
from projection_api.services.gemini_advisor import GeminiAdvisorEngine

logger = logging.getLogger(__name__)

projection_router = APIRouter(prefix="/api/projections", tags=["3-Year Agricultural Projections & Gemini Advisory"])


@projection_router.post(
    "/plan-3year",
    response_model=ThreeYearPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate 5 Distinct 3-Year Planting Plans with Soil Dynamics and Gemini Advisory",
    description="""
Ingests multi-domain field data (NASA POWER daily timeseries, GPM IMERG rainfall, SMAP moisture,
OpenET, SoilGrids, In-Situ Sensors, Elevation Maps, and Input Prices).
Simulates year-by-year physical ground impact (NPK balances, Henin-Dupuis SOC %, ASAE compaction PSI,
FAO-56 ETc water deficits, RUSLE erosion).
Outputs 5 distinct strategies for the farmer to choose from:
1. **Most Income**
2. **Best Soil Health**
3. **Least Effort / Labour**
4. **Highest ROI (%)**
5. **Least Amount of Crop Loss Risk**
Includes grounded Google Gemini 3.8 Flash AI advisory with deterministic offline fallback.
"""
)
async def generate_three_year_plan(payload: FullFieldIngestionPayload = Body(...)) -> ThreeYearPlanResponse:
    try:
        # 1. Normalize multi-source raw ingestion data
        normalized = FieldIngestionParser.parse_and_validate(payload)
        
        # 2. Extract key parameters from normalized profile (User ground-truth layers on top of NASA)
        area_ha = normalized.area_hectares or 1.0
        annual_precip = normalized.effective_rainfall_annual_mm or normalized.gpm_imerg_annual_rainfall_mm or 650.0
        annual_et0 = normalized.effective_et0_annual_mm or normalized.nasa_power_et0_annual_mm or 1100.0
        mean_temp = normalized.effective_temp_mean_c or normalized.nasa_power_temp_mean_c or 14.0

        # In-situ ground moisture probe layers on top of NASA SMAP satellite
        if normalized.calibrated_soil_moisture_vol_pct is not None:
            smap_moisture = normalized.calibrated_soil_moisture_vol_pct / 100.0
        else:
            smap_moisture = (normalized.smap_rootzone_moisture_vol_pct or 26.0) / 100.0

        base_soc = normalized.calibrated_soc_pct or normalized.soilgrids_organic_carbon_pct or 1.85
        base_compaction = normalized.calibrated_compaction_psi or 215.0
        base_nitrate = normalized.calibrated_topsoil_n_kg_ha or 24.0

        preceding_crop = normalized.past_crops_sequence[-1] if normalized.past_crops_sequence else "Corn (Maize)"
        elevation_val = normalized.elevation_mean_m or 150.0
        slope_val = normalized.slope_mean_pct or 2.0
        low_spot_hazard = bool(normalized.waterlogging_depression_risk)

        parcel = payload.parcel_info

        optimizer_input: Dict[str, Any] = {
            "area_hectares": area_ha,
            "resolved_soil_type": normalized.soil_type,
            "elevation_m": elevation_val,
            "slope_pct": slope_val,
            "has_greenhouse": bool(parcel.greenhouse_available),
            "legal_water_quota_m3": (payload.local_user_data.local_water_quota_m3 if payload.local_user_data and payload.local_user_data.local_water_quota_m3 is not None else parcel.annual_water_quota_m3),
            "baseline_soc_pct": base_soc,
            "baseline_compaction_psi": base_compaction,
            "baseline_nitrate_ppm": base_nitrate,
            "annual_et0_mm": annual_et0,
            "annual_precip_mm": annual_precip,
            "mean_temp_c": mean_temp,
            "smap_rootzone_moisture": smap_moisture,
            "low_spot_waterlogging_hazard": low_spot_hazard,
            "preceding_crop_name": preceding_crop,
            "water_price_usd_m3": normalized.water_price_usd_m3 or 0.08,
            "diesel_price_usd_liter": normalized.diesel_price_usd_liter or 1.15,
            "fertilizer_n_price_usd_kg": normalized.nitrogen_fertilizer_usd_kg or 1.35,
            "fertilizer_p_price_usd_kg": normalized.phosphorus_fertilizer_usd_kg or 1.60,
            "fertilizer_k_price_usd_kg": normalized.potassium_fertilizer_usd_kg or 0.95,
            "labor_hourly_wage_usd": normalized.labor_hourly_wage_usd or 22.0,
            "preferred_candidate_crops": normalized.whitelisted_crops,
            "excluded_crops": normalized.blacklisted_crops,
        }

        # 3. Execute 3-Year Multi-Objective Optimizer Engine
        optimizer = PlanOptimizerEngine(optimizer_input)
        strategies_dict = optimizer.optimize_all_strategies()

        # 4. Generate Grounded Gemini AI Advisory (or deterministic fallback)
        parcel_context = {
            "cadastral_id": parcel.parcel_id,
            "area_hectares": area_ha,
            "soil_type": normalized.soil_type,
            "elevation_m": elevation_val,
            "slope_pct": slope_val,
            "data_layering_provenance": normalized.data_layering_provenance,
        }
        climate_context = {
            "annual_et0_mm": annual_et0,
            "annual_precip_mm": annual_precip,
            "mean_temp_c": mean_temp,
            "smap_rootzone_moisture": smap_moisture,
            "low_spot_hazard": low_spot_hazard,
        }

        advisor = GeminiAdvisorEngine()
        # Blocking SDK call: run it off the event loop so other requests aren't stalled
        gemini_report = await asyncio.to_thread(
            advisor.generate_advisory_report,
            parcel_info=parcel_context,
            climate_baseline=climate_context,
            strategies=strategies_dict
        )

        return ThreeYearPlanResponse(
            cadastral_parcel_id=parcel.parcel_id,
            field_area_ha=area_ha,
            resolved_soil_type=normalized.soil_type,
            simulation_timestamp=datetime.now(timezone.utc).isoformat(),
            climate_baseline=climate_context,
            data_layering_provenance=normalized.data_layering_provenance,
            strategies=strategies_dict,
            gemini_advisory=gemini_report
        )

    except Exception as e:
        logger.exception("Error generating 3-year planting plan")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"3-Year Plan Optimization Failed: {str(e)}"
        )


@projection_router.get(
    "/crops-catalog",
    summary="Get Agronomic Parameters for All 12 Master Crops",
    description="Returns physiological, nutritional (NPK), hydrological (FAO-56), and economic parameters for all 12 crops."
)
async def get_crops_catalog():
    return {
        "crops_count": len(MASTER_CROPS_CATALOG),
        "crops": list(MASTER_CROPS_CATALOG.values())
    }


@projection_router.get(
    "/soil-profiles",
    summary="Get Soil Physics & Hydraulic Reference Profiles",
    description="Returns physical parameters (bulk density, field capacity, wilting point, saturation, Ksat, clay %) across USDA texture classes."
)
async def get_soil_profiles():
    return {
        "profiles_count": len(SOIL_PHYSICAL_PROPERTIES),
        "profiles": SOIL_PHYSICAL_PROPERTIES
    }
