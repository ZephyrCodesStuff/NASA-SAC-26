"""
Pydantic v2 schemas for the 3-Year Agricultural Planning & Ground Impact Simulation Engine.
Models the year-by-year physical transformation of the soil, financial balances,
5 distinct farmer utility strategies, and the Google Gemini AI advisory.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class AnnualGroundImpact(BaseModel):
    """Year-by-year physical, chemical, and economic impact of a crop on the parcel."""
    year_index: int = Field(..., description="Simulation year: 1, 2, or 3")
    crop_id: str
    crop_name: str
    botanical_family: str
    season_label: str = "Warm Season (Spring/Summer)"

    # Production & Economics
    projected_yield_tons_ha: float
    total_yield_tons: float
    gross_revenue_usd: float
    total_cost_usd: float
    itemized_costs_usd: Dict[str, float] = Field(
        default_factory=dict,
        description="Seed, water, fuel/machinery, fertilizer (N, P, K), labor, crop protection, botanical penalty"
    )
    net_profit_usd: float
    roi_pct: float

    # Operational Labor & Machinery Passes
    labor_hours_total: float
    machinery_passes_count: int
    fuel_consumed_liters: float

    # Macronutrient Soil Balances (NPK)
    nitrogen_balance_kg_ha: float = Field(..., description="Net soil nitrogen (+ fixed credit or - uptake extraction)")
    p2o5_balance_kg_ha: float
    k2o_balance_kg_ha: float
    biological_n_fixed_kg_ha: float = 0.0
    synthetic_n_applied_kg_ha: float = 0.0
    legume_n_credit_used_kg_ha: float = 0.0

    # Soil Physics & Organic Carbon (Henin-Dupuis)
    soc_pct_start: float
    soc_pct_end: float
    soc_change_pct: float = Field(..., description="Delta SOC % (humification of residue vs mineralization)")
    carbon_input_tons_ha: float = Field(..., description="IPCC dry matter carbon input (AG + BG roots)")

    # Soil Compaction Mechanics (ASAE S313.3 Cone Index)
    compaction_psi_start: float
    compaction_psi_end: float
    compaction_change_psi: float = Field(..., description="Traffic compaction accumulation vs taproot bio-drill relief")

    # Agro-Hydrology (FAO-56 Dual Crop Coefficient)
    water_demand_etc_mm: float
    effective_precipitation_mm: float
    irrigation_water_applied_mm: float
    irrigation_volume_m3: float
    water_stress_coefficient_ks: float = Field(1.0, description="1.0 = no water stress, <1.0 = transpiration reduction")

    # Soil Conservation & Ecological Health
    soil_erosion_tons_ha: float = Field(..., description="RUSLE predicted soil loss")
    rhizosphere_vitality_score: float = Field(..., description="Rhizosphere microbial score 0-100")
    pathogen_disease_risk_score: float = Field(..., description="Pathogen/disease risk index 0-100")
    extreme_event_vulnerability_score: float = Field(..., description="Climate shock vulnerability index 0-100")

    # Qualitative Agronomic Ground Narrative
    ground_narrative: str = Field(..., description="Mechanistic explanation of what this crop caused to the ground")


class ThreeYearCumulativeMetrics(BaseModel):
    """Aggregate 3-year performance and soil evolution metrics."""
    total_gross_revenue_usd: float
    total_cost_usd: float
    total_net_profit_usd: float
    cumulative_roi_pct: float
    total_labor_hours: float
    total_machinery_passes: int
    total_diesel_liters: float

    # Soil Regeneration Totals
    net_soc_change_pct: float
    initial_soc_pct: float
    final_soc_pct: float
    total_carbon_input_tons_ha: float
    total_biological_n_fixed_kg_ha: float
    synthetic_n_saved_usd: float
    initial_compaction_psi: float
    final_compaction_psi: float
    net_compaction_change_psi: float
    total_irrigation_volume_m3: float
    average_annual_erosion_tons_ha: float

    # Composite Strategy Indices
    cumulative_soil_health_score: float = Field(..., description="0 - 100 regenerative soil health index")
    composite_loss_risk_score: float = Field(..., description="0 - 100 overall failure risk")
    botanical_families_count: int = Field(..., description="Distinct plant families in the 3-year sequence")


class ThreeYearCultivationPlan(BaseModel):
    """Full 3-year trajectory for one farmer strategy."""
    strategy_id: str = Field(..., description="most_income, best_soil_health, least_effort, highest_roi, least_crop_loss_risk")
    strategy_title: str
    core_objective: str
    rotation_sequence: List[str]
    year_1: AnnualGroundImpact
    year_2: AnnualGroundImpact
    year_3: AnnualGroundImpact
    cumulative_metrics: ThreeYearCumulativeMetrics
    strategic_summary: str
    risk_mitigation_actions: List[str]


class GeminiAdvisoryReport(BaseModel):
    """Structured AI agronomic consultation generated via Google Gemini 3.8 Flash (with deterministic fallback)."""
    model_used: str = Field("google-genai/gemini-3.8-flash", description="Model identifier")
    executive_summary: str
    parcel_climate_context: str
    strategy_tradeoff_matrix: str
    year_by_year_soil_transformation: str
    extreme_event_resilience_playbook: str
    farmer_decision_guide: str
    ground_truth_field_checklist: List[str]


class ThreeYearPlanResponse(BaseModel):
    """Top-level API response containing all 5 strategy trajectories and Gemini AI advisory."""
    cadastral_parcel_id: str
    field_area_ha: float
    resolved_soil_type: str
    simulation_timestamp: str
    climate_baseline: Dict[str, Any]
    strategies: Dict[str, ThreeYearCultivationPlan] = Field(
        ...,
        description="Keys: most_income, best_soil_health, least_effort, highest_roi, least_crop_loss_risk"
    )
    gemini_advisory: GeminiAdvisoryReport
