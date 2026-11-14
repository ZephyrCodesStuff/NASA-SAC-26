"""
Scientific Crop Catalog & Botanical Agronomics Matrix.
Provides calibrated physiological, hydrological (FAO-56), nutritional (NPK),
economic (costs/revenue/labor), and rotational pathology parameters for 12+ crops.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from projection_api.models.input_parser_schemas import GreenhouseRequirement


class BotanicalFamily(str, Enum):
    POACEAE = "Poaceae"              # Grasses & Cereals (Corn, Wheat, Sorghum)
    FABACEAE = "Fabaceae"            # Legumes & Pulses (Soybeans, Alfalfa, Field Peas)
    ASTERACEAE = "Asteraceae"        # Composites (Sunflowers)
    BRASSICACEAE = "Brassicaceae"    # Crucifers & Biofumigants (Canola, Daikon Radish)
    SOLANACEAE = "Solanaceae"        # Nightshades (Tomatoes, Bell Peppers)
    AMARANTHACEAE = "Amaranthaceae"  # Chenopodiaceae / Leafy Greens (Spinach)


class RootArchitecture(str, Enum):
    FIBROUS_SHALLOW = "fibrous_shallow"      # 0.0 - 0.8m (e.g. Tomatoes, Spinach)
    FIBROUS_MEDIUM = "fibrous_medium"        # 0.0 - 1.2m (e.g. Wheat)
    FIBROUS_DEEP = "fibrous_deep"            # 0.0 - 1.6m (e.g. Corn, Sorghum)
    TAPROOT_MEDIUM = "taproot_medium"        # 0.0 - 1.0m (e.g. Soybeans, Field Peas)
    TAPROOT_DEEP = "taproot_deep"            # 0.0 - 2.0m (e.g. Sunflowers, Canola)
    TAPROOT_BIODRILL = "taproot_biodrill"    # 0.0 - 2.5m+ (e.g. Alfalfa, Daikon Radish)


class CropAgronomicProfile(BaseModel):
    crop_id: str
    common_name: str
    botanical_family: BotanicalFamily
    category: str
    season_type: str = "Warm Season (Spring/Summer)"  # or "Cool Season (Fall/Winter)"

    # Production & Economics
    potential_yield_tons_ha: float
    market_price_usd_ton: float
    seed_cost_usd_ha: float
    fixed_operational_cost_usd_ha: float = 150.0  # scouting, maintenance, spray operations
    labor_hours_per_ha: float
    machinery_passes_count: int
    fuel_consumption_liters_ha: float

    # Plant Nutrition & Nutrient Balances
    nitrogen_uptake_kg_per_ton: float
    p2o5_uptake_kg_per_ton: float
    k2o_uptake_kg_per_ton: float
    is_legume: bool = False
    ndfa_fraction: float = 0.0            # Biological Nitrogen Fixation: % of N derived from atmosphere (Herridge et al.)
    residual_soil_n_credit_kg_ha: float = 0.0  # Net soil nitrogen benefit to following crop

    # Root Architecture & ASAE Soil Compaction Mechanics
    root_architecture: RootArchitecture
    max_rooting_depth_m: float
    critical_compaction_limit_psi: float = 280.0  # Threshold where elongation stops (~2.0 MPa)
    compaction_relief_delta_psi: float = 0.0     # Subsoil bio-drilling hardpan relief (negative value reduces PSI)

    # Hydrology & FAO-56 Dual Crop Coefficients
    seasonal_water_demand_mm: float
    fao56_kcb_initial: float
    fao56_kcb_mid: float
    fao56_kcb_end: float
    depletion_fraction_p: float = 0.50            # Soil water depletion fraction for no stress (FAO-56 Table 22)
    growth_cycle_days: int

    # Environmental Requirements & Extreme Event Resistances (1.0 = highly vulnerable, 5.0 = highly resilient)
    greenhouse_requirement: GreenhouseRequirement = GreenhouseRequirement.OPEN_FIELD_ONLY
    drought_resistance: float = 3.0
    flood_resistance: float = 2.5
    wind_lodging_resistance: float = 3.5
    frost_resistance: float = 2.0
    extreme_heat_resistance: float = 3.5
    salinity_resistance: float = 2.5

    # Soil Conservation & Phytosanitary Break Properties
    rusle_c_factor: float = 0.20                  # Cover and management factor in RUSLE erosion
    humic_conversion_k1: float = 0.15             # Henin-Dupuis humification coefficient (straw/residue to stable humus)
    biomass_carbon_fraction: float = 0.45         # IPCC carbon fraction of dry biomass
    biofumigant_active: bool = False              # Releases glucosinolates / suppressive bio-compounds
    pest_break_families: List[BotanicalFamily] = Field(default_factory=list)
    rotational_break_needed_years: int = 1        # Minimum years before repeating this exact family safely


# Comprehensive Master Catalog of 12 Validated Agricultural Crops
MASTER_CROPS_CATALOG: Dict[str, CropAgronomicProfile] = {
    "corn": CropAgronomicProfile(
        crop_id="corn",
        common_name="Corn (Maize)",
        botanical_family=BotanicalFamily.POACEAE,
        category="Cereal Grain / High Yield Cash Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=9.5,
        market_price_usd_ton=225.0,
        seed_cost_usd_ha=240.0,
        fixed_operational_cost_usd_ha=210.0,
        labor_hours_per_ha=4.8,
        machinery_passes_count=4,
        fuel_consumption_liters_ha=42.0,
        nitrogen_uptake_kg_per_ton=22.0,
        p2o5_uptake_kg_per_ton=8.5,
        k2o_uptake_kg_per_ton=19.5,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_DEEP,
        max_rooting_depth_m=1.5,
        critical_compaction_limit_psi=270.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=550.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=0.35,
        depletion_fraction_p=0.55,
        growth_cycle_days=130,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.0,
        flood_resistance=2.2,
        wind_lodging_resistance=3.2,
        frost_resistance=1.5,
        extreme_heat_resistance=3.8,
        salinity_resistance=2.0,
        rusle_c_factor=0.22,
        humic_conversion_k1=0.14,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.SOLANACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=1,
    ),
    "soybeans": CropAgronomicProfile(
        crop_id="soybeans",
        common_name="Soybeans",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Oilseed Legume / Protein Cash Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=3.4,
        market_price_usd_ton=470.0,
        seed_cost_usd_ha=165.0,
        fixed_operational_cost_usd_ha=170.0,
        labor_hours_per_ha=3.5,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=32.0,
        nitrogen_uptake_kg_per_ton=64.0,
        p2o5_uptake_kg_per_ton=14.0,
        k2o_uptake_kg_per_ton=24.0,
        is_legume=True,
        ndfa_fraction=0.68,                      # 68% of plant N fixed from atmosphere
        residual_soil_n_credit_kg_ha=35.0,      # Positive nitrogen credit for following crop
        root_architecture=RootArchitecture.TAPROOT_MEDIUM,
        max_rooting_depth_m=1.2,
        critical_compaction_limit_psi=260.0,
        compaction_relief_delta_psi=-10.0,
        seasonal_water_demand_mm=480.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.30,
        depletion_fraction_p=0.50,
        growth_cycle_days=120,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.5,
        flood_resistance=2.5,
        wind_lodging_resistance=4.0,
        frost_resistance=2.0,
        extreme_heat_resistance=3.5,
        salinity_resistance=2.2,
        rusle_c_factor=0.25,
        humic_conversion_k1=0.18,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
    ),
    "winter_wheat": CropAgronomicProfile(
        crop_id="winter_wheat",
        common_name="Winter Wheat",
        botanical_family=BotanicalFamily.POACEAE,
        category="Cool Season Cereal / Soil Protection Cover",
        season_type="Cool Season (Fall/Winter/Spring)",
        potential_yield_tons_ha=5.6,
        market_price_usd_ton=245.0,
        seed_cost_usd_ha=115.0,
        fixed_operational_cost_usd_ha=140.0,
        labor_hours_per_ha=2.8,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=28.0,
        nitrogen_uptake_kg_per_ton=24.0,
        p2o5_uptake_kg_per_ton=9.0,
        k2o_uptake_kg_per_ton=18.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_MEDIUM,
        max_rooting_depth_m=1.3,
        critical_compaction_limit_psi=270.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=380.0,
        fao56_kcb_initial=0.20,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.25,
        depletion_fraction_p=0.55,
        growth_cycle_days=210,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.8,
        flood_resistance=3.0,
        wind_lodging_resistance=3.6,
        frost_resistance=4.9,                     # High frost resilience down to -15°C
        extreme_heat_resistance=2.5,
        salinity_resistance=3.0,
        rusle_c_factor=0.08,                     # Exceptional winter erosion reduction
        humic_conversion_k1=0.15,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.FABACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
    ),
    "grain_sorghum": CropAgronomicProfile(
        crop_id="grain_sorghum",
        common_name="Grain Sorghum (Milo)",
        botanical_family=BotanicalFamily.POACEAE,
        category="Drought Resilient Cereal Grain",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=6.8,
        market_price_usd_ton=210.0,
        seed_cost_usd_ha=80.0,
        fixed_operational_cost_usd_ha=130.0,
        labor_hours_per_ha=2.5,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=26.0,
        nitrogen_uptake_kg_per_ton=18.5,
        p2o5_uptake_kg_per_ton=7.5,
        k2o_uptake_kg_per_ton=15.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_DEEP,
        max_rooting_depth_m=1.6,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=340.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.00,
        fao56_kcb_end=0.35,
        depletion_fraction_p=0.65,
        growth_cycle_days=115,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.8,                  # Extreme drought resilience
        flood_resistance=2.8,
        wind_lodging_resistance=3.8,
        frost_resistance=1.8,
        extreme_heat_resistance=4.7,             # Excels in extreme heat
        salinity_resistance=3.2,
        rusle_c_factor=0.18,
        humic_conversion_k1=0.14,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.FABACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
    ),
    "alfalfa": CropAgronomicProfile(
        crop_id="alfalfa",
        common_name="Alfalfa (Lucerne)",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Perennial Deep-Rooted Soil Builder & Forage",
        season_type="Full Season Perennial",
        potential_yield_tons_ha=11.5,
        market_price_usd_ton=235.0,
        seed_cost_usd_ha=195.0,
        fixed_operational_cost_usd_ha=180.0,
        labor_hours_per_ha=6.5,
        machinery_passes_count=5,
        fuel_consumption_liters_ha=48.0,
        nitrogen_uptake_kg_per_ton=28.0,
        p2o5_uptake_kg_per_ton=6.0,
        k2o_uptake_kg_per_ton=25.0,
        is_legume=True,
        ndfa_fraction=0.85,                      # 85% atmospheric N fixation
        residual_soil_n_credit_kg_ha=120.0,     # Massive +120 kg N/ha biological N credit!
        root_architecture=RootArchitecture.TAPROOT_BIODRILL,
        max_rooting_depth_m=2.6,
        critical_compaction_limit_psi=340.0,
        compaction_relief_delta_psi=-55.0,      # Deep bio-drilling hardpan relief
        seasonal_water_demand_mm=620.0,
        fao56_kcb_initial=0.30,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=1.10,
        depletion_fraction_p=0.55,
        growth_cycle_days=200,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.3,                  # Deep roots tap subsoil moisture
        flood_resistance=2.0,
        wind_lodging_resistance=4.5,
        frost_resistance=4.6,
        extreme_heat_resistance=3.8,
        salinity_resistance=2.8,
        rusle_c_factor=0.04,                     # Dense sod prevents virtually all erosion
        humic_conversion_k1=0.28,                # Very high organic matter contributor
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=2,
    ),
    "sunflowers": CropAgronomicProfile(
        crop_id="sunflowers",
        common_name="Sunflowers",
        botanical_family=BotanicalFamily.ASTERACEAE,
        category="Oilseed Cash Crop / Subsoil Scavenger",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=2.9,
        market_price_usd_ton=510.0,
        seed_cost_usd_ha=125.0,
        fixed_operational_cost_usd_ha=160.0,
        labor_hours_per_ha=3.0,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=30.0,
        nitrogen_uptake_kg_per_ton=35.0,
        p2o5_uptake_kg_per_ton=12.0,
        k2o_uptake_kg_per_ton=32.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_DEEP,
        max_rooting_depth_m=2.0,
        critical_compaction_limit_psi=310.0,
        compaction_relief_delta_psi=-25.0,      # Penetrates deep subsoil
        seasonal_water_demand_mm=390.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.05,
        fao56_kcb_end=0.25,
        depletion_fraction_p=0.45,
        growth_cycle_days=110,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.2,
        flood_resistance=2.0,
        wind_lodging_resistance=3.0,
        frost_resistance=2.6,
        extreme_heat_resistance=4.2,
        salinity_resistance=3.0,
        rusle_c_factor=0.22,
        humic_conversion_k1=0.16,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=2,
    ),
    "canola": CropAgronomicProfile(
        crop_id="canola",
        common_name="Canola (Rapeseed)",
        botanical_family=BotanicalFamily.BRASSICACEAE,
        category="Oilseed Cash Crop / Natural Biofumigant",
        season_type="Cool/Transition Season",
        potential_yield_tons_ha=3.0,
        market_price_usd_ton=530.0,
        seed_cost_usd_ha=140.0,
        fixed_operational_cost_usd_ha=165.0,
        labor_hours_per_ha=3.2,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=31.0,
        nitrogen_uptake_kg_per_ton=45.0,
        p2o5_uptake_kg_per_ton=18.0,
        k2o_uptake_kg_per_ton=22.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_DEEP,
        max_rooting_depth_m=1.4,
        critical_compaction_limit_psi=280.0,
        compaction_relief_delta_psi=-15.0,
        seasonal_water_demand_mm=410.0,
        fao56_kcb_initial=0.20,
        fao56_kcb_mid=1.05,
        fao56_kcb_end=0.25,
        depletion_fraction_p=0.60,
        growth_cycle_days=105,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.2,
        flood_resistance=2.3,
        wind_lodging_resistance=3.4,
        frost_resistance=4.2,
        extreme_heat_resistance=2.2,             # Heat stress during flowering hurts yield
        salinity_resistance=3.5,
        rusle_c_factor=0.16,
        humic_conversion_k1=0.17,
        biofumigant_active=True,                 # Glucosinolate biofumigation
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=2,
    ),
    "field_peas": CropAgronomicProfile(
        crop_id="field_peas",
        common_name="Field Peas / Chickpeas",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Pulse Legume / Low Water Protein Crop",
        season_type="Cool Season (Spring)",
        potential_yield_tons_ha=3.3,
        market_price_usd_ton=390.0,
        seed_cost_usd_ha=145.0,
        fixed_operational_cost_usd_ha=135.0,
        labor_hours_per_ha=2.7,
        machinery_passes_count=3,
        fuel_consumption_liters_ha=27.0,
        nitrogen_uptake_kg_per_ton=32.0,
        p2o5_uptake_kg_per_ton=8.0,
        k2o_uptake_kg_per_ton=18.0,
        is_legume=True,
        ndfa_fraction=0.76,                      # 76% N fixed
        residual_soil_n_credit_kg_ha=55.0,      # +55 kg N/ha credit
        root_architecture=RootArchitecture.TAPROOT_MEDIUM,
        max_rooting_depth_m=0.9,
        critical_compaction_limit_psi=250.0,
        compaction_relief_delta_psi=-8.0,
        seasonal_water_demand_mm=290.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.25,
        depletion_fraction_p=0.45,
        growth_cycle_days=95,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.9,
        flood_resistance=1.8,                    # Very poor waterlogging tolerance
        wind_lodging_resistance=3.0,
        frost_resistance=3.8,
        extreme_heat_resistance=2.2,
        salinity_resistance=2.2,
        rusle_c_factor=0.20,
        humic_conversion_k1=0.19,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.ASTERACEAE],
        rotational_break_needed_years=1,
    ),
    "processing_tomatoes": CropAgronomicProfile(
        crop_id="processing_tomatoes",
        common_name="Processing Tomatoes",
        botanical_family=BotanicalFamily.SOLANACEAE,
        category="High Gross Margin Specialty Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=75.0,
        market_price_usd_ton=128.0,              # ~$9,600/ha gross revenue
        seed_cost_usd_ha=780.0,
        fixed_operational_cost_usd_ha=1200.0,    # Intensive spray, bed prep, harvest contract
        labor_hours_per_ha=16.0,
        machinery_passes_count=7,
        fuel_consumption_liters_ha=76.0,
        nitrogen_uptake_kg_per_ton=2.8,          # ~210 kg N/ha
        p2o5_uptake_kg_per_ton=0.9,
        k2o_uptake_kg_per_ton=4.4,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.8,
        critical_compaction_limit_psi=240.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=620.0,
        fao56_kcb_initial=0.25,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=0.70,
        depletion_fraction_p=0.40,
        growth_cycle_days=130,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=2.0,
        flood_resistance=1.6,                    # Prone to root-rot / Phytophthora
        wind_lodging_resistance=3.5,
        frost_resistance=1.0,                    # Frost fatal
        extreme_heat_resistance=2.8,
        salinity_resistance=2.5,
        rusle_c_factor=0.30,
        humic_conversion_k1=0.10,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=3,        # Strict 3-year break to avoid Fusarium/Verticillium
    ),
    "daikon_radish_cover": CropAgronomicProfile(
        crop_id="daikon_radish_cover",
        common_name="Daikon Radish (Tillage Cover)",
        botanical_family=BotanicalFamily.BRASSICACEAE,
        category="Hardpan Bio-Drill / Soil Restorer Cover",
        season_type="Late Summer / Fall Cover",
        potential_yield_tons_ha=5.2,
        market_price_usd_ton=140.0,              # Biomass/forage/seed value
        seed_cost_usd_ha=65.0,
        fixed_operational_cost_usd_ha=60.0,
        labor_hours_per_ha=1.8,
        machinery_passes_count=2,
        fuel_consumption_liters_ha=18.0,
        nitrogen_uptake_kg_per_ton=28.0,         # Scavenges 140+ kg residual subsoil N
        p2o5_uptake_kg_per_ton=6.0,
        k2o_uptake_kg_per_ton=30.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=40.0,      # Releases scavenged nitrate in spring upon winterkill
        root_architecture=RootArchitecture.TAPROOT_BIODRILL,
        max_rooting_depth_m=1.8,
        critical_compaction_limit_psi=360.0,
        compaction_relief_delta_psi=-65.0,      # Major biological subsoil hardpan alleviation
        seasonal_water_demand_mm=220.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=0.95,
        fao56_kcb_end=0.30,
        depletion_fraction_p=0.50,
        growth_cycle_days=70,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.6,
        flood_resistance=2.8,
        wind_lodging_resistance=5.0,
        frost_resistance=3.5,                    # Winterkills around -6°C, creating open root channels
        extreme_heat_resistance=2.8,
        salinity_resistance=3.8,
        rusle_c_factor=0.12,
        humic_conversion_k1=0.22,
        biofumigant_active=True,                 # Powerful biofumigant suppresses nematodes
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
    ),
    "bell_peppers": CropAgronomicProfile(
        crop_id="bell_peppers",
        common_name="Bell Peppers",
        botanical_family=BotanicalFamily.SOLANACEAE,
        category="High Gross Value Specialty Vegetable",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=28.0,
        market_price_usd_ton=880.0,              # ~$24,640/ha gross revenue!
        seed_cost_usd_ha=1150.0,
        fixed_operational_cost_usd_ha=2600.0,    # Mulch, fertigation, trellis, scouting
        labor_hours_per_ha=42.0,                 # High labor harvesting & management
        machinery_passes_count=8,
        fuel_consumption_liters_ha=82.0,
        nitrogen_uptake_kg_per_ton=5.5,
        p2o5_uptake_kg_per_ton=1.8,
        k2o_uptake_kg_per_ton=7.2,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.7,
        critical_compaction_limit_psi=230.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=580.0,
        fao56_kcb_initial=0.25,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.80,
        depletion_fraction_p=0.35,
        growth_cycle_days=125,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=1.8,
        flood_resistance=1.5,
        wind_lodging_resistance=2.8,
        frost_resistance=1.0,
        extreme_heat_resistance=2.6,
        salinity_resistance=2.1,
        rusle_c_factor=0.28,
        humic_conversion_k1=0.11,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=3,
    ),
    "spinach": CropAgronomicProfile(
        crop_id="spinach",
        common_name="Spinach (Fresh / Processing)",
        botanical_family=BotanicalFamily.AMARANTHACEAE,
        category="Rapid Cycle Leafy Green / High ROI Vegetable",
        season_type="Cool Season (Spring or Autumn)",
        potential_yield_tons_ha=16.0,
        market_price_usd_ton=920.0,              # ~$14,720/ha gross revenue
        seed_cost_usd_ha=380.0,
        fixed_operational_cost_usd_ha=1400.0,
        labor_hours_per_ha=20.0,
        machinery_passes_count=4,
        fuel_consumption_liters_ha=36.0,
        nitrogen_uptake_kg_per_ton=8.0,
        p2o5_uptake_kg_per_ton=2.5,
        k2o_uptake_kg_per_ton=11.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.5,
        critical_compaction_limit_psi=220.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=260.0,
        fao56_kcb_initial=0.30,
        fao56_kcb_mid=1.00,
        fao56_kcb_end=0.90,
        depletion_fraction_p=0.30,
        growth_cycle_days=50,                    # Fast 50-day crop
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=2.0,
        flood_resistance=2.0,
        wind_lodging_resistance=4.8,
        frost_resistance=4.6,                    # Cold tolerant down to -4°C
        extreme_heat_resistance=1.3,             # Bolting above 24°C
        salinity_resistance=3.2,
        rusle_c_factor=0.20,
        humic_conversion_k1=0.15,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=1,
    ),
}


def get_crop_profile(crop_identifier: str) -> Optional[CropAgronomicProfile]:
    """Retrieves crop profile by id or normalized name."""
    clean_id = crop_identifier.lower().replace(" ", "_").replace("-", "_")
    if clean_id in MASTER_CROPS_CATALOG:
        return MASTER_CROPS_CATALOG[clean_id]
    
    # Partial match
    for k, v in MASTER_CROPS_CATALOG.items():
        if clean_id in k or k in clean_id or clean_id in v.common_name.lower():
            return v
    return None
