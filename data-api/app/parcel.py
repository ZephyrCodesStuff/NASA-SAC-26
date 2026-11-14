"""Parse Italian cadastre (Agenzia delle Entrate INSPIRE WFS) GML into parcel geometries."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from lxml import etree
from pyproj import CRS, Geod, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.geometry.base import BaseGeometry
import shapely

GML = "http://www.opengis.net/gml/3.2"
NS = {"gml": GML}
_GEOD = Geod(ellps="WGS84")


class ParcelParseError(ValueError):
    pass


@dataclass
class Parcel:
    id: str
    geometry: BaseGeometry  # WGS84, lon/lat (x=lon, y=lat)
    attributes: dict = field(default_factory=dict)

    @property
    def centroid(self) -> tuple[float, float]:
        """(lat, lon) of a point guaranteed to be inside the parcel."""
        p = self.geometry.representative_point() if not self.geometry.centroid.within(self.geometry) else self.geometry.centroid
        return p.y, p.x

    @property
    def area_ha(self) -> float:
        return abs(_GEOD.geometry_area_perimeter(self.geometry)[0]) / 10_000

    def summary(self) -> dict:
        lat, lon = self.centroid
        minx, miny, maxx, maxy = self.geometry.bounds
        return {
            "id": self.id,
            **self.attributes,
            "area_ha": round(self.area_ha, 4),
            "centroid": {"lat": round(lat, 6), "lon": round(lon, 6)},
            "bbox": [round(v, 6) for v in (minx, miny, maxx, maxy)],
            "geometry": mapping(self.geometry),
        }


def _crs_from_srs_name(name: str | None) -> CRS:
    if not name:
        return CRS.from_epsg(6706)  # cadastre default
    m = re.search(r"EPSG(?::+|/0/|/)(\d+)", name, re.I)
    if not m:
        raise ParcelParseError(f"Unrecognised srsName: {name}")
    return CRS.from_epsg(int(m.group(1)))


def _to_wgs84(geom: BaseGeometry, crs: CRS) -> BaseGeometry:
    # Coordinates are in the CRS's authority axis order (EPSG:6706 => lat, lon).
    # OGC:CRS84 output is always lon, lat.
    t = Transformer.from_crs(crs, "OGC:CRS84")
    return shapely.transform(geom, lambda x, y: t.transform(x, y), interleaved=False)


def _ring(el, dim: int) -> list[tuple[float, float]]:
    pos_list = el.find(".//gml:posList", NS)
    if pos_list is not None:
        dim = int(pos_list.get("srsDimension") or dim)
        nums = [float(v) for v in pos_list.text.split()]
    else:
        nums = [float(v) for p in el.iterfind(".//gml:pos", NS) for v in p.text.split()[:2]]
        dim = 2
    if len(nums) % dim:
        raise ParcelParseError("posList length is not a multiple of srsDimension")
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), dim)]


def _polygon(el, dim: int) -> Polygon:
    ext = el.find("gml:exterior", NS)
    if ext is None:
        raise ParcelParseError("Polygon without exterior ring")
    holes = [_ring(i, dim) for i in el.iterfind("gml:interior", NS)]
    return Polygon(_ring(ext, dim), holes)


def _geometry(member) -> tuple[BaseGeometry, CRS]:
    polys = member.findall(".//gml:Polygon", NS)
    if not polys:
        raise ParcelParseError("Parcel has no gml:Polygon geometry")
    srs = None
    for el in [*member.iter(f"{{{GML}}}MultiSurface"), *polys]:
        srs = srs or el.get("srsName")
    shapes = [_polygon(p, 2) for p in polys]
    geom = shapes[0] if len(shapes) == 1 else MultiPolygon(shapes)
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom, _crs_from_srs_name(srs)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attributes(feature) -> dict:
    attrs = {}
    for child in feature:
        name = _local(child.tag)
        if child.text and child.text.strip() and len(child) == 0:
            attrs[name] = child.text.strip()
    ref = attrs.get("NATIONALCADASTRALREFERENCE", "")
    out = {"national_cadastral_reference": ref or None, "comune_code": attrs.get("ADMINISTRATIVEUNIT")}
    # e.g. F257_025400.121 -> comune F257, foglio 0254 (+ allegato/sviluppo "00"), particella 121
    m = re.match(r"^(\w{4})_(\d{4})(\w{2})\.(.+)$", ref)
    if m:
        out.update(comune_code=m.group(1), foglio=m.group(2), allegato=m.group(3), particella=m.group(4))
    elif attrs.get("LABEL"):
        out["particella"] = attrs["LABEL"]
    return out


def parse_cadastre_gml(xml: bytes | str) -> list[Parcel]:
    if isinstance(xml, str):
        xml = xml.encode()
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError as e:
        raise ParcelParseError(f"Invalid XML: {e}") from e

    features = [el for el in root.iter() if isinstance(el.tag, str) and _local(el.tag) == "CadastralParcel"]
    if not features:
        raise ParcelParseError("No CadastralParcel features found in the XML")

    parcels = []
    for f in features:
        geom, crs = _geometry(f)
        attrs = _attributes(f)
        pid = attrs.get("national_cadastral_reference") or f.get(f"{{{GML}}}id") or f"parcel-{len(parcels) + 1}"
        parcels.append(Parcel(id=pid, geometry=_to_wgs84(geom, crs), attributes=attrs))
    return parcels


def point_parcel(lat: float, lon: float, half_size_m: float = 15.0) -> Parcel:
    """A small square around a point, for testing or non-cadastre callers."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ParcelParseError("lat/lon out of range")
    dlat = half_size_m / 111_320
    dlon = half_size_m / (111_320 * max(0.01, abs(math.cos(math.radians(lat)))))
    return Parcel(id=f"point:{lat:.6f},{lon:.6f}", geometry=box(lon - dlon, lat - dlat, lon + dlon, lat + dlat), attributes={})


def parse_geojson(obj: dict) -> list[Parcel]:
    """Parcels from GeoJSON (Feature, FeatureCollection or bare Polygon/MultiPolygon), WGS84 [lon, lat].

    Matches what web/src/providers/catasto.py produces (feature id = INSPIRE local id, properties may
    carry belfiore_code / foglio / particella).
    """
    from shapely.geometry import shape

    if not isinstance(obj, dict) or "type" not in obj:
        raise ParcelParseError("Body must be a GeoJSON object")
    t = obj["type"]
    if t == "FeatureCollection":
        feats = obj.get("features") or []
    elif t == "Feature":
        feats = [obj]
    elif t in ("Polygon", "MultiPolygon"):
        feats = [{"type": "Feature", "geometry": obj, "properties": {}}]
    else:
        raise ParcelParseError(f"Unsupported GeoJSON type: {t}")

    parcels = []
    for n, f in enumerate(feats, 1):
        g = f.get("geometry")
        if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
            continue  # skip points/lines
        try:
            geom = shape(g)
        except Exception as e:  # noqa: BLE001
            raise ParcelParseError(f"Invalid geometry in feature {n}: {e}") from e
        if not geom.is_valid:
            geom = geom.buffer(0)
        minx, miny, maxx, maxy = geom.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise ParcelParseError("Coordinates must be WGS84 [lon, lat]")
        props = f.get("properties") or {}
        attrs = {k: props.get(k) for k in ("belfiore_code", "foglio", "sezione", "particella", "national_cadastral_reference", "source")
                 if props.get(k) is not None}
        pid = str(f.get("id") or props.get("id") or props.get("national_cadastral_reference") or f"parcel-{n}")
        parcels.append(Parcel(id=pid, geometry=geom, attributes=attrs))
    if not parcels:
        raise ParcelParseError("No Polygon/MultiPolygon features found")
    return parcels
