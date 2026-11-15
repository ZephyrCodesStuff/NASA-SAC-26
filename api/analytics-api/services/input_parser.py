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
from datetime import date
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from projection_api.services.soil_physics import SoilPhysicsEngine

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
    country_code: str = "US"
    state_or_province: Optional[str] = None
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
    elemental_n_price_usd_kg: float = 1.35
    elemental_p_price_usd_kg: float = 3.7809
    elemental_k_price_usd_kg: float = 1.1444
    fertilizer_price_basis: str = "oxide"
    labor_hourly_wage_usd: float
    custom_seed_prices: Dict[str, float]
    crop_market_prices_usd_t: Dict[str, float] = Field(default_factory=dict)
    regional_crop_yields_t_ha: Dict[str, float] = Field(default_factory=dict)

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
    soilgrids_sand_pct: Optional[float] = None
    soilgrids_silt_pct: Optional[float] = None
    soilgrids_clay_pct: Optional[float] = None
    soilgrids_bulk_density_g_cm3: Optional[float] = None
    soilgrids_total_nitrogen_g_kg: Optional[float] = None
    soilgrids_cfvo_pct: Optional[float] = None
    grace_groundwater_trend: str
    nasa_power_coldest_night_c: Optional[float] = None
    nasa_power_hottest_day_c: Optional[float] = None
    warm_season_et0_mm: Optional[float] = None
    warm_season_precip_mm: Optional[float] = None
    cool_season_et0_mm: Optional[float] = None
    cool_season_precip_mm: Optional[float] = None
    monthly_climatology: Optional[Dict[int, Dict[str, Any]]] = None
    et0_method_used: str = "NASA POWER Precomputed / Benchmark"
    ggcmi_crop_calendar: Optional[Dict[str, Dict[str, int]]] = None

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
    calibrated_soil_moisture_vol_pct: Optional[float] = None
    calibrated_caco3_g_kg: Optional[float] = None
    field_effervescence_hcl_positive: Optional[bool] = None
    calcareous_flag: bool = False
    in_situ_ambient_temp_c: Optional[float] = None
    in_situ_ambient_humidity_pct: Optional[float] = None
    effective_rainfall_annual_mm: float = 620.0
    rain_gauge_monitoring_only_mm: Optional[float] = None
    effective_et0_annual_mm: float = 1200.0
    effective_temp_mean_c: float = 18.5
    compaction_level_tag: str
    irrigation_system: str
    irrigation_method: str = "sprinkler"
    irrigation_efficiency_ea: float = 0.75
    tillage_practice: str
    straw_export_fraction: Optional[float] = None
    crop_calendars: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    max_legal_n_kg_ha: Optional[float] = None
    is_organic: bool
    whitelisted_crops: Optional[List[str]] = None
    blacklisted_crops: List[str] = Field(default_factory=list)

    # 10. Elevation & Terrain
    elevation_mean_m: float
    slope_mean_pct: float
    slope_max_pct: Optional[float] = None
    gloreda_r_factor: Optional[float] = None
    slope_aspect: str
    waterlogging_depression_risk: bool
    erosion_susceptibility_rating: str

    # Quality, Provenance & Multi-Source Layering Tracking
    data_layering_provenance: Dict[str, str] = Field(
        default_factory=dict,
        description="Transparent tracking of how user local ground truth calibrated and layered on top of NASA satellite data"
    )
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
        country_code = p.country_code or "US"
        state_or_province = p.state_or_province

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
        history_crop_calendars = cls._extract_history_calendars(history)
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
        (
            n_price,
            p_price,
            k_price,
            elem_n_price,
            elem_p_price,
            elem_k_price,
            fert_basis,
        ) = cls._resolve_elemental_prices(econ)
        labor_wage = econ.labor_hourly_wage_usd or 22.0
        custom_seed_prices = econ.seed_prices_usd_per_ha or {}
        crop_market_prices = econ.crop_market_prices_usd_t or {}
        regional_crop_yields = econ.regional_crop_yields_t_ha or {}
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
        coldest_night_c: Optional[float] = None
        hottest_day_c: Optional[float] = None
        warm_season_et0_mm: Optional[float] = None
        warm_season_precip_mm: Optional[float] = None
        cool_season_et0_mm: Optional[float] = None
        cool_season_precip_mm: Optional[float] = None
        peak_storm_date = None
        peak_storm_mm = None
        peak_ndvi_date = None

        # Defaults if NASA absent
        t_mean, solar, gdd, et0 = 18.5, 18.0, 1650.0, 1200.0
        rain_ann, rain_grow = 620.0, 403.0
        smap_root, openet_et, ecostress_esi, hls_ndvi = 28.0, 480.0, 0.75, 0.78
        soil_tex, soil_soc, soil_ph, grace_trend = "Clay Loam", 2.15, 6.7, "Stable (Calibrated)"
        raw_soilgrids_soc = 2.15
        raw_soilgrids_ph = 6.7
        raw_soilgrids_tex = "Clay Loam"
        sg_sand_pct: Optional[float] = None
        sg_silt_pct: Optional[float] = None
        sg_clay_pct: Optional[float] = None
        sg_bdod: Optional[float] = None
        sg_total_n_g_kg: Optional[float] = None
        sg_cfvo_pct: Optional[float] = None
        sg_caco3_g_kg: Optional[float] = None
        monthly_climatology: Optional[Dict[int, Dict[str, Any]]] = None
        et0_method_used = "NASA POWER Precomputed / Benchmark"
        ggcmi_crop_calendar: Optional[Dict[str, Dict[str, int]]] = None

        nasa = payload.nasa_data
        if nasa:
            completeness_points += 10.0
            ggcmi_crop_calendar = nasa.ggcmi_crop_calendar

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

                    t_mins = [w.t2m_min_c for w in daily_weather if w.t2m_min_c is not None]
                    t_maxs = [w.t2m_max_c for w in daily_weather if w.t2m_max_c is not None]
                    if t_mins:
                        coldest_night_c = round(min(t_mins), 2)
                    if t_maxs:
                        hottest_day_c = round(max(t_maxs), 2)
                    if nasa.nasa_power.fao56_et0_annual_mm is not None:
                        et0 = nasa.nasa_power.fao56_et0_annual_mm
                else:
                    # Fallback to scalar inputs if timeseries absent
                    t_mean = nasa.nasa_power.t2m_mean_c if nasa.nasa_power.t2m_mean_c is not None else 18.5
                    solar = nasa.nasa_power.solar_radiation_mj_m2 if nasa.nasa_power.solar_radiation_mj_m2 is not None else 18.2
                    gdd = nasa.nasa_power.growing_degree_days_base10 if nasa.nasa_power.growing_degree_days_base10 is not None else 1650.0
                    et0 = nasa.nasa_power.fao56_et0_annual_mm if nasa.nasa_power.fao56_et0_annual_mm is not None else 1220.0
                    if nasa.nasa_power.frost_days_count is not None:
                        frost_days_count = nasa.nasa_power.frost_days_count
                    if nasa.nasa_power.heatwave_days_count is not None:
                        heatwave_days_count = nasa.nasa_power.heatwave_days_count
                    if nasa.nasa_power.longest_dry_spell_days is not None:
                        max_consecutive_dry_days = nasa.nasa_power.longest_dry_spell_days
                    coldest_night_c = nasa.nasa_power.coldest_night_c if nasa.nasa_power.coldest_night_c is not None else nasa.nasa_power.t2m_min_c
                    hottest_day_c = nasa.nasa_power.hottest_day_c if nasa.nasa_power.hottest_day_c is not None else nasa.nasa_power.t2m_max_c
                    warm_season_et0_mm = nasa.nasa_power.warm_season_et0_mm
                    warm_season_precip_mm = nasa.nasa_power.warm_season_precip_mm
                    cool_season_et0_mm = nasa.nasa_power.cool_season_et0_mm
                    cool_season_precip_mm = nasa.nasa_power.cool_season_precip_mm

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

            # Build 12-month agroclimatology (FAO-56 PM primary, Hargreaves-Samani fallback)
            if nasa.nasa_power:
                raw_monthly = cls._build_monthly_weather_normals(nasa.nasa_power, daily_weather, daily_rainfall)
                if raw_monthly:
                    monthly_climatology, et0_method_used = SoilPhysicsEngine.build_monthly_climate_series(
                        monthly_raw=raw_monthly,
                        latitude_deg=lat,
                        elevation_m=p.elevation_m or 200.0,
                    )
                    if nasa.nasa_power.fao56_et0_annual_mm is None or nasa.nasa_power.monthly_normals:
                        et0 = round(sum(m["et0_mm"] for m in monthly_climatology.values()), 1)
                    audit_logs.append(
                        f"Computed 12-month ET0 ({et0:.1f} mm/yr) via {et0_method_used}."
                    )
                elif nasa.nasa_power.fao56_et0_annual_mm is not None:
                    et0_method_used = "NASA POWER Precomputed Scalar"

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
                    sg_sand_pct = top_layer.sand_pct
                    sg_silt_pct = top_layer.silt_pct
                    sg_clay_pct = top_layer.clay_pct
                    sg_bdod = top_layer.bulk_density_g_cm3
                    sg_total_n_g_kg = top_layer.total_nitrogen_g_kg
                    sg_cfvo_pct = top_layer.coarse_fragments_vol_pct
                    sg_caco3_g_kg = top_layer.caco3_g_kg if top_layer.caco3_g_kg is not None else nasa.soilgrids.caco3_g_kg
                    audit_logs.append(f"Extracted {len(soil_depth_layers)} depth-stratified horizon layers from SoilGrids 2.0.")
                else:
                    soil_soc = nasa.soilgrids.soil_organic_carbon_pct or 2.15
                    soil_ph = nasa.soilgrids.soil_ph_h2o or 6.7
                    sg_sand_pct = nasa.soilgrids.sand_percentage
                    sg_silt_pct = nasa.soilgrids.silt_percentage
                    sg_clay_pct = nasa.soilgrids.clay_percentage
                    sg_bdod = nasa.soilgrids.bulk_density_g_cm3
                    sg_total_n_g_kg = nasa.soilgrids.total_nitrogen_g_kg
                    sg_caco3_g_kg = nasa.soilgrids.caco3_g_kg
                soil_tex = nasa.soilgrids.texture_class or "Clay Loam"
                raw_soilgrids_soc = soil_soc
                raw_soilgrids_ph = soil_ph
                raw_soilgrids_tex = soil_tex

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
        # 8. LOCAL USER DATA (IN-SITU SENSORS, LAB TESTS, RAIN GAUGES & MANAGEMENT)
        # ----------------------------------------------------------------------
        usr = payload.local_user_data
        calib_n = None
        calib_ph = None
        calib_soc = None
        calib_comp_psi = None
        calib_moist = None
        calib_caco3_g_kg = sg_caco3_g_kg
        hcl_positive: Optional[bool] = None
        calib_amb_temp: Optional[float] = None
        calib_amb_hum: Optional[float] = None
        effective_rain = rain_ann
        rain_gauge_monitoring_only: Optional[float] = None
        effective_temp = t_mean
        effective_et0 = et0
        comp_tag = "Unmeasured (modeled from bulk density & traffic)"
        irrig_method = "sprinkler"
        irrig_eff_ea = 0.75
        straw_export_frac: Optional[float] = None
        max_legal_n: Optional[float] = None
        merged_crop_calendars: Dict[str, Dict[str, int]] = dict(history_crop_calendars)
        dated_sensor_list: List[DatedInSituSensorReading] = []
        earliest_ts = None
        latest_ts = None
        provenance: Dict[str, str] = {}

        if usr:
            completeness_points += 10.0
            irrig_sys = str(usr.irrigation_system.value if hasattr(usr.irrigation_system, 'value') else usr.irrigation_system)
            irrig_method, irrig_eff_ea = cls._resolve_irrigation_method_efficiency(usr.irrigation_method, irrig_sys)
            tillage = str(usr.tillage_practice.value if hasattr(usr.tillage_practice, 'value') else usr.tillage_practice)
            straw_export_frac = usr.straw_export_fraction
            max_legal_n = usr.max_legal_n_kg_ha
            if usr.crop_calendars:
                merged_crop_calendars.update(usr.crop_calendars)
            is_org = usr.is_organic_certified
            whitelist = usr.preferred_candidate_crops
            blacklist = usr.excluded_crops or []

            # 8A. Process dated in-situ sensor readings
            if usr.dated_sensor_readings:
                sensors_present = True
                dated_sensor_list = sorted(usr.dated_sensor_readings, key=lambda s: s.timestamp)
                earliest_ts = dated_sensor_list[0].timestamp
                latest_ts = dated_sensor_list[-1].timestamp
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
                if latest_reading.soil_moisture_vol_pct is not None:
                    calib_moist = round(latest_reading.soil_moisture_vol_pct, 1)
                if latest_reading.ambient_temperature_c is not None:
                    calib_amb_temp = round(latest_reading.ambient_temperature_c, 2)
                if latest_reading.ambient_humidity_pct is not None:
                    calib_amb_hum = round(latest_reading.ambient_humidity_pct, 1)
                audit_logs.append(
                    f"Fused {len(dated_sensor_list)} dated in-situ sensor readings ({earliest_ts} to {latest_ts})."
                )
            elif usr.portable_sensors:
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
                if sens.soil_moisture_vol_pct is not None:
                    calib_moist = round(sens.soil_moisture_vol_pct, 1)
                audit_logs.append("Fused single-point in-situ sensor reading.")
            else:
                sensors_present = False

            # 8B. Direct user lab tests & ground-truth measurements (layers on top)
            if usr.lab_soil_organic_matter_pct is not None:
                calib_soc = round(usr.lab_soil_organic_matter_pct / 1.724, 2)
                soil_soc = calib_soc
                audit_logs.append(f"User lab soil organic matter: {usr.lab_soil_organic_matter_pct}% (SOC: {calib_soc}%) layered on top of SoilGrids.")
            if usr.lab_soil_ph is not None:
                calib_ph = round(usr.lab_soil_ph, 2)
                soil_ph = calib_ph
            if usr.lab_topsoil_nitrogen_ppm is not None:
                calib_n = round(usr.lab_topsoil_nitrogen_ppm * 2.24, 1)
            if usr.penetrometer_compaction_psi is not None:
                calib_comp_psi = usr.penetrometer_compaction_psi
            if usr.in_situ_soil_moisture_vol_pct is not None:
                calib_moist = round(usr.in_situ_soil_moisture_vol_pct, 1)
            if usr.lab_caco3_g_kg is not None:
                calib_caco3_g_kg = round(usr.lab_caco3_g_kg, 1)
                audit_logs.append(f"User lab CaCO3 equivalent: {calib_caco3_g_kg} g/kg layered into k2 mineralization buffer.")
            if usr.field_effervescence_hcl_positive is not None:
                hcl_positive = usr.field_effervescence_hcl_positive

            # 8C. On-farm rain gauge & weather station overrides
            if usr.on_farm_annual_rainfall_mm is not None:
                if usr.on_farm_rain_gauge_years is not None and usr.on_farm_rain_gauge_years < 10:
                    rain_gauge_monitoring_only = round(usr.on_farm_annual_rainfall_mm, 1)
                    audit_logs.append(
                        f"User on-farm rain gauge ({rain_gauge_monitoring_only} mm over {usr.on_farm_rain_gauge_years} yr < 10 yr threshold) "
                        f"stored for monitoring only; retained long-term normals ({effective_rain} mm)."
                    )
                else:
                    effective_rain = round(usr.on_farm_annual_rainfall_mm, 1)
                    rain_grow = round(effective_rain * 0.65, 1)
                    yrs_note = f"{usr.on_farm_rain_gauge_years} yr verified" if usr.on_farm_rain_gauge_years else "record length unverified"
                    audit_logs.append(
                        f"User on-farm rain gauge ({effective_rain} mm, {yrs_note}) layered on top of NASA GPM IMERG ({rain_ann} mm)."
                    )
            if usr.on_farm_mean_temperature_c is not None:
                effective_temp = round(usr.on_farm_mean_temperature_c, 2)
                audit_logs.append(f"User on-farm weather station temp: {effective_temp}°C layered on top of NASA POWER ({t_mean}°C).")
            if usr.on_farm_annual_et0_mm is not None:
                effective_et0 = round(usr.on_farm_annual_et0_mm, 1)
                audit_logs.append(f"User on-farm ET0: {effective_et0} mm layered on top of NASA POWER ({et0} mm).")

            # 8D. Compaction status tag
            if calib_comp_psi is not None:
                if calib_comp_psi > 300:
                    comp_tag = f"Severe Hardpan ({calib_comp_psi:.0f} PSI - Root barrier)"
                elif calib_comp_psi > 200:
                    comp_tag = f"Moderate Plowpan ({calib_comp_psi:.0f} PSI)"
                else:
                    comp_tag = f"Optimal Tilth ({calib_comp_psi:.0f} PSI)"
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
        slope_max_pct: Optional[float] = None
        gloreda_r_factor: Optional[float] = None
        if topo:
            completeness_points += 10.0
            elev_mean = topo.elevation_mean_m or 280.0
            slope_mean = topo.slope_mean_pct or 2.2
            slope_max_pct = topo.slope_max_pct
            gloreda_r_factor = topo.gloreda_r_factor
            aspect = str(topo.aspect.value if hasattr(topo.aspect, 'value') else topo.aspect)
            waterlogging = bool(topo.waterlogging_depression_present)
            erosion_stat = topo.soil_erosion_susceptibility or ("Low" if slope_mean < 3.0 else "Moderate")
            audit_logs.append(f"Parsed elevation metrics: Mean Elevation {elev_mean:.1f}m, Slope {slope_mean:.1f}%, Aspect: {aspect}.")
        else:
            elev_mean, slope_mean, aspect, waterlogging, erosion_stat = 250.0, 2.0, "Flat / Level Terrain", False, "Low"
            audit_logs.append("Elevation maps omitted; applied regional topographic elevation (250m, 2% slope).")

        # Ground RTK / drone survey overrides (layer on top of DEM)
        if usr and usr.survey_elevation_m is not None:
            elev_mean = round(usr.survey_elevation_m, 1)
            audit_logs.append(f"User surveyed elevation: {elev_mean}m layered on top of SRTM DEM.")
        if usr and usr.survey_slope_pct is not None:
            slope_mean = round(usr.survey_slope_pct, 2)
            slope_max_pct = max(slope_max_pct or 0.0, slope_mean) if slope_max_pct is not None else None
            audit_logs.append(f"User surveyed slope: {slope_mean}% layered on top of SRTM DEM.")

        calcareous_flag = bool(
            (calib_caco3_g_kg is not None and calib_caco3_g_kg > 10.0)
            or hcl_positive is True
            or (soil_ph >= 7.5 and calib_caco3_g_kg is None)
        )
        if soil_ph >= 7.5 and calib_caco3_g_kg is None:
            audit_logs.append(
                f"Topsoil pH {soil_ph:.2f} >= 7.5 indicates potentially calcareous soil (SoilGrids v2.0 omits CaCO3); "
                "defaulting CaCO3 = 0 g/kg pending lab carbonate or field dilute-HCl verification."
            )

        # ----------------------------------------------------------------------
        # 10. MULTI-SOURCE DATA PROVENANCE & LAYERING AUDIT
        # ----------------------------------------------------------------------
        provenance["soil_texture"] = (
            f"User Local Lab Override '{effective_soil_type}' (overrode NASA SoilGrids '{soil_tex}')"
            if (usr and usr.soil_type) else f"NASA SoilGrids 2.0 Baseline '{effective_soil_type}'"
        )
        provenance["soil_organic_carbon"] = (
            f"User Lab Ground Truth ({calib_soc:.2f}% SOC) calibrated on top of NASA SoilGrids ({raw_soilgrids_soc:.2f}%)"
            if (calib_soc is not None and (usr and (usr.lab_soil_organic_matter_pct or usr.dated_sensor_readings or usr.portable_sensors)))
            else f"NASA SoilGrids Satellite Baseline ({raw_soilgrids_soc:.2f}% SOC)"
        )
        provenance["soil_compaction"] = (
            f"User Cone Penetrometer ({calib_comp_psi:.0f} PSI - {comp_tag}) ground-truthed on field"
            if calib_comp_psi is not None
            else "Unmeasured (modeled from machinery passes & soil texture; verify with spade/penetrometer)"
        )
        provenance["rootzone_moisture"] = (
            f"User In-Situ Ground Probe ({calib_moist:.1f}%) calibrated on top of NASA SMAP L4 ({smap_root:.1f}%)"
            if calib_moist is not None else f"NASA SMAP L4 Satellite Baseline ({smap_root:.1f}%)"
        )
        if usr and usr.on_farm_annual_rainfall_mm is not None and (
            usr.on_farm_rain_gauge_years is None or usr.on_farm_rain_gauge_years >= 10
        ):
            yrs_label = f"{usr.on_farm_rain_gauge_years} yr" if usr.on_farm_rain_gauge_years else "record length unspecified"
            provenance["annual_rainfall"] = (
                f"User On-Farm Rain Gauge ({effective_rain:.1f} mm; {yrs_label}) layered on top of NASA GPM IMERG ({rain_ann:.1f} mm)"
            )
        elif rain_gauge_monitoring_only is not None:
            provenance["annual_rainfall"] = (
                f"NASA GPM IMERG / Long-Term Normals retained ({effective_rain:.1f} mm); "
                f"on-farm gauge ({rain_gauge_monitoring_only:.1f} mm, {usr.on_farm_rain_gauge_years} yr < 10 yr) logged for monitoring only"
            )
        else:
            provenance["annual_rainfall"] = f"NASA GPM IMERG Satellite Baseline ({rain_ann:.1f} mm)"

        provenance["et0_methodology"] = et0_method_used
        provenance["irrigation_efficiency"] = f"{irrig_method} (e_a = {irrig_eff_ea:.2f})"
        if calib_caco3_g_kg is not None:
            provenance["soil_carbonate"] = f"Calibrated CaCO3 = {calib_caco3_g_kg:.1f} g/kg"
        elif soil_ph >= 7.5:
            provenance["soil_carbonate"] = (
                f"Flagged potentially calcareous (pH {soil_ph:.2f} >= 7.5; SoilGrids omits CaCO3 -> assume 0 g/kg pending HCl/lab check)"
            )
        else:
            provenance["soil_carbonate"] = "Non-calcareous assumption (0 g/kg CaCO3)"
        provenance["temperature_and_et0"] = (
            f"User On-Farm Weather Station ({effective_temp:.1f}°C, {effective_et0:.0f} mm ET0) calibrated on top of NASA POWER"
            if (usr and (usr.on_farm_mean_temperature_c is not None or usr.on_farm_annual_et0_mm is not None))
            else f"NASA POWER Agroclimatology Baseline ({t_mean:.1f}°C, {et0:.0f} mm ET0)"
        )
        provenance["elevation_and_slope"] = (
            f"User RTK/Drone Survey ({elev_mean:.1f} m, {slope_mean:.1f}% slope) calibrated on top of NASA SRTM DEM"
            if (usr and (usr.survey_elevation_m is not None or usr.survey_slope_pct is not None))
            else f"NASA SRTM DEM Satellite Baseline ({elev_mean:.1f} m, {slope_mean:.1f}% slope)"
        )
        if whitelist or blacklist:
            provenance["crop_preferences"] = f"Farmer Whitelist: {whitelist or 'All'} | Blacklist: {blacklist or 'None'}"
        if is_org:
            provenance["organic_certification"] = "Strict Organic Protocol Enforced (Synthetic NPK disallowed)"

        completeness_pct = round((completeness_points / max_points) * 100.0, 1)

        return ParsedFieldNormalized(
            parcel_id=parcel_id,
            field_name=field_name,
            country_code=country_code,
            state_or_province=state_or_province,
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
            elemental_n_price_usd_kg=elem_n_price,
            elemental_p_price_usd_kg=elem_p_price,
            elemental_k_price_usd_kg=elem_k_price,
            fertilizer_price_basis=fert_basis,
            labor_hourly_wage_usd=labor_wage,
            custom_seed_prices=custom_seed_prices,
            crop_market_prices_usd_t=crop_market_prices,
            regional_crop_yields_t_ha=regional_crop_yields,
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
            soilgrids_texture_class=raw_soilgrids_tex,
            soilgrids_organic_carbon_pct=raw_soilgrids_soc,
            soilgrids_ph=raw_soilgrids_ph,
            soilgrids_sand_pct=sg_sand_pct,
            soilgrids_silt_pct=sg_silt_pct,
            soilgrids_clay_pct=sg_clay_pct,
            soilgrids_bulk_density_g_cm3=sg_bdod,
            soilgrids_total_nitrogen_g_kg=sg_total_n_g_kg,
            soilgrids_cfvo_pct=sg_cfvo_pct,
            grace_groundwater_trend=grace_trend,
            nasa_power_coldest_night_c=coldest_night_c,
            nasa_power_hottest_day_c=hottest_day_c,
            warm_season_et0_mm=warm_season_et0_mm,
            warm_season_precip_mm=warm_season_precip_mm,
            cool_season_et0_mm=cool_season_et0_mm,
            cool_season_precip_mm=cool_season_precip_mm,
            monthly_climatology=monthly_climatology,
            et0_method_used=et0_method_used,
            ggcmi_crop_calendar=ggcmi_crop_calendar,
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
            calibrated_soil_moisture_vol_pct=calib_moist,
            calibrated_caco3_g_kg=calib_caco3_g_kg,
            field_effervescence_hcl_positive=hcl_positive,
            calcareous_flag=calcareous_flag,
            in_situ_ambient_temp_c=calib_amb_temp,
            in_situ_ambient_humidity_pct=calib_amb_hum,
            effective_rainfall_annual_mm=effective_rain,
            rain_gauge_monitoring_only_mm=rain_gauge_monitoring_only,
            effective_et0_annual_mm=effective_et0,
            effective_temp_mean_c=effective_temp,
            compaction_level_tag=comp_tag,
            irrigation_system=irrig_sys,
            irrigation_method=irrig_method,
            irrigation_efficiency_ea=irrig_eff_ea,
            tillage_practice=tillage,
            straw_export_fraction=straw_export_frac,
            crop_calendars=merged_crop_calendars,
            max_legal_n_kg_ha=max_legal_n,
            is_organic=is_org,
            whitelisted_crops=whitelist,
            blacklisted_crops=blacklist,
            elevation_mean_m=elev_mean,
            slope_mean_pct=slope_mean,
            slope_max_pct=slope_max_pct,
            gloreda_r_factor=gloreda_r_factor,
            slope_aspect=aspect,
            waterlogging_depression_risk=waterlogging,
            erosion_susceptibility_rating=erosion_stat,
            data_layering_provenance=provenance,
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
                    # ISRIC units: soc is dg/kg (divide by 100 for %), clay/sand/silt is g/kg (divide by 10 for %),
                    # ph is pH*10, bdod is cg/cm3 (divide by 100 for g/cm3), cfvo is cm3/dm3 (divide by 10 for vol%),
                    # nitrogen is cg/kg (divide by 100 for g/kg)
                    soc_pct = round(vals.get("soc", 0) / 100.0, 2) if "soc" in vals else None
                    clay_pct = round(vals.get("clay", 0) / 10.0, 1) if "clay" in vals else None
                    sand_pct = round(vals.get("sand", 0) / 10.0, 1) if "sand" in vals else None
                    silt_pct = round(vals.get("silt", 0) / 10.0, 1) if "silt" in vals else None
                    ph_val = round(vals.get("phh2o", 0) / 10.0, 2) if "phh2o" in vals else None
                    bd_val = round(vals.get("bdod", 0) / 100.0, 2) if "bdod" in vals else None
                    n_val = round(vals.get("nitrogen", 0) / 100.0, 3) if "nitrogen" in vals else None
                    cfvo_val = round(vals.get("cfvo", 0) / 10.0, 1) if "cfvo" in vals else None
                    caco3_val = round(vals.get("caco3", 0), 1) if "caco3" in vals else None

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
                            bulk_density_g_cm3=bd_val,
                            total_nitrogen_g_kg=n_val,
                            coarse_fragments_vol_pct=cfvo_val,
                            caco3_g_kg=caco3_val,
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

    @staticmethod
    def _resolve_elemental_prices(econ: Any) -> Tuple[float, float, float, float, float, float, str]:
        """Converts oxide/product fertilizer prices cleanly to elemental N, P, K ($/kg)."""
        basis = (getattr(econ, "fertilizer_price_basis", None) or "oxide").lower()

        if getattr(econ, "urea_price_usd_ton", None) is not None:
            n_price = round(econ.urea_price_usd_ton / 460.0, 4)
            elem_n = n_price
        else:
            n_price = econ.nitrogen_price_usd_kg if econ.nitrogen_price_usd_kg is not None else 1.35
            elem_n = n_price

        if getattr(econ, "tsp_price_usd_ton", None) is not None:
            elem_p = round(econ.tsp_price_usd_ton / 201.0, 4)
            p_price = econ.phosphorus_price_usd_kg if econ.phosphorus_price_usd_kg is not None else round(elem_p * 0.4364, 4)
        else:
            p_price = econ.phosphorus_price_usd_kg if econ.phosphorus_price_usd_kg is not None else 1.65
            elem_p = round(p_price, 4) if basis == "elemental" else round(p_price / 0.4364, 4)

        if getattr(econ, "kcl_price_usd_ton", None) is not None:
            elem_k = round(econ.kcl_price_usd_ton / 498.0, 4)
            k_price = econ.potassium_price_usd_kg if econ.potassium_price_usd_kg is not None else round(elem_k * 0.8301, 4)
        else:
            k_price = econ.potassium_price_usd_kg if econ.potassium_price_usd_kg is not None else 0.95
            elem_k = round(k_price, 4) if basis == "elemental" else round(k_price / 0.8301, 4)

        return n_price, p_price, k_price, elem_n, elem_p, elem_k, basis

    @staticmethod
    def _resolve_irrigation_method_efficiency(
        explicit_method: Optional[str],
        irrig_system_label: str,
    ) -> Tuple[str, float]:
        """Maps installed irrigation technology to canonical method and FAO-56 application efficiency."""
        if explicit_method:
            m = explicit_method.strip().lower()
            if "drip" in m or "trickle" in m or "subsurface" in m:
                return "drip", 0.90
            if "surface" in m or "flood" in m or "furrow" in m or "basin" in m:
                return "surface", 0.60
            if "rain" in m or "none" in m:
                return "rainfed", 0.75
            return "sprinkler", 0.75

        s = (irrig_system_label or "").lower()
        if "drip" in s or "subsurface" in s:
            return "drip", 0.90
        if "flood" in s or "furrow" in s or "surface" in s:
            return "surface", 0.60
        if "rain" in s or "none" in s:
            return "rainfed", 0.75
        return "sprinkler", 0.75

    @staticmethod
    def _extract_history_calendars(history: List[Any]) -> Dict[str, Dict[str, int]]:
        """Builds Tier 1 sowing/harvest DOY calendars from grower harvest history dates."""
        name_to_key = {
            "corn": "corn", "maize": "corn",
            "soybean": "soybeans", "soy": "soybeans",
            "wheat": "winter_wheat",
            "alfalfa": "alfalfa", "clover": "alfalfa",
            "tomato": "processing_tomatoes",
            "sunflower": "sunflowers",
            "sorghum": "grain_sorghum",
            "peas": "field_peas", "pea": "field_peas",
            "canola": "canola", "rapeseed": "canola",
            "radish": "daikon_radish_cover", "daikon": "daikon_radish_cover",
            "bell pepper": "bell_peppers", "pepper": "bell_peppers",
            "spinach": "spinach",
        }
        calendars: Dict[str, Dict[str, int]] = {}
        for h in history:
            if not getattr(h, "planting_date", None) or not getattr(h, "harvest_date", None):
                continue
            try:
                p_dt = date.fromisoformat(str(h.planting_date)[:10])
                h_dt = date.fromisoformat(str(h.harvest_date)[:10])
            except ValueError:
                continue
            crop_lower = (h.crop_name or "").lower()
            matched_key = next((k for pat, k in name_to_key.items() if pat in crop_lower), None)
            if matched_key:
                calendars[matched_key] = {
                    "sowing_doy": p_dt.timetuple().tm_yday,
                    "harvest_doy": h_dt.timetuple().tm_yday,
                    "sowing_month": p_dt.month,
                    "harvest_month": h_dt.month,
                }
        return calendars

    @classmethod
    def _build_monthly_weather_normals(
        cls,
        power: Any,
        daily_weather: List[DatedDailyWeatherRecord],
        daily_rainfall: List[DatedPrecipitationObservation],
    ) -> Optional[Dict[int, Dict[str, Any]]]:
        """Extracts 12-month normals from NASA POWER monthly_normals or multi-month daily timeseries."""
        if getattr(power, "monthly_normals", None):
            norm_out: Dict[int, Dict[str, Any]] = {}
            for k, v in power.monthly_normals.items():
                try:
                    m_idx = int(k)
                except (TypeError, ValueError):
                    continue
                if 1 <= m_idx <= 12 and isinstance(v, dict):
                    norm_out[m_idx] = dict(v)
            if len(norm_out) == 12:
                return norm_out

        if not daily_weather:
            return None

        by_month: Dict[int, Dict[str, List[float]]] = {m: {} for m in range(1, 13)}
        year_month_precip: Dict[Tuple[int, int], float] = {}
        for w in daily_weather:
            try:
                dt = date.fromisoformat(str(w.date)[:10])
            except ValueError:
                continue
            m = dt.month
            bucket = by_month[m]
            for attr, key in [
                ("t2m_c", "t2m_c"),
                ("t2m_max_c", "t2m_max_c"),
                ("t2m_min_c", "t2m_min_c"),
                ("solar_radiation_mj_m2", "solar_radiation_mj_m2"),
                ("relative_humidity_pct", "relative_humidity_pct"),
                ("wind_speed_2m_ms", "wind_speed_2m_ms"),
                ("dew_point_c", "dew_point_c"),
                ("surface_pressure_kpa", "surface_pressure_kpa"),
            ]:
                val = getattr(w, attr, None)
                if val is not None:
                    bucket.setdefault(key, []).append(float(val))
            if w.precipitation_mm is not None:
                ym = (dt.year, m)
                year_month_precip[ym] = year_month_precip.get(ym, 0.0) + float(w.precipitation_mm)

        # Incorporate GPM IMERG monthly rain sums if available
        gpm_ym: Dict[Tuple[int, int], float] = {}
        for r in daily_rainfall:
            try:
                dt = date.fromisoformat(str(r.date)[:10])
            except ValueError:
                continue
            ym = (dt.year, dt.month)
            gpm_ym[ym] = gpm_ym.get(ym, 0.0) + float(r.precipitation_mm)

        observed_months = [m for m in range(1, 13) if by_month[m]]
        if len(observed_months) < 10:
            return None

        result: Dict[int, Dict[str, Any]] = {}
        for m in range(1, 13):
            b = by_month[m]
            if not b:
                # Interpolate missing month from neighbors if 10-11 months observed
                prev_m = ((m - 2) % 12) + 1
                next_m = (m % 12) + 1
                b = by_month.get(prev_m) or by_month.get(next_m) or {}
            m_dict: Dict[str, Any] = {}
            for key, vals in b.items():
                if vals:
                    m_dict[key] = round(sum(vals) / len(vals), 3)
            gpm_vals = [v for (yr, mo), v in gpm_ym.items() if mo == m]
            pwr_vals = [v for (yr, mo), v in year_month_precip.items() if mo == m]
            if gpm_vals:
                m_dict["precip_mm"] = round(sum(gpm_vals) / len(gpm_vals), 2)
            elif pwr_vals:
                m_dict["precip_mm"] = round(sum(pwr_vals) / len(pwr_vals), 2)
            result[m] = m_dict
        return result
