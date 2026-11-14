"""Two-mode Leaflet map: Active Farm View + Draw-to-Claim Plot Refinement."""

from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from src.auth import is_farm_owner
from src.farms import (
    FarmStore,
    extract_drawn_geojson,
    merge_catasto_features_into_plot,
    polygons_intersect,
)
from src.providers.catasto import (
    TURIN_PRESETS,
    CatastoClient,
    _feature_bbox,
    is_in_italy,
    point_in_geojson_geometry,
)
from src.providers.data_api import DataApiClient
from src.providers.worldcover import WorldCoverClient
from src.ui.insights_dialog import open_plot_insights_dialog

# Land-cover visual styling & Material icon per ESA WorldCover class
LANDCOVER_STYLES: dict[int, dict[str, str]] = {
    40: {
        "name": "Cropland",
        "icon": "agriculture",
        "text_color": "amber-9",
        "color": "#d97706",
        "fillColor": "#f59e0b",
        "fillOpacity": "0.24",
    },
    30: {
        "name": "Grassland",
        "icon": "grass",
        "text_color": "green-9",
        "color": "#15803d",
        "fillColor": "#22c55e",
        "fillOpacity": "0.20",
    },
    10: {
        "name": "Tree cover",
        "icon": "park",
        "text_color": "teal-9",
        "color": "#0f766e",
        "fillColor": "#14b8a6",
        "fillOpacity": "0.14",
    },
    50: {
        "name": "Built-up",
        "icon": "apartment",
        "text_color": "blue-grey-7",
        "color": "#64748b",
        "fillColor": "#94a3b8",
        "fillOpacity": "0.12",
    },
}

DEFAULT_PLOT_STYLE: dict[str, str] = {
    "name": "Custom Plot",
    "icon": "crop_square",
    "text_color": "primary",
    "color": "#0b3d91",
    "fillColor": "#3b82f6",
    "fillOpacity": "0.20",
}


def _style_for_class(wc_class: int | None) -> dict[str, str]:
    if wc_class is None:
        return DEFAULT_PLOT_STYLE
    return LANDCOVER_STYLES.get(wc_class, DEFAULT_PLOT_STYLE)


async def build_catasto_map_picker(
    current_user: dict[str, Any],
    farm_store: FarmStore | None = None,
    catasto_client: CatastoClient | None = None,
    worldcover_client: WorldCoverClient | None = None,
    data_api_client: DataApiClient | None = None,
    default_preset: str = "carmagnola_po_valley",
    mode_slot: ui.row | None = None,
) -> None:
    """Render the two-mode farm map (Active Farm View & Edit/Draw Plot-Claiming Mode)."""
    store = farm_store or FarmStore()
    client = catasto_client or CatastoClient()
    wc_client = worldcover_client or WorldCoverClient()
    data_api = data_api_client or DataApiClient()
    preset = TURIN_PRESETS.get(default_preset) or TURIN_PRESETS["carmagnola_po_valley"]

    farms = await store.list_farms(current_user)
    state: dict[str, Any] = {
        "farms": farms,
        "current_farm": farms[0] if farms else None,
        "plots": [],
        "edit_mode": False,
        "plot_layers": [],
        "candidate_layers": [],
        "highlight_layer": None,
        "selected_plot": None,
        "pending_drawn": None,
        "pending_catasto": [],
    }

    with ui.element("div").classes("relative w-full h-[calc(100vh-56px)] min-h-[560px]"):
        m = ui.leaflet(
            center=(preset.lat, preset.lon),
            zoom=16,
            draw_control={
                "draw": {
                    "polygon": {"allowIntersection": False, "showArea": True},
                    "rectangle": True,
                    "circle": False,
                    "marker": False,
                    "circlemarker": False,
                    "polyline": False,
                },
                "edit": False,
            },
            hide_drawn_items=True,
        ).classes("w-full h-full z-0")

        # --- Top-Left Farm Toolbar Overlay ---
        with ui.card().classes(
            "absolute top-3 left-14 z-[1000] p-3 bg-white/95 backdrop-blur shadow-md gap-2 w-80"
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Active Farm").classes("text-sm font-bold text-primary")
                viewer_badge = ui.badge("Viewer Mode", color="blue-grey")

            farm_select = ui.select(
                options={f["id"]: f["name"] for f in state["farms"]},
                value=state["current_farm"]["id"] if state["current_farm"] else None,
                label="Select Farm",
            ).props("dense outlined").classes("w-full")

            with ui.row().classes("w-full items-center justify-end gap-2") as admin_controls:
                new_farm_btn = ui.button("+ Farm", icon="add").props("outline dense size=sm")

            with ui.row().classes("w-full items-center justify-between text-xs text-gray-600"):
                plot_count_label = ui.label("Saved plots: 0")
                mode_hint_label = ui.label("Read-only view").classes("text-[11px] text-gray-500")

            plot_list_container = ui.column().classes("w-full gap-1 max-h-44 overflow-y-auto mt-1")

        # --- Top-Right Plot / Claiming Card ---
        with ui.card().classes(
            "absolute top-3 right-3 z-[1000] p-4 bg-white/95 backdrop-blur shadow-lg w-80 max-h-[calc(100%-24px)] overflow-y-auto"
        ):
            with ui.row().classes("w-full items-center justify-between"):
                card_title = ui.label("Farm Plots").classes("text-base font-bold text-primary")
                status_badge = ui.badge("Active View", color="positive")

            hint_label = ui.label(
                "Click a saved plot to inspect it. Farm admins can toggle 'Edit Farm Plots' to draw new fields."
            ).classes("text-xs text-gray-600")

            # Existing Plot Info Container
            info_container = ui.column().classes("w-full gap-1.5 mt-1")
            info_container.visible = False
            with info_container:
                plot_name_label = ui.label("").classes("text-lg font-bold text-gray-900")
                plot_ref_label = ui.label("").classes("text-xs font-mono text-gray-600")
                ui.separator()
                with ui.grid(columns=2).classes("w-full gap-y-1 gap-x-2 text-xs"):
                    ui.label("Area").classes("text-gray-500")
                    area_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Land Cover").classes("text-gray-500")
                    with ui.row().classes("items-center justify-end gap-1"):
                        landcover_icon = ui.icon("agriculture", size="16px").classes("text-amber-600")
                        landcover_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Rotation").classes("text-gray-500")
                    rotation_val = ui.label("-").classes("text-right")

                    ui.label("Centroid").classes("text-gray-500")
                    centroid_val = ui.label("-").classes("font-mono text-right")

                async def on_open_insights() -> None:
                    if state["selected_plot"] and state["current_farm"]:
                        await open_plot_insights_dialog(
                            plot=state["selected_plot"],
                            farm=state["current_farm"],
                            current_user=current_user,
                            farm_store=store,
                            data_api=data_api,
                        )

                insights_btn = ui.button(
                    "Satellite & Rotation Insights", icon="satellite_alt", on_click=on_open_insights
                ).props("color=primary dense").classes("w-full mt-2")

                remove_plot_btn = ui.button(
                    "Remove from Farm", icon="delete", color="negative"
                ).props("outline dense").classes("w-full mt-1")
                remove_plot_btn.visible = False

            # Draw / Claim Confirmation Container (Edit Mode)
            claim_container = ui.column().classes("w-full gap-2 mt-1")
            claim_container.visible = False
            with claim_container:
                claim_summary = ui.label("").classes("text-xs text-gray-700")
                nickname_input = ui.input("Field Nickname", placeholder="e.g. North Maize Field").props("dense outlined").classes("w-full")
                crop_input = ui.input("Current Crop", value="Maize").props("dense outlined").classes("w-full")

                use_catasto_btn = ui.button(
                    "Use Catasto Plot Shapes", icon="auto_fix_high", color="primary"
                ).props("dense").classes("w-full")
                keep_drawn_btn = ui.button(
                    "Keep My Drawn Polygon", icon="check", color="secondary"
                ).props("outline dense").classes("w-full")
                cancel_claim_btn = ui.button("Cancel", color="grey").props("flat dense").classes("w-full")

        # New Farm Dialog (farm_admin only)
        with ui.dialog() as new_farm_dialog, ui.card().classes("w-80 p-4 gap-3"):
            ui.label("Create New Farm").classes("text-base font-bold text-primary")
            new_farm_name = ui.input("Farm Name", placeholder="Cascina Piemonte").props("dense outlined").classes("w-full")

            async def create_farm_submit() -> None:
                name = (new_farm_name.value or "").strip()
                if not name:
                    return
                created = await store.create_farm(name=name, user=current_user)
                state["farms"] = await store.list_farms(current_user)
                farm_select.options = {f["id"]: f["name"] for f in state["farms"]}
                farm_select.value = created["id"]
                new_farm_name.value = ""
                new_farm_dialog.close()
                await load_selected_farm(created["id"])

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=new_farm_dialog.close).props("flat")
                ui.button("Create", on_click=create_farm_submit, color="primary")

        new_farm_btn.on_click(new_farm_dialog.open)

        await m.initialized()

        def _sync_draw_toolbar_visibility() -> None:
            show_draw = bool(state["edit_mode"])
            ui.run_javascript(
                f"""
                (function toggleDraw(attempt) {{
                    const el = getElement({m.id});
                    if (!el || !el.$el) {{
                        if (attempt < 15) setTimeout(() => toggleDraw(attempt + 1), 100);
                        return;
                    }}
                    const ctrl = el.$el.querySelector('.leaflet-draw');
                    if (ctrl) ctrl.style.display = {'""' if show_draw else '"none"'};
                }})(0);
                """
            )

        def _clear_candidate_layers() -> None:
            for layer in state["candidate_layers"]:
                m.remove_layer(layer)
            state["candidate_layers"] = []
            state["pending_drawn"] = None
            state["pending_catasto"] = []
            claim_container.visible = False

        def _render_plot_icons(plots: list[dict[str, Any]]) -> None:
            icon_items = []
            for p in plots:
                c = p.get("centroid")
                if not isinstance(c, dict) or "lat" not in c or "lon" not in c:
                    continue
                st = _style_for_class(p.get("worldcover_class"))
                icon_items.append(
                    {
                        "lat": c["lat"],
                        "lon": c["lon"],
                        "icon": st["icon"],
                        "color": st["color"],
                        "label": p.get("label") or "",
                    }
                )
            ui.run_javascript(
                f"""
                (function renderPlotIcons(attempt) {{
                    const el = getElement({m.id});
                    if (!el || !el.map || typeof L === 'undefined') {{
                        if (attempt < 20) setTimeout(() => renderPlotIcons(attempt + 1), 100);
                        return;
                    }}
                    if (el._parcelIconLayer) el.map.removeLayer(el._parcelIconLayer);
                    const items = {json.dumps(icon_items)};
                    const markers = items.map(item => L.marker([item.lat, item.lon], {{
                        interactive: false,
                        icon: L.divIcon({{
                            className: '',
                            html: `<div style="width:22px;height:22px;border-radius:50%;background:rgba(255,255,255,0.92);border:1.5px solid ${{item.color}};display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(0,0,0,0.25);"><span class="material-icons" style="font-size:14px;color:${{item.color}};">${{item.icon}}</span></div>`,
                            iconSize: [22, 22],
                            iconAnchor: [11, 11],
                        }})
                    }}));
                    el._parcelIconLayer = L.layerGroup(markers).addTo(el.map);
                }})(0);
                """
            )

        def _render_saved_plots() -> None:
            for layer in state["plot_layers"]:
                m.remove_layer(layer)
            state["plot_layers"] = []
            if state["highlight_layer"] is not None:
                m.remove_layer(state["highlight_layer"])
                state["highlight_layer"] = None

            plots = state["plots"]
            plot_count_label.set_text(f"Saved plots: {len(plots)}")

            grouped: dict[int | None, list[dict[str, Any]]] = {}
            for p in plots:
                geom = p.get("geometry")
                if not geom:
                    continue
                wc_cls = p.get("worldcover_class")
                grouped.setdefault(wc_cls, []).append(
                    {"type": "Feature", "id": p.get("id"), "geometry": geom, "properties": p}
                )

            for wc_cls, feats in grouped.items():
                st = _style_for_class(wc_cls)
                layer = m.generic_layer(
                    name="geoJSON",
                    args=[
                        {"type": "FeatureCollection", "features": feats},
                        {
                            "style": {
                                "color": st["color"],
                                "weight": 2,
                                "fillColor": st["fillColor"],
                                "fillOpacity": float(st["fillOpacity"]),
                            }
                        },
                    ],
                )
                state["plot_layers"].append(layer)

            _render_plot_icons(plots)

            plot_list_container.clear()
            with plot_list_container:
                if not plots:
                    ui.label("No plots yet.").classes("text-[11px] text-gray-400 italic")
                for p in plots:
                    area_ha = float(p.get("area_ha") or 0.0)
                    sub_count = len(p.get("sub_plots") or [])
                    sub_txt = f" · {sub_count} parcels" if sub_count > 1 else ""
                    ui.button(
                        f"{p.get('label') or 'Plot'} ({area_ha:.2f} ha{sub_txt})",
                        icon="place",
                        on_click=lambda _, plot_item=p: _select_plot(plot_item, pan_to=True),
                    ).props("flat dense no-caps align=left size=sm").classes(
                        "w-full text-left text-xs text-gray-800 hover:bg-slate-100 rounded px-1"
                    )

        def _sync_mode_dropdown(owner: bool) -> None:
            if state["edit_mode"] and owner:
                mode_dropdown.set_text("Editor")
                mode_dropdown.props("icon=edit color=amber text-color=black dense no-caps")
            else:
                mode_dropdown.set_text("Viewer")
                mode_dropdown.props("icon=visibility color=white text-color=primary dense no-caps")
            edit_menu_item.set_enabled(owner)

        def set_edit_mode(editing: bool) -> None:
            owner = is_farm_owner(state["current_farm"], current_user)
            if editing and not owner:
                state["edit_mode"] = False
                _sync_mode_dropdown(False)
                return
            state["edit_mode"] = bool(editing)
            _clear_candidate_layers()
            _sync_role_controls()
            if state["edit_mode"]:
                status_badge.set_text("Edit Mode")
                status_badge.props("color=amber")
                hint_label.set_text("Use the polygon/rectangle tool (left) to draw a farm area.")
            else:
                status_badge.set_text("Active View")
                status_badge.props("color=positive")
                hint_label.set_text("Click a saved plot to inspect it.")

        target_slot = mode_slot if mode_slot is not None else admin_controls
        target_slot.clear()
        with target_slot:
            with ui.dropdown_button("Viewer", icon="visibility", auto_close=True).props(
                "color=white text-color=primary dense no-caps size=sm"
            ) as mode_dropdown:
                with ui.item(on_click=lambda: set_edit_mode(False)).props("dense"):
                    with ui.item_section().props("side").classes("pr-2"):
                        ui.icon("visibility", size="18px")
                    with ui.item_section():
                        ui.item_label("Viewer")
                        ui.item_label("Read-only map").props("caption")
                with ui.item(on_click=lambda: set_edit_mode(True)).props("dense") as edit_menu_item:
                    with ui.item_section().props("side").classes("pr-2"):
                        ui.icon("edit", size="18px")
                    with ui.item_section():
                        ui.item_label("Editor")
                        ui.item_label("Draw & manage plots").props("caption")

        def _sync_role_controls() -> None:
            owner = is_farm_owner(state["current_farm"], current_user)
            admin_controls.visible = owner
            viewer_badge.visible = not owner
            if not owner and state["edit_mode"]:
                state["edit_mode"] = False
            _sync_mode_dropdown(owner)
            mode_hint_label.set_text(
                "Draw polygon to claim" if state["edit_mode"] else ("Owner view" if owner else "Read-only view")
            )
            remove_plot_btn.visible = owner and state["edit_mode"] and state["selected_plot"] is not None
            _sync_draw_toolbar_visibility()

        async def load_selected_farm(farm_id: str | None) -> None:
            _clear_candidate_layers()
            state["selected_plot"] = None
            info_container.visible = False
            hint_label.visible = True

            farm = next((f for f in state["farms"] if f["id"] == farm_id), None)
            state["current_farm"] = farm
            _sync_role_controls()

            if not farm:
                state["plots"] = []
                _render_saved_plots()
                return

            state["plots"] = await store.list_plots(farm["id"], user=current_user)
            _render_saved_plots()

            # Center map on first plot if available
            if state["plots"]:
                c = state["plots"][0].get("centroid")
                if isinstance(c, dict) and "lat" in c and "lon" in c:
                    m.set_center((c["lat"], c["lon"]))
                    m.set_zoom(16)

        farm_select.on_value_change(lambda e: load_selected_farm(e.value))

        async def on_draw_created(e: Any) -> None:
            if not state["edit_mode"] or not is_farm_owner(state["current_farm"], current_user):
                return
            drawn = extract_drawn_geojson(e.args)
            if not drawn:
                return

            _clear_candidate_layers()
            info_container.visible = False
            hint_label.visible = False
            status_badge.set_text("Checking Catasto...")
            status_badge.props("color=amber")

            state["pending_drawn"] = drawn
            drawn_geom = drawn["geometry"]
            drawn_layer = m.generic_layer(
                name="geoJSON",
                args=[
                    drawn,
                    {"style": {"color": "#64748b", "weight": 2, "dashArray": "4, 4", "fillOpacity": 0.1}},
                ],
            )
            state["candidate_layers"].append(drawn_layer)

            # Query Catasto + WorldCover if drawn area is in Italy
            intersecting_farmland: list[dict[str, Any]] = []
            bbox = _feature_bbox(drawn_geom)
            if bbox is not None:
                min_lat, min_lon, max_lat, max_lon = bbox
                mid_lat = (min_lat + max_lat) / 2.0
                mid_lon = (min_lon + max_lon) / 2.0
                if is_in_italy(mid_lat, mid_lon):
                    # Clamp BBOX span safely under WFS 2,000 m Vdist limit
                    half_lat = min(max((max_lat - min_lat) / 2.0, 0.001), 0.007)
                    half_lon = min(max((max_lon - min_lon) / 2.0, 0.001), 0.009)
                    try:
                        fc = await client.fetch_parcels_in_bbox(
                            mid_lat - half_lat,
                            mid_lon - half_lon,
                            mid_lat + half_lat,
                            mid_lon + half_lon,
                            count=150,
                        )
                        candidates = fc.get("features") or []
                        overlapping = [f for f in candidates if polygons_intersect(drawn_geom, f["geometry"])]
                        if overlapping:
                            try:
                                await wc_client.classify_parcels(overlapping)
                                intersecting_farmland = [
                                    f for f in overlapping if (f.get("properties") or {}).get("is_farmland") is True
                                ]
                            except Exception:
                                intersecting_farmland = overlapping
                    except Exception:
                        intersecting_farmland = []

            state["pending_catasto"] = intersecting_farmland
            drawn_ha = drawn["properties"]["area_ha"]

            if intersecting_farmland:
                cat_layer = m.generic_layer(
                    name="geoJSON",
                    args=[
                        {"type": "FeatureCollection", "features": intersecting_farmland},
                        {
                            "style": {
                                "color": "#2563eb",
                                "weight": 2.5,
                                "dashArray": "6, 4",
                                "fillColor": "#3b82f6",
                                "fillOpacity": 0.22,
                            }
                        },
                    ],
                )
                state["candidate_layers"].append(cat_layer)
                total_cat_ha = sum((f.get("properties") or {}).get("area_ha", 0.0) for f in intersecting_farmland)
                claim_summary.set_text(
                    f"Found {len(intersecting_farmland)} Catasto farmland parcel(s) "
                    f"({total_cat_ha:.2f} ha) intersecting your {drawn_ha:.2f} ha selection."
                )
                use_catasto_btn.set_text(f"Save as 1 Plot ({len(intersecting_farmland)} Catasto sub-plots)")
                use_catasto_btn.visible = True
                keep_drawn_btn.set_text("Keep My Drawn Polygon")
                status_badge.set_text("Refine Selection")
                status_badge.props("color=primary")
            else:
                # No Catasto/WorldCover intersection -> accept drawn selection directly
                claim_summary.set_text(
                    f"No Catasto farmland plots found here. Ready to save your drawn area ({drawn_ha:.2f} ha)."
                )
                use_catasto_btn.visible = False
                keep_drawn_btn.set_text("Add Drawn Area to Farm")
                status_badge.set_text("Confirm Area")
                status_badge.props("color=primary")

            claim_container.visible = True

        m.on("draw:created", on_draw_created)

        async def _save_features_to_farm(features: list[dict[str, Any]], use_catasto_names: bool) -> None:
            farm = state["current_farm"]
            if not farm or not is_farm_owner(farm, current_user) or not features:
                return
            nick = (nickname_input.value or "").strip()
            crop = (crop_input.value or "Maize").strip() or "Maize"

            plot_data = merge_catasto_features_into_plot(
                features,
                label=nick,
                crop=crop,
                use_catasto_names=use_catasto_names,
                fallback_index=len(state["plots"]) + 1,
            )
            await store.add_plot(
                farm_id=farm["id"],
                plot_data=plot_data,
                user=current_user,
            )

            nickname_input.value = ""
            _clear_candidate_layers()
            await load_selected_farm(farm["id"])
            status_badge.set_text("Saved!")
            status_badge.props("color=positive")

        use_catasto_btn.on_click(lambda: _save_features_to_farm(state["pending_catasto"], True))
        keep_drawn_btn.on_click(
            lambda: _save_features_to_farm([state["pending_drawn"]], False) if state["pending_drawn"] else None
        )
        cancel_claim_btn.on_click(
            lambda: (_clear_candidate_layers(), setattr(hint_label, "visible", True))
        )

        def _select_plot(matched: dict[str, Any] | None, *, pan_to: bool = False) -> None:
            if state["highlight_layer"] is not None:
                m.remove_layer(state["highlight_layer"])
                state["highlight_layer"] = None

            if not matched:
                state["selected_plot"] = None
                info_container.visible = False
                remove_plot_btn.visible = False
                hint_label.visible = not claim_container.visible
                return

            state["selected_plot"] = matched
            if matched.get("geometry"):
                state["highlight_layer"] = m.generic_layer(
                    name="geoJSON",
                    args=[
                        {"type": "Feature", "geometry": matched["geometry"]},
                        {"style": {"color": "#fc3d21", "weight": 3, "fillColor": "#fc3d21", "fillOpacity": 0.30}},
                    ],
                )

            area_ha = matched.get("area_ha") or 0.0
            wc_cls = matched.get("worldcover_class")
            wc_lbl = matched.get("worldcover_label") or "Custom Area"
            st = _style_for_class(wc_cls)
            rot = matched.get("baseline_rotation") or []
            c = matched.get("centroid") or {}
            sub_plots = matched.get("sub_plots") or []
            ref_text = matched.get("cadastral_ref") or "Custom drawn polygon"
            if len(sub_plots) > 1:
                ref_text = f"{len(sub_plots)} Catasto sub-plots · {ref_text}"

            plot_name_label.set_text(matched.get("label") or "Plot")
            plot_ref_label.set_text(ref_text)
            area_val.set_text(f"{area_ha:.4f} ha ({round(area_ha * 10_000):,} m²)")
            landcover_icon.props(f"name={st['icon']} color={st['text_color']}")
            landcover_val.set_text(f"{wc_lbl}" + (f" ({wc_cls})" if wc_cls else ""))
            rotation_val.set_text(" → ".join(rot) if rot else "-")
            centroid_val.set_text(f"{c['lat']:.5f}, {c['lon']:.5f}" if "lat" in c else "-")

            remove_plot_btn.visible = is_farm_owner(state["current_farm"], current_user) and state["edit_mode"]
            hint_label.visible = False
            info_container.visible = True

            if pan_to and isinstance(c, dict) and "lat" in c and "lon" in c:
                m.set_center((c["lat"], c["lon"]))
                m.set_zoom(16)

        async def on_map_click(e: Any) -> None:
            latlng = e.args.get("latlng") if isinstance(e.args, dict) else None
            if not latlng:
                return
            lat = float(latlng["lat"])
            lon = float(latlng["lng"])

            matched = next(
                (p for p in state["plots"] if p.get("geometry") and point_in_geojson_geometry(lat, lon, p["geometry"])),
                None,
            )
            _select_plot(matched, pan_to=False)

        m.on("map-click", on_map_click)

        def on_remove_plot() -> None:
            plot = state["selected_plot"]
            farm = state["current_farm"]
            if not plot or not farm or not is_farm_owner(farm, current_user):
                return

            plot_name = plot.get("label") or "this plot"
            area_ha = float(plot.get("area_ha") or 0.0)
            with ui.dialog() as confirm_dlg, ui.card().classes("w-96 p-5 gap-3"):
                ui.label("Remove Plot from Farm?").classes("text-base font-bold text-negative")
                ui.label(
                    f"Are you sure you want to delete '{plot_name}' ({area_ha:.2f} ha)? "
                    "Its cached NASA snapshot, overrides, and saved plan will be permanently removed."
                ).classes("text-xs text-gray-700")
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button("Cancel", on_click=confirm_dlg.close).props("flat dense")

                    async def _confirm_delete() -> None:
                        confirm_dlg.close()
                        await store.remove_plot(plot["id"], user=current_user)
                        await load_selected_farm(farm["id"])
                        ui.notify(f"Removed '{plot_name}'", type="info")

                    ui.button("Delete Plot", icon="delete", color="negative", on_click=_confirm_delete).props("dense")

            confirm_dlg.open()

        remove_plot_btn.on_click(on_remove_plot)

        ui.timer(0.05, lambda: load_selected_farm(state["current_farm"]["id"] if state["current_farm"] else None), once=True)
