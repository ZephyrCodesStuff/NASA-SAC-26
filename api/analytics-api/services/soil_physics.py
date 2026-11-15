"""
Scientific Soil Physics, Organic Carbon, Compaction, and Hydrology Engine.
Implements:
1. Henin-Dupuis & IPCC Tier 2 Soil Organic Carbon (SOC) dynamics (k1, k2, Bolinder root C)
2. ASAE S313.3 Cone Penetrometer Compaction & Bio-Drilling Taproot Alleviation
3. Herridge & Peoples Biological Nitrogen Fixation (BNF) equations
4. FAO-56 Penman-Monteith ET0 & Dual Crop Coefficient water balance
5. RUSLE topsoil erosion modeling
6. Botanical pathology break matrices
"""

import math
from typing import Dict, Any, Tuple, Optional
from projection_api.models.crops_catalog import CropAgronomicProfile, BotanicalFamily, RootArchitecture


# Soil physical benchmarks mapped to SoilTypeEnum
SOIL_PHYSICAL_PROPERTIES: Dict[str, Dict[str, float]] = {
    "clay": {
        "clay_pct": 48.0,
        "sand_pct": 20.0,
        "bulk_density_g_cm3": 1.25,
        "theta_fc": 0.40,
        "theta_wp": 0.27,
        "theta_sat": 0.51,
        "ksat_mm_hr": 1.5,
        "rusle_k_factor": 0.024,
    },
    "clay_loam": {
        "clay_pct": 32.0,
        "sand_pct": 32.0,
        "bulk_density_g_cm3": 1.30,
        "theta_fc": 0.33,
        "theta_wp": 0.19,
        "theta_sat": 0.47,
        "ksat_mm_hr": 4.5,
        "rusle_k_factor": 0.030,
    },
    "loam": {
        "clay_pct": 20.0,
        "sand_pct": 40.0,
        "bulk_density_g_cm3": 1.35,
        "theta_fc": 0.27,
        "theta_wp": 0.13,
        "theta_sat": 0.46,
        "ksat_mm_hr": 13.0,
        "rusle_k_factor": 0.034,
    },
    "sandy_loam": {
        "clay_pct": 10.0,
        "sand_pct": 65.0,
        "bulk_density_g_cm3": 1.45,
        "theta_fc": 0.20,
        "theta_wp": 0.09,
        "theta_sat": 0.43,
        "ksat_mm_hr": 26.0,
        "rusle_k_factor": 0.026,
    },
    "silt_loam": {
        "clay_pct": 18.0,
        "sand_pct": 18.0,
        "bulk_density_g_cm3": 1.32,
        "theta_fc": 0.33,
        "theta_wp": 0.14,
        "theta_sat": 0.48,
        "ksat_mm_hr": 8.0,
        "rusle_k_factor": 0.042,
    },
    "sand": {
        "clay_pct": 4.0,
        "sand_pct": 92.0,
        "bulk_density_g_cm3": 1.55,
        "theta_fc": 0.10,
        "theta_wp": 0.04,
        "theta_sat": 0.38,
        "ksat_mm_hr": 110.0,
        "rusle_k_factor": 0.015,
    },
}


class SoilPhysicsEngine:
    """Scientific calculator for ground impact, soil chemistry, compaction, and hydrology."""

    @staticmethod
    def get_soil_properties(soil_type: str) -> Dict[str, float]:
        clean = soil_type.lower().replace(" ", "_").replace("-", "_")
        if clean in SOIL_PHYSICAL_PROPERTIES:
            return SOIL_PHYSICAL_PROPERTIES[clean]
        for k, v in SOIL_PHYSICAL_PROPERTIES.items():
            if k in clean or clean in k:
                return v
        return SOIL_PHYSICAL_PROPERTIES["loam"]

    @staticmethod
    def calculate_fao56_penman_monteith_et0(
        t_max: float,
        t_min: float,
        solar_rad_mj_m2: float,
        wind_speed_2m: float,
        rh_mean: float = 60.0,
        elevation_m: float = 100.0,
        latitude_deg: float = 40.0,
        day_of_year: int = 180
    ) -> float:
        """Computes daily reference evapotranspiration (ET0) via FAO-56 Penman-Monteith."""
        t_mean = (t_max + t_min) / 2.0
        p = 101.3 * math.pow((293.0 - 0.0065 * elevation_m) / 293.0, 5.26)
        gamma = 0.000665 * p
        delta = (4098.0 * (0.6108 * math.exp((17.27 * t_mean) / (t_mean + 237.3)))) / math.pow(t_mean + 237.3, 2)

        e0_tmax = 0.6108 * math.exp((17.27 * t_max) / (t_max + 237.3))
        e0_tmin = 0.6108 * math.exp((17.27 * t_min) / (t_min + 237.3))
        es = (e0_tmax + e0_tmin) / 2.0
        ea = min(es, (max(5.0, min(100.0, rh_mean)) / 100.0) * es)
        vpd = max(0.0, es - ea)

        # Extraterrestrial radiation Ra
        lat_rad = math.radians(latitude_deg)
        dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
        sol_dec = 0.409 * math.sin((2.0 * math.pi * day_of_year / 365.0) - 1.39)
        tan_val = max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(sol_dec)))
        ws = math.acos(tan_val)
        ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
            ws * math.sin(lat_rad) * math.sin(sol_dec) +
            math.cos(lat_rad) * math.cos(sol_dec) * math.sin(ws)
        )
        ra = max(0.1, ra)
        rso = (0.75 + 2e-5 * elevation_m) * ra
        rns = (1.0 - 0.23) * solar_rad_mj_m2

        # Net longwave Rnl
        sigma = 4.903e-9
        t_max_k4 = math.pow(t_max + 273.16, 4)
        t_min_k4 = math.pow(t_min + 273.16, 4)
        rel_solar = min(1.0, max(0.3, solar_rad_mj_m2 / max(rso, 0.1)))
        rnl = max(0.0, sigma * ((t_max_k4 + t_min_k4) / 2.0) * (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * rel_solar - 0.35))
        rn = rns - rnl

        u2 = max(0.5, wind_speed_2m)
        num = 0.408 * delta * rn + gamma * (900.0 / (t_mean + 273.0)) * u2 * vpd
        den = delta + gamma * (1.0 + 0.34 * u2)
        return max(0.0, round(num / den, 2))

    @staticmethod
    def simulate_crop_hydrology(
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        annual_et0_mm: float,
        annual_precip_mm: float,
        smap_rootzone_moisture: float = 0.25,
        seasonal_et0_override_mm: Optional[float] = None,
        seasonal_precip_override_mm: Optional[float] = None,
        has_irrigation: bool = True,
        water_quota_mm_ha: Optional[float] = None,
    ) -> Tuple[float, float, float, float, float]:
        """
        Simulates seasonal FAO-56 dual crop water balance:
        Returns: (water_demand_etc_mm, effective_precip_mm, irrigation_needed_mm, irrigation_m3_ha, stress_ks)
        """
        is_cool = "cool" in crop.season_type.lower() or "cover" in crop.season_type.lower()
        is_perennial = "perennial" in crop.season_type.lower()

        if seasonal_et0_override_mm is not None and seasonal_et0_override_mm > 0:
            seasonal_et0 = seasonal_et0_override_mm * min(1.0, crop.growth_cycle_days / (210.0 if is_cool else 160.0))
        else:
            # Seasonal radiative concentration: summer crops transpire more ET0 per day than cool/winter crops
            et_weight = 0.72 if not is_cool and not is_perennial else (0.30 if is_cool else 0.90)
            seasonal_et0 = annual_et0_mm * et_weight * min(1.0, crop.growth_cycle_days / (210.0 if is_cool else 165.0))

        # FAO-56 Kc time-weighted average across growth stages
        kc_seasonal = (crop.fao56_kcb_initial * 0.2) + (crop.fao56_kcb_mid * 0.5) + (crop.fao56_kcb_end * 0.3)
        etc_mm = max(80.0, round(seasonal_et0 * kc_seasonal, 1))

        # Effective precipitation via USDA SCS approximation over the active growing window
        if seasonal_precip_override_mm is not None and seasonal_precip_override_mm >= 0:
            seasonal_rain = seasonal_precip_override_mm * min(1.0, crop.growth_cycle_days / (210.0 if is_cool else 160.0))
        else:
            rain_weight = 0.48 if not is_cool and not is_perennial else (0.52 if is_cool else 0.85)
            seasonal_rain = annual_precip_mm * rain_weight * min(1.0, crop.growth_cycle_days / (210.0 if is_cool else 165.0))
        peff_mm = max(0.0, round(0.75 * seasonal_rain - 10.0, 1))

        # Root zone storage and available water capacity
        zr = crop.max_rooting_depth_m
        taw_mm = 1000.0 * (soil_props["theta_fc"] - soil_props["theta_wp"]) * zr
        raw_mm = taw_mm * crop.depletion_fraction_p

        # Available moisture currently stored in root zone
        theta_curr = max(soil_props["theta_wp"], min(soil_props["theta_fc"], smap_rootzone_moisture))
        available_soil_water_mm = 1000.0 * (theta_curr - soil_props["theta_wp"]) * zr

        # Seasonal crop water deficit before irrigation
        net_water_deficit_mm = max(0.0, etc_mm - peff_mm - (available_soil_water_mm * 0.4))

        if has_irrigation:
            desired_irrigation_mm = round(net_water_deficit_mm / 0.85, 1)
            if water_quota_mm_ha is not None:
                irrigation_applied_mm = round(min(desired_irrigation_mm, max(0.0, water_quota_mm_ha)), 1)
            else:
                irrigation_applied_mm = desired_irrigation_mm
            effective_irrig_mm = irrigation_applied_mm * 0.85
            unmet_deficit_mm = max(0.0, net_water_deficit_mm - effective_irrig_mm)
        else:
            irrigation_applied_mm = 0.0
            unmet_deficit_mm = net_water_deficit_mm

        irrigation_volume_m3 = round(irrigation_applied_mm * 10.0, 1)  # 1 mm = 10 m3/ha

        # FAO-56 Ks water stress coefficient applies ONLY to remaining unmet deficit
        if unmet_deficit_mm > raw_mm:
            ks = max(0.30, (taw_mm - unmet_deficit_mm) / max(1.0, (1.0 - crop.depletion_fraction_p) * taw_mm))
        else:
            ks = 1.0

        return etc_mm, peff_mm, irrigation_applied_mm, irrigation_volume_m3, round(ks, 2)

    @staticmethod
    def simulate_soc_dynamics(
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        current_soc_pct: float,
        mean_annual_temp_c: float = 14.0,
        tillage_factor: float = 1.0,  # 1.0 for conventional, 0.7 for min-till, 0.5 for no-till
        plow_depth_m: float = 0.30,
        actual_yield_tons_ha: Optional[float] = None,
        soilgrids_clay_pct: Optional[float] = None,
        soilgrids_bulk_density_g_cm3: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Henin-Dupuis & IPCC Tier 2 model of Soil Organic Carbon evolution.
        Returns: (soc_pct_end, delta_soc_pct, carbon_input_tons_ha, k2_rate)
        """
        rho_b = soilgrids_bulk_density_g_cm3 or soil_props["bulk_density_g_cm3"]
        clay_pct = soilgrids_clay_pct if soilgrids_clay_pct is not None else soil_props["clay_pct"]

        # Initial SOC stock (t C / ha in top 30cm)
        # Stock (t C/ha) = 100 * rho_b (g/cm3) * depth (m) * SOC %
        c_stock_start = 100.0 * rho_b * plow_depth_m * current_soc_pct

        # Annual mineralization rate k2 (Machet / Mary-Guérif formulation):
        # Perennial unplowed sod (Alfalfa) reduces soil disturbance and microbial oxidation
        is_perennial = "perennial" in crop.season_type.lower() or crop.crop_id == "alfalfa"
        effective_tillage = 0.50 if is_perennial else tillage_factor
        k2_base = max(0.012, (1.2 * max(6.0, mean_annual_temp_c) - 6.0) / (10.0 * clay_pct + 200.0))
        k2 = k2_base * effective_tillage

        # Carbon input from crop residues scaled by actual simulated yield (fresh weight -> DM approx)
        harvested_yield = actual_yield_tons_ha if actual_yield_tons_ha is not None else crop.potential_yield_tons_ha
        # Fresh horticultural produce (peppers, tomatoes, spinach) is ~85-92% water, dry grains ~14% moisture
        dm_factor = 0.14 if crop.botanical_family == BotanicalFamily.SOLANACEAE or crop.crop_id == "spinach" else 0.86
        dry_matter_yield = harvested_yield * dm_factor
        # Aboveground residue
        if crop.crop_id in ("alfalfa", "daikon_radish_cover"):
            ag_residue_c = dry_matter_yield * 0.35 * crop.biomass_carbon_fraction
            bg_root_c = dry_matter_yield * 0.65 * crop.biomass_carbon_fraction  # deep taproot allocation
        else:
            harvest_index = 0.45 if crop.is_legume else 0.50
            ag_residue = (dry_matter_yield * (1.0 - harvest_index) / harvest_index) * 0.85
            ag_residue_c = ag_residue * crop.biomass_carbon_fraction
            bg_root_c = (dry_matter_yield / harvest_index) * 0.22 * 1.5 * crop.biomass_carbon_fraction

        total_c_input = ag_residue_c + bg_root_c  # t C / ha / yr

        # Henin-Dupuis humic balance: dC/dt = k1 * A - k2 * C
        k1 = crop.humic_conversion_k1
        humified_c = k1 * total_c_input
        mineralized_c = k2 * c_stock_start
        delta_c_stock = humified_c - mineralized_c

        c_stock_end = max(10.0, c_stock_start + delta_c_stock)
        soc_pct_end = round(c_stock_end / (100.0 * rho_b * plow_depth_m), 3)
        delta_soc_pct = round(soc_pct_end - current_soc_pct, 3)

        return soc_pct_end, delta_soc_pct, round(total_c_input, 2), round(k2, 4)

    @staticmethod
    def simulate_soil_compaction(
        crop: CropAgronomicProfile,
        current_compaction_psi: float,
        soil_props: Dict[str, float]
    ) -> Tuple[float, float]:
        """
        Simulates ASAE S313.3 Cone Penetrometer Compaction dynamics:
        - Machinery traffic adds compaction with diminishing returns per pass.
        - Deep taproots and bio-drill crops (Daikon radish, Alfalfa) fracture plowpans.
        Returns: (compaction_psi_end, compaction_delta_psi)
        """
        # Traffic compaction accumulation proportional to axle passes (avoids saturating at 2 passes)
        passes = max(1, crop.machinery_passes_count)
        traffic_addition = 8.0 + (4.0 * min(10, passes))

        # Heavy clay is more susceptible to wheel compaction
        clay_factor = 1.0 + (soil_props["clay_pct"] / 100.0)
        traffic_psi = traffic_addition * clay_factor

        # Bio-drill taproot hardpan alleviation (e.g. -65 PSI for Daikon Radish, -55 PSI for Alfalfa)
        relief_psi = crop.compaction_relief_delta_psi

        delta_psi = round(traffic_psi + relief_psi, 1)
        final_psi = max(120.0, min(380.0, current_compaction_psi + delta_psi))
        actual_delta = round(final_psi - current_compaction_psi, 1)
        return round(final_psi, 1), actual_delta

    @staticmethod
    def calculate_nitrogen_balance(
        crop: CropAgronomicProfile,
        yield_tons_ha: float,
        preceding_legume_credit_kg_ha: float = 0.0,
        in_situ_soil_nitrate_ppm: float = 25.0,
        in_situ_soil_n_kg_ha: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Herridge & Peoples Symbiotic Biological Nitrogen Fixation and N Balance.
        Returns: (net_soil_n_balance_kg_ha, biological_n_fixed_kg_ha, synthetic_n_applied_kg_ha, legume_credit_used)
        """
        # Total nitrogen uptake requirement
        total_n_required = yield_tons_ha * crop.nitrogen_uptake_kg_per_ton

        # Avoid unit bug: only multiply ppm -> kg/ha (~2.2 in top 18cm at 1.25 g/cm3) when kg/ha not passed directly
        available_soil_mineral_n = (
            in_situ_soil_n_kg_ha
            if in_situ_soil_n_kg_ha is not None
            else (in_situ_soil_nitrate_ppm * 2.2)
        )

        if crop.is_legume:
            # Fixes atmospheric N via rhizobial nodules (%Ndfa)
            plant_n = total_n_required * 1.35
            bio_fixed_n = plant_n * crop.ndfa_fraction
            seed_harvest_removal = yield_tons_ha * crop.nitrogen_uptake_kg_per_ton
            net_n_balance = bio_fixed_n - seed_harvest_removal + crop.residual_soil_n_credit_kg_ha
            synthetic_n_applied = 0.0
            legume_credit_used = 0.0
        else:
            bio_fixed_n = 0.0
            legume_credit_used = min(total_n_required, preceding_legume_credit_kg_ha)
            # Only ~30% of baseline mineral pool is immediately plant-available without luxury mining
            mineral_contribution = min(total_n_required * 0.45, available_soil_mineral_n * 0.30)
            remaining_demand = max(0.0, total_n_required - legume_credit_used - mineral_contribution)
            synthetic_n_applied = round(remaining_demand, 1)
            # Partial mass balance: inputs + scavenged cover-crop spring credit minus harvested export
            net_n_balance = max(
                -80.0,
                synthetic_n_applied + legume_credit_used + crop.residual_soil_n_credit_kg_ha - total_n_required,
            )

        return round(net_n_balance, 1), round(bio_fixed_n, 1), synthetic_n_applied, round(legume_credit_used, 1)

    @staticmethod
    def calculate_rusle_erosion(
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        slope_pct: float,
        annual_precip_mm: float,
        soilgrids_sand_pct: Optional[float] = None,
        soilgrids_silt_pct: Optional[float] = None,
        soilgrids_clay_pct: Optional[float] = None,
        soilgrids_soc_pct: Optional[float] = None,
        area_hectares: float = 10.0,
    ) -> float:
        """
        Revised Universal Soil Loss Equation (RUSLE): A = R * K * LS * C * P (t / ha / yr).
        Uses Renard & Freimund (1994) R, Williams (1995) EPIC K (when SoilGrids fractions provided),
        Moore & Burch (1986) LS, and P = 1.0 (no unverified support practices assumed).
        """
        # Rainfall erosivity factor R (Renard & Freimund 1994, MJ mm / (ha h yr))
        p_mm = max(50.0, annual_precip_mm)
        if p_mm <= 850.0:
            r_factor = max(40.0, 0.04830 * (p_mm ** 1.61))
        else:
            r_factor = max(40.0, 587.8 - (1.219 * p_mm) + (0.004105 * (p_mm ** 2)))

        # Soil erodibility factor K: EPIC Williams (1995) when particle fractions exist, else texture lookup
        if (
            soilgrids_sand_pct is not None
            and soilgrids_silt_pct is not None
            and soilgrids_clay_pct is not None
        ):
            sand = max(0.0, min(100.0, soilgrids_sand_pct))
            silt = max(0.0, min(100.0, soilgrids_silt_pct))
            clay = max(0.0, min(100.0, soilgrids_clay_pct))
            soc = max(0.1, soilgrids_soc_pct if soilgrids_soc_pct is not None else 1.5)
            sn1 = 1.0 - sand / 100.0
            f_csand = 0.2 + 0.3 * math.exp(-0.256 * sand * (1.0 - silt / 100.0))
            f_cl_si = (silt / max(1.0, clay + silt)) ** 0.3
            f_orgc = 1.0 - (0.25 * soc) / (soc + math.exp(3.72 - 2.95 * soc))
            f_hisand = 1.0 - (0.7 * sn1) / (sn1 + math.exp(-5.51 + 22.9 * sn1))
            # EPIC K in t*ha*h / (ha*MJ*mm) (~0.1317 conversion from US customary)
            k_factor = max(0.005, min(0.08, f_csand * f_cl_si * f_orgc * f_hisand * 0.1317))
        else:
            # Convert US customary RUSLE K (~0.20-0.42) to SI EPIC units cleanly if needed (~x0.1317)
            k_factor = soil_props["rusle_k_factor"] * 0.1317

        # Moore & Burch (1986) unit stream power LS factor capped for field flow path (~sqrt(area_m2)/2, max 150m)
        slope_rad = math.atan(max(0.1, slope_pct) / 100.0)
        flow_length_m = max(22.13, min(150.0, math.sqrt(max(0.5, area_hectares) * 10000.0) * 0.5))
        ls_factor = max(
            0.05,
            ((flow_length_m / 22.13) ** 0.4) * ((math.sin(slope_rad) / 0.0896) ** 1.3),
        )
        c_factor = crop.rusle_c_factor
        # Do not invent conservation terracing/contouring unless explicitly surveyed
        p_factor = 1.0

        erosion_tons_ha = r_factor * k_factor * ls_factor * c_factor * p_factor
        return round(max(0.05, erosion_tons_ha), 2)

    @staticmethod
    def evaluate_rotational_health(
        current_crop: CropAgronomicProfile,
        preceding_crop: Optional[CropAgronomicProfile]
    ) -> Tuple[float, float, float]:
        """
        Evaluates Botanical Pathology Risk & Rhizosphere Vitality (returns 0.0 arbitrary USD fines;
        pest/disease rotation breaks are enforced via agronomic eligibility and yield penalties).
        Returns: (pathogen_risk_score, rhizosphere_score, botanical_penalty_usd_ha)
        """
        if preceding_crop is None:
            return 25.0, 70.0, 0.0

        same_family = current_crop.botanical_family == preceding_crop.botanical_family

        if same_family:
            if current_crop.botanical_family == BotanicalFamily.SOLANACEAE:
                return 85.0, 30.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.BRASSICACEAE:
                return 75.0, 40.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.FABACEAE:
                return 70.0, 45.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.POACEAE:
                return 65.0, 50.0, 0.0
            else:
                return 60.0, 55.0, 0.0

        # Beneficial botanical rotation
        pathogen_score = 20.0
        rhizosphere_score = 80.0

        # Biofumigant bonus (Canola or Daikon Radish suppresses soil-borne nematodes)
        if preceding_crop.biofumigant_active:
            pathogen_score -= 10.0
            rhizosphere_score += 10.0

        # Legume followed by cereal synergy
        if preceding_crop.is_legume and not current_crop.is_legume:
            rhizosphere_score += 10.0

        return max(5.0, pathogen_score), min(100.0, rhizosphere_score), 0.0
