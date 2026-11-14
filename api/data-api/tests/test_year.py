"""Year mode (24 half-month periods), crop-group classification and erosion factors — offline."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import core, main
from app.core import aggregate_periods, flatten_history, half_month_periods
from app.parcel import point_parcel
from app.sources import erosion
from app.sources.crop_history import classify


def test_half_month_periods_cover_a_year_in_24():
    p = half_month_periods(date(2026, 1, 1), date(2026, 12, 31))
    assert len(p) == 24
    assert p[0] == ("2026-01-H1", date(2026, 1, 1), date(2026, 1, 15))
    assert p[3] == ("2026-02-H2", date(2026, 2, 16), date(2026, 2, 28))


@pytest.mark.parametrize("today", [date(2026, 11, 14), date(2026, 11, 20), date(2026, 12, 31), date(2026, 1, 1)])
def test_year_window_is_always_24_periods_ending_now(today):
    s, e = main.year_window(today)
    p = half_month_periods(s, e)
    assert len(p) == 24 and p[-1][1] <= today <= p[-1][2]


def test_aggregate_sums_rain_means_temperature_and_spreads_months():
    rows = [{"date": "2026-03-01", "PRECTOTCORR": 5, "T2M": 10, "T2M_MAX": 14},
            {"date": "2026-03-02", "PRECTOTCORR": 3, "T2M": 12, "T2M_MAX": 18},
            {"date": "2026-03-20", "PRECTOTCORR": None, "T2M": 8, "T2M_MAX": 9}]
    out = aggregate_periods(rows, date(2026, 3, 1), date(2026, 3, 31))
    h1, h2 = out
    assert (h1["PRECTOTCORR"], h1["T2M"], h1["T2M_MAX"], h1["observations"]) == (8, 11, 18, 2)
    assert h2["T2M"] == 8 and "PRECTOTCORR" not in h2
    monthly = aggregate_periods([{"month": "2026-03", "anomaly_cm": -4}], date(2026, 3, 1), date(2026, 3, 31))
    assert [m["anomaly_cm"] for m in monthly] == [-4, -4]


def test_flatten_ecostress_style_history():
    rows = flatten_history({"esi": [{"datetime": "2026-05-02T10:00:00Z", "mean": 0.5}], "lst": []})
    assert rows == [{"datetime": "2026-05-02T10:00:00Z", "esi": 0.5}]


def _curve(peak_idx, high=0.85, low=0.2, width=4):
    return [high if abs(i - peak_idx) <= width // 2 else low for i in range(24)]


def test_classify_winter_cereal_summer_crop_grass_bare_rice():
    ndmi = [None] * 24
    assert classify(_curve(8), ndmi)["crop_group"].startswith("winter cereal")
    assert classify(_curve(14), ndmi)["crop_group"].startswith("summer crop")
    assert classify([0.7] * 24, ndmi)["crop_group"].startswith("permanent grassland")
    assert classify([0.15] * 24, ndmi)["crop_group"].startswith("bare")
    rice_ndvi = _curve(15)
    rice_ndmi = [0.4 if 8 <= i < 12 else None for i in range(24)]
    assert classify(rice_ndvi, rice_ndmi)["crop_group"].startswith("rice")
    assert classify([None] * 24, ndmi)["crop_group"] == "unknown"


def test_erosion_factors_and_compute():
    assert erosion.r_factor(600) == pytest.approx(0.0483 * 600 ** 1.61)
    assert 0.01 < erosion.k_factor(30, 45, 25, 1.5) < 0.05
    assert erosion.ls_factor(5, 100) > erosion.ls_factor(1, 100)
    assert erosion.c_factor(0.8) < erosion.c_factor(0.2) <= 1
    ds = {"soil": {"status": "ok", "values": {"0-5cm": {"sand": 30, "silt": 45, "clay": 25, "soc": 15}}},
          "terrain": {"status": "ok", "values": {"slope_deg": {"mean": 3}}},
          "weather": {"status": "ok", "values": {"normals_1991_2020": {"ann": {"PRECTOTCORR": 2.6}}}},
          "crop_health": {"status": "ok", "date": "2026-10-01", "values": {"ndvi": {"mean": 0.6}}}}
    v = erosion.compute(point_parcel(45, 8, half_size_m=100), ds)["values"]
    assert v["soil_loss_current_cover_t_ha_yr"] < v["soil_loss_bare_t_ha_yr"]
    assert erosion.compute(point_parcel(45, 8), {"soil": {"status": "error"}})["status"] == "no_data"


class _Hist:
    @staticmethod
    def fetch(parcel, q):
        s, e = q.window
        return {"status": "ok", "values": {}, "history": [{"date": s.isoformat(), "x": 1.0}, {"date": e.isoformat(), "x": 3.0}]}


def test_year_flag_adds_24_periods(monkeypatch):
    core._mem.clear()
    monkeypatch.setattr(main, "SOURCES", {n: (_Hist, t, d) for n, (_, t, d) in main.SOURCES.items()})
    with TestClient(main.app) as c:
        r = c.get("/point", params={"lat": 45, "lon": 8, "datasets": "weather", "year": "true"})
    body = r.json()
    assert body["query"]["periods"] is True
    periods = body["parcels"][0]["datasets"]["weather"]["periods"]
    assert len(periods) == 24 and periods[0]["x"] == 1.0 and periods[-1]["x"] == 3.0


def test_eurostat_jsonstat_decoding(monkeypatch):
    from app.sources import eu_prices

    fake = {"id": ["geo", "time"], "size": [1, 2], "value": {"0": 0.17, "1": 0.18},
            "dimension": {"geo": {"category": {"index": {"IT": 0}, "label": {"IT": "Italy"}}},
                          "time": {"category": {"index": {"2025-S1": 0, "2025-S2": 1}}}}}
    monkeypatch.setattr(eu_prices, "http_get_json", lambda *a, **k: fake)
    rows = eu_prices._jsonstat("nrg_pc_205")
    assert [(r["time"], r["value"], r["label"]["geo"]) for r in rows] == [("2025-S1", 0.17, "Italy"), ("2025-S2", 0.18, "Italy")]


def test_local_prices_outside_eu(monkeypatch):
    from app.sources import eu_prices

    monkeypatch.setattr(eu_prices, "country_at", lambda lat, lon: {"iso2": "US", "name": "United States"})
    assert eu_prices.fetch(point_parcel(40, -100), None)["status"] == "unavailable"


def test_plane_gradient_ignores_dem_noise():
    import numpy as np

    from app.sources.nasadem import _plane_gradient_deg

    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:20, 0:20]
    flat_noisy = 100 + rng.normal(0, 1.0, (20, 20))  # ±1 m noise, like NASADEM on a paddy
    tilted = 100 + xx * 30 * np.tan(np.radians(3))  # true 3° slope along x
    inside = np.ones((20, 20), bool)
    assert _plane_gradient_deg(flat_noisy, inside, 30, 30) < 0.3
    assert abs(_plane_gradient_deg(tilted, inside, 30, 30) - 3) < 0.01
