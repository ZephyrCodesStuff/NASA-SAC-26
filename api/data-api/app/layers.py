"""NASA GIBS map layers for the web map (Leaflet tile URL templates) — precipitation, soil moisture, NDVI,
temperature, true colour, HLS 30 m imagery, shaded relief. Tiles come straight from NASA; no proxy needed."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .core import _http, ttl_cache

CAPS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
NS = {"w": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1", "xlink": "http://www.w3.org/1999/xlink"}

# our key -> (GIBS identifier, group, description)
LAYERS = {
    "true_color_hls_sentinel2": ("HLS_S30_Nadir_BRDF_Adjusted_Reflectance", "imagery", "HLS Sentinel-2 true colour, 30 m (zoom ≤ 12)"),
    "true_color_hls_landsat": ("HLS_L30_Nadir_BRDF_Adjusted_Reflectance", "imagery", "HLS Landsat true colour, 30 m (zoom ≤ 12)"),
    "true_color_modis": ("MODIS_Terra_CorrectedReflectance_TrueColor", "imagery", "MODIS Terra true colour, daily, 250 m"),
    "false_color_modis_721": ("MODIS_Terra_CorrectedReflectance_Bands721", "imagery", "MODIS bands 7-2-1: vegetation green, burn scars/bare red, water blue"),
    "precipitation": ("IMERG_Precipitation_Rate", "water", "GPM IMERG precipitation rate (mm/h), daily"),
    "soil_moisture_rootzone": ("SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", "water", "SMAP L4 root-zone soil moisture, 9 km"),
    "surface_water": ("OPERA_L3_Dynamic_Surface_Water_Extent-HLS", "water", "OPERA surface water extent from HLS, 30 m"),
    "groundwater_anomaly": ("GRACE_Tellus_Liquid_Water_Equivalent_Thickness_Mascon_CRI", "water", "GRACE water storage anomaly, monthly"),
    "ndvi_modis_16day": ("MODIS_Terra_L3_NDVI_16Day", "vegetation", "MODIS NDVI 16-day, 250 m"),
    "ndvi_viirs_8day": ("VIIRS_SNPP_NDVI_8Day", "vegetation", "VIIRS NDVI 8-day, 500 m"),
    "leaf_area_index": ("MODIS_Combined_L4_LAI_4Day", "vegetation", "MODIS leaf area index, 4-day, 500 m"),
    "land_surface_temp_day": ("MODIS_Terra_Land_Surface_Temp_Day", "temperature", "MODIS daytime land-surface temperature, 1 km"),
    "shaded_relief_color": ("ASTER_GDEM_Color_Shaded_Relief", "terrain", "ASTER GDEM colour shaded relief (altitude), 30 m"),
    "shaded_relief_grey": ("ASTER_GDEM_Greyscale_Shaded_Relief", "terrain", "ASTER GDEM greyscale shaded relief, 30 m"),
}


@ttl_cache(12 * 3600)
def _capabilities() -> dict:
    root = ET.fromstring(_http.get(CAPS, timeout=120).raise_for_status().content)
    wanted = {v[0] for v in LAYERS.values()}
    out = {}
    for L in root.iter(f"{{{NS['w']}}}Layer"):
        ident = L.find("ows:Identifier", NS).text
        if ident not in wanted:
            continue
        tms = L.find("w:TileMatrixSetLink/w:TileMatrixSet", NS).text
        fmt = L.find("w:Format", NS).text
        dim = L.find("w:Dimension", NS)
        legend = next((e.get(f"{{{NS['xlink']}}}href") for e in L.iter(f"{{{NS['w']}}}LegendURL")
                       if e.get(f"{{{NS['xlink']}}}href", "").endswith(".png")), None)
        out[ident] = {"tile_matrix_set": tms, "ext": "jpg" if "jpeg" in fmt else "png",
                      "default_time": dim.find("w:Default", NS).text if dim is not None else None,
                      "max_zoom": int(tms.rsplit("Level", 1)[-1]) if "Level" in tms else 9, "legend": legend}
    return out


def layers() -> dict:
    caps = _capabilities()
    out = {}
    for key, (ident, group, desc) in LAYERS.items():
        c = caps.get(ident)
        if not c:
            continue
        time = "{time}/" if c["default_time"] else ""
        out[key] = {
            "group": group, "description": desc, "gibs_layer": ident,
            "url": f"{BASE}/{ident}/default/{time}{c['tile_matrix_set']}/{{z}}/{{y}}/{{x}}.{c['ext']}",
            "default_time": c["default_time"], "max_native_zoom": c["max_zoom"], "legend_url": c["legend"],
            "attribution": "NASA EOSDIS GIBS",
        }
    return {"layers": out, "usage": "Leaflet: L.tileLayer(url.replace('{time}', default_time), "
                                     "{maxNativeZoom: max_native_zoom, maxZoom: 18, opacity: 0.7}). "
                                     "Change {time} (YYYY-MM-DD) to browse history."}
