"""
Comprehensive Ingestion and Parser Schemas for Field Planning.
Covers the core input domains:
1. Parcel Info (cadastral, boundary GeoJSON, coordinates, acreage, baseline soil type)
2. Harvest & Crop History (flexible 1-5 past years: yields, dates, nutrients, irrigation)
3. Seed / Water / Oil Prices & Seed Data:
   - Input costs: diesel, electricity, water m3, elemental NPK, labor
   - Seed varieties with:
     * Greenhouse need ('Open Field Only', 'Open Field or Greenhouse Compatible', 'Greenhouse Recommended', 'Greenhouse Required')
     * Resistance to extreme events (drought, flood/waterlogging, high winds/lodging, frost, extreme heat, salinity)
4. NASA Data (Official raw database responses & full dated daily/scene timeseries):
   - NASA POWER: Full daily weather series (T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, ALLSKY, RH2M, WS2M) with dates
   - GPM IMERG: Full daily precipitation observation series with dates and storm tracking
   - NASA SMAP: Daily surface (0-5cm) & root-zone (0-100cm) volumetric moisture with dates
   - OpenET: Actual evapotranspiration (ETa) daily/monthly timeseries with dates
   - ECOSTRESS: Canopy surface temperature and Evaporative Stress Index (ESI) scenes with timestamps
   - HLS (Landsat + Sentinel): Multispectral NDVI, NDRE, NDWI overpasses with dates
   - SoilGrids 2.0: Depth-stratified soil horizons (0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm)
   - GRACE: Monthly deep aquifer liquid water equivalent (LWE) anomaly timeseries
5. Long-Term Weather Projections (optional: climate scenarios, temp shifts, precipitation anomalies)
6. Local User Data:
   - In-situ portable sensor measurements with explicit date/time signatures
   - Soil type override, irrigation infrastructure, tillage system, management constraints
7. Elevation Maps (DEM, slope %, aspect, topographic wetness index, waterlogging low spots)
"""

from typing import Dict, List, Optional, Any, Union
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator


# ==============================================================================
# STANDARD SOIL TYPES & CLASSIFICATIONS
# ==============================================================================

class SoilTypeEnum(str, Enum):
    CLAY = "Clay"
    CLAY_LOAM = "Clay Loam"
    SILTY_CLAY = "Silty Clay"
    SILTY_CLAY_LOAM = "Silty Clay Loam"
    SILT_LOAM = "Silt Loam"
    SILT = "Silt"
    LOAM = "Loam"
    SANDY_CLAY = "Sandy Clay"
    SANDY_CLAY_LOAM = "Sandy Clay Loam"
    SANDY_LOAM = "Sandy Loam"
    LOAMY_SAND = "Loamy Sand"
    SAND = "Sand"
    PEAT = "Peat / Organic Muck"
    CHERNOZEM = "Chernozem / Mollisol (Black Soil)"
    CALCAREOUS = "Calcareous / Chalky Soil"
    ALLUVIAL = "Alluvial / Riverbed Soil"


# ==============================================================================
# 1. PARCEL INFO
# ==============================================================================

class OwnershipType(str, Enum):
    OWNED = "Owned"
    LEASED = "Leased"
    COMMUNAL = "Communal / Shared"
    PUBLIC = "Public / State"


class ParcelInfoInput(BaseModel):
    """Geospatial boundary, cadastral identifiers, soil classification, and land legal attributes."""
    parcel_id: str = Field(..., description="Unique internal or farm parcel identifier (e.g. 'PRCL-2026-08')")
    field_name: Optional[str] = Field(None, description="Human-readable field name (e.g. 'North 40 Valley')")
    cadastral_number: Optional[str] = Field(None, description="Official government land registry / cadastral ID")
    country_code: Optional[str] = Field(default="US", description="ISO 2-letter country code")
    state_or_province: Optional[str] = Field(None, description="State, province, or region")

    # Geospatial location
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Centroid Latitude (WGS84)")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Centroid Longitude (WGS84)")
    boundary_geojson: Optional[Dict[str, Any]] = Field(
        None, description="GeoJSON Geometry (Polygon or MultiPolygon) defining field borders"
    )

    # Area
    area_hectares: Optional[float] = Field(None, gt=0.0, description="Total field area in hectares")
    area_acres: Optional[float] = Field(None, gt=0.0, description="Field area in acres (auto-converted if provided)")

    # Baseline Soil Type
    soil_type: Optional[str] = Field(
        None,
        description="Declared soil type or classification (e.g. 'Silt Loam', 'Clay Loam', 'Loam', 'Chernozem')"
    )

    # Legal & Water Rights
    ownership_type: Optional[OwnershipType] = Field(default=OwnershipType.OWNED)
    annual_water_quota_m3: Optional[float] = Field(None, ge=0.0, description="Legal water allocation limit (m^3/year)")

    @model_validator(mode="after")
    def harmonize_area_and_coordinates(self) -> "ParcelInfoInput":
        if self.area_hectares is None and self.area_acres is not None:
            self.area_hectares = round(self.area_acres * 0.404686, 2)
        elif self.area_hectares is not None and self.area_acres is None:
            self.area_acres = round(self.area_hectares * 2.47105, 2)

        if (self.latitude is None or self.longitude is None) and self.boundary_geojson:
            try:
                coords = self.boundary_geojson.get("coordinates", [])
                if coords:
                    ring = coords[0] if isinstance(coords[0][0], (list, tuple)) else coords
                    lons = [pt[0] for pt in ring]
                    lats = [pt[1] for pt in ring]
                    if lons and lats:
                        self.longitude = round(sum(lons) / len(lons), 6)
                        self.latitude = round(sum(lats) / len(lats), 6)
            except Exception:
                pass
        return self


# ==============================================================================
# 2. LAST COUPLE YEARS HARVEST & CROP INFORMATION (MAX 5 FLEXIBLE)
# ==============================================================================

class SeasonalCropRecord(BaseModel):
    """Detailed observation of a single historical cultivation season."""
    year: int = Field(..., ge=1990, le=2035, description="Harvest calendar year")
    season: Optional[str] = Field("Main Season", description="Growing season: 'Main Season', 'Spring', 'Fall', 'Winter Cover'")
    crop_name: str = Field(..., description="Crop planted (e.g. 'Corn (Maize)', 'Soybeans', 'Winter Wheat')")
    variety_or_hybrid: Optional[str] = Field(None, description="Specific seed variety, GMO trait, or hybrid tag")
    botanical_family: Optional[str] = Field(None, description="Family (e.g. 'Poaceae', 'Fabaceae', 'Solanaceae')")

    # Harvest & Yield
    yield_harvested_tons_ha: Optional[float] = Field(None, ge=0.0, description="Harvested crop yield (metric tons / hectare)")
    yield_harvested_bushels_acre: Optional[float] = Field(None, ge=0.0, description="Yield in bushels/acre (optional)")
    planting_date: Optional[str] = Field(None, description="ISO Date YYYY-MM-DD of seeding")
    harvest_date: Optional[str] = Field(None, description="ISO Date YYYY-MM-DD of harvest")

    # Nutrients & Amendments Applied
    nitrogen_applied_kg_ha: Optional[float] = Field(None, ge=0.0, description="Synthetic or organic N applied (kg/ha)")
    phosphorus_applied_kg_ha: Optional[float] = Field(None, ge=0.0, description="P2O5 applied (kg/ha)")
    potassium_applied_kg_ha: Optional[float] = Field(None, ge=0.0, description="K2O applied (kg/ha)")
    irrigation_applied_mm: Optional[float] = Field(None, ge=0.0, description="Total depth of irrigation applied (mm)")
    soil_amendments: Optional[List[str]] = Field(
        None, description="Applied amendments: 'Lime (CaCO3)', 'Composted Manure', 'Biochar', 'Gypsum'"
    )

    # Agronomic & Financial Notes
    pest_disease_incidents: Optional[List[str]] = Field(
        None, description="Notable pest/pathogen outbreaks: 'Corn Borer', 'Soybean Cyst Nematode', 'Rust'"
    )
    gross_revenue_usd_ha: Optional[float] = Field(None, ge=0.0, description="Realized revenue per hectare")


class HarvestAndCropHistoryInput(BaseModel):
    """Flexible history of past harvests (max 5 years)."""
    historical_seasons: List[SeasonalCropRecord] = Field(
        ...,
        description="Chronological past cultivation records (minimum 1, maximum 5 years recommended)"
    )

    @field_validator("historical_seasons")
    @classmethod
    def validate_historical_range(cls, v: List[SeasonalCropRecord]) -> List[SeasonalCropRecord]:
        if len(v) == 0:
            raise ValueError("At least 1 historical season must be provided.")
        if len(v) > 10:
            raise ValueError("A maximum of 10 historical seasons is accepted (5 years recommended).")
        return sorted(v, key=lambda s: s.year)


# ==============================================================================
# 3. SEED DATA: GREENHOUSE NEED & RESISTANCE TO EXTREME EVENTS
# ==============================================================================

class GreenhouseRequirement(str, Enum):
    OPEN_FIELD_ONLY = "Open Field Only"
    OPEN_FIELD_OR_GREENHOUSE = "Open Field or Greenhouse Compatible"
    GREENHOUSE_RECOMMENDED = "Greenhouse Recommended"
    GREENHOUSE_REQUIRED = "Greenhouse Required (Protected Cultivation)"


class ExtremeResistanceLevel(str, Enum):
    VERY_LOW = "Very Low (Highly Susceptible)"
    LOW = "Low"
    MODERATE = "Moderate (Average Resilience)"
    HIGH = "High"
    VERY_HIGH = "Very High (Extreme Tolerance)"


class ExtremeEventResistance(BaseModel):
    """
    Agronomic resistance and tolerance metrics to severe abiotic weather shocks:
    Drought, flood/waterlogging, high winds/lodging, frost/freezing, and extreme heat.
    """
    drought_resistance: ExtremeResistanceLevel = Field(
        default=ExtremeResistanceLevel.MODERATE,
        description="Resilience against soil moisture deficits and prolonged dry spells"
    )
    drought_tolerance_score: float = Field(
        default=3.0, ge=1.0, le=5.0,
        description="Quantitative drought rating (1.0 = wilts and dies quickly, 5.0 = arid/deep taproot adapted)"
    )

    flood_waterlogging_resistance: ExtremeResistanceLevel = Field(
        default=ExtremeResistanceLevel.MODERATE,
        description="Resilience against root-zone hypoxia, ponding, standing water, and anaerobic saturation"
    )
    flood_tolerance_score: float = Field(
        default=3.0, ge=1.0, le=5.0,
        description="Quantitative flood rating (1.0 = root rot in 24h, 5.0 = wetland/aerenchyma adapted)"
    )

    wind_lodging_resistance: ExtremeResistanceLevel = Field(
        default=ExtremeResistanceLevel.MODERATE,
        description="Resistance against gale winds, stem snapping, root uprooting, and crop lodging"
    )
    wind_tolerance_score: float = Field(
        default=3.0, ge=1.0, le=5.0,
        description="Quantitative wind/lodging score (1.0 = tall brittle stalks lodging easily, 5.0 = prostrate or storm-resilient)"
    )

    frost_cold_resistance: ExtremeResistanceLevel = Field(
        default=ExtremeResistanceLevel.MODERATE,
        description="Resilience to sudden late spring frost, early autumn freezes, or harsh overwintering temperatures"
    )
    frost_tolerance_score: float = Field(
        default=3.0, ge=1.0, le=5.0,
        description="Quantitative frost score (1.0 = tender killed at 0°C, 5.0 = survives below -20°C dormancy)"
    )

    extreme_heat_resistance: ExtremeResistanceLevel = Field(
        default=ExtremeResistanceLevel.MODERATE,
        description="Resilience to canopy scorching, pollen sterilization, and heat shock above 35°C"
    )
    heat_tolerance_score: float = Field(
        default=3.0, ge=1.0, le=5.0,
        description="Quantitative heat score (1.0 = flower abortion at 30°C, 5.0 = high C4/tropical heat performance)"
    )

    salinity_tolerance: Optional[str] = Field(
        default="Moderate",
        description="Tolerance to soil electrical conductivity (EC) / salt accumulation: 'Low', 'Moderate', 'High'"
    )
    extreme_event_notes: Optional[str] = Field(
        default=None,
        description="Breeder or field observation notes on extreme event resilience"
    )


class SeedDataInput(BaseModel):
    """Comprehensive seed variety specification."""
    crop_name: str = Field(..., description="Target crop (e.g. 'Corn (Maize)', 'Processing Tomatoes', 'Winter Wheat')")
    variety_or_hybrid_name: Optional[str] = Field(
        None, description="Commercial variety, hybrid code, or GMO trait (e.g. 'Pioneer P1197AM', 'Sub1 Rice')"
    )
    seed_cost_usd_per_ha: Optional[float] = Field(
        None, ge=0.0, description="Cost of seed per hectare ($/ha)"
    )
    seed_cost_usd_per_kg: Optional[float] = Field(
        None, ge=0.0, description="Cost of seed per kilogram ($/kg)"
    )
    seeding_rate_kg_ha: Optional[float] = Field(
        None, ge=0.0, description="Standard seeding density (kg/ha)"
    )

    greenhouse_need: GreenhouseRequirement = Field(
        default=GreenhouseRequirement.OPEN_FIELD_ONLY,
        description="Cultivation environment requirement"
    )
    can_grow_in_greenhouse: bool = Field(
        default=False,
        description="True if variety can be cultivated inside protected greenhouse or tunnel structure"
    )
    requires_greenhouse: bool = Field(
        default=False,
        description="True if variety strictly requires a greenhouse/climate-controlled structure"
    )

    extreme_event_resistance: ExtremeEventResistance = Field(
        default_factory=ExtremeEventResistance,
        description="Physiological resistance profile against drought, floods, wind storms, frost, and extreme heat"
    )

    @model_validator(mode="after")
    def sync_greenhouse_flags(self) -> "SeedDataInput":
        if self.greenhouse_need == GreenhouseRequirement.GREENHOUSE_REQUIRED:
            self.requires_greenhouse = True
            self.can_grow_in_greenhouse = True
        elif self.greenhouse_need in (GreenhouseRequirement.GREENHOUSE_RECOMMENDED, GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE):
            self.can_grow_in_greenhouse = True
        elif self.greenhouse_need == GreenhouseRequirement.OPEN_FIELD_ONLY:
            self.requires_greenhouse = False
            self.can_grow_in_greenhouse = False
        return self


# ==============================================================================
# 4. ECONOMIC PRICES (SEED, WATER, OIL, FERTILIZER)
# ==============================================================================

class EconomicPricesInput(BaseModel):
    """Market prices for agricultural inputs and consumables."""
    diesel_fuel_price_usd_liter: float = Field(
        default=1.15, gt=0.0, description="Agricultural off-road diesel fuel price ($/liter)"
    )
    engine_lubricant_oil_price_usd_liter: Optional[float] = Field(
        default=5.50, gt=0.0, description="Engine/hydraulic machinery oil price ($/liter)"
    )
    irrigation_water_price_usd_m3: float = Field(
        default=0.08, ge=0.0, description="Irrigation water tariff per cubic meter ($/m^3)"
    )
    electricity_pumping_tariff_usd_kwh: Optional[float] = Field(
        default=0.12, ge=0.0, description="Grid electricity price for irrigation pump motors ($/kWh)"
    )
    nitrogen_price_usd_kg: Optional[float] = Field(
        default=1.35, gt=0.0, description="Cost of pure elemental Nitrogen equivalent ($/kg N)"
    )
    phosphorus_price_usd_kg: Optional[float] = Field(
        default=1.65, gt=0.0, description="Cost of P2O5 fertilizer equivalent ($/kg P2O5)"
    )
    potassium_price_usd_kg: Optional[float] = Field(
        default=0.95, gt=0.0, description="Cost of K2O fertilizer equivalent ($/kg K2O)"
    )
    seed_prices_usd_per_ha: Optional[Dict[str, float]] = Field(
        default=None,
        description="Optional seed price mapping per hectare (e.g. {'Corn (Maize)': 280.0, 'Soybeans': 160.0})"
    )
    seed_data: Optional[List[SeedDataInput]] = Field(
        default=None,
        description="Detailed seed varieties specification: greenhouse requirement, cost, and resistance to extreme events"
    )
    labor_hourly_wage_usd: Optional[float] = Field(
        default=22.0, ge=0.0, description="Farm equipment operator / laborer hourly wage ($/hour)"
    )


# ==============================================================================
# 5. DATED TIMESERIES MODELS FOR NASA & IN-SITU OBSERVATIONS
# High temporal resolution structures preserving exact dates and overpass scenes.
# ==============================================================================

class DatedDailyWeatherRecord(BaseModel):
    """Daily meteorological observation with explicit date signature (NASA POWER)."""
    date: str = Field(..., description="Date of observation YYYY-MM-DD or YYYYMMDD")
    t2m_c: Optional[float] = Field(None, description="2m daily mean air temperature (°C)")
    t2m_max_c: Optional[float] = Field(None, description="Daily max air temperature (°C)")
    t2m_min_c: Optional[float] = Field(None, description="Daily min air temperature (°C)")
    precipitation_mm: Optional[float] = Field(None, ge=0.0, description="Daily precipitation accumulation (mm)")
    solar_radiation_mj_m2: Optional[float] = Field(None, ge=0.0, description="Daily all-sky surface insolation (MJ/m^2/day)")
    relative_humidity_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Daily mean relative humidity (%)")
    wind_speed_2m_ms: Optional[float] = Field(None, ge=0.0, description="Daily 2m wind speed (m/s)")
    dew_point_c: Optional[float] = Field(None, description="Dew point temperature (°C)")
    surface_pressure_kpa: Optional[float] = Field(None, description="Atmospheric surface pressure (kPa)")


class DatedPrecipitationObservation(BaseModel):
    """Timestamped precipitation record from NASA GPM IMERG."""
    date: str = Field(..., description="Observation date YYYY-MM-DD")
    precipitation_mm: float = Field(..., ge=0.0, description="Daily precipitation depth (mm)")
    rain_rate_max_mm_hr: Optional[float] = Field(None, ge=0.0, description="Peak storm precipitation rate (mm/hr)")
    storm_duration_hours: Optional[float] = Field(None, ge=0.0, description="Estimated rainfall duration (hours)")


class DatedSoilMoistureRecord(BaseModel):
    """Dated soil moisture observation from NASA SMAP L4."""
    date: str = Field(..., description="Observation date YYYY-MM-DD")
    surface_moisture_m3_m3: Optional[float] = Field(None, ge=0.0, le=1.0, description="0-5 cm surface volumetric moisture (m^3/m^3)")
    rootzone_moisture_m3_m3: Optional[float] = Field(None, ge=0.0, le=1.0, description="0-100 cm root-zone volumetric moisture (m^3/m^3)")
    surface_soil_temp_c: Optional[float] = Field(None, description="Soil surface temperature (°C)")
    rootzone_depletion_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Available water capacity depletion (%)")


class OpenEtTimeseriesRecord(BaseModel):
    """Dated crop actual evapotranspiration from NASA OpenET."""
    date: str = Field(..., description="Observation date YYYY-MM-DD")
    et_actual_mm: float = Field(..., ge=0.0, description="Actual evapotranspiration consumed by crop (mm)")
    et_reference_et0_mm: Optional[float] = Field(None, ge=0.0, description="Reference grass ET0 (mm)")
    crop_coefficient_kc: Optional[float] = Field(None, ge=0.0, description="Derived crop coefficient Kc")
    model_name: Optional[str] = Field(default="Ensemble", description="OpenET model algorithm")


class EcostressSceneRecord(BaseModel):
    """Dated canopy thermal stress overpass from NASA ECOSTRESS."""
    timestamp: str = Field(..., description="Overpass timestamp ISO-8601 YYYY-MM-DDTHH:MM:SSZ")
    canopy_surface_temp_c: Optional[float] = Field(None, description="Canopy surface thermal infrared temperature (°C)")
    evaporative_stress_index: Optional[float] = Field(None, ge=0.0, le=1.0, description="Evaporative Stress Index (ESI)")
    water_deficit_index: Optional[float] = Field(None, description="Water Deficit Index (WDI)")
    quality_flag: Optional[str] = Field(default="Clear", description="Quality flag / cloud interference")


class HlsOverpassRecord(BaseModel):
    """Dated multispectral vegetation scene from Harmonized Landsat-Sentinel (HLS)."""
    date: str = Field(..., description="Observation date YYYY-MM-DD")
    sensor: Optional[str] = Field(default="HLS", description="'Landsat-8/9 OLI' (L30) or 'Sentinel-2 MSI' (S30)")
    ndvi: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Normalized Difference Vegetation Index")
    ndre: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Red Edge Chlorophyll Index")
    ndwi: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Normalized Difference Water Index")
    cloud_cover_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Scene cloud cover percentage")


class SoilGridsDepthLayer(BaseModel):
    """Depth-stratified soil horizon property from ISRIC SoilGrids 2.0 / gSSURGO."""
    depth_interval: str = Field(..., description="Horizon depth tag (e.g. '0-5cm', '5-15cm', '15-30cm', '30-60cm', '60-100cm')")
    top_depth_cm: float = Field(..., ge=0.0, description="Top boundary depth (cm)")
    bottom_depth_cm: float = Field(..., gt=0.0, description="Bottom boundary depth (cm)")
    clay_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Clay fraction (%)")
    sand_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Sand fraction (%)")
    silt_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Silt fraction (%)")
    soil_organic_carbon_pct: Optional[float] = Field(None, ge=0.0, le=30.0, description="SOC percentage (%)")
    soc_pct: Optional[float] = Field(None, ge=0.0, le=30.0, description="SOC percentage alias (%)")
    soil_ph_h2o: Optional[float] = Field(None, ge=3.0, le=11.0, description="pH in H2O")
    bulk_density_g_cm3: Optional[float] = Field(None, ge=0.5, le=2.5, description="Fine earth bulk density (g/cm^3)")
    cation_exchange_capacity_cmol_kg: Optional[float] = Field(None, ge=0.0, description="CEC (cmol(+)/kg)")
    total_nitrogen_g_kg: Optional[float] = Field(None, ge=0.0, description="Total nitrogen (g/kg)")

    @model_validator(mode="after")
    def sync_soc_alias(self) -> "SoilGridsDepthLayer":
        if self.soil_organic_carbon_pct is None and self.soc_pct is not None:
            self.soil_organic_carbon_pct = self.soc_pct
        elif self.soil_organic_carbon_pct is not None and self.soc_pct is None:
            self.soc_pct = self.soil_organic_carbon_pct
        return self


class GraceMonthlyRecord(BaseModel):
    """Monthly deep aquifer groundwater storage anomaly from NASA GRACE / GRACE-FO."""
    date: str = Field(..., description="Observation month YYYY-MM")
    lwe_thickness_anomaly_cm: float = Field(..., description="Liquid Water Equivalent thickness anomaly (cm)")
    groundwater_percentile: Optional[float] = Field(None, ge=0.0, le=100.0, description="Drought/recharge historical percentile (0-100%)")
    trend_status: Optional[str] = Field(None, description="'Recharging', 'Stable', 'Depleting'")


class DatedInSituSensorReading(BaseModel):
    """
    Ground-level sensor observation with explicit date and time signature.
    Enables tracking of temporal depletion, compaction build-up, and moisture draw-down.
    """
    timestamp: str = Field(..., description="ISO-8601 Date/Time signature (e.g. '2025-05-15T09:30:00Z' or '2025-05-15')")
    sensor_id: Optional[str] = Field(None, description="Unique hardware probe or field station identifier")
    depth_cm: Optional[float] = Field(default=15.0, ge=0.0, description="Depth of probe insertion (cm)")
    location_latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Specific probe GPS latitude")
    location_longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Specific probe GPS longitude")
    soil_nitrogen_ppm: Optional[float] = Field(None, ge=0.0, description="Available Nitrate/Ammonium (ppm)")
    soil_phosphorus_ppm: Optional[float] = Field(None, ge=0.0, description="Available Phosphorus (ppm)")
    soil_potassium_ppm: Optional[float] = Field(None, ge=0.0, description="Available Potassium (ppm)")
    soil_moisture_vol_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Volumetric Soil Moisture (%)")
    soil_ph: Optional[float] = Field(None, ge=3.0, le=11.0, description="In-situ glass/ISFET pH reading")
    soil_ec_salinity_ds_m: Optional[float] = Field(None, ge=0.0, description="Electrical Conductivity in dS/m")
    soil_organic_matter_pct: Optional[float] = Field(None, ge=0.0, le=30.0, description="SOM % from portable NIR/LOI")
    soil_compaction_psi: Optional[float] = Field(None, ge=0.0, description="Cone penetrometer resistance (PSI)")
    soil_temperature_c: Optional[float] = Field(None, description="Soil temperature at sensor depth (°C)")
    device_model: Optional[str] = Field(None, description="Hardware make/model (e.g. 'Spectrum FieldScout TDR-350')")
    notes: Optional[str] = Field(None, description="Agronomist field notes for this reading")


# ==============================================================================
# 6. NASA PAYLOAD CONTAINERS (ACCEPTING OFFICIAL RAW FORMATS & TIMESERIES)
# ==============================================================================

class NasaPowerPayload(BaseModel):
    """
    Weather & Climate series from NASA POWER AG Community.
    Accepts:
    1. Official raw JSON point query response (Feature with properties.parameter)
    2. Explicit daily dated timeseries records (daily_timeseries)
    3. Parameter-to-date mapping dictionaries (daily_parameters: {"T2M": {"20230101": -2.3, ...}})
    4. Optional summary scalar fallbacks
    """
    raw_official_response: Optional[Dict[str, Any]] = Field(
        None, description="Raw official NASA POWER API point response containing 'properties.parameter'"
    )
    daily_timeseries: Optional[List[DatedDailyWeatherRecord]] = Field(
        None, description="Explicit list of dated daily weather observations"
    )
    daily_parameters: Optional[Dict[str, Dict[str, float]]] = Field(
        None, description="Dictionary of parameter name to date-value map (e.g. {'T2M': {'20230101': -2.3}})"
    )

    # Optional pre-computed scalar benchmarks
    t2m_mean_c: Optional[float] = Field(None, description="2m annual mean air temperature (°C)")
    t2m_max_c: Optional[float] = Field(None, description="Summer peak daily air temperature (°C)")
    t2m_min_c: Optional[float] = Field(None, description="Winter lowest daily air temperature (°C)")
    solar_radiation_mj_m2: Optional[float] = Field(None, description="Daily all-sky surface insolation (MJ/m^2/day)")
    relative_humidity_pct: Optional[float] = Field(None, description="Relative humidity (%)")
    wind_speed_2m_ms: Optional[float] = Field(None, description="2m wind speed (m/s)")
    growing_degree_days_base10: Optional[float] = Field(None, description="Annual accumulated GDD (Base 10°C)")
    fao56_et0_annual_mm: Optional[float] = Field(None, description="Annual Penman-Monteith reference ET0 (mm)")


class GpmImergPayload(BaseModel):
    """
    Precipitation metrics from NASA GPM IMERG.
    Accepts raw official response, daily precipitation list, or date-to-rain map.
    """
    raw_official_response: Optional[Any] = Field(
        None, description="Raw official NASA GPM IMERG STAC / timeseries response"
    )
    daily_records: Optional[List[DatedPrecipitationObservation]] = Field(
        None, description="Chronological daily precipitation observations with storm rates"
    )
    daily_rainfall_series: Optional[Dict[str, float]] = Field(
        None, description="Mapping of date string 'YYYY-MM-DD' to rainfall accumulation in mm"
    )

    annual_rainfall_mm: Optional[float] = Field(None, ge=0.0, description="Annual rainfall total (mm)")
    growing_season_rainfall_mm: Optional[float] = Field(None, ge=0.0, description="Rainfall during active growth season (mm)")
    peak_daily_rainfall_mm: Optional[float] = Field(None, ge=0.0, description="Max 24h storm accumulation (mm)")
    rainfall_deficit_percentage: Optional[float] = Field(None, description="Anomaly vs 30-year climatological normal (%)")


class SmapMoisturePayload(BaseModel):
    """
    Surface and root-zone soil moisture from NASA SMAP L4.
    Accepts raw official response or chronological dated moisture records.
    """
    raw_official_response: Optional[Any] = Field(
        None, description="Raw official NASA SMAP L4 timeseries payload"
    )
    daily_records: Optional[List[DatedSoilMoistureRecord]] = Field(
        None, description="Dated surface (0-5cm) and root-zone (0-100cm) volumetric moisture readings"
    )

    surface_moisture_m3_m3: Optional[float] = Field(None, ge=0.0, le=1.0, description="Surface volumetric moisture")
    rootzone_moisture_m3_m3: Optional[float] = Field(None, ge=0.0, le=1.0, description="Root-zone volumetric moisture")
    rootzone_depletion_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Available water capacity depletion (%)")


class OpenEtPayload(BaseModel):
    """
    Actual crop evapotranspiration from NASA OpenET.
    Accepts official OpenET API array (`[{'date': 'YYYY-MM-DD', 'et': mm}, ...]`), timeseries list, or date-to-ET dict.
    """
    raw_official_response: Optional[Any] = Field(
        None, description="Raw official OpenET REST API timeseries response array"
    )
    timeseries: Optional[List[OpenEtTimeseriesRecord]] = Field(
        None, description="Dated actual crop evapotranspiration records"
    )
    daily_et_series: Optional[Dict[str, float]] = Field(
        None, description="Date to ET (mm) mapping"
    )

    actual_et_annual_mm: Optional[float] = Field(None, ge=0.0, description="Field actual ET consumed by vegetation (mm)")
    crop_coefficient_kc_mid: Optional[float] = Field(None, description="Peak mid-season crop coefficient Kc")


class EcostressPayload(BaseModel):
    """
    Plant thermal and canopy stress from NASA ECOSTRESS.
    Accepts raw official response or dated scene overpass records.
    """
    raw_official_response: Optional[Any] = Field(
        None, description="Raw official ECOSTRESS LP DAAC / AppEEARS scene response"
    )
    scenes: Optional[List[EcostressSceneRecord]] = Field(
        None, description="Dated canopy thermal infrared scenes and Evaporative Stress Index"
    )

    canopy_surface_temp_c: Optional[float] = Field(None, description="Thermal infrared canopy temperature (°C)")
    evaporative_stress_index: Optional[float] = Field(None, ge=0.0, le=1.0, description="Evaporative Stress Index ESI")


class HlsSpectralPayload(BaseModel):
    """
    Harmonized Landsat-Sentinel 30m multispectral vegetation health.
    Accepts raw STAC response or chronological satellite overpasses.
    """
    raw_official_response: Optional[Any] = Field(
        None, description="Raw official NASA STAC / Earthdata HLS surface reflectance items"
    )
    overpasses: Optional[List[HlsOverpassRecord]] = Field(
        None, description="Chronological dated multispectral satellite overpasses"
    )

    ndvi_peak: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Peak Normalized Difference Vegetation Index")
    ndre_peak: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Red Edge Index (canopy chlorophyll)")
    ndwi_peak: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Canopy water hydration index")


class SoilGridsPayload(BaseModel):
    """
    Static soil physical & chemical traits from ISRIC SoilGrids 2.0 / gSSURGO.
    Accepts official ISRIC REST JSON format, depth-stratified horizon layers, or topsoil scalars.
    """
    raw_official_response: Optional[Dict[str, Any]] = Field(
        None, description="Raw official ISRIC SoilGrids 2.0 REST API response containing 'properties.layers'"
    )
    depth_layers: Optional[List[SoilGridsDepthLayer]] = Field(
        None, description="Depth-stratified soil horizon intervals (0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm)"
    )

    texture_class: Optional[str] = Field(None, description="USDA texture (e.g. 'Clay Loam', 'Silt Loam', 'Sandy Loam')")
    soil_order: Optional[str] = Field(None, description="Soil taxonomic order (e.g. 'Mollisol', 'Alfisol', 'Inceptisol')")
    sand_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    silt_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    clay_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    soil_organic_carbon_pct: Optional[float] = Field(None, ge=0.0, le=30.0, description="Topsoil SOC (%)")
    soil_ph_h2o: Optional[float] = Field(None, ge=3.0, le=11.0)
    total_nitrogen_g_kg: Optional[float] = Field(None, ge=0.0)
    bulk_density_g_cm3: Optional[float] = Field(None, ge=0.5, le=2.5)
    cation_exchange_capacity_cmol_kg: Optional[float] = Field(None, ge=0.0)


class GraceGroundwaterPayload(BaseModel):
    """
    Deep aquifer water storage anomalies from NASA GRACE / GRACE-FO.
    Accepts raw official response, monthly dated records, or date-to-anomaly dict.
    """
    raw_official_response: Optional[Dict[str, Any]] = Field(
        None, description="Raw official NASA GRACE Tellus / Earthdata groundwater anomaly payload"
    )
    monthly_records: Optional[List[GraceMonthlyRecord]] = Field(
        None, description="Monthly Liquid Water Equivalent (LWE) thickness anomaly timeseries"
    )
    monthly_series: Optional[Dict[str, float]] = Field(
        None, description="Month 'YYYY-MM' to LWE thickness anomaly (cm) mapping"
    )

    terrestrial_water_storage_trend: Optional[str] = Field(
        None, description="'Stable', 'Depleting (-1.2 cm/yr)', 'Recharging (+0.8 cm/yr)'"
    )
    water_table_depth_meters: Optional[float] = Field(None, ge=0.0, description="Depth to regional aquifer (m)")
    aquifer_security_status: Optional[str] = Field(None, description="'Secure', 'Vulnerable', 'Severely Depleted'")


class NasaDataPayload(BaseModel):
    """Unified container for all 11 NASA Earth Observation datasets."""
    nasa_power: Optional[NasaPowerPayload] = Field(None, description="NASA POWER agroclimatology")
    gpm_imerg: Optional[GpmImergPayload] = Field(None, description="NASA GPM satellite precipitation")
    smap_moisture: Optional[SmapMoisturePayload] = Field(None, description="NASA SMAP root-zone moisture")
    openet_water: Optional[OpenEtPayload] = Field(None, description="NASA OpenET actual evapotranspiration")
    ecostress: Optional[EcostressPayload] = Field(None, description="NASA ECOSTRESS thermal stress")
    hls_vegetation: Optional[HlsSpectralPayload] = Field(None, description="Harmonized Landsat-Sentinel spectral indices")
    soilgrids: Optional[SoilGridsPayload] = Field(None, description="SoilGrids / gSSURGO topsoil properties")
    grace_groundwater: Optional[GraceGroundwaterPayload] = Field(None, description="NASA GRACE deep groundwater anomalies")
    appeears_task_id: Optional[str] = Field(None, description="Optional NASA AppEEARS sample extraction reference ID")


# ==============================================================================
# 7. LONG-TERM WEATHER PROJECTIONS (OPTIONAL)
# ==============================================================================

class ClimateProjectionScenario(str, Enum):
    HISTORICAL_PERSISTENCE = "Historical Persistence (Past 5-10yr Trend)"
    CMIP6_SSP2_45 = "CMIP6 Moderate Mitigation (SSP2-4.5)"
    CMIP6_SSP5_85 = "CMIP6 High Emissions / Extreme Warming (SSP5-8.5)"
    CUSTOM_GROWER = "Custom Grower Projected Scenario"


class LongTermWeatherProjectionsInput(BaseModel):
    """Multi-year climatological projections and decadal climate shifts."""
    scenario: Optional[ClimateProjectionScenario] = Field(
        default=ClimateProjectionScenario.HISTORICAL_PERSISTENCE,
        description="Underlying climate trajectory model"
    )
    projection_horizon_years: int = Field(default=5, ge=1, le=20, description="Projection duration horizon in years")
    projected_annual_temp_shift_c: Optional[float] = Field(
        None, description="Anticipated mean temperature rise (°C) over horizon (e.g. +0.8°C)"
    )
    projected_annual_precipitation_delta_pct: Optional[float] = Field(
        None, description="Anticipated precipitation shift (%) (e.g. -6.5% for drying, +4.0% for wetter)"
    )
    heat_wave_days_increase_per_year: Optional[int] = Field(
        None, ge=0, description="Additional days per year exceeding crop heat threshold (>32°C)"
    )
    drought_frequency_rating: Optional[str] = Field(
        None, description="'Low (1 in 10 yr)', 'Moderate (1 in 4 yr)', 'Severe (Annual summer drought)'"
    )


# ==============================================================================
# 8. LOCAL USER DATA (IN-SITU SENSORS WITH DATE SIGNATURES, OVERRIDE, MANAGEMENT)
# ==============================================================================

class IrrigationSystemType(str, Enum):
    RAINFED = "Rainfed / Dryland (No Irrigation)"
    CENTER_PIVOT = "Center Pivot Sprinkler"
    DRIP_MICRO = "Precision Drip / Micro-Irrigation"
    FURROW_FLOOD = "Furrow / Gravity Surface Flood"
    SUB_IRRIGATION = "Sub-surface Drainage Tile Irrigation"


class TillagePractice(str, Enum):
    NO_TILL = "Continuous No-Till"
    STRIP_TILL = "Strip-Till / Reduced Tillage"
    CONVENTIONAL = "Conventional Inversion Plow"


class InSituPortableSensorReading(BaseModel):
    """Single handheld or mounted sensor observation snapshot (backward compatible)."""
    measurement_timestamp: Optional[str] = Field(None, description="ISO timestamp YYYY-MM-DD")
    soil_nitrogen_ppm: Optional[float] = Field(None, ge=0.0, description="Available Soil Nitrate/Ammonium (ppm)")
    soil_phosphorus_ppm: Optional[float] = Field(None, ge=0.0, description="Available Bray/Olsen Phosphorus (ppm)")
    soil_potassium_ppm: Optional[float] = Field(None, ge=0.0, description="Available Potassium (ppm)")
    soil_moisture_vol_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="TDR Volumetric Soil Moisture (%)")
    soil_ph: Optional[float] = Field(None, ge=3.0, le=11.0, description="In-situ glass/ISFET pH reading")
    soil_ec_salinity_ds_m: Optional[float] = Field(None, ge=0.0, description="Electrical Conductivity in dS/m")
    soil_organic_matter_pct: Optional[float] = Field(None, ge=0.0, le=30.0, description="SOM % from portable NIR/LOI")
    soil_compaction_psi: Optional[float] = Field(None, ge=0.0, description="Cone penetrometer resistance (PSI)")
    device_model: Optional[str] = Field(None, description="Hardware make/model")


class LocalUserDataInput(BaseModel):
    """Farm-specific operational parameters, machinery constraints, soil override, and ground sensors."""
    soil_type: Optional[str] = Field(
        None,
        description="Local farmer/lab verified soil type (overrides satellite SoilGrids data, e.g. 'Sandy Loam', 'Clay Loam')"
    )
    # Detailed in-situ sensor readings with date signatures
    dated_sensor_readings: Optional[List[DatedInSituSensorReading]] = Field(
        default=None,
        description="Chronological in-situ ground sensor readings with exact date/time signatures"
    )
    portable_sensors: Optional[InSituPortableSensorReading] = Field(
        None, description="Single handheld sensor observation snapshot (if timeseries not provided)"
    )

    irrigation_system: Optional[IrrigationSystemType] = Field(
        default=IrrigationSystemType.CENTER_PIVOT,
        description="Field irrigation technology installed"
    )
    tillage_practice: Optional[TillagePractice] = Field(
        default=TillagePractice.STRIP_TILL,
        description="Soil management tillage system"
    )
    is_organic_certified: bool = Field(default=False, description="Strict organic protocol (disallows synthetic NPK/chem)")
    labor_availability_rating: Optional[str] = Field(
        default="Standard", description="'Abundant Full-Time', 'Standard', 'Constrained / Part-Time'"
    )
    preferred_candidate_crops: Optional[List[str]] = Field(
        None, description="Optional whitelist of candidate crops for rotation"
    )
    excluded_crops: Optional[List[str]] = Field(
        None, description="Blacklist of crops farmer refuses to grow (e.g. ['Cotton'])"
    )
    farm_management_notes: Optional[str] = Field(
        None, description="Free-text operational instructions or notes for the agronomist"
    )


# ==============================================================================
# 9. ELEVATION MAPS (DEM, TOPOGRAPHY, RUNOFF)
# ==============================================================================

class AspectCompass(str, Enum):
    NORTH = "North-Facing"
    NORTHEAST = "Northeast-Facing"
    EAST = "East-Facing"
    SOUTHEAST = "Southeast-Facing"
    SOUTH = "South-Facing (Maximum Solar Irradiance)"
    SOUTHWEST = "Southwest-Facing"
    WEST = "West-Facing"
    NORTHWEST = "Northwest-Facing"
    FLAT = "Flat / Level Terrain"


class ElevationMapsInput(BaseModel):
    """High-resolution Digital Elevation Model (DEM) and terrain slope metrics."""
    elevation_mean_m: Optional[float] = Field(None, ge=-400.0, le=8848.0, description="Mean surface elevation (m)")
    elevation_min_m: Optional[float] = Field(None, description="Lowest spot elevation (m)")
    elevation_max_m: Optional[float] = Field(None, description="Highest crest elevation (m)")
    slope_mean_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Mean topographic slope (%)")
    slope_max_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Maximum slope gradient on parcel (%)")
    aspect: Optional[AspectCompass] = Field(default=AspectCompass.FLAT, description="Sun exposure slope direction")
    topographic_wetness_index: Optional[float] = Field(None, description="TWI: wetness accumulation potential")
    waterlogging_depression_present: Optional[bool] = Field(
        False, description="True if parcel has low spot prone to water stagnation after storms"
    )
    soil_erosion_susceptibility: Optional[str] = Field(
        None, description="'Low (Stable Flat)', 'Moderate (Terracing Recommended)', 'High (Washout Risk)'"
    )
    elevation_raster_url_or_ref: Optional[str] = Field(
        None, description="Optional URL or GeoTIFF reference to SRTM/NASADEM 30m raster"
    )


# ==============================================================================
# UNIFIED RAW INGESTION PAYLOAD
# ==============================================================================

class FullFieldIngestionPayload(BaseModel):
    """
    Unified Ingestion Payload accepted by the Input Parser API.
    Encompasses all core agronomic domains:
    - Parcel Info (with Soil Type)
    - Last couple years harvest/crop info (1-5 flexible)
    - Seed / Water / Oil Prices (with Greenhouse need & Extreme Event resistance inside seed data)
    - NASA data (Official raw database responses & full dated daily/scene timeseries)
    - Long Term Weather Projections (optional)
    - Local User Data (with dated in-situ sensor readings & soil type override)
    - Elevation Maps
    """
    parcel_info: ParcelInfoInput = Field(..., description="1. Parcel cadastral, geometry, coordinates, and soil type")
    harvest_history: HarvestAndCropHistoryInput = Field(..., description="2. Last couple years (max 5) harvest records")
    economic_prices: EconomicPricesInput = Field(
        default_factory=EconomicPricesInput,
        description="3. Seed, Water, Oil/Diesel, fertilizer prices, and seed characteristics"
    )
    seed_data: Optional[List[SeedDataInput]] = Field(
        default=None,
        description="Optional top-level seed data list (can also be provided inside economic_prices.seed_data)"
    )
    nasa_data: Optional[NasaDataPayload] = Field(
        None, description="4. NASA Earth Observations (POWER, GPM, SMAP, OpenET, ECOSTRESS, HLS, etc.)"
    )
    long_term_projections: Optional[LongTermWeatherProjectionsInput] = Field(
        None, description="5. Optional long-term climate scenario projections"
    )
    local_user_data: Optional[LocalUserDataInput] = Field(
        None, description="6. Local in-situ sensor data with date signatures, equipment, soil override, and farm constraints"
    )
    elevation_maps: Optional[ElevationMapsInput] = Field(
        None, description="7. Elevation, terrain slope, aspect, and waterlogging metrics"
    )
