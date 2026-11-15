"""
Google Gemini AI Advisory Engine with Deterministic Offline Fallback.
Uses the official google-genai SDK (gemini-3.8-flash) to translate multi-objective
simulation metrics and NASA Earth observations into actionable agronomic guidance.
"""

import os
import json
import time
import hashlib
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

from projection_api.cache import cache_get, cache_set
from projection_api.models.simulation_models import (
    ThreeYearCultivationPlan, GeminiAdvisoryReport, StrategyPlainLanguageBreakdown
)

logger = logging.getLogger(__name__)

# Official google-genai SDK import
try:
    from google import genai
    from google.genai import types
    GENAI_SDK_AVAILABLE = True
except ImportError:
    GENAI_SDK_AVAILABLE = False


def _advisory_cache_key(parcel: Dict[str, Any], climate: Dict[str, Any], strategies: Dict[str, ThreeYearCultivationPlan]) -> str:
    blob = json.dumps(
        [parcel, climate, {k: v.model_dump() for k, v in strategies.items()}],
        sort_keys=True, default=str,
    )
    return "gemini:" + hashlib.sha256(blob.encode()).hexdigest()


class GeminiAdvisorEngine:
    """Grounded AI Agronomic Advisor with guaranteed offline fallback."""

    def __init__(self, model_name: str = "gemini-3.1-flash-lite"):
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        # Total time allowed for Gemini (all candidate models) before using the offline fallback. Keeps the
        # projection well inside web-api's 90 s wait and Cloudflare's 100 s limit when Gemini is slow or overloaded.
        self.timeout_s = float(os.getenv("GEMINI_TIMEOUT_S", "45"))

    def generate_advisory_report(
        self,
        parcel_info: Dict[str, Any],
        climate_baseline: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> GeminiAdvisoryReport:
        """
        Synthesizes simulated 3-year outcomes into structured agronomic advisory.
        Uses live Gemini AI (gemini-3.1-flash-lite / gemini-3.8-flash) if API key is present;
        otherwise gracefully executes the deterministic agronomic expert engine.
        """
        cache_key = _advisory_cache_key(parcel_info, climate_baseline, strategies)
        cached = cache_get(cache_key)
        live = bool(self.api_key and GENAI_SDK_AVAILABLE)
        # With a key, a cached offline-fallback report (from before the key was set, or from a failed call)
        # is not reused: try Gemini again.
        if cached is not None and live and not str(cached.get("model_used") or "").startswith("google-genai/"):
            cached = None
        if cached is not None:
            try:
                return GeminiAdvisoryReport(**cached)
            except Exception:  # noqa: BLE001 — a corrupt cache entry falls through to recompute
                pass

        # If live API key is present and SDK is available, try live Gemini call
        if live:
            candidate_models = [self.model_name]
            if "gemini-3.1-flash-lite" not in candidate_models:
                candidate_models.append("gemini-3.1-flash-lite")
            if "gemini-3.8-flash" not in candidate_models:
                candidate_models.append("gemini-3.8-flash")

            prompt = self._build_grounded_prompt(parcel_info, climate_baseline, strategies)
            deadline = time.monotonic() + self.timeout_s

            for target_model in candidate_models:
                remaining = deadline - time.monotonic()
                if remaining < 10:  # Gemini rejects request deadlines under 10 s
                    logger.warning("Gemini time budget used up; using the offline fallback")
                    break
                try:
                    client = genai.Client(
                        api_key=self.api_key,
                        http_options=types.HttpOptions(timeout=int(remaining * 1000)),
                    )
                    response = client.models.generate_content(
                        model=target_model,
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
                        report.model_used = f"google-genai/{target_model}"
                        cache_set(cache_key, report.model_dump())
                        return report

                except Exception as e:
                    logger.warning(f"Live Gemini API call ({target_model}) failed: {e}. Trying next model...")

        # Deterministic Offline Fallback
        report = self._generate_deterministic_fallback(parcel_info, climate_baseline, strategies)
        # Gemini configured but failed: keep the fallback briefly so the next request retries soon
        if live:
            cache_set(cache_key, report.model_dump(), ttl=600)
        else:
            cache_set(cache_key, report.model_dump())
        return report

    def _build_grounded_prompt(
        self,
        parcel: Dict[str, Any],
        climate: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> str:
        """Constructs quantitative grounded prompt injecting all simulation metrics with farmer-first framing."""
        summary_lines = []
        for strat_id, plan in strategies.items():
            m = plan.cumulative_metrics
            summary_lines.append(
                f"- Strategy '{plan.strategy_title}' (Key: {strat_id}) | Rotation: {' -> '.join(plan.rotation_sequence)}:\n"
                f"  Net Profit: ${m.total_net_profit_usd:,.2f} | Total Cost: ${m.total_cost_usd:,.2f} | "
                f"ROI: {m.cumulative_roi_pct:.1f}% | Labor: {m.total_labor_hours:.1f} hrs | Passes: {m.total_machinery_passes} | "
                f"Soil Health Score: {m.cumulative_soil_health_score}/100 | Delta Organic Carbon: {m.net_soc_change_pct:+.2f}% | "
                f"Free Bio-Nitrogen Fixed: {m.total_biological_n_fixed_kg_ha:.1f} kg/ha (saving ${m.synthetic_n_saved_usd:,.2f}) | "
                f"Final Hardpan Compaction: {m.final_compaction_psi:.1f} PSI (Start: {m.initial_compaction_psi:.1f} PSI) | "
                f"Crop Loss Risk Score: {m.composite_loss_risk_score}/100"
            )

        strategies_block = "\n".join(summary_lines)

        prov_dict = parcel.get("data_layering_provenance", {})
        prov_lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in prov_dict.items()]
        prov_block = "\n".join(prov_lines) if prov_lines else "NASA Satellite Baseline (no local user overrides provided)"

        return f"""You are a trusted Senior Farm Advisor and Agronomist speaking directly to the farmer.
A biophysical simulation engine has analyzed this specific field using NASA Earth observations (POWER atmospheric data, GPM precipitation, SMAP root-zone soil moisture, SoilGrids, SRTM DEM), combined with the farmer's own on-farm ground truth data layered on top. It generated 5 mathematically distinct 3-year crop rotation plans.

YOUR CORE MISSION:
Translate the complex scientific, agronomic, and financial data into clear, plain, everyday words that a practical farmer can understand.
Help the farmer clearly grasp:
1. What are the benefits and drawbacks of each plan in plain words?
2. What risks are they taking on (money, weather, pests, soil hardpan) vs what benefits/rewards they might get?
3. What will they actually need to do across the 3-year period (Year 1, Year 2, and Year 3) as a clear operational roadmap?
4. How should they choose the best plan based on their cash flow, machinery, labor, and tolerance for risk?
5. Acknowledge how the farmer's own data layered on top of NASA satellite data to give personalized accuracy for their ground.

DATA LAYERING & GROUND TRUTH (USER DATA LAYERED ON TOP OF NASA SATELLITE BASELINE):
{prov_block}

FIELD & WEATHER OVERVIEW (TRANSLATE IN PLAIN RELATABLE TERMS):
- Field Cadastre: {parcel.get('cadastral_id', 'Field-01')} ({parcel.get('area_hectares', 1.0)} ha)
- Soil Texture: {parcel.get('soil_type', 'Loam')} | Elevation: {parcel.get('elevation_m', 150)} m | Slope: {parcel.get('slope_pct', 2.0)}%
- NASA Evaporative Sun/Air Demand (ET0): {climate.get('annual_et0_mm', 1080)} mm/year
- NASA Rainfall Measured (GPM): {climate.get('annual_precip_mm', 640)} mm/year
- NASA SMAP Rootzone Soil Moisture: {climate.get('smap_rootzone_moisture', 0.26)} m³/m³
- Low-Spot Water Ponding Hazard: {climate.get('low_spot_hazard', False)}

SIMULATED 3-YEAR STRATEGIES DATA:
{strategies_block}

TRANSLATION & FORMATTING GUIDELINES:
- Translate technical terms into real-world farm impacts:
  * Do NOT just quote 'ET0 1200mm' -> explain 'evaporative water demand: how quickly sun, wind, and heat draw moisture out of your crops and topsoil'.
  * Do NOT just quote 'Compaction 338 PSI' -> explain 'wheel-traffic hardpan: ground packed tight like concrete, making it hard for roots to dig down for subsoil moisture'.
  * Do NOT just quote 'SOC delta' -> explain 'soil organic sponge: the natural humus that holds onto fertilizer and rainwater'.
  * Do NOT just quote 'Rhizobial BNF' -> explain 'free natural fertilizer: legumes pulling nitrogen out of thin air to feed following crops'.
- Ensure every single one of the 5 strategies in `strategies_breakdown` has:
  * `strategy_id`: exactly matching one of ['most_income', 'best_soil_health', 'least_effort', 'highest_roi', 'least_crop_loss_risk']
  * `strategy_name`: display name
  * `rotation_sequence`: list of 3 crop names
  * `benefits_plain_words`: concrete everyday benefits (cash in pocket, loose ground, low fuel).
  * `drawbacks_plain_words`: real downsides, sacrifices, or extra requirements (high capital, lower immediate cash, weed pressure).
  * `risks_taken`: specific operational, financial, or weather risks the farmer accepts.
  * `expected_rewards`: realistic financial payout, soil building, or stress reduction.
  * `three_year_action_overview`: clear, practical steps for Year 1, Year 2, and Year 3.
- In `three_year_operational_overview`, summarize the year-by-year farm workload and seasonal transitions.
- In `risk_vs_reward_comparison`, contrast the high-investment/high-return options against the safe/soil-rebuilding options.
- In `farmer_decision_guide`, provide simple diagnostic rules for selecting the best plan.
"""

    def _generate_deterministic_fallback(
        self,
        parcel: Dict[str, Any],
        climate: Dict[str, Any],
        strategies: Dict[str, ThreeYearCultivationPlan]
    ) -> GeminiAdvisoryReport:
        """
        High-fidelity rule-based agronomic expert system.
        Guarantees 100% complete, plain-language advice even without internet or API keys.
        """
        p_inc = strategies["most_income"]
        p_soil = strategies["best_soil_health"]
        p_lab = strategies["least_effort"]
        p_roi = strategies["highest_roi"]
        p_risk = strategies["least_crop_loss_risk"]

        area = parcel.get("area_hectares", 1.0)
        soil_type = parcel.get("soil_type", "Loam")
        cadastre = parcel.get("cadastral_id", "Field-01")

        farmer_summary = (
            f"Here is your 3-year farming roadmap for field '{cadastre}' ({area} ha, {soil_type} soil). "
            f"We ran full physical and financial simulations across 5 different pathways to match your farming priorities. "
            f"If your priority is purely putting the most cash into your bank account, the 'Most Income' plan "
            f"({' -> '.join(p_inc.rotation_sequence)}) delivers ${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} in clear net profit. "
            f"If your ground is tired and you want to restore soil vitality, the 'Best Soil Health' plan "
            f"({' -> '.join(p_soil.rotation_sequence)}) fixes {p_soil.cumulative_metrics.total_biological_n_fixed_kg_ha:.0f} kg of free nitrogen "
            f"out of the air and softens hardpan compaction. "
            f"If you farm alone or are short on labor, 'Least Effort' keeps total labor down to just "
            f"{p_lab.cumulative_metrics.total_labor_hours:.0f} hours over all 3 years while still generating solid returns."
        )

        breakdowns = [
            StrategyPlainLanguageBreakdown(
                strategy_id="most_income",
                strategy_name="Most Income Plan",
                rotation_sequence=p_inc.rotation_sequence,
                benefits_plain_words=(
                    f"Puts the absolute highest total cash in your pocket: ${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} "
                    f"in cumulative net profit across 3 years with strong annual cash flow."
                ),
                drawbacks_plain_words=(
                    f"Requires the largest upfront operating budget (${p_inc.cumulative_metrics.total_cost_usd:,.2f}) "
                    f"and {p_inc.cumulative_metrics.total_labor_hours:.0f} hours of fieldwork, meaning higher capital exposure if crop prices drop."
                ),
                risks_taken=(
                    "High upfront financial risk. If a severe summer drought strikes or grain prices dip, "
                    "you have significant capital tied up in seed, fertilizer, and irrigation water."
                ),
                expected_rewards=(
                    f"Peak cumulative profit of ${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} and a {p_inc.cumulative_metrics.cumulative_roi_pct:.1f}% ROI."
                ),
                three_year_action_overview=(
                    f"Year 1: Plant {p_inc.rotation_sequence[0]}, fertilize for high yield, and manage moisture. "
                    f"Year 2: Switch to {p_inc.rotation_sequence[1]} to tap subsoil water and generate premium forage income. "
                    f"Year 3: Return to {p_inc.rotation_sequence[2]} utilizing residual soil moisture for a strong cash-crop harvest."
                )
            ),
            StrategyPlainLanguageBreakdown(
                strategy_id="best_soil_health",
                strategy_name="Best Soil Health Plan",
                rotation_sequence=p_soil.rotation_sequence,
                benefits_plain_words=(
                    f"Acts as a total soil rehabilitation cure. Fixes {p_soil.cumulative_metrics.total_biological_n_fixed_kg_ha:.0f} kg/ha "
                    f"of free biological nitrogen from the atmosphere (saving ${p_soil.cumulative_metrics.synthetic_n_saved_usd:,.2f} in fertilizer) "
                    f"and uses deep taproots to break up hardpan compaction down to {p_soil.cumulative_metrics.final_compaction_psi:.1f} PSI."
                ),
                drawbacks_plain_words=(
                    "Lower immediate cash profit compared to intensive grain cropping; requires patience as soil equity accumulates."
                ),
                risks_taken=(
                    "Opportunity cost risk: You sacrifice immediate maximum grain cash sales today in exchange for a permanently better field tomorrow."
                ),
                expected_rewards=(
                    "A field that holds 20-30% more water during future droughts, requires much less fertilizer, and has rich spongy topsoil."
                ),
                three_year_action_overview=(
                    f"Year 1: Establish {p_soil.rotation_sequence[0]} with winter cover benefits. "
                    f"Year 2: Plant {p_soil.rotation_sequence[1]} with active rhizobia inoculant to start deep bio-drilling into the hardpan. "
                    f"Year 3: Maintain {p_soil.rotation_sequence[2]} to maximize free nitrogen accumulation and lock in soil organic matter."
                )
            ),
            StrategyPlainLanguageBreakdown(
                strategy_id="least_effort",
                strategy_name="Least Effort / Low Labor Plan",
                rotation_sequence=p_lab.rotation_sequence,
                benefits_plain_words=(
                    f"Lowest workload and minimal tractor wear: only {p_lab.cumulative_metrics.total_machinery_passes} total tractor passes "
                    f"and {p_lab.cumulative_metrics.total_labor_hours:.0f} labor hours across all 3 years. Perfect if you have limited equipment or time."
                ),
                drawbacks_plain_words=(
                    "Less root diversity in the ground, meaning the subsoil does not get bio-drilled and compaction gradually creeps up."
                ),
                risks_taken=(
                    "Subsoil hardpan accumulation. Without deep taproots, continuous tractor passes pack down the subsoil layer over time."
                ),
                expected_rewards=(
                    f"High lifestyle convenience and low stress, combined with an outstanding {p_lab.cumulative_metrics.cumulative_roi_pct:.1f}% ROI "
                    f"and ${p_lab.cumulative_metrics.total_net_profit_usd:,.2f} net profit."
                ),
                three_year_action_overview=(
                    f"Year 1: Direct-seed {p_lab.rotation_sequence[0]} with minimal passes; harvest efficiently. "
                    f"Year 2: Low-till seeding of {p_lab.rotation_sequence[1]} capitalizing on low input needs. "
                    f"Year 3: Repeat {p_lab.rotation_sequence[2]} with clean stubble management."
                )
            ),
            StrategyPlainLanguageBreakdown(
                strategy_id="highest_roi",
                strategy_name="Highest Capital ROI Plan",
                rotation_sequence=p_roi.rotation_sequence,
                benefits_plain_words=(
                    f"Gives you the highest return for every single dollar spent: an impressive {p_roi.cumulative_metrics.cumulative_roi_pct:.1f}% ROI. "
                    f"Requires less working capital (${p_roi.cumulative_metrics.total_cost_usd:,.2f}) while generating ${p_roi.cumulative_metrics.total_net_profit_usd:,.2f} profit."
                ),
                drawbacks_plain_words=(
                    "Requires precise timing on weed control and harvesting to capture the high percentage margins without yield slippage."
                ),
                risks_taken=(
                    "Moderate agronomic risk: relies on legume nitrogen carryover to save on fertilizer bills in Year 3."
                ),
                expected_rewards=(
                    "Maximum capital efficiency: your operating dollars work twice as hard as in standard farming programs."
                ),
                three_year_action_overview=(
                    f"Year 1: Plant {p_roi.rotation_sequence[0]} with targeted fertilizer. "
                    f"Year 2: Rotate to {p_roi.rotation_sequence[1]} to break pest cycles and leave biological or scavenged nitrogen in the soil. "
                    f"Year 3: Plant {p_roi.rotation_sequence[2]} tapering synthetic nitrogen by the Year 2 residual N credit, saving ${p_roi.cumulative_metrics.synthetic_n_saved_usd:,.0f}."
                )
            ),
            StrategyPlainLanguageBreakdown(
                strategy_id="least_crop_loss_risk",
                strategy_name="Least Crop Loss Risk Plan",
                rotation_sequence=p_risk.rotation_sequence,
                benefits_plain_words=(
                    f"The safest, most resilient plan against Mother Nature. Lowest loss risk score ({p_risk.cumulative_metrics.composite_loss_risk_score}/100). "
                    f"Deep-rooting, drought-tolerant crops ensure you still get a harvest even in extreme heat or erratic rainfall."
                ),
                drawbacks_plain_words=(
                    "You trade away the highest possible boom-year windfall in exchange for guaranteed stability and disaster-proofing."
                ),
                risks_taken=(
                    "Minimal risk across the board. You are insulated against severe rainfall deficits and sudden market crashes."
                ),
                expected_rewards=(
                    f"Peace of mind, steady ${p_risk.cumulative_metrics.total_net_profit_usd:,.2f} profit, and an exceptionally durable field."
                ),
                three_year_action_overview=(
                    f"Year 1: Establish deep-rooting {p_risk.rotation_sequence[0]} to open subsoil pores. "
                    f"Year 2: Follow with resilient {p_risk.rotation_sequence[1]} to maintain canopy protection. "
                    f"Year 3: Plant {p_risk.rotation_sequence[2]} ensuring complete field cover and root-zone stability."
                )
            )
        ]

        op_overview = (
            "3-YEAR OPERATIONAL ROADMAP:\n"
            "- Year 1 (Foundation & Setup): Test topsoil nutrients, adjust tractor tire pressure to 12-15 PSI to avoid hardpan packing, "
            "and calibrate seeding drills. Plant the primary crop on time to establish early canopy cover.\n"
            "- Year 2 (Biological Transition): Rotate crop families to break weed and pest cycles. If planting legumes, verify rhizobia seed inoculant. "
            "Scout for moisture drawdown during midsummer heat.\n"
            "- Year 3 (Harvest & Handover): Cut synthetic fertilizer rates by the full legume credit left in the soil. Conduct a simple spade test "
            "at harvest to inspect earthworm channels and root depth before deciding the next cycle."
        )

        risk_reward = (
            "RISK VS. REWARD COMPARISON:\n"
            f"- High-Reward / High-Investment ('Most Income'): Invests ${p_inc.cumulative_metrics.total_cost_usd:,.0f} upfront for ${p_inc.cumulative_metrics.total_net_profit_usd:,.0f} projected net profit ({p_inc.cumulative_metrics.cumulative_roi_pct:.1f}% ROI).\n"
            f"- High-Efficiency / Low-Exposure ('Highest ROI'): Spends ${p_roi.cumulative_metrics.total_cost_usd:,.0f} to return ${p_roi.cumulative_metrics.total_net_profit_usd:,.0f} ({p_roi.cumulative_metrics.cumulative_roi_pct:.1f}% ROI).\n"
            f"- Low-Stress / Low-Labor ('Least Effort'): Lowest fieldwork load ({p_lab.cumulative_metrics.total_labor_hours:.0f} hrs, {p_lab.cumulative_metrics.total_machinery_passes} tractor passes) with ${p_lab.cumulative_metrics.total_net_profit_usd:,.0f} net profit.\n"
            f"- Low-Risk / Maximum Resilience ('Least Crop Loss Risk'): Lowest site-weighted loss score ({p_risk.cumulative_metrics.composite_loss_risk_score:.1f}/100) while returning ${p_risk.cumulative_metrics.total_net_profit_usd:,.0f}."
        )

        decision_guide = (
            "WHICH PLAN SHOULD YOU CHOOSE?\n"
            "1. Choose 'Most Income' if: You have cash in the bank, market contracts in hand, and want maximum total dollars.\n"
            "2. Choose 'Highest ROI' if: You have limited working capital and need each dollar to generate the biggest percentage return.\n"
            "3. Choose 'Best Soil Health' if: Your ground is compacted (>250 PSI), organic matter is low, and you want to build long-term land equity.\n"
            "4. Choose 'Least Effort' if: You farm part-time, have older machinery, or cannot afford hired labor.\n"
            "5. Choose 'Least Crop Loss Risk' if: Your area suffers from erratic rainfall, heat spikes, and you want guaranteed security."
        )

        field_checklist = [
            "Dig a simple spade test hole (30 cm deep) to inspect earthworm activity and check for hardpan layers.",
            "Set tractor and combine tire pressures to 12-15 PSI before field entry to prevent deep soil packing.",
            "Verify live rhizobia inoculant on all legume seed bags before planting (store in cool, dark place).",
            "Walk field boundaries and drainage ditches after the first heavy rain to ensure water runs off without pooling.",
            "Calibrate seed drill meters and sprayer nozzles with clean water to avoid costly over-application.",
            "Take a quick mid-season soil moisture check at shovel depth during peak summer flowering."
        ]

        exec_summary = (
            f"Comprehensive 3-year agricultural projection completed for parcel '{cadastre}' ({area} ha, {soil_type}). "
            f"Five distinct cultivation strategies have been generated to accommodate contrasting farm management priorities. "
            f"The 'Most Income' strategy ({' -> '.join(p_inc.rotation_sequence)}) achieves peak cumulative net profit of "
            f"${p_inc.cumulative_metrics.total_net_profit_usd:,.2f}. The 'Best Soil Health' strategy ({' -> '.join(p_soil.rotation_sequence)}) "
            f"fixes {p_soil.cumulative_metrics.total_biological_n_fixed_kg_ha:.1f} kg N/ha biologically. "
            f"The 'Highest ROI' strategy delivers {p_roi.cumulative_metrics.cumulative_roi_pct:.1f}% return on investment with minimal capital risk."
        )

        climate_context = (
            f"NASA POWER agroclimatology indicates an annual evaporative sun/air demand (ET0) of {climate.get('annual_et0_mm', 1080):.0f} mm, "
            f"offset by {climate.get('annual_precip_mm', 640):.0f} mm of rainfall recorded via NASA GPM IMERG. "
            f"NASA SMAP observations confirm baseline root-zone soil moisture at {climate.get('smap_rootzone_moisture', 0.26) * 100:.1f}%. "
            f"With a field slope of {parcel.get('slope_pct', 2.0):.1f}% and an elevation of {parcel.get('elevation_m', 150):.0f} m, "
            f"{'caution is warranted regarding depression waterlogging' if climate.get('low_spot_hazard') else 'surface drainage is stable and well-aerated'}."
        )

        tradeoff_matrix = (
            f"1. Income vs. Capital: Most Income generates ${p_inc.cumulative_metrics.total_net_profit_usd:,.2f} but requires ${p_inc.cumulative_metrics.total_cost_usd:,.2f}. "
            f"2. Capital Efficiency: Highest ROI delivers {p_roi.cumulative_metrics.cumulative_roi_pct:.1f}% return with only ${p_roi.cumulative_metrics.total_cost_usd:,.2f} spent. "
            f"3. Soil Equity: Best Soil Health fixes ${p_soil.cumulative_metrics.synthetic_n_saved_usd:,.2f} worth of free nitrogen and relieves subsoil hardpan."
        )

        soil_narrative = (
            f"Year 1 establishes root architecture and canopy protection. Year 2 leverages rotational diversity and residual nitrogen credits. "
            f"Over 3 years, SOC shifts by {p_soil.cumulative_metrics.net_soc_change_pct:+.2f}% and modeled topsoil/subsoil resistance moves toward {p_soil.cumulative_metrics.final_compaction_psi:.0f} PSI (confirm actual plowpan depth with a spade test)."
        )

        resilience_playbook = (
            "1. Drought Mitigation: Prioritize drought-resilient crops (Sorghum, Alfalfa) with deep taproots to scavenge subsoil moisture. "
            "2. Flood & Waterlogging Prevention: Clear field perimeter furrows; avoid planting pulse legumes in low-lying depressions. "
            "3. Frost Management: For cool-season crops, monitor canopy temperature during floral bud emergence. "
            "4. Heatwave Stress: Ensure adequate soil moisture before flowering to sustain cooling."
        )

        return GeminiAdvisoryReport(
            model_used="deterministic-agronomic-engine",
            farmer_plain_language_summary=farmer_summary,
            strategies_breakdown=breakdowns,
            three_year_operational_overview=op_overview,
            risk_vs_reward_comparison=risk_reward,
            farmer_decision_guide=decision_guide,
            ground_truth_field_checklist=field_checklist,
            executive_summary=exec_summary,
            parcel_climate_context=climate_context,
            strategy_tradeoff_matrix=tradeoff_matrix,
            year_by_year_soil_transformation=soil_narrative,
            extreme_event_resilience_playbook=resilience_playbook
        )
