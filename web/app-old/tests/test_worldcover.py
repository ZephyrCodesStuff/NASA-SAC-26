"""Unit tests for the ESA WorldCover 2021 10m COG provider."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.providers.worldcover import (
    _HEADER_CACHE,
    _TILE_CACHE,
    CogHeader,
    WorldCoverClient,
    worldcover_tile_id,
)


class WorldCoverTests(unittest.TestCase):
    def test_worldcover_tile_id_for_turin(self) -> None:
        self.assertEqual(worldcover_tile_id(45.0703, 7.6869), "N45E006")
        self.assertEqual(worldcover_tile_id(44.8467, 7.7178), "N42E006")
        self.assertEqual(worldcover_tile_id(-3.1, -60.2), "S06W063")

    def test_classify_parcel_cropland_vs_builtup(self) -> None:
        _HEADER_CACHE.clear()
        _TILE_CACHE.clear()

        hdr = CogHeader(
            tile_id="N45E006",
            width=36000,
            height=36000,
            tile_width=1024,
            tile_height=1024,
            origin_lon=6.0,
            origin_lat=48.0,
            scale_lon=3.0 / 36000.0,
            scale_lat=3.0 / 36000.0,
            tile_offsets=[0] * 1296,
            tile_byte_counts=[0] * 1296,
        )
        _HEADER_CACHE["N45E006"] = hdr

        # Populate the specific 1024x1024 tile covering (45.0705, 7.6865)
        px = int((7.6865 - 6.0) / hdr.scale_lon)
        py = int((48.0 - 45.0705) / hdr.scale_lat)
        tid = (py // 1024) * hdr.tiles_per_row + (px // 1024)

        cropland_feature = {
            "type": "Feature",
            "id": "farm-1",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [7.6860, 45.0700],
                        [7.6870, 45.0700],
                        [7.6870, 45.0710],
                        [7.6860, 45.0710],
                        [7.6860, 45.0700],
                    ]
                ],
            },
            "properties": {"centroid": [45.0705, 7.6865]},
        }
        builtup_feature = {
            "type": "Feature",
            "id": "city-1",
            "geometry": cropland_feature["geometry"],
            "properties": {"centroid": [45.0705, 7.6865]},
        }

        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                wc = WorldCoverClient(cache_dir=tmpdir)
                _TILE_CACHE[("N45E006", tid)] = bytes([40]) * (1024 * 1024)
                await wc.classify_parcel(cropland_feature)
                self.assertEqual(cropland_feature["properties"]["worldcover_class"], 40)
                self.assertEqual(cropland_feature["properties"]["worldcover_label"], "Cropland")
                self.assertTrue(cropland_feature["properties"]["is_farmland"])

                _TILE_CACHE[("N45E006", tid)] = bytes([50]) * (1024 * 1024)
                await wc.classify_parcel(builtup_feature)
                self.assertEqual(builtup_feature["properties"]["worldcover_class"], 50)
                self.assertEqual(builtup_feature["properties"]["worldcover_label"], "Built-up")
                self.assertFalse(builtup_feature["properties"]["is_farmland"])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
