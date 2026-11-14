"""
Ingestion & Normalization Parser Service for Field Cultivation Planning.
Parses, validates, harmonizes units, and audits raw agricultural datasets:
1. Parcel Info (cadastral, geometry, coordinates, acreage, soil type)
2. Last couple years (max 5 flexible) harvest and crop information
3. Seed / Water / Oil Prices:
   - Economic input prices (diesel, water, electricity, fertilizer NPK, labor)
   - Seed characteristics:
     * Greenhouse need ('Open Field Only', 'Open Field or Greenhouse Compatible', 'Greenhouse Recommended', 'Greenhouse Required')
     * Resistance to extreme events (drought, flood/waterlogging, winds/lodging, frost, heat, salinity)
4. NASA data (Official raw database responses & full dated daily/scene timeseries):
   - NASA POWER daily weather timeseries with dates
   - GPM IMERG daily precipitation with storm dates
   - SMAP daily surface & root-zone volumetric moisture
   - OpenET daily actual evapotranspiration timeseries
   - ECOSTRESS dated thermal infrared stress scenes
   - HLS dated multispectral vegetation overpasses
   - SoilGrids depth-stratified horizon layers
   - GRACE monthly deep groundwater anomalies
5. Long Term Weather Projections (optional)
6. Local User Data:
   - In-situ portable sensor measurements with explicit date/time signatures
   - Soil type override, irrigation infrastructure, tillage system, management constraints
7. Elevation Maps (DEM, slope, aspect, wetness index, erosion)
"""

import math
import logging
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from projection_api.models.input_parser_schemas import (
    FullFieldIngestionPayload,
    ParcelInfoInput,
    HarvestAndCropHistoryInput,
    EconomicPricesInput,
    SeedDataInput,
    GreenhouseRequirement,
    ExtremeEventResistance,
    ExtremeResistanceLevel,
    NasaDataPayload,
    DatedDailyWeatherRecord,
    DatedPrecipitationObservation,
    DatedSoilMoistureRecord,
    OpenEtTimeseriesRecord,
    EcostressSceneRecord,
    HlsOverpassRecord,
    SoilGridsDepthLayer,
    GraceMonthlyRecord,
    DatedInSituSensorReading,
    LongTermWeatherProjectionsInput,
    LocalUserDataInput,
    ElevationMapsInput
)

logger = logging.getLogger(__name__)


# ==============================================================================
# SCIENTIFIC DEFAULT SEED PROFILES
# Standard agronomic reference traits for greenhouse need and extreme events.
# ==============================================================================

DEFAULT_SEED_PROFILES: Dict[str, SeedDataInput] = {
    "Corn (Maize)": SeedDataInput(
        crop_name="Corn (Maize)",
        variety_or_hybrid_name="Standard Commercial Hybrid",
        seed_cost_usd_per_ha=280.0,
        seeding_rate_kg_ha=25.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.MODERATE,
            drought_tolerance_score=3.0,
            flood_waterlogging_resistance=ExtremeResistanceLevel.MODERATE,
            flood_tolerance_score=2.8,
            wind_lodging_resistance=ExtremeResistanceLevel.MODERATE,
            wind_tolerance_score=3.2,
            frost_cold_resistance=ExtremeResistanceLevel.LOW,
            frost_tolerance_score=1.8,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.5,
            salinity_tolerance="Moderate",
            extreme_event_notes="Sensitive to severe drought during silking/tasseling; prone to root lodging in late season winds."
        )
    ),
    "Soybeans": SeedDataInput(
        crop_name="Soybeans",
        variety_or_hybrid_name="Maturity Group III Standard",
        seed_cost_usd_per_ha=160.0,
        seeding_rate_kg_ha=70.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.MODERATE,
            drought_tolerance_score=3.2,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.2,
            wind_lodging_resistance=ExtremeResistanceLevel.HIGH,
            wind_tolerance_score=4.0,
            frost_cold_resistance=ExtremeResistanceLevel.LOW,
            frost_tolerance_score=2.0,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.4,
            salinity_tolerance="Low to Moderate",
            extreme_event_notes="Highly susceptible to root rot (phytophthora) in saturated standing water."
        )
    ),
    "Winter Wheat": SeedDataInput(
        crop_name="Winter Wheat",
        variety_or_hybrid_name="Hard Red Winter",
        seed_cost_usd_per_ha=110.0,
        seeding_rate_kg_ha=120.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.HIGH,
            drought_tolerance_score=4.0,
            flood_waterlogging_resistance=ExtremeResistanceLevel.MODERATE,
            flood_tolerance_score=2.8,
            wind_lodging_resistance=ExtremeResistanceLevel.HIGH,
            wind_tolerance_score=4.2,
            frost_cold_resistance=ExtremeResistanceLevel.VERY_HIGH,
            frost_tolerance_score=4.8,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.0,
            salinity_tolerance="Moderate to High",
            extreme_event_notes="Exceptional cold hardiness under snowpack; deep fibrous root system limits drought stress."
        )
    ),
    "Grain Sorghum": SeedDataInput(
        crop_name="Grain Sorghum",
        variety_or_hybrid_name="Drought-Resilient Hybrid",
        seed_cost_usd_per_ha=85.0,
        seeding_rate_kg_ha=9.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.VERY_HIGH,
            drought_tolerance_score=4.8,
            flood_waterlogging_resistance=ExtremeResistanceLevel.MODERATE,
            flood_tolerance_score=3.0,
            wind_lodging_resistance=ExtremeResistanceLevel.HIGH,
            wind_tolerance_score=4.2,
            frost_cold_resistance=ExtremeResistanceLevel.MODERATE,
            frost_tolerance_score=2.8,
            extreme_heat_resistance=ExtremeResistanceLevel.VERY_HIGH,
            heat_tolerance_score=4.7,
            salinity_tolerance="High",
            extreme_event_notes="High waxy cuticular leaf wax prevents transpiration; enters dormancy during acute water stress."
        )
    ),
    "Sunflowers": SeedDataInput(
        crop_name="Sunflowers",
        variety_or_hybrid_name="High-Oleic Hybrid",
        seed_cost_usd_per_ha=135.0,
        seeding_rate_kg_ha=5.5,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.HIGH,
            drought_tolerance_score=4.2,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.0,
            wind_lodging_resistance=ExtremeResistanceLevel.MODERATE,
            wind_tolerance_score=3.0,
            frost_cold_resistance=ExtremeResistanceLevel.MODERATE,
            frost_tolerance_score=2.8,
            extreme_heat_resistance=ExtremeResistanceLevel.HIGH,
            heat_tolerance_score=4.2,
            salinity_tolerance="Moderate",
            extreme_event_notes="Taproot penetrates down to 2m+ extracting deep subsoil moisture; top-heavy heads prone to wind lodging."
        )
    ),
    "Field Peas / Chickpeas": SeedDataInput(
        crop_name="Field Peas / Chickpeas",
        variety_or_hybrid_name="Semi-leafless Pulse",
        seed_cost_usd_per_ha=120.0,
        seeding_rate_kg_ha=160.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.VERY_HIGH,
            drought_tolerance_score=4.5,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.0,
            wind_lodging_resistance=ExtremeResistanceLevel.MODERATE,
            wind_tolerance_score=3.2,
            frost_cold_resistance=ExtremeResistanceLevel.HIGH,
            frost_tolerance_score=4.0,
            extreme_heat_resistance=ExtremeResistanceLevel.LOW,
            heat_tolerance_score=2.2,
            salinity_tolerance="Low",
            extreme_event_notes="Excellent cold/dryland vigor; extremely intolerant of wet saturated soils (aschochyta blight)."
        )
    ),
    "Canola / Rapeseed": SeedDataInput(
        crop_name="Canola / Rapeseed",
        variety_or_hybrid_name="Spring / Winter Hybrid",
        seed_cost_usd_per_ha=145.0,
        seeding_rate_kg_ha=5.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.MODERATE,
            drought_tolerance_score=3.2,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.4,
            wind_lodging_resistance=ExtremeResistanceLevel.MODERATE,
            wind_tolerance_score=3.0,
            frost_cold_resistance=ExtremeResistanceLevel.HIGH,
            frost_tolerance_score=4.2,
            extreme_heat_resistance=ExtremeResistanceLevel.LOW,
            heat_tolerance_score=2.5,
            salinity_tolerance="Moderate",
            extreme_event_notes="Vulnerable to pod shatter in high winds; flower abortion occurs when temperatures exceed 30°C."
        )
    ),
    "Alfalfa / Clover (Perennial Legume)": SeedDataInput(
        crop_name="Alfalfa / Clover (Perennial Legume)",
        variety_or_hybrid_name="Certified Taproot Alfalfa",
        seed_cost_usd_per_ha=175.0,
        seeding_rate_kg_ha=18.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.HIGH,
            drought_tolerance_score=4.4,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.0,
            wind_lodging_resistance=ExtremeResistanceLevel.VERY_HIGH,
            wind_tolerance_score=4.8,
            frost_cold_resistance=ExtremeResistanceLevel.VERY_HIGH,
            frost_tolerance_score=4.6,
            extreme_heat_resistance=ExtremeResistanceLevel.HIGH,
            heat_tolerance_score=4.0,
            salinity_tolerance="Moderate to High",
            extreme_event_notes="Very deep root structure (2.5m) guarantees drought persistence; low canopy prevents wind damage."
        )
    ),
    "Barley (Low-Input Cereal)": SeedDataInput(
        crop_name="Barley (Low-Input Cereal)",
        variety_or_hybrid_name="Two-Row Malting / Feed",
        seed_cost_usd_per_ha=95.0,
        seeding_rate_kg_ha=110.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.VERY_HIGH,
            drought_tolerance_score=4.6,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=2.4,
            wind_lodging_resistance=ExtremeResistanceLevel.HIGH,
            wind_tolerance_score=4.0,
            frost_cold_resistance=ExtremeResistanceLevel.VERY_HIGH,
            frost_tolerance_score=4.5,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.2,
            salinity_tolerance="High",
            extreme_event_notes="One of the most salt- and drought-resilient small grains in commercial production."
        )
    ),
    "Processing Tomatoes": SeedDataInput(
        crop_name="Processing Tomatoes",
        variety_or_hybrid_name="Determinate Processing Hybrid",
        seed_cost_usd_per_ha=450.0,
        seeding_rate_kg_ha=0.4,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        can_grow_in_greenhouse=True,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.LOW,
            drought_tolerance_score=2.0,
            flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
            flood_tolerance_score=1.8,
            wind_lodging_resistance=ExtremeResistanceLevel.LOW,
            wind_tolerance_score=2.2,
            frost_cold_resistance=ExtremeResistanceLevel.VERY_LOW,
            frost_tolerance_score=1.2,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.2,
            salinity_tolerance="Moderate",
            extreme_event_notes="Highly vulnerable to blossom end rot during water swings; benefited by sheltered microclimates."
        )
    ),
    "Daikon Radish & Rye (Regenerative Bio-Drill)": SeedDataInput(
        crop_name="Daikon Radish & Rye (Regenerative Bio-Drill)",
        variety_or_hybrid_name="Tillage Radish + Cereal Rye Blend",
        seed_cost_usd_per_ha=65.0,
        seeding_rate_kg_ha=30.0,
        greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
        can_grow_in_greenhouse=False,
        requires_greenhouse=False,
        extreme_event_resistance=ExtremeEventResistance(
            drought_resistance=ExtremeResistanceLevel.HIGH,
            drought_tolerance_score=4.2,
            flood_waterlogging_resistance=ExtremeResistanceLevel.MODERATE,
            flood_tolerance_score=3.2,
            wind_lodging_resistance=ExtremeResistanceLevel.VERY_HIGH,
            wind_tolerance_score=4.8,
            frost_cold_resistance=ExtremeResistanceLevel.VERY_HIGH,
            frost_tolerance_score=4.8,
            extreme_heat_resistance=ExtremeResistanceLevel.MODERATE,
            heat_tolerance_score=3.2,
            salinity_tolerance="Moderate to High",
            extreme_event_notes="Extreme root penetration (breaks hardpan >300 PSI); dense rye canopy withstands heavy storms."
        )
    )
}


# ==============================================================================
# NORMALIZED OUTPUT SCHEMA PRESERVING FULL DATED TIMESERIES
# ==============================================================================

class ParsedFieldNormalized(BaseModel):
    """
    Standardized, high-resolution representation produced by the parser.
    Retains full dated daily weather, rain, moisture, ET, scenes, depth layers,
    and user sensor readings alongside derived agro-climatological indices.
    """
    # 1. Parcel Core & Soil Type
    parcel_id: str
    field_name: str
    latitude: float
    longitude: float
    area_hectares: float
    area_acres: float
    cadastral_number: Optional[str] = None
    boundary_geojson: Optional[Dict[str, Any]] = None
    water_rights_quota_m3: Optional[float] = None
    soil_type: str = Field(description="Harmonized effective soil type")
    soil_type_source: str = Field(description="Source of soil type: 'User Local Override', 'Parcel Declared', 'SoilGrids Satellite', or 'Regional Baseline'")

    # 2. Historical Harvest & Rotation Summary (1-5 Flexible Years)
    history_years_count: int
    history_years_span: str
    past_crops_sequence: List[str]
    past_botanical_families: List[str]
    avg_historical_yield_tons_ha: float
    cumulative_nitrogen_applied_kg_ha: float
    cumulative_irrigation_applied_mm: float
    observed_pest_pathogens: List[str]
    detailed_past_seasons: List[Dict[str, Any]]

    # 3. Economic Price Index (Standardized $/ha & Unit Costs)
    diesel_price_usd_liter: float
    water_price_usd_m3: float
    electricity_kwh_usd: float
    nitrogen_fertilizer_usd_kg: float
    phosphorus_fertilizer_usd_kg: float
    potassium_fertilizer_usd_kg: float
    labor_hourly_wage_usd: float
    custom_seed_prices: Dict[str, float]

    # 4. Seed Variety Specifications (Greenhouse Need & Extreme Event Resistances)
    seed_catalog: Dict[str, SeedDataInput] = Field(default_factory=dict)
    greenhouse_compatible_crops: List[str] = Field(default_factory=list)
    greenhouse_required_crops: List[str] = Field(default_factory=list)
    open_field_only_crops: List[str] = Field(default_factory=list)
    drought_resilient_crops: List[str] = Field(default_factory=list)
    flood_resilient_crops: List[str] = Field(default_factory=list)
    wind_resilient_crops: List[str] = Field(default_factory=list)
    frost_resilient_crops: List[str] = Field(default_factory=list)
    heat_resilient_crops: List[str] = Field(default_factory=list)

    # 5. Full Dated Timeseries Preserved from NASA & In-Situ Sensors
    daily_weather_timeseries: List[DatedDailyWeatherRecord] = Field(
        default_factory=list,
        description="Preserved full daily weather records with date signatures (NASA POWER)"
    )
    daily_rainfall_timeseries: List[DatedPrecipitationObservation] = Field(
        default_factory=list,
        description="Preserved full daily precipitation records with storm intensities (NASA GPM IMERG)"
    )
    daily_soil_moisture_timeseries: List[DatedSoilMoistureRecord] = Field(
        default_factory=list,
        description="Preserved surface and root-zone moisture records with dates (NASA SMAP)"
    )
    daily_openet_timeseries: List[OpenEtTimeseriesRecord] = Field(
        default_factory=list,
        description="Preserved actual evapotranspiration records with dates (NASA OpenET)"
    )
    ecostress_scenes: List[EcostressSceneRecord] = Field(
        default_factory=list,
        description="Preserved canopy thermal infrared stress scenes with timestamps (NASA ECOSTRESS)"
    )
    hls_overpasses: List[HlsOverpassRecord] = Field(
        default_factory=list,
        description="Preserved multispectral NDVI/NDRE overpasses with dates (Harmonized Landsat-Sentinel)"
    )
    soil_depth_layers: List[SoilGridsDepthLayer] = Field(
        default_factory=list,
        description="Preserved depth-stratified soil horizon intervals (ISRIC SoilGrids 2.0)"
    )
    grace_monthly_anomalies: List[GraceMonthlyRecord] = Field(
        default_factory=list,
        description="Preserved monthly deep groundwater anomalies with dates (NASA GRACE)"
    )
    dated_in_situ_sensors: List[DatedInSituSensorReading] = Field(
        default_factory=list,
        description="Preserved grower ground sensor readings with explicit date/time signatures"
    )

    # 6. High-Resolution Temporal Statistics Derived from Dated Series
    weather_start_date: Optional[str] = None
    weather_end_date: Optional[str] = None
    weather_days_count: int = 0
    frost_days_count: int = 0
    heatwave_days_count: int = 0
    max_consecutive_dry_days: int = 0
    peak_storm_event_date: Optional[str] = None
    peak_storm_event_mm: Optional[float] = None
    peak_ndvi_date: Optional[str] = None
    in_situ_readings_count: int = 0
    in_situ_earliest_timestamp: Optional[str] = None
    in_situ_latest_timestamp: Optional[str] = None

    # 7. NASA Earth Observations (Summary Benchmarks)
    nasa_power_temp_mean_c: float
    nasa_power_solar_radiation_mj_m2: float
    nasa_power_gdd_accumulated: float
    nasa_power_et0_annual_mm: float
    gpm_imerg_annual_rainfall_mm: float
    gpm_imerg_growing_season_rain_mm: float
    smap_rootzone_moisture_vol_pct: float
    openet_actual_et_annual_mm: float
    ecostress_evaporative_stress_index: float
    hls_peak_ndvi: float
    soilgrids_texture_class: str
    soilgrids_organic_carbon_pct: float
    soilgrids_ph: float
    grace_groundwater_trend: str

    # 8. Long-Term Weather Shift Projections
    climate_scenario_name: str
    has_custom_climate_projections: bool
    projected_temp_rise_c: float
    projected_precipitation_shift_pct: float
    drought_frequency_assessment: str

    # 9. Local Ground Truth & Farmer Preferences
    portable_sensors_present: bool
    calibrated_topsoil_n_kg_ha: Optional[float] = None
    calibrated_soil_ph: Optional[float] = None
    calibrated_soc_pct: Optional[float] = None
    calibrated_compaction_psi: Optional[float] = None
    compaction_level_tag: str
    irrigation_system: str
    tillage_practice: str
    is_organic: bool
    whitelisted_crops: Optional[List[str]] = None
    blacklisted_crops: List[str] = Field(default_factory=list)

    # 10. Elevation & Terrain
    elevation_mean_m: float
    slope_mean_pct: float
    slope_aspect: str
    waterlogging_depression_risk: bool
    erosion_susceptibility_rating: str

    # Quality & Audit
    data_completeness_score_pct: float
    audit_messages: List[str]


# ==============================================================================
# FIELD INGESTION PARSER SERVICE
# ==============================================================================

class FieldIngestionParser:
    """Core parser service converting raw multi-modal inputs into normalized structures."""

    @classmethod
    def parse_and_validate(cls, payload: FullFieldIngestionPayload) -> ParsedFieldNormalized:
        audit_logs: List[str] = []
        completeness_points = 0.0
        max_points = 80.0

        # ----------------------------------------------------------------------
        # 1. PARCEL INFO & BASELINE SOIL TYPE
        # ----------------------------------------------------------------------
        p = payload.parcel_info
        parcel_id = p.parcel_id
        field_name = p.field_name or f"Parcel-{parcel_id}"

        lat = p.latitude
        lon = p.longitude
        if lat is None or lon is None:
            lat = 41.5300
            lon = -93.6500
            audit_logs.append(f"Coordinates absent in parcel info. Applied regional benchmark (Lat: {lat}, Lon: {lon}).")
        else:
            completeness_points += 10.0

        area_ha = p.area_hectares
        if area_ha is None:
            area_ha = round(p.area_acres * 0.404686, 2) if p.area_acres else 10.0
            audit_logs.append(f"Area in hectares defaulted or derived from acres: {area_ha} ha.")
        area_ac = p.area_acres or round(area_ha * 2.47105, 2)

        # ----------------------------------------------------------------------
        # 2. HARVEST & CROP HISTORY (MAX 5 FLEXIBLE)
        # ----------------------------------------------------------------------
        history = payload.harvest_history.historical_seasons
        if len(history) > 5:
            audit_logs.append(f"Provided {len(history)} historical seasons; trimmed to most recent 5 years.")
            history = history[-5:]

        history_count = len(history)
        years_list = [h.year for h in history]
        history_span = f"{min(years_list)} - {max(years_list)}" if years_list else "None"
        past_crops = [h.crop_name for h in history]
        past_families = [h.botanical_family or cls._infer_botanical_family(h.crop_name) for h in history]

        yields = [h.yield_harvested_tons_ha for h in history if h.yield_harvested_tons_ha is not None]
        avg_yield = round(sum(yields) / len(yields), 2) if yields else 4.5

        tot_n_applied = sum(h.nitrogen_applied_kg_ha or 0.0 for h in history)
        tot_irrigation = sum(h.irrigation_applied_mm or 0.0 for h in history)

        pests: List[str] = []
        for h in history:
            if h.pest_disease_incidents:
                pests.extend(h.pest_disease_incidents)
        observed_pests = list(set(pests))

        detailed_seasons = [h.model_dump() for h in history]
        completeness_points += min(10.0, history_count * 2.0)
        audit_logs.append(f"Parsed {history_count} historical cultivation years spanning {history_span}.")

        # ----------------------------------------------------------------------
        # 3. SEED SPECIFICATIONS & GREENHOUSE / EXTREME RESISTANCE
        # ----------------------------------------------------------------------
        raw_seeds: List[SeedDataInput] = []
        if payload.seed_data:
            raw_seeds.extend(payload.seed_data)
        if payload.economic_prices and payload.economic_prices.seed_data:
            for s in payload.economic_prices.seed_data:
                if not any(existing.crop_name == s.crop_name for existing in raw_seeds):
                    raw_seeds.append(s)

        seed_catalog: Dict[str, SeedDataInput] = {}
        for s in raw_seeds:
            seed_catalog[s.crop_name] = s

        relevant_crops = set(past_crops)
        if payload.local_user_data and payload.local_user_data.preferred_candidate_crops:
            relevant_crops.update(payload.local_user_data.preferred_candidate_crops)
        if payload.economic_prices and payload.economic_prices.seed_prices_usd_per_ha:
            relevant_crops.update(payload.economic_prices.seed_prices_usd_per_ha.keys())

        if not seed_catalog:
            relevant_crops.update(["Corn (Maize)", "Soybeans", "Winter Wheat", "Alfalfa / Clover (Perennial Legume)"])

        for c_name in relevant_crops:
            if c_name not in seed_catalog:
                matched_profile = cls._match_default_seed_profile(c_name)
                if (payload.economic_prices and payload.economic_prices.seed_prices_usd_per_ha and
                        c_name in payload.economic_prices.seed_prices_usd_per_ha):
                    matched_profile.seed_cost_usd_per_ha = payload.economic_prices.seed_prices_usd_per_ha[c_name]
                seed_catalog[c_name] = matched_profile

        greenhouse_compat: List[str] = []
        greenhouse_req: List[str] = []
        open_field_only: List[str] = []
        drought_resilient: List[str] = []
        flood_resilient: List[str] = []
        wind_resilient: List[str] = []
        frost_resilient: List[str] = []
        heat_resilient: List[str] = []

        for name, seed in seed_catalog.items():
            if seed.can_grow_in_greenhouse:
                greenhouse_compat.append(name)
            if seed.requires_greenhouse:
                greenhouse_req.append(name)
            if seed.greenhouse_need == GreenhouseRequirement.OPEN_FIELD_ONLY:
                open_field_only.append(name)

            res = seed.extreme_event_resistance
            if res.drought_tolerance_score >= 3.8:
                drought_resilient.append(name)
            if res.flood_tolerance_score >= 3.0:
                flood_resilient.append(name)
            if res.wind_tolerance_score >= 3.8:
                wind_resilient.append(name)
            if res.frost_tolerance_score >= 3.8:
                frost_resilient.append(name)
            if res.heat_tolerance_score >= 3.8:
                heat_resilient.append(name)

        if raw_seeds:
            completeness_points += 10.0
            audit_logs.append(f"Ingested {len(raw_seeds)} custom seed specifications with greenhouse & extreme event traits.")
        else:
            completeness_points += 5.0
            audit_logs.append(f"Seed specifications auto-enriched ({len(seed_catalog)} varieties) using standard agronomic traits.")

        # ----------------------------------------------------------------------
        # 4. ECONOMIC PRICES
        # ----------------------------------------------------------------------
        econ = payload.economic_prices
        diesel_price = econ.diesel_fuel_price_usd_liter
        water_price = econ.irrigation_water_price_usd_m3
        electricity_price = econ.electricity_pumping_tariff_usd_kwh or 0.12
        n_price = econ.nitrogen_price_usd_kg or 1.35
        p_price = econ.phosphorus_price_usd_kg or 1.65
        k_price = econ.potassium_price_usd_kg or 0.95
        labor_wage = econ.labor_hourly_wage_usd or 22.0
        custom_seed_prices = econ.seed_prices_usd_per_ha or {}
        for c_name, s_data in seed_catalog.items():
            if s_data.seed_cost_usd_per_ha is not None and c_name not in custom_seed_prices:
                custom_seed_prices[c_name] = s_data.seed_cost_usd_per_ha

        completeness_points += 10.0

        # ----------------------------------------------------------------------
        # 5. NASA DATA (OFFICIAL FORMATS & DATED TIMESERIES EXTRACTION)
        # ----------------------------------------------------------------------
        daily_weather: List[DatedDailyWeatherRecord] = []
        daily_rainfall: List[DatedPrecipitationObservation] = []
        daily_moisture: List[DatedSoilMoistureRecord] = []
        daily_openet: List[OpenEtTimeseriesRecord] = []
        ecostress_scenes: List[EcostressSceneRecord] = []
        hls_overpasses: List[HlsOverpassRecord] = []
        soil_depth_layers: List[SoilGridsDepthLayer] = []
        grace_monthly: List[GraceMonthlyRecord] = []

        weather_start_date = None
        weather_end_date = None
        weather_days_count = 0
        frost_days_count = 0
        heatwave_days_count = 0
        max_consecutive_dry_days = 0
        peak_storm_date = None
        peak_storm_mm = None
        peak_ndvi_date = None

        # Defaults if NASA absent
        t_mean, solar, gdd, et0 = 18.5, 18.0, 1650.0, 1200.0
        rain_ann, rain_grow = 620.0, 403.0
        smap_root, openet_et, ecostress_esi, hls_ndvi = 28.0, 480.0, 0.75, 0.78
        soil_tex, soil_soc, soil_ph, grace_trend = "Clay Loam", 2.15, 6.7, "Stable (Calibrated)"

        nasa = payload.nasa_data
        if nasa:
            completeness_points += 10.0

            # 5A. NASA POWER (Extract full daily weather series from official formats)
            if nasa.nasa_power:
                daily_weather = cls._extract_nasa_power_timeseries(nasa.nasa_power)
                if daily_weather:
                    weather_days_count = len(daily_weather)
                    weather_start_date = daily_weather[0].date
                    weather_end_date = daily_weather[-1].date
                    audit_logs.append(
                        f"Extracted {weather_days_count} daily weather records from NASA POWER ({weather_start_date} to {weather_end_date})."
                    )

                    t_means = [w.t2m_c for w in daily_weather if w.t2m_c is not None]
                    t_mean = round(sum(t_means) / len(t_means), 2) if t_means else 18.5

                    solars = [w.solar_radiation_mj_m2 for w in daily_weather if w.solar_radiation_mj_m2 is not None]
                    solar = round(sum(solars) / len(solars), 2) if solars else 18.0

                    # GDD base 10°C calculation from daily series
                    daily_gdd = [max(0.0, ((w.t2m_max_c + w.t2m_min_c)/2.0 if w.t2m_max_c is not None and w.t2m_min_c is not None else w.t2m_c or 0.0) - 10.0) for w in daily_weather]
                    gdd = round(sum(daily_gdd), 1)

                    # Frost days (Tmin <= 0°C) and Heatwave days (Tmax >= 35°C)
                    frost_days_count = sum(1 for w in daily_weather if w.t2m_min_c is not None and w.t2m_min_c <= 0.0)
                    heatwave_days_count = sum(1 for w in daily_weather if w.t2m_max_c is not None and w.t2m_max_c >= 35.0)

                    # Consecutive dry days calculation
                    cur_dry = 0
                    for w in daily_weather:
                        p_val = w.precipitation_mm or 0.0
                        if p_val < 1.0:
                            cur_dry += 1
                            if cur_dry > max_consecutive_dry_days:
                                max_consecutive_dry_days = cur_dry
                        else:
                            cur_dry = 0
                else:
                    # Fallback to scalar inputs if timeseries absent
                    t_mean = nasa.nasa_power.t2m_mean_c or 18.5
                    solar = nasa.nasa_power.solar_radiation_mj_m2 or 18.2
                    gdd = nasa.nasa_power.growing_degree_days_base10 or 1650.0
                    et0 = nasa.nasa_power.fao56_et0_annual_mm or 1220.0

            # 5B. NASA GPM IMERG (Extract daily precipitation & storm events)
            if nasa.gpm_imerg:
                daily_rainfall = cls._extract_gpm_timeseries(nasa.gpm_imerg)
                if daily_rainfall:
                    rain_ann = round(sum(r.precipitation_mm for r in daily_rainfall), 1)
                    rain_grow = round(rain_ann * 0.65, 1)
                    storm_event = max(daily_rainfall, key=lambda r: r.precipitation_mm)
                    peak_storm_date = storm_event.date
                    peak_storm_mm = storm_event.precipitation_mm
                    audit_logs.append(
                        f"Extracted {len(daily_rainfall)} dated rainfall records from GPM IMERG (Peak 24h storm: {peak_storm_mm} mm on {peak_storm_date})."
                    )
                else:
                    rain_ann = nasa.gpm_imerg.annual_rainfall_mm or 620.0
                    rain_grow = nasa.gpm_imerg.growing_season_rainfall_mm or round(rain_ann * 0.65, 1)

            # 5C. NASA SMAP (Extract daily surface & rootzone moisture)
            if nasa.smap_moisture:
                daily_moisture = cls._extract_smap_timeseries(nasa.smap_moisture)
                if daily_moisture:
                    m_vals = [m.rootzone_moisture_m3_m3 for m in daily_moisture if m.rootzone_moisture_m3_m3 is not None]
                    smap_root = round((sum(m_vals) / len(m_vals)) * 100.0, 1) if m_vals else 28.0
                    audit_logs.append(f"Extracted {len(daily_moisture)} dated soil moisture records from SMAP L4.")
                elif nasa.smap_moisture.rootzone_moisture_m3_m3 is not None:
                    smap_root = round(nasa.smap_moisture.rootzone_moisture_m3_m3 * 100.0, 1)

            # 5D. NASA OpenET (Extract actual ET timeseries)
            if nasa.openet_water:
                daily_openet = cls._extract_openet_timeseries(nasa.openet_water)
                if daily_openet:
                    openet_et = round(sum(e.et_actual_mm for e in daily_openet), 1)
                    audit_logs.append(f"Extracted {len(daily_openet)} dated actual ET records from OpenET (Total: {openet_et} mm).")
                elif nasa.openet_water.actual_et_annual_mm is not None:
                    openet_et = nasa.openet_water.actual_et_annual_mm

            # 5E. NASA ECOSTRESS (Extract scenes)
            if nasa.ecostress:
                ecostress_scenes = cls._extract_ecostress_scenes(nasa.ecostress)
                if ecostress_scenes:
                    esi_vals = [s.evaporative_stress_index for s in ecostress_scenes if s.evaporative_stress_index is not None]
                    ecostress_esi = round(sum(esi_vals) / len(esi_vals), 2) if esi_vals else 0.75
                    audit_logs.append(f"Extracted {len(ecostress_scenes)} thermal stress overpass scenes from ECOSTRESS.")
                elif nasa.ecostress.evaporative_stress_index is not None:
                    ecostress_esi = nasa.ecostress.evaporative_stress_index

            # 5F. HLS Multispectral (Extract overpasses)
            if nasa.hls_vegetation:
                hls_overpasses = cls._extract_hls_overpasses(nasa.hls_vegetation)
                if hls_overpasses:
                    best_scene = max(hls_overpasses, key=lambda s: s.ndvi if s.ndvi is not None else -1.0)
                    hls_ndvi = best_scene.ndvi or 0.78
                    peak_ndvi_date = best_scene.date
                    audit_logs.append(f"Extracted {len(hls_overpasses)} multispectral scenes from HLS (Peak NDVI: {hls_ndvi} on {peak_ndvi_date}).")
                elif nasa.hls_vegetation.ndvi_peak is not None:
                    hls_ndvi = nasa.hls_vegetation.ndvi_peak

            # 5G. SoilGrids (Extract depth horizons)
            if nasa.soilgrids:
                soil_depth_layers = cls._extract_soilgrids_layers(nasa.soilgrids)
                if soil_depth_layers:
                    top_layer = soil_depth_layers[0]
                    soil_soc = top_layer.soil_organic_carbon_pct or 2.15
                    soil_ph = top_layer.soil_ph_h2o or 6.7
                    audit_logs.append(f"Extracted {len(soil_depth_layers)} depth-stratified horizon layers from SoilGrids 2.0.")
                else:
                    soil_soc = nasa.soilgrids.soil_organic_carbon_pct or 2.15
                    soil_ph = nasa.soilgrids.soil_ph_h2o or 6.7
                soil_tex = nasa.soilgrids.texture_class or "Clay Loam"

            # 5H. GRACE Groundwater (Extract monthly series)
            if nasa.grace_groundwater:
                grace_monthly = cls._extract_grace_series(nasa.grace_groundwater)
                if grace_monthly:
                    audit_logs.append(f"Extracted {len(grace_monthly)} monthly groundwater anomaly records from GRACE.")
                grace_trend = nasa.grace_groundwater.terrestrial_water_storage_trend or "Stable"

        else:
            audit_logs.append("NASA payload absent; generated regional calibrated agro-climatology baseline.")

        # ----------------------------------------------------------------------
        # 6. RESOLVE EFFECTIVE SOIL TYPE
        # ----------------------------------------------------------------------
        if payload.local_user_data and payload.local_user_data.soil_type:
            effective_soil_type = payload.local_user_data.soil_type
            soil_type_source = "User Local Override"
            audit_logs.append(f"Applied farmer-specified soil type override: '{effective_soil_type}'.")
        elif payload.parcel_info and payload.parcel_info.soil_type:
            effective_soil_type = payload.parcel_info.soil_type
            soil_type_source = "Parcel Declared"
            audit_logs.append(f"Applied parcel-level declared soil type: '{effective_soil_type}'.")
        elif payload.nasa_data and payload.nasa_data.soilgrids and payload.nasa_data.soilgrids.texture_class:
            effective_soil_type = payload.nasa_data.soilgrids.texture_class
            soil_type_source = "SoilGrids Satellite"
            audit_logs.append(f"Derived soil type from NASA SoilGrids 2.0 texture class: '{effective_soil_type}'.")
        else:
            effective_soil_type = soil_tex or "Clay Loam"
            soil_type_source = "Regional Baseline"
            audit_logs.append(f"Soil type assigned from regional agro-ecological baseline: '{effective_soil_type}'.")

        # ----------------------------------------------------------------------
        # 7. LONG TERM WEATHER PROJECTIONS (OPTIONAL)
        # ----------------------------------------------------------------------
        lt = payload.long_term_projections
        if lt:
            completeness_points += 10.0
            scenario_name = str(lt.scenario.value if hasattr(lt.scenario, 'value') else lt.scenario)
            has_lt = True
            temp_rise = lt.projected_annual_temp_shift_c or 0.35
            rain_shift = lt.projected_annual_precipitation_delta_pct or -2.5
            drought_rating = lt.drought_frequency_rating or "Moderate (1 in 4 yr)"
            audit_logs.append(f"Ingested long-term climate projection scenario: {scenario_name} (+{temp_rise:.2f}°C, {rain_shift:+.1f}% rain).")
        else:
            scenario_name = "Historical Persistence Baseline"
            has_lt = False
            temp_rise = 0.25
            rain_shift = -1.5
            drought_rating = "Low to Moderate"
            audit_logs.append("Long-term climate scenario omitted; projecting forward based on historical decadal trend.")

        # ----------------------------------------------------------------------
        # 8. LOCAL USER DATA (IN-SITU SENSORS WITH DATE SIGNATURES)
        # ----------------------------------------------------------------------
        usr = payload.local_user_data
        calib_n = None
        calib_ph = None
        calib_soc = None
        calib_comp_psi = None
        comp_tag = "Optimal Tilth (<200 PSI)"
        dated_sensor_list: List[DatedInSituSensorReading] = []
        earliest_ts = None
        latest_ts = None

        if usr:
            completeness_points += 10.0
            irrig_sys = str(usr.irrigation_system.value if hasattr(usr.irrigation_system, 'value') else usr.irrigation_system)
            tillage = str(usr.tillage_practice.value if hasattr(usr.tillage_practice, 'value') else usr.tillage_practice)
            is_org = usr.is_organic_certified
            whitelist = usr.preferred_candidate_crops
            blacklist = usr.excluded_crops or []

            # 8A. Process dated in-situ sensor readings
            if usr.dated_sensor_readings:
                sensors_present = True
                # Sort chronologically by timestamp
                dated_sensor_list = sorted(usr.dated_sensor_readings, key=lambda s: s.timestamp)
                earliest_ts = dated_sensor_list[0].timestamp
                latest_ts = dated_sensor_list[-1].timestamp
                # Calibrate using the most recent reading
                latest_reading = dated_sensor_list[-1]
                if latest_reading.soil_nitrogen_ppm is not None:
                    calib_n = round(latest_reading.soil_nitrogen_ppm * 2.24, 1)
                if latest_reading.soil_ph is not None:
                    calib_ph = round(latest_reading.soil_ph, 2)
                    soil_ph = calib_ph
                if latest_reading.soil_organic_matter_pct is not None:
                    calib_soc = round(latest_reading.soil_organic_matter_pct / 1.724, 2)
                    soil_soc = calib_soc
                if latest_reading.soil_compaction_psi is not None:
                    calib_comp_psi = latest_reading.soil_compaction_psi
                    if calib_comp_psi > 300:
                        comp_tag = f"Severe Hardpan ({calib_comp_psi:.0f} PSI - Root barrier)"
                    elif calib_comp_psi > 200:
                        comp_tag = f"Moderate Plowpan ({calib_comp_psi:.0f} PSI)"
                    else:
                        comp_tag = f"Optimal Tilth ({calib_comp_psi:.0f} PSI)"
                audit_logs.append(
                    f"Fused {len(dated_sensor_list)} dated in-situ sensor readings ({earliest_ts} to {latest_ts}). Latest Compaction: {comp_tag}."
                )
            elif usr.portable_sensors:
                # Fallback to single snapshot
                sensors_present = True
                sens = usr.portable_sensors
                ts = sens.measurement_timestamp or "Single-Point"
                earliest_ts = ts
                latest_ts = ts
                dated_sensor_list = [
                    DatedInSituSensorReading(
                        timestamp=ts,
                        soil_nitrogen_ppm=sens.soil_nitrogen_ppm,
                        soil_phosphorus_ppm=sens.soil_phosphorus_ppm,
                        soil_potassium_ppm=sens.soil_potassium_ppm,
                        soil_moisture_vol_pct=sens.soil_moisture_vol_pct,
                        soil_ph=sens.soil_ph,
                        soil_ec_salinity_ds_m=sens.soil_ec_salinity_ds_m,
                        soil_organic_matter_pct=sens.soil_organic_matter_pct,
                        soil_compaction_psi=sens.soil_compaction_psi,
                        device_model=sens.device_model
                    )
                ]
                if sens.soil_nitrogen_ppm is not None:
                    calib_n = round(sens.soil_nitrogen_ppm * 2.24, 1)
                if sens.soil_ph is not None:
                    calib_ph = round(sens.soil_ph, 2)
                    soil_ph = calib_ph
                if sens.soil_organic_matter_pct is not None:
                    calib_soc = round(sens.soil_organic_matter_pct / 1.724, 2)
                    soil_soc = calib_soc
                if sens.soil_compaction_psi is not None:
                    calib_comp_psi = sens.soil_compaction_psi
                    if calib_comp_psi > 300:
                        comp_tag = f"Severe Hardpan ({calib_comp_psi:.0f} PSI - Root barrier)"
                    elif calib_comp_psi > 200:
                        comp_tag = f"Moderate Plowpan ({calib_comp_psi:.0f} PSI)"
                    else:
                        comp_tag = f"Optimal Tilth ({calib_comp_psi:.0f} PSI)"
                audit_logs.append(f"Fused single-point in-situ sensor reading (Compaction: {comp_tag}).")
            else:
                sensors_present = False
        else:
            sensors_present = False
            irrig_sys = "Center Pivot Sprinkler"
            tillage = "Strip-Till / Reduced Tillage"
            is_org = False
            whitelist = None
            blacklist = []
            audit_logs.append("Local user telemetry omitted; defaulted to standard commercial tillage and irrigation.")

        # ----------------------------------------------------------------------
        # 9. ELEVATION MAPS & TOPOGRAPHY
        # ----------------------------------------------------------------------
        topo = payload.elevation_maps
        if topo:
            completeness_points += 10.0
            elev_mean = topo.elevation_mean_m or 280.0
            slope_mean = topo.slope_mean_pct or 2.2
            aspect = str(topo.aspect.value if hasattr(topo.aspect, 'value') else topo.aspect)
            waterlogging = bool(topo.waterlogging_depression_present)
            erosion_stat = topo.soil_erosion_susceptibility or ("Low" if slope_mean < 3.0 else "Moderate")
            audit_logs.append(f"Parsed elevation metrics: Mean Elevation {elev_mean:.1f}m, Slope {slope_mean:.1f}%, Aspect: {aspect}.")
        else:
            elev_mean, slope_mean, aspect, waterlogging, erosion_stat = 250.0, 2.0, "Flat / Level Terrain", False, "Low"
            audit_logs.append("Elevation maps omitted; applied regional topographic elevation (250m, 2% slope).")

        completeness_pct = round((completeness_points / max_points) * 100.0, 1)

        return ParsedFieldNormalized(
            parcel_id=parcel_id,
            field_name=field_name,
            latitude=lat,
            longitude=lon,
            area_hectares=area_ha,
            area_acres=area_ac,
            cadastral_number=p.cadastral_number,
            boundary_geojson=p.boundary_geojson,
            water_rights_quota_m3=p.annual_water_quota_m3,
            soil_type=effective_soil_type,
            soil_type_source=soil_type_source,
            history_years_count=history_count,
            history_years_span=history_span,
            past_crops_sequence=past_crops,
            past_botanical_families=past_families,
            avg_historical_yield_tons_ha=avg_yield,
            cumulative_nitrogen_applied_kg_ha=round(tot_n_applied, 1),
            cumulative_irrigation_applied_mm=round(tot_irrigation, 1),
            observed_pest_pathogens=observed_pests,
            detailed_past_seasons=detailed_seasons,
            diesel_price_usd_liter=diesel_price,
            water_price_usd_m3=water_price,
            electricity_kwh_usd=electricity_price,
            nitrogen_fertilizer_usd_kg=n_price,
            phosphorus_fertilizer_usd_kg=p_price,
            potassium_fertilizer_usd_kg=k_price,
            labor_hourly_wage_usd=labor_wage,
            custom_seed_prices=custom_seed_prices,
            seed_catalog=seed_catalog,
            greenhouse_compatible_crops=greenhouse_compat,
            greenhouse_required_crops=greenhouse_req,
            open_field_only_crops=open_field_only,
            drought_resilient_crops=drought_resilient,
            flood_resilient_crops=flood_resilient,
            wind_resilient_crops=wind_resilient,
            frost_resilient_crops=frost_resilient,
            heat_resilient_crops=heat_resilient,
            daily_weather_timeseries=daily_weather,
            daily_rainfall_timeseries=daily_rainfall,
            daily_soil_moisture_timeseries=daily_moisture,
            daily_openet_timeseries=daily_openet,
            ecostress_scenes=ecostress_scenes,
            hls_overpasses=hls_overpasses,
            soil_depth_layers=soil_depth_layers,
            grace_monthly_anomalies=grace_monthly,
            dated_in_situ_sensors=dated_sensor_list,
            weather_start_date=weather_start_date,
            weather_end_date=weather_end_date,
            weather_days_count=weather_days_count,
            frost_days_count=frost_days_count,
            heatwave_days_count=heatwave_days_count,
            max_consecutive_dry_days=max_consecutive_dry_days,
            peak_storm_event_date=peak_storm_date,
            peak_storm_event_mm=peak_storm_mm,
            peak_ndvi_date=peak_ndvi_date,
            in_situ_readings_count=len(dated_sensor_list),
            in_situ_earliest_timestamp=earliest_ts,
            in_situ_latest_timestamp=latest_ts,
            nasa_power_temp_mean_c=t_mean,
            nasa_power_solar_radiation_mj_m2=solar,
            nasa_power_gdd_accumulated=gdd,
            nasa_power_et0_annual_mm=et0,
            gpm_imerg_annual_rainfall_mm=rain_ann,
            gpm_imerg_growing_season_rain_mm=rain_grow,
            smap_rootzone_moisture_vol_pct=smap_root,
            openet_actual_et_annual_mm=openet_et,
            ecostress_evaporative_stress_index=ecostress_esi,
            hls_peak_ndvi=hls_ndvi,
            soilgrids_texture_class=soil_tex,
            soilgrids_organic_carbon_pct=soil_soc,
            soilgrids_ph=soil_ph,
            grace_groundwater_trend=grace_trend,
            climate_scenario_name=scenario_name,
            has_custom_climate_projections=has_lt,
            projected_temp_rise_c=temp_rise,
            projected_precipitation_shift_pct=rain_shift,
            drought_frequency_assessment=drought_rating,
            portable_sensors_present=sensors_present,
            calibrated_topsoil_n_kg_ha=calib_n,
            calibrated_soil_ph=calib_ph,
            calibrated_soc_pct=calib_soc,
            calibrated_compaction_psi=calib_comp_psi,
            compaction_level_tag=comp_tag,
            irrigation_system=irrig_sys,
            tillage_practice=tillage,
            is_organic=is_org,
            whitelisted_crops=whitelist,
            blacklisted_crops=blacklist,
            elevation_mean_m=elev_mean,
            slope_mean_pct=slope_mean,
            slope_aspect=aspect,
            waterlogging_depression_risk=waterlogging,
            erosion_susceptibility_rating=erosion_stat,
            data_completeness_score_pct=completeness_pct,
            audit_messages=audit_logs
        )

    # ==========================================================================
    # NASA EXTRACTOR UTILITIES FOR OFFICIAL FORMATS & TIMESERIES
    # ==========================================================================

    @classmethod
    def _extract_nasa_power_timeseries(cls, power: Any) -> List[DatedDailyWeatherRecord]:
        """Extracts chronological dated daily weather records from official NASA POWER payload."""
        if power.daily_timeseries:
            return sorted(power.daily_timeseries, key=lambda w: w.date)

        # Check raw official GeoJSON or parameter dictionary
        param_dict = None
        if power.raw_official_response and isinstance(power.raw_official_response, dict):
            raw = power.raw_official_response
            param_dict = raw.get("properties", {}).get("parameter") or raw.get("parameter") or raw
        elif power.daily_parameters and isinstance(power.daily_parameters, dict):
            param_dict = power.daily_parameters

        if not param_dict:
            return []

        # Find all dates present across parameters
        dates_set = set()
        for param_name, date_map in param_dict.items():
            if isinstance(date_map, dict):
                dates_set.update(date_map.keys())

        if not dates_set:
            return []

        sorted_dates = sorted(dates_set)
        records: List[DatedDailyWeatherRecord] = []

        t2m_map = param_dict.get("T2M", {})
        t2m_max_map = param_dict.get("T2M_MAX", {})
        t2m_min_map = param_dict.get("T2M_MIN", {})
        precip_map = param_dict.get("PRECTOTCORR", {}) or param_dict.get("PRECTOT", {})
        solar_map = param_dict.get("ALLSKY_SFC_SW_DWN", {}) or param_dict.get("ALLSKY_SW_DWN", {})
        rh_map = param_dict.get("RH2M", {})
        ws_map = param_dict.get("WS2M", {})
        dew_map = param_dict.get("T2MDEW", {})
        ps_map = param_dict.get("PS", {})

        for raw_d in sorted_dates:
            # Normalize YYYYMMDD -> YYYY-MM-DD
            d_norm = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:]}" if len(raw_d) == 8 and raw_d.isdigit() else raw_d

            # Sentinel -999.0 indicates missing data in NASA POWER
            def safe_val(m: dict, key: str) -> Optional[float]:
                v = m.get(key)
                if v is None or v == -999.0 or v == -999:
                    return None
                return float(v)

            rec = DatedDailyWeatherRecord(
                date=d_norm,
                t2m_c=safe_val(t2m_map, raw_d),
                t2m_max_c=safe_val(t2m_max_map, raw_d),
                t2m_min_c=safe_val(t2m_min_map, raw_d),
                precipitation_mm=safe_val(precip_map, raw_d),
                solar_radiation_mj_m2=safe_val(solar_map, raw_d),
                relative_humidity_pct=safe_val(rh_map, raw_d),
                wind_speed_2m_ms=safe_val(ws_map, raw_d),
                dew_point_c=safe_val(dew_map, raw_d),
                surface_pressure_kpa=safe_val(ps_map, raw_d)
            )
            records.append(rec)

        return records

    @classmethod
    def _extract_gpm_timeseries(cls, gpm: Any) -> List[DatedPrecipitationObservation]:
        """Extracts chronological precipitation observations from GPM IMERG."""
        if gpm.daily_records:
            return sorted(gpm.daily_records, key=lambda r: r.date)
        if gpm.daily_rainfall_series and isinstance(gpm.daily_rainfall_series, dict):
            records = []
            for d, val in sorted(gpm.daily_rainfall_series.items()):
                records.append(DatedPrecipitationObservation(date=d, precipitation_mm=float(val)))
            return records
        if gpm.raw_official_response:
            if isinstance(gpm.raw_official_response, list):
                records = []
                for item in gpm.raw_official_response:
                    if isinstance(item, dict) and "date" in item and "precipitation_mm" in item:
                        records.append(DatedPrecipitationObservation(**item))
                if records:
                    return sorted(records, key=lambda r: r.date)
        return []

    @classmethod
    def _extract_smap_timeseries(cls, smap: Any) -> List[DatedSoilMoistureRecord]:
        """Extracts chronological soil moisture records from SMAP."""
        if smap.daily_records:
            return sorted(smap.daily_records, key=lambda r: r.date)
        if smap.raw_official_response and isinstance(smap.raw_official_response, list):
            records = []
            for item in smap.raw_official_response:
                if isinstance(item, dict) and "date" in item:
                    records.append(DatedSoilMoistureRecord(**item))
            if records:
                return sorted(records, key=lambda r: r.date)
        return []

    @classmethod
    def _extract_openet_timeseries(cls, openet: Any) -> List[OpenEtTimeseriesRecord]:
        """Extracts chronological actual ET records from OpenET."""
        if openet.timeseries:
            return sorted(openet.timeseries, key=lambda r: r.date)
        if openet.daily_et_series and isinstance(openet.daily_et_series, dict):
            records = []
            for d, val in sorted(openet.daily_et_series.items()):
                records.append(OpenEtTimeseriesRecord(date=d, et_actual_mm=float(val)))
            return records
        if openet.raw_official_response and isinstance(openet.raw_official_response, list):
            records = []
            for item in openet.raw_official_response:
                if isinstance(item, dict) and "date" in item:
                    et_val = item.get("et") if item.get("et") is not None else item.get("et_actual_mm", 0.0)
                    records.append(
                        OpenEtTimeseriesRecord(
                            date=item["date"],
                            et_actual_mm=float(et_val),
                            et_reference_et0_mm=item.get("et0"),
                            crop_coefficient_kc=item.get("kc")
                        )
                    )
            if records:
                return sorted(records, key=lambda r: r.date)
        return []

    @classmethod
    def _extract_ecostress_scenes(cls, ecostress: Any) -> List[EcostressSceneRecord]:
        """Extracts thermal stress scenes from ECOSTRESS."""
        if ecostress.scenes:
            return sorted(ecostress.scenes, key=lambda s: s.timestamp)
        if ecostress.raw_official_response and isinstance(ecostress.raw_official_response, list):
            scenes = []
            for item in ecostress.raw_official_response:
                if isinstance(item, dict) and ("timestamp" in item or "datetime" in item):
                    ts = item.get("timestamp") or item.get("datetime")
                    scenes.append(
                        EcostressSceneRecord(
                            timestamp=ts,
                            canopy_surface_temp_c=item.get("canopy_surface_temp_c") or item.get("lst_c"),
                            evaporative_stress_index=item.get("evaporative_stress_index") or item.get("esi")
                        )
                    )
            if scenes:
                return sorted(scenes, key=lambda s: s.timestamp)
        return []

    @classmethod
    def _extract_hls_overpasses(cls, hls: Any) -> List[HlsOverpassRecord]:
        """Extracts multispectral satellite overpasses from HLS."""
        if hls.overpasses:
            return sorted(hls.overpasses, key=lambda o: o.date)
        if hls.raw_official_response and isinstance(hls.raw_official_response, list):
            overpasses = []
            for item in hls.raw_official_response:
                if isinstance(item, dict) and "date" in item:
                    overpasses.append(HlsOverpassRecord(**item))
            if overpasses:
                return sorted(overpasses, key=lambda o: o.date)
        return []

    @classmethod
    def _extract_soilgrids_layers(cls, soilgrids: Any) -> List[SoilGridsDepthLayer]:
        """Extracts depth-stratified horizon layers from SoilGrids."""
        if soilgrids.depth_layers:
            return soilgrids.depth_layers
        if soilgrids.raw_official_response and isinstance(soilgrids.raw_official_response, dict):
            # Parse ISRIC properties.layers
            layers = soilgrids.raw_official_response.get("properties", {}).get("layers", [])
            if layers:
                depth_map: Dict[str, Dict[str, float]] = {}
                for layer in layers:
                    layer_name = layer.get("name")
                    for depth_info in layer.get("depths", []):
                        d_range = depth_info.get("range", {})
                        d_key = f"{d_range.get('top_depth', 0)}-{d_range.get('bottom_depth', 5)}cm"
                        if d_key not in depth_map:
                            depth_map[d_key] = {
                                "top": d_range.get("top_depth", 0),
                                "bottom": d_range.get("bottom_depth", 5)
                            }
                        val = depth_info.get("values", {}).get("mean")
                        if val is not None:
                            depth_map[d_key][layer_name] = val

                result_layers = []
                for d_key, vals in depth_map.items():
                    # ISRIC units: soc is dg/kg (divide by 100 for %), clay/sand/silt is g/kg (divide by 10 for %), ph is pH*10
                    soc_pct = round(vals.get("soc", 0) / 100.0, 2) if "soc" in vals else None
                    clay_pct = round(vals.get("clay", 0) / 10.0, 1) if "clay" in vals else None
                    sand_pct = round(vals.get("sand", 0) / 10.0, 1) if "sand" in vals else None
                    silt_pct = round(vals.get("silt", 0) / 10.0, 1) if "silt" in vals else None
                    ph_val = round(vals.get("phh2o", 0) / 10.0, 2) if "phh2o" in vals else None
                    bd_val = round(vals.get("bdod", 0) / 100.0, 2) if "bdod" in vals else None

                    result_layers.append(
                        SoilGridsDepthLayer(
                            depth_interval=d_key,
                            top_depth_cm=float(vals.get("top", 0)),
                            bottom_depth_cm=float(vals.get("bottom", 5)),
                            clay_pct=clay_pct,
                            sand_pct=sand_pct,
                            silt_pct=silt_pct,
                            soil_organic_carbon_pct=soc_pct,
                            soil_ph_h2o=ph_val,
                            bulk_density_g_cm3=bd_val
                        )
                    )
                if result_layers:
                    return result_layers
        return []

    @classmethod
    def _extract_grace_series(cls, grace: Any) -> List[GraceMonthlyRecord]:
        """Extracts monthly liquid water equivalent anomaly series from GRACE."""
        if grace.monthly_records:
            return sorted(grace.monthly_records, key=lambda r: r.date)
        if grace.monthly_series and isinstance(grace.monthly_series, dict):
            records = []
            for d, val in sorted(grace.monthly_series.items()):
                records.append(GraceMonthlyRecord(date=d, lwe_thickness_anomaly_cm=float(val)))
            return records
        return []

    @classmethod
    def _match_default_seed_profile(cls, crop_name: str) -> SeedDataInput:
        name_lower = crop_name.lower()
        for key, profile in DEFAULT_SEED_PROFILES.items():
            if key.lower() in name_lower or name_lower in key.lower():
                data = profile.model_dump()
                data["crop_name"] = crop_name
                return SeedDataInput(**data)

        return SeedDataInput(
            crop_name=crop_name,
            variety_or_hybrid_name="General Standard Variety",
            seed_cost_usd_per_ha=150.0,
            greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
            can_grow_in_greenhouse=False,
            requires_greenhouse=False,
            extreme_event_resistance=ExtremeEventResistance()
        )

    @staticmethod
    def _infer_botanical_family(crop_name: str) -> str:
        name_lower = crop_name.lower()
        if any(c in name_lower for c in ["corn", "maize", "wheat", "sorghum", "barley", "rye", "oats"]):
            return "Poaceae (Grasses / Cereals)"
        elif any(c in name_lower for c in ["soy", "pea", "chickpea", "clover", "alfalfa", "bean"]):
            return "Fabaceae (Legumes / Pulses)"
        elif any(c in name_lower for c in ["sunflower"]):
            return "Asteraceae (Composites)"
        elif any(c in name_lower for c in ["canola", "rapeseed", "radish", "mustard"]):
            return "Brassicaceae (Brassicas)"
        elif any(c in name_lower for c in ["tomato", "potato", "pepper", "eggplant"]):
            return "Solanaceae (Nightshades)"
        elif any(c in name_lower for c in ["cotton"]):
            return "Malvaceae (Mallows)"
        return "General Agronomic Family"
