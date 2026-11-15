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
    phosphorus_balance_kg_ha: Optional[float] = Field(default=None, description="Elemental phosphorus balance (kg P/ha)")
    potassium_balance_kg_ha: Optional[float] = Field(default=None, description="Elemental potassium balance (kg K/ha)")
    biological_n_fixed_kg_ha: float = 0.0
    synthetic_n_applied_kg_ha: float = 0.0
    legume_n_credit_used_kg_ha: float = 0.0
    soil_mineralized_n_kg_ha: float = 0.0
    nitrogen_surplus_kg_ha: float = 0.0
    nitrogen_leaching_kg_ha: float = 0.0
    direct_n2o_n_kg_ha: float = 0.0

    # Soil Physics & Organic Carbon (Henin-Dupuis)
    soc_pct_start: float
    soc_pct_end: float
    soc_change_pct: float = Field(..., description="Delta SOC % (humification of residue vs mineralization)")
    carbon_input_tons_ha: float = Field(..., description="IPCC dry matter carbon input (AG + BG roots)")

    # Soil Compaction Mechanics (ASAE S313.3 Cone Index heuristic)
    compaction_psi_start: float
    compaction_psi_end: float
    compaction_change_psi: float = Field(..., description="Traffic compaction accumulation vs taproot bio-drill relief")
    compaction_is_heuristic: bool = Field(default=True, description="True unless calibrated with field penetrometer/bulk-density")

    # Agro-Hydrology (FAO-56 Single Crop Coefficient + Monthly Bucket)
    water_demand_etc_mm: float
    actual_et_eta_mm: Optional[float] = Field(default=None, description="Actual seasonal crop evapotranspiration ETa (mm)")
    relative_et_deficit: float = Field(default=0.0, description="Seasonal relative ET deficit 1 - ETa/ETc")
    fao33_outside_calibrated_range: bool = Field(default=False, description="True if 1 - ETa/ETc > 0.50 (FAO-33 empirical bound)")
    effective_precipitation_mm: float
    irrigation_water_applied_mm: float
    irrigation_volume_m3: float
    irrigation_method: Optional[str] = Field(default=None, description="surface, sprinkler, or drip")
    irrigation_efficiency_ea: Optional[float] = Field(default=None, description="Application efficiency e_a (0.60, 0.75, or 0.90)")
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
    total_nitrogen_surplus_kg_ha: float = 0.0
    total_nitrogen_leaching_kg_ha: float = 0.0
    total_direct_n2o_n_kg_ha: float = 0.0

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


class StrategyPlainLanguageBreakdown(BaseModel):
    """Farmer-friendly translation of a single 3-year strategy into plain everyday language."""
    strategy_id: str = Field(..., description="Strategy identifier: most_income, best_soil_health, least_effort, highest_roi, least_crop_loss_risk")
    strategy_name: str = Field(..., description="Display title of the strategy")
    rotation_sequence: List[str] = Field(..., description="3-year crop sequence")
    benefits_plain_words: str = Field(..., description="What the farmer gains in everyday terms (cash profit, free nitrogen, loose soil, low stress)")
    drawbacks_plain_words: str = Field(..., description="The downsides or sacrifices the farmer makes in plain words (higher upfront cost, lower cash, etc.)")
    risks_taken: str = Field(..., description="Specific risks the farmer takes on (weather exposure, market price drops, machinery breakdown, compaction)")
    expected_rewards: str = Field(..., description="Realistic financial, yield, or soil equity rewards if the plan succeeds")
    three_year_action_overview: str = Field(..., description="Plain-English step-by-step summary of what the farmer actually has to do across Year 1, Year 2, and Year 3")


class GeminiAdvisoryReport(BaseModel):
    """Structured AI agronomic consultation generated via Google Gemini, translated into clear farmer-friendly guidance."""
    model_used: str = Field("google-genai/gemini-3.1-flash-lite", description="Model identifier")
    farmer_plain_language_summary: str = Field(..., description="Executive briefing translated into plain, relatable farmer language")
    strategies_breakdown: List[StrategyPlainLanguageBreakdown] = Field(
        default_factory=list,
        description="Plain-English breakdown for each of the 5 strategies: benefits, drawbacks, risks, rewards, and 3-year tasks"
    )
    three_year_operational_overview: str = Field(..., description="Calendar roadmap of what the farmer needs to do each year to succeed across the 3-year horizon")
    risk_vs_reward_comparison: str = Field(..., description="Side-by-side plain-English comparison of the risks taken vs benefits gained across options")
    farmer_decision_guide: str = Field(..., description="Practical decision guide helping the farmer pick the right plan based on cash, labor, and risk appetite")
    ground_truth_field_checklist: List[str] = Field(..., description="Actionable physical checks the farmer should carry out on their parcel")

    # Core reference fields
    executive_summary: str = Field(..., description="High-level summary of the 3-year simulation outcomes")
    parcel_climate_context: str = Field(..., description="Plain-English translation of NASA satellite observations for this specific field")
    strategy_tradeoff_matrix: str = Field(..., description="Analysis of economic margin vs soil regeneration vs labor expenditure")
    year_by_year_soil_transformation: str = Field(..., description="Plain explanation of how soil organic matter, compaction, and nitrogen change over 3 years")
    extreme_event_resilience_playbook: str = Field(..., description="Practical farmer actions for drought, heatwaves, heavy downpours, and frost")


class ThreeYearPlanResponse(BaseModel):
    """Top-level API response containing all 5 strategy trajectories, Gemini AI advisory, and data provenance."""
    cadastral_parcel_id: str
    field_area_ha: float
    resolved_soil_type: str
    simulation_timestamp: str
    climate_baseline: Dict[str, Any]
    data_layering_provenance: Dict[str, str] = Field(
        default_factory=dict,
        description="Transparent tracking of how local user ground truth calibrated and layered on top of NASA satellite data"
    )
    strategies: Dict[str, ThreeYearCultivationPlan] = Field(
        ...,
        description="Keys: most_income, best_soil_health, least_effort, highest_roi, least_crop_loss_risk"
    )
    calibration_and_assumptions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Uncalibrated empirical assumptions, soil/water provenance warnings, and model limits"
    )
    parcel_is_constrained: bool = Field(
        default=False,
        description="True when strict biophysical filters admit fewer than 3 distinct crops without lowering biophysical walls"
    )
    gemini_advisory: GeminiAdvisoryReport
