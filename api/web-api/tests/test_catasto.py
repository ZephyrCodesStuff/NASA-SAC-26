"""Unit tests for the Agenzia delle Entrate Catasto WMS/WFS provider."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.providers.catasto import (
    TURIN_PRESETS,
    WMS_URL,
    CatastoClient,
    WFSLayers,
    WMSLayers,
    build_wms_getmap_url,
    compute_geometry_area_ha,
    get_wms_leaflet_config,
    parse_cadastral_reference,
    parse_gml_feature_collection,
    point_in_geojson_geometry,
    validate_wfs_bbox,
)

SAMPLE_PARCEL_GML = """<?xml version='1.0' encoding="UTF-8" ?>
<wfs:FeatureCollection
   xmlns:CP="http://mapserver.gis.umn.edu/mapserver"
   xmlns:gml="http://www.opengis.net/gml/3.2"
   xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:member>
    <CP:CadastralParcel gml:id="CadastralParcel.IT.AGE.PLA.L219_124700.42">
      <CP:msGeometry>
        <gml:Polygon gml:id="CadastralParcel.IT.AGE.PLA.L219_124700.42.1" srsName="urn:ogc:def:crs:EPSG::6706">
          <gml:exterior>
            <gml:LinearRing>
              <gml:posList srsDimension="2">45.0700 7.6860 45.0700 7.6870 45.0710 7.6870 45.0710 7.6860 45.0700 7.6860</gml:posList>
            </gml:LinearRing>
          </gml:exterior>
        </gml:Polygon>
      </CP:msGeometry>
      <CP:INSPIREID_LOCALID>IT.AGE.PLA.L219_124700.42</CP:INSPIREID_LOCALID>
      <CP:INSPIREID_NAMESPACE>IT.AGE.PLA.</CP:INSPIREID_NAMESPACE>
      <CP:LABEL>42</CP:LABEL>
      <CP:NATIONALCADASTRALREFERENCE>L219_124700.42</CP:NATIONALCADASTRALREFERENCE>
      <CP:ADMINISTRATIVEUNIT>L219</CP:ADMINISTRATIVEUNIT>
    </CP:CadastralParcel>
  </wfs:member>
</wfs:FeatureCollection>
"""

SAMPLE_ZONING_GML = """<?xml version='1.0' encoding="UTF-8" ?>
<wfs:FeatureCollection
   xmlns:CP="http://mapserver.gis.umn.edu/mapserver"
   xmlns:gml="http://www.opengis.net/gml/3.2"
   xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:member>
    <CP:CadastralZoning gml:id="CadastralZoning.IT.AGE.MAP.L219_124700">
      <CP:msGeometry>
        <gml:Polygon gml:id="CadastralZoning.IT.AGE.MAP.L219_124700.1" srsName="urn:ogc:def:crs:EPSG::6706">
          <gml:exterior>
            <gml:LinearRing>
              <gml:posList srsDimension="2">45.069 7.686 45.069 7.690 45.075 7.690 45.075 7.686 45.069 7.686</gml:posList>
            </gml:LinearRing>
          </gml:exterior>
        </gml:Polygon>
      </CP:msGeometry>
      <CP:INSPIREID_LOCALID>IT.AGE.MAP.L219_124700</CP:INSPIREID_LOCALID>
      <CP:INSPIREID_NAMESPACE>IT.AGE.MAP</CP:INSPIREID_NAMESPACE>
      <CP:LABEL>1247</CP:LABEL>
      <CP:NATIONALCADASTRALZONINGREFERENCE>L219_124700</CP:NATIONALCADASTRALZONINGREFERENCE>
      <CP:BEGINLIFESPANVERSION>24/04/2025</CP:BEGINLIFESPANVERSION>
      <CP:LEVEL>3rdOrder</CP:LEVEL>
      <CP:LEVELNAME>Mappa Catastale</CP:LEVELNAME>
      <CP:ORIGINALMAPSCALEDENOMINATOR>1000</CP:ORIGINALMAPSCALEDENOMINATOR>
      <CP:ADMINISTRATIVEUNIT>L219</CP:ADMINISTRATIVEUNIT>
    </CP:CadastralZoning>
  </wfs:member>
</wfs:FeatureCollection>
"""


class CatastoTests(unittest.TestCase):
    def test_parse_parcel_gml_swaps_lat_lon_to_geojson(self) -> None:
        fc = parse_gml_feature_collection(SAMPLE_PARCEL_GML, layer=WFSLayers.CADASTRAL_PARCEL)
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertEqual(len(fc["features"]), 1)

        feat = fc["features"][0]
        self.assertEqual(feat["id"], "IT.AGE.PLA.L219_124700.42")
        self.assertEqual(feat["geometry"]["type"], "Polygon")
        first_coord = feat["geometry"]["coordinates"][0][0]
        # EPSG:6706 (45.0700, 7.6860) -> GeoJSON [7.6860, 45.0700]
        self.assertEqual(first_coord, [7.6860, 45.0700])

        props = feat["properties"]
        self.assertEqual(props["administrative_unit"], "L219")
        self.assertEqual(props["foglio"], "1247")
        self.assertEqual(props["particella"], "42")
        self.assertGreater(props["area_ha"], 0.8)
        self.assertLess(props["area_ha"], 1.0)

    def test_parse_zoning_gml(self) -> None:
        fc = parse_gml_feature_collection(SAMPLE_ZONING_GML, layer=WFSLayers.CADASTRAL_ZONING)
        self.assertEqual(len(fc["features"]), 1)
        props = fc["features"][0]["properties"]
        self.assertEqual(props["label"], "1247")
        self.assertEqual(props["scale_denominator"], "1000")
        self.assertEqual(props["level"], "3rdOrder")

    def test_parse_cadastral_reference(self) -> None:
        parsed = parse_cadastral_reference("B791_011500.1")
        self.assertEqual(
            parsed,
            {"belfiore_code": "B791", "foglio": "0115", "sezione": "00", "particella": "1"},
        )

    def test_point_in_polygon_and_area(self) -> None:
        fc = parse_gml_feature_collection(SAMPLE_PARCEL_GML)
        geom = fc["features"][0]["geometry"]
        self.assertTrue(point_in_geojson_geometry(45.0705, 7.6865, geom))
        self.assertFalse(point_in_geojson_geometry(45.0750, 7.6865, geom))
        self.assertGreater(compute_geometry_area_ha(geom), 0.5)

    def test_validate_wfs_bbox_enforces_vdist(self) -> None:
        validate_wfs_bbox(45.069, 7.685, 45.071, 7.688, layer=WFSLayers.CADASTRAL_PARCEL)
        with self.assertRaises(ValueError):
            # ~3,340 m vertical span exceeds 2,000 m parcel limit
            validate_wfs_bbox(45.050, 7.685, 45.080, 7.688, layer=WFSLayers.CADASTRAL_PARCEL)
        # Same span is valid for CadastralZoning (< 8,000 m)
        validate_wfs_bbox(45.050, 7.685, 45.080, 7.688, layer=WFSLayers.CADASTRAL_ZONING)

    def test_wms_helpers(self) -> None:
        cfg = get_wms_leaflet_config([WMSLayers.CADASTRAL_PARCEL, WMSLayers.FABBRICATI])
        self.assertEqual(cfg["url_template"], WMS_URL)
        self.assertEqual(cfg["options"]["layers"], "CP.CadastralParcel,fabbricati")
        self.assertTrue(cfg["options"]["transparent"])

        url = build_wms_getmap_url(45.069, 7.685, 45.071, 7.688)
        self.assertIn("SERVICE=WMS", url)
        self.assertIn("VERSION=1.3.0", url)
        self.assertIn("CRS=EPSG%3A6706", url)

    def test_turin_presets_present(self) -> None:
        self.assertIn("torino_centro", TURIN_PRESETS)
        self.assertEqual(TURIN_PRESETS["torino_centro"].belfiore_code, "L219")

    def test_fetch_parcel_at_point_mock(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=SAMPLE_PARCEL_GML)

        async def run_test() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = CatastoClient(client=http)
                res = await client.fetch_parcel_at_point(45.0705, 7.6865)
                self.assertEqual(res["source"], "ade_catasto_wfs")
                self.assertEqual(res["parcel"]["properties"]["national_ref"], "L219_124700.42")
                self.assertEqual(res["parcel"]["properties"]["foglio"], "1247")
                self.assertEqual(res["parcel"]["properties"]["particella"], "42")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()


class WfsCachedErrorRetryTests(unittest.TestCase):
    def test_cached_exception_report_is_retried_with_cache_buster(self) -> None:
        error_xml = ('<?xml version="1.0" encoding="ISO-8859-1"?><ServiceExceptionReport version="1.1.1">'
                     '<ServiceException code="InvalidFormat"><![CDATA[Richiesta non valida ]]></ServiceException>'
                     '</ServiceExceptionReport>')
        seen: list[httpx.URL] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url)
            if "_" not in request.url.params:  # the nginx-cached error for the plain URL
                return httpx.Response(200, text=error_xml)
            return httpx.Response(200, text=SAMPLE_PARCEL_GML)

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                return await CatastoClient(client=http).fetch_parcels_in_bbox(45.0, 7.7, 45.003, 7.703)

        fc = asyncio.run(run())
        self.assertEqual(len(seen), 2)
        self.assertGreater(len(fc["features"]), 0)
        self.assertEqual(seen[0].params["BBOX"], "45.000000,7.700000,45.003000,7.703000")
