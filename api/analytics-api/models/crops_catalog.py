"""
Scientific Crop Catalog & Botanical Agronomics Matrix.
Provides calibrated physiological, hydrological (FAO-56), nutritional (NPK),
economic (costs/revenue/labor), and rotational pathology parameters for 12+ crops.
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
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
    potential_yield_tons_ha: float                # Attainable yield ceiling (t/ha)
    reference_yield_tons_ha: float = 0.0          # Regional statistical reference yield Y_ref (t/ha)
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
    ndfa_fraction: float = 0.0                    # Biological Nitrogen Fixation: fraction of N derived from atmosphere (Peoples et al. 2021)
    residual_soil_n_credit_kg_ha: float = 0.0     # Legacy fallback / scavenged N credit (N_scav for cover crops)
    nitrogen_harvest_index: float = 0.72          # NHI = N_harvest / N_shoot (1.0 for forages/cover crops)
    f_bgn: float = 1.3                            # Ratio N_plant / N_shoot (Herridge/Unkovich: 1.5 soybean, 2.0 chickpea/forages)
    residue_n_release_fraction: float = 0.35      # f_rel: fraction of legume residue N released to next crop (calibration param)
    scavenged_n_credit_kg_ha: float = 0.0         # N_scav: scavenged mineral N released by cover crop (calibration param)

    # Root Architecture & Heuristic Soil Compaction Mechanics (critical limit ~ 2 MPa = 290 PSI)
    root_architecture: RootArchitecture
    max_rooting_depth_m: float
    critical_compaction_limit_psi: float = 290.0  # Bengough et al. (2011): ~2 MPa (~290 PSI)
    compaction_relief_delta_psi: float = 0.0      # Subsoil bio-drilling hardpan relief (negative value reduces PSI)

    # Hydrology, Crop Calendar & FAO-56 Single Crop Coefficients (Table 11 & 12)
    seasonal_water_demand_mm: float
    fao56_kcb_initial: float                      # Retained for backward compatibility
    fao56_kcb_mid: float
    fao56_kcb_end: float
    kc_ini: float = 0.30                          # FAO-56 Table 12 single Kc (initial)
    kc_mid: float = 1.15                          # FAO-56 Table 12 single Kc (mid-season)
    kc_end: float = 0.35                          # FAO-56 Table 12 single Kc (end-season)
    stage_fractions: Tuple[float, float, float, float] = (0.17, 0.28, 0.33, 0.22)  # L_ini, L_dev, L_mid, L_late
    crop_height_m: float = 1.0                    # Mean maximum crop height h (m) for FAO-56 Eq. 62
    sowing_month_default: int = 4                 # Default sowing month (1..12, Northern Hemisphere)
    harvest_month_default: int = 9                # Default harvest month (1..12, Northern Hemisphere)
    sowing_doy_default: int = 105                 # Default sowing day-of-year (1..365)
    harvest_doy_default: int = 255                # Default harvest day-of-year (1..365; < sowing_doy wraps year)
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

    # Soil Conservation, Bolinder Carbon Allocation & Phytosanitary Break Properties
    rusle_c_factor: float = 0.20                  # Cover and management factor (Panagos et al. 2015)
    humic_conversion_k1: float = 0.15             # Legacy single k1 (retained for compatibility)
    k1_above: float = 0.12                        # Humification coefficient for above-ground residue (calibration param)
    k1_below: float = 0.25                        # Humification coefficient for below-ground root/extra-root C (calibration param)
    dry_matter_fraction: float = 0.86             # f_DM = 1 - moisture (USDA FDC for fresh produce)
    bolinder_rp: float = 0.43                     # Bolinder relative allocation to harvested product R_P
    bolinder_rs: float = 0.43                     # Bolinder relative allocation to shoot residue R_S
    bolinder_rr: float = 0.14                     # Bolinder relative allocation to root R_R (R_P + R_S + R_R = 1)
    bolinder_flagged_no_published_set: bool = False  # True when crop lacks a published Bolinder (2007/2015) set
    biomass_carbon_fraction: float = 0.45         # Bolinder / IPCC carbon fraction of dry biomass
    biofumigant_active: bool = False              # Releases glucosinolates / suppressive bio-compounds
    pest_break_families: List[BotanicalFamily] = Field(default_factory=list)
    rotational_break_needed_years: int = 1        # Minimum years before repeating this exact family safely
    optimal_temp_min_c: float = 10.0              # Lower optimal mean growing temperature (°C)
    optimal_temp_max_c: float = 28.0              # Upper optimal mean growing temperature (°C)
    frost_kill_temp_c: Optional[float] = None     # Freezing threshold (°C) for acute frost kill
    optimal_ph_min: float = 5.8                   # Lower optimal soil pH
    optimal_ph_max: float = 7.6                   # Upper optimal soil pH
    abs_ph_min: Optional[float] = None            # FAO ECOCROP absolute lower soil pH lockout
    abs_ph_max: Optional[float] = None            # FAO ECOCROP absolute upper soil pH lockout
    fao33_ky: float = 1.0                         # FAO Irrigation & Drainage Paper 33 seasonal yield response factor (Ky)

    @property
    def phosphorus_uptake_kg_per_ton(self) -> float:
        """Elemental P uptake (kg P / t): P2O5 * 0.4364."""
        return round(self.p2o5_uptake_kg_per_ton * 0.4364, 4)

    @property
    def potassium_uptake_kg_per_ton(self) -> float:
        """Elemental K uptake (kg K / t): K2O * 0.8301."""
        return round(self.k2o_uptake_kg_per_ton * 0.8301, 4)


# Comprehensive Master Catalog of 12 Validated Agricultural Crops
MASTER_CROPS_CATALOG: Dict[str, CropAgronomicProfile] = {
    "corn": CropAgronomicProfile(
        crop_id="corn",
        common_name="Corn (Maize)",
        botanical_family=BotanicalFamily.POACEAE,
        category="Cereal Grain / High Yield Cash Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=11.0,
        reference_yield_tons_ha=9.2,
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
        nitrogen_harvest_index=0.68,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_DEEP,
        max_rooting_depth_m=1.5,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=550.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=0.35,
        kc_ini=0.30,
        kc_mid=1.20,
        kc_end=0.35,
        stage_fractions=(0.17, 0.28, 0.33, 0.22),
        crop_height_m=2.0,
        sowing_month_default=4,
        harvest_month_default=9,
        sowing_doy_default=105,
        harvest_doy_default=255,
        depletion_fraction_p=0.55,
        growth_cycle_days=150,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.0,
        flood_resistance=2.2,
        wind_lodging_resistance=3.2,
        frost_resistance=1.5,
        extreme_heat_resistance=3.8,
        salinity_resistance=2.0,
        rusle_c_factor=0.38,
        humic_conversion_k1=0.14,
        k1_above=0.12,
        k1_below=0.26,
        dry_matter_fraction=0.86,
        bolinder_rp=0.43,
        bolinder_rs=0.43,
        bolinder_rr=0.14,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.SOLANACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=14.0,
        optimal_temp_max_c=27.0,
        frost_kill_temp_c=0.0,
        optimal_ph_min=5.8,
        optimal_ph_max=7.4,
        abs_ph_min=4.5,
        abs_ph_max=8.5,
        fao33_ky=1.25,
    ),
    "soybeans": CropAgronomicProfile(
        crop_id="soybeans",
        common_name="Soybeans",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Oilseed Legume / Protein Cash Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=4.0,
        reference_yield_tons_ha=3.4,
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
        ndfa_fraction=0.68,                      # 68% of plant N fixed from atmosphere (Peoples et al. 2021)
        residual_soil_n_credit_kg_ha=35.0,      # Legacy field; v1.1 computes f_rel * (N_plant - N_harvest)
        nitrogen_harvest_index=0.73,
        f_bgn=1.5,                              # Herridge / Unkovich (2008): 1.5 for soybean
        residue_n_release_fraction=0.35,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_MEDIUM,
        max_rooting_depth_m=1.2,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=-10.0,
        seasonal_water_demand_mm=480.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.30,
        kc_ini=0.40,
        kc_mid=1.15,
        kc_end=0.50,
        stage_fractions=(0.15, 0.20, 0.45, 0.20),
        crop_height_m=0.8,
        sowing_month_default=5,
        harvest_month_default=9,
        sowing_doy_default=125,
        harvest_doy_default=260,
        depletion_fraction_p=0.50,
        growth_cycle_days=135,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.5,
        flood_resistance=2.5,
        wind_lodging_resistance=4.0,
        frost_resistance=2.0,
        extreme_heat_resistance=3.5,
        salinity_resistance=2.2,
        rusle_c_factor=0.28,
        humic_conversion_k1=0.18,
        k1_above=0.14,
        k1_below=0.28,
        dry_matter_fraction=0.86,
        bolinder_rp=0.34,
        bolinder_rs=0.51,
        bolinder_rr=0.15,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=14.0,
        optimal_temp_max_c=26.5,
        frost_kill_temp_c=0.0,
        optimal_ph_min=6.0,
        optimal_ph_max=7.2,
        abs_ph_min=4.5,
        abs_ph_max=8.4,
        fao33_ky=0.85,
    ),
    "winter_wheat": CropAgronomicProfile(
        crop_id="winter_wheat",
        common_name="Winter Wheat",
        botanical_family=BotanicalFamily.POACEAE,
        category="Cool Season Cereal / Soil Protection Cover",
        season_type="Cool Season (Fall/Winter/Spring)",
        potential_yield_tons_ha=7.2,
        reference_yield_tons_ha=5.6,
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
        nitrogen_harvest_index=0.73,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_MEDIUM,
        max_rooting_depth_m=1.3,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=380.0,
        fao56_kcb_initial=0.20,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.25,
        kc_ini=0.40,
        kc_mid=1.15,
        kc_end=0.25,
        stage_fractions=(0.15, 0.25, 0.40, 0.20),
        crop_height_m=1.0,
        sowing_month_default=10,
        harvest_month_default=6,
        sowing_doy_default=288,
        harvest_doy_default=175,
        depletion_fraction_p=0.55,
        growth_cycle_days=252,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.8,
        flood_resistance=3.0,
        wind_lodging_resistance=3.6,
        frost_resistance=4.9,                     # High frost resilience down to -15°C
        extreme_heat_resistance=2.5,
        salinity_resistance=3.0,
        rusle_c_factor=0.20,                     # Panagos et al. (2015) cereals
        humic_conversion_k1=0.15,
        k1_above=0.12,
        k1_below=0.26,
        dry_matter_fraction=0.86,
        bolinder_rp=0.35,
        bolinder_rs=0.47,
        bolinder_rr=0.18,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.FABACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=4.0,
        optimal_temp_max_c=21.0,
        frost_kill_temp_c=-15.0,
        optimal_ph_min=5.8,
        optimal_ph_max=7.8,
        abs_ph_min=4.5,
        abs_ph_max=8.5,
        fao33_ky=1.00,
    ),
    "grain_sorghum": CropAgronomicProfile(
        crop_id="grain_sorghum",
        common_name="Grain Sorghum (Milo)",
        botanical_family=BotanicalFamily.POACEAE,
        category="Drought Resilient Cereal Grain",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=7.8,
        reference_yield_tons_ha=6.5,
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
        nitrogen_harvest_index=0.70,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_DEEP,
        max_rooting_depth_m=1.6,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=340.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.00,
        fao56_kcb_end=0.35,
        kc_ini=0.30,
        kc_mid=1.05,
        kc_end=0.55,
        stage_fractions=(0.16, 0.28, 0.32, 0.24),
        crop_height_m=1.5,
        sowing_month_default=5,
        harvest_month_default=9,
        sowing_doy_default=135,
        harvest_doy_default=255,
        depletion_fraction_p=0.65,
        growth_cycle_days=120,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.8,                  # Extreme drought resilience
        flood_resistance=2.8,
        wind_lodging_resistance=3.8,
        frost_resistance=1.8,
        extreme_heat_resistance=4.7,             # Excels in extreme heat
        salinity_resistance=3.2,
        rusle_c_factor=0.26,
        humic_conversion_k1=0.14,
        k1_above=0.12,
        k1_below=0.25,
        dry_matter_fraction=0.86,
        bolinder_rp=0.40,
        bolinder_rs=0.45,
        bolinder_rr=0.15,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.FABACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=16.0,
        optimal_temp_max_c=32.0,
        frost_kill_temp_c=0.0,
        optimal_ph_min=5.5,
        optimal_ph_max=8.2,
        abs_ph_min=4.5,
        abs_ph_max=8.8,
        fao33_ky=0.90,
    ),
    "alfalfa": CropAgronomicProfile(
        crop_id="alfalfa",
        common_name="Alfalfa (Lucerne)",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Perennial Deep-Rooted Soil Builder & Forage",
        season_type="Full Season Perennial",
        potential_yield_tons_ha=12.0,
        reference_yield_tons_ha=10.0,
        market_price_usd_ton=190.0,
        seed_cost_usd_ha=220.0,
        fixed_operational_cost_usd_ha=240.0,
        labor_hours_per_ha=12.0,
        machinery_passes_count=6,
        fuel_consumption_liters_ha=48.0,
        nitrogen_uptake_kg_per_ton=28.0,
        p2o5_uptake_kg_per_ton=6.0,
        k2o_uptake_kg_per_ton=25.0,
        is_legume=True,
        ndfa_fraction=0.85,                      # 85% atmospheric N fixation
        residual_soil_n_credit_kg_ha=120.0,     # Legacy field
        nitrogen_harvest_index=1.0,             # Section 3.3: For forages, harvested biomass is the shoot (NHI=1)
        f_bgn=2.0,                              # Section 3.3: 2.0 for pasture/fodder legumes (Unkovich et al. 2008)
        residue_n_release_fraction=0.35,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_BIODRILL,
        max_rooting_depth_m=2.6,
        critical_compaction_limit_psi=340.0,
        compaction_relief_delta_psi=-55.0,      # Deep bio-drilling hardpan relief
        seasonal_water_demand_mm=620.0,
        fao56_kcb_initial=0.30,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=1.10,
        kc_ini=0.40,
        kc_mid=0.95,                            # FAO-56 Table 12 averaged cutting-cycle coefficient
        kc_end=0.90,
        stage_fractions=(0.10, 0.20, 0.50, 0.20),
        crop_height_m=0.7,
        sowing_month_default=3,
        harvest_month_default=10,
        sowing_doy_default=60,
        harvest_doy_default=304,
        depletion_fraction_p=0.55,
        growth_cycle_days=244,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.3,                  # Deep roots tap subsoil moisture
        flood_resistance=2.0,
        wind_lodging_resistance=4.5,
        frost_resistance=4.6,
        extreme_heat_resistance=3.8,
        salinity_resistance=2.8,
        rusle_c_factor=0.08,                     # Panagos et al. (2015) perennial forage/grassland
        humic_conversion_k1=0.28,
        k1_above=0.16,
        k1_below=0.35,
        dry_matter_fraction=0.86,
        bolinder_rp=0.44,
        bolinder_rs=0.19,
        bolinder_rr=0.37,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=2,
        optimal_temp_min_c=7.0,
        optimal_temp_max_c=25.0,
        frost_kill_temp_c=-12.0,
        optimal_ph_min=6.5,
        optimal_ph_max=8.2,
        abs_ph_min=5.5,
        abs_ph_max=8.7,
        fao33_ky=1.10,
    ),
    "sunflowers": CropAgronomicProfile(
        crop_id="sunflowers",
        common_name="Sunflowers",
        botanical_family=BotanicalFamily.ASTERACEAE,
        category="Oilseed Cash Crop / Subsoil Scavenger",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=3.4,
        reference_yield_tons_ha=2.7,
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
        nitrogen_harvest_index=0.68,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_DEEP,
        max_rooting_depth_m=2.0,
        critical_compaction_limit_psi=310.0,
        compaction_relief_delta_psi=-25.0,      # Penetrates deep subsoil
        seasonal_water_demand_mm=390.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.05,
        fao56_kcb_end=0.25,
        kc_ini=0.35,
        kc_mid=1.10,
        kc_end=0.35,
        stage_fractions=(0.19, 0.27, 0.35, 0.19),
        crop_height_m=2.0,
        sowing_month_default=4,
        harvest_month_default=8,
        sowing_doy_default=105,
        harvest_doy_default=235,
        depletion_fraction_p=0.45,
        growth_cycle_days=130,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=4.2,
        flood_resistance=2.0,
        wind_lodging_resistance=3.0,
        frost_resistance=2.6,
        extreme_heat_resistance=4.2,
        salinity_resistance=3.0,
        rusle_c_factor=0.32,                     # Panagos et al. (2015) sunflower
        humic_conversion_k1=0.16,
        k1_above=0.12,
        k1_below=0.26,
        dry_matter_fraction=0.86,
        bolinder_rp=0.30,
        bolinder_rs=0.55,
        bolinder_rr=0.15,
        bolinder_flagged_no_published_set=True,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=2,
        optimal_temp_min_c=14.0,
        optimal_temp_max_c=29.0,
        frost_kill_temp_c=-1.0,
        optimal_ph_min=6.0,
        optimal_ph_max=7.8,
        abs_ph_min=5.0,
        abs_ph_max=8.5,
        fao33_ky=0.95,
    ),
    "canola": CropAgronomicProfile(
        crop_id="canola",
        common_name="Canola (Rapeseed)",
        botanical_family=BotanicalFamily.BRASSICACEAE,
        category="Oilseed Cash Crop / Natural Biofumigant",
        season_type="Cool/Transition Season",
        potential_yield_tons_ha=3.6,
        reference_yield_tons_ha=3.0,
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
        nitrogen_harvest_index=0.68,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_DEEP,
        max_rooting_depth_m=1.4,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=-15.0,
        seasonal_water_demand_mm=410.0,
        fao56_kcb_initial=0.20,
        fao56_kcb_mid=1.05,
        fao56_kcb_end=0.25,
        kc_ini=0.35,
        kc_mid=1.10,
        kc_end=0.35,
        stage_fractions=(0.18, 0.28, 0.34, 0.20),
        crop_height_m=0.6,
        sowing_month_default=9,
        harvest_month_default=6,
        sowing_doy_default=260,
        harvest_doy_default=170,
        depletion_fraction_p=0.60,
        growth_cycle_days=275,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.2,
        flood_resistance=2.3,
        wind_lodging_resistance=3.4,
        frost_resistance=4.2,
        extreme_heat_resistance=2.2,             # Heat stress during flowering hurts yield
        salinity_resistance=3.5,
        rusle_c_factor=0.24,                     # Panagos et al. (2015) rape
        humic_conversion_k1=0.17,
        k1_above=0.13,
        k1_below=0.27,
        dry_matter_fraction=0.86,
        bolinder_rp=0.28,
        bolinder_rs=0.56,
        bolinder_rr=0.16,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=True,                 # Glucosinolate biofumigation
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=2,
        optimal_temp_min_c=5.0,
        optimal_temp_max_c=21.0,
        frost_kill_temp_c=-8.0,
        optimal_ph_min=5.8,
        optimal_ph_max=7.8,
        abs_ph_min=5.0,
        abs_ph_max=8.3,
        fao33_ky=1.00,
    ),
    "field_peas": CropAgronomicProfile(
        crop_id="field_peas",
        common_name="Field Peas / Chickpeas",
        botanical_family=BotanicalFamily.FABACEAE,
        category="Pulse Legume / Low Water Protein Crop",
        season_type="Cool Season (Spring)",
        potential_yield_tons_ha=3.8,
        reference_yield_tons_ha=3.1,
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
        residual_soil_n_credit_kg_ha=55.0,
        nitrogen_harvest_index=0.70,
        f_bgn=2.0,                              # Unkovich et al. (2008) / Herridge et al. (2022): 2.0 for chickpea/pulses
        residue_n_release_fraction=0.40,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.TAPROOT_MEDIUM,
        max_rooting_depth_m=0.9,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=-8.0,
        seasonal_water_demand_mm=290.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.25,
        kc_ini=0.40,
        kc_mid=1.15,
        kc_end=0.30,
        stage_fractions=(0.20, 0.27, 0.33, 0.20),
        crop_height_m=0.5,
        sowing_month_default=3,
        harvest_month_default=6,
        sowing_doy_default=75,
        harvest_doy_default=175,
        depletion_fraction_p=0.45,
        growth_cycle_days=100,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.9,
        flood_resistance=1.8,                    # Very poor waterlogging tolerance
        wind_lodging_resistance=3.0,
        frost_resistance=3.8,
        extreme_heat_resistance=2.2,
        salinity_resistance=2.2,
        rusle_c_factor=0.30,                     # Panagos et al. (2015) dry pulses
        humic_conversion_k1=0.19,
        k1_above=0.14,
        k1_below=0.28,
        dry_matter_fraction=0.86,
        bolinder_rp=0.36,
        bolinder_rs=0.49,
        bolinder_rr=0.15,
        bolinder_flagged_no_published_set=False,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.ASTERACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=6.0,
        optimal_temp_max_c=22.0,
        frost_kill_temp_c=-5.0,
        optimal_ph_min=6.0,
        optimal_ph_max=7.5,
        abs_ph_min=5.0,
        abs_ph_max=8.2,
        fao33_ky=1.15,
    ),
    "processing_tomatoes": CropAgronomicProfile(
        crop_id="processing_tomatoes",
        common_name="Processing Tomatoes",
        botanical_family=BotanicalFamily.SOLANACEAE,
        category="High Gross Margin Specialty Crop",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=85.0,
        reference_yield_tons_ha=68.0,
        market_price_usd_ton=115.0,              # Contract cannery bulk field price
        seed_cost_usd_ha=950.0,                  # Plug transplants
        fixed_operational_cost_usd_ha=2400.0,    # Drip tape, fungicide blight sprays, harvest hauling
        labor_hours_per_ha=75.0,                 # Transplanting, irrigation management & harvest sorting
        machinery_passes_count=7,
        fuel_consumption_liters_ha=76.0,
        nitrogen_uptake_kg_per_ton=2.8,          # ~200 kg N/ha
        p2o5_uptake_kg_per_ton=0.9,
        k2o_uptake_kg_per_ton=4.4,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        nitrogen_harvest_index=0.60,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.8,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=620.0,
        fao56_kcb_initial=0.25,
        fao56_kcb_mid=1.15,
        fao56_kcb_end=0.70,
        kc_ini=0.60,
        kc_mid=1.15,
        kc_end=0.80,
        stage_fractions=(0.20, 0.28, 0.32, 0.20),
        crop_height_m=0.6,
        sowing_month_default=4,
        harvest_month_default=8,
        sowing_doy_default=110,
        harvest_doy_default=235,
        depletion_fraction_p=0.40,
        growth_cycle_days=125,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=2.0,
        flood_resistance=1.6,                    # Prone to root-rot / Phytophthora
        wind_lodging_resistance=3.5,
        frost_resistance=1.0,                    # Frost fatal
        extreme_heat_resistance=2.8,
        salinity_resistance=2.5,
        rusle_c_factor=0.35,                     # Panagos et al. (2015) vegetables
        humic_conversion_k1=0.10,
        k1_above=0.10,
        k1_below=0.22,
        dry_matter_fraction=0.055,               # USDA FoodData Central raw tomato (~94.5% water, replaces 0.14)
        bolinder_rp=0.48,
        bolinder_rs=0.38,
        bolinder_rr=0.14,
        bolinder_flagged_no_published_set=True,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=3,        # Strict 3-year break to avoid Fusarium/Verticillium
        optimal_temp_min_c=15.0,
        optimal_temp_max_c=30.0,
        frost_kill_temp_c=0.0,
        optimal_ph_min=6.0,
        optimal_ph_max=7.2,
        abs_ph_min=4.5,
        abs_ph_max=8.2,
        fao33_ky=1.05,
    ),
    "daikon_radish_cover": CropAgronomicProfile(
        crop_id="daikon_radish_cover",
        common_name="Daikon Radish (Tillage Cover)",
        botanical_family=BotanicalFamily.BRASSICACEAE,
        category="Hardpan Bio-Drill / Soil Restorer Cover",
        season_type="Late Summer / Fall Cover",
        potential_yield_tons_ha=5.8,
        reference_yield_tons_ha=5.0,
        market_price_usd_ton=140.0,              # Biomass/forage/seed value
        seed_cost_usd_ha=65.0,
        fixed_operational_cost_usd_ha=60.0,
        labor_hours_per_ha=1.8,
        machinery_passes_count=2,
        fuel_consumption_liters_ha=18.0,
        nitrogen_uptake_kg_per_ton=28.0,         # Scavenges residual subsoil N
        p2o5_uptake_kg_per_ton=6.0,
        k2o_uptake_kg_per_ton=30.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=40.0,
        nitrogen_harvest_index=1.0,
        f_bgn=1.35,
        residue_n_release_fraction=0.40,
        scavenged_n_credit_kg_ha=40.0,          # N_scav released upon winterkill
        root_architecture=RootArchitecture.TAPROOT_BIODRILL,
        max_rooting_depth_m=1.8,
        critical_compaction_limit_psi=360.0,
        compaction_relief_delta_psi=-65.0,      # Major biological subsoil hardpan alleviation
        seasonal_water_demand_mm=220.0,
        fao56_kcb_initial=0.15,
        fao56_kcb_mid=0.95,
        fao56_kcb_end=0.30,
        kc_ini=0.50,
        kc_mid=0.90,
        kc_end=0.70,
        stage_fractions=(0.20, 0.30, 0.35, 0.15),
        crop_height_m=0.4,
        sowing_month_default=8,
        harvest_month_default=11,
        sowing_doy_default=225,
        harvest_doy_default=320,
        depletion_fraction_p=0.50,
        growth_cycle_days=95,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_ONLY,
        drought_resistance=3.6,
        flood_resistance=2.8,
        wind_lodging_resistance=5.0,
        frost_resistance=3.5,                    # Winterkills around -6°C, creating open root channels
        extreme_heat_resistance=2.8,
        salinity_resistance=3.8,
        rusle_c_factor=0.12,
        humic_conversion_k1=0.22,
        k1_above=0.14,
        k1_below=0.30,
        dry_matter_fraction=0.12,
        bolinder_rp=0.0,                         # Cover crop: R_P = 0, all biomass returned
        bolinder_rs=0.55,
        bolinder_rr=0.45,
        bolinder_flagged_no_published_set=True,
        biofumigant_active=True,                 # Powerful biofumigant suppresses nematodes
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=6.0,
        optimal_temp_max_c=24.0,
        frost_kill_temp_c=-6.0,
        optimal_ph_min=5.8,
        optimal_ph_max=7.6,
        abs_ph_min=5.0,
        abs_ph_max=8.2,
        fao33_ky=0.70,
    ),
    "bell_peppers": CropAgronomicProfile(
        crop_id="bell_peppers",
        common_name="Bell Peppers",
        botanical_family=BotanicalFamily.SOLANACEAE,
        category="High Gross Value Specialty Vegetable",
        season_type="Warm Season (Spring/Summer)",
        potential_yield_tons_ha=29.0,
        reference_yield_tons_ha=24.0,
        market_price_usd_ton=520.0,              # Wholesale field-gate bulk price after grading/culls
        seed_cost_usd_ha=1850.0,                 # Nursery plug transplants
        fixed_operational_cost_usd_ha=3600.0,    # Plastic mulch, drip lines, stakes, IPM sprays, field cooling/packing
        labor_hours_per_ha=220.0,                # High hand-transplanting & multi-pick hand harvest labor
        machinery_passes_count=8,
        fuel_consumption_liters_ha=82.0,
        nitrogen_uptake_kg_per_ton=5.5,
        p2o5_uptake_kg_per_ton=1.8,
        k2o_uptake_kg_per_ton=7.2,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        nitrogen_harvest_index=0.60,
        f_bgn=1.25,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.7,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=580.0,
        fao56_kcb_initial=0.25,
        fao56_kcb_mid=1.10,
        fao56_kcb_end=0.80,
        kc_ini=0.60,
        kc_mid=1.05,
        kc_end=0.90,
        stage_fractions=(0.20, 0.28, 0.32, 0.20),
        crop_height_m=0.7,
        sowing_month_default=5,
        harvest_month_default=9,
        sowing_doy_default=125,
        harvest_doy_default=260,
        depletion_fraction_p=0.35,
        growth_cycle_days=135,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=1.8,
        flood_resistance=1.5,
        wind_lodging_resistance=2.8,
        frost_resistance=1.0,
        extreme_heat_resistance=2.6,
        salinity_resistance=2.1,
        rusle_c_factor=0.35,                     # Panagos et al. (2015) vegetables
        humic_conversion_k1=0.11,
        k1_above=0.10,
        k1_below=0.22,
        dry_matter_fraction=0.08,                # USDA FDC raw sweet pepper (~92% water)
        bolinder_rp=0.42,
        bolinder_rs=0.43,
        bolinder_rr=0.15,
        bolinder_flagged_no_published_set=True,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=3,
        optimal_temp_min_c=16.0,
        optimal_temp_max_c=29.0,
        frost_kill_temp_c=0.5,
        optimal_ph_min=6.0,
        optimal_ph_max=7.0,
        abs_ph_min=4.8,
        abs_ph_max=8.0,
        fao33_ky=1.10,
    ),
    "spinach": CropAgronomicProfile(
        crop_id="spinach",
        common_name="Spinach (Fresh / Processing)",
        botanical_family=BotanicalFamily.AMARANTHACEAE,
        category="Rapid Cycle Leafy Green / Cool-Season Cash Crop",
        season_type="Cool Season (Spring or Autumn)",
        potential_yield_tons_ha=16.5,
        reference_yield_tons_ha=13.5,
        market_price_usd_ton=340.0,              # Bulk farm-gate wholesale/freezer contract price
        seed_cost_usd_ha=420.0,
        fixed_operational_cost_usd_ha=1650.0,    # Precision bed prep, downy mildew control, hydrocooling/hauling
        labor_hours_per_ha=65.0,                 # Precision scouting, hand weeding & perishable harvest handling
        machinery_passes_count=4,
        fuel_consumption_liters_ha=36.0,
        nitrogen_uptake_kg_per_ton=8.0,
        p2o5_uptake_kg_per_ton=2.5,
        k2o_uptake_kg_per_ton=11.0,
        is_legume=False,
        ndfa_fraction=0.0,
        residual_soil_n_credit_kg_ha=0.0,
        nitrogen_harvest_index=0.90,
        f_bgn=1.20,
        residue_n_release_fraction=0.25,
        scavenged_n_credit_kg_ha=0.0,
        root_architecture=RootArchitecture.FIBROUS_SHALLOW,
        max_rooting_depth_m=0.5,
        critical_compaction_limit_psi=290.0,
        compaction_relief_delta_psi=0.0,
        seasonal_water_demand_mm=260.0,
        fao56_kcb_initial=0.30,
        fao56_kcb_mid=1.00,
        fao56_kcb_end=0.90,
        kc_ini=0.70,
        kc_mid=1.00,
        kc_end=0.95,
        stage_fractions=(0.25, 0.30, 0.35, 0.10),
        crop_height_m=0.3,
        sowing_month_default=3,
        harvest_month_default=5,
        sowing_doy_default=75,
        harvest_doy_default=135,
        depletion_fraction_p=0.30,
        growth_cycle_days=60,
        greenhouse_requirement=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE,
        drought_resistance=2.0,
        flood_resistance=2.0,
        wind_lodging_resistance=4.8,
        frost_resistance=4.6,                    # Cold tolerant down to -4°C
        extreme_heat_resistance=1.3,             # Bolting above 24°C
        salinity_resistance=3.2,
        rusle_c_factor=0.25,
        humic_conversion_k1=0.15,
        k1_above=0.11,
        k1_below=0.22,
        dry_matter_fraction=0.09,                # USDA FDC raw spinach (~91% water)
        bolinder_rp=0.65,
        bolinder_rs=0.18,
        bolinder_rr=0.17,
        bolinder_flagged_no_published_set=True,
        biofumigant_active=False,
        pest_break_families=[BotanicalFamily.POACEAE, BotanicalFamily.SOLANACEAE, BotanicalFamily.FABACEAE],
        rotational_break_needed_years=1,
        optimal_temp_min_c=6.0,
        optimal_temp_max_c=21.0,
        frost_kill_temp_c=-6.0,
        optimal_ph_min=6.2,
        optimal_ph_max=7.5,
        abs_ph_min=5.5,
        abs_ph_max=8.3,
        fao33_ky=0.90,
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
