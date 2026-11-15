"""
Comprehensive Test Suite for Field Ingestion & Input Parser.
Verifies:
1. Ingestion of the 7 core agronomic domains.
2. Soil Type resolution and priority inheritance (User > Parcel > SoilGrids > Baseline).
3. Seed Data parsing:
   - Greenhouse need ('Open Field Only', 'Open Field or Greenhouse Compatible', 'Greenhouse Required')
   - Resistance to extreme events (drought, flood/waterlogging, high wind/lodging, frost, heat, salinity)
4. Flexible 1-5 year historical harvest record processing & >5 year trimming.
5. NASA Data official raw formats & full dated timeseries extraction:
   - NASA POWER official daily weather parameters (T2M, T2M_MAX, T2M_MIN, PRECTOTCORR)
   - GPM IMERG daily rainfall timeseries & storm tracking
   - OpenET daily actual evapotranspiration array
   - SoilGrids depth-stratified horizon layers (0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm)
6. Local User in-situ sensor telemetry with exact date/time signatures (chronological sorting & latest calibration).
7. GeoJSON polygon centroid extraction & Acre-to-Hectare unit harmonization.
8. Robust handling of absent/partial optional datasets.
9. FastAPI HTTP endpoints (/api/parser/ingest, /api/parser/validate, /api/parser/seed-templates, /api/parser/soil-types).
"""

import unittest
from fastapi.testclient import TestClient

from projection_api.main import app
from projection_api.models.input_parser_schemas import (
    FullFieldIngestionPayload,
    ParcelInfoInput,
    HarvestAndCropHistoryInput,
    SeasonalCropRecord,
    EconomicPricesInput,
    SeedDataInput,
    GreenhouseRequirement,
    ExtremeEventResistance,
    ExtremeResistanceLevel,
    NasaDataPayload,
    NasaPowerPayload,
    GpmImergPayload,
    OpenEtPayload,
    SoilGridsPayload,
    SoilGridsDepthLayer,
    DatedInSituSensorReading,
    LocalUserDataInput,
    ElevationMapsInput,
    LongTermWeatherProjectionsInput
)
from projection_api.services.input_parser import FieldIngestionParser


class TestFieldInputParser(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_soil_type_priority_user_override(self):
        """User local override takes top priority for soil type."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(
                parcel_id="PRCL-TEST-01",
                soil_type="Clay Loam",
                area_hectares=20.0,
                latitude=42.0,
                longitude=-93.5
            ),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2025, crop_name="Corn (Maize)", yield_harvested_tons_ha=9.5)
                ]
            ),
            local_user_data=LocalUserDataInput(
                soil_type="Silty Clay Loam"
            ),
            nasa_data=NasaDataPayload(
                soilgrids=SoilGridsPayload(texture_class="Sandy Loam")
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(normalized.soil_type, "Silty Clay Loam")
        self.assertEqual(normalized.soil_type_source, "User Local Override")

    def test_soil_type_priority_parcel_declared(self):
        """When user override is absent, parcel declared soil type is used."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(
                parcel_id="PRCL-TEST-02",
                soil_type="Chernozem / Mollisol (Black Soil)",
                area_hectares=15.0,
                latitude=44.0,
                longitude=-95.0
            ),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2025, crop_name="Soybeans", yield_harvested_tons_ha=3.6)
                ]
            ),
            nasa_data=NasaDataPayload(
                soilgrids=SoilGridsPayload(texture_class="Clay")
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(normalized.soil_type, "Chernozem / Mollisol (Black Soil)")
        self.assertEqual(normalized.soil_type_source, "Parcel Declared")

    def test_soil_type_priority_satellite_soilgrids(self):
        """When user and parcel soil type are absent, NASA SoilGrids satellite texture is used."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(
                parcel_id="PRCL-TEST-03",
                area_hectares=12.0,
                latitude=40.0,
                longitude=-88.0
            ),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2025, crop_name="Winter Wheat", yield_harvested_tons_ha=5.2)
                ]
            ),
            nasa_data=NasaDataPayload(
                soilgrids=SoilGridsPayload(texture_class="Silt Loam")
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(normalized.soil_type, "Silt Loam")
        self.assertEqual(normalized.soil_type_source, "SoilGrids Satellite")

    def test_seed_greenhouse_need_synchronization(self):
        """Greenhouse requirement enums properly sync boolean flags."""
        seed_open = SeedDataInput(
            crop_name="Corn (Maize)",
            greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY
        )
        self.assertFalse(seed_open.can_grow_in_greenhouse)
        self.assertFalse(seed_open.requires_greenhouse)

        seed_compat = SeedDataInput(
            crop_name="Processing Tomatoes",
            greenhouse_need=GreenhouseRequirement.OPEN_FIELD_OR_GREENHOUSE
        )
        self.assertTrue(seed_compat.can_grow_in_greenhouse)
        self.assertFalse(seed_compat.requires_greenhouse)

        seed_req = SeedDataInput(
            crop_name="Hydroponic Tomatoes",
            greenhouse_need=GreenhouseRequirement.GREENHOUSE_REQUIRED
        )
        self.assertTrue(seed_req.can_grow_in_greenhouse)
        self.assertTrue(seed_req.requires_greenhouse)

    def test_seed_extreme_events_resistance_parsing(self):
        """Custom extreme event resistances (drought, flood, wind, frost, heat) parse accurately."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(
                parcel_id="PRCL-DROUGHT-01",
                area_hectares=50.0,
                latitude=33.5,
                longitude=-101.8
            ),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2024, crop_name="Grain Sorghum"),
                    SeasonalCropRecord(year=2025, crop_name="Cotton")
                ]
            ),
            seed_data=[
                SeedDataInput(
                    crop_name="Grain Sorghum",
                    variety_or_hybrid_name="AridMax Ultra",
                    seed_cost_usd_per_ha=90.0,
                    greenhouse_need=GreenhouseRequirement.OPEN_FIELD_ONLY,
                    extreme_event_resistance=ExtremeEventResistance(
                        drought_resistance=ExtremeResistanceLevel.VERY_HIGH,
                        drought_tolerance_score=4.9,
                        flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
                        flood_tolerance_score=2.0,
                        wind_lodging_resistance=ExtremeResistanceLevel.HIGH,
                        wind_tolerance_score=4.2,
                        extreme_heat_resistance=ExtremeResistanceLevel.VERY_HIGH,
                        heat_tolerance_score=4.8
                    )
                ),
                SeedDataInput(
                    crop_name="Bell Peppers",
                    variety_or_hybrid_name="Greenhouse Sweet Bell",
                    seed_cost_usd_per_ha=450.0,
                    greenhouse_need=GreenhouseRequirement.GREENHOUSE_REQUIRED,
                    extreme_event_resistance=ExtremeEventResistance(
                        drought_resistance=ExtremeResistanceLevel.LOW,
                        drought_tolerance_score=2.1,
                        flood_waterlogging_resistance=ExtremeResistanceLevel.LOW,
                        flood_tolerance_score=1.5,
                        wind_lodging_resistance=ExtremeResistanceLevel.LOW,
                        wind_tolerance_score=1.8,
                        frost_cold_resistance=ExtremeResistanceLevel.VERY_LOW,
                        frost_tolerance_score=1.0
                    )
                )
            ]
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertIn("Grain Sorghum", normalized.seed_catalog)
        self.assertIn("Bell Peppers", normalized.seed_catalog)
        self.assertIn("Grain Sorghum", normalized.drought_resilient_crops)
        self.assertIn("Grain Sorghum", normalized.heat_resilient_crops)
        self.assertNotIn("Bell Peppers", normalized.drought_resilient_crops)
        self.assertIn("Bell Peppers", normalized.greenhouse_required_crops)
        self.assertIn("Grain Sorghum", normalized.open_field_only_crops)

    def test_flexible_history_trimming_max_5(self):
        """When user provides >5 years of historical records, parser trims to most recent 5."""
        records = [
            SeasonalCropRecord(year=2019, crop_name="Corn (Maize)"),
            SeasonalCropRecord(year=2020, crop_name="Soybeans"),
            SeasonalCropRecord(year=2021, crop_name="Winter Wheat"),
            SeasonalCropRecord(year=2022, crop_name="Corn (Maize)"),
            SeasonalCropRecord(year=2023, crop_name="Soybeans"),
            SeasonalCropRecord(year=2024, crop_name="Grain Sorghum"),
            SeasonalCropRecord(year=2025, crop_name="Sunflowers")
        ]
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-HIST-7YR", area_hectares=10.0, latitude=40.0, longitude=-90.0),
            harvest_history=HarvestAndCropHistoryInput(historical_seasons=records)
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(normalized.history_years_count, 5)
        self.assertEqual(normalized.past_crops_sequence, [
            "Winter Wheat", "Corn (Maize)", "Soybeans", "Grain Sorghum", "Sunflowers"
        ])
        self.assertIn("trimmed to most recent 5 years", " ".join(normalized.audit_messages))

    # --------------------------------------------------------------------------
    # RAW OFFICIAL NASA DATABASE FORMAT & DATED TIMESERIES TESTS
    # --------------------------------------------------------------------------

    def test_nasa_power_official_format_timeseries_extraction(self):
        """Parses official NASA POWER raw GeoJSON response containing daily parameters."""
        raw_power = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-93.5, 41.5, 280.0]},
            "properties": {
                "parameter": {
                    "T2M": {"20240101": -2.5, "20240102": 3.0, "20240103": -1.0},
                    "T2M_MAX": {"20240101": 1.0, "20240102": 8.0, "20240103": 2.0},
                    "T2M_MIN": {"20240101": -6.0, "20240102": -2.0, "20240103": -4.0},
                    "PRECTOTCORR": {"20240101": 0.0, "20240102": 15.0, "20240103": 0.0},
                    "ALLSKY_SFC_SW_DWN": {"20240101": 8.5, "20240102": 12.0, "20240103": 9.0}
                }
            }
        }
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-NASA-POWER", area_hectares=20.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[SeasonalCropRecord(year=2024, crop_name="Corn (Maize)")]
            ),
            nasa_data=NasaDataPayload(
                nasa_power=NasaPowerPayload(raw_official_response=raw_power)
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)

        # Confirm full dated timeseries is preserved
        self.assertEqual(len(normalized.daily_weather_timeseries), 3)
        self.assertEqual(normalized.weather_days_count, 3)
        self.assertEqual(normalized.weather_start_date, "2024-01-01")
        self.assertEqual(normalized.weather_end_date, "2024-01-03")

        # Verify daily dates are normalized
        dates = [w.date for w in normalized.daily_weather_timeseries]
        self.assertEqual(dates, ["2024-01-01", "2024-01-02", "2024-01-03"])

        # Check high-resolution statistics
        self.assertEqual(normalized.frost_days_count, 3)  # Tmin was -6, -2, -4 (all <= 0)
        self.assertEqual(normalized.heatwave_days_count, 0)
        self.assertAlmostEqual(normalized.nasa_power_temp_mean_c, (-2.5 + 3.0 - 1.0)/3.0, places=1)

    def test_gpm_imerg_daily_storm_tracking(self):
        """Extracts daily rainfall series and correctly flags peak 24h storm event."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-STORM-01", area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[SeasonalCropRecord(year=2024, crop_name="Soybeans")]
            ),
            nasa_data=NasaDataPayload(
                gpm_imerg=GpmImergPayload(
                    daily_rainfall_series={
                        "2024-06-01": 2.5,
                        "2024-06-15": 68.4,  # Peak storm
                        "2024-06-28": 12.0
                    }
                )
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(len(normalized.daily_rainfall_timeseries), 3)
        self.assertEqual(normalized.peak_storm_event_date, "2024-06-15")
        self.assertEqual(normalized.peak_storm_event_mm, 68.4)
        self.assertAlmostEqual(normalized.gpm_imerg_annual_rainfall_mm, 82.9, places=1)

    def test_openet_official_format_timeseries_extraction(self):
        """Parses raw OpenET REST response array with daily actual ET."""
        openet_raw = [
            {"date": "2024-05-01", "et": 3.8, "et0": 4.5, "kc": 0.84},
            {"date": "2024-05-02", "et": 4.2, "et0": 4.8, "kc": 0.88},
            {"date": "2024-05-03", "et": 5.1, "et0": 5.5, "kc": 0.92}
        ]
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-OPENET-01", area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[SeasonalCropRecord(year=2024, crop_name="Corn (Maize)")]
            ),
            nasa_data=NasaDataPayload(
                openet_water=OpenEtPayload(raw_official_response=openet_raw)
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(len(normalized.daily_openet_timeseries), 3)
        self.assertAlmostEqual(normalized.openet_actual_et_annual_mm, 13.1, places=1)
        self.assertEqual(normalized.daily_openet_timeseries[0].date, "2024-05-01")

    def test_soilgrids_depth_stratified_layers_extraction(self):
        """Ingests multi-depth soil horizon profile (0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm)."""
        layers = [
            SoilGridsDepthLayer(depth_interval="0-5cm", top_depth_cm=0, bottom_depth_cm=5, clay_pct=22.0, soc_pct=2.8, soil_ph_h2o=6.8),
            SoilGridsDepthLayer(depth_interval="5-15cm", top_depth_cm=5, bottom_depth_cm=15, clay_pct=24.0, soc_pct=2.4, soil_ph_h2o=6.7),
            SoilGridsDepthLayer(depth_interval="15-30cm", top_depth_cm=15, bottom_depth_cm=30, clay_pct=28.0, soc_pct=1.8, soil_ph_h2o=6.6),
            SoilGridsDepthLayer(depth_interval="30-60cm", top_depth_cm=30, bottom_depth_cm=60, clay_pct=32.0, soc_pct=1.2, soil_ph_h2o=6.5),
            SoilGridsDepthLayer(depth_interval="60-100cm", top_depth_cm=60, bottom_depth_cm=100, clay_pct=35.0, soc_pct=0.8, soil_ph_h2o=6.4)
        ]
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-SOIL-DEPTH", area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[SeasonalCropRecord(year=2024, crop_name="Winter Wheat")]
            ),
            nasa_data=NasaDataPayload(
                soilgrids=SoilGridsPayload(depth_layers=layers)
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(len(normalized.soil_depth_layers), 5)
        self.assertEqual(normalized.soil_depth_layers[0].depth_interval, "0-5cm")
        self.assertEqual(normalized.soil_depth_layers[4].depth_interval, "60-100cm")
        self.assertEqual(normalized.soilgrids_organic_carbon_pct, 2.8)

    # --------------------------------------------------------------------------
    # USER IN-SITU SENSORS WITH DATE SIGNATURES TESTS
    # --------------------------------------------------------------------------

    def test_dated_in_situ_sensors_chronological_ordering_and_trend(self):
        """User in-situ sensors with date signatures sort chronologically and calibrate using latest reading."""
        # Unsorted in-situ readings
        readings = [
            DatedInSituSensorReading(
                timestamp="2025-06-25T11:00:00Z",
                depth_cm=15.0,
                soil_nitrogen_ppm=18.5,  # Later in season (nitrogen depleted)
                soil_moisture_vol_pct=19.2,
                soil_ph=6.75,
                soil_compaction_psi=230.0  # Increased compaction from equipment
            ),
            DatedInSituSensorReading(
                timestamp="2025-04-10T09:30:00Z",
                depth_cm=15.0,
                soil_nitrogen_ppm=42.0,  # Early season pre-plant N
                soil_moisture_vol_pct=31.5,
                soil_ph=6.80,
                soil_compaction_psi=175.0
            ),
            DatedInSituSensorReading(
                timestamp="2025-05-18T14:15:00Z",
                depth_cm=15.0,
                soil_nitrogen_ppm=30.0,
                soil_moisture_vol_pct=25.0,
                soil_ph=6.78,
                soil_compaction_psi=195.0
            )
        ]
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PRCL-SENSORS-DATED", area_hectares=25.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[SeasonalCropRecord(year=2024, crop_name="Corn (Maize)")]
            ),
            local_user_data=LocalUserDataInput(
                dated_sensor_readings=readings
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)

        # Check in-situ list is preserved and ordered chronologically
        self.assertEqual(normalized.in_situ_readings_count, 3)
        self.assertEqual(len(normalized.dated_in_situ_sensors), 3)
        self.assertEqual(normalized.in_situ_earliest_timestamp, "2025-04-10T09:30:00Z")
        self.assertEqual(normalized.in_situ_latest_timestamp, "2025-06-25T11:00:00Z")

        # Verify latest reading governs active calibration
        # 18.5 ppm * 2.24 = 41.4 kg N/ha
        self.assertAlmostEqual(normalized.calibrated_topsoil_n_kg_ha, 41.4, places=1)
        self.assertEqual(normalized.calibrated_compaction_psi, 230.0)
        self.assertIn("Moderate Plowpan", normalized.compaction_level_tag)

    def test_unit_conversions_and_centroid_extraction(self):
        """Acres are converted to ha, and GeoJSON polygon extracts centroid."""
        geojson_poly = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-93.50, 42.00],
                    [-93.40, 42.00],
                    [-93.40, 42.10],
                    [-93.50, 42.10],
                    [-93.50, 42.00]
                ]
            ]
        }
        parcel = ParcelInfoInput(
            parcel_id="PRCL-GEO-01",
            area_acres=100.0,
            boundary_geojson=geojson_poly
        )
        self.assertAlmostEqual(parcel.area_hectares, 40.47, places=1)
        self.assertAlmostEqual(parcel.latitude, 42.04, places=1)
        self.assertAlmostEqual(parcel.longitude, -93.46, places=1)

    def test_minimal_payload_with_absent_data_does_not_crash(self):
        """Minimal input with all optional fields omitted completes cleanly with scientific defaults."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="MINIMAL-01"),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2025, crop_name="Corn (Maize)")
                ]
            )
        )
        normalized = FieldIngestionParser.parse_and_validate(payload)
        self.assertEqual(normalized.parcel_id, "MINIMAL-01")
        self.assertEqual(normalized.history_years_count, 1)
        self.assertIsNotNone(normalized.soil_type)
        self.assertGreater(len(normalized.seed_catalog), 0)
        self.assertGreater(normalized.data_completeness_score_pct, 20.0)

    # --------------------------------------------------------------------------
    # FASTAPI HTTP ENDPOINT TESTS
    # --------------------------------------------------------------------------

    def test_http_endpoint_parser_ingest(self):
        """POST /api/parser/ingest returns 200 with normalized model."""
        body = {
            "parcel_info": {
                "parcel_id": "HTTP-TEST-INGEST",
                "latitude": 41.6,
                "longitude": -93.8,
                "area_hectares": 25.0,
                "soil_type": "Loam"
            },
            "harvest_history": {
                "historical_seasons": [
                    {"year": 2024, "crop_name": "Soybeans", "yield_harvested_tons_ha": 3.8},
                    {"year": 2025, "crop_name": "Corn (Maize)", "yield_harvested_tons_ha": 10.2}
                ]
            },
            "economic_prices": {
                "diesel_fuel_price_usd_liter": 1.20,
                "irrigation_water_price_usd_m3": 0.09,
                "seed_data": [
                    {
                        "crop_name": "Corn (Maize)",
                        "variety_or_hybrid_name": "Pioneer P1197",
                        "greenhouse_need": "Open Field Only",
                        "extreme_event_resistance": {
                            "drought_resistance": "Moderate (Average Resilience)",
                            "drought_tolerance_score": 3.2,
                            "flood_waterlogging_resistance": "Moderate (Average Resilience)",
                            "flood_tolerance_score": 3.0,
                            "wind_lodging_resistance": "High",
                            "wind_tolerance_score": 4.1
                        }
                    }
                ]
            }
        }
        res = self.client.post("/api/parser/ingest", json=body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["parcel_id"], "HTTP-TEST-INGEST")
        self.assertEqual(data["soil_type"], "Loam")
        self.assertIn("Corn (Maize)", data["seed_catalog"])
        self.assertEqual(data["seed_catalog"]["Corn (Maize)"]["greenhouse_need"], "Open Field Only")
        self.assertIn("Corn (Maize)", data["wind_resilient_crops"])

    def test_http_endpoint_parser_ingest_with_raw_nasa_and_dated_sensors(self):
        """POST /api/parser/ingest ingests official raw NASA POWER payload & dated sensor readings."""
        body = {
            "parcel_info": {
                "parcel_id": "HTTP-RAW-NASA-01",
                "area_acres": 40.0
            },
            "harvest_history": {
                "historical_seasons": [
                    {"year": 2025, "crop_name": "Corn (Maize)"}
                ]
            },
            "nasa_data": {
                "nasa_power": {
                    "raw_official_response": {
                        "type": "Feature",
                        "properties": {
                            "parameter": {
                                "T2M": {"20240401": 10.5, "20240402": 12.0, "20240403": 14.2},
                                "T2M_MAX": {"20240401": 15.0, "20240402": 17.5, "20240403": 20.0},
                                "T2M_MIN": {"20240401": 5.0, "20240402": 6.5, "20240403": 8.0},
                                "PRECTOTCORR": {"20240401": 0.0, "20240402": 5.5, "20240403": 0.0}
                            }
                        }
                    }
                },
                "openet_water": {
                    "raw_official_response": [
                        {"date": "2024-04-01", "et": 2.1},
                        {"date": "2024-04-02", "et": 2.4},
                        {"date": "2024-04-03", "et": 2.8}
                    ]
                }
            },
            "local_user_data": {
                "dated_sensor_readings": [
                    {
                        "timestamp": "2024-04-01T08:00:00Z",
                        "depth_cm": 15.0,
                        "soil_nitrogen_ppm": 35.0,
                        "soil_moisture_vol_pct": 28.0,
                        "soil_ph": 6.8,
                        "soil_compaction_psi": 180.0
                    },
                    {
                        "timestamp": "2024-04-03T16:00:00Z",
                        "depth_cm": 15.0,
                        "soil_nitrogen_ppm": 33.5,
                        "soil_moisture_vol_pct": 26.5,
                        "soil_ph": 6.8,
                        "soil_compaction_psi": 185.0
                    }
                ]
            }
        }
        res = self.client.post("/api/parser/ingest", json=body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["weather_days_count"], 3)
        self.assertEqual(len(data["daily_weather_timeseries"]), 3)
        self.assertEqual(data["daily_weather_timeseries"][0]["date"], "2024-04-01")
        self.assertEqual(len(data["daily_openet_timeseries"]), 3)
        self.assertEqual(data["in_situ_readings_count"], 2)
        self.assertEqual(data["in_situ_earliest_timestamp"], "2024-04-01T08:00:00Z")
        self.assertEqual(data["in_situ_latest_timestamp"], "2024-04-03T16:00:00Z")

    def test_http_endpoint_parser_validate(self):
        """POST /api/parser/validate returns a diagnostic validation report."""
        body = {
            "parcel_info": {
                "parcel_id": "HTTP-TEST-VALIDATE",
                "area_acres": 50.0
            },
            "harvest_history": {
                "historical_seasons": [
                    {"year": 2025, "crop_name": "Winter Wheat"}
                ]
            }
        }
        res = self.client.post("/api/parser/validate", json=body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_valid"])
        self.assertEqual(data["parcel_id"], "HTTP-TEST-VALIDATE")
        self.assertEqual(data["historical_years_found"], 1)
        self.assertIn("audit_messages", data)

    def test_http_endpoint_seed_templates(self):
        """GET /api/parser/seed-templates returns pre-configured seed catalog."""
        res = self.client.get("/api/parser/seed-templates")
        self.assertEqual(res.status_code, 200)
        seeds = res.json()
        self.assertGreater(len(seeds), 5)
        names = [s["crop_name"] for s in seeds]
        self.assertIn("Corn (Maize)", names)
        self.assertIn("Grain Sorghum", names)
        self.assertIn("Processing Tomatoes", names)

        # Filter by name query
        res_filter = self.client.get("/api/parser/seed-templates?crop_name=Tomatoes")
        self.assertEqual(res_filter.status_code, 200)
        filtered = res_filter.json()
        self.assertTrue(all("Tomatoes" in s["crop_name"] for s in filtered))

    def test_http_endpoint_soil_types(self):
        """GET /api/parser/soil-types returns soil hydraulic catalog."""
        res = self.client.get("/api/parser/soil-types")
        self.assertEqual(res.status_code, 200)
        types = res.json()
        self.assertGreater(len(types), 5)
        soil_names = [s["soil_type"] for s in types]
        self.assertIn("Clay Loam", soil_names)
        self.assertIn("Silt Loam", soil_names)
        self.assertIn("Chernozem / Mollisol (Black Soil)", soil_names)

    def test_user_data_layers_on_top_of_nasa(self):
        """User local data (rain gauge, penetrometer, lab tests, in-situ sensors) layers on top of NASA satellite data."""
        payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(
                parcel_id="PRCL-LAYERING-01",
                baseline_soil_type="Clay",
                area_hectares=15.0,
                latitude=42.0,
                longitude=-93.5
            ),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(year=2025, crop_name="Corn (Maize)")
                ]
            ),
            nasa_data=NasaDataPayload(
                nasa_power=NasaPowerPayload(
                    t2m_mean_c=16.0,
                    fao56_et0_annual_mm=1150.0
                ),
                gpm_imerg=GpmImergPayload(
                    annual_rainfall_mm=620.0
                ),
                soilgrids=SoilGridsPayload(
                    texture_class="Clay",
                    soil_organic_carbon_pct=1.65,
                    soil_ph_h2o=6.2
                )
            ),
            local_user_data=LocalUserDataInput(
                soil_type="Silt Loam",  # User lab soil type override
                on_farm_annual_rainfall_mm=780.0,  # User rain gauge layers on top of GPM
                on_farm_mean_temperature_c=17.2,  # User weather station layers on top of POWER
                lab_soil_organic_matter_pct=3.5,  # User lab SOM layers on top of SoilGrids (3.5% SOM -> ~2.03% SOC)
                penetrometer_compaction_psi=265.0,  # User penetrometer layers on top of regional standard
                in_situ_soil_moisture_vol_pct=32.0,  # User probe layers on top of satellite SMAP
                survey_slope_pct=3.5  # User survey layers on top of DEM
            )
        )

        normalized = FieldIngestionParser.parse_and_validate(payload)

        # 1. User soil type overrides SoilGrids
        self.assertEqual(normalized.soil_type, "Silt Loam")
        self.assertEqual(normalized.soil_type_source, "User Local Override")

        # 2. User rain gauge layers on top of NASA GPM
        self.assertEqual(normalized.effective_rainfall_annual_mm, 780.0)
        self.assertEqual(normalized.gpm_imerg_annual_rainfall_mm, 620.0)

        # 3. User weather station layers on top of NASA POWER
        self.assertEqual(normalized.effective_temp_mean_c, 17.2)
        self.assertEqual(normalized.nasa_power_temp_mean_c, 16.0)

        # 4. User lab SOM layers on top of SoilGrids
        self.assertAlmostEqual(normalized.calibrated_soc_pct, 2.03, places=2)
        self.assertEqual(normalized.soilgrids_organic_carbon_pct, 1.65)

        # 5. User penetrometer layers on top of regional standard
        self.assertEqual(normalized.calibrated_compaction_psi, 265.0)

        # 6. User in-situ soil moisture probe layers on top of SMAP
        self.assertEqual(normalized.calibrated_soil_moisture_vol_pct, 32.0)

        # 7. User topographic survey layers on top of DEM
        self.assertEqual(normalized.slope_mean_pct, 3.5)

        # 8. Provenance tracking is fully documented
        prov = normalized.data_layering_provenance
        self.assertIn("soil_texture", prov)
        self.assertIn("annual_rainfall", prov)
        self.assertIn("soil_organic_carbon", prov)
        self.assertIn("soil_compaction", prov)
        self.assertIn("rootzone_moisture", prov)
        self.assertIn("User On-Farm Rain Gauge", prov["annual_rainfall"])
        self.assertIn("User Cone Penetrometer", prov["soil_compaction"])
        self.assertIn("User In-Situ Ground Probe", prov["rootzone_moisture"])
        self.assertIn("User Lab Ground Truth", prov["soil_organic_carbon"])

    def test_v11_rain_gauge_ten_year_threshold(self):
        """Short (<10 yr) on-farm rain-gauge records stay monitoring-only; >=10 yr replaces normals."""
        base_kwargs = dict(
            parcel_info=ParcelInfoInput(parcel_id="RG-TEST", area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(
                historical_seasons=[
                    SeasonalCropRecord(
                        year=2024,
                        crop_name="Corn (Maize)",
                        botanical_family="Poaceae",
                        yield_harvested_tons_ha=9.0,
                        planting_date="2024-04-15",
                        harvest_date="2024-09-25",
                    )
                ]
            ),
            economic_prices=EconomicPricesInput(diesel_fuel_price_usd_liter=1.2, irrigation_water_price_usd_m3=0.05),
            nasa_data=NasaDataPayload(gpm_imerg=GpmImergPayload(annual_rainfall_mm=640.0)),
        )
        short_payload = FullFieldIngestionPayload(
            **base_kwargs,
            local_user_data=LocalUserDataInput(on_farm_annual_rainfall_mm=980.0, on_farm_rain_gauge_years=3),
        )
        n_short = FieldIngestionParser.parse_and_validate(short_payload)
        self.assertEqual(n_short.effective_rainfall_annual_mm, 640.0)
        self.assertEqual(n_short.rain_gauge_monitoring_only_mm, 980.0)
        self.assertIn("monitoring only", n_short.data_layering_provenance["annual_rainfall"])

        extracted_cal = FieldIngestionParser._extract_history_calendars([
            SeasonalCropRecord(year=2024, crop_name="Corn (Maize)", planting_date="2024-04-15", harvest_date="2024-09-25"),
            SeasonalCropRecord(year=2023, crop_name="Processing Tomatoes", planting_date="2023-05-01", harvest_date="2023-08-20"),
            SeasonalCropRecord(year=2022, crop_name="Bell Peppers", planting_date="2022-05-10", harvest_date="2022-09-05"),
        ])
        self.assertIn("corn", extracted_cal)
        self.assertIn("processing_tomatoes", extracted_cal)
        self.assertIn("bell_peppers", extracted_cal)
        self.assertEqual(extracted_cal["corn"]["sowing_month"], 4)
        self.assertEqual(extracted_cal["corn"]["harvest_month"], 9)

        long_payload = FullFieldIngestionPayload(
            **base_kwargs,
            local_user_data=LocalUserDataInput(on_farm_annual_rainfall_mm=980.0, on_farm_rain_gauge_years=12),
        )
        n_long = FieldIngestionParser.parse_and_validate(long_payload)
        self.assertEqual(n_long.effective_rainfall_annual_mm, 980.0)
        self.assertIsNone(n_long.rain_gauge_monitoring_only_mm)

    def test_v11_elemental_npk_conversion_and_product_prices(self):
        """Converts Urea/TSP/KCl product $/t and oxide P2O5/K2O $/kg to elemental $/kg N, P, K."""
        sample_history = [SeasonalCropRecord(year=2024, crop_name="Corn (Maize)", yield_harvested_tons_ha=9.0)]
        prod_payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="FERT-1", area_hectares=5.0),
            harvest_history=HarvestAndCropHistoryInput(historical_seasons=sample_history),
            economic_prices=EconomicPricesInput(
                diesel_fuel_price_usd_liter=1.2,
                irrigation_water_price_usd_m3=0.05,
                urea_price_usd_ton=460.0,
                tsp_price_usd_ton=402.0,
                kcl_price_usd_ton=498.0,
            ),
        )
        n_prod = FieldIngestionParser.parse_and_validate(prod_payload)
        self.assertAlmostEqual(n_prod.elemental_n_price_usd_kg, 1.0, places=3)
        self.assertAlmostEqual(n_prod.elemental_p_price_usd_kg, 2.0, places=3)
        self.assertAlmostEqual(n_prod.elemental_k_price_usd_kg, 1.0, places=3)

        oxide_payload = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="FERT-2", area_hectares=5.0),
            harvest_history=HarvestAndCropHistoryInput(historical_seasons=sample_history),
            economic_prices=EconomicPricesInput(
                diesel_fuel_price_usd_liter=1.2,
                irrigation_water_price_usd_m3=0.05,
                phosphorus_price_usd_kg=1.65,
                potassium_price_usd_kg=0.95,
                fertilizer_price_basis="oxide",
            ),
        )
        n_ox = FieldIngestionParser.parse_and_validate(oxide_payload)
        self.assertAlmostEqual(n_ox.elemental_p_price_usd_kg, 1.65 / 0.4364, places=3)
        self.assertAlmostEqual(n_ox.elemental_k_price_usd_kg, 0.95 / 0.8301, places=3)

    def test_v11_monthly_pm_vs_hargreaves_fallback_and_calcareous_flag(self):
        """Tests PM monthly ET0 vs Hargreaves fallback and pH >= 7.5 unmeasured CaCO3 warning."""
        sample_history = [SeasonalCropRecord(year=2024, crop_name="Corn (Maize)", yield_harvested_tons_ha=9.0)]
        pm_normals = {
            str(m): {
                "t2m_c": 14.0 + (8.0 if 5 <= m <= 8 else -3.0),
                "t2m_max_c": 20.0 + (9.0 if 5 <= m <= 8 else -3.0),
                "t2m_min_c": 8.0 + (7.0 if 5 <= m <= 8 else -3.0),
                "solar_radiation_mj_m2": 18.0 if 5 <= m <= 8 else 9.0,
                "wind_speed_2m_ms": 2.2,
                "dew_point_c": 9.0,
                "precip_mm": 65.0,
            }
            for m in range(1, 13)
        }
        hs_normals = {
            str(m): {
                "t2m_c": 15.0,
                "t2m_max_c": 21.0,
                "t2m_min_c": 9.0,
                "precip_mm": 55.0,
            }
            for m in range(1, 13)
        }
        p_pm = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="PM-1", latitude=45.0, longitude=7.6, area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(historical_seasons=sample_history),
            economic_prices=EconomicPricesInput(diesel_fuel_price_usd_liter=1.2, irrigation_water_price_usd_m3=0.05),
            nasa_data=NasaDataPayload(
                nasa_power=NasaPowerPayload(monthly_normals=pm_normals),
                soilgrids=SoilGridsPayload(
                    raw_official_response={
                        "properties": {
                            "layers": [
                                {"name": "soc", "depths": [{"range": {"top_depth": 0, "bottom_depth": 5}, "values": {"mean": 180}}]},
                                {"name": "cfvo", "depths": [{"range": {"top_depth": 0, "bottom_depth": 5}, "values": {"mean": 150}}]},
                                {"name": "nitrogen", "depths": [{"range": {"top_depth": 0, "bottom_depth": 5}, "values": {"mean": 160}}]},
                                {"name": "phh2o", "depths": [{"range": {"top_depth": 0, "bottom_depth": 5}, "values": {"mean": 79}}]},
                            ]
                        }
                    }
                ),
            ),
        )
        n_pm = FieldIngestionParser.parse_and_validate(p_pm)
        self.assertIn("Penman-Monteith", n_pm.et0_method_used)
        self.assertTrue(n_pm.calcareous_flag)
        self.assertEqual(n_pm.soilgrids_cfvo_pct, 15.0)
        self.assertAlmostEqual(n_pm.soilgrids_total_nitrogen_g_kg, 1.6, places=2)
        self.assertIn("potentially calcareous", n_pm.data_layering_provenance["soil_carbonate"])

        p_hs = FullFieldIngestionPayload(
            parcel_info=ParcelInfoInput(parcel_id="HS-1", latitude=45.0, longitude=7.6, area_hectares=10.0),
            harvest_history=HarvestAndCropHistoryInput(historical_seasons=sample_history),
            economic_prices=EconomicPricesInput(diesel_fuel_price_usd_liter=1.2, irrigation_water_price_usd_m3=0.05),
            nasa_data=NasaDataPayload(nasa_power=NasaPowerPayload(monthly_normals=hs_normals)),
            local_user_data=LocalUserDataInput(lab_caco3_g_kg=120.0, irrigation_method="drip"),
        )
        n_hs = FieldIngestionParser.parse_and_validate(p_hs)
        self.assertIn("Hargreaves", n_hs.et0_method_used)
        self.assertEqual(n_hs.calibrated_caco3_g_kg, 120.0)
        self.assertEqual(n_hs.irrigation_method, "drip")
        self.assertEqual(n_hs.irrigation_efficiency_ea, 0.90)


if __name__ == "__main__":
    unittest.main()
