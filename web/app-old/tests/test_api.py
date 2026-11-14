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
