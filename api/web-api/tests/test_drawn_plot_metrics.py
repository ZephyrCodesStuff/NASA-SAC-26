"""Custom-drawn plots must get area and centroid computed from their geometry."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.farms import fill_plot_geometry_metrics, merge_catasto_features_into_plot

# Drawn Field 7 (Carmagnola), saved with area 0 and no centroid
GEOM = {
    "type": "Polygon",
    "coordinates": [[
        [7.707359790802003, 44.86129887321884], [7.708625793457032, 44.859595378271266],
        [7.711479663848878, 44.860553600381024], [7.710878849029542, 44.862272276273956],
        [7.707359790802003, 44.86129887321884],
    ]],
}


class DrawnPlotMetricsTests(unittest.TestCase):
    def test_merge_computes_missing_area_and_centroid(self):
        plot = merge_catasto_features_into_plot([{"type": "Feature", "geometry": GEOM, "properties": {}}])
        self.assertGreater(plot["area_ha"], 3.0)
        self.assertLess(plot["area_ha"], 6.0)
        self.assertAlmostEqual(plot["centroid"]["lat"], 44.861, places=2)
        self.assertAlmostEqual(plot["centroid"]["lon"], 7.709, places=2)

    def test_existing_record_is_filled_on_read(self):
        plot = fill_plot_geometry_metrics({"id": "x", "area_ha": 0, "centroid": None, "geometry": GEOM})
        self.assertGreater(plot["area_ha"], 3.0)
        self.assertIn("lat", plot["centroid"])

    def test_saved_values_are_kept(self):
        plot = fill_plot_geometry_metrics({"area_ha": 1.5, "centroid": {"lat": 1.0, "lon": 2.0}, "geometry": GEOM})
        self.assertEqual((plot["area_ha"], plot["centroid"]), (1.5, {"lat": 1.0, "lon": 2.0}))
        self.assertEqual(fill_plot_geometry_metrics({"id": "farm"}), {"id": "farm"})


if __name__ == "__main__":
    unittest.main()
