from pathlib import Path

import pytest

from app.parcel import ParcelParseError, parse_cadastre_gml, point_parcel

SAMPLE = (Path(__file__).parent / "fixtures" / "catasto_modena.xml").read_bytes()


def test_parses_all_parcels_with_ids():
    parcels = parse_cadastre_gml(SAMPLE)
    assert [p.id for p in parcels] == ["F257_025400.121", "F257_025400.124"]
    a = parcels[0].attributes
    assert (a["comune_code"], a["foglio"], a["allegato"], a["particella"]) == ("F257", "0254", "00", "121")


def test_axis_order_is_converted_to_lon_lat():
    p = parse_cadastre_gml(SAMPLE)[0]
    lat, lon = p.centroid
    # Modena: lat ~44.60, lon ~11.00 (GML gives lat first; must not be swapped)
    assert 44.59 < lat < 44.61 and 10.99 < lon < 11.01
    minx, miny, maxx, maxy = p.geometry.bounds
    assert 10.99 < minx < maxx < 11.01 and 44.59 < miny < maxy < 44.61


def test_area_is_plausible():
    p = parse_cadastre_gml(SAMPLE)[0]
    assert 1.0 < p.area_ha < 2.5


def test_rejects_non_cadastre_xml():
    with pytest.raises(ParcelParseError):
        parse_cadastre_gml(b"<foo/>")
    with pytest.raises(ParcelParseError):
        parse_cadastre_gml(b"not xml")


def test_point_parcel():
    p = point_parcel(44.6, 11.0)
    lat, lon = p.centroid
    assert abs(lat - 44.6) < 1e-9 and abs(lon - 11.0) < 1e-9
    assert 0.07 < p.area_ha < 0.11  # 30 m square
    with pytest.raises(ParcelParseError):
        point_parcel(95, 0)


def test_geojson_feature_collection_like_web_catasto_provider():
    from app.parcel import parse_geojson

    gml_parcel = parse_cadastre_gml(SAMPLE)[0]
    from shapely.geometry import mapping

    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "IT.AGE.PLA.F257_025400.121", "geometry": mapping(gml_parcel.geometry),
         "properties": {"belfiore_code": "F257", "foglio": "0254", "particella": "121"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11, 44.6]}, "properties": {}},
    ]}
    [p] = parse_geojson(fc)
    assert p.id == "IT.AGE.PLA.F257_025400.121"
    assert p.attributes["particella"] == "121"
    assert abs(p.area_ha - gml_parcel.area_ha) < 1e-6


def test_geojson_rejects_lat_lon_swapped_or_empty():
    from app.parcel import parse_geojson

    with pytest.raises(ParcelParseError):
        parse_geojson({"type": "FeatureCollection", "features": []})
    with pytest.raises(ParcelParseError):
        parse_geojson({"type": "Polygon", "coordinates": [[[44.6, 200], [44.7, 200], [44.7, 201], [44.6, 200]]]})
