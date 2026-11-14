"""World Bank Commodity Price Data ("Pink Sheet") — monthly world prices: crude oil, gas, fertilizers, grains, oils.

Global benchmark prices in nominal USD, updated monthly. Not farm-gate prices (see `regional_production`
for national producer prices). Seed prices have no public global source; they are a farmer input.
"""
import re

from ..core import _http, clean, download, result, ttl_cache

AGGREGATE_PERIODS = False  # history is not a daily/monthly series of this parcel

PAGE = "https://www.worldbank.org/en/research/commodity-markets"
MONTHS = 60
SERIES = {  # our key -> (Pink Sheet column header, group)
    "crude_oil_avg": ("Crude oil, average", "energy"),
    "crude_oil_brent": ("Crude oil, Brent", "energy"),
    "natural_gas_europe": ("Natural gas, Europe", "energy"),
    "urea": ("Urea", "fertilizer"),
    "dap": ("DAP", "fertilizer"),
    "tsp": ("TSP", "fertilizer"),
    "potassium_chloride": ("Potassium chloride", "fertilizer"),
    "phosphate_rock": ("Phosphate rock", "fertilizer"),
    "maize": ("Maize", "crop"),
    "wheat_us_hrw": ("Wheat, US HRW", "crop"),
    "wheat_us_srw": ("Wheat, US SRW", "crop"),
    "barley": ("Barley", "crop"),
    "sorghum": ("Sorghum", "crop"),
    "rice_thai_5pct": ("Rice, Thai 5%", "crop"),
    "soybeans": ("Soybeans", "crop"),
    "soybean_oil": ("Soybean oil", "vegetable_oil"),
    "sunflower_oil": ("Sunflower oil", "vegetable_oil"),
    "rapeseed_oil": ("Rapeseed oil", "vegetable_oil"),
    "palm_oil": ("Palm oil", "vegetable_oil"),
    "sugar_eu": ("Sugar, EU", "crop"),
    "orange": ("Orange", "crop"),
    "banana_europe": ("Banana, Europe", "crop"),
}


@ttl_cache(24 * 3600)
def _xlsx_url() -> str:
    html = _http.get(PAGE).raise_for_status().text
    m = re.search(r'https://thedocs\.worldbank\.org/[^"\']*CMO-Historical-Data-Monthly\.xlsx', html)
    if not m:
        raise RuntimeError("Pink Sheet monthly file link not found on the World Bank page")
    return m.group(0)


@ttl_cache(24 * 3600)
def _table() -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(download(_xlsx_url(), "CMO-Historical-Data-Monthly.xlsx", 7 * 24 * 3600),
                                read_only=True, data_only=True)
    rows = list(wb["Monthly Prices"].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[1] == "Crude oil, average")
    names = [str(h or "").replace("*", "").strip() for h in rows[hi]]
    units = [str(u or "").strip("()") for u in rows[hi + 1]]
    data = [r for r in rows[hi + 2:] if r and isinstance(r[0], str) and re.fullmatch(r"\d{4}M\d{2}", r[0])]
    out = {}
    for key, (col, group) in SERIES.items():
        j = names.index(col)
        series = [{"month": f"{r[0][:4]}-{r[0][5:]}", "price": clean(r[j], 2)} for r in data[-MONTHS:]
                  if isinstance(r[j], (int, float))]
        out[key] = {"name": col, "group": group, "unit": units[j].replace("$", "USD"), "series": series}
    return out


def fetch(parcel, q) -> dict:
    t = _table()
    values, history = {}, {}
    for key, s in t.items():
        ser = s["series"]
        if not ser:
            continue
        latest = ser[-1]
        year_ago = next((x for x in ser if x["month"] == f"{int(latest['month'][:4]) - 1}{latest['month'][4:]}"), None)
        values[key] = {"name": s["name"], "group": s["group"], "unit": s["unit"], "latest": latest,
                       "change_12m_pct": clean((latest["price"] / year_ago["price"] - 1) * 100, 1) if year_ago and year_ago["price"] else None}
        history[key] = ser
    month = max(v["latest"]["month"] for v in values.values())
    return result(scale="global", resolution_m=None, source="World Bank Commodity Price Data (Pink Sheet), monthly",
                  date_=month, values=values, history=history,
                  note=f"World benchmark prices (USD, nominal), last {MONTHS} months. Electricity, water and seed "
                       "prices are local: enter them per farm.")
