"""
Comprehensive Automated Unit and Integration Test Suite
for the 3-Year Crop Planning & Ground Impact Simulation Engine.
Tests:
1. Henin-Dupuis SOC dynamics, ASAE compaction, Herridge BNF, FAO-56 ET0, RUSLE erosion
2. 3-Year Multi-Objective Plan Optimizer (5 distinct strategies)
3. Sequential physical state carryover (Year 1 -> Year 2 -> Year 3)
4. Google Gemini 3.8 Advisory & Deterministic Offline Fallback Engine
5. FastAPI HTTP endpoints (/api/projections/plan-3year, /crops-catalog, /soil-profiles)
"""

import pytest
from fastapi.testclient import TestClient

from projection_api.main import app
from projection_api.models.crops_catalog import (
    MASTER_CROPS_CATALOG, get_crop_profile, BotanicalFamily
)
from projection_api.services.soil_physics import SoilPhysicsEngine
from projection_api.services.plan_optimizer import PlanOptimizerEngine
from projection_api.services.gemini_advisor import GeminiAdvisorEngine


client = TestClient(app)


# ==============================================================================
# 1. SOIL PHYSICS & AGRONOMIC MODEL TESTS
# ==============================================================================

def test_soil_properties_retrieval():
    clay_props = SoilPhysicsEngine.get_soil_properties("Clay")
    assert clay_props["clay_pct"] == 48.0
    assert clay_props["bulk_density_g_cm3"] == 1.25

    loam_props = SoilPhysicsEngine.get_soil_properties("Loam")
    assert loam_props["clay_pct"] == 20.0
    assert loam_props["theta_fc"] == 0.27


def test_fao56_penman_monteith_et0_computation():
    et0 = SoilPhysicsEngine.calculate_fao56_penman_monteith_et0(
        t_max=32.0,
        t_min=18.0,
        solar_rad_mj_m2=24.5,
        wind_speed_2m=2.2,
        rh_mean=55.0,
        elevation_m=120.0,
        latitude_deg=41.5,
        day_of_year=180
    )
    assert et0 > 3.0
    assert et0 < 8.0  # Typical summer temperate ET0 range (mm/day)


def test_henin_dupuis_soc_dynamics():
    soil_props = SoilPhysicsEngine.get_soil_properties("Loam")
    corn = MASTER_CROPS_CATALOG["corn"]
    
    # Starting at 1.80% SOC
    end_soc, delta_soc, c_in, k2 = SoilPhysicsEngine.simulate_soc_dynamics(
        crop=corn,
        soil_props=soil_props,
        current_soc_pct=1.80,
        mean_annual_temp_c=14.0
    )
    assert c_in > 2.0  # Significant carbon input from corn stover and roots
    assert k2 > 0.015 and k2 < 0.035  # Valid annual mineralization rate range
    assert abs(delta_soc) < 0.20  # Annual SOC changes are typically within 0.1-0.2%


def test_alfalfa_soc_enhancement():
    soil_props = SoilPhysicsEngine.get_soil_properties("Loam")
    alfalfa = MASTER_CROPS_CATALOG["alfalfa"]
    
    end_soc, delta_soc, c_in, k2 = SoilPhysicsEngine.simulate_soc_dynamics(
        crop=alfalfa,
        soil_props=soil_props,
        current_soc_pct=1.80,
        mean_annual_temp_c=14.0
    )
    assert delta_soc > 0.0  # Alfalfa is a strong soil builder


def test_asae_cone_index_compaction_and_biodrill():
    soil_props = SoilPhysicsEngine.get_soil_properties("Loam")
    
    # 1. Corn with 4 machinery passes adds compaction
    corn = MASTER_CROPS_CATALOG["corn"]
    psi_after_corn, delta_corn = SoilPhysicsEngine.simulate_soil_compaction(
        crop=corn,
        current_compaction_psi=200.0,
        soil_props=soil_props
    )
    assert delta_corn > 0.0
    assert psi_after_corn > 200.0

    # 2. Daikon Radish bio-drill taproot alleviates hardpan
    radish = MASTER_CROPS_CATALOG["daikon_radish_cover"]
    psi_after_radish, delta_radish = SoilPhysicsEngine.simulate_soil_compaction(
        crop=radish,
        current_compaction_psi=260.0,
        soil_props=soil_props
    )
    assert delta_radish < 0.0  # Significant compaction reduction
    assert psi_after_radish < 260.0


def test_herridge_biological_nitrogen_fixation():
    soybean = MASTER_CROPS_CATALOG["soybeans"]
    net_n, bio_fixed, synth_n, leg_used = SoilPhysicsEngine.calculate_nitrogen_balance(
        crop=soybean,
        yield_tons_ha=3.4,
        preceding_legume_credit_kg_ha=0.0,
        in_situ_soil_nitrate_ppm=20.0
    )
    assert bio_fixed > 100.0  # Legumes fix substantial atmospheric N
    assert synth_n == 0.0     # Legumes do not require synthetic N fertilizer

    # Non-legume corn should require synthetic N
    corn = MASTER_CROPS_CATALOG["corn"]
    net_n_corn, bio_fixed_corn, synth_n_corn, leg_used_corn = SoilPhysicsEngine.calculate_nitrogen_balance(
        crop=corn,
        yield_tons_ha=9.5,
        preceding_legume_credit_kg_ha=45.0,  # Credit from preceding soybean
        in_situ_soil_nitrate_ppm=20.0
    )
    assert bio_fixed_corn == 0.0
    assert leg_used_corn == 45.0             # Successfully uses legume credit!
    assert synth_n_corn > 100.0              # Needs synthetic N for high corn yield


def test_rusle_soil_loss():
    soil_props = SoilPhysicsEngine.get_soil_properties("Sandy Loam")
    corn = MASTER_CROPS_CATALOG["corn"]
    erosion_corn = SoilPhysicsEngine.calculate_rusle_erosion(
        crop=corn,
        soil_props=soil_props,
        slope_pct=3.0,
        annual_precip_mm=700.0
    )
    assert erosion_corn > 0.0

    wheat = MASTER_CROPS_CATALOG["winter_wheat"]
    erosion_wheat = SoilPhysicsEngine.calculate_rusle_erosion(
        crop=wheat,
        soil_props=soil_props,
        slope_pct=3.0,
        annual_precip_mm=700.0
    )
    # Winter wheat has dense cover and should exhibit lower erosion than corn
    assert erosion_wheat < erosion_corn


# ==============================================================================
# 2. PLAN OPTIMIZER & MULTI-OBJECTIVE SOLVER TESTS
# ==============================================================================

@pytest.fixture
def sample_field_profile():
    return {
        "area_hectares": 12.5,
        "resolved_soil_type": "Loam",
        "elevation_m": 160.0,
        "slope_pct": 2.5,
        "has_greenhouse": False,
        "legal_water_quota_m3": 50000.0,
        "baseline_soc_pct": 1.85,
        "baseline_compaction_psi": 220.0,
        "baseline_nitrate_ppm": 24.0,
        "annual_et0_mm": 1100.0,
        "annual_precip_mm": 640.0,
        "mean_temp_c": 13.8,
        "smap_rootzone_moisture": 0.27,
        "low_spot_waterlogging_hazard": False,
        "preceding_crop_name": "Corn (Maize)",
        "seed_price_multiplier": 1.0,
        "water_price_usd_m3": 0.08,
        "diesel_price_usd_liter": 1.15,
        "fertilizer_n_price_usd_kg": 1.35,
        "fertilizer_p_price_usd_kg": 1.60,
        "fertilizer_k_price_usd_kg": 0.95,
        "labor_hourly_wage_usd": 22.0,
    }


def test_plan_optimizer_generates_all_five_strategies(sample_field_profile):
    optimizer = PlanOptimizerEngine(sample_field_profile)
    strategies = optimizer.optimize_all_strategies()

    assert "most_income" in strategies
    assert "best_soil_health" in strategies
    assert "least_effort" in strategies
    assert "highest_roi" in strategies
    assert "least_crop_loss_risk" in strategies

    # Verify that each plan has 3 distinct years
    for strat_id, plan in strategies.items():
        assert len(plan.rotation_sequence) == 3
        assert plan.year_1.year_index == 1
        assert plan.year_2.year_index == 2
        assert plan.year_3.year_index == 3
        assert plan.cumulative_metrics.total_net_profit_usd is not None
        assert plan.cumulative_metrics.cumulative_roi_pct is not None
        assert plan.cumulative_metrics.cumulative_soil_health_score >= 0.0


def test_most_income_vs_least_effort_differentiation(sample_field_profile):
    optimizer = PlanOptimizerEngine(sample_field_profile)
    strategies = optimizer.optimize_all_strategies()

    income_plan = strategies["most_income"]
    labor_plan = strategies["least_effort"]

    # Most income plan must generate higher net profit than least effort plan
    assert income_plan.cumulative_metrics.total_net_profit_usd >= labor_plan.cumulative_metrics.total_net_profit_usd

    # Least effort plan must require fewer or equal labor hours compared to income plan
    assert labor_plan.cumulative_metrics.total_labor_hours <= income_plan.cumulative_metrics.total_labor_hours


def test_best_soil_health_characteristics(sample_field_profile):
    optimizer = PlanOptimizerEngine(sample_field_profile)
    strategies = optimizer.optimize_all_strategies()

    soil_plan = strategies["best_soil_health"]
    # Best soil health plan must exhibit high soil health score and positive biological N fixation
    assert soil_plan.cumulative_metrics.cumulative_soil_health_score >= 60.0
    assert soil_plan.cumulative_metrics.total_biological_n_fixed_kg_ha > 0.0


def test_sequential_state_carryover(sample_field_profile):
    optimizer = PlanOptimizerEngine(sample_field_profile)
    strategies = optimizer.optimize_all_strategies()

    for strat_id, plan in strategies.items():
        # Year 2 start SOC must match Year 1 end SOC exactly
        assert plan.year_2.soc_pct_start == plan.year_1.soc_pct_end
        # Year 3 start SOC must match Year 2 end SOC exactly
        assert plan.year_3.soc_pct_start == plan.year_2.soc_pct_end

        # Compaction PSI continuity
        assert plan.year_2.compaction_psi_start == plan.year_1.compaction_psi_end
        assert plan.year_3.compaction_psi_start == plan.year_2.compaction_psi_end


# ==============================================================================
# 3. GEMINI ADVISOR & DETERMINISTIC FALLBACK TESTS
# ==============================================================================

def test_gemini_advisor_deterministic_fallback(sample_field_profile):
    optimizer = PlanOptimizerEngine(sample_field_profile)
    strategies = optimizer.optimize_all_strategies()

    advisor = GeminiAdvisorEngine()
    parcel_context = {
        "cadastral_id": "PARCEL-TEST-01",
        "area_hectares": 12.5,
        "soil_type": "Loam",
        "elevation_m": 160.0,
        "slope_pct": 2.5,
    }
    climate_context = {
        "annual_et0_mm": 1100.0,
        "annual_precip_mm": 640.0,
        "mean_temp_c": 13.8,
        "smap_rootzone_moisture": 0.27,
        "low_spot_hazard": False,
    }

    report = advisor.generate_advisory_report(
        parcel_info=parcel_context,
        climate_baseline=climate_context,
        strategies=strategies
    )

    assert report.executive_summary
    assert len(report.executive_summary) > 50
    assert report.parcel_climate_context
    assert report.strategy_tradeoff_matrix
    assert report.year_by_year_soil_transformation
    assert report.extreme_event_resilience_playbook
    assert report.farmer_decision_guide
    assert len(report.ground_truth_field_checklist) >= 4


# ==============================================================================
# 4. HTTP API INTEGRATION TESTS
# ==============================================================================

def test_http_crops_catalog():
    response = client.get("/api/projections/crops-catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["crops_count"] == 12
    assert len(data["crops"]) == 12


def test_http_soil_profiles():
    response = client.get("/api/projections/soil-profiles")
    assert response.status_code == 200
    data = response.json()
    assert data["profiles_count"] >= 6
    assert "loam" in data["profiles"]
    assert "clay" in data["profiles"]


def test_http_root_metadata():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "plan_3year" in data["endpoints"]
    assert "most_income" in data["supported_strategies"]


def test_http_plan_3year_endpoint_execution():
    """End-to-end integration test with full payload to /api/projections/plan-3year."""
    payload = {
        "parcel_info": {
            "cadastral_id": "TEST-PARCEL-3YR",
            "area_hectares": 15.0,
            "soil_type": "Loam",
            "elevation_m": 175.0,
            "slope_pct": 2.2,
            "greenhouse_available": False,
            "legal_water_quota_m3": 60000.0
        },
        "historical_harvests": [
            {
                "season_year": 2024,
                "crop_name": "Corn (Maize)",
                "yield_tons_ha": 9.2,
                "nitrogen_applied_kg_ha": 180.0
            }
        ],
        "input_prices": {
            "diesel_price_per_liter_usd": 1.20,
            "water_price_per_m3_usd": 0.09,
            "fertilizer_n_per_kg_usd": 1.40,
            "fertilizer_p_per_kg_usd": 1.65,
            "fertilizer_k_per_kg_usd": 0.98,
            "labor_hourly_rate_usd": 24.0
        },
        "nasa_data": {
            "power_agroclimatology": {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [7.5, 45.0]},
                "properties": {
                    "parameter": {
                        "T2M": {"20240701": 24.5, "20240702": 25.1},
                        "T2M_MAX": {"20240701": 31.0, "20240702": 32.5},
                        "T2M_MIN": {"20240701": 18.0, "20240702": 17.8},
                        "PRECTOTCORR": {"20240701": 0.0, "20240702": 12.0},
                        "ALLSKY_SFC_SW_DWN": {"20240701": 25.2, "20240702": 18.4},
                        "RH2M": {"20240701": 58.0, "20240702": 72.0},
                        "WS2M": {"20240701": 2.1, "20240702": 3.4}
                    }
                }
            },
            "gpm_precipitation": {
                "annual_precipitation_mm": 680.0
            },
            "smap_soil_moisture": {
                "rootzone_moisture_vol_pct": 28.5
            }
        },
        "elevation_maps": {
            "elevation_mean_m": 175.0,
            "slope_mean_pct": 2.2,
            "waterlogging_hazard_class": "Low"
        },
        "local_user_data": {
            "dated_sensor_readings": [
                {
                    "timestamp": "2025-05-15T10:00:00Z",
                    "depth_cm": 15.0,
                    "soil_nitrogen_ppm": 26.0,
                    "soil_moisture_vol_pct": 28.0,
                    "soil_compaction_psi": 205.0,
                    "soil_organic_carbon_pct": 1.90
                }
            ]
        }
    }

    response = client.post("/api/projections/plan-3year", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["cadastral_parcel_id"] == "TEST-PARCEL-3YR"
    assert data["field_area_ha"] == 15.0
    assert "strategies" in data
    assert len(data["strategies"]) == 5

    # Check that all 5 strategies are present
    strategies = data["strategies"]
    for strat in ["most_income", "best_soil_health", "least_effort", "highest_roi", "least_crop_loss_risk"]:
        assert strat in strategies
        assert len(strategies[strat]["rotation_sequence"]) == 3
        assert strategies[strat]["cumulative_metrics"]["total_net_profit_usd"] is not None

    # Check Gemini advisory structure
    advisory = data["gemini_advisory"]
    assert "executive_summary" in advisory
    assert "strategy_tradeoff_matrix" in advisory
    assert "ground_truth_field_checklist" in advisory
    assert len(advisory["ground_truth_field_checklist"]) >= 4
