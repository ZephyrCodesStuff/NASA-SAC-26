# AGENTS.md

## Project Overview
- **Event:** NASA Space Apps Challenge 2026 (Turin / Global) — Crop Rotation Decision-Support Challenge.
- **Goal:** Help farmers select resilient 3-year crop rotations by combining NASA Earth observations, cadastral/OSM field boundaries, local soil inputs, and farmer priorities.
- **Core Design Principle:** **Deterministic math first, AI for plain-language translation.** All water, erosion, and nitrogen calculations must come from credited agronomic equations in Python. LLMs only translate computed JSON metrics into farmer-friendly trade-offs and local verification checklists—never invent or alter numerical outputs.

## Tech Stack & Commands
- **Frontend & Backend:** Python 3.12+, **NiceGUI** (FastAPI + Vue/Quasar + `ui.leaflet` + `ui.echart`).
- **Database & Cache:** **PocketBase** (SQLite + admin UI + response cache).
- **Local Dev (M4 Mac):**
  - Terminal 1 (PocketBase native `darwin_arm64` binary): `./pb/pocketbase serve`
  - Terminal 2 (NiceGUI hot-reload): `uv run python main.py` (or `python main.py`)
- **Production:** `docker compose up --build -d` (runs `pocketbase` and `app` containers; NiceGUI talks to `http://pocketbase:8090` internally).

## Module Boundaries
- `src/formulas.py` — **Pure deterministic math only.** No network calls, no LLM calls, no UI imports. Implements:
  1. **FAO-56 Water Balance:** $ET_c = K_c \times ET_0$ and net deficit $\Delta W = P_{\text{eff}} - ET_c$.
  2. **RUSLE Topsoil Erosion:** $A = R \cdot K \cdot LS \cdot C \cdot P$ (deriving cover factor $C$ from MODIS NDVI across bare vs. vegetated months).
  3. **FAO/IPCC Nitrogen Budget:** $\Delta N = N_{\text{fix}} + N_{\text{res}} - N_{\text{uptake}} - N_{\text{leach}}$.
  4. **Agronomic Rotation Matrix:** Penalizes back-to-back same-botanical-family crops (pest/disease carryover) and rewards deep-taproot + shallow-fibrous alternation.
- `src/providers/` — Async `httpx` clients with mandatory PocketBase `field_cache` persistence:
  - `catasto.py`: Agenzia delle Entrate WFS (`CP:CadastralParcel`) for Italian parcels + OpenStreetMap Overpass fallback (`landuse~"farmland|meadow|orchard|vineyard"`) outside Italy.
  - `nasa.py`: NASA POWER (`community=AG`: `GWETROOT`, `GWETTOP`, `PRECTOTCORR`, `EVPTRNS`, `T2M_MAX`, `T2M_MIN`), ORNL DAAC MODIS `MOD13Q1` (16-day NDVI), Open-Meteo 3×3 elevation grid (SRTM slope %), and ISRIC SoilGrids (editable by user).
- `src/explainer.py` — Takes the output dict from `formulas.py` and produces plain-language summaries, jargon definitions (*NDVI*, *evapotranspiration*, *soil moisture anomaly*), and a *"Where Satellite Data Needs Local Eyes"* checklist. **Must include a deterministic Python template fallback** if the LLM API fails or rate-limits.
- `src/ui/` — NiceGUI views. Keep the primary dashboard scannable in a single viewport (no multi-page clutter) to support a 30-second demo recording.

## Critical Technical Gotchas
1. **Agenzia delle Entrate WFS Quirks:**
   - Endpoint: `https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php`
   - Ignores GeoJSON output format; always returns **GML 3.2 XML**.
   - Coordinates in `<gml:posList>` are ordered **`lat lon`** (`EPSG:6706`); swap to **`[lon, lat]`** when building GeoJSON for `ui.leaflet`.
   - Keep `BBOX` small (~`±0.0015°` around click) or the server rejects the query. Render visual parcel lines via the AdE WMS tile layer (`CP.CadastralParcel`) and fire WFS only on `map-click`.
2. **NiceGUI Leaflet GeoJSON:** Wait for `await m.initialized()` before calling `m.generic_layer(name="geoJSON", args=[geojson_dict])`.
3. **API Rate Limits & Offline Resilience:** SoilGrids enforces ~5 req/min. Always read/write `field_cache` in PocketBase first and pre-seed 4–5 demo locations (e.g., Turin/Carmagnola Po Valley, Andalusia, Iowa) so stage demos never stall on external APIs.
4. **Scientific Transparency & Human-in-the-Loop:** Every strategy card must show plain outcomes first, with an expandable *"How this was calculated & NASA sources"* section and a visible reminder that recommendations support—and do not replace—local agronomist and farmer judgment.

## Git & Hackathon Rules
- Do not commit `pb/pb_data/` or `.env` secrets; **do** commit `pb/pb_migrations/` so schema changes replicate in Docker.
- Keep code open-source compliant (Apache 2.0) and cite all NASA APIs, FAO-56/RUSLE formulas, and AdE Catasto CC BY 4.0 data in `README.md`.