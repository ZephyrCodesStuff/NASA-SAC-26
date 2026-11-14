"""Satellite & Rotation Insights dialog powered by `data-api`, `formulas.py`, and `explainer.py`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nicegui import ui

logger = logging.getLogger(__name__)

from src.auth import is_farm_owner
from src.explainer import explain_plot_insights
from src.farms import FarmStore
from src.formulas import evaluate_plot_strategies
from src.providers.data_api import (
    FAST_DATASETS,
    SLOW_DATASETS,
    DataApiClient,
    extract_datasets,
    is_snapshot_fresh,
    merge_telemetry_snapshots,
    summarize_sensor_gaps,
)


def _extract_history_series(datasets: dict[str, dict[str, Any]]) -> tuple[list[str], list[float | None], list[float | None], list[float | None]]:
    """Align NDVI (HLS), rainfall (IMERG), and root-zone moisture (SMAP) onto shared dates."""
    ndvi_map: dict[str, float] = {}
    rain_map: dict[str, float] = {}
    smap_map: dict[str, float] = {}

    for pt in (datasets.get("crop_health") or {}).get("history") or []:
        if pt.get("date") and pt.get("ndvi") is not None:
            ndvi_map[str(pt["date"])] = round(float(pt["ndvi"]), 3)
    for pt in (datasets.get("rainfall") or {}).get("history") or []:
        d = pt.get("date")
        val = pt.get("rain_mm") if pt.get("rain_mm") is not None else pt.get("precipitation_mm")
        if d and val is not None:
            rain_map[str(d)] = round(float(val), 1)
    for pt in (datasets.get("soil_moisture") or {}).get("history") or []:
        d = pt.get("date")
        val = pt.get("root_zone_wetness") if pt.get("root_zone_wetness") is not None else pt.get("rootzone_moisture")
        if d and val is not None:
            smap_map[str(d)] = round(float(val) * 100.0, 1)

    dates = sorted(set(ndvi_map) | set(rain_map) | set(smap_map))[-45:]
    return (
        dates,
        [ndvi_map.get(d) for d in dates],
        [rain_map.get(d) for d in dates],
        [smap_map.get(d) for d in dates],
    )


async def open_plot_insights_dialog(
    plot: dict[str, Any],
    farm: dict[str, Any],
    current_user: dict[str, Any],
    farm_store: FarmStore,
    data_api: DataApiClient,
) -> None:
    """Open the two-stage progressive NASA telemetry & rotation strategy dialog for a plot."""
    owner = is_farm_owner(farm, current_user)
    snapshot: dict[str, Any] | None = plot.get("nasa_snapshot")
    soil_override: dict[str, Any] = dict(plot.get("soil_override") or {})

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl max-h-[90vh] overflow-y-auto p-5 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label(f"{plot.get('label') or 'Plot'} — Satellite & Rotation Insights").classes(
                    "text-lg font-bold text-primary"
                )
                ui.label(
                    f"{farm.get('name')} · {plot.get('cadastral_ref') or 'Custom Polygon'} · {plot.get('area_ha', 0):.2f} ha"
                ).classes("text-xs text-gray-500")
            with ui.row().classes("items-center gap-2"):
                fetch_badge = ui.badge("Checking cache...", color="amber")
                ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        body = ui.column().classes("w-full gap-4")

        def render_contents(snap: dict[str, Any] | None, api_note: str | None = None) -> None:
            body.clear()
            datasets = extract_datasets(snap)
            gaps = summarize_sensor_gaps(datasets, soil_override=soil_override)
            analysis = evaluate_plot_strategies(
                datasets=datasets,
                area_ha=float(plot.get("area_ha") or 1.0),
                baseline_rotation=plot.get("baseline_rotation"),
                soil_override=soil_override,
            )
            explained = explain_plot_insights(analysis, gaps, plot_label=str(plot.get("label") or "Plot"))
            inputs = analysis["inputs"]

            with body:
                if api_note:
                    ui.label(api_note).classes("text-xs text-amber-800 bg-amber-50 p-2 rounded w-full")

                # 1. Two-Tier Telemetry Strip (Field vs Regional)
                with ui.grid(columns=2).classes("w-full gap-3"):
                    with ui.card().classes("p-3 bg-emerald-50/50 border border-emerald-200"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Your Field (30m–70m)").classes("text-xs font-bold text-emerald-900")
                            ui.badge("HLS · ECOSTRESS · NASADEM", color="positive").props("outline")
                        with ui.grid(columns=2).classes("w-full gap-1 text-xs mt-1"):
                            ui.label("NDVI (Vigor)").classes("text-gray-600")
                            ui.label(f"{inputs['ndvi']:.2f}").classes("font-semibold text-right")
                            ui.label("Daily ET Source").classes("text-gray-600")
                            ui.label(f"{inputs['et0_mm_day']:.2f} mm/d ({inputs['et_source']})").classes("font-semibold text-right")
                            ui.label("Slope / Low Spot").classes("text-gray-600")
                            ui.label(f"{inputs['slope_deg']:.1f}° · {'Wet pocket' if inputs['low_spot_flag'] else 'Well drained'}").classes("font-semibold text-right")

                    with ui.card().classes("p-3 bg-blue-50/50 border border-blue-200"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Regional Context (250m–300km)").classes("text-xs font-bold text-blue-900")
                            ui.badge("SMAP · IMERG · POWER · GRACE", color="primary").props("outline")
                        with ui.grid(columns=2).classes("w-full gap-1 text-xs mt-1"):
                            ui.label("Root-Zone Moisture").classes("text-gray-600")
                            ui.label(f"{inputs['root_zone_moisture'] * 100:.0f}%").classes("font-semibold text-right")
                            ui.label("30d Rain / Dry Streak").classes("text-gray-600")
                            ui.label(f"{inputs['rain_30d_mm']:.0f} mm · {inputs['consecutive_dry_days']:.0f}d dry").classes("font-semibold text-right")
                            ui.label("Soil Estimate").classes("text-gray-600")
                            ui.badge(gaps["soil_badge"], color="positive" if "Lab" in gaps["soil_badge"] else "grey").props("dense")

                for msg in gaps["alerts"] + gaps["fallbacks"]:
                    ui.label(f"• {msg}").classes("text-xs text-amber-900 bg-amber-50 px-2 py-1 rounded w-full")

                # 2. Soil Override Bar (farm_admin editable)
                with ui.expansion("Soil Profile & Local Lab Overrides", icon="science").classes("w-full border rounded"):
                    with ui.row().classes("w-full items-end gap-2 p-2"):
                        clay_in = ui.number("Clay %", value=inputs["clay_pct"], min=0, max=100, step=1).props("dense outlined").classes("w-28")
                        sand_in = ui.number("Sand %", value=inputs["sand_pct"], min=0, max=100, step=1).props("dense outlined").classes("w-28")
                        oc_in = ui.number("Org. C (g/kg)", value=inputs["organic_carbon_g_kg"], min=0, max=100, step=0.5).props("dense outlined").classes("w-32")
                        ph_in = ui.number("pH", value=inputs["ph"], min=3.5, max=9.5, step=0.1).props("dense outlined").classes("w-24")

                        if owner:
                            async def save_soil() -> None:
                                soil_override.update(
                                    {
                                        "clay_pct": clay_in.value,
                                        "sand_pct": sand_in.value,
                                        "organic_carbon_g_kg": oc_in.value,
                                        "ph": ph_in.value,
                                    }
                                )
                                plot["soil_override"] = dict(soil_override)
                                await farm_store.update_plot(plot["id"], {"soil_override": plot["soil_override"]}, user=current_user)
                                ui.notify("Saved soil overrides", type="positive")
                                render_contents(snap, api_note)

                            ui.button("Save Soil Overrides", on_click=save_soil, color="primary").props("dense")
                        else:
                            ui.badge("Viewer Mode (Read-Only)", color="blue-grey")

                # 3. 90-Day Multi-Sensor Chart (if history present)
                dates, ndvi_s, rain_s, smap_s = _extract_history_series(datasets)
                if dates:
                    ui.echart(
                        {
                            "tooltip": {"trigger": "axis"},
                            "legend": {"data": ["HLS NDVI", "IMERG Rain (mm)", "SMAP Root Moisture (%)"]},
                            "xAxis": {"type": "category", "data": dates},
                            "yAxis": [
                                {"type": "value", "name": "NDVI", "min": 0, "max": 1},
                                {"type": "value", "name": "mm / %"},
                            ],
                            "series": [
                                {"name": "HLS NDVI", "type": "line", "yAxisIndex": 0, "data": ndvi_s, "smooth": True},
                                {"name": "IMERG Rain (mm)", "type": "bar", "yAxisIndex": 1, "data": rain_s},
                                {"name": "SMAP Root Moisture (%)", "type": "line", "yAxisIndex": 1, "areaStyle": {"opacity": 0.15}, "data": smap_s},
                            ],
                        }
                    ).classes("w-full h-56")

                # 4. Plain-Language Diagnosis + Top 3 Rotation Strategies
                with ui.card().classes("w-full p-3 bg-slate-50 gap-1"):
                    ui.label("Agronomic Diagnosis").classes("text-xs font-bold text-primary uppercase")
                    for b in explained["bullets"]:
                        ui.label(f"• {b}").classes("text-xs text-gray-800")

                ui.label("Top 3 Resilient 3-Year Rotations (FAO-56 · RUSLE · IPCC N)").classes("text-sm font-bold text-primary")
                with ui.grid(columns=3).classes("w-full gap-3"):
                    for strat in analysis["strategies"]:
                        with ui.card().classes("p-3 gap-1.5 border"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(strat["name"]).classes("text-xs font-bold text-gray-900")
                                ui.badge(f"{strat['score']:.0f}/100", color="positive" if strat["score"] >= 70 else "amber")
                            ui.label(" → ".join(strat["rotation"])).classes("text-xs font-medium text-primary")
                            ui.label(f"Water deficit: {strat['water_deficit_m3']:,.0f} m³").classes("text-[11px] text-gray-600")
                            ui.label(f"Erosion (RUSLE): {strat['erosion_t_ha_yr']:.2f} t/ha/yr").classes("text-[11px] text-gray-600")
                            ui.label(f"N budget: {strat['n_budget_kg_ha']:+.0f} kg/ha/yr").classes("text-[11px] text-gray-600")
                            if owner:
                                async def apply_plan(s=strat) -> None:
                                    plot["active_plan"] = s
                                    await farm_store.update_plot(plot["id"], {"active_plan": s}, user=current_user)
                                    ui.notify(f"Applied '{s['name']}'", type="positive")

                                ui.button("Apply Plan", on_click=apply_plan, color="primary").props("outline dense size=sm").classes("w-full mt-1")

                # 5. Local Eyes Checklist & Disclaimer
                with ui.expansion("Where Satellite Data Needs Local Eyes & Sources", icon="visibility").classes("w-full border rounded"):
                    for item in explained["checklist"]:
                        ui.label(f"• {item}").classes("text-xs text-gray-700 px-2")
                    ui.label(explained["disclaimer"]).classes("text-[11px] italic text-gray-500 px-2 pt-1")

        dlg.open()

        # Stage 1: Use fresh cached `nasa_snapshot` or fetch fast datasets
        if is_snapshot_fresh(snapshot):
            fetch_badge.set_text("Cached Snapshot")
            fetch_badge.props("color=positive")
            render_contents(snapshot)
            return

        fetch_badge.set_text("Fetching NASA Stage 1...")
        fetch_badge.props("color=amber")
        feature = {
            "type": "Feature",
            "id": plot.get("cadastral_ref") or plot.get("id"),
            "geometry": plot["geometry"],
            "properties": {"area_ha": plot.get("area_ha")},
        }
        try:
            snapshot = await data_api.fetch_plot_telemetry(feature, datasets=FAST_DATASETS, history=True)
            plot["nasa_snapshot"] = snapshot
            if owner:
                await farm_store.update_plot(plot["id"], {"nasa_snapshot": snapshot}, user=current_user)
            fetch_badge.set_text("Stage 1 Ready (Enriching MODIS ET...)")
            fetch_badge.props("color=primary")
            render_contents(snapshot)

            # Stage 2: Background enrichment for slow MODIS MOD16A2 (~50s cold)
            async def _enrich_stage2() -> None:
                try:
                    modis = await data_api.fetch_plot_telemetry(feature, datasets=SLOW_DATASETS, history=True)
                    merged = merge_telemetry_snapshots(snapshot, modis)
                    plot["nasa_snapshot"] = merged
                    if owner:
                        await farm_store.update_plot(plot["id"], {"nasa_snapshot": merged}, user=current_user)
                    fetch_badge.set_text("All 9 Datasets Ready")
                    fetch_badge.props("color=positive")
                    render_contents(merged)
                except Exception:
                    fetch_badge.set_text("Stage 1 Ready")
                    fetch_badge.props("color=positive")

            asyncio.create_task(_enrich_stage2())
        except Exception as exc:
            logger.warning("data-api fetch failed (%s): %s", data_api.base_url, exc)
            fetch_badge.set_text("Baseline Mode")
            fetch_badge.props("color=warning")
            render_contents(
                None,
                api_note=f"data-api ({data_api.base_url}) is offline/unreachable ({type(exc).__name__}: {exc}) — running deterministic baseline models.",
            )
