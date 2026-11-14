"""Interactive Leaflet map with Agenzia delle Entrate Catasto WMS & WFS parcel picker."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from src.providers.catasto import (
    DEFAULT_BBOX_DELTA,
    TURIN_PRESETS,
    CatastoClient,
    WMSLayers,
    get_wms_leaflet_config,
)

# Common Turin-area Belfiore codes -> human-readable Comune names
BELFIORE_NAMES: dict[str, str] = {
    "L219": "Torino",
    "B791": "Carmagnola",
    "C627": "Chieri",
    "I703": "Settimo Torinese",
    "F335": "Moncalieri",
    "D062": "Collegno",
    "H355": "Rivoli",
    "E024": "Grugliasco",
    "F955": "Nichelino",
    "G090": "Orbassano",
}


async def build_catasto_map_picker(
    catasto_client: CatastoClient | None = None,
    default_preset: str = "torino_stura_farmland",
) -> None:
    """Render a full-viewport Leaflet map with an overlaid Catasto parcel info card."""
    client = catasto_client or CatastoClient()
    preset = TURIN_PRESETS.get(default_preset) or TURIN_PRESETS["torino_stura_farmland"]

    state: dict[str, Any] = {
        "cached_layer": None,
        "highlight_layer": None,
        "wms_layer": None,
        "selected_parcel": None,
    }

    with ui.element("div").classes("relative w-full h-[calc(100vh-80px)] min-h-[540px]"):
        m = ui.leaflet(center=(preset.lat, preset.lon), zoom=16).classes("w-full h-full z-0")

        # Top-left overlaid controls: Turin area switcher + WMS toggle
        with ui.card().classes(
            "absolute top-3 left-14 z-[1000] p-3 bg-white/95 backdrop-blur shadow-md gap-2 w-72"
        ):
            ui.label("Turin Catasto Explorer").classes("text-sm font-bold text-primary")
            preset_options = {k: f"{v.name} ({v.belfiore_code})" for k, v in TURIN_PRESETS.items()}

            def on_preset_change(e: Any) -> None:
                selected = TURIN_PRESETS.get(e.value)
                if selected:
                    m.set_center((selected.lat, selected.lon))
                    m.set_zoom(16)

            ui.select(
                options=preset_options,
                value=preset.key,
                label="Jump to Turin area",
                on_change=on_preset_change,
            ).props("dense outlined").classes("w-full")

            wms_toggle = ui.switch("Show Catasto WMS lines", value=True).props("dense")
            cached_count_label = ui.label("Cached parcels: 0").classes("text-xs text-gray-600")

        # Top-right overlaid parcel info card
        with ui.card().classes(
            "absolute top-3 right-3 z-[1000] p-4 bg-white/95 backdrop-blur shadow-lg w-80 max-h-[calc(100%-24px)] overflow-y-auto"
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Selected Parcel").classes("text-base font-bold text-primary")
                status_badge = ui.badge("Click map", color="grey")

            hint_label = ui.label(
                "Click any parcel inside the Catasto overlay to fetch and cache its boundary."
            ).classes("text-xs text-gray-600")

            info_container = ui.column().classes("w-full gap-1.5 mt-1")
            info_container.visible = False

            with info_container:
                ref_label = ui.label("").classes("text-lg font-mono font-bold text-gray-900")
                comune_label = ui.label("").classes("text-sm text-gray-700")
                ui.separator()
                with ui.grid(columns=2).classes("w-full gap-y-1 gap-x-2 text-xs"):
                    ui.label("Foglio").classes("text-gray-500")
                    foglio_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Particella").classes("text-gray-500")
                    particella_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Area").classes("text-gray-500")
                    area_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Centroid").classes("text-gray-500")
                    centroid_val = ui.label("-").classes("font-mono text-right")

                    ui.label("Source").classes("text-gray-500")
                    source_val = ui.label("-").classes("text-right")

                inspire_label = ui.label("").classes("text-[11px] font-mono text-gray-500 break-all mt-1")

        # Wait for Leaflet initialization before adding WMS or GeoJSON layers
        await m.initialized()

        wms_cfg = get_wms_leaflet_config(
            layers=[WMSLayers.CADASTRAL_PARCEL, WMSLayers.FABBRICATI],
            transparent=True,
            min_zoom=14,
            max_zoom=20,
        )
        state["wms_layer"] = m.wms_layer(**wms_cfg)

        def refresh_cached_layer() -> None:
            cached_feats = client.get_cached_parcels()
            cached_count_label.set_text(f"Cached parcels: {len(cached_feats)}")
            if state["cached_layer"] is not None:
                m.remove_layer(state["cached_layer"])
                state["cached_layer"] = None
            if cached_feats:
                fc = {"type": "FeatureCollection", "features": cached_feats}
                state["cached_layer"] = m.generic_layer(
                    name="geoJSON",
                    args=[
                        fc,
                        {
                            "style": {
                                "color": "#0b3d91",
                                "weight": 1.5,
                                "fillColor": "#3b82f6",
                                "fillOpacity": 0.10,
                            }
                        },
                    ],
                )

        refresh_cached_layer()

        def on_wms_toggle(e: Any) -> None:
            if e.value and state["wms_layer"] is None:
                state["wms_layer"] = m.wms_layer(**wms_cfg)
            elif not e.value and state["wms_layer"] is not None:
                m.remove_layer(state["wms_layer"])
                state["wms_layer"] = None

        wms_toggle.on_value_change(on_wms_toggle)

        async def on_map_click(e: Any) -> None:
            latlng = e.args.get("latlng") if isinstance(e.args, dict) else None
            if not latlng:
                return
            lat = float(latlng["lat"])
            lon = float(latlng["lng"])

            search_circle = None
            is_cached_hit = client.find_cached_parcel_at_point(lat, lon) is not None
            if not is_cached_hit:
                status_badge.set_text("Searching area...")
                status_badge.props("color=amber")
                search_circle = m.generic_layer(
                    name="circle",
                    args=[
                        [lat, lon],
                        {
                            "radius": round(DEFAULT_BBOX_DELTA * 111_320),
                            "color": "#f59e0b",
                            "weight": 2,
                            "dashArray": "6, 6",
                            "fillColor": "#fbbf24",
                            "fillOpacity": 0.12,
                        },
                    ],
                )

            try:
                result = await client.fetch_parcel_at_point(lat, lon, use_cache=True)
            except Exception as exc:
                status_badge.set_text("Error")
                status_badge.props("color=negative")
                hint_label.set_text(f"Catasto lookup failed: {exc}")
                hint_label.visible = True
                return
            finally:
                if search_circle is not None:
                    m.remove_layer(search_circle)

            parcel = result.get("parcel")
            if state["highlight_layer"] is not None:
                m.remove_layer(state["highlight_layer"])
                state["highlight_layer"] = None

            if not parcel:
                status_badge.set_text("No parcel")
                status_badge.props("color=grey")
                info_container.visible = False
                hint_label.set_text(f"No parcel found near ({lat:.5f}, {lon:.5f}). Try zooming in.")
                hint_label.visible = True
                return

            if not result.get("cached"):
                refresh_cached_layer()

            state["selected_parcel"] = parcel
            state["highlight_layer"] = m.generic_layer(
                name="geoJSON",
                args=[
                    parcel,
                    {
                        "style": {
                            "color": "#fc3d21",
                            "weight": 3,
                            "fillColor": "#fc3d21",
                            "fillOpacity": 0.25,
                        }
                    },
                ],
            )

            props = parcel.get("properties") or {}
            belfiore = props.get("administrative_unit") or "-"
            comune_name = BELFIORE_NAMES.get(belfiore, "Comune")
            area_ha = props.get("area_ha") or 0.0
            area_m2 = round(area_ha * 10_000)
            centroid = props.get("centroid")

            ref_label.set_text(props.get("national_ref") or props.get("label") or "Parcel")
            comune_label.set_text(f"{comune_name} ({belfiore})")
            foglio_val.set_text(str(props.get("foglio") or "-"))
            particella_val.set_text(str(props.get("particella") or props.get("label") or "-"))
            area_val.set_text(f"{area_ha:.4f} ha ({area_m2:,} m²)")
            centroid_val.set_text(
                f"{centroid[0]:.5f}, {centroid[1]:.5f}" if centroid else f"{lat:.5f}, {lon:.5f}"
            )
            source_val.set_text("Catasto WFS" if result["source"] == "ade_catasto_wfs" else "OSM Fallback")
            inspire_label.set_text(f"INSPIRE: {props.get('inspire_id') or '-'}")

            is_cached = bool(result.get("cached"))
            status_badge.set_text("Cached" if is_cached else "Live WFS")
            status_badge.props(f"color={'positive' if is_cached else 'primary'}")

            hint_label.visible = False
            info_container.visible = True

        m.on("map-click", on_map_click)
