"""Unit tests for the FastAPI router & standalone app (`src/api/app.py`)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.api import create_fastapi_app
from src.auth import AuthService
from src.farms import FarmStore
from src.providers.catasto import CatastoClient
from src.providers.data_api import DataApiClient
from src.providers.worldcover import WorldCoverClient


class ApiTests(unittest.TestCase):
    def test_health_auth_farms_plots_and_analysis_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FarmStore(pb_url="", store_path=Path(tmp) / "farms.json")
            auth = AuthService(pb_url="")
            admin_user = {"id": "u_admin", "user_id": "u_admin", "role": "farm_admin", "token": "tok_admin"}
            auth.verify_token = AsyncMock(side_effect=lambda tok: admin_user if tok == "tok_admin" else None)  # type: ignore[method-assign]

            app = create_fastapi_app(
                auth_service=auth,
                farm_store=store,
                catasto_client=CatastoClient(pb_url=""),
                worldcover_client=WorldCoverClient(),
                data_api_client=DataApiClient(base_url="http://data-api.test"),
            )
            client = TestClient(app)

            # Health
            r = client.get("/api/health")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "ok")

            # Unauthenticated rejected
            self.assertEqual(client.get("/api/farms").status_code, 401)

            headers = {"Authorization": "Bearer tok_admin"}
            farms_res = client.get("/api/farms", headers=headers)
            self.assertEqual(farms_res.status_code, 200)

            new_farm = client.post("/api/farms", headers=headers, json={"name": "API Test Farm"})
            self.assertEqual(new_farm.status_code, 201)
            farm_id = new_farm.json()["farm"]["id"]

            # Create grouped plot from 2 Catasto features
            create_res = client.post(
                f"/api/farms/{farm_id}/plots",
                headers=headers,
                json={
                    "label": "Merged East",
                    "crop": "Soy",
                    "use_catasto_names": True,
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Polygon", "coordinates": [[[7.70, 45.00], [7.71, 45.00], [7.71, 45.01], [7.70, 45.00]]]},
                            "properties": {"national_ref": "B791_1", "area_ha": 0.9, "centroid": [45.003, 7.705]},
                        },
                        {
                            "type": "Feature",
                            "geometry": {"type": "Polygon", "coordinates": [[[7.71, 45.00], [7.72, 45.00], [7.72, 45.01], [7.71, 45.00]]]},
                            "properties": {"national_ref": "B791_2", "area_ha": 1.1, "centroid": [45.003, 7.715]},
                        },
                    ],
                },
            )
            self.assertEqual(create_res.status_code, 201)
            plot = create_res.json()["plot"]
            self.assertEqual(plot["geometry"]["type"], "MultiPolygon")
            self.assertAlmostEqual(plot["area_ha"], 2.0, places=3)

            # Patch soil overrides -> sets overridden_fields
            patch_res = client.patch(
                f"/api/plots/{plot['id']}",
                headers=headers,
                json={"soil_override": {"clay_pct": 38.0, "ph": 7.2}},
            )
            self.assertEqual(patch_res.status_code, 200)
            self.assertEqual(patch_res.json()["plot"]["overridden_fields"], ["soil.clay_pct", "soil.ph"])

            # Analysis payload endpoint
            analysis_res = client.get(f"/api/plots/{plot['id']}/analysis-payload", headers=headers)
            self.assertEqual(analysis_res.status_code, 200)
            body = analysis_res.json()
            self.assertEqual(body["payload"]["overridden_fields"], ["soil.clay_pct", "soil.ph"])
            self.assertEqual(len(body["baseline_preview"]["strategies"]), 3)


if __name__ == "__main__":
    unittest.main()


class CatastoDiscoverTests(unittest.TestCase):
    """`POST /api/catasto/discover`: parcels overlapping a drawn polygon, filtered to farmland."""

    def _app(self, catasto, worldcover):
        auth = AuthService(pb_url="")
        user = {"id": "u", "user_id": "u", "role": "farm_admin", "token": "t"}
        auth.verify_token = AsyncMock(side_effect=lambda tok: user if tok == "t" else None)  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as tmp:
            store = FarmStore(pb_url="", store_path=Path(tmp) / "farms.json")
        return TestClient(create_fastapi_app(auth_service=auth, farm_store=store, catasto_client=catasto,
                                             worldcover_client=worldcover,
                                             data_api_client=DataApiClient(base_url="http://data-api.test")))

    @staticmethod
    def _square(lon, lat, d=0.001):
        return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}

    def test_returns_overlapping_farmland_parcels(self) -> None:
        inside_farm = {"type": "Feature", "id": "a", "geometry": self._square(7.7002, 45.0002, 0.0005), "properties": {}}
        inside_urban = {"type": "Feature", "id": "b", "geometry": self._square(7.7005, 45.0005, 0.0003), "properties": {}}
        outside = {"type": "Feature", "id": "c", "geometry": self._square(7.80, 45.10), "properties": {}}
        catasto = CatastoClient(pb_url="")
        catasto.fetch_parcels_in_bbox = AsyncMock(return_value={"type": "FeatureCollection",  # type: ignore[method-assign]
                                                                "features": [inside_farm, inside_urban, outside]})
        worldcover = WorldCoverClient()

        async def classify(features):
            for f in features:
                f["properties"].update(is_farmland=f["id"] == "a", worldcover_class=40 if f["id"] == "a" else 50,
                                       worldcover_label="Cropland" if f["id"] == "a" else "Built-up")
            return features

        worldcover.classify_parcels = AsyncMock(side_effect=classify)  # type: ignore[method-assign]
        r = self._app(catasto, worldcover).post("/api/catasto/discover", headers={"Authorization": "Bearer t"},
                                                json={"geometry": self._square(7.70, 45.00)})
        self.assertEqual(r.status_code, 200, r.text)
        parcels = r.json()["parcels"]
        self.assertEqual([p["id"] for p in parcels], ["a"])
        self.assertEqual(parcels[0]["properties"]["worldcover_label"], "Cropland")
        lat_span = catasto.fetch_parcels_in_bbox.await_args.args[2] - catasto.fetch_parcels_in_bbox.await_args.args[0]
        self.assertLess(lat_span, 0.018)  # stays under the AdE WFS 2 km vertical limit

    def test_outside_italy_returns_empty_without_calling_wfs(self) -> None:
        catasto = CatastoClient(pb_url="")
        catasto.fetch_parcels_in_bbox = AsyncMock()  # type: ignore[method-assign]
        r = self._app(catasto, WorldCoverClient()).post("/api/catasto/discover", headers={"Authorization": "Bearer t"},
                                                        json={"geometry": self._square(-93.6, 42.0)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["parcels"], [])
        catasto.fetch_parcels_in_bbox.assert_not_awaited()

    def test_wfs_failure_is_a_502_not_a_crash(self) -> None:
        catasto = CatastoClient(pb_url="")
        catasto.fetch_parcels_in_bbox = AsyncMock(side_effect=RuntimeError("WFS down"))  # type: ignore[method-assign]
        r = self._app(catasto, WorldCoverClient()).post("/api/catasto/discover", headers={"Authorization": "Bearer t"},
                                                        json={"geometry": self._square(7.70, 45.00)})
        self.assertEqual(r.status_code, 502)
