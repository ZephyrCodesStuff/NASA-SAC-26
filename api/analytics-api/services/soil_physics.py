"""
Scientific Soil Physics, Organic Carbon, Compaction, and Hydrology Engine.
Implements:
1. Henin-Dupuis & IPCC Tier 2 Soil Organic Carbon (SOC) dynamics (k1, k2, Bolinder root C)
2. ASAE S313.3 Cone Penetrometer Compaction & Bio-Drilling Taproot Alleviation
3. Herridge & Peoples Biological Nitrogen Fixation (BNF) equations
4. FAO-56 Penman-Monteith ET0 & Dual Crop Coefficient water balance
5. RUSLE topsoil erosion modeling
6. Botanical pathology break matrices
"""

import math
from typing import Dict, Any, Tuple, Optional, List
from projection_api.models.crops_catalog import CropAgronomicProfile, BotanicalFamily, RootArchitecture


MONTH_DAYS: Dict[int, int] = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}
MONTH_MID_DOY: Dict[int, int] = {
    1: 15, 2: 46, 3: 75, 4: 105, 5: 135, 6: 166,
    7: 196, 8: 227, 9: 258, 10: 288, 11: 319, 12: 349,
}

IRRIGATION_EFFICIENCIES: Dict[str, float] = {
    "surface": 0.60,
    "sprinkler": 0.75,
    "drip": 0.90,
    "rainfed": 0.75,
}

# GloREDa (Panagos et al., 2017) regional benchmarks for common agro-ecological zones [MJ mm / (ha h yr)]
GLOREDA_REGIONAL_BENCHMARKS: List[Tuple[str, float, float, float, float, float]] = [
    ("Turin / Po Valley (GloREDa benchmark)", 43.5, 46.5, 6.5, 13.5, 1650.0),
    ("Istanbul / Marmara (GloREDa benchmark)", 39.5, 42.0, 26.5, 31.0, 1150.0),
    ("Iowa / US Corn Belt (GloREDa benchmark)", 40.0, 44.0, -97.0, -89.5, 2950.0),
    ("Andalusia / S. Spain (GloREDa benchmark)", 36.0, 39.0, -7.5, -2.0, 900.0),
]


# Soil physical benchmarks mapped to SoilTypeEnum
SOIL_PHYSICAL_PROPERTIES: Dict[str, Dict[str, float]] = {
    "clay": {
        "clay_pct": 48.0,
        "sand_pct": 20.0,
        "bulk_density_g_cm3": 1.25,
        "theta_fc": 0.40,
        "theta_wp": 0.27,
        "theta_sat": 0.51,
        "ksat_mm_hr": 1.5,
        "rusle_k_factor": 0.024,
    },
    "clay_loam": {
        "clay_pct": 32.0,
        "sand_pct": 32.0,
        "bulk_density_g_cm3": 1.30,
        "theta_fc": 0.33,
        "theta_wp": 0.19,
        "theta_sat": 0.47,
        "ksat_mm_hr": 4.5,
        "rusle_k_factor": 0.030,
    },
    "loam": {
        "clay_pct": 20.0,
        "sand_pct": 40.0,
        "bulk_density_g_cm3": 1.35,
        "theta_fc": 0.27,
        "theta_wp": 0.13,
        "theta_sat": 0.46,
        "ksat_mm_hr": 13.0,
        "rusle_k_factor": 0.034,
    },
    "sandy_loam": {
        "clay_pct": 10.0,
        "sand_pct": 65.0,
        "bulk_density_g_cm3": 1.45,
        "theta_fc": 0.20,
        "theta_wp": 0.09,
        "theta_sat": 0.43,
        "ksat_mm_hr": 26.0,
        "rusle_k_factor": 0.026,
    },
    "silt_loam": {
        "clay_pct": 18.0,
        "sand_pct": 18.0,
        "bulk_density_g_cm3": 1.32,
        "theta_fc": 0.33,
        "theta_wp": 0.14,
        "theta_sat": 0.48,
        "ksat_mm_hr": 8.0,
        "rusle_k_factor": 0.042,
    },
    "sand": {
        "clay_pct": 4.0,
        "sand_pct": 92.0,
        "bulk_density_g_cm3": 1.55,
        "theta_fc": 0.10,
        "theta_wp": 0.04,
        "theta_sat": 0.38,
        "ksat_mm_hr": 110.0,
        "rusle_k_factor": 0.015,
    },
}


class SoilPhysicsEngine:
    """Scientific calculator for ground impact, soil chemistry, compaction, and hydrology."""

    @staticmethod
    def get_soil_properties(soil_type: str) -> Dict[str, float]:
        clean = soil_type.lower().replace(" ", "_").replace("-", "_")
        if clean in SOIL_PHYSICAL_PROPERTIES:
            return SOIL_PHYSICAL_PROPERTIES[clean]
        for k, v in SOIL_PHYSICAL_PROPERTIES.items():
            if k in clean or clean in k:
                return v
        return SOIL_PHYSICAL_PROPERTIES["loam"]

    @staticmethod
    def calculate_fao56_penman_monteith_et0(
        t_max: float,
        t_min: float,
        solar_rad_mj_m2: float,
        wind_speed_2m: float,
        rh_mean: float = 60.0,
        elevation_m: float = 100.0,
        latitude_deg: float = 40.0,
        day_of_year: int = 180,
        t_dew: Optional[float] = None,
        g_soil_flux: float = 0.0,
    ) -> float:
        """
        Computes reference evapotranspiration (ET0, mm/day) via FAO-56 Penman-Monteith (Eq. 6).
        Uses T2MDEW via Eq. 14 when provided, actual Rs/Rso <= 1.0 (Eq. 39), and optional soil heat flux G (Eq. 43).
        """
        t_mean = (t_max + t_min) / 2.0
        p = 101.3 * math.pow((293.0 - 0.0065 * elevation_m) / 293.0, 5.26)
        gamma = 0.000665 * p
        delta = (4098.0 * (0.6108 * math.exp((17.27 * t_mean) / (t_mean + 237.3)))) / math.pow(t_mean + 237.3, 2)

        e0_tmax = 0.6108 * math.exp((17.27 * t_max) / (t_max + 237.3))
        e0_tmin = 0.6108 * math.exp((17.27 * t_min) / (t_min + 237.3))
        es = (e0_tmax + e0_tmin) / 2.0
        if t_dew is not None:
            ea = min(es, 0.6108 * math.exp((17.27 * t_dew) / (t_dew + 237.3)))
        else:
            ea = min(es, (max(5.0, min(100.0, rh_mean)) / 100.0) * es)
        vpd = max(0.0, es - ea)

        # Extraterrestrial radiation Ra
        lat_rad = math.radians(latitude_deg)
        dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
        sol_dec = 0.409 * math.sin((2.0 * math.pi * day_of_year / 365.0) - 1.39)
        tan_val = max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(sol_dec)))
        ws = math.acos(tan_val)
        ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
            ws * math.sin(lat_rad) * math.sin(sol_dec) +
            math.cos(lat_rad) * math.cos(sol_dec) * math.sin(ws)
        )
        ra = max(0.1, ra)
        rso = (0.75 + 2e-5 * elevation_m) * ra
        rns = (1.0 - 0.23) * solar_rad_mj_m2

        # Net longwave Rnl using actual Rs/Rso capped at 1.0 (FAO-56 Eq. 39, no artificial 0.3 floor)
        sigma = 4.903e-9
        t_max_k4 = math.pow(t_max + 273.16, 4)
        t_min_k4 = math.pow(t_min + 273.16, 4)
        rel_solar = min(1.0, max(0.0, solar_rad_mj_m2 / max(rso, 0.1)))
        cloud_term = max(0.0, 1.35 * rel_solar - 0.35)
        rnl = max(0.0, sigma * ((t_max_k4 + t_min_k4) / 2.0) * (0.34 - 0.14 * math.sqrt(ea)) * cloud_term)
        rn = rns - rnl

        u2 = max(0.5, wind_speed_2m)
        num = 0.408 * delta * (rn - g_soil_flux) + gamma * (900.0 / (t_mean + 273.0)) * u2 * vpd
        den = delta + gamma * (1.0 + 0.34 * u2)
        return max(0.0, round(num / den, 2))

    @staticmethod
    def calculate_hargreaves_samani_et0(
        t_max: float,
        t_min: float,
        latitude_deg: float = 40.0,
        day_of_year: int = 180,
    ) -> float:
        """Fallback daily reference ET0 (mm/day) via Hargreaves-Samani (FAO-56 Eq. 52)."""
        t_mean = (t_max + t_min) / 2.0
        lat_rad = math.radians(latitude_deg)
        dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
        sol_dec = 0.409 * math.sin((2.0 * math.pi * day_of_year / 365.0) - 1.39)
        tan_val = max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(sol_dec)))
        ws = math.acos(tan_val)
        ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
            ws * math.sin(lat_rad) * math.sin(sol_dec) +
            math.cos(lat_rad) * math.cos(sol_dec) * math.sin(ws)
        )
        ra_mm = 0.408 * max(0.1, ra)
        return max(0.0, round(0.0023 * (t_mean + 17.8) * math.sqrt(max(0.1, t_max - t_min)) * ra_mm, 2))

    @classmethod
    def build_monthly_climate_series(
        cls,
        monthly_raw: Optional[Dict[int, Dict[str, Any]]] = None,
        latitude_deg: float = 40.0,
        elevation_m: float = 200.0,
        annual_et0_mm: float = 1200.0,
        annual_precip_mm: float = 620.0,
        mean_temp_c: float = 15.0,
        warm_season_et0_mm: Optional[float] = None,
        warm_season_precip_mm: Optional[float] = None,
        cool_season_et0_mm: Optional[float] = None,
        cool_season_precip_mm: Optional[float] = None,
        coldest_night_c: Optional[float] = None,
        hottest_day_c: Optional[float] = None,
    ) -> Tuple[Dict[int, Dict[str, float]], str]:
        """
        Builds a full 12-month climatology table with monthly ET0 (mm), precip (mm), Tmean/Tmax/Tmin, RHmin, u2.
        Primary ET0: FAO-56 Penman-Monteith with Eq. 14 dew-point and Eq. 43 monthly soil heat flux.
        Fallback ET0: Hargreaves-Samani when wind, humidity, or solar radiation is absent.
        When raw monthly normals are omitted, synthesizes smooth hemisphere-aware monthly profiles scaled to scalars.
        """
        if monthly_raw and len(monthly_raw) >= 12:
            # Determine T_mean per month first so Eq. 43 soil heat flux uses cyclic (T[m+1] - T[m-1])
            t_means: Dict[int, float] = {}
            has_pm_inputs = True
            for m in range(1, 13):
                row = monthly_raw.get(m, {})
                tmax = row.get("t2m_max_c")
                tmin = row.get("t2m_min_c")
                tmean = row.get("t2m_c")
                if tmean is None and tmax is not None and tmin is not None:
                    tmean = (tmax + tmin) / 2.0
                if tmean is None:
                    tmean = mean_temp_c
                t_means[m] = float(tmean)
                if (
                    row.get("t2m_max_c") is None
                    or row.get("t2m_min_c") is None
                    or row.get("solar_radiation_mj_m2") is None
                    or row.get("wind_speed_2m_ms") is None
                    or (row.get("dew_point_c") is None and row.get("relative_humidity_pct") is None)
                ):
                    has_pm_inputs = False

            out: Dict[int, Dict[str, float]] = {}
            method = (
                "FAO-56 Penman-Monteith (Monthly Climatology)"
                if has_pm_inputs
                else "Hargreaves-Samani (Fallback: Incomplete Radiative/Aerodynamic Normals)"
            )
            for m in range(1, 13):
                row = monthly_raw.get(m, {})
                tmean = t_means[m]
                tmax = float(row.get("t2m_max_c") if row.get("t2m_max_c") is not None else tmean + 5.5)
                tmin = float(row.get("t2m_min_c") if row.get("t2m_min_c") is not None else tmean - 5.5)
                doy = MONTH_MID_DOY[m]
                days = MONTH_DAYS[m]
                precip_m = float(row.get("precip_mm") if row.get("precip_mm") is not None else (annual_precip_mm / 12.0))
                u2 = float(row.get("wind_speed_2m_ms") if row.get("wind_speed_2m_ms") is not None else 2.0)
                tdew = row.get("dew_point_c")
                rh_mean = float(row.get("relative_humidity_pct") if row.get("relative_humidity_pct") is not None else 62.0)

                if tdew is not None:
                    e_dew = 0.6108 * math.exp((17.27 * float(tdew)) / (float(tdew) + 237.3))
                    e_tmax = 0.6108 * math.exp((17.27 * tmax) / (tmax + 237.3))
                    rh_min = max(20.0, min(80.0, 100.0 * e_dew / max(0.05, e_tmax)))
                else:
                    rh_min = max(20.0, min(80.0, rh_mean * 0.72))

                if has_pm_inputs:
                    m_prev = ((m - 2) % 12) + 1
                    m_next = (m % 12) + 1
                    g_m = 0.07 * (t_means[m_next] - t_means[m_prev])
                    et0_day = cls.calculate_fao56_penman_monteith_et0(
                        t_max=tmax,
                        t_min=tmin,
                        solar_rad_mj_m2=float(row["solar_radiation_mj_m2"]),
                        wind_speed_2m=u2,
                        rh_mean=rh_mean,
                        elevation_m=elevation_m,
                        latitude_deg=latitude_deg,
                        day_of_year=doy,
                        t_dew=float(tdew) if tdew is not None else None,
                        g_soil_flux=g_m,
                    )
                else:
                    et0_day = cls.calculate_hargreaves_samani_et0(
                        t_max=tmax,
                        t_min=tmin,
                        latitude_deg=latitude_deg,
                        day_of_year=doy,
                    )

                out[m] = {
                    "et0_mm": round(et0_day * days, 2),
                    "precip_mm": round(max(0.0, precip_m), 2),
                    "tmean_c": round(tmean, 2),
                    "tmax_c": round(tmax, 2),
                    "tmin_c": round(tmin, 2),
                    "u2_ms": round(u2, 2),
                    "rh_min_pct": round(rh_min, 1),
                    "days": float(days),
                }
            return out, method

        # Synthetic seasonal fallback when caller supplies only annual/seasonal scalars
        peak_month = 7.0 if latitude_deg >= 0.0 else 1.0
        amp = 9.5
        if coldest_night_c is not None and hottest_day_c is not None:
            amp = max(4.0, min(16.0, (hottest_day_c - coldest_night_c) / 2.6))

        warm_months = {4, 5, 6, 7, 8, 9} if latitude_deg >= 0.0 else {10, 11, 12, 1, 2, 3}
        raw_et_weights = {}
        raw_rain_weights = {}
        temps = {}
        for m in range(1, 13):
            phase = math.cos(2.0 * math.pi * (m - peak_month) / 12.0)
            temps[m] = mean_temp_c + amp * phase
            raw_et_weights[m] = max(0.15, 1.0 + 0.65 * phase)
            # Slightly Mediterranean winter/spring or continental distribution blend
            raw_rain_weights[m] = max(0.35, 1.0 - 0.15 * phase)

        et_series: Dict[int, float] = {}
        rain_series: Dict[int, float] = {}
        if warm_season_et0_mm is not None and cool_season_et0_mm is not None:
            w_sum = sum(raw_et_weights[m] for m in warm_months)
            c_sum = sum(raw_et_weights[m] for m in range(1, 13) if m not in warm_months)
            for m in range(1, 13):
                if m in warm_months:
                    et_series[m] = warm_season_et0_mm * (raw_et_weights[m] / w_sum)
                else:
                    et_series[m] = cool_season_et0_mm * (raw_et_weights[m] / c_sum)
        else:
            tot_w = sum(raw_et_weights.values())
            for m in range(1, 13):
                et_series[m] = annual_et0_mm * (raw_et_weights[m] / tot_w)

        if warm_season_precip_mm is not None and cool_season_precip_mm is not None:
            w_sum = sum(raw_rain_weights[m] for m in warm_months)
            c_sum = sum(raw_rain_weights[m] for m in range(1, 13) if m not in warm_months)
            for m in range(1, 13):
                if m in warm_months:
                    rain_series[m] = warm_season_precip_mm * (raw_rain_weights[m] / w_sum)
                else:
                    rain_series[m] = cool_season_precip_mm * (raw_rain_weights[m] / c_sum)
        else:
            tot_w = sum(raw_rain_weights.values())
            for m in range(1, 13):
                rain_series[m] = annual_precip_mm * (raw_rain_weights[m] / tot_w)

        out = {}
        for m in range(1, 13):
            tmean = temps[m]
            out[m] = {
                "et0_mm": round(max(1.0, et_series[m]), 2),
                "precip_mm": round(max(0.0, rain_series[m]), 2),
                "tmean_c": round(tmean, 2),
                "tmax_c": round(tmean + 5.5, 2),
                "tmin_c": round(tmean - 5.5, 2),
                "u2_ms": 2.0,
                "rh_min_pct": 45.0,
                "days": float(MONTH_DAYS[m]),
            }
        return out, "NASA POWER Scalar / Synthetic Monthly Disaggregation"

    @staticmethod
    def get_irrigation_efficiency(irrigation_method: Optional[str] = None) -> Tuple[str, float]:
        """Returns canonical FAO-56 application method and efficiency (0.60, 0.75, 0.90)."""
        if not irrigation_method:
            return "sprinkler", 0.75
        m = irrigation_method.strip().lower()
        if m in IRRIGATION_EFFICIENCIES:
            return m, IRRIGATION_EFFICIENCIES[m]
        if "drip" in m or "trickle" in m or "subsurface" in m:
            return "drip", 0.90
        if "surface" in m or "flood" in m or "furrow" in m:
            return "surface", 0.60
        if "rain" in m or "none" in m:
            return "rainfed", 0.75
        return "sprinkler", 0.75

    @staticmethod
    def calculate_usda_scs_effective_rainfall_monthly(precip_month_mm: float) -> float:
        """Monthly USDA-SCS effective precipitation equation."""
        p = max(0.0, precip_month_mm)
        if p <= 250.0:
            return max(0.0, p * (125.0 - 0.2 * p) / 125.0)
        return 125.0 + 0.1 * p

    @staticmethod
    def calculate_saxton_rawls_moisture(
        sand_pct: float,
        clay_pct: float,
        soc_pct: float = 1.5,
    ) -> Tuple[float, float]:
        """
        Saxton & Rawls (2006) pedotransfer functions for volumetric water content at
        permanent wilting point (1500 kPa) and field capacity (33 kPa).
        Returns: (theta_wp, theta_fc)
        """
        s = max(0.01, min(0.95, sand_pct / 100.0))
        c = max(0.01, min(0.95, clay_pct / 100.0))
        om = max(0.0, min(8.0, soc_pct * 1.724))

        theta_1500t = (
            -0.024 * s + 0.487 * c + 0.006 * om
            + 0.005 * (s * om) - 0.013 * (c * om)
            + 0.068 * (s * c) + 0.031
        )
        theta_wp = theta_1500t + (0.14 * theta_1500t - 0.02)

        theta_33t = (
            -0.251 * s + 0.195 * c + 0.011 * om
            + 0.006 * (s * om) - 0.027 * (c * om)
            + 0.452 * (s * c) + 0.299
        )
        theta_fc = theta_33t + (1.283 * (theta_33t ** 2) - 0.374 * theta_33t - 0.015)

        theta_wp = round(max(0.03, min(0.45, theta_wp)), 4)
        theta_fc = round(max(theta_wp + 0.04, min(0.55, theta_fc)), 4)
        return theta_wp, theta_fc

    @staticmethod
    def _doy_to_month_day(doy: int) -> Tuple[int, int]:
        d = ((int(doy) - 1) % 365) + 1
        for m in range(1, 13):
            if d <= MONTH_DAYS[m]:
                return m, d
            d -= MONTH_DAYS[m]
        return 12, 31

    @staticmethod
    def _month_start_end_doy(month: int) -> Tuple[int, int]:
        start = 1 + sum(MONTH_DAYS[m] for m in range(1, month))
        end = start + MONTH_DAYS[month] - 1
        return start, end

    @classmethod
    def resolve_crop_calendar(
        cls,
        crop: CropAgronomicProfile,
        latitude_deg: float = 40.0,
        farmer_calendars: Optional[Dict[str, Dict[str, int]]] = None,
        ggcmi_calendars: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, str]:
        """
        Resolves crop growing-window calendar using 3-tier precedence:
          Tier 1: Farmer sowing/harvest dates
          Tier 2: GGCMI Phase 3 crop calendar
          Tier 3: Catalog Northern-Hemisphere defaults (shifted +6 months if lat < 0)
        Returns: (list of monthly occupancy dicts in chronological order, cycle_days, source_label)
        """
        crop_key = crop.crop_id
        sowing_doy: Optional[int] = None
        harvest_doy: Optional[int] = None
        source = "Catalog Default Calendar"

        for cal_dict, label in (
            (farmer_calendars, "Tier 1 Farmer Crop Calendar"),
            (ggcmi_calendars, "Tier 2 GGCMI Phase 3 Crop Calendar"),
        ):
            if cal_dict and crop_key in cal_dict:
                entry = cal_dict[crop_key]
                if "sowing_doy" in entry and "harvest_doy" in entry:
                    sowing_doy = int(entry["sowing_doy"])
                    harvest_doy = int(entry["harvest_doy"])
                    source = label
                    break
                elif "sowing_month" in entry and "harvest_month" in entry:
                    sowing_doy, _ = cls._month_start_end_doy(max(1, min(12, int(entry["sowing_month"]))))
                    _, harvest_doy = cls._month_start_end_doy(max(1, min(12, int(entry["harvest_month"]))))
                    source = label
                    break

        if sowing_doy is None or harvest_doy is None:
            sowing_doy = crop.sowing_doy_default
            harvest_doy = crop.harvest_doy_default
            if latitude_deg < 0.0:
                sowing_doy = ((sowing_doy - 1 + 182) % 365) + 1
                harvest_doy = ((harvest_doy - 1 + 182) % 365) + 1
                source = "Tier 3 Catalog Default (Southern Hemisphere +6 mo)"
            else:
                source = "Tier 3 Catalog Default (Northern Hemisphere)"

        if "perennial" in crop.season_type.lower() or crop.growth_cycle_days >= 330:
            months = [
                {
                    "month": m,
                    "f_m": 1.0,
                    "year_offset": 0,
                    "days_in_crop": MONTH_DAYS[m],
                    "cum_day_start": sum(MONTH_DAYS[k] for k in range(1, m)),
                    "cum_day_end": sum(MONTH_DAYS[k] for k in range(1, m + 1)),
                }
                for m in range(1, 13)
            ]
            return months, 365, source

        total_span = (harvest_doy - sowing_doy + 1) if harvest_doy >= sowing_doy else (365 - sowing_doy + 1 + harvest_doy)
        total_span = max(30, min(365, total_span))

        months_out: List[Dict[str, Any]] = []
        cur_day = 0
        # Walk day offsets from sowing_doy
        occupied_bounds: Dict[Tuple[int, int], Tuple[int, int]] = {}
        for offset in range(total_span):
            abs_day = sowing_doy + offset
            year_offset = 1 if abs_day > 365 else 0
            doy = ((abs_day - 1) % 365) + 1
            m_idx, _ = cls._doy_to_month_day(doy)
            key = (year_offset, m_idx)
            if key not in occupied_bounds:
                occupied_bounds[key] = (offset, offset + 1)
            else:
                prev_s, _ = occupied_bounds[key]
                occupied_bounds[key] = (prev_s, offset + 1)

        for (y_off, m_idx), (d_start, d_end) in occupied_bounds.items():
            n_crop_days = d_end - d_start
            months_out.append({
                "month": m_idx,
                "f_m": round(min(1.0, n_crop_days / MONTH_DAYS[m_idx]), 4),
                "year_offset": y_off,
                "days_in_crop": n_crop_days,
                "cum_day_start": d_start,
                "cum_day_end": d_end,
            })
        return months_out, total_span, source

    @staticmethod
    def compute_monthly_kc(
        crop: CropAgronomicProfile,
        calendar_months: List[Dict[str, Any]],
        cycle_days: int,
        monthly_climate: Dict[int, Dict[str, float]],
    ) -> Dict[Tuple[int, int], float]:
        """
        Computes monthly FAO-56 single crop coefficient Kc_m from stage durations and Eq. 62
        humidity/wind adjustments over mid-season occupied months.
        """
        f_ini, f_dev, f_mid, f_late = crop.stage_fractions
        l_ini = max(1.0, cycle_days * f_ini)
        l_dev = max(1.0, cycle_days * f_dev)
        l_mid = max(1.0, cycle_days * f_mid)
        l_late = max(1.0, cycle_days - l_ini - l_dev - l_mid)

        # Find months overlapping the mid-season stage for Eq. 62 adjustment
        mid_start = l_ini + l_dev
        mid_end = mid_start + l_mid
        mid_months = [
            cm["month"] for cm in calendar_months
            if cm["cum_day_end"] > mid_start and cm["cum_day_start"] < mid_end
        ] or [cm["month"] for cm in calendar_months]

        u2_mid = sum(monthly_climate[m]["u2_ms"] for m in mid_months) / len(mid_months)
        rh_min_mid = sum(monthly_climate[m]["rh_min_pct"] for m in mid_months) / len(mid_months)

        is_perennial_forage = "perennial" in crop.season_type.lower() and crop.crop_id == "alfalfa"
        if is_perennial_forage:
            # Averaged perennial cutting-cycle coefficient (kc_mid = 0.95)
            adj = (0.04 * (u2_mid - 2.0) - 0.004 * (rh_min_mid - 45.0)) * ((max(0.1, crop.crop_height_m) / 3.0) ** 0.3)
            kc_perennial = max(0.45, crop.kc_mid + adj)
            return {(cm["year_offset"], cm["month"]): round(kc_perennial, 3) for cm in calendar_months}

        adj_mid = (0.04 * (u2_mid - 2.0) - 0.004 * (rh_min_mid - 45.0)) * ((max(0.1, crop.crop_height_m) / 3.0) ** 0.3)
        kc_mid_adj = max(0.40, crop.kc_mid + adj_mid)
        kc_end_adj = max(0.20, crop.kc_end + (adj_mid if crop.kc_end > 0.45 else 0.0))

        def daily_kc(day_t: float) -> float:
            if day_t <= l_ini:
                return crop.kc_ini
            if day_t <= l_ini + l_dev:
                frac = (day_t - l_ini) / l_dev
                return crop.kc_ini + frac * (kc_mid_adj - crop.kc_ini)
            if day_t <= l_ini + l_dev + l_mid:
                return kc_mid_adj
            frac = min(1.0, (day_t - (l_ini + l_dev + l_mid)) / max(1.0, l_late))
            return kc_mid_adj + frac * (kc_end_adj - kc_mid_adj)

        kc_by_ym: Dict[Tuple[int, int], float] = {}
        for cm in calendar_months:
            d0 = cm["cum_day_start"]
            d1 = cm["cum_day_end"]
            vals = [daily_kc(d + 0.5) for d in range(d0, d1)]
            kc_by_ym[(cm["year_offset"], cm["month"])] = round(sum(vals) / max(1, len(vals)), 3)
        return kc_by_ym

    @classmethod
    def simulate_monthly_water_balance(
        cls,
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        monthly_climate: Dict[int, Dict[str, float]],
        latitude_deg: float = 40.0,
        smap_rootzone_moisture: float = 0.25,
        initial_storage_mm: Optional[float] = None,
        prev_rooting_depth_m: Optional[float] = None,
        has_irrigation: bool = True,
        irrigation_method: str = "sprinkler",
        annual_quotas_remaining_mm: Optional[Dict[int, float]] = None,
        base_calendar_year: int = 1,
        sand_pct: Optional[float] = None,
        clay_pct: Optional[float] = None,
        soc_pct: Optional[float] = None,
        farmer_calendars: Optional[Dict[str, Dict[str, int]]] = None,
        ggcmi_calendars: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> Dict[str, Any]:
        """
        Monthly carryover bucket water balance using Saxton-Rawls moisture limits,
        FAO-56 single Kc (Eq. 62), monthly USDA-SCS Peff, Eq. 84 Ks (no 0.30 floor),
        irrigation application efficiency e_a, and FAO-33 yield response (Eq. 89).
        """
        method_norm, eff_ea = cls.get_irrigation_efficiency(irrigation_method)
        if method_norm == "rainfed":
            has_irrigation = False

        if sand_pct is not None and clay_pct is not None:
            theta_wp, theta_fc = cls.calculate_saxton_rawls_moisture(
                sand_pct=sand_pct,
                clay_pct=clay_pct,
                soc_pct=soc_pct if soc_pct is not None else 1.5,
            )
        else:
            theta_wp = soil_props["theta_wp"]
            theta_fc = soil_props["theta_fc"]

        zr = crop.max_rooting_depth_m
        taw_mm = max(25.0, 1000.0 * (theta_fc - theta_wp) * zr)

        if initial_storage_mm is not None and prev_rooting_depth_m and prev_rooting_depth_m > 0:
            # Preserve soil moisture continuity across consecutive crop rooting depths
            frac_avail = max(0.0, min(1.0, initial_storage_mm / max(1.0, 1000.0 * (theta_fc - theta_wp) * prev_rooting_depth_m)))
            s_prev = frac_avail * taw_mm
        elif initial_storage_mm is not None:
            s_prev = max(0.0, min(taw_mm, initial_storage_mm))
        else:
            theta_curr = max(theta_wp, min(theta_fc, smap_rootzone_moisture))
            s_prev = 1000.0 * (theta_curr - theta_wp) * zr

        cal_months, cycle_days, cal_source = cls.resolve_crop_calendar(
            crop=crop,
            latitude_deg=latitude_deg,
            farmer_calendars=farmer_calendars,
            ggcmi_calendars=ggcmi_calendars,
        )
        kc_map = cls.compute_monthly_kc(crop, cal_months, cycle_days, monthly_climate)

        sum_etc = 0.0
        sum_eta = 0.0
        sum_peff = 0.0
        sum_i_gross = 0.0
        sum_i_net = 0.0

        for cm in cal_months:
            m = cm["month"]
            f_m = cm["f_m"]
            y_key = base_calendar_year + cm["year_offset"]
            clim = monthly_climate[m]
            kc_m = kc_map[(cm["year_offset"], m)]

            etc_m = max(0.0, kc_m * clim["et0_mm"] * f_m)
            etc_daily = etc_m / max(1.0, cm["days_in_crop"])
            p_m = max(0.10, min(0.80, crop.depletion_fraction_p + 0.04 * (5.0 - etc_daily)))
            raw_m = p_m * taw_mm
            peff_m = cls.calculate_usda_scs_effective_rainfall_monthly(clim["precip_mm"]) * f_m

            # Start-of-month depletion (before irrigation & rain)
            d_r_start = max(0.0, taw_mm - s_prev)
            i_gross_m = 0.0
            i_net_m = 0.0

            if has_irrigation:
                # Net water required to keep end-of-month depletion within RAW (no water stress)
                projected_end_no_irr = s_prev + peff_m - etc_m
                target_min_storage = taw_mm - raw_m
                if projected_end_no_irr < target_min_storage:
                    desired_net = target_min_storage - projected_end_no_irr
                    desired_gross = desired_net / eff_ea
                    if annual_quotas_remaining_mm is not None and y_key in annual_quotas_remaining_mm:
                        avail_gross = max(0.0, annual_quotas_remaining_mm[y_key])
                        i_gross_m = min(desired_gross, avail_gross)
                        annual_quotas_remaining_mm[y_key] = avail_gross - i_gross_m
                    else:
                        i_gross_m = desired_gross
                    i_net_m = i_gross_m * eff_ea

            # Effective depletion for FAO-56 Eq. 84 Ks evaluation
            d_r_eff = max(0.0, d_r_start - i_net_m)
            # Also check end-of-step deficit before ETa cap
            available_m = s_prev + peff_m + i_net_m
            if d_r_eff <= raw_m and available_m >= etc_m + (taw_mm - taw_mm * 0.999999):
                ks_m = 1.0
            if available_m - etc_m < taw_mm - raw_m:
                # Use average step depletion when month depletes across RAW threshold
                d_r_end_est = max(0.0, taw_mm - max(0.0, available_m - etc_m))
                d_r_step = 0.5 * (d_r_eff + d_r_end_est) if d_r_eff <= raw_m else d_r_eff
                if d_r_step <= raw_m:
                    ks_m = 1.0
                else:
                    ks_m = max(0.0, min(1.0, (taw_mm - d_r_step) / max(1.0, (1.0 - p_m) * taw_mm)))
            else:
                ks_m = 1.0 if d_r_eff <= raw_m else max(0.0, min(1.0, (taw_mm - d_r_eff) / max(1.0, (1.0 - p_m) * taw_mm)))

            eta_m = min(ks_m * etc_m, max(0.0, available_m))
            s_next = max(0.0, min(taw_mm, available_m - eta_m))

            sum_etc += etc_m
            sum_eta += eta_m
            sum_peff += peff_m
            sum_i_gross += i_gross_m
            sum_i_net += i_net_m
            s_prev = s_next

        rel_deficit = max(0.0, min(1.0, 1.0 - (sum_eta / max(1.0, sum_etc))))
        mu_water = max(0.0, 1.0 - crop.fao33_ky * rel_deficit)
        ks_eff = round(max(0.0, min(1.0, sum_eta / max(1.0, sum_etc))), 3)

        return {
            "etc_mm": round(max(1.0, sum_etc), 1),
            "eta_mm": round(max(0.0, sum_eta), 1),
            "peff_mm": round(max(0.0, sum_peff), 1),
            "irrigation_gross_mm": round(sum_i_gross, 1),
            "irrigation_net_mm": round(sum_i_net, 1),
            "irrigation_m3_ha": round(sum_i_gross * 10.0, 1),
            "ks": ks_eff,
            "relative_et_deficit": round(rel_deficit, 4),
            "fao33_mu_water": round(mu_water, 4),
            "fao33_outside_calibrated_range": rel_deficit > 0.50,
            "end_storage_mm": round(s_prev, 2),
            "end_rooting_depth_m": zr,
            "irrigation_method": method_norm,
            "irrigation_efficiency_ea": eff_ea,
            "calendar_months": cal_months,
            "calendar_source": cal_source,
            "theta_fc": theta_fc,
            "theta_wp": theta_wp,
        }

    @classmethod
    def simulate_crop_hydrology(
        cls,
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        annual_et0_mm: float,
        annual_precip_mm: float,
        smap_rootzone_moisture: float = 0.25,
        seasonal_et0_override_mm: Optional[float] = None,
        seasonal_precip_override_mm: Optional[float] = None,
        has_irrigation: bool = True,
        water_quota_mm_ha: Optional[float] = None,
        monthly_climate: Optional[Dict[int, Dict[str, float]]] = None,
        latitude_deg: float = 40.0,
        irrigation_method: str = "sprinkler",
        sand_pct: Optional[float] = None,
        clay_pct: Optional[float] = None,
        soc_pct: Optional[float] = None,
    ) -> Tuple[float, float, float, float, float]:
        """
        Seasonal FAO-56 single-Kc monthly carryover water balance wrapper.
        Returns: (water_demand_etc_mm, effective_precip_mm, irrigation_gross_mm, irrigation_m3_ha, stress_ks)
        """
        if monthly_climate is None:
            monthly_climate, _ = cls.build_monthly_climate_series(
                monthly_raw=None,
                latitude_deg=latitude_deg,
                annual_et0_mm=annual_et0_mm,
                annual_precip_mm=annual_precip_mm,
                warm_season_et0_mm=seasonal_et0_override_mm,
                warm_season_precip_mm=seasonal_precip_override_mm,
            )
        quotas = {1: water_quota_mm_ha, 2: water_quota_mm_ha} if water_quota_mm_ha is not None else None
        res = cls.simulate_monthly_water_balance(
            crop=crop,
            soil_props=soil_props,
            monthly_climate=monthly_climate,
            latitude_deg=latitude_deg,
            smap_rootzone_moisture=smap_rootzone_moisture,
            has_irrigation=has_irrigation,
            irrigation_method=irrigation_method,
            annual_quotas_remaining_mm=quotas,
            base_calendar_year=1,
            sand_pct=sand_pct,
            clay_pct=clay_pct,
            soc_pct=soc_pct,
        )
        return (
            res["etc_mm"],
            res["peff_mm"],
            res["irrigation_gross_mm"],
            res["irrigation_m3_ha"],
            res["ks"],
        )

    @staticmethod
    def calculate_initial_soc_stock(
        soil_depth_layers: Optional[List[Any]] = None,
        fallback_soc_pct: float = 1.5,
        fallback_rho_b: float = 1.30,
        fallback_clay_pct: float = 25.0,
        fallback_cfvo_pct: float = 0.0,
        calibrated_topsoil_soc_pct: Optional[float] = None,
        target_depth_cm: float = 30.0,
    ) -> Tuple[float, float, float, float, float]:
        """
        Depth-weighted integration of C_0 over [0, 30 cm] accounting for bulk density rho_b and
        coarse-fragment fraction CF = cfvo / 100.
        Returns: (c_stock_0_t_ha, weighted_soc_pct, weighted_rho_b, weighted_clay_pct, weighted_cf_frac)
        """
        if soil_depth_layers:
            total_cm = 0.0
            c_stock = 0.0
            sum_rho_cm = 0.0
            sum_clay_cm = 0.0
            sum_cf_cm = 0.0
            sum_soc_rho_cf_cm = 0.0
            for lyr in soil_depth_layers:
                top = float(getattr(lyr, "top_depth_cm", 0.0) or 0.0)
                bot = float(getattr(lyr, "bottom_depth_cm", 30.0) or 30.0)
                ov_top = max(0.0, top)
                ov_bot = min(target_depth_cm, bot)
                if ov_bot <= ov_top:
                    continue
                dz_cm = ov_bot - ov_top
                soc_l = getattr(lyr, "soil_organic_carbon_pct", None)
                if soc_l is None:
                    soc_l = fallback_soc_pct
                rho_l = getattr(lyr, "bulk_density_g_cm3", None) or fallback_rho_b
                clay_l = getattr(lyr, "clay_pct", None)
                if clay_l is None:
                    clay_l = fallback_clay_pct
                cfvo_l = getattr(lyr, "coarse_fragments_vol_pct", None)
                if cfvo_l is None:
                    cfvo_l = fallback_cfvo_pct or 0.0
                cf_l = max(0.0, min(0.85, float(cfvo_l) / 100.0))

                c_stock += dz_cm * float(rho_l) * float(soc_l) * (1.0 - cf_l)
                total_cm += dz_cm
                sum_rho_cm += dz_cm * float(rho_l)
                sum_clay_cm += dz_cm * float(clay_l)
                sum_cf_cm += dz_cm * cf_l
                sum_soc_rho_cf_cm += dz_cm * float(rho_l) * (1.0 - cf_l)

            if total_cm > 0.0 and sum_soc_rho_cf_cm > 0.0:
                if total_cm < target_depth_cm:
                    # Extrapolate remaining depth down to 30 cm using deepest overlapping horizon ratio
                    scale = target_depth_cm / total_cm
                    c_stock *= scale
                    w_rho = sum_rho_cm / total_cm
                    w_clay = sum_clay_cm / total_cm
                    w_cf = sum_cf_cm / total_cm
                else:
                    w_rho = sum_rho_cm / total_cm
                    w_clay = sum_clay_cm / total_cm
                    w_cf = sum_cf_cm / total_cm

                w_soc = c_stock / (target_depth_cm * w_rho * max(0.15, 1.0 - w_cf))
                if calibrated_topsoil_soc_pct is not None:
                    # Rescale horizon C stock if local lab topsoil SOC overrides SoilGrids
                    ratio = calibrated_topsoil_soc_pct / max(0.05, w_soc) if w_soc > 0 else 1.0
                    c_stock *= max(0.2, min(5.0, ratio))
                    w_soc = calibrated_topsoil_soc_pct
                return round(c_stock, 3), round(w_soc, 3), round(w_rho, 3), round(w_clay, 2), round(w_cf, 4)

        eff_soc = calibrated_topsoil_soc_pct if calibrated_topsoil_soc_pct is not None else fallback_soc_pct
        cf_frac = max(0.0, min(0.85, (fallback_cfvo_pct or 0.0) / 100.0))
        c_stock = target_depth_cm * fallback_rho_b * eff_soc * (1.0 - cf_frac)
        return round(c_stock, 3), round(eff_soc, 3), round(fallback_rho_b, 3), round(fallback_clay_pct, 2), round(cf_frac, 4)

    @staticmethod
    def simulate_soc_dynamics(
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        current_soc_pct: float,
        mean_annual_temp_c: float = 14.0,
        tillage_factor: float = 1.0,  # Kept in signature for API compatibility; not multiplied into k2 per v1.1
        plow_depth_m: float = 0.30,
        actual_yield_tons_ha: Optional[float] = None,
        soilgrids_clay_pct: Optional[float] = None,
        soilgrids_bulk_density_g_cm3: Optional[float] = None,
        caco3_g_kg: Optional[float] = None,
        coarse_fragments_frac: float = 0.0,
        straw_export_fraction: float = 0.0,
        c_cover_tons_ha: float = 0.0,
        c_stock_start_override_t_ha: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Henin-Dupuis exact analytical integration with Mary & Guerif CaCO3 mineralization rate k2
        and Bolinder et al. (2007) NPP-based shoot, root, and rhizodeposit C inputs (k1_above vs k1_below).
        Returns: (soc_pct_end, delta_soc_pct, carbon_input_tons_ha, k2_rate)
        """
        rho_b = soilgrids_bulk_density_g_cm3 or soil_props["bulk_density_g_cm3"]
        clay_pct = soilgrids_clay_pct if soilgrids_clay_pct is not None else soil_props["clay_pct"]
        ca_g_kg = max(0.0, caco3_g_kg or 0.0)
        cf = max(0.0, min(0.85, coarse_fragments_frac))

        fine_mass_factor = max(10.0, 100.0 * rho_b * plow_depth_m * (1.0 - cf))
        c_stock_start = (
            c_stock_start_override_t_ha
            if c_stock_start_override_t_ha is not None
            else (fine_mass_factor * current_soc_pct)
        )

        # Mary & Guerif (1994) / Boiffin (1986) mineralization constant k2 with CaCO3 stabilization
        # No arbitrary f_till multipliers and no 0.012 artificial floor
        temp_eff = max(6.0, mean_annual_temp_c)
        k2 = (1200.0 * 0.2 * (temp_eff - 5.0)) / ((10.0 * clay_pct + 200.0) * (0.3 * ca_g_kg + 200.0))

        # Bolinder et al. (2007) dry-matter and C allocation
        harvested_yield = actual_yield_tons_ha if actual_yield_tons_ha is not None else crop.potential_yield_tons_ha
        dm_yield = max(0.0, harvested_yield) * crop.dry_matter_fraction
        export_frac = max(0.0, min(1.0, straw_export_fraction))

        if crop.bolinder_rp > 0.0:
            npp = dm_yield / crop.bolinder_rp
            c_shoot = 0.45 * npp * crop.bolinder_rs * (1.0 - export_frac)
            c_root = 0.45 * npp * crop.bolinder_rr
            c_extra = 0.65 * c_root
        else:
            # Unharvested cover crop (Rp = 0): biomass anchored directly to cover DM yield
            c_shoot = 0.45 * dm_yield * (1.0 - export_frac)
            c_root = 0.45 * dm_yield * (crop.bolinder_rr / max(0.1, crop.bolinder_rs))
            c_extra = 0.65 * c_root

        total_c_input = c_shoot + c_root + c_extra + max(0.0, c_cover_tons_ha)
        humus_input = crop.k1_above * c_shoot + crop.k1_below * (c_root + c_extra + max(0.0, c_cover_tons_ha))

        # Exact analytical solution to dC/dt = A - k2 * C over dt = 1 yr
        exp_k2 = math.exp(-k2)
        c_stock_end = max(5.0, c_stock_start * exp_k2 + (humus_input / max(1e-6, k2)) * (1.0 - exp_k2))
        soc_pct_end = round(c_stock_end / fine_mass_factor, 3)
        delta_soc_pct = round(soc_pct_end - current_soc_pct, 3)

        return soc_pct_end, delta_soc_pct, round(total_c_input, 2), round(k2, 5)

    @staticmethod
    def simulate_soil_compaction(
        crop: CropAgronomicProfile,
        current_compaction_psi: float,
        soil_props: Dict[str, float]
    ) -> Tuple[float, float]:
        """
        Simulates ASAE S313.3 Cone Penetrometer Compaction dynamics:
        - Machinery traffic adds compaction with diminishing returns per pass.
        - Deep taproots and bio-drill crops (Daikon radish, Alfalfa) fracture plowpans.
        Returns: (compaction_psi_end, compaction_delta_psi)
        """
        # Traffic compaction accumulation proportional to axle passes (avoids saturating at 2 passes)
        passes = max(1, crop.machinery_passes_count)
        traffic_addition = 8.0 + (4.0 * min(10, passes))

        # Heavy clay is more susceptible to wheel compaction
        clay_factor = 1.0 + (soil_props["clay_pct"] / 100.0)
        traffic_psi = traffic_addition * clay_factor

        # Bio-drill taproot hardpan alleviation (e.g. -65 PSI for Daikon Radish, -55 PSI for Alfalfa)
        relief_psi = crop.compaction_relief_delta_psi

        delta_psi = round(traffic_psi + relief_psi, 1)
        final_psi = max(120.0, min(380.0, current_compaction_psi + delta_psi))
        actual_delta = round(final_psi - current_compaction_psi, 1)
        return round(final_psi, 1), actual_delta

    @staticmethod
    def calculate_nitrogen_budget_detailed(
        crop: CropAgronomicProfile,
        yield_tons_ha: float,
        c_stock_start_t_ha: float = 55.0,
        k2_rate: float = 0.02,
        preceding_legume_credit_kg_ha: float = 0.0,
        preceding_scavenged_credit_kg_ha: float = 0.0,
        cn_ratio: float = 11.0,
        monthly_climate: Optional[Dict[int, Dict[str, float]]] = None,
        calendar_months: Optional[List[Dict[str, Any]]] = None,
        annual_precip_mm: float = 620.0,
        annual_et0_mm: float = 1200.0,
        straw_export_fraction: float = 0.0,
        max_legal_n_kg_ha: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        v1.1 coupled carbon-nitrogen budget (Herridge/Peoples BNF, C-coupled N_min,
        Ladha RE_N=0.40, and IPCC 2019 Vol. 4 Ch. 11 wet/dry leaching & direct N2O).
        """
        nhi = max(0.05, min(1.0, crop.nitrogen_harvest_index))
        is_cover = crop.bolinder_rp == 0.0
        n_harvest = 0.0 if is_cover else (yield_tons_ha * crop.nitrogen_uptake_kg_per_ton)
        n_shoot = (yield_tons_ha * crop.nitrogen_uptake_kg_per_ton) / nhi

        # Carbon-coupled soil organic nitrogen mineralization (kg N/ha/yr)
        cn_eff = max(6.0, min(25.0, cn_ratio))
        n_min_yr = (1000.0 * max(0.0, k2_rate) * max(0.0, c_stock_start_t_ha)) / cn_eff

        thermal_frac = min(1.0, crop.growth_cycle_days / 365.0)
        if monthly_climate and calendar_months:
            ann_dd = sum(max(0.0, monthly_climate[m]["tmean_c"] - 5.0) for m in range(1, 13))
            if ann_dd > 0.0:
                crop_dd = sum(
                    cm["f_m"] * max(0.0, monthly_climate[cm["month"]]["tmean_c"] - 5.0)
                    for cm in calendar_months
                )
                thermal_frac = max(0.10, min(1.0, crop_dd / ann_dd))
        n_min_season = n_min_yr * thermal_frac

        export_frac = max(0.0, min(1.0, straw_export_fraction))
        next_legume_credit = 0.0
        next_scavenged_credit = 0.0
        legume_credit_used = 0.0
        scavenged_credit_used = 0.0

        if crop.is_legume:
            n_plant = crop.f_bgn * n_shoot
            bio_fixed_n = crop.ndfa_fraction * n_plant
            synthetic_n_applied = 0.0
            aboveground_res_n = max(0.0, n_shoot - n_harvest) * (1.0 - export_frac)
            belowground_n = max(0.0, n_plant - n_shoot)
            n_res_fcr = aboveground_res_n + belowground_n
            # Own-season balance excludes next crop's release credit; pass credit forward
            next_legume_credit = crop.residue_n_release_fraction * n_res_fcr
            net_n_balance = bio_fixed_n - n_harvest
        elif is_cover:
            bio_fixed_n = 0.0
            synthetic_n_applied = 0.0
            n_res_fcr = n_shoot * (1.0 - export_frac) + 0.25 * n_shoot
            next_scavenged_credit = crop.scavenged_n_credit_kg_ha
            net_n_balance = crop.scavenged_n_credit_kg_ha
        else:
            bio_fixed_n = 0.0
            legume_credit_used = min(n_shoot, max(0.0, preceding_legume_credit_kg_ha))
            remaining_after_leg = max(0.0, n_shoot - legume_credit_used)
            scavenged_credit_used = min(remaining_after_leg, max(0.0, preceding_scavenged_credit_kg_ha))

            n_demand = max(0.0, n_shoot - n_min_season - legume_credit_used - scavenged_credit_used)
            re_n = 0.40  # Ladha et al. cereal/arable fertilizer N recovery efficiency
            synthetic_uncapped = n_demand / re_n
            synthetic_n_applied = (
                min(synthetic_uncapped, max_legal_n_kg_ha)
                if max_legal_n_kg_ha is not None
                else synthetic_uncapped
            )
            n_res_fcr = max(0.0, n_shoot - n_harvest) * (1.0 - export_frac) + 0.25 * n_shoot
            net_n_balance = synthetic_n_applied + legume_credit_used + scavenged_credit_used - n_harvest

        n_surplus = synthetic_n_applied + bio_fixed_n - n_harvest

        # IPCC 2019 Vol. 4 Ch. 11 wet vs dry climate N2O & leaching emission factors
        is_wet = (annual_precip_mm / max(100.0, annual_et0_mm)) >= 1.0 or annual_precip_mm >= 1000.0
        frac_leach = 0.24 if is_wet else 0.0
        ef1_synth = 0.016 if is_wet else 0.005
        ef1_other = 0.006 if is_wet else 0.005

        n_leach = frac_leach * max(0.0, synthetic_n_applied + n_res_fcr + n_min_season)
        direct_n2o_n = ef1_synth * synthetic_n_applied + ef1_other * max(0.0, n_res_fcr + n_min_season)

        return {
            "net_soil_n_balance_kg_ha": round(net_n_balance, 1),
            "biological_n_fixed_kg_ha": round(bio_fixed_n, 1),
            "synthetic_n_applied_kg_ha": round(synthetic_n_applied, 1),
            "legume_credit_used_kg_ha": round(legume_credit_used, 1),
            "scavenged_credit_used_kg_ha": round(scavenged_credit_used, 1),
            "soil_mineralized_n_kg_ha": round(n_min_season, 1),
            "nitrogen_surplus_kg_ha": round(n_surplus, 1),
            "nitrogen_leaching_kg_ha": round(n_leach, 2),
            "direct_n2o_n_kg_ha": round(direct_n2o_n, 2),
            "next_legume_credit_kg_ha": round(next_legume_credit, 1),
            "next_scavenged_credit_kg_ha": round(next_scavenged_credit, 1),
            "n_harvest_export_kg_ha": round(n_harvest, 1),
        }

    @classmethod
    def calculate_nitrogen_balance(
        cls,
        crop: CropAgronomicProfile,
        yield_tons_ha: float,
        preceding_legume_credit_kg_ha: float = 0.0,
        in_situ_soil_nitrate_ppm: float = 25.0,
        in_situ_soil_n_kg_ha: Optional[float] = None,
        c_stock_start_t_ha: Optional[float] = None,
        k2_rate: float = 0.02,
        cn_ratio: float = 11.0,
        annual_precip_mm: float = 620.0,
        annual_et0_mm: float = 1200.0,
        straw_export_fraction: float = 0.0,
        max_legal_n_kg_ha: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Backward-compatible wrapper returning:
        (net_soil_n_balance_kg_ha, biological_n_fixed_kg_ha, synthetic_n_applied_kg_ha, legume_credit_used)
        """
        # Default 58 t C/ha (~1.5% SOC at 1.3 g/cm3 over 30 cm) when carbon stock omitted by legacy caller
        c_stock_eff = c_stock_start_t_ha if c_stock_start_t_ha is not None else 58.5
        res = cls.calculate_nitrogen_budget_detailed(
            crop=crop,
            yield_tons_ha=yield_tons_ha,
            c_stock_start_t_ha=c_stock_eff,
            k2_rate=k2_rate,
            preceding_legume_credit_kg_ha=preceding_legume_credit_kg_ha,
            cn_ratio=cn_ratio,
            annual_precip_mm=annual_precip_mm,
            annual_et0_mm=annual_et0_mm,
            straw_export_fraction=straw_export_fraction,
            max_legal_n_kg_ha=max_legal_n_kg_ha,
        )
        return (
            res["net_soil_n_balance_kg_ha"],
            res["biological_n_fixed_kg_ha"],
            res["synthetic_n_applied_kg_ha"],
            res["legume_credit_used_kg_ha"],
        )

    @staticmethod
    def resolve_gloreda_r_factor(
        annual_precip_mm: float,
        gloreda_r_factor: Optional[float] = None,
        latitude_deg: Optional[float] = None,
        longitude_deg: Optional[float] = None,
    ) -> Tuple[float, str]:
        """
        Primary rainfall erosivity R from GloREDa (direct override or regional benchmark),
        falling back to Renard & Freimund (1994) when outside calibrated regions.
        Returns: (r_factor, source_label)
        """
        if gloreda_r_factor is not None and gloreda_r_factor > 0:
            return float(gloreda_r_factor), "GloREDa Direct Input"

        if latitude_deg is not None and longitude_deg is not None:
            for region_name, lat_min, lat_max, lon_min, lon_max, r_val in GLOREDA_REGIONAL_BENCHMARKS:
                if lat_min <= latitude_deg <= lat_max and lon_min <= longitude_deg <= lon_max:
                    return r_val, region_name

        p_mm = max(50.0, annual_precip_mm)
        if p_mm <= 850.0:
            r_val = max(40.0, 0.04830 * (p_mm ** 1.61))
        else:
            r_val = max(40.0, 587.8 - (1.219 * p_mm) + (0.004105 * (p_mm ** 2)))
        return r_val, "Renard & Freimund (1994) Annual Precipitation Fallback"

    @classmethod
    def calculate_rusle_erosion(
        cls,
        crop: CropAgronomicProfile,
        soil_props: Dict[str, float],
        slope_pct: float,
        annual_precip_mm: float,
        soilgrids_sand_pct: Optional[float] = None,
        soilgrids_silt_pct: Optional[float] = None,
        soilgrids_clay_pct: Optional[float] = None,
        soilgrids_soc_pct: Optional[float] = None,
        area_hectares: float = 10.0,
        gloreda_r_factor: Optional[float] = None,
        latitude_deg: Optional[float] = None,
        longitude_deg: Optional[float] = None,
        slope_max_pct: Optional[float] = None,
    ) -> float:
        """
        Revised Universal Soil Loss Equation (RUSLE): A = R * K * LS * C * P (t / ha / yr).
        Primary R: GloREDa (direct or regional lookup) with Renard-Freimund fallback.
        EPIC K (Williams 1995), Moore & Burch (1986) LS (using parcel max slope when provided
        to avoid diluting steep hillside risk), Panagos et al. (2015) C, and P = 1.0.
        """
        r_factor, _ = cls.resolve_gloreda_r_factor(
            annual_precip_mm=annual_precip_mm,
            gloreda_r_factor=gloreda_r_factor,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
        )

        # Soil erodibility factor K: EPIC Williams (1995) when particle fractions exist, else texture lookup
        if (
            soilgrids_sand_pct is not None
            and soilgrids_silt_pct is not None
            and soilgrids_clay_pct is not None
        ):
            sand = max(0.0, min(100.0, soilgrids_sand_pct))
            silt = max(0.0, min(100.0, soilgrids_silt_pct))
            clay = max(0.0, min(100.0, soilgrids_clay_pct))
            soc = max(0.1, soilgrids_soc_pct if soilgrids_soc_pct is not None else 1.5)
            sn1 = 1.0 - sand / 100.0
            f_csand = 0.2 + 0.3 * math.exp(-0.256 * sand * (1.0 - silt / 100.0))
            f_cl_si = (silt / max(1.0, clay + silt)) ** 0.3
            f_orgc = 1.0 - (0.25 * soc) / (soc + math.exp(3.72 - 2.95 * soc))
            f_hisand = 1.0 - (0.7 * sn1) / (sn1 + math.exp(-5.51 + 22.9 * sn1))
            k_factor = max(0.005, min(0.08, f_csand * f_cl_si * f_orgc * f_hisand * 0.1317))
        else:
            k_factor = soil_props["rusle_k_factor"] * 0.1317

        # Use steepest slope segment (slope_max_pct) on sloped parcels to avoid mean-slope dilution
        eff_slope = slope_max_pct if (slope_max_pct is not None and slope_max_pct > slope_pct) else slope_pct
        slope_rad = math.atan(max(0.1, eff_slope) / 100.0)
        flow_length_m = max(22.13, min(150.0, math.sqrt(max(0.5, area_hectares) * 10000.0) * 0.5))
        ls_factor = max(
            0.05,
            ((flow_length_m / 22.13) ** 0.4) * ((math.sin(slope_rad) / 0.0896) ** 1.3),
        )
        c_factor = crop.rusle_c_factor
        p_factor = 1.0

        erosion_tons_ha = r_factor * k_factor * ls_factor * c_factor * p_factor
        return round(max(0.05, erosion_tons_ha), 2)

    @staticmethod
    def evaluate_rotational_health(
        current_crop: CropAgronomicProfile,
        preceding_crop: Optional[CropAgronomicProfile]
    ) -> Tuple[float, float, float]:
        """
        Evaluates Botanical Pathology Risk & Rhizosphere Vitality (returns 0.0 arbitrary USD fines;
        pest/disease rotation breaks are enforced via agronomic eligibility and yield penalties).
        Returns: (pathogen_risk_score, rhizosphere_score, botanical_penalty_usd_ha)
        """
        if preceding_crop is None:
            return 25.0, 70.0, 0.0

        same_family = current_crop.botanical_family == preceding_crop.botanical_family

        if same_family:
            if current_crop.botanical_family == BotanicalFamily.SOLANACEAE:
                return 85.0, 30.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.BRASSICACEAE:
                return 75.0, 40.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.FABACEAE:
                return 70.0, 45.0, 0.0
            elif current_crop.botanical_family == BotanicalFamily.POACEAE:
                return 65.0, 50.0, 0.0
            else:
                return 60.0, 55.0, 0.0

        # Beneficial botanical rotation
        pathogen_score = 20.0
        rhizosphere_score = 80.0

        # Biofumigant bonus (Canola or Daikon Radish suppresses soil-borne nematodes)
        if preceding_crop.biofumigant_active:
            pathogen_score -= 10.0
            rhizosphere_score += 10.0

        # Legume followed by cereal synergy
        if preceding_crop.is_legume and not current_crop.is_legume:
            rhizosphere_score += 10.0

        return max(5.0, pathogen_score), min(100.0, rhizosphere_score), 0.0
