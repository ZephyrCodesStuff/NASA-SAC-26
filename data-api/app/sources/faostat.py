"""FAOSTAT — national crop statistics (area harvested, yield, production) and producer prices.

Country-level, yearly. Read from FAOSTAT bulk downloads (the FAOSTAT web API is often down), filtered to the
parcel's country and cached. Useful for "what does this country grow, how much per hectare, and at what price".
"""
import csv
import io
import zipfile

from ..core import clean, country_at, download, result, ttl_cache

AGGREGATE_PERIODS = False  # history is not a daily/monthly series of this parcel

BULK = "https://bulks-faostat.fao.org/production/"
QCL = "Production_Crops_Livestock_E_All_Data_(Normalized).zip"
PP = "Prices_E_All_Data_(Normalized).zip"
YEARS = 10
TOP_CROPS = 30
QCL_ELEMENTS = {"5312": "area_harvested_ha", "5412": "yield_kg_per_ha", "5510": "production_t"}
PP_ELEMENTS = {"5532": "producer_price_usd_per_t", "5530": "producer_price_lcu_per_t"}


def _rows(zip_name: str, m49: str):
    z = zipfile.ZipFile(download(BULK + zip_name, zip_name, 30 * 24 * 3600))
    name = next(n for n in z.namelist() if "All_Data" in n)
    needle = f',"\'{m49}",'
    with z.open(name) as raw:
        f = io.TextIOWrapper(raw, encoding="latin-1")
        header = next(csv.reader([f.readline()]))
        for line in f:
            if needle in line:  # cheap prefilter before CSV parsing (file is ~550 MB)
                yield dict(zip(header, next(csv.reader([line]))))


@ttl_cache(30 * 24 * 3600)
def _country_table(m49: str) -> dict:
    crops: dict[str, dict] = {}
    last_year = 0
    for r in _rows(QCL, m49):
        el = QCL_ELEMENTS.get(r["Element Code"])
        if not el or not r["Item Code (CPC)"].startswith("'01"):  # CPC 01 = crop products
            continue
        y = int(r["Year"])
        last_year = max(last_year, y)
        crops.setdefault(r["Item"], {}).setdefault(y, {})[el] = clean(r["Value"], 1)
    for r in _rows(PP, m49):
        el = PP_ELEMENTS.get(r["Element Code"])
        if el and r.get("Months Code") == "7021" and r["Item"] in crops:
            crops[r["Item"]].setdefault(int(r["Year"]), {})[el] = clean(r["Value"], 1)
    return {"crops": crops, "last_year": last_year}


def fetch(parcel, q) -> dict:
    lat, lon = (round(v, 1) for v in parcel.centroid)
    c = country_at(lat, lon)
    t = _country_table(c["m49"])
    first = t["last_year"] - YEARS + 1

    def latest_area(item):
        ys = t["crops"][item]
        return (ys.get(t["last_year"]) or {}).get("area_harvested_ha") or 0

    ranked = sorted((i for i in t["crops"] if latest_area(i) > 0), key=latest_area, reverse=True)[:TOP_CROPS]
    crops = []
    for item in ranked:
        years = t["crops"][item]
        series = [{"year": y, **years[y]} for y in sorted(years) if y >= first]
        crops.append({"crop": item, "latest": series[-1] if series else None, "years": series})
    return result(scale="country", resolution_m=None, source="FAOSTAT (QCL production, PP producer prices) bulk data",
                  date_=str(t["last_year"]), values={"country": c, "crops": crops},
                  units={"area_harvested_ha": "ha", "yield_kg_per_ha": "kg/ha", "production_t": "tonnes",
                         "producer_price_usd_per_t": "USD per tonne at farm gate",
                         "producer_price_lcu_per_t": "local currency per tonne (EUR for Italy)"},
                  note=f"Top {TOP_CROPS} crops of the country by harvested area, last {YEARS} years. National totals, "
                       "not this field. Prices lag ~1–2 years.")
