"""Unit tests for FarmStore, role ownership, polygon drawing, and intersection."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.auth import is_farm_owner
from src.farms import FarmStore, extract_drawn_geojson, polygons_intersect


class FarmTests(unittest.TestCase):
    def test_is_farm_owner(self) -> None:
        farm = {"id": "f1", "owner": "u1"}
        self.assertTrue(is_farm_owner(farm, {"user_id": "u1", "role": "farm_admin"}))
        self.assertFalse(is_farm_owner(farm, {"user_id": "u1", "role": "viewer"}))
        self.assertFalse(is_farm_owner(farm, {"user_id": "u2", "role": "farm_admin"}))

    def test_extract_drawn_geojson_and_intersection(self) -> None:
        ev = {
            "layer": {
                "_latlngs": [
                    [
                        {"lat": 44.8465, "lng": 7.7160},
                        {"lat": 44.8465, "lng": 7.7170},
                        {"lat": 44.8472, "lng": 7.7170},
                        {"lat": 44.8472, "lng": 7.7160},
                    ]
                ]
            }
        }
        feat = extract_drawn_geojson(ev)
        self.assertIsNotNone(feat)
        assert feat is not None
        self.assertEqual(feat["geometry"]["type"], "Polygon")
        self.assertGreater(feat["properties"]["area_ha"], 0.5)

        overlapping = {
            "type": "Polygon",
            "coordinates": [
                [
                    [7.7165, 44.8468],
                    [7.7180, 44.8468],
                    [7.7180, 44.8478],
                    [7.7165, 44.8478],
                    [7.7165, 44.8468],
                ]
            ],
        }
        disjoint = {
            "type": "Polygon",
            "coordinates": [
                [
                    [7.7200, 44.8500],
                    [7.7210, 44.8500],
                    [7.7210, 44.8510],
                    [7.7200, 44.8510],
                    [7.7200, 44.8500],
                ]
            ],
        }
        self.assertTrue(polygons_intersect(feat["geometry"], overlapping))
        self.assertFalse(polygons_intersect(feat["geometry"], disjoint))

    def test_farm_store_crud_local_fallback(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                store = FarmStore(pb_url="", store_path=Path(tmpdir) / "farms.json")
                admin = {"user_id": "u_marco", "email": "marco@turinfarm.it", "role": "farm_admin"}
                farms = await store.list_farms(admin)
                self.assertGreaterEqual(len(farms), 2)

                created_farm = await store.create_farm("My Test Farm", admin)
                self.assertEqual(created_farm["owner"], "u_marco")

                plot = await store.add_plot(
                    created_farm["id"],
                    {
                        "label": "Test Plot",
                        "area_ha": 1.2,
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[7.7, 45.0], [7.701, 45.0], [7.701, 45.001], [7.7, 45.0]]],
                        },
                    },
                    user=admin,
                )
                plots = await store.list_plots(created_farm["id"], user=admin)
                self.assertEqual(len(plots), 1)
                self.assertEqual(plots[0]["label"], "Test Plot")

                removed = await store.remove_plot(plot["id"], user=admin)
                self.assertTrue(removed)
                self.assertEqual(await store.list_plots(created_farm["id"], user=admin), [])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
