"""Dedicated Plot Detail page with Esri World Imagery thumbnail and 3 tabbed views."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from nicegui import ui

from src.auth import is_farm_owner
from src.explainer import explain_plot_insights
from src.farms import FarmStore, compute_geometry_bounds
from src.formulas import evaluate_plot_strategies
from src.providers.data_api import (
    FAST_DATASETS,
    SLOW_DATASETS,
    DataApiClient,
    build_analysis_payload,
    compute_soil_override_flags,
    extract_datasets,
    is_snapshot_fresh,
    merge_telemetry_snapshots,
    summarize_sensor_gaps,
)

logger = logging.getLogger(__name__)

ESRI_WORLD_IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


def _extract_history_series(
    datasets: dict[str, dict[str, Any]],
) -> tuple[list[str], list[float | None], list[float | None], list[float | None]]:
    """Align HLS NDVI, IMERG rainfall, and SMAP root-zone moisture time series by date."""
    hls_hist = (datasets.get("crop_health") or {}).get("history") or []
    rain_hist = (datasets.get("rainfall") or {}).get("history") or []
    smap_hist = (datasets.get("soil_moisture") or {}).get("history") or []

    by_date: dict[str, dict[str, float | None]] = {}
    for row in hls_hist:
        d = row.get("date")
        if d:
            by_date.setdefault(d, {})["ndvi"] = row.get("ndvi")
    for row in rain_hist:
        d = row.get("date")
        if d:
            by_date.setdefault(d, {})["rain"] = row.get("precip_mm") or row.get("rain_mm")
    for row in smap_hist:
        d = row.get("date")
        if d:
            val = row.get("root_zone_wetness") or row.get("rootzone_moisture")
            by_date.setdefault(d, {})["smap"] = round(float(val) * 100.0, 1) if val is not None else None

    dates = sorted(by_date.keys())[-90:]
    ndvi_series = [by_date[d].get("ndvi") for d in dates]
    rain_series = [by_date[d].get("rain") for d in dates]
    smap_series = [by_date[d].get("smap") for d in dates]
    return dates, ndvi_series, rain_series, smap_series


async def build_plot_detail_page(
    *,
    plot_id: str,
    current_user: dict[str, Any],
    farm_store: FarmStore,
    data_api: DataApiClient,
) -> None:
    """Render `/plots/{plot_id}` with Esri World_Imagery thumbnail and 3 tabs."""
    plot, farm = await farm_store.get_plot_with_farm(plot_id, user=current_user)
    if not plot or not farm:
        with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-4"):
            ui.label("Plot not found or access denied.").classes("text-lg font-bold text-negative")
            ui.button("Back to Map", icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("color=primary")
        return

    owner = is_farm_owner(farm, current_user)
    snapshot: dict[str, Any] | None = plot.get("nasa_snapshot")
    soil_override: dict[str, Any] = dict(plot.get("soil_override") or {})
    sub_plots: list[dict[str, Any]] = list(plot.get("sub_plots") or [])
    area_ha = float(plot.get("area_ha") or 0.0)

    with ui.column().classes("w-full max-w-6xl mx-auto p-4 md:p-6 gap-4"):
        # --- Top Navigation & Hero Card with Esri Satellite Thumbnail ---
        with ui.row().classes("w-full items-center justify-between"):
            ui.button("Back to Map", icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "flat dense color=primary"
            )
            with ui.row().classes("items-center gap-2"):
                fetch_badge = ui.badge("Checking cache...", color="amber")
                if owner:
                    refresh_btn = ui.button("Refresh NASA Data", icon="refresh").props(
                        "outline dense size=sm color=primary"
                    )

        with ui.card().classes("w-full p-4 md:p-5 border"):
            with ui.row().classes("w-full items-start justify-between gap-6 flex-wrap"):
                with ui.column().classes("flex-1 min-w-[260px] gap-1.5"):
                    ui.label(plot.get("label") or "Plot").classes("text-2xl font-bold text-primary")
                    ui.label(
                        f"{farm.get('name')} · {area_ha:.2f} ha"
                        + (f" · {len(sub_plots)} Catasto sub-plots" if len(sub_plots) > 1 else "")
                    ).classes("text-sm text-gray-600")
                    ui.label(plot.get("cadastral_ref") or "Custom drawn polygon").classes(
                        "text-xs font-mono text-gray-500"
                    )
                    with ui.row().classes("items-center gap-2 mt-2"):
                        wc_lbl = plot.get("worldcover_label") or "Custom Area"
                        ui.badge(wc_lbl, color="positive").props("outline")
                        rot = plot.get("baseline_rotation") or []
                        if rot:
                            ui.badge(" → ".join(rot), color="primary").props("outline")
                        if not owner:
                            ui.badge("Viewer Mode (Read-Only)", color="blue-grey")

                # Esri World_Imagery Satellite Thumbnail Box
                with ui.column().classes("items-end gap-1"):
                    c = plot.get("centroid") or {}
                    center = (float(c["lat"]), float(c["lon"])) if "lat" in c and "lon" in c else (44.847, 7.717)
                    thumb_map = ui.leaflet(
                        center=center,
                        zoom=16,
                        options={
                            "zoomControl": False,
                            "attributionControl": False,
                            "dragging": False,
                            "scrollWheelZoom": False,
                            "doubleClickZoom": False,
                            "boxZoom": False,
                            "keyboard": False,
                        },
                    ).classes("w-72 h-44 rounded-lg overflow-hidden border border-gray-300 shadow-sm")
                    ui.label("Satellite view: Esri World Imagery").classes("text-[10px] text-gray-400")

        async def _init_satellite_thumbnail() -> None:
            await thumb_map.initialized()
            thumb_map.clear_layers()
            thumb_map.tile_layer(
                url_template=ESRI_WORLD_IMAGERY_URL,
                options={"maxZoom": 19, "attribution": "Esri World Imagery"},
            )
            geom = plot.get("geometry")
            if geom:
                thumb_map.generic_layer(
                    name="geoJSON",
                    args=[
                        {"type": "Feature", "geometry": geom},
                        {
                            "style": {
                                "color": "#38bdf8",
                                "weight": 3,
                                "fillColor": "#38bdf8",
                                "fillOpacity": 0.16,
                            }
                        },
                    ],
                )
                bounds = compute_geometry_bounds(geom)
                if bounds:
                    thumb_map.run_map_method("fitBounds", bounds, {"padding": [12, 12], "maxZoom": 18})

        ui.timer(0.05, _init_satellite_thumbnail, once=True)

        # --- 3 Tabbed Views ---
        with ui.tabs().classes("w-full border-b") as tabs:
            tab_overall = ui.tab("Overall Data", icon="sensors")
            tab_analysis = ui.tab("Analysis Reports (WIP)", icon="analytics")
            tab_devices = ui.tab("Devices (WIP)", icon="memory")

        with ui.tab_panels(tabs, value=tab_overall).classes("w-full bg-transparent p-0"):
            with ui.tab_panel(tab_overall).classes("p-0 pt-3"):
                overall_container = ui.column().classes("w-full gap-4")

            with ui.tab_panel(tab_analysis).classes("p-0 pt-3"):
                analysis_container = ui.column().classes("w-full gap-4")

            with ui.tab_panel(tab_devices).classes("p-0 pt-3"):
                with ui.card().classes("w-full p-6 border border-dashed border-gray-300 bg-slate-50 gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("construction", size="22px").classes("text-amber-600")
                        ui.label("Field Devices & IoT Sensors (WIP)").classes("text-base font-bold text-gray-800")
                    ui.label(
                        "Connect soil moisture probes, local weather stations, and irrigation controllers to this plot "
                        "to automatically feed ground-truth overrides into your satellite baseline."
                    ).classes("text-xs text-gray-600")

        def render_contents(snap: dict[str, Any] | None, api_note: str | None = None) -> None:
            datasets = extract_datasets(snap)
            gaps = summarize_sensor_gaps(datasets, soil_override=soil_override)
            analysis = evaluate_plot_strategies(
                datasets=datasets,
                area_ha=area_ha or 1.0,
                baseline_rotation=plot.get("baseline_rotation"),
                soil_override=soil_override,
            )
            explained = explain_plot_insights(analysis, gaps, plot_label=str(plot.get("label") or "Plot"))
            inputs = analysis["inputs"]

            # --- Tab 1: Overall Data ---
            overall_container.clear()
            with overall_container:
                if api_note:
                    ui.label(api_note).classes("text-xs text-amber-900 bg-amber-50 p-2 rounded w-full border border-amber-200")

                with ui.grid(columns=2).classes("w-full gap-3"):
                    with ui.card().classes("p-4 bg-emerald-50/50 border border-emerald-200"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Your Field (30m–70m)").classes("text-xs font-bold text-emerald-900")
                            ui.badge("HLS · ECOSTRESS · NASADEM", color="positive").props("outline")
                        with ui.grid(columns=2).classes("w-full gap-1.5 text-xs mt-2"):
                            ui.label("NDVI (Vigor)").classes("text-gray-600")
                            ui.label(f"{inputs['ndvi']:.2f}").classes("font-semibold text-right")
                            ui.label("Daily ET Source").classes("text-gray-600")
                            ui.label(f"{inputs['et0_mm_day']:.2f} mm/d ({inputs['et_source']})").classes(
                                "font-semibold text-right"
                            )
                            ui.label("Slope / Low Spot").classes("text-gray-600")
                            ui.label(
                                f"{inputs['slope_deg']:.1f}° · {'Wet pocket' if inputs['low_spot_flag'] else 'Well drained'}"
                            ).classes("font-semibold text-right")

                    with ui.card().classes("p-4 bg-blue-50/50 border border-blue-200"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Regional Context (250m–300km)").classes("text-xs font-bold text-blue-900")
                            ui.badge("SMAP · IMERG · POWER · GRACE", color="primary").props("outline")
                        with ui.grid(columns=2).classes("w-full gap-1.5 text-xs mt-2"):
                            ui.label("Root-Zone Moisture").classes("text-gray-600")
                            ui.label(f"{inputs['root_zone_moisture'] * 100:.0f}%").classes("font-semibold text-right")
                            ui.label("30d Rain / Dry Streak").classes("text-gray-600")
                            ui.label(f"{inputs['rain_30d_mm']:.0f} mm · {inputs['consecutive_dry_days']:.0f}d dry").classes(
                                "font-semibold text-right"
                            )
                            ui.label("Soil Estimate").classes("text-gray-600")
                            ui.badge(gaps["soil_badge"], color="positive" if "Lab" in gaps["soil_badge"] else "grey").props(
                                "dense"
                            )

                for msg in gaps["alerts"] + gaps["fallbacks"]:
                    ui.label(f"• {msg}").classes("text-xs text-amber-900 bg-amber-50 px-3 py-1.5 rounded w-full")

                # Soil Override Bar
                with ui.expansion("Soil Profile & Local Lab Overrides", icon="science", value=True).classes(
                    "w-full border rounded bg-white"
                ):
                    with ui.row().classes("w-full items-end gap-3 p-2 flex-wrap"):
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
                                flags = compute_soil_override_flags(soil_override)
                                plot["soil_override"] = dict(soil_override)
                                plot["overridden_fields"] = flags
                                await farm_store.update_plot(
                                    plot["id"],
                                    {"soil_override": plot["soil_override"], "overridden_fields": flags},
                                    user=current_user,
                                )
                                ui.notify(f"Saved overrides ({len(flags)} fields locked)", type="positive")
                                render_contents(snap, api_note)

                            async def reset_soil() -> None:
                                soil_override.clear()
                                plot["soil_override"] = {}
                                plot["overridden_fields"] = []
                                await farm_store.update_plot(
                                    plot["id"],
                                    {"soil_override": {}, "overridden_fields": []},
                                    user=current_user,
                                )
                                ui.notify("Reset soil profile to satellite baseline", type="info")
                                render_contents(snap, api_note)

                            ui.button("Save Soil Overrides", on_click=save_soil, color="primary").props("dense")
                            if compute_soil_override_flags(soil_override):
                                ui.button("Reset to Satellite", on_click=reset_soil, color="grey").props("outline dense")
                        else:
                            ui.badge("Viewer Mode (Read-Only)", color="blue-grey")

                # 90-Day Multi-Sensor Chart
                dates, ndvi_s, rain_s, smap_s = _extract_history_series(datasets)
                if dates:
                    with ui.card().classes("w-full p-4 border"):
                        ui.label("90-Day Multi-Sensor Time Series").classes("text-xs font-bold text-gray-700 mb-1")
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
                        ).classes("w-full h-64")

                if sub_plots:
                    with ui.expansion(f"Catasto Sub-Plots ({len(sub_plots)})", icon="grid_view").classes("w-full border rounded bg-white"):
                        for sp in sub_plots:
                            ui.label(
                                f"• {sp.get('cadastral_ref') or 'Parcel'} — {float(sp.get('area_ha') or 0.0):.4f} ha"
                            ).classes("text-xs font-mono text-gray-700 px-2 py-0.5")

            # --- Tab 2: Analysis Reports (WIP) ---
            analysis_container.clear()
            with analysis_container:
                with ui.card().classes("w-full p-3 bg-amber-50 border border-amber-200"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("construction", size="20px").classes("text-amber-700")
                        ui.label("Analysis-API Integration (WIP) — Showing Deterministic Baseline Preview").classes(
                            "text-xs font-bold text-amber-900"
                        )

                with ui.card().classes("w-full p-4 bg-slate-50 border gap-1"):
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

                                ui.button("Apply Plan", on_click=apply_plan, color="primary").props(
                                    "outline dense size=sm"
                                ).classes("w-full mt-1")

                with ui.expansion("Where Satellite Data Needs Local Eyes & Sources", icon="visibility").classes(
                    "w-full border rounded bg-white"
                ):
                    for item in explained["checklist"]:
                        ui.label(f"• {item}").classes("text-xs text-gray-700 px-2")
                    ui.label(explained["disclaimer"]).classes("text-[11px] italic text-gray-500 px-2 pt-1")

                with ui.expansion("Analysis-API Payload Preview (JSON)", icon="code").classes("w-full border rounded bg-white"):
                    payload_preview = build_analysis_payload(plot)
                    # Keep preview concise by summarizing raw snapshot size
                    preview_summary = {
                        "plot_id": payload_preview["plot_id"],
                        "area_ha": payload_preview["area_ha"],
                        "overridden_fields": payload_preview["overridden_fields"],
                        "soil_override": payload_preview["soil_override"],
                        "effective_datasets_keys": list((payload_preview["effective_datasets"] or {}).keys()),
                    }
                    ui.code(json.dumps(preview_summary, indent=2), language="json").classes("w-full text-xs")

        async def _fetch_and_store_telemetry() -> None:
            nonlocal snapshot
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
                    snapshot,
                    api_note=(
                        f"data-api ({data_api.base_url}) is offline/unreachable ({type(exc).__name__}: {exc}) "
                        "— running deterministic baseline models."
                    ),
                )

        if owner:
            refresh_btn.on_click(_fetch_and_store_telemetry)

        if is_snapshot_fresh(snapshot):
            fetch_badge.set_text("Cached Snapshot")
            fetch_badge.props("color=positive")
            render_contents(snapshot)
            return

        await _fetch_and_store_telemetry()
