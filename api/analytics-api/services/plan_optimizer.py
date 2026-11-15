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
from types import SimpleNamespace
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
        self.latitude_deg = float(normalized_field.get("latitude", 40.0))
        self.longitude_deg = float(normalized_field.get("longitude", -93.0))
        self.country_code = str(normalized_field.get("country_code") or "US")
        self.state_or_province = normalized_field.get("state_or_province")

        self.soil_type = normalized_field.get("resolved_soil_type", "Loam")
        self.soil_props = SoilPhysicsEngine.get_soil_properties(self.soil_type)
        self.elevation_m = float(normalized_field.get("elevation_m", 150.0))
        self.slope_pct = float(normalized_field.get("slope_pct", 2.5))
        self.slope_max_pct = normalized_field.get("slope_max_pct")
        self.gloreda_r_factor = normalized_field.get("gloreda_r_factor")
        self.has_greenhouse = bool(normalized_field.get("has_greenhouse", False))
        self.water_quota_m3 = normalized_field.get("legal_water_quota_m3")

        # Initial soil state (calibrated from in-situ sensors or SoilGrids)
        raw_init_soc = float(normalized_field.get("baseline_soc_pct", 1.85))
        self.compaction_is_measured = bool(normalized_field.get("compaction_is_measured", False))
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
        self.soilgrids_cfvo_pct = normalized_field.get("soilgrids_cfvo_pct")
        self.soilgrids_total_n_g_kg = normalized_field.get("soilgrids_total_nitrogen_g_kg")
        self.caco3_g_kg = float(normalized_field.get("caco3_g_kg") or 0.0)
        self.calcareous_flag = bool(
            normalized_field.get("calcareous_flag")
            or self.caco3_g_kg > 10.0
            or (self.soil_ph >= 7.5 and normalized_field.get("caco3_g_kg") is None)
        )

        # Depth-weighted 0-30 cm SOC stock integration accounting for coarse fragments (CF)
        raw_layers = normalized_field.get("soil_depth_layers") or []
        norm_layers = [SimpleNamespace(**lyr) if isinstance(lyr, dict) else lyr for lyr in raw_layers]
        (
            self.init_c_stock_t_ha,
            self.init_soc_pct,
            self.eff_rho_b,
            self.eff_clay_pct,
            self.eff_cf_frac,
        ) = SoilPhysicsEngine.calculate_initial_soc_stock(
            soil_depth_layers=norm_layers,
            fallback_soc_pct=raw_init_soc,
            fallback_rho_b=self.soilgrids_bdod or self.soil_props["bulk_density_g_cm3"],
            fallback_clay_pct=self.soilgrids_clay_pct if self.soilgrids_clay_pct is not None else self.soil_props["clay_pct"],
            fallback_cfvo_pct=self.soilgrids_cfvo_pct or 0.0,
            calibrated_topsoil_soc_pct=normalized_field.get("calibrated_soc_pct"),
            target_depth_cm=30.0,
        )
        if self.soilgrids_total_n_g_kg is not None and float(self.soilgrids_total_n_g_kg) > 0.0:
            self.cn_ratio = max(7.0, min(20.0, (self.init_soc_pct * 10.0) / float(self.soilgrids_total_n_g_kg)))
        else:
            self.cn_ratio = 11.0

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

        raw_monthly = normalized_field.get("monthly_climatology")
        if raw_monthly:
            self.monthly_climate = {int(k): dict(v) for k, v in raw_monthly.items()}
            self.et0_method_used = str(normalized_field.get("et0_method_used") or "FAO-56 Penman-Monteith (Monthly Climatology)")
        else:
            self.monthly_climate, self.et0_method_used = SoilPhysicsEngine.build_monthly_climate_series(
                monthly_raw=None,
                latitude_deg=self.latitude_deg,
                elevation_m=self.elevation_m,
                annual_et0_mm=self.annual_et0_mm,
                annual_precip_mm=self.annual_precip_mm,
                mean_temp_c=self.mean_temp_c,
                warm_season_et0_mm=self.warm_season_et0_mm,
                warm_season_precip_mm=self.warm_season_precip_mm,
                cool_season_et0_mm=self.cool_season_et0_mm,
                cool_season_precip_mm=self.cool_season_precip_mm,
                coldest_night_c=self.coldest_night_c,
                hottest_day_c=self.hottest_day_c,
            )

        # Management, Calendars & Governance Limits
        self.irrigation_system = str(normalized_field.get("irrigation_system") or "Center Pivot Sprinkler")
        explicit_method = normalized_field.get("irrigation_method")
        if explicit_method:
            self.irrigation_method, self.irrigation_efficiency_ea = SoilPhysicsEngine.get_irrigation_efficiency(explicit_method)
        else:
            sys_l = self.irrigation_system.lower()
            if "drip" in sys_l or "subsurface" in sys_l:
                self.irrigation_method, self.irrigation_efficiency_ea = "drip", 0.90
            elif "flood" in sys_l or "furrow" in sys_l or "surface" in sys_l:
                self.irrigation_method, self.irrigation_efficiency_ea = "surface", 0.60
            elif "rainfed" in sys_l or "none" in sys_l:
                self.irrigation_method, self.irrigation_efficiency_ea = "rainfed", 0.75
            else:
                self.irrigation_method, self.irrigation_efficiency_ea = "sprinkler", 0.75
        self.has_irrigation = self.irrigation_method != "rainfed" and "rainfed" not in self.irrigation_system.lower()

        tillage_str = str(normalized_field.get("tillage_practice") or "").lower()
        self.tillage_factor = 0.50 if "no-till" in tillage_str else (0.70 if "strip" in tillage_str or "reduced" in tillage_str else 1.0)
        self.straw_export_fraction = float(normalized_field.get("straw_export_fraction") or 0.0)
        self.crop_calendars = normalized_field.get("crop_calendars") or {}
        self.ggcmi_crop_calendar = normalized_field.get("ggcmi_crop_calendar")
        self.max_legal_n_kg_ha = normalized_field.get("max_legal_n_kg_ha")
        self.ambient_temp_c = normalized_field.get("ambient_temp_c")
        self.ambient_humidity_pct = normalized_field.get("ambient_humidity_pct")

        # Economic price structure (converted to elemental N, P, K $/kg) & regional yield benchmarks
        self.p_seed_mult = float(normalized_field.get("seed_price_multiplier", 1.0))
        self.p_water_m3 = float(normalized_field.get("water_price_usd_m3", 0.08))
        self.p_diesel_liter = float(normalized_field.get("diesel_price_usd_liter", 1.15))
        self.p_nitrogen_kg = float(normalized_field.get("fertilizer_n_price_usd_kg", 1.35))
        self.p_p2o5_kg = float(normalized_field.get("fertilizer_p_price_usd_kg", 1.60))
        self.p_k2o_kg = float(normalized_field.get("fertilizer_k_price_usd_kg", 0.95))
        self.p_elem_n_kg = float(normalized_field.get("elemental_n_price_usd_kg") or self.p_nitrogen_kg)
        self.p_elem_p_kg = (
            float(normalized_field["elemental_p_price_usd_kg"])
            if normalized_field.get("elemental_p_price_usd_kg") is not None
            else round(self.p_p2o5_kg / 0.4364, 4)
        )
        self.p_elem_k_kg = (
            float(normalized_field["elemental_k_price_usd_kg"])
            if normalized_field.get("elemental_k_price_usd_kg") is not None
            else round(self.p_k2o_kg / 0.8301, 4)
        )
        self.p_labor_hour = float(normalized_field.get("labor_hourly_wage_usd", 22.0))
        self.crop_market_prices = normalized_field.get("crop_market_prices_usd_t") or {}
        self.regional_crop_yields = normalized_field.get("regional_crop_yields_t_ha") or {}

        # Preceding 1-5 year crop history timeline (for full break checks & Year 0 water spin-up)
        self.past_crops_sequence: List[str] = list(normalized_field.get("past_crops_sequence") or [])
        self.hist_crop_name = normalized_field.get(
            "preceding_crop_name",
            self.past_crops_sequence[-1] if self.past_crops_sequence else "corn",
        )
        self.initial_preceding_crop = get_crop_profile(self.hist_crop_name) or MASTER_CROPS_CATALOG["corn"]
        self.past_crop_profiles: List[CropAgronomicProfile] = []
        for pname in self.past_crops_sequence[-5:]:
            prof = get_crop_profile(pname)
            if prof is not None:
                self.past_crop_profiles.append(prof)
        if not self.past_crop_profiles and self.initial_preceding_crop is not None:
            self.past_crop_profiles = [self.initial_preceding_crop]

        # Year 0 Water Balance Spin-Up from historical crop (W5)
        self.spinup_storage_mm: Optional[float] = None
        self.spinup_rooting_depth_m: Optional[float] = None
        if self.past_crop_profiles:
            spin = SoilPhysicsEngine.simulate_monthly_water_balance(
                crop=self.past_crop_profiles[-1],
                soil_props=self.soil_props,
                monthly_climate=self.monthly_climate,
                latitude_deg=self.latitude_deg,
                smap_rootzone_moisture=self.smap_moisture,
                has_irrigation=self.has_irrigation,
                irrigation_method=self.irrigation_method,
                annual_quotas_remaining_mm=None,
                base_calendar_year=0,
                sand_pct=self.soilgrids_sand_pct,
                clay_pct=self.eff_clay_pct,
                soc_pct=self.init_soc_pct,
                farmer_calendars=self.crop_calendars,
                ggcmi_calendars=self.ggcmi_crop_calendar,
            )
            self.spinup_storage_mm = spin["end_storage_mm"]
            self.spinup_rooting_depth_m = spin["end_rooting_depth_m"]

        # Whitelist / Blacklist & constrained flag
        self.whitelisted_crops = normalized_field.get("preferred_candidate_crops")
        self.blacklisted_crops = normalized_field.get("excluded_crops") or []
        self.parcel_is_constrained: bool = False
        self._ref_stress_cache: Dict[str, float] = {}

    def _compute_occupied_season_temp(self, crop: CropAgronomicProfile, cal_months: List[Dict[str, Any]], use_ambient: bool = True) -> float:
        """Weighted average temperature across the crop's actual occupied calendar months."""
        if not cal_months:
            base = self.mean_temp_c
        else:
            tot_w = sum(cm["f_m"] for cm in cal_months) or 1.0
            base = sum(cm["f_m"] * self.monthly_climate[cm["month"]]["tmean_c"] for cm in cal_months) / tot_w
        if use_ambient and self.ambient_temp_c is not None and -15.0 <= self.ambient_temp_c <= 50.0:
            return (0.85 * base) + (0.15 * self.ambient_temp_c)
        return base

    def _compute_reference_stress_product(self, crop: CropAgronomicProfile) -> float:
        """
        Computes reference-field combined stress multiplier product (Pi mu_ref) for relative yield scaling
        Y = Y_ref * (Pi mu_parcel / Pi mu_ref) * mu_family.
        Evaluated on modal Loam soil, neutral pH 6.8, uncompacted soil, and unlimited water quota.
        """
        if crop.crop_id in self._ref_stress_cache:
            return self._ref_stress_cache[crop.crop_id]

        loam_props = SoilPhysicsEngine.get_soil_properties("Loam")
        ref_water = SoilPhysicsEngine.simulate_monthly_water_balance(
            crop=crop,
            soil_props=loam_props,
            monthly_climate=self.monthly_climate,
            latitude_deg=self.latitude_deg,
            smap_rootzone_moisture=0.25,
            has_irrigation=self.has_irrigation,
            irrigation_method="sprinkler",
            annual_quotas_remaining_mm=None,
            base_calendar_year=1,
            sand_pct=None,
            clay_pct=None,
            soc_pct=1.8,
            farmer_calendars=self.crop_calendars,
            ggcmi_calendars=self.ggcmi_crop_calendar,
        )
        mu_water_ref = ref_water["fao33_mu_water"]
        occ_temp = self._compute_occupied_season_temp(crop, ref_water["calendar_months"], use_ambient=False)
        temp_dist = max(0.0, crop.optimal_temp_min_c - occ_temp, occ_temp - crop.optimal_temp_max_c)
        thermal_loss = min(0.45, temp_dist * 0.045)
        if self.heatwave_days_count > 10 and crop.extreme_heat_resistance < 2.5:
            thermal_loss = min(0.55, thermal_loss + ((self.heatwave_days_count - 10) * 0.012))
        mu_thermal_ref = max(0.25, 1.0 - thermal_loss)

        pi_ref = max(0.25, min(1.0, mu_water_ref * mu_thermal_ref))
        self._ref_stress_cache[crop.crop_id] = pi_ref
        return pi_ref

    def _filter_candidate_crops(self) -> List[CropAgronomicProfile]:
        """
        Prunes crops that violate strict ECOCROP pH envelopes, occupied-month thermal windows,
        greenhouse rules, flood hazards, or farmer preferences. Sets `parcel_is_constrained` when
        fewer than 3 distinct crops pass strict thresholds WITHOUT re-admitting excluded crops.
        """
        admissible: List[CropAgronomicProfile] = []
        for crop in MASTER_CROPS_CATALOG.values():
            if self.blacklisted_crops:
                if any(b.lower() in crop.common_name.lower() or b.lower() in crop.crop_id.lower() for b in self.blacklisted_crops):
                    continue

            if self.whitelisted_crops and len(self.whitelisted_crops) >= 3:
                matches_whitelist = any(
                    w.lower() in crop.common_name.lower() or w.lower() in crop.crop_id.lower() or
                    crop.common_name.lower() in w.lower() or crop.crop_id.lower() in w.lower()
                    for w in self.whitelisted_crops
                )
                if not matches_whitelist:
                    continue

            if crop.greenhouse_requirement == GreenhouseRequirement.GREENHOUSE_REQUIRED and not self.has_greenhouse:
                continue

            if self.low_spot_risk and crop.flood_resistance < 2.0:
                continue

            if not self.has_greenhouse:
                cal_months, _, _ = SoilPhysicsEngine.resolve_crop_calendar(
                    crop=crop,
                    latitude_deg=self.latitude_deg,
                    farmer_calendars=self.crop_calendars,
                    ggcmi_calendars=self.ggcmi_crop_calendar,
                )
                occ_temp = self._compute_occupied_season_temp(crop, cal_months, use_ambient=False)
                is_warm_crop = "warm" in crop.season_type.lower()
                if is_warm_crop and crop.frost_resistance <= 2.2 and (
                    self.mean_temp_c < 9.5 or self.frost_days_count > 130 or occ_temp < (crop.optimal_temp_min_c - 6.0)
                ):
                    continue
                if crop.crop_id == "spinach" and (self.mean_temp_c > 22.0 or self.heatwave_days_count >= 35 or occ_temp > 23.5):
                    continue

            # Crop-specific ECOCROP absolute pH lockout (no artificial widening / re-admission)
            ph_min = crop.abs_ph_min if crop.abs_ph_min is not None else (crop.optimal_ph_min - 1.6)
            ph_max = crop.abs_ph_max if crop.abs_ph_max is not None else (crop.optimal_ph_max + 1.6)
            if self.soil_ph < ph_min or self.soil_ph > ph_max:
                continue
            admissible.append(crop)

        self.parcel_is_constrained = len(admissible) < 3
        return admissible

    def _simulate_annual_impact(
        self,
        year_idx: int,
        crop: CropAgronomicProfile,
        preceding_crop: Optional[CropAgronomicProfile],
        start_soc_pct: float,
        start_compaction_psi: float,
        preceding_legume_credit_kg_ha: float,
    ) -> Tuple[AnnualGroundImpact, float]:
        """Backward-compatible single-year simulation wrapper returning (AnnualGroundImpact, next_legume_credit)."""
        impact, state = self._simulate_annual_impact_step(
            year_idx=year_idx,
            crop=crop,
            preceding_crop=preceding_crop,
            start_soc_pct=start_soc_pct,
            start_compaction_psi=start_compaction_psi,
            preceding_legume_credit_kg_ha=preceding_legume_credit_kg_ha,
            preceding_scavenged_credit_kg_ha=0.0,
            start_storage_mm=self.spinup_storage_mm if year_idx == 1 else None,
            prev_rooting_depth_m=self.spinup_rooting_depth_m if year_idx == 1 else None,
            start_c_stock_t_ha=self.init_c_stock_t_ha if year_idx == 1 else None,
            annual_quotas_remaining_mm=None,
        )
        return impact, float(state["next_legume_credit_kg_ha"])

    def _simulate_annual_impact_step(
        self,
        year_idx: int,
        crop: CropAgronomicProfile,
        preceding_crop: Optional[CropAgronomicProfile],
        start_soc_pct: float,
        start_compaction_psi: float,
        preceding_legume_credit_kg_ha: float,
        preceding_scavenged_credit_kg_ha: float = 0.0,
        start_storage_mm: Optional[float] = None,
        prev_rooting_depth_m: Optional[float] = None,
        start_c_stock_t_ha: Optional[float] = None,
        annual_quotas_remaining_mm: Optional[Dict[int, float]] = None,
    ) -> Tuple[AnnualGroundImpact, Dict[str, Any]]:
        """
        Simulates physical, chemical, and economic impact of one crop year on the parcel (v1.1).
        Returns: (AnnualGroundImpact, next_state_dict)
        """
        # 1. Monthly Carryover Hydrology (FAO-56 single Kc, Saxton-Rawls, USDA-SCS monthly Peff, Eq. 84 Ks)
        quotas = annual_quotas_remaining_mm
        if quotas is None and self.water_quota_m3 is not None:
            q_mm = float(self.water_quota_m3) / max(0.1, self.area_ha) / 10.0
            quotas = {year_idx: q_mm, year_idx + 1: q_mm}

        water_res = SoilPhysicsEngine.simulate_monthly_water_balance(
            crop=crop,
            soil_props=self.soil_props,
            monthly_climate=self.monthly_climate,
            latitude_deg=self.latitude_deg,
            smap_rootzone_moisture=self.smap_moisture,
            initial_storage_mm=start_storage_mm,
            prev_rooting_depth_m=prev_rooting_depth_m,
            has_irrigation=self.has_irrigation,
            irrigation_method=self.irrigation_method,
            annual_quotas_remaining_mm=quotas,
            base_calendar_year=year_idx,
            sand_pct=self.soilgrids_sand_pct,
            clay_pct=self.eff_clay_pct,
            soc_pct=start_soc_pct,
            farmer_calendars=self.crop_calendars,
            ggcmi_calendars=self.ggcmi_crop_calendar,
        )
        etc_mm = water_res["etc_mm"]
        eta_mm = water_res["eta_mm"]
        peff_mm = water_res["peff_mm"]
        irr_applied_mm = water_res["irrigation_gross_mm"]
        irr_m3_ha = water_res["irrigation_m3_ha"]
        ks = water_res["ks"]
        rel_deficit = water_res["relative_et_deficit"]
        mu_water = water_res["fao33_mu_water"]

        # 2. Relative-Stress Yield Attenuation: Y = Y_ref * (Pi mu_parcel / Pi mu_ref) * mu_family (capped at Y_att)
        ph_dist = max(0.0, crop.optimal_ph_min - self.soil_ph, self.soil_ph - crop.optimal_ph_max)
        ph_loss_frac = min(0.40, ph_dist * 0.14)
        mu_ph = max(0.0, 1.0 - ph_loss_frac)

        est_season_temp = self._compute_occupied_season_temp(crop, water_res["calendar_months"], use_ambient=True)
        temp_dist = max(0.0, crop.optimal_temp_min_c - est_season_temp, est_season_temp - crop.optimal_temp_max_c)
        thermal_loss_frac = min(0.45, temp_dist * 0.045)
        if self.heatwave_days_count > 10 and crop.extreme_heat_resistance < 2.5:
            thermal_loss_frac = min(0.55, thermal_loss_frac + ((self.heatwave_days_count - 10) * 0.012))
        mu_thermal = max(0.25, 1.0 - thermal_loss_frac)

        comp_excess = max(0.0, start_compaction_psi - crop.critical_compaction_limit_psi)
        comp_loss_frac = min(0.25, comp_excess * 0.0025) if crop.compaction_relief_delta_psi >= 0.0 else 0.0
        mu_comp = max(0.0, 1.0 - comp_loss_frac)

        same_family_repeat = preceding_crop is not None and crop.botanical_family == preceding_crop.botanical_family
        mu_family = 0.88 if same_family_repeat else 1.0

        pi_mu_parcel = max(0.0, mu_water * mu_ph * mu_thermal * mu_comp)
        pi_mu_ref = self._compute_reference_stress_product(crop)

        y_ref = float(
            self.regional_crop_yields.get(crop.crop_id)
            or crop.reference_yield_tons_ha
            or crop.potential_yield_tons_ha
        )
        stress_ratio = pi_mu_parcel / max(0.25, pi_mu_ref)
        if crop.bolinder_rp == 0.0:
            actual_yield_tons_ha = round(max(0.5, min(crop.potential_yield_tons_ha * 1.15, y_ref * stress_ratio * mu_family)), 2)
        else:
            raw_y = y_ref * stress_ratio * mu_family
            actual_yield_tons_ha = round(min(crop.potential_yield_tons_ha, max(0.15 * y_ref, raw_y)), 2)

        total_yield_tons = round(actual_yield_tons_ha * self.area_ha, 2)
        effective_market_price = float(self.crop_market_prices.get(crop.crop_id) or crop.market_price_usd_ton)
        gross_rev_ha = actual_yield_tons_ha * effective_market_price

        # 3. Soil Organic Carbon Dynamics (Exact analytical Henin-Dupuis + Mary-Guerif CaCO3 k2 + Bolinder C)
        fine_mass_factor = max(10.0, 100.0 * self.eff_rho_b * 0.30 * (1.0 - self.eff_cf_frac))
        c_stock_start = start_c_stock_t_ha if start_c_stock_t_ha is not None else (fine_mass_factor * start_soc_pct)
        end_soc_pct, delta_soc_pct, c_input, k2 = SoilPhysicsEngine.simulate_soc_dynamics(
            crop=crop,
            soil_props=self.soil_props,
            current_soc_pct=start_soc_pct,
            mean_annual_temp_c=self.mean_temp_c,
            tillage_factor=self.tillage_factor,
            actual_yield_tons_ha=actual_yield_tons_ha,
            soilgrids_clay_pct=self.eff_clay_pct,
            soilgrids_bulk_density_g_cm3=self.eff_rho_b,
            caco3_g_kg=self.caco3_g_kg,
            coarse_fragments_frac=self.eff_cf_frac,
            straw_export_fraction=self.straw_export_fraction,
            c_stock_start_override_t_ha=c_stock_start,
        )
        c_stock_end = round(end_soc_pct * fine_mass_factor, 3)

        # 4. Coupled Carbon-Nitrogen Budget (Herridge/Peoples BNF, C-coupled N_min, RE_N=0.40, IPCC 2019 leaching/N2O)
        n_res = SoilPhysicsEngine.calculate_nitrogen_budget_detailed(
            crop=crop,
            yield_tons_ha=actual_yield_tons_ha,
            c_stock_start_t_ha=c_stock_start,
            k2_rate=k2,
            preceding_legume_credit_kg_ha=preceding_legume_credit_kg_ha,
            preceding_scavenged_credit_kg_ha=preceding_scavenged_credit_kg_ha,
            cn_ratio=self.cn_ratio,
            monthly_climate=self.monthly_climate,
            calendar_months=water_res["calendar_months"],
            annual_precip_mm=self.annual_precip_mm,
            annual_et0_mm=self.annual_et0_mm,
            straw_export_fraction=self.straw_export_fraction,
            max_legal_n_kg_ha=self.max_legal_n_kg_ha,
        )
        net_n_bal = n_res["net_soil_n_balance_kg_ha"]
        bio_n_fixed = n_res["biological_n_fixed_kg_ha"]
        synth_n_needed = n_res["synthetic_n_applied_kg_ha"]
        leg_credit_used = n_res["legume_credit_used_kg_ha"]

        # 5. Itemized Costs ($/ha): Gross water withdrawals & elemental N, P, K nutrient pricing
        seed_cost = crop.seed_cost_usd_ha * self.p_seed_mult
        water_cost = irr_m3_ha * self.p_water_m3
        fuel_cost = crop.fuel_consumption_liters_ha * self.p_diesel_liter
        fert_n_cost = synth_n_needed * self.p_elem_n_kg
        elem_p_removed = actual_yield_tons_ha * crop.phosphorus_uptake_kg_per_ton
        elem_k_removed = actual_yield_tons_ha * crop.potassium_uptake_kg_per_ton
        fert_p_cost = elem_p_removed * self.p_elem_p_kg
        fert_k_cost = elem_k_removed * self.p_elem_k_kg
        labor_cost = crop.labor_hours_per_ha * self.p_labor_hour
        protection_cost = crop.fixed_operational_cost_usd_ha * (1.20 if same_family_repeat else 1.0)

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

        # 6. Soil Compaction Heuristic (ASAE S313.3 Cone Index proxy; ~290 PSI / 2 MPa critical threshold)
        end_compaction_psi, delta_psi = SoilPhysicsEngine.simulate_soil_compaction(
            crop=crop,
            current_compaction_psi=start_compaction_psi,
            soil_props=self.soil_props
        )

        # 7. Soil Erosion (RUSLE with GloREDa R, max parcel slope, EPIC K, Panagos C)
        erosion_t_ha = SoilPhysicsEngine.calculate_rusle_erosion(
            crop=crop,
            soil_props=self.soil_props,
            slope_pct=self.slope_pct,
            annual_precip_mm=self.annual_precip_mm,
            soilgrids_sand_pct=self.soilgrids_sand_pct,
            soilgrids_silt_pct=self.soilgrids_silt_pct,
            soilgrids_clay_pct=self.eff_clay_pct,
            soilgrids_soc_pct=start_soc_pct,
            area_hectares=self.area_ha,
            gloreda_r_factor=self.gloreda_r_factor,
            latitude_deg=self.latitude_deg,
            longitude_deg=self.longitude_deg,
            slope_max_pct=self.slope_max_pct,
        )

        # 8. Site-Grounded Climate & Hazard Vulnerability Score (0-100)
        aridity_ratio = self.annual_et0_mm / max(120.0, self.annual_precip_mm)
        drought_exposure = min(2.2, max(0.4, (aridity_ratio - 0.5) * 1.1 + (self.longest_dry_spell_days / 45.0) + (2.0 * rel_deficit)))
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
            ((1.0 - mu_water) * 35.0) +
            (comp_loss_frac * 20.0)
        )
        climate_vuln_score = round(max(5.0, min(100.0, climate_vuln)), 1)

        # Ground Narrative Construction
        narrative_parts = []
        if crop.is_legume:
            narrative_parts.append(
                f"Fixed {bio_n_fixed:.0f} kg N/ha via symbiotic rhizobia (own N balance {net_n_bal:+.1f} kg N/ha; "
                f"{n_res['next_legume_credit_kg_ha']:.0f} kg N/ha released to next crop)."
            )
        else:
            narrative_parts.append(
                f"Removed {n_res['n_harvest_export_kg_ha']:.0f} kg N/ha in harvest; soil mineralized {n_res['soil_mineralized_n_kg_ha']:.0f} kg N/ha "
                f"and applied {synth_n_needed:.0f} kg synthetic N/ha (RE_N=0.40)."
            )

        if delta_psi < -10.0:
            narrative_parts.append(f"Deep taproot bio-drilled subsoil hardpan heuristic by {delta_psi:+.1f} PSI, enhancing infiltration.")
        elif delta_psi > 15.0:
            narrative_parts.append(f"Machinery traffic added {delta_psi:+.1f} PSI cone resistance heuristic toward {end_compaction_psi:.0f} PSI.")

        if delta_soc_pct > 0.0:
            narrative_parts.append(f"Biomass residue humification built SOC from {start_soc_pct:.2f}% to {end_soc_pct:.2f}%.")
        else:
            narrative_parts.append(f"Microbial mineralization reduced SOC from {start_soc_pct:.2f}% to {end_soc_pct:.2f}%.")

        ground_narrative = " ".join(narrative_parts)

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
            phosphorus_balance_kg_ha=round(-elem_p_removed, 1),
            potassium_balance_kg_ha=round(-elem_k_removed, 1),
            biological_n_fixed_kg_ha=bio_n_fixed,
            synthetic_n_applied_kg_ha=synth_n_needed,
            legume_n_credit_used_kg_ha=leg_credit_used,
            soil_mineralized_n_kg_ha=n_res["soil_mineralized_n_kg_ha"],
            nitrogen_surplus_kg_ha=n_res["nitrogen_surplus_kg_ha"],
            nitrogen_leaching_kg_ha=n_res["nitrogen_leaching_kg_ha"],
            direct_n2o_n_kg_ha=n_res["direct_n2o_n_kg_ha"],
            soc_pct_start=start_soc_pct,
            soc_pct_end=end_soc_pct,
            soc_change_pct=delta_soc_pct,
            carbon_input_tons_ha=c_input,
            compaction_psi_start=start_compaction_psi,
            compaction_psi_end=end_compaction_psi,
            compaction_change_psi=delta_psi,
            compaction_is_heuristic=True,
            water_demand_etc_mm=etc_mm,
            actual_et_eta_mm=eta_mm,
            relative_et_deficit=rel_deficit,
            fao33_outside_calibrated_range=water_res["fao33_outside_calibrated_range"],
            effective_precipitation_mm=peff_mm,
            irrigation_water_applied_mm=irr_applied_mm,
            irrigation_volume_m3=round(irr_m3_ha * self.area_ha, 1),
            irrigation_method=water_res["irrigation_method"],
            irrigation_efficiency_ea=water_res["irrigation_efficiency_ea"],
            water_stress_coefficient_ks=ks,
            soil_erosion_tons_ha=erosion_t_ha,
            rhizosphere_vitality_score=rhizo_score,
            pathogen_disease_risk_score=pathogen_score,
            extreme_event_vulnerability_score=climate_vuln_score,
            ground_narrative=ground_narrative,
        )

        next_state = {
            "next_legume_credit_kg_ha": n_res["next_legume_credit_kg_ha"],
            "next_scavenged_credit_kg_ha": n_res["next_scavenged_credit_kg_ha"],
            "end_storage_mm": water_res["end_storage_mm"],
            "end_rooting_depth_m": water_res["end_rooting_depth_m"],
            "end_c_stock_t_ha": c_stock_end,
        }
        return impact, next_state

    def simulate_three_year_plan(
        self,
        strategy_id: str,
        strategy_title: str,
        core_objective: str,
        sequence: List[CropAgronomicProfile]
    ) -> ThreeYearCultivationPlan:
        """Runs the multi-year sequential simulation carrying forward C_t, S_t, PSI_t, N_credit, and shared quotas."""
        c1, c2, c3 = sequence

        quotas_remaining: Optional[Dict[int, float]] = None
        if self.water_quota_m3 is not None:
            q_mm = float(self.water_quota_m3) / max(0.1, self.area_ha) / 10.0
            quotas_remaining = {1: q_mm, 2: q_mm, 3: q_mm, 4: q_mm}

        # Year 1 (initialized from Year 0 water spin-up if history exists, and initial C stock)
        y1_impact, st1 = self._simulate_annual_impact_step(
            year_idx=1,
            crop=c1,
            preceding_crop=self.initial_preceding_crop,
            start_soc_pct=self.init_soc_pct,
            start_compaction_psi=self.init_compaction_psi,
            preceding_legume_credit_kg_ha=0.0,
            preceding_scavenged_credit_kg_ha=0.0,
            start_storage_mm=self.spinup_storage_mm,
            prev_rooting_depth_m=self.spinup_rooting_depth_m,
            start_c_stock_t_ha=self.init_c_stock_t_ha,
            annual_quotas_remaining_mm=quotas_remaining,
        )

        # Year 2: Carries forward Year 1 ending SOC, C_stock, S_t, compaction PSI, and N credits
        y2_impact, st2 = self._simulate_annual_impact_step(
            year_idx=2,
            crop=c2,
            preceding_crop=c1,
            start_soc_pct=y1_impact.soc_pct_end,
            start_compaction_psi=y1_impact.compaction_psi_end,
            preceding_legume_credit_kg_ha=st1["next_legume_credit_kg_ha"],
            preceding_scavenged_credit_kg_ha=st1["next_scavenged_credit_kg_ha"],
            start_storage_mm=st1["end_storage_mm"],
            prev_rooting_depth_m=st1["end_rooting_depth_m"],
            start_c_stock_t_ha=st1["end_c_stock_t_ha"],
            annual_quotas_remaining_mm=quotas_remaining,
        )

        # Year 3: Carries forward Year 2 ending state
        y3_impact, _ = self._simulate_annual_impact_step(
            year_idx=3,
            crop=c3,
            preceding_crop=c2,
            start_soc_pct=y2_impact.soc_pct_end,
            start_compaction_psi=y2_impact.compaction_psi_end,
            preceding_legume_credit_kg_ha=st2["next_legume_credit_kg_ha"],
            preceding_scavenged_credit_kg_ha=st2["next_scavenged_credit_kg_ha"],
            start_storage_mm=st2["end_storage_mm"],
            prev_rooting_depth_m=st2["end_rooting_depth_m"],
            start_c_stock_t_ha=st2["end_c_stock_t_ha"],
            annual_quotas_remaining_mm=quotas_remaining,
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
        synth_n_saved = round((y2_impact.legume_n_credit_used_kg_ha + y3_impact.legume_n_credit_used_kg_ha) * self.p_elem_n_kg * self.area_ha, 2)

        net_compact = round(y3_impact.compaction_psi_end - self.init_compaction_psi, 1)
        total_irr_m3 = round(y1_impact.irrigation_volume_m3 + y2_impact.irrigation_volume_m3 + y3_impact.irrigation_volume_m3, 1)
        avg_erosion = round((y1_impact.soil_erosion_tons_ha + y2_impact.soil_erosion_tons_ha + y3_impact.soil_erosion_tons_ha) / 3.0, 2)
        total_n_surplus = round(y1_impact.nitrogen_surplus_kg_ha + y2_impact.nitrogen_surplus_kg_ha + y3_impact.nitrogen_surplus_kg_ha, 1)
        total_n_leach = round(y1_impact.nitrogen_leaching_kg_ha + y2_impact.nitrogen_leaching_kg_ha + y3_impact.nitrogen_leaching_kg_ha, 2)
        total_direct_n2o = round(y1_impact.direct_n2o_n_kg_ha + y2_impact.direct_n2o_n_kg_ha + y3_impact.direct_n2o_n_kg_ha, 2)

        # Composite Regenerative Soil Health Score (0-100): SOC, erosion, BNF, low N losses, secondary compaction heuristic
        soc_score = min(30.0, max(0.0, 15.0 + (net_soc * 40.0)))
        n_fix_score = min(25.0, (total_n_fix / 200.0) * 25.0)
        compaction_score = min(15.0, max(0.0, 7.5 - (net_compact * 0.3)))
        erosion_score = max(0.0, 18.0 - (avg_erosion * 2.0))
        diversity_families = len({c1.botanical_family, c2.botanical_family, c3.botanical_family})
        diversity_score = diversity_families * 4.0
        n_loss_penalty = min(12.0, (total_n_leach / 120.0) * 8.0 + (total_direct_n2o / 8.0) * 4.0)
        soil_health_score = round(min(100.0, max(10.0, soc_score + n_fix_score + compaction_score + erosion_score + diversity_score - n_loss_penalty)), 1)

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
            total_nitrogen_surplus_kg_ha=total_n_surplus,
            total_nitrogen_leaching_kg_ha=total_n_leach,
            total_direct_n2o_n_kg_ha=total_direct_n2o,
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

    def _triplet_respects_rotation_breaks(self, c1: CropAgronomicProfile, c2: CropAgronomicProfile, c3: CropAgronomicProfile) -> bool:
        """
        Enforces phytosanitary break intervals (`rotational_break_needed_years`) across BOTH the
        farmer's 5-year crop history and Years 1 -> 2 -> 3, plus consecutive cover-crop exclusion.
        """
        if c1.botanical_family == c2.botanical_family == c3.botanical_family:
            return False
        if (c1.crop_id == "daikon_radish_cover" and c2.crop_id == "daikon_radish_cover") or (
            c2.crop_id == "daikon_radish_cover" and c3.crop_id == "daikon_radish_cover"
        ):
            return False

        hist = self.past_crop_profiles
        n_hist = len(hist)
        timeline = hist + [c1, c2, c3]
        for idx in range(n_hist, len(timeline)):
            cur = timeline[idx]
            for prev_idx in range(idx):
                prev = timeline[prev_idx]
                if cur.botanical_family != prev.botanical_family:
                    continue
                req_break = max(cur.rotational_break_needed_years, prev.rotational_break_needed_years)
                if req_break >= 2 and (idx - prev_idx) <= req_break:
                    return False
        return True

    def optimize_all_strategies(self) -> Dict[str, ThreeYearCultivationPlan]:
        """
        Explores all valid 3-year sequences and extracts the 5 optimal champion strategies.
        Does NOT re-admit biophysically excluded crops when <3 candidates survive strict filtering.
        """
        candidates = self._filter_candidate_crops()
        if not candidates:
            raise ValueError(
                f"No admissible catalog crops remain after strict biophysical and pH ({self.soil_ph}) lockout "
                "(requires local soil amendment such as liming/gypsum or protected cultivation)."
            )

        valid_triplets: List[Tuple[CropAgronomicProfile, CropAgronomicProfile, CropAgronomicProfile]] = [
            (c1, c2, c3)
            for c1 in candidates
            for c2 in candidates
            for c3 in candidates
            if self._triplet_respects_rotation_breaks(c1, c2, c3)
        ]

        # Graceful relaxation ONLY within admissible candidates when <3 candidates or tight breaks leave 0 triplets
        if not valid_triplets:
            valid_triplets = [
                (c1, c2, c3)
                for c1 in candidates
                for c2 in candidates
                for c3 in candidates
                if not (c1.botanical_family == c2.botanical_family == c3.botanical_family)
            ]
        if not valid_triplets:
            valid_triplets = [(c1, c2, c3) for c1 in candidates for c2 in candidates for c3 in candidates]

        evaluated_plans: List[Tuple[Tuple[str, str, str], ThreeYearCultivationPlan]] = []
        for triplet in valid_triplets:
            plan = self.simulate_three_year_plan("cand", "Candidate", "Candidate", list(triplet))
            seq_key = (triplet[0].crop_id, triplet[1].crop_id, triplet[2].crop_id)
            evaluated_plans.append((seq_key, plan))

        chosen_sequences: Set[Tuple[str, str, str]] = set()

        def pick_champion(key_fn, reverse=True, pool=None) -> ThreeYearCultivationPlan:
            src = pool if pool is not None else evaluated_plans
            sorted_candidates = sorted(src, key=lambda x: key_fn(x[1]), reverse=reverse)
            for seq_k, candidate_plan in sorted_candidates:
                if seq_k not in chosen_sequences:
                    chosen_sequences.add(seq_k)
                    return candidate_plan
            return sorted_candidates[0][1]

        # 1. Most Income
        raw_income = pick_champion(lambda p: p.cumulative_metrics.total_net_profit_usd, reverse=True)
        plan_income = self.simulate_three_year_plan(
            strategy_id="most_income",
            strategy_title="Most Income Strategy",
            core_objective="Maximize 3-year cumulative net profit ($) while maintaining legal water and rotation constraints",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_income.year_1.crop_id, raw_income.year_2.crop_id, raw_income.year_3.crop_id]]
        )

        # 2. Best Soil Health
        raw_soil = pick_champion(lambda p: p.cumulative_metrics.cumulative_soil_health_score, reverse=True)
        plan_soil = self.simulate_three_year_plan(
            strategy_id="best_soil_health",
            strategy_title="Best Soil Health Strategy",
            core_objective="Maximize Soil Organic Carbon (SOC) build, Biological N Fixation, low N losses, and erosion suppression",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_soil.year_1.crop_id, raw_soil.year_2.crop_id, raw_soil.year_3.crop_id]]
        )

        # 3. Least Effort / Labour (preserving positive farm margin where achievable)
        profitable_pool = [item for item in evaluated_plans if item[1].cumulative_metrics.total_net_profit_usd > 0]
        raw_labor = pick_champion(
            lambda p: (
                p.cumulative_metrics.total_labor_hours
                + (p.cumulative_metrics.total_machinery_passes * 1.5)
                + (p.cumulative_metrics.total_irrigation_volume_m3 / 1000.0)
            ),
            reverse=False,
            pool=profitable_pool or evaluated_plans,
        )
        plan_labor = self.simulate_three_year_plan(
            strategy_id="least_effort",
            strategy_title="Least Effort / Labour Strategy",
            core_objective="Minimize labor hours, tractor passes, and pumping burden while preserving positive farm margin",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_labor.year_1.crop_id, raw_labor.year_2.crop_id, raw_labor.year_3.crop_id]]
        )

        # 4. Highest ROI (%)
        raw_roi = pick_champion(lambda p: p.cumulative_metrics.cumulative_roi_pct, reverse=True)
        plan_roi = self.simulate_three_year_plan(
            strategy_id="highest_roi",
            strategy_title="Highest Capital ROI (%) Strategy",
            core_objective="Maximize percentage return on production capital invested across the 3 years",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_roi.year_1.crop_id, raw_roi.year_2.crop_id, raw_roi.year_3.crop_id]]
        )

        # 5. Least Amount of Crop Loss Risk
        raw_risk = pick_champion(lambda p: p.cumulative_metrics.composite_loss_risk_score, reverse=False)
        plan_risk = self.simulate_three_year_plan(
            strategy_id="least_crop_loss_risk",
            strategy_title="Least Crop Loss Risk Strategy",
            core_objective="Minimize vulnerability to climate extremes (ET deficit, frost, heat) and soil-borne pathogens",
            sequence=[MASTER_CROPS_CATALOG[c] for c in [raw_risk.year_1.crop_id, raw_risk.year_2.crop_id, raw_risk.year_3.crop_id]]
        )

        return {
            "most_income": plan_income,
            "best_soil_health": plan_soil,
            "least_effort": plan_labor,
            "highest_roi": plan_roi,
            "least_crop_loss_risk": plan_risk,
        }

    def get_calibration_and_assumptions(self) -> Dict[str, Any]:
        """Returns Table 2 calibration metadata, empirical boundaries, and soil/water provenance warnings."""
        _, r_source = SoilPhysicsEngine.resolve_gloreda_r_factor(
            annual_precip_mm=self.annual_precip_mm,
            gloreda_r_factor=self.gloreda_r_factor,
            latitude_deg=self.latitude_deg,
            longitude_deg=self.longitude_deg,
        )
        approx_crops = [
            c.crop_id for c in MASTER_CROPS_CATALOG.values() if getattr(c, "bolinder_flagged_no_published_set", False)
        ]
        ph_fallback_crops = [
            c.crop_id for c in MASTER_CROPS_CATALOG.values() if c.abs_ph_min is None or c.abs_ph_max is None
        ]
        calcareous_warning = None
        if self.soil_ph >= 7.5 and self.caco3_g_kg == 0.0:
            calcareous_warning = (
                f"Topsoil pH {self.soil_ph:.2f} >= 7.5 with unmeasured CaCO3 (SoilGrids v2.0 omits carbonate); "
                "using 0 g/kg pending lab carbonate or dilute-HCl field fizz test."
            )
        high_temp_warning = None
        if self.mean_temp_c > 20.0:
            high_temp_warning = (
                f"Mean annual temperature {self.mean_temp_c:.1f} C exceeds 20 C; Mary & Guerif k2 mineralization rate "
                "is extrapolated above its temperate French calibration domain."
            )

        return {
            "methodology_version": "v1.1",
            "et0_method_used": self.et0_method_used,
            "rusle_r_source": r_source,
            "irrigation_method": self.irrigation_method,
            "irrigation_efficiency_ea": self.irrigation_efficiency_ea,
            "compaction_status": (
                f"Measured in-situ cone index ({self.init_compaction_psi:.0f} PSI)"
                if self.compaction_is_measured
                else f"Modeled heuristic proxy ({self.init_compaction_psi:.0f} PSI; unmeasured; critical limit ~290 PSI / 2 MPa)"
            ),
            "calcareous_soil_warning": calcareous_warning,
            "high_temp_k2_extrapolation_warning": high_temp_warning,
            "bolinder_approximated_crops": approx_crops,
            "ecocrop_ph_fallback_crops": ph_fallback_crops,
            "uncalibrated_model_parameters": {
                "fertilizer_recovery_efficiency_re_n": 0.40,
                "k1_above_annual": 0.15,
                "k1_below_annual": 0.30,
                "rhizodeposition_to_root_ratio": 0.65,
                "continuous_family_yield_drag": 0.88,
                "ph_penalty_per_unit": 0.14,
                "flood_score_gate": 2.0,
                "compaction_relief_deltas_psi": "ASAE S313.3 heuristic (confirm plowpan depth by spade/penetrometer)",
            },
        }
