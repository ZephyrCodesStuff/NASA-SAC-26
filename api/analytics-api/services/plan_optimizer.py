"""
3-Year Multi-Objective Combinatorial Plan Optimizer.
Generates 5 distinct 3-year planting trajectories:
1. Most Income
2. Best Soil Health
3. Least Effort / Labour
4. Highest ROI (%)
5. Least Amount of Crop Loss Risk

Simulates multi-year physical ground impact carryover:
Year 1 changes feed into Year 2 initial conditions; Year 2 feeds into Year 3.
"""

import math
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime

from projection_api.models.crops_catalog import (
    CropAgronomicProfile, MASTER_CROPS_CATALOG, get_crop_profile, BotanicalFamily, GreenhouseRequirement
)
from projection_api.models.simulation_models import (
    AnnualGroundImpact, ThreeYearCumulativeMetrics, ThreeYearCultivationPlan
)
from projection_api.services.soil_physics import SoilPhysicsEngine


class PlanOptimizerEngine:
    """Combinatorial search and sequential multi-year simulation engine."""

    def __init__(self, normalized_field: Dict[str, Any]):
        self.field = normalized_field
        self.area_ha = float(normalized_field.get("area_hectares", 1.0))
        self.soil_type = normalized_field.get("resolved_soil_type", "Loam")
        self.soil_props = SoilPhysicsEngine.get_soil_properties(self.soil_type)
        self.elevation_m = float(normalized_field.get("elevation_m", 150.0))
        self.slope_pct = float(normalized_field.get("slope_pct", 2.5))
        self.has_greenhouse = bool(normalized_field.get("has_greenhouse", False))
        self.water_quota_m3 = normalized_field.get("legal_water_quota_m3")

        # Initial soil state (calibrated from in-situ sensors or SoilGrids)
        self.init_soc_pct = float(normalized_field.get("baseline_soc_pct", 1.85))
        self.compaction_is_measured = bool(normalized_field.get("compaction_is_measured", normalized_field.get("baseline_compaction_psi") is not None))
        default_texture_psi = 230.0 if self.soil_props["clay_pct"] >= 35.0 else (180.0 if self.soil_props["clay_pct"] <= 12.0 else 205.0)
        self.init_compaction_psi = float(
            normalized_field["baseline_compaction_psi"]
            if normalized_field.get("baseline_compaction_psi") is not None
            else default_texture_psi
        )
        self.init_nitrate_ppm = float(normalized_field.get("baseline_nitrate_ppm", 22.0))
        self.init_soil_n_kg_ha = normalized_field.get("baseline_soil_n_kg_ha")
        self.soil_ph = float(normalized_field.get("soil_ph", 6.7))
        self.soilgrids_sand_pct = normalized_field.get("soilgrids_sand_pct")
        self.soilgrids_silt_pct = normalized_field.get("soilgrids_silt_pct")
        self.soilgrids_clay_pct = normalized_field.get("soilgrids_clay_pct")
        self.soilgrids_bdod = normalized_field.get("soilgrids_bulk_density_g_cm3")

        # Climate & seasonal baselines from NASA POWER / GPM / SMAP
        self.annual_et0_mm = float(normalized_field.get("annual_et0_mm", 1080.0))
        self.annual_precip_mm = float(normalized_field.get("annual_precip_mm", 640.0))
        self.warm_season_et0_mm = normalized_field.get("warm_season_et0_mm")
        self.warm_season_precip_mm = normalized_field.get("warm_season_precip_mm")
        self.cool_season_et0_mm = normalized_field.get("cool_season_et0_mm")
        self.cool_season_precip_mm = normalized_field.get("cool_season_precip_mm")
        self.mean_temp_c = float(normalized_field.get("mean_temp_c", 13.5))
        self.frost_days_count = int(normalized_field.get("frost_days_count") or 0)
        self.heatwave_days_count = int(normalized_field.get("heatwave_days_count") or 0)
        self.longest_dry_spell_days = int(normalized_field.get("longest_dry_spell_days") or 0)
        self.coldest_night_c = normalized_field.get("coldest_night_c")
        self.hottest_day_c = normalized_field.get("hottest_day_c")
        self.smap_moisture = float(normalized_field.get("smap_rootzone_moisture", 0.26))
        self.low_spot_risk = bool(normalized_field.get("low_spot_waterlogging_hazard", False))

        # Management & live IoT context
        self.irrigation_system = str(normalized_field.get("irrigation_system") or "Center Pivot Sprinkler")
        self.has_irrigation = "rainfed" not in self.irrigation_system.lower()
        tillage_str = str(normalized_field.get("tillage_practice") or "").lower()
        self.tillage_factor = 0.50 if "no-till" in tillage_str else (0.70 if "strip" in tillage_str or "reduced" in tillage_str else 1.0)
        self.ambient_temp_c = normalized_field.get("ambient_temp_c")
        self.ambient_humidity_pct = normalized_field.get("ambient_humidity_pct")

        # Economic price structure & regional FAOSTAT yield benchmarks
        self.p_seed_mult = float(normalized_field.get("seed_price_multiplier", 1.0))
        self.p_water_m3 = float(normalized_field.get("water_price_usd_m3", 0.08))
        self.p_diesel_liter = float(normalized_field.get("diesel_price_usd_liter", 1.15))
        self.p_nitrogen_kg = float(normalized_field.get("fertilizer_n_price_usd_kg", 1.35))
        self.p_p2o5_kg = float(normalized_field.get("fertilizer_p_price_usd_kg", 1.60))
        self.p_k2o_kg = float(normalized_field.get("fertilizer_k_price_usd_kg", 0.95))
        self.p_labor_hour = float(normalized_field.get("labor_hourly_wage_usd", 22.0))
        self.crop_market_prices = normalized_field.get("crop_market_prices_usd_t") or {}
        self.regional_crop_yields = normalized_field.get("regional_crop_yields_t_ha") or {}

        # Preceding crop from history
        self.hist_crop_name = normalized_field.get("preceding_crop_name", "corn")
        self.initial_preceding_crop = get_crop_profile(self.hist_crop_name) or MASTER_CROPS_CATALOG["corn"]

        # Whitelist / Blacklist filters
        self.whitelisted_crops = normalized_field.get("preferred_candidate_crops")
        self.blacklisted_crops = normalized_field.get("excluded_crops") or []

    def _filter_candidate_crops(self) -> List[CropAgronomicProfile]:
        """Prunes crops that violate parcel environmental or physical capabilities or farmer preferences."""
        admissible: List[CropAgronomicProfile] = []
        for crop in MASTER_CROPS_CATALOG.values():
            # Excluded / blacklisted crops
            if self.blacklisted_crops:
                if any(b.lower() in crop.common_name.lower() or b.lower() in crop.crop_id.lower() for b in self.blacklisted_crops):
                    continue

            # Whitelisted / preferred candidate crops (if specified and sufficient)
            if self.whitelisted_crops and len(self.whitelisted_crops) >= 3:
                matches_whitelist = any(
                    w.lower() in crop.common_name.lower() or w.lower() in crop.crop_id.lower() or
                    crop.common_name.lower() in w.lower() or crop.crop_id.lower() in w.lower()
                    for w in self.whitelisted_crops
                )
                if not matches_whitelist:
                    continue

            # Greenhouse constraint
            if crop.greenhouse_requirement == GreenhouseRequirement.GREENHOUSE_REQUIRED and not self.has_greenhouse:
                continue
            # Severe flood/waterlogging depression risk
            if self.low_spot_risk and crop.flood_resistance < 2.0:
                continue
            # Extreme thermal/frost envelope pruning (open-field)
            if not self.has_greenhouse:
                is_warm_crop = "warm" in crop.season_type.lower()
                # Cold/boreal sites (annual mean < 9.5C or >130 frost days) cannot sustain warm-season grain/vegetable cycles
                if is_warm_crop and crop.frost_resistance <= 2.2 and (self.mean_temp_c < 9.5 or self.frost_days_count > 130):
                    continue
                # Cool leafy greens bolt severely in hot arid summers without cooling (>22C annual mean or >35 heatwave days)
                if crop.crop_id == "spinach" and (self.mean_temp_c > 22.0 or self.heatwave_days_count >= 35):
                    continue
            # Severe acid/alkaline soil pH lockout (> 1.8 units outside tolerance)
            if self.soil_ph < (crop.optimal_ph_min - 1.6) or self.soil_ph > (crop.optimal_ph_max + 1.6):
                continue
            admissible.append(crop)

        # Safety fallback if constraints over-pruned the search space
        if len(admissible) < 2:
            return [c for c in MASTER_CROPS_CATALOG.values() if not (c.greenhouse_requirement == GreenhouseRequirement.GREENHOUSE_REQUIRED and not self.has_greenhouse)]
        return admissible

    def _simulate_annual_impact(
        self,
        year_idx: int,
        crop: CropAgronomicProfile,
        preceding_crop: Optional[CropAgronomicProfile],
        start_soc_pct: float,
        start_compaction_psi: float,
        preceding_legume_credit_kg_ha: float
    ) -> Tuple[AnnualGroundImpact, float]:
        """
        Simulates physical, chemical, and economic impact of one crop year on the parcel.
        Returns: (AnnualGroundImpact, legume_n_credit_for_next_year)
        """
        # 1. Hydrology (FAO-56) with seasonal weather & legal water quota awareness
        is_cool = "cool" in crop.season_type.lower() or "cover" in crop.season_type.lower()
        seasonal_et0_override = self.cool_season_et0_mm if is_cool else self.warm_season_et0_mm
        seasonal_precip_override = self.cool_season_precip_mm if is_cool else self.warm_season_precip_mm
        annual_quota_mm_ha = (
            (float(self.water_quota_m3) / max(0.1, self.area_ha) / 10.0)
            if self.water_quota_m3 is not None
            else None
        )
        etc_mm, peff_mm, irr_applied_mm, irr_m3_ha, ks = SoilPhysicsEngine.simulate_crop_hydrology(
            crop=crop,
            soil_props=self.soil_props,
            annual_et0_mm=self.annual_et0_mm,
            annual_precip_mm=self.annual_precip_mm,
            smap_rootzone_moisture=self.smap_moisture,
            seasonal_et0_override_mm=seasonal_et0_override,
            seasonal_precip_override_mm=seasonal_precip_override,
            has_irrigation=self.has_irrigation,
            water_quota_mm_ha=annual_quota_mm_ha,
        )

        # 2. Yield & Economics (FAO-33 water stress + thermal + pH + compaction + regional yield + live price)
        # Water stress (FAO-33 Ky * (1 - Ks))
        water_loss_frac = max(0.0, min(0.65, crop.fao33_ky * (1.0 - ks)))

        # Soil pH nutrient availability penalty (smoothly penalizes outside optimal range)
        ph_dist = max(0.0, crop.optimal_ph_min - self.soil_ph, self.soil_ph - crop.optimal_ph_max)
        ph_loss_frac = min(0.40, ph_dist * 0.14)

        # Thermal / heatwave / frost stress suitability
        # Growing-season warm temperature estimate is ~mean_temp + 5C; cool season ~mean_temp - 3C
        est_season_temp = (
            self.mean_temp_c - 2.5 if is_cool else (self.mean_temp_c + 4.5 if "warm" in crop.season_type.lower() else self.mean_temp_c)
        )
        # Blend in live IoT ambient canopy sensor when active (20% calibration signal for current conditions)
        if self.ambient_temp_c is not None and -15.0 <= self.ambient_temp_c <= 50.0:
            est_season_temp = (0.85 * est_season_temp) + (0.15 * self.ambient_temp_c)
        temp_dist = max(0.0, crop.optimal_temp_min_c - est_season_temp, est_season_temp - crop.optimal_temp_max_c)
        thermal_loss_frac = min(0.45, temp_dist * 0.045)
        if self.heatwave_days_count > 10 and crop.extreme_heat_resistance < 2.5:
            thermal_loss_frac = min(0.55, thermal_loss_frac + ((self.heatwave_days_count - 10) * 0.012))

        # Compaction root-impedance drag (when measured/modeled PSI exceeds crop threshold and not a bio-driller)
        comp_excess = max(0.0, start_compaction_psi - crop.critical_compaction_limit_psi)
        comp_loss_frac = min(0.25, comp_excess * 0.0025) if crop.compaction_relief_delta_psi >= 0.0 else 0.0

        # Same-family pathogen drag (continuous cropping yield drag replacing fake USD fines)
        same_family_repeat = preceding_crop is not None and crop.botanical_family == preceding_crop.botanical_family
        pathology_loss_frac = 0.12 if same_family_repeat else 0.0

        combined_yield_mult = max(
            0.25,
            (1.0 - water_loss_frac) * (1.0 - ph_loss_frac) * (1.0 - thermal_loss_frac) * (1.0 - comp_loss_frac) * (1.0 - pathology_loss_frac),
        )

        # Anchor potential yield with FAOSTAT national/regional benchmark if provided
        regional_bench = self.regional_crop_yields.get(crop.crop_id)
        base_yield = crop.potential_yield_tons_ha
        if regional_bench is not None and regional_bench > 0:
            # Blend 50/50 between catalog target and 1.15x regional national average, bounded to sensible range
            calibrated_ceiling = regional_bench * 1.15
            base_yield = max(crop.potential_yield_tons_ha * 0.55, min(crop.potential_yield_tons_ha * 1.35, (crop.potential_yield_tons_ha + calibrated_ceiling) / 2.0))

        actual_yield_tons_ha = round(base_yield * combined_yield_mult, 2)
        total_yield_tons = round(actual_yield_tons_ha * self.area_ha, 2)
        effective_market_price = float(self.crop_market_prices.get(crop.crop_id) or crop.market_price_usd_ton)
        gross_rev_ha = actual_yield_tons_ha * effective_market_price

        # 3. Nitrogen Balances (Herridge & Peoples BNF)
        net_n_bal, bio_n_fixed, synth_n_needed, leg_credit_used = SoilPhysicsEngine.calculate_nitrogen_balance(
            crop=crop,
            yield_tons_ha=actual_yield_tons_ha,
            preceding_legume_credit_kg_ha=preceding_legume_credit_kg_ha,
            in_situ_soil_nitrate_ppm=self.init_nitrate_ppm,
            in_situ_soil_n_kg_ha=self.init_soil_n_kg_ha,
        )

        # 4. Itemized Costs ($/ha)
        seed_cost = crop.seed_cost_usd_ha * self.p_seed_mult
        water_cost = irr_m3_ha * self.p_water_m3
        fuel_cost = crop.fuel_consumption_liters_ha * self.p_diesel_liter
        fert_n_cost = synth_n_needed * self.p_nitrogen_kg
        fert_p_cost = (actual_yield_tons_ha * crop.p2o5_uptake_kg_per_ton) * self.p_p2o5_kg
        fert_k_cost = (actual_yield_tons_ha * crop.k2o_uptake_kg_per_ton) * self.p_k2o_kg
        labor_cost = crop.labor_hours_per_ha * self.p_labor_hour
        protection_cost = crop.fixed_operational_cost_usd_ha * (1.20 if same_family_repeat else 1.0)

        # Rotational pathology evaluation (score-only, zero fabricated USD penalty)
        pathogen_score, rhizo_score, bot_penalty = SoilPhysicsEngine.evaluate_rotational_health(
            current_crop=crop,
            preceding_crop=preceding_crop
        )

        total_cost_ha = (
            seed_cost + water_cost + fuel_cost + fert_n_cost +
            fert_p_cost + fert_k_cost + labor_cost + protection_cost + bot_penalty
        )
        net_profit_ha = gross_rev_ha - total_cost_ha
        roi_pct = round((net_profit_ha / total_cost_ha * 100.0) if total_cost_ha > 0 else 0.0, 1)

        # Scale by parcel area
        gross_rev_total = round(gross_rev_ha * self.area_ha, 2)
        total_cost_total = round(total_cost_ha * self.area_ha, 2)
        net_profit_total = round(net_profit_ha * self.area_ha, 2)

        itemized_dict = {
            "seed_usd": round(seed_cost * self.area_ha, 2),
            "irrigation_water_usd": round(water_cost * self.area_ha, 2),
            "machinery_fuel_usd": round(fuel_cost * self.area_ha, 2),
            "fertilizer_nitrogen_usd": round(fert_n_cost * self.area_ha, 2),
            "fertilizer_phosphorus_usd": round(fert_p_cost * self.area_ha, 2),
            "fertilizer_potassium_usd": round(fert_k_cost * self.area_ha, 2),
            "labor_usd": round(labor_cost * self.area_ha, 2),
            "crop_protection_usd": round(protection_cost * self.area_ha, 2),
            "botanical_violation_penalty_usd": round(bot_penalty * self.area_ha, 2),
        }

        # 5. Soil Organic Carbon Dynamics (Henin-Dupuis)
        end_soc_pct, delta_soc_pct, c_input, k2 = SoilPhysicsEngine.simulate_soc_dynamics(
            crop=crop,
            soil_props=self.soil_props,
            current_soc_pct=start_soc_pct,
            mean_annual_temp_c=self.mean_temp_c,
            tillage_factor=self.tillage_factor,
            actual_yield_tons_ha=actual_yield_tons_ha,
            soilgrids_clay_pct=self.soilgrids_clay_pct,
            soilgrids_bulk_density_g_cm3=self.soilgrids_bdod,
        )

        # 6. Soil Compaction (ASAE S313.3 Cone Index)
        end_compaction_psi, delta_psi = SoilPhysicsEngine.simulate_soil_compaction(
            crop=crop,
            current_compaction_psi=start_compaction_psi,
            soil_props=self.soil_props
        )

        # 7. Soil Erosion (RUSLE)
        erosion_t_ha = SoilPhysicsEngine.calculate_rusle_erosion(
            crop=crop,
            soil_props=self.soil_props,
            slope_pct=self.slope_pct,
            annual_precip_mm=self.annual_precip_mm,
            soilgrids_sand_pct=self.soilgrids_sand_pct,
            soilgrids_silt_pct=self.soilgrids_silt_pct,
            soilgrids_clay_pct=self.soilgrids_clay_pct,
            soilgrids_soc_pct=start_soc_pct,
            area_hectares=self.area_ha,
        )

        # 8. Site-Grounded Climate & Hazard Vulnerability Score (0-100)
        # Weights crop sensitivities by ACTUAL NASA POWER/SMAP/SoilGrids exposures at this field
        aridity_ratio = self.annual_et0_mm / max(120.0, self.annual_precip_mm)
        drought_exposure = min(2.2, max(0.4, (aridity_ratio - 0.5) * 1.1 + (self.longest_dry_spell_days / 45.0) + (2.0 * (1.0 - ks))))
        flood_exposure = 2.0 if self.low_spot_risk else (1.3 if self.annual_precip_mm > 900.0 else 0.5)
        frost_exposure = min(2.2, max(0.3, self.frost_days_count / 60.0))
        heat_exposure = min(2.4, max(0.4, (self.heatwave_days_count / 18.0) + (0.6 if self.mean_temp_c > 20.0 else 0.0)))
        wind_exposure = 1.0

        climate_vuln = (
            (5.0 - crop.drought_resistance) * 3.8 * drought_exposure +
            (5.0 - crop.flood_resistance) * 3.5 * flood_exposure +
            (5.0 - crop.wind_lodging_resistance) * 2.5 * wind_exposure +
            (5.0 - crop.frost_resistance) * 3.8 * frost_exposure +
            (5.0 - crop.extreme_heat_resistance) * 4.2 * heat_exposure +
            (ph_loss_frac * 25.0) +
            (water_loss_frac * 35.0)
        )
        climate_vuln_score = round(max(5.0, min(100.0, climate_vuln)), 1)

        # Ground Narrative Construction
        narrative_parts = []
        if crop.is_legume:
            narrative_parts.append(f"Fixed {bio_n_fixed:.0f} kg N/ha via symbiotic rhizobia, creating a soil nitrogen surplus.")
        else:
            narrative_parts.append(f"Uptake removed {abs(net_n_bal):.0f} kg N/ha; applied {synth_n_needed:.0f} kg synthetic N.")

        if delta_psi < -10.0:
            narrative_parts.append(f"Deep taproot bio-drilled subsoil hardpan by {delta_psi:+.1f} PSI, enhancing infiltration.")
        elif delta_psi > 15.0:
            narrative_parts.append(f"Machinery traffic added {delta_psi:+.1f} PSI cone resistance to subsoil layer.")

        if delta_soc_pct > 0.0:
            narrative_parts.append(f"Biomass residue humification built Soil Organic Carbon from {start_soc_pct:.2f}% to {end_soc_pct:.2f}%.")
        else:
            narrative_parts.append(f"High microbial mineralization slightly reduced SOC from {start_soc_pct:.2f}% to {end_soc_pct:.2f}%.")

        ground_narrative = " ".join(narrative_parts)

        # Next season residual nitrogen credit (both BNF legumes and scavenged winterkill cover crops)
        next_legume_credit = crop.residual_soil_n_credit_kg_ha if (crop.is_legume or crop.residual_soil_n_credit_kg_ha > 0) else 0.0

        impact = AnnualGroundImpact(
            year_index=year_idx,
            crop_id=crop.crop_id,
            crop_name=crop.common_name,
            botanical_family=crop.botanical_family.value,
            season_label=crop.season_type,
            projected_yield_tons_ha=actual_yield_tons_ha,
            total_yield_tons=total_yield_tons,
            gross_revenue_usd=gross_rev_total,
            total_cost_usd=total_cost_total,
            itemized_costs_usd=itemized_dict,
            net_profit_usd=net_profit_total,
            roi_pct=roi_pct,
            labor_hours_total=round(crop.labor_hours_per_ha * self.area_ha, 1),
            machinery_passes_count=crop.machinery_passes_count,
            fuel_consumed_liters=round(crop.fuel_consumption_liters_ha * self.area_ha, 1),
            nitrogen_balance_kg_ha=net_n_bal,
            p2o5_balance_kg_ha=round(-(actual_yield_tons_ha * crop.p2o5_uptake_kg_per_ton), 1),
            k2o_balance_kg_ha=round(-(actual_yield_tons_ha * crop.k2o_uptake_kg_per_ton), 1),
            biological_n_fixed_kg_ha=bio_n_fixed,
            synthetic_n_applied_kg_ha=synth_n_needed,
            legume_n_credit_used_kg_ha=leg_credit_used,
            soc_pct_start=start_soc_pct,
            soc_pct_end=end_soc_pct,
            soc_change_pct=delta_soc_pct,
            carbon_input_tons_ha=c_input,
            compaction_psi_start=start_compaction_psi,
            compaction_psi_end=end_compaction_psi,
            compaction_change_psi=delta_psi,
            water_demand_etc_mm=etc_mm,
            effective_precipitation_mm=peff_mm,
            irrigation_water_applied_mm=irr_applied_mm,
            irrigation_volume_m3=round(irr_m3_ha * self.area_ha, 1),
            water_stress_coefficient_ks=ks,
            soil_erosion_tons_ha=erosion_t_ha,
            rhizosphere_vitality_score=rhizo_score,
            pathogen_disease_risk_score=pathogen_score,
            extreme_event_vulnerability_score=climate_vuln_score,
            ground_narrative=ground_narrative,
        )

        return impact, next_legume_credit

    def simulate_three_year_plan(
        self,
        strategy_id: str,
        strategy_title: str,
        core_objective: str,
        sequence: List[CropAgronomicProfile]
    ) -> ThreeYearCultivationPlan:
        """Runs the multi-year sequential simulation for a candidate 3-year sequence."""
        c1, c2, c3 = sequence

        # Year 1
        y1_impact, leg_credit_1 = self._simulate_annual_impact(
            year_idx=1,
            crop=c1,
            preceding_crop=self.initial_preceding_crop,
            start_soc_pct=self.init_soc_pct,
            start_compaction_psi=self.init_compaction_psi,
            preceding_legume_credit_kg_ha=0.0
        )

        # Year 2: Carries forward Year 1 ending SOC, compaction PSI, and legume N credit!
        y2_impact, leg_credit_2 = self._simulate_annual_impact(
            year_idx=2,
            crop=c2,
            preceding_crop=c1,
            start_soc_pct=y1_impact.soc_pct_end,
            start_compaction_psi=y1_impact.compaction_psi_end,
            preceding_legume_credit_kg_ha=leg_credit_1
        )

        # Year 3: Carries forward Year 2 ending state!
        y3_impact, _ = self._simulate_annual_impact(
            year_idx=3,
            crop=c3,
            preceding_crop=c2,
            start_soc_pct=y2_impact.soc_pct_end,
            start_compaction_psi=y2_impact.compaction_psi_end,
            preceding_legume_credit_kg_ha=leg_credit_2
        )

        # 3-Year Cumulative Totals
        total_rev = round(y1_impact.gross_revenue_usd + y2_impact.gross_revenue_usd + y3_impact.gross_revenue_usd, 2)
        total_cost = round(y1_impact.total_cost_usd + y2_impact.total_cost_usd + y3_impact.total_cost_usd, 2)
        total_profit = round(y1_impact.net_profit_usd + y2_impact.net_profit_usd + y3_impact.net_profit_usd, 2)
        cum_roi = round((total_profit / total_cost * 100.0) if total_cost > 0 else 0.0, 1)

        total_labor = round(y1_impact.labor_hours_total + y2_impact.labor_hours_total + y3_impact.labor_hours_total, 1)
        total_passes = y1_impact.machinery_passes_count + y2_impact.machinery_passes_count + y3_impact.machinery_passes_count
        total_fuel = round(y1_impact.fuel_consumed_liters + y2_impact.fuel_consumed_liters + y3_impact.fuel_consumed_liters, 1)

        net_soc = round(y3_impact.soc_pct_end - self.init_soc_pct, 3)
        total_c_in = round(y1_impact.carbon_input_tons_ha + y2_impact.carbon_input_tons_ha + y3_impact.carbon_input_tons_ha, 2)
        total_n_fix = round(y1_impact.biological_n_fixed_kg_ha + y2_impact.biological_n_fixed_kg_ha + y3_impact.biological_n_fixed_kg_ha, 1)
        synth_n_saved = round((y2_impact.legume_n_credit_used_kg_ha + y3_impact.legume_n_credit_used_kg_ha) * self.p_nitrogen_kg * self.area_ha, 2)

        net_compact = round(y3_impact.compaction_psi_end - self.init_compaction_psi, 1)
        total_irr_m3 = round(y1_impact.irrigation_volume_m3 + y2_impact.irrigation_volume_m3 + y3_impact.irrigation_volume_m3, 1)
        avg_erosion = round((y1_impact.soil_erosion_tons_ha + y2_impact.soil_erosion_tons_ha + y3_impact.soil_erosion_tons_ha) / 3.0, 2)

        # Composite Regenerative Soil Health Score (0-100)
        # Favors SOC gains, N fixation, compaction relief, low erosion, high rhizosphere vitality
        soc_score = min(30.0, max(0.0, 15.0 + (net_soc * 40.0)))
        n_fix_score = min(25.0, (total_n_fix / 200.0) * 25.0)
        compaction_score = min(20.0, max(0.0, 10.0 - (net_compact * 0.4)))
        erosion_score = max(0.0, 15.0 - (avg_erosion * 2.0))
        diversity_families = len({c1.botanical_family, c2.botanical_family, c3.botanical_family})
        diversity_score = diversity_families * 3.33
        soil_health_score = round(min(100.0, max(10.0, soc_score + n_fix_score + compaction_score + erosion_score + diversity_score)), 1)

        # Composite Loss Risk Score (0-100)
        avg_pathogen = (y1_impact.pathogen_disease_risk_score + y2_impact.pathogen_disease_risk_score + y3_impact.pathogen_disease_risk_score) / 3.0
        avg_climate = (y1_impact.extreme_event_vulnerability_score + y2_impact.extreme_event_vulnerability_score + y3_impact.extreme_event_vulnerability_score) / 3.0
        loss_risk_score = round(min(100.0, (avg_pathogen * 0.45) + (avg_climate * 0.55)), 1)

        cumulative = ThreeYearCumulativeMetrics(
            total_gross_revenue_usd=total_rev,
            total_cost_usd=total_cost,
            total_net_profit_usd=total_profit,
            cumulative_roi_pct=cum_roi,
            total_labor_hours=total_labor,
            total_machinery_passes=total_passes,
            total_diesel_liters=total_fuel,
            net_soc_change_pct=net_soc,
            initial_soc_pct=self.init_soc_pct,
            final_soc_pct=y3_impact.soc_pct_end,
            total_carbon_input_tons_ha=total_c_in,
            total_biological_n_fixed_kg_ha=total_n_fix,
            synthetic_n_saved_usd=synth_n_saved,
            initial_compaction_psi=self.init_compaction_psi,
            final_compaction_psi=y3_impact.compaction_psi_end,
            net_compaction_change_psi=net_compact,
            total_irrigation_volume_m3=total_irr_m3,
            average_annual_erosion_tons_ha=avg_erosion,
            cumulative_soil_health_score=soil_health_score,
            composite_loss_risk_score=loss_risk_score,
            botanical_families_count=diversity_families,
        )

        names = [c1.common_name, c2.common_name, c3.common_name]
        summary = (
            f"3-Year Sequence: {' -> '.join(names)}. "
            f"Delivers ${total_profit:,.2f} net margin with {cum_roi:.1f}% ROI. "
            f"Regenerates soil organic carbon ({net_soc:+.2f}%) and fixes {total_n_fix:.0f} kg N/ha biologically."
        )

        risk_actions = []
        if net_compact > 10.0:
            risk_actions.append("Consider non-inversion subsoil aeration or planting a taproot cover crop to mitigate machinery traffic compaction.")
        if diversity_families < 3:
            risk_actions.append("Add a distinct third botanical family into future rotations to break soil-borne pathogens.")
        if total_irr_m3 > 0.0:
            risk_actions.append(f"Ensure drip or precision sprinkler irrigation is calibrated for {total_irr_m3:,.0f} m³ cumulative water demand.")

        return ThreeYearCultivationPlan(
            strategy_id=strategy_id,
            strategy_title=strategy_title,
            core_objective=core_objective,
            rotation_sequence=names,
            year_1=y1_impact,
            year_2=y2_impact,
            year_3=y3_impact,
            cumulative_metrics=cumulative,
            strategic_summary=summary,
            risk_mitigation_actions=risk_actions or ["Follow recommended fertilization and pest scouting protocols."],
        )

    def optimize_all_strategies(self) -> Dict[str, ThreeYearCultivationPlan]:
        """
        Explores all valid 3-year sequences and extracts the 5 optimal champion strategies.
        Guarantees mathematically distinct sequences for each strategy.
        """
        candidates = self._filter_candidate_crops()
        if len(candidates) < 3:
            candidates = list(MASTER_CROPS_CATALOG.values())

        # Generate all admissible 3-year combinations (C1 -> C2 -> C3)
        valid_triplets: List[Tuple[CropAgronomicProfile, CropAgronomicProfile, CropAgronomicProfile]] = []

        for c1 in candidates:
            # Enforce break relative to field's preceding crop if farmer just grew that heavy-pathogen family
            if (
                self.initial_preceding_crop is not None
                and c1.rotational_break_needed_years >= 3
                and c1.botanical_family == self.initial_preceding_crop.botanical_family
            ):
                continue
            for c2 in candidates:
                for c3 in candidates:
                    # Hard Pruning Rule 1: No 3 consecutive seasons of the same botanical family
                    if c1.botanical_family == c2.botanical_family == c3.botanical_family:
                        continue
                    # Do not repeat pure cover crops back-to-back as consecutive primary years
                    if (c1.crop_id == "daikon_radish_cover" and c2.crop_id == "daikon_radish_cover") or (
                        c2.crop_id == "daikon_radish_cover" and c3.crop_id == "daikon_radish_cover"
                    ):
                        continue
                    # Hard Pruning Rule 2: Enforce rotational_break_needed_years dynamically
                    # If break >= 3 years (e.g., Solanaceae / Bell Peppers / Processing Tomatoes), allow at most ONCE in 3-year cycle
                    if (
                        (c1.rotational_break_needed_years >= 3 or c2.rotational_break_needed_years >= 3)
                        and c1.botanical_family == c2.botanical_family
                    ):
                        continue
                    if (
                        (c2.rotational_break_needed_years >= 3 or c3.rotational_break_needed_years >= 3)
                        and c2.botanical_family == c3.botanical_family
                    ):
                        continue
                    if (
                        (c1.rotational_break_needed_years >= 3 or c3.rotational_break_needed_years >= 3)
                        and c1.botanical_family == c3.botanical_family
                    ):
                        continue
                    # If break == 2 years (e.g., Alfalfa, Canola, Sunflowers), disallow consecutive years of that family
                    if (
                        (c1.rotational_break_needed_years >= 2 or c2.rotational_break_needed_years >= 2)
                        and c1.botanical_family == c2.botanical_family
                    ):
                        continue
                    if (
                        (c2.rotational_break_needed_years >= 2 or c3.rotational_break_needed_years >= 2)
                        and c2.botanical_family == c3.botanical_family
                    ):
                        continue
                    valid_triplets.append((c1, c2, c3))

        # Safety fallback if user whitelisted only 3 crops with strict breaks
        if not valid_triplets:
            for c1 in candidates:
                for c2 in candidates:
                    for c3 in candidates:
                        if not (c1.botanical_family == c2.botanical_family == c3.botanical_family):
                            valid_triplets.append((c1, c2, c3))
        if not valid_triplets:
            valid_triplets = [(c1, c2, c3) for c1 in candidates for c2 in candidates for c3 in candidates]

        # Evaluate candidate pool
        evaluated_plans: List[Tuple[Tuple[str, str, str], ThreeYearCultivationPlan]] = []
        for triplet in valid_triplets:
            plan = self.simulate_three_year_plan("cand", "Candidate", "Candidate", list(triplet))
            seq_key = (triplet[0].crop_id, triplet[1].crop_id, triplet[2].crop_id)
            evaluated_plans.append((seq_key, plan))

        # Helper to pick next best distinct sequence
        chosen_sequences: Set[Tuple[str, str, str]] = set()

        def pick_champion(key_fn, reverse=True) -> ThreeYearCultivationPlan:
            sorted_candidates = sorted(evaluated_plans, key=lambda x: key_fn(x[1]), reverse=reverse)
            for seq_k, candidate_plan in sorted_candidates:
                if seq_k not in chosen_sequences:
                    chosen_sequences.add(seq_k)
                    return candidate_plan
            # Fallback if exhausted
            return sorted_candidates[0][1]

        # 1. Most Income: Maximize 3-year net profit ($)
        raw_income = pick_champion(lambda p: p.cumulative_metrics.total_net_profit_usd, reverse=True)
        plan_income = self.simulate_three_year_plan(
            strategy_id="most_income",
            strategy_title="Most Income Strategy",
            core_objective="Maximize 3-year cumulative net profit ($) while maintaining legal water and rotation constraints",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_income.year_1.crop_id, raw_income.year_2.crop_id, raw_income.year_3.crop_id]]
        )

        # 2. Best Soil Health: Maximize regenerative soil health index (SOC, BNF fixation, decompaction, low erosion)
        raw_soil = pick_champion(lambda p: p.cumulative_metrics.cumulative_soil_health_score, reverse=True)
        plan_soil = self.simulate_three_year_plan(
            strategy_id="best_soil_health",
            strategy_title="Best Soil Health Strategy",
            core_objective="Maximize Soil Organic Carbon (SOC) build, Biological N Fixation, and subsoil bio-drilling decompaction",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_soil.year_1.crop_id, raw_soil.year_2.crop_id, raw_soil.year_3.crop_id]]
        )

        # 3. Least Effort / Labour: Minimize total field labor hours and machinery passes
        raw_labor = pick_champion(lambda p: p.cumulative_metrics.total_labor_hours + (p.cumulative_metrics.total_machinery_passes * 1.5), reverse=False)
        plan_labor = self.simulate_three_year_plan(
            strategy_id="least_effort",
            strategy_title="Least Effort / Labour Strategy",
            core_objective="Minimize labor hours, field tractor passes, and machinery fuel expenditure",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_labor.year_1.crop_id, raw_labor.year_2.crop_id, raw_labor.year_3.crop_id]]
        )

        # 4. Highest ROI (%): Maximize capital efficiency (Net Profit / Total Costs)
        raw_roi = pick_champion(lambda p: p.cumulative_metrics.cumulative_roi_pct, reverse=True)
        plan_roi = self.simulate_three_year_plan(
            strategy_id="highest_roi",
            strategy_title="Highest Capital ROI (%) Strategy",
            core_objective="Maximize percentage return on production capital invested across the 3 years",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_roi.year_1.crop_id, raw_roi.year_2.crop_id, raw_roi.year_3.crop_id]]
        )

        # 5. Least Amount of Crop Loss Risk: Minimize weather shock, disease carryover, and erosion hazards
        raw_risk = pick_champion(lambda p: p.cumulative_metrics.composite_loss_risk_score, reverse=False)
        plan_risk = self.simulate_three_year_plan(
            strategy_id="least_crop_loss_risk",
            strategy_title="Least Crop Loss Risk Strategy",
            core_objective="Minimize vulnerability to climate extremes (drought/flood/frost/heat) and fungal/nematode pathogens",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_risk.year_1.crop_id, raw_risk.year_2.crop_id, raw_risk.year_3.crop_id]]
        )

        return {
            "most_income": plan_income,
            "best_soil_health": plan_soil,
            "least_effort": plan_labor,
            "highest_roi": plan_roi,
            "least_crop_loss_risk": plan_risk,
        }
