"""Farmer crop whitelist/blacklist stored in `soil_override` and sent to analytics-api."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.crop_preferences import crop_preferences, soil_values_only
from src.providers.analytics_api import build_ingestion_payload
from src.providers.data_api import (
    compute_soil_override_flags,
    merge_plot_with_overrides,
    summarize_sensor_gaps,
)

PREFS = {"crop_whitelist": ["corn", "soybeans", "winter_wheat", "corn"], "crop_blacklist": ["soybeans", "spinach"]}
PLOT = {
    "id": "p1",
    "label": "Test",
    "area_ha": 2.0,
    "centroid": {"lat": 44.85, "lon": 7.72},
    "geometry": {"type": "Polygon", "coordinates": [[[7.72, 44.85], [7.73, 44.85], [7.73, 44.86], [7.72, 44.85]]]},
}


class CropPreferenceTests(unittest.TestCase):
    def test_lists_are_cleaned_and_blacklist_wins(self):
        self.assertEqual(crop_preferences(PREFS), (["corn", "winter_wheat"], ["soybeans", "spinach"]))
        self.assertEqual(crop_preferences({"crop_whitelist": "corn"}), ([], []))
        self.assertEqual(crop_preferences(None), ([], []))

    def test_preferences_are_not_soil_values(self):
        override = {**PREFS, "ph": 6.8}
        self.assertEqual(soil_values_only(override), {"ph": 6.8})
        self.assertEqual(compute_soil_override_flags(override), ["soil.ph"])
        merged = merge_plot_with_overrides({"soil": {"status": "ok", "values": {"ph": 6.0}}}, override)
        self.assertNotIn("crop_whitelist", merged["soil"]["values"])
        self.assertEqual(summarize_sensor_gaps({}, soil_override=PREFS)["soil_badge"], "Satellite Estimate (250m)")

    def test_ingestion_payload_carries_preferences(self):
        lud = build_ingestion_payload(PLOT, {}, PREFS)["local_user_data"]
        self.assertEqual(lud["preferred_candidate_crops"], ["corn", "winter_wheat"])
        self.assertEqual(lud["excluded_crops"], ["soybeans", "spinach"])
        self.assertNotIn("preferred_candidate_crops", build_ingestion_payload(PLOT, {}, {"ph": 6.5})["local_user_data"])


class SoilCarbonUnitsTest(unittest.TestCase):
    def test_soilgrids_soc_g_per_kg_is_sent_as_percent(self):
        ds = {"soil": {"status": "ok", "values": {"0-5cm": {"soc": 41.9, "clay": 20, "sand": 40, "silt": 40}}}}
        nasa = build_ingestion_payload(PLOT, ds, {})["nasa_data"]["soilgrids"]
        self.assertEqual(nasa["soil_organic_carbon_pct"], 4.19)


if __name__ == "__main__":
    unittest.main()
