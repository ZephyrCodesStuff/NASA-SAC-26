# Parcel Data API — design

## Why
The farm advisory app needs, for one farm field, the values of every global dataset in
the team's dataset list. The field arrives as a parcel from the Italian cadastre
(Catasto, Agenzia delle Entrate), produced by a separate team API that forwards the
cadastre's XML unchanged.

## Input
`POST /geojson` with GeoJSON (what `web/src/providers/catasto.py` already produces), or
`POST /parcel` with the raw cadastre WFS response as the body:
GML 3.2, `CP:CadastralParcel` features, CRS EPSG:6706 (RDN2008, **lat/lon axis order**).
One request may contain several parcels; each gets its own result.
Convenience: `GET /point?lat=..&lon=..` builds a ~30 m square around a point (for testing / non-cadastre use).

Query options: `history=true` adds time series; `start`, `end` (ISO dates) set the history window
(default: last 90 days, capped at 365).

## Output (per parcel)
```
parcel:   id, comune code, foglio, particella, area_ha, centroid, bbox
datasets: { <name>: { status: ok|no_data|error|unavailable, scale: field|area,
                      resolution_m, date, values{...}, units{...}, history[...]?, note? } }
```
`scale` tells the app whether the value describes the field itself (HLS, ECOSTRESS, NASADEM)
or the surrounding area (everything ≥ 250 m). Italian parcels are often < 1 ha.

## Sources and access (all verified against a Modena parcel, 2026-11-14)
| Dataset | Access | Notes |
|---|---|---|
| NASA POWER | REST, no auth | ~2–3 day latency, -999 → null. Computes GDD (base 10 °C) since 1 Jan. |
| GPM IMERG Late daily | HTTPS range read (h5) | needs "NASA GESDISC DATA ARCHIVE" approved on the Earthdata account |
| SMAP L4 (SPL4SMGP) | HTTPS range read (h5) | surface + root-zone, 9 km, 3-hourly |
| ECOSTRESS ET + ESI | COG via CMR-STAC | 70 m, irregular overpasses; latest *valid* one used |
| MODIS MOD16A2 ET | ORNL subset REST, no auth | 500 m, 8-day; service is slow (~50 s) |
| HLS L30/S30 | COG via CMR-STAC | NDVI, NDWI, NDRE (S30 only); Fmask clouds removed; latest scene with clear pixels on the parcel |
| SoilGrids | COG/VRT from files.isric.org, no auth | 0–30 cm; values converted to normal units |
| GRACE-FO mascon | HTTPS range read (nc) | monthly, ~300 km, regional context only |
| NASADEM | tile zip downloaded once, cached | elevation + slope over parcel |
| WorldCereal | **not yet** | only global 15–25 GB zips or Earth Engine; deferred |

## Approaches considered
1. **Direct cloud reads per request (chosen)** — reads only the needed bytes from NASA cloud files; one call ≈ 10–60 s, no queue.
2. AppEEARS for everything — one tool, but async jobs take minutes to hours; unusable behind a live call.
3. Pre-download a regional data cube — fastest responses, but large storage and a daily ingest job; overkill for the hackathon.

## Behaviour
- Each source runs in parallel with its own timeout; one failing source never fails the response.
- Results cached in memory (TTL ~6 h); DEM tiles cached on disk.
- Credentials: Earthdata Login via `~/.netrc` (or `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD`). Never stored in the repo.

## Non-goals
Advice/decision logic (that's the app), storing farms, a UI.
