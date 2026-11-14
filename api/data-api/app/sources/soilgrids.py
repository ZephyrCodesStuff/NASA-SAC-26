"""ISRIC SoilGrids 2.0 — global soil properties at 250 m, read from public COG/VRT mosaics. No auth."""
from concurrent.futures import ThreadPoolExecutor

from ..core import Query, clean, result, ttl_cache, zonal

BASE = "/vsicurl/https://files.isric.org/soilgrids/latest/data"
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
# property -> (divide stored integer by, output unit, label)
PROPS = {
    "clay": (10, "%", "clay"),
    "sand": (10, "%", "sand"),
    "silt": (10, "%", "silt"),
    "soc": (10, "g/kg", "soil organic carbon"),
    "phh2o": (10, "pH", "pH (water)"),
    "nitrogen": (100, "g/kg", "total nitrogen"),
    "cec": (10, "cmol(c)/kg", "cation exchange capacity"),
    "bdod": (100, "g/cm³", "bulk density"),
}


def _texture_class(clay, sand, silt):
    """USDA texture class from % clay/sand/silt."""
    if None in (clay, sand, silt):
        return None
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    if clay >= 40 and sand <= 45 and silt < 40:
        return "clay"
    return None


@ttl_cache(7 * 24 * 3600)
def _read(prop: str, depth: str, wkt: str):
    from shapely import wkt as W

    return zonal(f"{BASE}/{prop}/{prop}_{depth}_mean.vrt", W.loads(wkt))


@ttl_cache(30 * 24 * 3600)
def _rest(lat: float, lon: float) -> dict:
    """All properties × depths in one call (REST is point-based; fine at 250 m vs. small parcels)."""
    import httpx

    params = [("lon", lon), ("lat", lat), ("value", "mean")] + [("property", p) for p in PROPS] + [("depth", d) for d in DEPTHS]
    r = httpx.get("https://rest.isric.org/soilgrids/v2.0/properties/query", params=params, timeout=40)
    r.raise_for_status()
    out = {}
    for layer in r.json()["properties"]["layers"]:
        for d in layer["depths"]:
            out[(layer["name"], d["label"])] = {"mean": d["values"]["mean"]}
    return out


def _vrt(parcel) -> dict:
    jobs = [(p, d) for p in PROPS for d in DEPTHS]
    wkt = parcel.geometry.wkt
    with ThreadPoolExecutor(8) as ex:
        return dict(zip(jobs, ex.map(lambda j: _read(j[0], j[1], wkt), jobs)))


def fetch(parcel, q: Query) -> dict:
    lat, lon = parcel.centroid
    try:
        res = _rest(round(lat, 4), round(lon, 4))
        method = "REST point query"
    except Exception:  # noqa: BLE001 — REST is rate-limited (5/min) and sometimes down; read the maps directly
        res = _vrt(parcel)
        method = "COG mosaic, parcel mean"

    values = {}
    for d in DEPTHS:
        layer = {}
        for p, (div, _, _) in PROPS.items():
            m = res.get((p, d), {}).get("mean")
            layer[p] = clean(m / div, 2) if m is not None else None
        layer["texture_class"] = _texture_class(layer["clay"], layer["sand"], layer["silt"])
        values[d] = layer
    if all(v is None for layer in values.values() for k, v in layer.items() if k != "texture_class"):
        return result(scale="area", resolution_m=250, source="SoilGrids 2.0", status="no_data",
                      note="No soil data here (SoilGrids masks urban areas and water).")
    return result(scale="area", resolution_m=250, source=f"ISRIC SoilGrids 2.0 (mean prediction, {method})", values=values,
                  units={p: u for p, (_, u, _) in PROPS.items()}, date_="static")
