"""Erosion risk (RUSLE A = R·K·LS·C·P) computed from the other datasets — no extra download.

R from long-term annual rainfall (NASA POWER 1991–2020 normals), K from SoilGrids topsoil texture and organic
carbon (Williams/EPIC), LS from the NASADEM field gradient and the parcel size, C from current HLS NDVI. P (conservation
practice) = 1. Gives the farmer a "bare soil" worst case and an estimate for the current cover.
"""
import math

from ..core import clean, result

DEPENDS = ["soil", "terrain", "weather", "crop_health"]


def r_factor(annual_precip_mm: float) -> float:
    """Rainfall erosivity, MJ·mm/(ha·h·yr) — Renard & Freimund (1994)."""
    p = annual_precip_mm
    return 0.0483 * p ** 1.61 if p < 850 else 587.8 - 1.219 * p + 0.004105 * p ** 2


def k_factor(sand: float, silt: float, clay: float, oc_pct: float) -> float:
    """Soil erodibility, t·ha·h/(ha·MJ·mm) — Williams (1995) EPIC equation."""
    sn1 = 1 - sand / 100
    f_csand = 0.2 + 0.3 * math.exp(-0.256 * sand * (1 - silt / 100))
    f_clsi = (silt / max(1e-6, clay + silt)) ** 0.3
    f_orgc = 1 - 0.25 * oc_pct / (oc_pct + math.exp(3.72 - 2.95 * oc_pct))
    f_hisand = 1 - 0.7 * sn1 / (sn1 + math.exp(-5.51 + 22.9 * sn1))
    return 0.1317 * f_csand * f_clsi * f_orgc * f_hisand


def ls_factor(slope_deg: float, slope_length_m: float) -> float:
    """Topographic factor — Moore & Burch (1986)."""
    return (slope_length_m / 22.13) ** 0.4 * (math.sin(math.radians(slope_deg)) / 0.0896) ** 1.3


def c_factor(ndvi: float) -> float:
    """Cover-management factor from NDVI — van der Knijff et al. (2000), clipped to 0–1."""
    ndvi = min(max(ndvi, -0.1), 0.95)
    return min(1.0, max(0.0, math.exp(-2 * ndvi / (1 - ndvi))))


def risk_class(a: float) -> str:
    return "low" if a < 2 else "moderate" if a < 5 else "high" if a < 10 else "very high"


def _get(ds, *path):
    for p in path:
        if not isinstance(ds, dict):
            return None
        ds = ds.get(p)
    return ds


def compute(parcel, datasets: dict) -> dict:
    missing = [d for d in DEPENDS[:3] if (datasets.get(d) or {}).get("status") != "ok"]
    if missing:
        return result(scale="field", resolution_m=30, source="RUSLE from soil + terrain + weather + crop_health",
                      status="no_data", note=f"Needs {', '.join(missing)} (not available).")
    top = datasets["soil"]["values"].get("0-5cm") or {}
    sand, silt, clay, soc = (top.get(k) for k in ("sand", "silt", "clay", "soc"))
    precip_day = _get(datasets["weather"], "values", "normals_1991_2020", "ann", "PRECTOTCORR")
    # Field gradient (plane fit) when available: per-pixel DEM slope reads ~1° even on flat paddies
    slope = _get(datasets["terrain"], "values", "field_gradient_deg")
    if slope is None:
        slope = _get(datasets["terrain"], "values", "slope_deg", "mean")
    if None in (sand, silt, clay, soc, precip_day, slope):
        return result(scale="field", resolution_m=30, source="RUSLE", status="no_data",
                      note="Soil texture, long-term rainfall or slope missing.")
    annual_mm = precip_day * 365.25
    length = min(150.0, max(20.0, math.sqrt(parcel.area_ha * 10_000)))  # rough slope length within the field
    r, k, ls = r_factor(annual_mm), k_factor(sand, silt, clay, soc / 10), ls_factor(max(slope, 0.1), length)
    bare = r * k * ls
    ndvi = _get(datasets.get("crop_health"), "values", "ndvi", "mean")
    c = c_factor(ndvi) if ndvi is not None else None
    values = {
        "r_factor": clean(r, 0), "k_factor": clean(k, 4), "ls_factor": clean(ls, 2),
        "c_factor_current": clean(c, 3), "p_factor": 1.0,
        "annual_precip_mm": clean(annual_mm, 0), "slope_deg": clean(slope, 1), "slope_length_m": clean(length, 0),
        "soil_loss_bare_t_ha_yr": clean(bare, 2), "risk_bare": risk_class(bare),
        "soil_loss_current_cover_t_ha_yr": clean(bare * c, 2) if c is not None else None,
        "risk_current_cover": risk_class(bare * c) if c is not None else None,
    }
    return result(scale="field", resolution_m=30, source="RUSLE (POWER normals, SoilGrids, NASADEM, HLS)",
                  date_=_get(datasets.get("crop_health"), "date") or "static", values=values,
                  units={"r_factor": "MJ·mm/(ha·h·yr)", "k_factor": "t·ha·h/(ha·MJ·mm)",
                         "soil_loss_bare_t_ha_yr": "t/ha/yr; EU tolerable ≈ 1.4"},
                  note="To compare crops multiply soil_loss_bare by the crop's C factor (e.g. maize 0.38, "
                       "wheat 0.20, meadow 0.01). Screening estimate, not a field survey.")
