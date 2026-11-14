# Data catalog — everything `data-api` can return

Spreadsheet version: [data-catalog.csv](data-catalog.csv).

One page listing every piece of data the backend can get for a farm parcel: where it comes from, how
detailed it is and what each field means. For how to call the API from `web/`, see
[data-api-for-web.md](data-api-for-web.md).

- **Scale** says what the number describes. `field` = measured on the parcel itself (30–70 m pixels).
  `area` = the surroundings (250 m – 300 km). `country` / `global` = national or world statistics.
- **Freshness** says how far behind real time the data runs.
- Every dataset entry has the same envelope: `status` (`ok` · `no_data` · `error` · `timeout` · `unavailable`),
  `scale`, `resolution_m`, `source`, `date`, `values`, `units`, `note`, and optionally `history` and `periods`.

## Endpoints

| Call | What you get |
|---|---|
| `POST /geojson` (GeoJSON parcel) · `POST /parcel` (catasto GML) · `GET /point?lat&lon` | All datasets below for the parcel |
| `?datasets=a,b` | Only these datasets |
| `?history=true&start&end` | Adds `history` time series (max 365 days; default the last 90) |
| `?year=true` | Last 12 months of history **plus `periods`: 24 half-month summaries** (1st–15th, 16th–end of month) |
| `POST /imagery` (GeoJSON) · `GET /imagery/point?lat&lon` | Parcel images: true colour, infrared, SWIR, NDVI, NDMI, NDRE, thermal, surface temperature, elevation, hillshade, slope |
| `…/imagery?layer=ndvi` | One image as `image/png` (for `<img src>`) |
| `GET /layers` | NASA GIBS map tile layers (rain, soil moisture, NDVI, temperature, relief, 30 m imagery) for Leaflet |
| `GET /periods` | The 24 periods `year=true` uses right now |
| `GET /datasets` | Dataset names and descriptions |

## Your wish list → where it comes from

| Wanted | Dataset / field | Scale | Status |
|---|---|---|---|
| Parcel info | catasto (web), `parcel` block of every response | field | ✅ |
| Last year of data for everything, in 24 periods | `?year=true` → `periods` on every time-series dataset | — | ✅ |
| Rainfall | `rainfall` (IMERG daily), `weather.PRECTOTCORR` | area 11 km / 55 km | ✅ |
| Soil moisture | `soil_moisture` (SMAP L4) | area 9 km | ✅ |
| Humidity | `weather.RH2M`, `weather.T2MDEW` | area 55 km | ✅ |
| Daylight amount | `weather.daylight_h`, `sunshine_fraction`, `ALLSKY_SFC_SW_DWN` | computed / area | ✅ |
| Climate & temperature | `weather` (daily, 1991–2020 normals, extremes), `evapotranspiration_field.lst` | area / field | ✅ |
| Extreme temperatures through the seasons | `weather.extremes_last_365_days`, `periods[].T2M_MAX/T2M_MIN/frost_days/heat_days_over_35c` | area | ✅ |
| Altitude, steepness | `terrain` (NASADEM), `/imagery` elevation/slope/hillshade, `/layers` shaded relief | field 30 m | ✅ |
| Elevation maps | `/imagery` group `dem`, `/layers.shaded_relief_*` | 30 m | ✅ |
| Water stress in the region (and projection) | `evapotranspiration_field.esi`, `evapotranspiration_area.et_pet_ratio`, `groundwater`, `climate_projection` | field → regional | ✅ |
| Drought risk for upcoming years | `climate_projection.projections.*.drought_risk` | area 25 km | ✅ |
| Long-term weather projections | `climate_projection` (2030s, 2050s; two scenarios) | area 25 km | ✅ |
| Erosion risk | `erosion` (RUSLE) | field | ✅ |
| Resistance to floods / winds | `weather.extremes_last_365_days` (heavy-rain days, gale days), `terrain.low_spot` | area / field | ✅ |
| Last 5 years of crops on the field | `crop_history` (crop **group** per year, from the NDVI curve) | field 30 m | ✅ (group, not species) |
| Last 5 years of harvests | `regional_production` (national yield, production, area) | country | ✅ (national) |
| Raw crop prices | `local_prices.crop_selling_prices` (EU, farm-gate, yearly), `regional_production` (FAO), `market_prices` (world, monthly) | country / global | ✅ |
| Oil, fertilizer prices | `local_prices.fuel` (diesel, heating oil, weekly, EU), `market_prices` (crude oil, gas, urea, DAP, potash…) | country / global | ✅ |
| Electricity and heating (gas) prices | `local_prices.energy` (Eurostat, business tariffs, half-yearly, EU) | country | ✅ national average |
| Satellite images in different spectra | `/imagery` | field 30–70 m | ✅ |
| Multi-layer map | `/layers` | tiles | ✅ |
| Seed prices | — no public global source → farmer input | | ❌ |
| Water price, water/electricity connection | — local irrigation-consortium fees → farmer input | | ❌ |
| Weekly prices on named markets (e.g. Milan, Vercelli) | `local_prices.market_prices_weekly` (EU Agri-food Data Portal) | market | ⚠ API often down / rate-limited |
| Exact crop species per year | — needs farmer input or a regional crop map (WorldCereal only covers 2021) | | ⚠ |
| EU "agricultural production hotspots" (JRC ASAP) | — covers food-insecure countries, not Europe | | ❌ not applicable |
| AI news on past extreme weather, sensor API, admin stats | — not data-api (separate services) | | — |

---

## Parcel datasets (`/geojson`, `/parcel`, `/point`)

### `weather` — NASA POWER (daily) + 1991–2020 normals
Scale `area`, ~55 km · freshness 2–3 days · no login.

`values`
| field | meaning |
|---|---|
| `latest` | Newest complete day; contains every daily field below |
| `today.daylight_h` | Hours from sunrise to sunset today (computed astronomically) |
| `today.daylight_h_longest_day` / `_shortest_day` | Same, on 21 June / 21 December |
| `last_7_days.precip_mm` · `t_max_c` · `t_min_c` · `rh_mean_pct` · `frost_days` · `heat_days_over_35c` | Last-week summary |
| `last_30_days.precip_mm` · `evapotranspiration_mm` · `t_mean_c` · `rh_mean_pct` · `sunshine_fraction` | Last-month summary |
| `last_30_days.normal_t_mean_c_this_month` · `normal_precip_mm_per_day_this_month` | The 1991–2020 normal, for comparison |
| `gdd_since_jan1.value` | Growing degree days since 1 January, base 10 °C |
| `extremes_last_365_days` | `hottest_day`, `coldest_night`, `wettest_day`, `windiest_day` (each with a date); counts of `frost_days`, `heat_days_over_35c`, `heavy_rain_days_over_30mm`, `gale_days_wind_over_10_8ms`; `longest_dry_spell_days`; `total_precip_mm` |
| `normals_1991_2020.{jan…dec,ann}` | Monthly 30-year means of `T2M`, `T2M_MAX`, `T2M_MIN`, `PRECTOTCORR` (mm/day), `RH2M`, `ALLSKY_SFC_SW_DWN` |

Daily row (`latest`, `history[]`)
| field | unit | meaning |
|---|---|---|
| `date` | | day |
| `T2M`, `T2M_MAX`, `T2M_MIN` | °C | air temperature at 2 m: mean, max, min |
| `T2MDEW` | °C | dew point |
| `RH2M` | % | relative humidity |
| `PRECTOTCORR` | mm/day | precipitation (bias-corrected) |
| `ALLSKY_SFC_SW_DWN` | MJ/m²/day | solar radiation at the surface |
| `WS2M`, `WS2M_MAX` | m/s | wind at 2 m: mean and max |
| `EVPTRNS` | mm/day | evapotranspiration (model) |
| `daylight_h` | h | sunrise to sunset |
| `sunshine_fraction` | 0–1 | measured radiation / clear-sky radiation (1 = cloudless) |
| `gdd` | °C·day | growing degree days that day |
| `frost_days`, `heat_days_over_35c` | 0/1 | flags (summed in `periods`) |

`periods[]` (with `year=true`): `period` (e.g. `2026-03-H1`), `start`, `end`, `observations`, then every daily
field. Rain, ET, GDD and day counts are **summed**. `*_MAX` is the period maximum and `*_MIN` the minimum.
Everything else is averaged.

### `rainfall` — GPM IMERG Late, daily
Scale `area`, 0.1° (~11 km) · freshness ~1 day · Earthdata login (GES DISC).

| field | meaning |
|---|---|
| `latest_day` | `{date, precip_mm}` |
| `total_3d_mm`, `total_7d_mm`, `total_30d_mm` | Rain totals |
| `consecutive_dry_days` | Days in a row with < 1 mm, up to the latest day |
| `history[]` / `periods[]` | `{date, precip_mm}` daily / summed per period |

### `soil_moisture` — SMAP L4 (model + satellite)
Scale `area`, 9 km · freshness 3–4 days · Earthdata.

| field | unit | meaning |
|---|---|---|
| `surface_m3m3` | m³/m³ | water in the top 0–5 cm |
| `rootzone_m3m3` | m³/m³ | water in 0–100 cm |
| `rootzone_wetness` | 0–1 | fraction of saturation (0 dry, 1 saturated) |
| `time`, `cell_center` | | granule time and 9 km cell centre |
| `history[]` | | `{date, surface_m3m3, rootzone_m3m3}`, ~30 samples (~48 with `year=true`) |

### `evapotranspiration_field` — ECOSTRESS (ISS), 70 m
Scale `field` · freshness: irregular overpasses, the newest valid daytime one · Earthdata.

| field | unit | meaning |
|---|---|---|
| `et_daily.{mean,min,max,pixels,datetime}` | mm/day | actual water use of the crop that day |
| `esi.{…}` | 0–1 | evaporative stress index = actual / potential ET; low = water stress |
| `lst.{…}` | °C | land-surface temperature, cloud-masked |
| `history.{et_daily,esi,lst}[]` | | all valid overpasses in the window |

### `evapotranspiration_area` — MODIS MOD16A2, 500 m, 8-day
Scale `area` · freshness 2–4 weeks · no login (ORNL; slow).

| field | meaning |
|---|---|
| `date` | start of the 8-day composite |
| `et_mm_8day`, `pet_mm_8day` | actual / potential ET over 8 days (mm) |
| `et_mm_per_day` | `et_mm_8day / 8` |
| `et_pet_ratio` | 0–1; low = water-limited |

### `crop_health` — HLS (Landsat 8/9 + Sentinel-2), 30 m
Scale `field` · freshness 2–5 days (needs a clear sky) · Earthdata.

| field | meaning |
|---|---|
| `date`, `scene`, `sensor`, `clear_fraction`, `pixels` | the scene used |
| `ndvi.{mean,min,max,std}` | vegetation vigour (−1…1) |
| `ndmi.{…}` | canopy water (NIR/SWIR) |
| `ndre.{…}` | chlorophyll / nitrogen (Sentinel-2 only) |
| `low_vigor_fraction` | share of the field with NDVI more than 0.1 below the field median (patchiness) |
| `history[]` | `{date, sensor, ndvi, ndmi, ndre}` for every clear scene |

### `soil` — ISRIC SoilGrids 2.0, 250 m
Scale `area` · static.

`values["0-5cm" | "5-15cm" | "15-30cm" | "30-60cm"]`:
| field | unit | meaning |
|---|---|---|
| `clay`, `sand`, `silt` | % | texture |
| `texture_class` | | USDA class (e.g. "silt loam") |
| `soc` | g/kg | soil organic carbon |
| `phh2o` | pH | acidity |
| `nitrogen` | g/kg | total nitrogen |
| `cec` | cmol(c)/kg | nutrient-holding capacity |
| `bdod` | g/cm³ | bulk density (compaction) |

### `groundwater` — GRACE / GRACE-FO mascons
Scale `area`, ~300 km · freshness 2–4 months · Earthdata.

| field | meaning |
|---|---|
| `latest.{month, anomaly_cm}` | water storage vs the 2004–2009 mean (cm of water) |
| `trend_last_12_months_cm` | change over the last 12 months |
| `percentile_vs_same_month_all_years` | 0–100 (low = drier than usual for this month) |
| `interpretation` | "drier than usual" · "near normal" · "wetter than usual" |
| `history[]` | `{month, anomaly_cm}` since 2002 |

### `terrain` — NASADEM, 30 m
Scale `field` · static.

| field | meaning |
|---|---|
| `elevation_m.{mean,min,max}` | altitude (m) |
| `slope_deg.{mean,max}` | steepness (°), per pixel. On flat land this reads ~1° from DEM noise |
| `field_gradient_deg` | overall tilt of the field (least-squares plane over the parcel); used by `erosion` |
| `aspect_deg` | direction the slope faces (0 = north) |
| `share_steeper_than_8deg` | 0–1 |
| `relative_elevation_m` | parcel minus surroundings (~300 m); negative = lower ground |
| `low_spot` | true if > 1 m below the surroundings (waterlogging / frost-pocket risk) |

### `crop_history` — what grew here in the last 5 years (HLS NDVI phenology)
Scale `field` 30 m · cached 30 days · Earthdata · ~60–70 s the first time.

`values.seasons[]` (one per year; the current year is partial):
| field | meaning |
|---|---|
| `year`, `complete`, `observations` | year, whether it is finished, how many of the 24 half-months were cloud-free |
| `crop_group` | e.g. "winter cereal (wheat / barley) or rapeseed", "summer crop (maize, soybean, sunflower, sorghum)", "rice (flooded in spring, green in summer)", "double crop…", "permanent grassland, meadow or perennial…", "vineyard, orchard or sparse crop", "bare soil / fallow…", "mixed / unclear" |
| `confidence` | `medium` · `low` · `none` |
| `peak_ndvi`, `peak_period` | greenest value and when (e.g. `08-H1` = 1–15 August) |
| `green_season` | e.g. `07-H1 → 09-H2` |
| `flooded_in_spring` | water seen under the young crop in April–May (rice) |

`values.most_common_crop_group`, `values.rotates` (true if the group changes between years).
`history[].ndvi_by_period[]` = 24 points per year `{period, date, ndvi, ndmi}`, ready for a season-curve chart.

### `climate_projection` — NASA NEX-GDDP-CMIP6, 0.25° (~25 km)
Scale `area` · cached 90 days · no login · ~1 min the first time.

`values.baseline_2000s` and `values.projections.{ssp245,ssp585}_{near_2030s,mid_2050s}`:
| field | unit | meaning |
|---|---|---|
| `precip_mm` | mm/yr | annual rain |
| `pet_mm` | mm/yr | reference evapotranspiration (Hargreaves) |
| `water_balance_mm` | mm/yr | rain − PET (negative = deficit) |
| `summer_precip_mm` | mm | June–August rain |
| `t_max_summer_c` | °C | mean June–August daily maximum |
| `heat_days_over_35c`, `frost_days` | days/yr | |
| `longest_dry_spell_days` | days | longest run of days with < 1 mm |
| `max_1day_precip_mm` | mm | wettest day (flood proxy) |
| `water_balance_change_mm`, `summer_precip_change_pct`, `dry_spell_change_days`, `heat_days_change` | | change vs baseline (projections only) |
| `drought_risk` | | `low` · `moderate` · `high` · `very high` |

`values.headline` = drought risk for SSP2-4.5 in the 2050s.
`periods[]` = 24 calendar half-months (`01-H1` … `12-H2`) with `{precip_mm, t_max_c, water_balance_mm}` for
`baseline`, `ssp245_mid_2050s` and `ssp585_mid_2050s`: the seasonal shape today vs 2050.
Two models (ACCESS-CM2, MPI-ESM1-2-HR) with two sampled years per window: a trend indicator, not a forecast.

### `erosion` — RUSLE, computed (no extra download)
Scale `field` · fetches `soil`, `terrain`, `weather` and `crop_health` automatically if not requested.

| field | meaning |
|---|---|
| `slope_deg` | the field gradient used for LS (falls back to the mean pixel slope) |
| `r_factor` | rainfall erosivity, MJ·mm/(ha·h·yr), from 30-year annual rain |
| `k_factor` | soil erodibility, from topsoil texture + organic carbon |
| `ls_factor` | slope steepness × length |
| `c_factor_current` | cover factor from the current NDVI (1 = bare) |
| `p_factor` | conservation practice (1 = none) |
| `soil_loss_bare_t_ha_yr`, `risk_bare` | worst case: bare soil |
| `soil_loss_current_cover_t_ha_yr`, `risk_current_cover` | with today's vegetation |
| `annual_precip_mm`, `slope_deg`, `slope_length_m` | inputs used |

To compare crops: `soil_loss_bare × crop C` (maize ≈ 0.38, wheat ≈ 0.20, meadow ≈ 0.01). Classes: < 2 low,
2–5 moderate, 5–10 high, > 10 very high t/ha/yr (EU tolerable ≈ 1.4).

### `regional_production` — FAOSTAT (national)
Scale `country` · yearly, lags 1–2 years · no login.

| field | meaning |
|---|---|
| `country.{name, iso2, iso3, m49}` | country of the parcel |
| `crops[]` | the country's top 30 crops by harvested area |
| `crops[].crop` | FAO crop name (e.g. "Maize (corn)", "Rice", "Wheat") |
| `crops[].latest` / `years[]` | per year (last 10): `area_harvested_ha`, `yield_kg_per_ha`, `production_t`, `producer_price_usd_per_t`, `producer_price_lcu_per_t` (local currency, EUR in Italy) |

Profit formula input: projected harvest ≈ `field area × yield_kg_per_ha`, priced at `producer_price_lcu_per_t`.

### `market_prices` — World Bank Pink Sheet (monthly world prices)
Scale `global` · monthly · no login.

`values.<key>` = `{name, group, unit, latest {month, price}, change_12m_pct}` and `history.<key>[]` = last 60
months. Keys:
- energy: `crude_oil_avg`, `crude_oil_brent`, `natural_gas_europe`
- fertilizer: `urea`, `dap`, `tsp`, `potassium_chloride`, `phosphate_rock`
- crops: `maize`, `wheat_us_hrw`, `wheat_us_srw`, `barley`, `sorghum`, `rice_thai_5pct`, `soybeans`, `sugar_eu`, `orange`, `banana_europe`
- vegetable oils: `soybean_oil`, `sunflower_oil`, `rapeseed_oil`, `palm_oil`

Units are USD per bbl / mmbtu / mt (metric tonne) / kg.

### `local_prices` — national prices for EU parcels
Scale `country` · Eurostat, EU Weekly Oil Bulletin, EU Agri-food Data Portal · no login. Status is
`unavailable` outside the EU. If one sub-source fails, the others are still returned and `errors` names it.

| field | unit | meaning |
|---|---|---|
| `country` | | country of the parcel |
| `crop_selling_prices[].crop` | | Eurostat crop name (e.g. "Soft wheat", "Durum wheat", "Maize", "Rice") |
| `crop_selling_prices[].latest` / `years[]` | EUR/t | farm-gate selling price per year (last ~6 years) |
| `energy.electricity.{MWH20-499, MWH500-1999}` | EUR/kWh | business electricity price for a small / large farm, `excl_taxes[]` and `incl_all_taxes[]`, per half-year |
| `energy.natural_gas.GJ1000-9999` | EUR/kWh | business gas price (greenhouse-heating scale), excluding / including taxes |
| `fuel.diesel` · `fuel.heating_oil` | EUR/litre | weekly, last 52 weeks: `with_taxes[]`, `without_taxes[]`, `latest_with_taxes`, `latest_without_taxes` |
| `market_prices_weekly.{cereal,rice,oilseeds,fertiliser}` | as published | weekly prices on named markets. Best effort, because the EU API is often down. |

Italian farm diesel (gasolio agricolo) is tax-reduced, so the real price lies between `without_taxes` and
`with_taxes`. Irrigation water (local consortium fees) and seeds stay farmer inputs.

### `crop_type` — not available
ESA WorldCereal 2021 is only distributed as very large global archives. It is listed as `unavailable`.

---

## Images (`/imagery`)

Response: `parcel`, `groups.{hls,lst,dem}`, `descriptions`, `ramps`. Each group has `status`, `source`,
`date`, `bounds` `[[south, west], [north, east]]` (for `L.imageOverlay`), `pixel_size_m`, `legends` and
`layers.<name>` = PNG data URI. Pixels outside the parcel are dimmed and the parcel is outlined in white.

| group | layer | what it shows |
|---|---|---|
| `hls` (30 m, newest scene clear over the parcel) | `true_color` | natural colour |
| | `color_infrared` | NIR-R-G: healthy crops bright red |
| | `agriculture` | SWIR1-NIR-B: crops green, bare soil magenta |
| | `swir_moisture` | SWIR2-SWIR1-R: wet soil dark, dry soil bright |
| | `ndvi` | vigour, −0.2 → 0.9 |
| | `ndmi` | water content, −0.4 → 0.6 |
| | `ndre` | chlorophyll / N (Sentinel-2 scenes) |
| | `thermal` | Landsat thermal, °C (Landsat scenes) |
| `lst` (70 m) | `lst` | ECOSTRESS surface temperature, °C |
| `dem` (30 m) | `elevation`, `hillshade`, `slope` | NASADEM terrain |

`legends.<layer>` = `{min, max, unit?, ramp, parcel_mean?}`. `?date=YYYY-MM-DD` uses the newest clear scene on or
before that date. `?groups=hls` limits the work. `?layer=ndvi` returns that PNG directly.

## Map layers (`/layers`)

`layers.<key>` = `{group, description, gibs_layer, url, default_time, max_native_zoom, legend_url, attribution}`.
Use `url.replace('{time}', default_time)` as a Leaflet tile URL; change the date to browse history.

| key | what |
|---|---|
| `true_color_hls_sentinel2`, `true_color_hls_landsat` | 30 m true colour (zoom ≤ 12) |
| `true_color_modis`, `false_color_modis_721` | daily 250 m imagery |
| `precipitation` | IMERG rain rate |
| `soil_moisture_rootzone` | SMAP root-zone soil moisture |
| `surface_water` | OPERA surface water (flooding, irrigation) |
| `groundwater_anomaly` | GRACE water storage |
| `ndvi_modis_16day`, `ndvi_viirs_8day`, `leaf_area_index` | vegetation |
| `land_surface_temp_day` | MODIS daytime surface temperature |
| `shaded_relief_color`, `shaded_relief_grey` | altitude / relief (no date) |

## Speed

Everything is cached (memory + disk, survives restarts). Cold times for a new parcel: weather ~2 s, soil/terrain
a few s, rainfall ~10–60 s, crop health ~10–40 s, ECOSTRESS ~15 s, SMAP ~20 s, MODIS 30–120 s, crop history
~60–70 s, climate projection ~60 s (shared per 25 km cell), FAOSTAT ~5 s (shared per country), prices < 1 s,
imagery ~25 s. `year=true` is slower the first time (a full year of every series). Warm the demo parcels
in advance.
