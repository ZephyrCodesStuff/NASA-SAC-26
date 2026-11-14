"""Plain-language agronomic translator with deterministic template fallback."""

from __future__ import annotations

from typing import Any


def explain_plot_insights(
    analysis: dict[str, Any],
    gap_summary: dict[str, Any],
    plot_label: str = "Selected Plot",
) -> dict[str, Any]:
    """Translate `formulas.py` outputs and sensor gaps into farmer-friendly guidance."""
    inputs = analysis["inputs"]
    baseline = analysis["baseline"]
    strategies = analysis["strategies"]
    top = strategies[0] if strategies else baseline

    bullets: list[str] = []

    if baseline["water_balance_mm"] < -80:
        bullets.append(
            f"Water stress risk: {plot_label} faces an estimated {abs(baseline['water_balance_mm']):.0f} mm "
            f"seasonal water deficit ({baseline['water_deficit_m3']:,.0f} m³ across {inputs['area_ha']:.2f} ha) "
            f"based on {inputs['et_source']}."
        )
    else:
        bullets.append(
            f"Moisture outlook: Seasonal water balance is {baseline['water_balance_mm']:+.0f} mm "
            f"with {inputs['consecutive_dry_days']:.0f} recent consecutive dry days."
        )

    if baseline["erosion_t_ha_yr"] > 4.0:
        bullets.append(
            f"Topsoil erosion risk: RUSLE estimates {baseline['erosion_t_ha_yr']:.1f} t/ha/yr under the baseline "
            f"rotation (slope {inputs['slope_deg']:.1f}°, NDVI {inputs['ndvi']:.2f}). "
            f"Switching to '{top['name']}' cuts erosion to {top['erosion_t_ha_yr']:.1f} t/ha/yr."
        )
    else:
        bullets.append(
            f"Soil stability: Low baseline erosion ({baseline['erosion_t_ha_yr']:.1f} t/ha/yr); "
            f"'{top['name']}' further improves resilience to {top['score']:.0f}/100."
        )

    bullets.append(
        f"Nitrogen & root structure: Baseline N budget is {baseline['n_budget_kg_ha']:+.0f} kg/ha/yr. "
        f"'{top['name']}' ({' → '.join(top['rotation'])}) yields {top['n_budget_kg_ha']:+.0f} kg N/ha/yr."
    )

    checklist: list[str] = [
        "Walk the field after heavy rain to check for ponding or surface rills before finalizing spring tillage.",
        "Verify topsoil texture and pH with a local lab test if SoilGrids (250 m) differs from field history.",
    ]
    if inputs["low_spot_flag"]:
        checklist.append("Inspect low-lying pockets detected by NASADEM (30 m) for drainage before planting legumes.")
    for fb in gap_summary.get("fallbacks") or []:
        checklist.append(f"Sensor note: {fb}")
    for al in gap_summary.get("alerts") or []:
        checklist.append(al)

    return {
        "bullets": bullets,
        "checklist": checklist,
        "disclaimer": (
            "Recommendations support—and do not replace—local agronomist and farmer judgment."
        ),
    }
