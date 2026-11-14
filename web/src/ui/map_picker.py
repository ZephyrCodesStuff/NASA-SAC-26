"""Interactive Leaflet map with Agenzia delle Entrate Catasto WMS & WFS parcel picker."""

from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from src.providers.catasto import (
    DEFAULT_BBOX_DELTA,
    TURIN_PRESETS,
    CatastoClient,
)
from src.providers.worldcover import WorldCoverClient

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
    20: {
        "name": "Shrubland",
        "icon": "nature",
        "text_color": "teal-8",
        "color": "#0f766e",
        "fillColor": "#2dd4bf",
        "fillOpacity": "0.14",
    },
    80: {
        "name": "Water",
        "icon": "water",
        "text_color": "blue-8",
        "color": "#1d4ed8",
        "fillColor": "#3b82f6",
        "fillOpacity": "0.18",
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

DEFAULT_LANDCOVER_STYLE: dict[str, str] = {
    "name": "Other",
    "icon": "layers",
    "text_color": "grey-7",
    "color": "#64748b",
    "fillColor": "#94a3b8",
    "fillOpacity": "0.12",
}


def _style_for_class(wc_class: int | None) -> dict[str, str]:
    if wc_class is None:
        return DEFAULT_LANDCOVER_STYLE
    return LANDCOVER_STYLES.get(wc_class, DEFAULT_LANDCOVER_STYLE)


async def build_catasto_map_picker(
    catasto_client: CatastoClient | None = None,
    worldcover_client: WorldCoverClient | None = None,
    default_preset: str = "torino_stura_farmland",
) -> None:
    """Render a full-viewport Leaflet map with an overlaid Catasto parcel info card."""
    client = catasto_client or CatastoClient()
    wc_client = worldcover_client or WorldCoverClient()
    preset = TURIN_PRESETS.get(default_preset) or TURIN_PRESETS["torino_stura_farmland"]

    state: dict[str, Any] = {
        "cached_layers": [],
        "highlight_layer": None,
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

            farmland_only_toggle = ui.switch("Farmland only (WorldCover 10m)", value=True).props("dense")
            cached_count_label = ui.label("Farmland: 0 / 0 cached").classes("text-xs text-gray-600")
            with ui.row().classes("w-full gap-3 pt-1 items-center text-[11px] text-gray-700"):
                with ui.row().classes("items-center gap-1"):
                    ui.icon("agriculture", size="14px").classes("text-amber-600")
                    ui.label("Cropland")
                with ui.row().classes("items-center gap-1"):
                    ui.icon("grass", size="14px").classes("text-green-700")
                    ui.label("Grassland")
                with ui.row().classes("items-center gap-1") as other_legend:
                    ui.icon("apartment", size="14px").classes("text-slate-500")
                    ui.label("Other")
                other_legend.visible = False

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

                    ui.label("Land Cover").classes("text-gray-500")
                    with ui.row().classes("items-center justify-end gap-1"):
                        landcover_icon = ui.icon("agriculture", size="16px").classes("text-amber-600")
                        landcover_val = ui.label("-").classes("font-semibold text-right")

                    ui.label("Source").classes("text-gray-500")
                    source_val = ui.label("-").classes("text-right")

                inspire_label = ui.label("").classes("text-[11px] font-mono text-gray-500 break-all mt-1")

        # Wait for Leaflet initialization before adding GeoJSON layers
        await m.initialized()

        async def _init_layers() -> None:
            await refresh_cached_layer()

        ui.timer(0.05, _init_layers, once=True)

        async def refresh_cached_layer() -> None:
            cached_feats = client.get_cached_parcels()
            try:
                await wc_client.classify_parcels(cached_feats)
            except Exception:
                pass

            farmland_feats = [
                f for f in cached_feats if (f.get("properties") or {}).get("is_farmland") is True
            ]
            non_farmland_feats = [
                f for f in cached_feats if (f.get("properties") or {}).get("is_farmland") is False
            ]
            cached_count_label.set_text(
                f"Farmland: {len(farmland_feats)} / {len(cached_feats)} cached"
            )
            other_legend.visible = not farmland_only_toggle.value

            for layer in state["cached_layers"]:
                m.remove_layer(layer)
            state["cached_layers"] = []

            visible_feats = farmland_feats if farmland_only_toggle.value else farmland_feats + non_farmland_feats

            # Group features by WorldCover class so each land-cover type gets its own color
            grouped: dict[int | None, list[dict[str, Any]]] = {}
            for feat in visible_feats:
                wc_cls = (feat.get("properties") or {}).get("worldcover_class")
                grouped.setdefault(wc_cls, []).append(feat)

            for wc_cls, feats in grouped.items():
                st = _style_for_class(wc_cls)
                fc = {"type": "FeatureCollection", "features": feats}
                layer = m.generic_layer(
                    name="geoJSON",
                    args=[
                        fc,
                        {
                            "style": {
                                "color": st["color"],
                                "weight": 1.5,
                                "fillColor": st["fillColor"],
                                "fillOpacity": float(st["fillOpacity"]),
                            }
                        },
                    ],
                )
                state["cached_layers"].append(layer)

            # Render a non-interactive Material icon at each visible parcel's centroid
            icon_items = []
            for feat in visible_feats:
                props = feat.get("properties") or {}
                centroid = props.get("centroid")
                if not centroid or len(centroid) != 2:
                    continue
                st = _style_for_class(props.get("worldcover_class"))
                icon_items.append(
                    {
                        "lat": centroid[0],
                        "lon": centroid[1],
                        "icon": st["icon"],
                        "color": st["color"],
                    }
                )

            ui.run_javascript(
                f"""
                (function renderIcons(attempt) {{
                    const el = getElement({m.id});
                    if (!el || !el.map || typeof L === 'undefined') {{
                        if (attempt < 20) setTimeout(() => renderIcons(attempt + 1), 100);
                        return;
                    }}
                    if (el._parcelIconLayer) {{
                        el.map.removeLayer(el._parcelIconLayer);
                    }}
                    const items = {json.dumps(icon_items)};
                    const markers = items.map(item => L.marker([item.lat, item.lon], {{
                        interactive: false,
                        icon: L.divIcon({{
                            className: '',
                            html: `<div style="width:22px;height:22px;border-radius:50%;background:rgba(255,255,255,0.9);border:1.5px solid ${{item.color}};display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(0,0,0,0.25);"><span class="material-icons" style="font-size:14px;color:${{item.color}};">${{item.icon}}</span></div>`,
                            iconSize: [22, 22],
                            iconAnchor: [11, 11],
                        }})
                    }}));
                    el._parcelIconLayer = L.layerGroup(markers).addTo(el.map);
                }})(0);
                """
            )

        async def on_farmland_toggle(_: Any) -> None:
            await refresh_cached_layer()

        farmland_only_toggle.on_value_change(on_farmland_toggle)

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

            try:
                await wc_client.classify_parcel(parcel)
            except Exception:
                pass

            if not result.get("cached"):
                await refresh_cached_layer()

            props = parcel.get("properties") or {}
            wc_label = props.get("worldcover_label") or "Unknown"
            wc_cls = props.get("worldcover_class")
            is_farm = props.get("is_farmland")

            if farmland_only_toggle.value and is_farm is False:
                status_badge.set_text("Not farmland")
                status_badge.props("color=grey")
                info_container.visible = False
                hint_label.set_text(
                    f"Excluded parcel {props.get('national_ref') or ''}: "
                    f"{wc_label} (Class {wc_cls}). Toggle off 'Farmland only' to inspect."
                )
                hint_label.visible = True
                return

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
            st = _style_for_class(wc_cls)
            landcover_icon.props(f"name={st['icon']} color={st['text_color']}")
            wc_suffix = f" ({wc_cls})" if wc_cls is not None else ""
            landcover_val.set_text(f"{wc_label}{wc_suffix}")
            inspire_label.set_text(f"INSPIRE: {props.get('inspire_id') or '-'}")

            is_cached = bool(result.get("cached"))
            status_badge.set_text("Cached" if is_cached else "Live WFS")
            status_badge.props(f"color={'positive' if is_cached else 'primary'}")

            hint_label.visible = False
            info_container.visible = True

        m.on("map-click", on_map_click)
