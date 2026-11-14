"""Unit tests for `data_api.py`, `formulas.py`, and `explainer.py`."""

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.explainer import explain_plot_insights
from src.formulas import evaluate_plot_strategies
from src.providers.data_api import (
    DataApiClient,
    extract_datasets,
    is_snapshot_fresh,
    merge_telemetry_snapshots,
    summarize_sensor_gaps,
)

SAMPLE_DATA_API_RESPONSE = {
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "parcels": [
        {
            "parcel": {"id": "B791_011500.1", "area_ha": 1.5},
            "datasets": {
                "crop_health": {"status": "ok", "scale": "field", "resolution_m": 30, "values": {"ndvi": 0.62}},
                "evapotranspiration_field": {"status": "no_data", "scale": "field", "resolution_m": 70},
                "terrain": {"status": "ok", "scale": "field", "resolution_m": 30, "values": {"slope_deg": 2.4, "low_spot_flag": True}},
                "weather": {"status": "ok", "scale": "area", "resolution_m": 55000, "values": {"et0_mm_day": 3.8, "rain_30d_mm": 55.0}},
                "rainfall": {"status": "ok", "scale": "area", "resolution_m": 11000, "values": {"total_30d_mm": 58.0, "consecutive_dry_days": 9}},
                "soil_moisture": {"status": "ok", "scale": "area", "resolution_m": 9000, "values": {"root_zone_wetness": 0.45}},
                "soil": {"status": "ok", "scale": "area", "resolution_m": 250, "values": {"clay_pct": 28.0, "sand_pct": 32.0, "organic_carbon_g_kg": 16.0, "ph": 6.9}},
                "groundwater": {"status": "ok", "scale": "area", "resolution_m": 300000, "values": {"percentile": 18.0}},
            },
            "timings_s": {"crop_health": 1.2},
        }
    ],
}


class InsightsTests(unittest.TestCase):
    def test_snapshot_freshness_merge_and_gaps(self) -> None:
        self.assertTrue(is_snapshot_fresh(SAMPLE_DATA_API_RESPONSE))
        self.assertFalse(is_snapshot_fresh(None))

        enrichment = {
            "parcels": [
                {
                    "datasets": {
                        "evapotranspiration_area": {"status": "ok", "scale": "area", "resolution_m": 500, "values": {"et_mm_day": 3.4}}
                    },
                    "timings_s": {"evapotranspiration_area": 42.0},
                }
            ]
        }
        merged = merge_telemetry_snapshots(SAMPLE_DATA_API_RESPONSE, enrichment)
        ds = extract_datasets(merged)
        self.assertIn("evapotranspiration_area", ds)

        gaps = summarize_sensor_gaps(ds, soil_override={"ph": 7.1})
        self.assertEqual(gaps["soil_badge"], "Lab-Verified Soil")
        self.assertTrue(any("MODIS MOD16A2" in f for f in gaps["fallbacks"]))
        self.assertTrue(any("Aquifer alert" in a for a in gaps["alerts"]))

    def test_formulas_and_explainer(self) -> None:
        ds = extract_datasets(SAMPLE_DATA_API_RESPONSE)
        analysis = evaluate_plot_strategies(
            datasets=ds,
            area_ha=1.5,
            baseline_rotation=["Maize", "Maize", "Winter Wheat"],
        )
        self.assertEqual(len(analysis["strategies"]), 3)
        self.assertGreater(analysis["strategies"][0]["score"], analysis["baseline"]["score"])

        gaps = summarize_sensor_gaps(ds)
        explained = explain_plot_insights(analysis, gaps, plot_label="South Clay Parcel")
        self.assertEqual(len(explained["bullets"]), 3)
        self.assertGreaterEqual(len(explained["checklist"]), 3)

    def test_data_api_client_mock(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/geojson")
            return httpx.Response(200, json=SAMPLE_DATA_API_RESPONSE)

        async def run_test() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = DataApiClient(base_url="http://data-api.test", client=http)
                res = await client.fetch_plot_telemetry({"type": "Feature", "geometry": {}})
                self.assertIn("fetched_at", res)
                self.assertEqual(len(res["parcels"]), 1)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
