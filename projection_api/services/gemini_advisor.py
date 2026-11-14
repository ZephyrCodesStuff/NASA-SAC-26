"""
Google Gemini AI Advisory Engine with Deterministic Offline Fallback.
Uses the official google-genai SDK (gemini-3.8-flash) to translate multi-objective
simulation metrics and NASA Earth observations into actionable agronomic guidance.
"""

import os
import json
import logging
from typing import Dict, Any, List

from projection_api.models.simulation_models import (
    ThreeYearCultivationPlan, GeminiAdvisoryReport
)

logger = logging.getLogger(__name__)

# Official google-genai SDK import
try:
    from google import genai
    from google.genai import types
    GENAI_SDK_AVAILABLE = True
except ImportError:
    GENAI_SDK_AVAILABLE = False


class GeminiAdvisorEngine:
    """Grounded AI Agronomic Advisor with guaranteed offline fallback."""

    def __init__(self, model_name: str = "gemini-3.8-flash"):
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self.api_key = os.getenv("GEMINI_API_KEY")

    def generate_advisory_report(
        self,
        parcel_info: Dict[str, Any],
        climate_baseline: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> GeminiAdvisoryReport:
        """
        Synthesizes simulated 3-year outcomes into structured agronomic advisory.
        Uses live Gemini 3.8 Flash if API key is present; otherwise gracefully
        executes the deterministic agronomic expert engine.
        """
        # If live API key is present and SDK is available, try live Gemini call
        if self.api_key and GENAI_SDK_AVAILABLE:
            try:
                client = genai.Client(api_key=self.api_key)
                prompt = self._build_grounded_prompt(parcel_info, climate_baseline, strategies)

                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,  # Low temperature for precise agronomic consistency
                        response_mime_type="application/json",
                        response_schema=GeminiAdvisoryReport,
                    )
                )

                if response.text:
                    parsed_json = json.loads(response.text)
                    report = GeminiAdvisoryReport(**parsed_json)
                    report.model_used = f"google-genai/{self.model_name}"
                    return report

            except Exception as e:
                logger.warning(f"Live Gemini API call failed: {e}. Falling back to deterministic engine.")

        # Deterministic Offline Fallback
        return self._generate_deterministic_fallback(parcel_info, climate_baseline, strategies)

    def _build_grounded_prompt(
        self,
        parcel: Dict[str, Any],
        climate: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> str:
        """Constructs quantitative grounded prompt injecting all simulation metrics."""
        summary_lines = []
        for strat_id, plan in strategies.items():
            m = plan.cumulative_metrics
            summary_lines.append(
                f"- Strategy '{plan.strategy_title}' ({' -> '.join(plan.rotation_sequence)}):\n"
                f"  Net Profit: ${m.total_net_profit_usd:,.2f} | Total Cost: ${m.total_cost_usd:,.2f} | "
                f"ROI: {m.cumulative_roi_pct:.1f}% | Labor: {m.total_labor_hours:.1f} hrs | "
                f"Soil Health: {m.cumulative_soil_health_score}/100 | Delta SOC: {m.net_soc_change_pct:+.2f}% | "
                f"N Fixed: {m.total_biological_n_fixed_kg_ha:.1f} kg/ha | Final Compaction: {m.final_compaction_psi:.1f} PSI | "
                f"Risk Score: {m.composite_loss_risk_score}/100"
            )

        strategies_block = "\n".join(summary_lines)

        return f"""You are a Senior Agronomist and Soil Scientist consulting for a commercial farm.
A deterministic biophysical simulation engine has modeled 5 distinct 3-year crop rotation strategies using official NASA Earth observations (POWER agroclimatology, GPM IMERG precipitation, SMAP rootzone moisture), in-situ soil sensors, and DEM elevation/slope data.

PARCEL & CLIMATE CONTEXT:
- Parcel Cadastre: {parcel.get('cadastral_id', 'Field-01')} ({parcel.get('area_hectares', 1.0)} ha)
- Soil Type: {parcel.get('soil_type', 'Loam')} | Elevation: {parcel.get('elevation_m', 150)} m | Slope: {parcel.get('slope_pct', 2.0)}%
- NASA POWER ET0: {climate.get('annual_et0_mm', 1080)} mm/year
- NASA GPM Annual Rainfall: {climate.get('annual_precip_mm', 640)} mm/year
- NASA SMAP Rootzone Soil Moisture: {climate.get('smap_rootzone_moisture', 0.26)} m³/m³
- Topographic Low Spot Hazard: {climate.get('low_spot_hazard', False)}

SIMULATED 3-YEAR STRATEGY METRICS:
{strategies_block}

TASK:
Generate a structured, rigorous agronomic consultation report adhering strictly to the JSON schema:
1. 'executive_summary': High-level strategic briefing comparing the trade-offs of all 5 plans.
2. 'parcel_climate_context': Grounded environmental appraisal citing NASA observations and field topography.
3. 'strategy_tradeoff_matrix': Comprehensive analysis of economic margin vs soil regeneration vs labor expenditure.
4. 'year_by_year_soil_transformation': Detailed mechanistic narrative explaining how Soil Organic Carbon, Biological Nitrogen Fixation, and penetrometer compaction evolve across Year 1, Year 2, and Year 3.
5. 'extreme_event_resilience_playbook': Concrete adaptation actions for drought, flood/waterlogging, frost, and extreme heat.
6. 'farmer_decision_guide': Clear criteria guiding which plan the farmer should select based on capital, machinery, and labor availability.
7. 'ground_truth_field_checklist': 5 to 7 concrete physical verification steps (soil tests, penetrometer checks, ditch cleaning, seed inoculation).
"""

    def _generate_deterministic_fallback(
        self,
        parcel: Dict[str, Any],
        climate: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> GeminiAdvisoryReport:
        """
        High-fidelity rule-based agronomic expert system.
        Guarantees 100% complete and valid advice even without internet or API keys.
        """
        p_inc = strategies["most_income"]
        p_soil = strategies["best_soil_health"]
        p_lab = strategies["least_effort"]
        p_roi = strategies["highest_roi"]
        p_risk = strategies["least_crop_loss_risk"]

        area = parcel.get("area_hectares", 1.0)
        soil_type = parcel.get("soil_type", "Loam")
        cadastre = parcel.get("cadastral_id", "Field-01")

        exec_summary = (
            f"Comprehensive 3-year agricultural projection completed for parcel '{cadastre}' ({area} ha, soil texture: {soil_type}). "
            f"Five mathematically distinct cultivation strategies have been generated to accommodate contrasting farm management priorities. "
            f"The 'Most Income' strategy ({' -> '.join(p_inc.rotation_sequence)}) achieves peak cumulative net profit of "
            f"${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} over the 3-year horizon. "
            f"The 'Best Soil Health' strategy ({' -> '.join(p_soil.rotation_sequence)}) prioritizes biological regeneration, "
            f"accumulating {p_soil.cumulative_metrics.net_soc_change_pct:+.2f}% Soil Organic Carbon and fixing "
            f"{p_soil.cumulative_metrics.total_biological_n_fixed_kg_ha:.1f} kg N/ha biologically. "
            f"Operators seeking minimal operational burden can deploy 'Least Effort' ({' -> '.join(p_lab.rotation_sequence)}), "
            f"which limits total labor to {p_lab.cumulative_metrics.total_labor_hours:.1f} hours across 3 seasons."
        )

        climate_context = (
            f"NASA POWER agroclimatology indicates an annual reference evaporative demand (ET0) of {climate.get('annual_et0_mm', 1080):.0f} mm, "
            f"offset by {climate.get('annual_precip_mm', 640):.0f} mm of annual precipitation recorded via NASA GPM IMERG. "
            f"NASA SMAP L4 observations confirm baseline root-zone soil moisture at {climate.get('smap_rootzone_moisture', 0.26) * 100:.1f}%. "
            f"With a terrain slope of {parcel.get('slope_pct', 2.0):.1f}% and an elevation of {parcel.get('elevation_m', 150):.0f} m, "
            f"{'caution is warranted regarding depression waterlogging' if climate.get('low_spot_hazard') else 'surface drainage is stable and well-aerated'}."
        )

        tradeoff_matrix = (
            f"1. Income vs. Capital & Labor: The Most Income plan generates ${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} "
            f"but requires ${p_inc.cumulative_metrics.total_cost_usd:,.2f} in operational inputs and {p_inc.cumulative_metrics.total_labor_hours:.1f} labor hours. "
            f"2. Capital Efficiency: The Highest ROI plan ({' -> '.join(p_roi.rotation_sequence)}) optimizes return per dollar invested, "
            f"delivering an aggregate {p_roi.cumulative_metrics.cumulative_roi_pct:.1f}% ROI with lower capital exposure (${p_roi.cumulative_metrics.total_cost_usd:,.2f}). "
            f"3. Ecological Equity: The Best Soil Health plan fixes ${p_soil.cumulative_metrics.synthetic_n_saved_usd:,.2f} worth of synthetic nitrogen "
            f"and reduces subsoil compaction, creating long-term structural productivity that lowers future fertilizer costs."
        )

        soil_narrative = (
            f"Year 1 establishes baseline rhizosphere restructuring: crops with deep rooting systems decompact the subsoil profile. "
            f"Year 2 leverages biological carryover: legumes in the rotation leave up to 50-120 kg/ha of mineralizable organic nitrogen, "
            f"reducing synthetic fertilizer requirements for following cereal crops. "
            f"Year 3 consolidates soil organic carbon via humification of crop stover and root turnover, with ending penetration resistance "
            f"stabilized at {p_soil.cumulative_metrics.final_compaction_psi:.1f} PSI in the soil health trajectory."
        )

        resilience_playbook = (
            "1. Drought Mitigation: Under rainfed deficits, prioritize drought-resilient crops (Grain Sorghum, Sunflowers) "
            "that utilize osmotic adjustment and deep taproots to scavenge subsoil moisture. "
            "2. Flood & Waterlogging Prevention: Clear field perimeter drainage furrows; avoid planting pulse legumes in low-lying depressions. "
            "3. Frost Management: For cool-season crops (Winter Wheat, Canola, Spinach), monitor canopy inversion temperatures during floral bud emergence. "
            "4. Heatwave Stress: Ensure optimal soil moisture prior to flowering to sustain transpirational cooling."
        )

        decision_guide = (
            f"- Choose 'Most Income' if operating capital is available (${p_inc.cumulative_metrics.total_cost_usd:,.0f}) and market contracts are secured.\n"
            f"- Choose 'Best Soil Health' if soil compaction exceeds 250 PSI or organic carbon is degraded (<2.0%), as this restores field equity.\n"
            f"- Choose 'Least Effort' if machinery or labor availability is constrained ({p_lab.cumulative_metrics.total_labor_hours:.0f} total hours).\n"
            f"- Choose 'Highest ROI' if capital is limited and maximizing percentage returns per invested dollar is paramount.\n"
            f"- Choose 'Least Risk' if farming under unpredictable seasonal weather shocks or uninsurable climate conditions."
        )

        field_checklist = [
            f"Conduct calibrated pre-season soil core test to verify topsoil nitrate and pH ({soil_type} baseline).",
            f"Deploy cone penetrometer across field grid at 15-30 cm depth to map hardpan zones prior to Year 1 planting.",
            "Verify Rhizobium leguminosarum / Bradyrhizobium inoculant viability for all legume seed batches.",
            "Inspect field drainage ditches and culverts to prevent localized ponding during peak GPM storm events.",
            "Calibrate sprayer nozzles and drill seeding meters to ensure exact per-hectare application rates.",
            "Monitor NASA POWER daily GDD and soil moisture sensor drawdown to schedule timely irrigation applications."
        ]

        return GeminiAdvisoryReport(
            model_used="deterministic-agronomic-engine",
            executive_summary=exec_summary,
            parcel_climate_context=climate_context,
            strategy_tradeoff_matrix=tradeoff_matrix,
            year_by_year_soil_transformation=soil_narrative,
            extreme_event_resilience_playbook=resilience_playbook,
            farmer_decision_guide=decision_guide,
            ground_truth_field_checklist=field_checklist
        )
