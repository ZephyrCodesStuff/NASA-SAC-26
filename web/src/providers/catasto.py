"""Agenzia delle Entrate Italian Cadastral (Catasto) WMS & WFS client.

Interfaces with the official OGC INSPIRE services published under CC BY 4.0:
- WMS (raster tiles & GetFeatureInfo):
  https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php
- WFS (vector GML 3.2 parcels & zoning):
  https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php

Key protocol details (verified against service capabilities & documentation):
- Coordinate Reference System: EPSG:6706 (RDN2008 / ETRS89), axis order `lat lon`.
- WFS ignores GeoJSON outputFormat and returns GML 3.2 XML; `<gml:posList>` pairs
  are swapped from `(lat, lon)` to GeoJSON `[lon, lat]`.
- WFS enforces Vertical Distance (Vdist) limits on BBOX:
  * `CP:CadastralParcel`: Vdist < 2,000 m
  * `CP:CadastralZoning`: Vdist < 8,000 m
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode

import httpx

WMS_URL = "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php"
WFS_URL = "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

CRS_RDN2008 = "EPSG:6706"
ATTRIBUTION = "Agenzia delle Entrate - Cartografia Catastale (CC BY 4.0)"

# WFS Vertical Distance (Vdist) limits in meters (from official WFS spec)
MAX_PARCEL_VDIST_M = 2000.0
MAX_ZONING_VDIST_M = 8000.0
DEFAULT_BBOX_DELTA = 0.0040  # ~890 m Vdist at 45°N: fetches clicked + ~100-150 nearby parcels in 1 call

# Rough bounding box for Italy (excluding Trento/Bolzano which use autonomous catasto)
ITALY_BOUNDS = (35.4, 6.6, 47.1, 18.6)

# XML namespaces used by AdE WFS 2.0.0 / GML 3.2
NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "cp": "http://mapserver.gis.umn.edu/mapserver",
    "ows": "http://www.opengis.net/ows/1.1",
}


class WMSLayers:
    """Layer names exposed by the AdE Catasto WMS 1.3.0 service."""

    ROOT = "Cartografia_Catastale"
    CADASTRAL_PARCEL = "CP.CadastralParcel"
    CADASTRAL_ZONING = "CP.CadastralZoning"
    FABBRICATI = "fabbricati"
    ACQUE = "acque"
    STRADE = "strade"
    VESTIZIONI = "vestizioni"
    PROVINCE = "province"


class WFSLayers:
    """FeatureType names exposed by the AdE Catasto WFS 2.0.0 service."""

    CADASTRAL_PARCEL = "CP:CadastralParcel"
    CADASTRAL_ZONING = "CP:CadastralZoning"


@dataclass(frozen=True, slots=True)
class TurinPreset:
    """Named Turin-area reference location with Belfiore cadastral code."""

    key: str
    name: str
    belfiore_code: str
    lat: float
    lon: float
    description: str


TURIN_PRESETS: dict[str, TurinPreset] = {
    "torino_centro": TurinPreset(
        key="torino_centro",
        name="Torino Centro",
        belfiore_code="L219",
        lat=45.0703,
        lon=7.6869,
        description="Comune di Torino (L219) urban center",
    ),
    "torino_stura_farmland": TurinPreset(
        key="torino_stura_farmland",
        name="Torino Nord / Stura Farmland",
        belfiore_code="L219",
        lat=45.1185,
        lon=7.7160,
        description="Peri-urban agricultural parcels in northern Torino (L219)",
    ),
    "carmagnola_po_valley": TurinPreset(
        key="carmagnola_po_valley",
        name="Carmagnola (Po Valley)",
        belfiore_code="B791",
        lat=44.8467,
        lon=7.7178,
        description="Irrigated Po Valley arable farmland south of Turin (B791)",
    ),
    "chieri": TurinPreset(
        key="chieri",
        name="Chieri Hills",
        belfiore_code="C627",
        lat=45.0139,
        lon=7.8225,
        description="Hillside mixed crops & vineyards east of Turin (C627)",
    ),
    "settimo_torinese": TurinPreset(
        key="settimo_torinese",
        name="Settimo Torinese",
        belfiore_code="I703",
        lat=45.1408,
        lon=7.7703,
        description="Po plain agricultural belt northeast of Turin (I703)",
    ),
}


class CatastoError(RuntimeError):
    """Raised when the AdE Catasto WMS/WFS service returns an error."""


# ---------------------------------------------------------------------------
# Pure geometry & cadastral reference helpers
# ---------------------------------------------------------------------------


def is_in_italy(lat: float, lon: float) -> bool:
    """Return True if coordinates fall within Italy's rough bounding box."""
    min_lat, min_lon, max_lat, max_lon = ITALY_BOUNDS
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def estimate_bbox_vdist_meters(min_lat: float, max_lat: float) -> float:
    """Estimate vertical distance (north-south span) of a lat/lon BBOX in meters."""
    return abs(max_lat - min_lat) * 111_320.0


def validate_wfs_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    layer: str = WFSLayers.CADASTRAL_PARCEL,
) -> None:
    """Validate that BBOX is well-ordered and within the AdE WFS Vdist threshold."""
    if min_lat >= max_lat or min_lon >= max_lon:
        raise ValueError(
            f"Invalid BBOX ({min_lat}, {min_lon}, {max_lat}, {max_lon}): "
            "min must be strictly less than max."
        )
    vdist = estimate_bbox_vdist_meters(min_lat, max_lat)
    limit = MAX_ZONING_VDIST_M if layer == WFSLayers.CADASTRAL_ZONING else MAX_PARCEL_VDIST_M
    if vdist >= limit:
        raise ValueError(
            f"BBOX vertical distance (~{vdist:.0f} m) exceeds WFS limit for {layer} "
            f"({limit:.0f} m). Reduce the latitude span."
        )


def parse_cadastral_reference(ref: str | None) -> dict[str, str | None]:
    """Parse an Italian NATIONALCADASTRALREFERENCE like 'B791_011500.1'.

    Format: `<BelfioreCode>_<Foglio4><Sezione/Allegato2>[.<Particella>]`
    """
    if not ref:
        return {"belfiore_code": None, "foglio": None, "sezione": None, "particella": None}

    code_part, _, particella = ref.partition(".")
    belfiore, _, sheet_part = code_part.partition("_")
    foglio = sheet_part[:4] if len(sheet_part) >= 4 else (sheet_part or None)
    sezione = sheet_part[4:] if len(sheet_part) > 4 else None
    return {
        "belfiore_code": belfiore or None,
        "foglio": foglio,
        "sezione": sezione,
        "particella": particella or None,
    }


def _ring_area_m2(ring: Sequence[Sequence[float]]) -> float:
    """Approximate planar area in m² for a GeoJSON [lon, lat] ring."""
    if len(ring) < 3:
        return 0.0
    mean_lat = sum(pt[1] for pt in ring) / len(ring)
    m_per_deg_lat = 111_132.95
    m_per_deg_lon = 111_412.84 * math.cos(math.radians(mean_lat))

    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0] * m_per_deg_lon, ring[i][1] * m_per_deg_lat
        x2, y2 = ring[i + 1][0] * m_per_deg_lon, ring[i + 1][1] * m_per_deg_lat
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def compute_geometry_area_ha(geometry: dict[str, Any]) -> float:
    """Compute area in hectares (ha) for a GeoJSON Polygon or MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    total_m2 = 0.0

    if gtype == "Polygon" and coords:
        total_m2 += _ring_area_m2(coords[0])
        for hole in coords[1:]:
            total_m2 -= _ring_area_m2(hole)
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                total_m2 += _ring_area_m2(poly[0])
                for hole in poly[1:]:
                    total_m2 -= _ring_area_m2(hole)

    return round(max(total_m2, 0.0) / 10_000.0, 4)


def compute_geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Return approximate (lat, lon) centroid from the first exterior ring."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    ring: Sequence[Sequence[float]] = []

    if gtype == "Polygon" and coords:
        ring = coords[0]
    elif gtype == "MultiPolygon" and coords and coords[0]:
        ring = coords[0][0]

    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not pts:
        return None
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return round(lat, 7), round(lon, 7)


def _point_in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray-casting point-in-ring check on [lon, lat] coordinates."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_geojson_geometry(lat: float, lon: float, geometry: dict[str, Any]) -> bool:
    """Return True if (lat, lon) lies inside a GeoJSON Polygon or MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []

    def _in_poly(rings: Sequence[Sequence[Sequence[float]]]) -> bool:
        if not rings or not _point_in_ring(lon, lat, rings[0]):
            return False
        return not any(_point_in_ring(lon, lat, hole) for hole in rings[1:])

    if gtype == "Polygon":
        return _in_poly(coords)
    if gtype == "MultiPolygon":
        return any(_in_poly(poly) for poly in coords)
    return False


# ---------------------------------------------------------------------------
# GML 3.2 -> GeoJSON parser
# ---------------------------------------------------------------------------


def _parse_pos_list(text: str | None) -> list[list[float]]:
    """Parse GML `<gml:posList>` (lat lon pairs in EPSG:6706) into GeoJSON [lon, lat]."""
    if not text:
        return []
    tokens = text.strip().split()
    coords: list[list[float]] = []
    for i in range(0, len(tokens) - 1, 2):
        lat = float(tokens[i])
        lon = float(tokens[i + 1])
        coords.append([lon, lat])
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def _parse_gml_polygon(poly_el: ET.Element) -> list[list[list[float]]]:
    """Extract exterior and interior rings from a `<gml:Polygon>` element."""
    rings: list[list[list[float]]] = []
    ext = poly_el.find("gml:exterior//gml:posList", NS)
    if ext is not None:
        ring = _parse_pos_list(ext.text)
        if ring:
            rings.append(ring)
    for interior in poly_el.findall("gml:interior//gml:posList", NS):
        ring = _parse_pos_list(interior.text)
        if ring:
            rings.append(ring)
    return rings


def _parse_gml_geometry(geom_el: ET.Element | None) -> dict[str, Any] | None:
    """Convert `<CP:msGeometry>` GML 3.2 Polygon/MultiSurface to GeoJSON geometry."""
    if geom_el is None:
        return None

    polygons = geom_el.findall(".//gml:Polygon", NS)
    if not polygons:
        return None

    parsed_polys = [rings for p in polygons if (rings := _parse_gml_polygon(p))]
    if not parsed_polys:
        return None
    if len(parsed_polys) == 1:
        return {"type": "Polygon", "coordinates": parsed_polys[0]}
    return {"type": "MultiPolygon", "coordinates": parsed_polys}


def _child_text(el: ET.Element, *names: str) -> str | None:
    """Return stripped text of the first matching `CP:<name>` child element."""
    for name in names:
        node = el.find(f"cp:{name}", NS)
        if node is not None and node.text is not None:
            val = node.text.strip()
            if val:
                return val
    return None


def parse_gml_feature_collection(
    xml_text: str,
    layer: str = WFSLayers.CADASTRAL_PARCEL,
) -> dict[str, Any]:
    """Parse an AdE WFS 2.0 GML 3.2 FeatureCollection into a GeoJSON FeatureCollection."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CatastoError(f"Failed to parse WFS GML response: {exc}") from exc

    # Check for OWS ExceptionReport
    if root.tag.endswith("ExceptionReport"):
        exc_node = root.find(".//ows:ExceptionText", NS)
        msg = exc_node.text.strip() if exc_node is not None and exc_node.text else xml_text[:300]
        raise CatastoError(f"WFS service returned ExceptionReport: {msg}")

    local_tag = layer.split(":")[-1]
    features: list[dict[str, Any]] = []

    for member in root.findall("wfs:member", NS):
        feat_el = member.find(f"cp:{local_tag}", NS)
        if feat_el is None:
            continue

        geometry = _parse_gml_geometry(feat_el.find("cp:msGeometry", NS))
        if geometry is None:
            continue

        nat_ref = _child_text(
            feat_el,
            "NATIONALCADASTRALREFERENCE",
            "NATIONALCADASTRALZONINGREFERENCE",
        )
        parsed_ref = parse_cadastral_reference(nat_ref)
        admin_unit = _child_text(feat_el, "ADMINISTRATIVEUNIT", "ADMISTRATIVEUNIT")
        centroid = compute_geometry_centroid(geometry)

        props: dict[str, Any] = {
            "gml_id": feat_el.attrib.get(f"{{{NS['gml']}}}id"),
            "inspire_id": _child_text(feat_el, "INSPIREID_LOCALID"),
            "inspire_namespace": _child_text(feat_el, "INSPIREID_NAMESPACE"),
            "label": _child_text(feat_el, "LABEL"),
            "national_ref": nat_ref,
            "administrative_unit": admin_unit or parsed_ref["belfiore_code"],
            "foglio": parsed_ref["foglio"],
            "particella": parsed_ref["particella"],
            "area_ha": compute_geometry_area_ha(geometry),
            "centroid": list(centroid) if centroid else None,
        }

        if local_tag == "CadastralZoning":
            props.update(
                {
                    "begin_lifespan": _child_text(feat_el, "BEGINLIFESPANVERSION"),
                    "end_lifespan": _child_text(feat_el, "ENDLIFESPANVERSION"),
                    "level": _child_text(feat_el, "LEVEL"),
                    "level_name": _child_text(feat_el, "LEVELNAME"),
                    "scale_denominator": _child_text(feat_el, "ORIGINALMAPSCALEDENOMINATOR"),
                }
            )

        features.append(
            {
                "type": "Feature",
                "id": props["inspire_id"] or props["gml_id"],
                "geometry": geometry,
                "properties": props,
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "layer": layer,
            "crs": "EPSG:4326",
            "source_crs": CRS_RDN2008,
            "attribution": ATTRIBUTION,
            "count": len(features),
        },
    }


# ---------------------------------------------------------------------------
# WMS URL builders & helpers (for NiceGUI ui.leaflet & raster/info queries)
# ---------------------------------------------------------------------------


def get_wms_leaflet_config(
    layers: str | Sequence[str] = WMSLayers.CADASTRAL_PARCEL,
    transparent: bool = True,
    image_format: str = "image/png",
    version: str = "1.3.0",
    min_zoom: int = 14,
    max_zoom: int = 20,
) -> dict[str, Any]:
    """Return URL and Leaflet WMS options for NiceGUI `ui.leaflet` tile overlays."""
    layer_str = layers if isinstance(layers, str) else ",".join(layers)
    return {
        "url_template": WMS_URL,
        "options": {
            "layers": layer_str,
            "format": image_format,
            "transparent": transparent,
            "version": version,
            "attribution": ATTRIBUTION,
            "minZoom": min_zoom,
            "maxZoom": max_zoom,
        },
    }


def build_wms_getmap_url(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    width: int = 512,
    height: int = 512,
    layers: str | Sequence[str] = WMSLayers.CADASTRAL_PARCEL,
    crs: str = CRS_RDN2008,
    transparent: bool = True,
    image_format: str = "image/png",
) -> str:
    """Build a WMS 1.3.0 GetMap URL. Note EPSG:6706 uses `min_lat,min_lon,max_lat,max_lon`."""
    layer_str = layers if isinstance(layers, str) else ",".join(layers)
    bbox = (
        f"{min_lat},{min_lon},{max_lat},{max_lon}"
        if crs in {CRS_RDN2008, "EPSG:4326", "EPSG:4258"}
        else f"{min_lon},{min_lat},{max_lon},{max_lat}"
    )
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer_str,
        "STYLES": "",
        "CRS": crs,
        "BBOX": bbox,
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": image_format,
        "TRANSPARENT": "TRUE" if transparent else "FALSE",
    }
    return f"{WMS_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Async WMS / WFS / OSM Overpass Client with PocketBase field_cache
# ---------------------------------------------------------------------------


DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "catasto"
_MEM_CACHE: dict[str, dict[str, Any]] = {}


def _feature_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return (min_lat, min_lon, max_lat, max_lon) for a Polygon/MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    rings: list[Sequence[Sequence[float]]] = []
    if gtype == "Polygon" and coords:
        rings = coords
    elif gtype == "MultiPolygon":
        for poly in coords:
            rings.extend(poly)
    if not rings:
        return None
    lons = [pt[0] for ring in rings for pt in ring]
    lats = [pt[1] for ring in rings for pt in ring]
    if not lons or not lats:
        return None
    return min(lats), min(lons), max(lats), max(lons)


class CatastoClient:
    """Async client for AdE Catasto WMS & WFS with permanent multi-tier caching."""

    def __init__(
        self,
        pb_url: str | None = None,
        cache_dir: Path | str | None = DEFAULT_CACHE_DIR,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.pb_url = (pb_url if pb_url is not None else os.getenv("PB_URL", "http://127.0.0.1:8090")).rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self._external_client = client
        self._client: httpx.AsyncClient | None = client
        self._parcel_index: dict[str, tuple[tuple[float, float, float, float], dict[str, Any]]] = {}
        self._disk_loaded = False

    async def __aenter__(self) -> CatastoClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @staticmethod
    def _make_cache_key(prefix: str, *parts: Any) -> str:
        raw = json.dumps([prefix, *parts], sort_keys=True, default=str)
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

    def _disk_cache_path(self, cache_key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{cache_key}.json"

    async def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        """Read from in-memory, PocketBase `field_cache`, or local disk cache."""
        if cache_key in _MEM_CACHE:
            return _MEM_CACHE[cache_key]

        if self.pb_url:
            try:
                http = await self._http()
                resp = await http.get(
                    f"{self.pb_url}/api/collections/field_cache/records",
                    params={"filter": f'cache_key="{cache_key}"', "perPage": 1},
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    items = resp.json().get("items") or []
                    if items:
                        payload = items[0].get("payload")
                        data = json.loads(payload) if isinstance(payload, str) else payload
                        if isinstance(data, dict):
                            _MEM_CACHE[cache_key] = data
                            return data
            except Exception:
                pass

        disk_path = self._disk_cache_path(cache_key)
        if disk_path is not None and disk_path.exists():
            try:
                data = json.loads(disk_path.read_text(encoding="utf-8"))
                _MEM_CACHE[cache_key] = data
                return data
            except Exception:
                pass

        return None

    async def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        """Persist immutable Catasto data to memory, disk, and PocketBase `field_cache`."""
        _MEM_CACHE[cache_key] = payload
        self._index_features(payload.get("features") or [])

        disk_path = self._disk_cache_path(cache_key)
        if disk_path is not None:
            try:
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                disk_path.write_text(json.dumps(payload), encoding="utf-8")
            except Exception:
                pass

        if self.pb_url:
            try:
                http = await self._http()
                await http.post(
                    f"{self.pb_url}/api/collections/field_cache/records",
                    json={"cache_key": cache_key, "payload": payload},
                    timeout=2.0,
                )
            except Exception:
                pass

    def _index_features(self, features: Sequence[dict[str, Any]]) -> None:
        """Add GeoJSON parcel features to the in-memory spatial index."""
        for feat in features:
            fid = feat.get("id") or (feat.get("properties") or {}).get("inspire_id")
            geom = feat.get("geometry")
            if not fid or not geom:
                continue
            bbox = _feature_bbox(geom)
            if bbox is not None:
                self._parcel_index[str(fid)] = (bbox, feat)

    def _ensure_disk_index_loaded(self) -> None:
        """Load any previously cached WFS FeatureCollections from disk into the parcel index."""
        if self._disk_loaded:
            return
        self._disk_loaded = True
        for payload in _MEM_CACHE.values():
            if (payload.get("properties") or {}).get("layer") == WFSLayers.CADASTRAL_PARCEL:
                self._index_features(payload.get("features") or [])
        if self.cache_dir is None or not self.cache_dir.exists():
            return
        for path in self.cache_dir.glob("catasto_wfs_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (data.get("properties") or {}).get("layer", WFSLayers.CADASTRAL_PARCEL) == WFSLayers.CADASTRAL_PARCEL:
                    self._index_features(data.get("features") or [])
            except Exception:
                continue

    def get_cached_parcels(self) -> list[dict[str, Any]]:
        """Return all deduplicated cached parcel GeoJSON features."""
        self._ensure_disk_index_loaded()
        return [feat for _, feat in self._parcel_index.values()]

    def find_cached_parcel_at_point(self, lat: float, lon: float) -> dict[str, Any] | None:
        """Return an already-cached parcel containing (lat, lon), or None."""
        self._ensure_disk_index_loaded()
        for (min_lat, min_lon, max_lat, max_lon), feat in self._parcel_index.values():
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                if point_in_geojson_geometry(lat, lon, feat["geometry"]):
                    return feat
        return None

    # --- WMS methods ---

    async def fetch_wms_capabilities(self) -> str:
        """Fetch raw WMS 1.3.0 GetCapabilities XML."""
        http = await self._http()
        resp = await http.get(
            WMS_URL,
            params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"},
        )
        resp.raise_for_status()
        return resp.text

    async def fetch_wms_map_image(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        width: int = 512,
        height: int = 512,
        layers: str | Sequence[str] = WMSLayers.CADASTRAL_PARCEL,
    ) -> bytes:
        """Fetch a raster PNG map tile from the AdE WMS GetMap endpoint."""
        url = build_wms_getmap_url(
            min_lat, min_lon, max_lat, max_lon, width=width, height=height, layers=layers
        )
        http = await self._http()
        resp = await http.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "xml" in content_type or "text" in content_type:
            raise CatastoError(f"WMS GetMap returned non-image response: {resp.text[:300]}")
        return resp.content

    async def fetch_wms_feature_info(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        i: int,
        j: int,
        width: int = 256,
        height: int = 256,
        layer: str = WMSLayers.CADASTRAL_PARCEL,
        info_format: str = "text/plain",
    ) -> str:
        """Query WMS GetFeatureInfo at pixel (i, j) within the given BBOX."""
        http = await self._http()
        resp = await http.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetFeatureInfo",
                "LAYERS": layer,
                "QUERY_LAYERS": layer,
                "CRS": CRS_RDN2008,
                "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
                "WIDTH": str(width),
                "HEIGHT": str(height),
                "I": str(i),
                "J": str(j),
                "INFO_FORMAT": info_format,
            },
        )
        resp.raise_for_status()
        return resp.text

    # --- WFS methods ---

    async def _fetch_wfs_features(
        self,
        layer: str,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        count: int = 100,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        validate_wfs_bbox(min_lat, min_lon, max_lat, max_lon, layer=layer)
        cache_key = self._make_cache_key(
            "catasto_wfs",
            layer,
            round(min_lat, 5),
            round(min_lon, 5),
            round(max_lat, 5),
            round(max_lon, 5),
            count,
        )
        if use_cache:
            cached = await self._read_cache(cache_key)
            if cached is not None:
                return {**cached, "_from_cache": True}

        http = await self._http()
        resp = await http.get(
            WFS_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": layer,
                "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
                "COUNT": str(count),
            },
        )
        resp.raise_for_status()
        geojson = parse_gml_feature_collection(resp.text, layer=layer)
        if use_cache and geojson["features"]:
            await self._write_cache(cache_key, geojson)
        return {**geojson, "_from_cache": False}

    async def fetch_parcels_in_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        count: int = 100,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Fetch cadastral parcels (`CP:CadastralParcel`) as a GeoJSON FeatureCollection."""
        return await self._fetch_wfs_features(
            WFSLayers.CADASTRAL_PARCEL, min_lat, min_lon, max_lat, max_lon, count=count, use_cache=use_cache
        )

    async def fetch_zoning_in_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        count: int = 50,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Fetch cadastral map sheet borders (`CP:CadastralZoning`) as GeoJSON."""
        return await self._fetch_wfs_features(
            WFSLayers.CADASTRAL_ZONING, min_lat, min_lon, max_lat, max_lon, count=count, use_cache=use_cache
        )

    async def fetch_osm_farmland_at_point(
        self,
        lat: float,
        lon: float,
        radius_m: int = 150,
    ) -> dict[str, Any]:
        """Fallback: query OpenStreetMap Overpass for farmland/meadow/orchard polygons."""
        query = (
            f'[out:json][timeout:10];'
            f'way["landuse"~"farmland|meadow|orchard|vineyard"](around:{radius_m},{lat},{lon});'
            f'out geom;'
        )
        http = await self._http()
        resp = await http.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()

        features: list[dict[str, Any]] = []
        for el in data.get("elements") or []:
            geom_pts = el.get("geometry") or []
            if len(geom_pts) < 3:
                continue
            ring = [[pt["lon"], pt["lat"]] for pt in geom_pts]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            geometry = {"type": "Polygon", "coordinates": [ring]}
            tags = el.get("tags") or {}
            centroid = compute_geometry_centroid(geometry)
            features.append(
                {
                    "type": "Feature",
                    "id": f"osm/way/{el.get('id')}",
                    "geometry": geometry,
                    "properties": {
                        "osm_id": el.get("id"),
                        "landuse": tags.get("landuse"),
                        "crop": tags.get("crop"),
                        "name": tags.get("name"),
                        "area_ha": compute_geometry_area_ha(geometry),
                        "centroid": list(centroid) if centroid else None,
                    },
                }
            )

        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {
                "layer": "osm:farmland",
                "crs": "EPSG:4326",
                "attribution": "OpenStreetMap contributors (ODbL)",
                "count": len(features),
            },
        }

    async def fetch_parcel_at_point(
        self,
        lat: float,
        lon: float,
        delta: float = DEFAULT_BBOX_DELTA,
        count: int = 150,
        use_cache: bool = True,
        osm_fallback: bool = True,
    ) -> dict[str, Any]:
        """Locate the exact cadastral parcel containing (lat, lon).

        Checks the permanent spatial parcel cache first so any click inside an
        already-fetched parcel returns immediately with zero network calls. On a
        cache miss, queries a ~1 km BBOX (`delta=0.0040`, `count=150`) via AdE WFS
        to fetch and cache the clicked parcel plus neighboring plots in one call.
        """
        if use_cache:
            cached_feat = self.find_cached_parcel_at_point(lat, lon)
            if cached_feat is not None:
                return {
                    "parcel": cached_feat,
                    "candidates": self.get_cached_parcels(),
                    "source": "ade_catasto_wfs",
                    "cached": True,
                    "attribution": ATTRIBUTION,
                }

        candidates: list[dict[str, Any]] = []
        source = "ade_catasto_wfs"
        from_cache = False

        if is_in_italy(lat, lon):
            fc = await self.fetch_parcels_in_bbox(
                lat - delta,
                lon - delta,
                lat + delta,
                lon + delta,
                count=count,
                use_cache=use_cache,
            )
            candidates = fc["features"]
            self._index_features(candidates)
            from_cache = bool(fc.get("_from_cache", False))
            for feat in candidates:
                if point_in_geojson_geometry(lat, lon, feat["geometry"]):
                    return {
                        "parcel": feat,
                        "candidates": candidates,
                        "source": source,
                        "cached": from_cache,
                        "attribution": ATTRIBUTION,
                    }

        if osm_fallback and not candidates:
            osm_fc = await self.fetch_osm_farmland_at_point(lat, lon)
            candidates = osm_fc["features"]
            source = "osm_overpass"
            for feat in candidates:
                if point_in_geojson_geometry(lat, lon, feat["geometry"]):
                    return {
                        "parcel": feat,
                        "candidates": candidates,
                        "source": source,
                        "cached": False,
                        "attribution": "OpenStreetMap contributors (ODbL)",
                    }

        return {
            "parcel": candidates[0] if candidates else None,
            "candidates": candidates,
            "source": source,
            "cached": from_cache,
            "attribution": ATTRIBUTION if source == "ade_catasto_wfs" else "OpenStreetMap contributors (ODbL)",
        }
