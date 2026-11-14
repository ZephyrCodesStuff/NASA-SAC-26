"""Local (country-level) prices for EU parcels: what a farmer in this country actually pays and earns.

- Eurostat apri_ap_crpouta — farm-gate selling prices of crops (EUR/100 kg, yearly).
- Eurostat nrg_pc_205 / nrg_pc_203 — non-household electricity and natural-gas prices (EUR/kWh, half-yearly).
- EU Weekly Oil Bulletin — diesel and heating gas oil (EUR/litre, weekly, with and without taxes).
- EU Agri-food Data Portal — weekly prices on named markets (cereals, rice, oilseeds) and fertilisers.
  That API is rate-limited and sometimes down; its block is optional.

Only for EU member states. Irrigation water (local consortium fees) and seed prices have no public source.
"""
import re

from ..core import _http, clean, country_at, download, http_get_json, result, ttl_cache

AGGREGATE_PERIODS = False

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
WOB_PAGE = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
AGRIFOOD = "https://ec.europa.eu/agrifood/api"
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
      "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
ELECTRICITY_BANDS = {"MWH20-499": "small farm (20–499 MWh/yr)", "MWH500-1999": "large farm (500–1999 MWh/yr)"}
GAS_BAND = ("GJ1000-9999", "1 000–9 999 GJ/yr (greenhouse heating scale)")
FUELS = {"diesel": "automotive diesel", "heating_oil": "heating gas oil"}
WEEKS = 52


def _eurostat_geo(iso2: str) -> str:
    return {"GR": "EL"}.get(iso2, iso2)


def _jsonstat(table: str, **params) -> list[dict]:
    """Eurostat JSON-stat → rows {dim: label..., time, value}."""
    d = http_get_json(f"{EUROSTAT}/{table}", **params)
    dims = d["id"]
    sizes = d["size"]
    cats = {k: d["dimension"][k]["category"] for k in dims}
    keys = {k: sorted(cats[k]["index"], key=cats[k]["index"].get) for k in dims}
    rows = []
    for flat, v in d.get("value", {}).items():
        i = int(flat)
        pos = []
        for s in reversed(sizes):
            pos.append(i % s)
            i //= s
        pos.reverse()
        row = {k: keys[k][p] for k, p in zip(dims, pos)}
        row["label"] = {k: cats[k].get("label", {}).get(row[k], row[k]) for k in dims}
        row["value"] = v
        rows.append(row)
    return rows


@ttl_cache(7 * 24 * 3600)
def _crop_prices(geo: str) -> list[dict]:
    rows = _jsonstat("apri_ap_crpouta", geo=geo, currency="EUR", sinceTimePeriod=str(_this_year() - 6))
    crops: dict[str, dict] = {}
    for r in rows:
        name = r["label"]["prod_veg"].replace(" - prices per 100 kg", "")
        if "prices per 100 kg" not in r["label"]["prod_veg"]:
            continue
        crops.setdefault(name, {})[r["time"]] = clean(r["value"] * 10, 1)  # EUR/100 kg → EUR/t
    out = []
    for name, years in crops.items():
        ys = sorted(years)
        out.append({"crop": name, "latest": {"year": ys[-1], "eur_per_t": years[ys[-1]]},
                    "years": [{"year": y, "eur_per_t": years[y]} for y in ys]})
    return sorted(out, key=lambda c: c["crop"])


@ttl_cache(7 * 24 * 3600)
def _energy(geo: str) -> dict:
    since = f"{_this_year() - 2}-S1"
    out = {"electricity": {}, "natural_gas": {}}
    for band, label in ELECTRICITY_BANDS.items():
        for tax in ("X_TAX", "I_TAX"):
            rows = _jsonstat("nrg_pc_205", geo=geo, nrg_cons=band, tax=tax, currency="EUR", unit="KWH", sinceTimePeriod=since)
            ser = sorted(((r["time"], r["value"]) for r in rows))
            e = out["electricity"].setdefault(band, {"consumer": label, "unit": "EUR/kWh"})
            e["excl_taxes" if tax == "X_TAX" else "incl_all_taxes"] = [{"semester": t, "price": clean(v, 4)} for t, v in ser]
    band, label = GAS_BAND
    for tax in ("X_TAX", "I_TAX"):
        rows = _jsonstat("nrg_pc_203", geo=geo, nrg_cons=band, tax=tax, currency="EUR", unit="KWH", sinceTimePeriod=since)
        ser = sorted(((r["time"], r["value"]) for r in rows))
        g = out["natural_gas"].setdefault(band, {"consumer": label, "unit": "EUR/kWh"})
        g["excl_taxes" if tax == "X_TAX" else "incl_all_taxes"] = [{"semester": t, "price": clean(v, 4)} for t, v in ser]
    return out


@ttl_cache(24 * 3600)
def _wob_url() -> str:
    html = _http.get(WOB_PAGE).raise_for_status().text
    m = re.search(r'href="([^"]*Prices_History[^"]*\.xlsx)"', html)
    if not m:
        raise RuntimeError("Weekly Oil Bulletin history file not found")
    href = m.group(1)
    return href if href.startswith("http") else "https://energy.ec.europa.eu" + href


@ttl_cache(24 * 3600)
def _fuel(iso2: str) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(download(_wob_url(), "Weekly_Oil_Bulletin_History.xlsx", 3 * 24 * 3600),
                                read_only=True, data_only=True)
    out = {}
    for sheet, tax in (("Prices with taxes", "with_taxes"), ("Prices wo taxes", "without_taxes")):
        rows = list(wb[sheet].iter_rows(max_row=WEEKS + 3, values_only=True))
        header = rows[0]
        for key, name in FUELS.items():
            col = next((j for j, h in enumerate(header) if isinstance(h, str) and h.startswith(f"{iso2}_price")
                        and h.endswith(f"_{key}")), None)
            if col is None:
                continue
            ser = [{"week": r[0].date().isoformat(), "eur_per_litre": clean(r[col] / 1000, 3)}
                   for r in rows[3:] if r and hasattr(r[0], "date") and isinstance(r[col], (int, float))]
            f = out.setdefault(key, {"fuel": name, "unit": "EUR/litre"})
            f[tax] = ser[::-1]  # oldest first
            f[f"latest_{tax}"] = ser[0] if ser else None
    return out


@ttl_cache(24 * 3600)
def _agrifood(iso2: str) -> dict:
    """Weekly market prices from the EU Agri-food Data Portal (best effort: strict rate limit, outages)."""
    from datetime import date, timedelta

    from concurrent.futures import ThreadPoolExecutor

    begin = (date.today() - timedelta(days=120)).strftime("%d/%m/%Y")

    def one(sector):
        try:
            r = _http.get(f"{AGRIFOOD}/{sector}/prices", params={"memberStateCodes": iso2, "beginDate": begin}, timeout=15)
            rows = r.raise_for_status().json()
            if not isinstance(rows, list):
                raise RuntimeError(str(rows)[:150])
            return sector, {"status": "ok", "rows": rows[:500]}
        except Exception as e:  # noqa: BLE001
            return sector, {"status": "unavailable", "error": f"{type(e).__name__}: {e}"[:200]}

    with ThreadPoolExecutor(4) as ex:
        out = dict(ex.map(one, ("cereal", "rice", "oilseeds", "fertiliser")))
    if all(v["status"] != "ok" for v in out.values()):
        raise RuntimeError("EU Agri-food Data Portal API unavailable (rate limit or outage); retried on next request")
    return out


def _this_year() -> int:
    from datetime import date

    return date.today().year


def fetch(parcel, q) -> dict:
    lat, lon = (round(v, 1) for v in parcel.centroid)
    c = country_at(lat, lon)
    if c["iso2"] not in EU:
        return result(scale="country", resolution_m=None, source="Eurostat / EU Oil Bulletin", status="unavailable",
                      note=f"Local price sources cover EU member states only ({c['name']} is not).")
    geo = _eurostat_geo(c["iso2"])
    parts, errors = {}, {}
    for name, fn in (("crop_selling_prices", lambda: _crop_prices(geo)), ("energy", lambda: _energy(geo)),
                     ("fuel", lambda: _fuel(c["iso2"])), ("market_prices_weekly", lambda: _agrifood(c["iso2"]))):
        try:
            parts[name] = fn()
        except Exception as e:  # noqa: BLE001 — each source is optional
            errors[name] = f"{type(e).__name__}: {e}"[:300]
    if not parts:
        return result(scale="country", resolution_m=None, source="Eurostat / EU Oil Bulletin", status="error",
                      error="; ".join(errors.values()))
    return result(scale="country", resolution_m=None,
                  source="Eurostat (apri_ap_crpouta, nrg_pc_205, nrg_pc_203), EU Weekly Oil Bulletin, EU Agri-food Data Portal",
                  date_="latest", values={"country": c, **parts}, errors=errors or None,
                  units={"crop_selling_prices": "EUR per tonne, farm-gate, yearly",
                         "energy": "EUR/kWh, half-yearly (S1 = Jan–Jun)", "fuel": "EUR/litre, weekly"},
                  note="National averages. Farm diesel in Italy is tax-reduced (gasolio agricolo): use the "
                       "without-taxes price as a lower bound. Irrigation water and seed prices: farmer input.")
