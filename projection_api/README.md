# Field Input Ingestion & Parser API

A robust, high-performance agricultural REST API and ingestion parser. Built to ingest, validate, audit, and normalize multi-source agricultural datasets—preserving full dated timeseries rather than just averages—into a unified field profile:

1. 📍 **Parcel Info & Soil Type**: Cadastral identifier, boundary GeoJSON, coordinates, area (acres/ha), legal water quota, and baseline soil type.
2. 🌾 **Harvest & Crop History**: Flexible 1 to 5 past seasons (yields, planting/harvest dates, applied NPK, irrigation, and pest outbreaks; auto-trimmed to 5 if $>5$ provided).
3. 🚜 **Seed Data & Economic Prices**:
   - Consumable prices: Diesel ($/L), water ($/m³), electricity ($/kWh), elemental NPK ($/kg), and labor ($/hr).
   - Seed varieties specifications:
     * **Greenhouse Need**: `Open Field Only`, `Open Field or Greenhouse Compatible`, `Greenhouse Recommended`, `Greenhouse Required (Protected Cultivation)`.
     * **Extreme Events Resistance**: Quantitative ratings (1.0 to 5.0) for Drought, Flood/Waterlogging, High Wind/Lodging, Frost/Cold Snaps, Extreme Heat, and Salinity.
4. 🛰️ **NASA Earth Observations (Official Database Formats & Dated Timeseries)**:
   - **NASA POWER**: Full daily weather parameters (`T2M`, `T2M_MAX`, `T2M_MIN`, `PRECTOTCORR`, `ALLSKY_SFC_SW_DWN`, `RH2M`, `WS2M`) with exact dates.
   - **NASA GPM IMERG**: Full daily rainfall series with storm event tracking and peak storm date.
   - **NASA SMAP L4**: Surface (0–5 cm) & root-zone (0–100 cm) volumetric moisture records with dates.
   - **NASA OpenET**: Actual evapotranspiration ($ET_a$) daily/monthly records with dates.
   - **NASA ECOSTRESS**: Thermal infrared canopy temperature and Evaporative Stress Index (ESI) scenes with timestamps.
   - **Harmonized Landsat-Sentinel (HLS)**: Multispectral NDVI, NDRE, NDWI satellite overpass scenes with dates.
   - **SoilGrids 2.0 / gSSURGO**: Depth-stratified horizon layers (0–5cm, 5–15cm, 15–30cm, 30–60cm, 60–100cm).
   - **NASA GRACE**: Monthly deep aquifer liquid water equivalent (LWE) thickness anomaly timeseries.
5. 🌡️ **Long-Term Weather Projections**: Optional climate scenario projections (CMIP6 SSP2-4.5 / SSP5-8.5), decadal warming shifts (°C), and precipitation delta %.
6. 🔬 **Local User Telemetry with Date Signatures**: In-situ ground sensors with exact timestamps/dates (`soil_nitrogen_ppm`, `soil_phosphorus_ppm`, `soil_potassium_ppm`, `soil_moisture_vol_pct`, `soil_ph`, `soil_ec_salinity_ds_m`, `soil_organic_matter_pct`, `soil_compaction_psi`, `depth_cm`), tracking temporal changes across the season.
7. 🗺️ **Elevation Maps**: Digital Elevation Model (DEM) metrics, mean/max slope %, solar aspect, topographic wetness index, waterlogging depressions, and erosion susceptibility.

---

## 📅 Official NASA Data Formats & User Date Signatures

The parser operates on the core philosophy of **maximizing temporal resolution and retaining full dated timeseries** for downstream prediction algorithms:

### 1. NASA POWER (Official Daily Feature Format)
Accepts the raw point response from the official NASA POWER API (`raw_official_response`):
```json
{
  "nasa_power": {
    "raw_official_response": {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-93.5, 41.5, 280.0] },
      "properties": {
        "parameter": {
          "T2M": { "20240401": 10.5, "20240402": 12.0, "20240403": 14.2 },
          "T2M_MAX": { "20240401": 15.0, "20240402": 17.5, "20240403": 20.0 },
          "T2M_MIN": { "20240401": 5.0, "20240402": 6.5, "20240403": 8.0 },
          "PRECTOTCORR": { "20240401": 0.0, "20240402": 12.4, "20240403": 0.0 },
          "ALLSKY_SFC_SW_DWN": { "20240401": 18.2, "20240402": 14.5, "20240403": 19.8 }
        }
      }
    }
  }
}
```
*The parser normalizes date strings (`20240401` $\rightarrow$ `2024-04-01`), preserves every daily record in `daily_weather_timeseries`, computes cumulative GDD base 10°C, and calculates frost days, extreme heat days, and dry-spell streaks.*

### 2. User In-Situ Sensors (With Date Signatures)
Accepts multiple dated readings taken over time (`dated_sensor_readings`):
```json
{
  "local_user_data": {
    "dated_sensor_readings": [
      {
        "timestamp": "2025-04-10T09:30:00Z",
        "depth_cm": 15.0,
        "soil_nitrogen_ppm": 42.0,
        "soil_moisture_vol_pct": 31.5,
        "soil_ph": 6.80,
        "soil_compaction_psi": 175.0,
        "device_model": "Spectrum FieldScout TDR-350"
      },
      {
        "timestamp": "2025-05-18T14:15:00Z",
        "depth_cm": 15.0,
        "soil_nitrogen_ppm": 30.0,
        "soil_moisture_vol_pct": 25.0,
        "soil_ph": 6.78,
        "soil_compaction_psi": 195.0
      },
      {
        "timestamp": "2025-06-25T11:00:00Z",
        "depth_cm": 15.0,
        "soil_nitrogen_ppm": 18.5,
        "soil_moisture_vol_pct": 19.2,
        "soil_ph": 6.75,
        "soil_compaction_psi": 230.0
      }
    ]
  }
}
```
*The parser sorts all readings chronologically, retains the complete timeseries in `dated_in_situ_sensors`, tracks in-situ drawdown trends, and calibrates baseline properties using the most recent reading.*

### 3. OpenET & Satellite Scenes
- **OpenET**: Accepts official REST API arrays `[{"date": "2024-05-01", "et": 3.8}, {"date": "2024-05-02", "et": 4.1}]`.
- **HLS**: Accepts multispectral overpasses and extracts the peak NDVI value alongside the exact `peak_ndvi_date`.
- **SoilGrids**: Accepts depth-stratified horizon layers (0–5cm, 5–15cm, 15–30cm, 30–60cm, 60–100cm) or raw ISRIC JSON responses.

---

## 🏗️ Soil Type Priority Resolution

1. **User Local Override** (`local_user_data.soil_type`): In-situ test or grower field knowledge *(highest priority)*.
2. **Parcel Declared** (`parcel_info.soil_type`): Cadastral or land registry classification.
3. **Satellite Derived** (`nasa_data.soilgrids.texture_class`): NASA / ISRIC SoilGrids 2.0.
4. **Calibrated Baseline**: Regional agro-ecological benchmark when all inputs are absent.

Supported standard classifications:
`Clay`, `Clay Loam`, `Silty Clay`, `Silty Clay Loam`, `Silt Loam`, `Silt`, `Loam`, `Sandy Clay`, `Sandy Clay Loam`, `Sandy Loam`, `Loamy Sand`, `Sand`, `Peat / Organic Muck`, `Chernozem / Mollisol (Black Soil)`, `Calcareous / Chalky Soil`, `Alluvial / Riverbed Soil`.

---

## 🌱 Seed Characteristics Schema

```json
{
  "crop_name": "Grain Sorghum",
  "variety_or_hybrid_name": "AridMax Ultra",
  "seed_cost_usd_per_ha": 85.0,
  "seeding_rate_kg_ha": 9.0,
  "greenhouse_need": "Open Field Only",
  "can_grow_in_greenhouse": false,
  "requires_greenhouse": false,
  "extreme_event_resistance": {
    "drought_resistance": "Very High (Extreme Tolerance)",
    "drought_tolerance_score": 4.8,
    "flood_waterlogging_resistance": "Moderate (Average Resilience)",
    "flood_tolerance_score": 3.0,
    "wind_lodging_resistance": "High",
    "wind_tolerance_score": 4.2,
    "frost_cold_resistance": "Moderate (Average Resilience)",
    "frost_tolerance_score": 2.8,
    "extreme_heat_resistance": "Very High (Extreme Tolerance)",
    "heat_tolerance_score": 4.7,
    "salinity_tolerance": "High"
  }
}
```

---

## 🔌 API Endpoints

- `POST /api/parser/ingest`: Full multi-domain ingestion, preserving dated timeseries, unit harmonization (acres ↔ ha, GeoJSON centroid), soil resolution, and seed categorization.
- `POST /api/parser/validate`: Lightweight validator checking payload integrity, completeness score (0–100%), and resilience highlights.
- `GET /api/parser/seed-templates`: Scientific seed templates with greenhouse requirements and extreme event resistance profiles (supports `?crop_name=` filter).
- `GET /api/parser/soil-types`: Standard soil hydraulic properties catalog (drainage, available water capacity, compaction risk).

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
python -m pip install -r projection_api/requirements.txt
```

### 2. Run Test Suite
```bash
python -m unittest projection_api/test_parser.py
```

### 3. Start the FastAPI Server
```bash
python -m uvicorn projection_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive Swagger UI: `http://localhost:8000/docs`
