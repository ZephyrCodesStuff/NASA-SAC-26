"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { DatasetState, fmt, num, okValues, pick, str } from "@/lib/use-nasa-data";

type Datasets = Record<string, DatasetState>;

// ---------------------------------------------------------------- building blocks
function StatusDot({ ds }: { ds?: DatasetState }) {
  if (!ds || ds.state === "loading")
    return <Loader2 className="h-3 w-3 animate-spin text-[#6b675f]" />;
  const status = ds.state === "error" ? "error" : ds.data?.status;
  const tone =
    status === "ok" ? "bg-emerald-500" : status === "no_data" || status === "unavailable" ? "bg-amber-500" : "bg-rose-500";
  return <span className={`h-2 w-2 rounded-full ${tone}`} title={ds.error || ds.data?.note || status} />;
}

function DataCard({
  title,
  ds,
  children,
  className = "",
}: {
  title: string;
  ds?: DatasetState;
  children: React.ReactNode;
  className?: string;
}) {
  const d = ds?.data;
  const problem =
    ds?.state === "error" ? ds.error : d && d.status !== "ok" ? d.note || d.error || d.status : null;
  return (
    <div className={`rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-2.5 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusDot ds={ds} />
          <h3 className="text-xs font-mono uppercase tracking-wider text-[#1f1915]">{title}</h3>
        </div>
        {d?.scale && (
          <span className="text-[10px] font-mono text-[#6b675f] text-right">
            {d.scale}
            {d.resolution_m ? ` · ${d.resolution_m >= 1000 ? `${d.resolution_m / 1000} km` : `${d.resolution_m} m`}` : ""}
            {d.date && d.date !== "static" ? ` · ${String(d.date).slice(0, 10)}` : ""}
          </span>
        )}
      </div>
      {ds?.state === "loading" || !ds ? (
        <p className="text-[11px] text-[#6b675f]">Loading…</p>
      ) : problem ? (
        <p className="text-[11px] text-amber-700 break-words">{String(problem).slice(0, 220)}</p>
      ) : (
        children
      )}
      {d?.source && <p className="text-[10px] text-[#6b675f] pt-1 border-t border-[#e7e5e0]">{d.source}</p>}
    </div>
  );
}

function Row({ k, v, hint }: { k: string; v: React.ReactNode; hint?: string }) {
  return (
    <div className="flex justify-between gap-3 text-xs" title={hint}>
      <span className="text-[#6b675f]">{k}</span>
      <span className="font-mono tabular-nums text-right">{v}</span>
    </div>
  );
}

function Pill({ text, tone }: { text: string; tone: "good" | "warn" | "bad" | "neutral" }) {
  const cls = {
    good: "text-emerald-700 bg-emerald-50 border-emerald-200",
    warn: "text-amber-700 bg-amber-50 border-amber-200",
    bad: "text-rose-700 bg-rose-50 border-rose-200",
    neutral: "text-[#6b675f] bg-[#f5f4ef] border-[#e7e5e0]",
  }[tone];
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-mono ${cls}`}>{text}</span>;
}

function riskTone(r: string | null): "good" | "warn" | "bad" | "neutral" {
  if (!r) return "neutral";
  if (r.startsWith("low") || r.includes("wetter") || r === "near normal") return "good";
  if (r.startsWith("moderate") || r.includes("drier")) return "warn";
  return "bad";
}

function Sparkline({ values, max = 1, min = 0 }: { values: Array<number | null>; max?: number; min?: number }) {
  const w = 120;
  const h = 22;
  const pts = values
    .map((v, i) => (v === null ? null : [(i / Math.max(1, values.length - 1)) * w, h - ((v - min) / (max - min)) * h]))
    .filter(Boolean) as number[][];
  if (pts.length < 2) return <span className="text-[10px] text-[#6b675f]">—</span>;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[22px] w-[120px]">
      <path d={pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")} fill="none" stroke="#20808d" strokeWidth={1.5} />
    </svg>
  );
}

// ---------------------------------------------------------------- the panel
export function NasaDataPanel({ datasets }: { datasets: Datasets }) {
  const w = okValues(datasets.weather);
  const rain = okValues(datasets.rainfall);
  const sm = okValues(datasets.soil_moisture);
  const etf = okValues(datasets.evapotranspiration_field);
  const eta = okValues(datasets.evapotranspiration_area);
  const gw = okValues(datasets.groundwater);
  const ch = okValues(datasets.crop_health);
  const soil = okValues(datasets.soil);
  const terr = okValues(datasets.terrain);
  const ero = okValues(datasets.erosion);
  const hist = okValues(datasets.crop_history);
  const proj = okValues(datasets.climate_projection);
  const local = okValues(datasets.local_prices);
  const market = okValues(datasets.market_prices);
  const fao = okValues(datasets.regional_production);

  const topsoil = (soil?.["0-5cm"] || {}) as Record<string, unknown>;
  const seasons = (pick(hist, "seasons") as Array<Record<string, unknown>>) || [];
  const seasonCurves = (datasets.crop_history?.data?.history as Array<Record<string, unknown>>) || [];
  const projections = (pick(proj, "projections") as Record<string, Record<string, unknown>>) || {};
  const ext = (pick(w, "extremes_last_365_days") || {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      {/* Weather & climate */}
      <section className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Weather &amp; climate</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <DataCard title="Weather today" ds={datasets.weather}>
            <Row k="Air temperature" v={fmt(num(w, "latest.T2M"), 1, " °C")} />
            <Row k="Min / max" v={`${fmt(num(w, "latest.T2M_MIN"))} / ${fmt(num(w, "latest.T2M_MAX"), 1, " °C")}`} />
            <Row k="Humidity" v={fmt(num(w, "latest.RH2M"), 0, " %")} />
            <Row k="Dew point" v={fmt(num(w, "latest.T2MDEW"), 1, " °C")} />
            <Row k="Wind (max)" v={`${fmt(num(w, "latest.WS2M"))} (${fmt(num(w, "latest.WS2M_MAX"))}) m/s`} />
            <Row k="Solar radiation" v={fmt(num(w, "latest.ALLSKY_SFC_SW_DWN"), 1, " MJ/m²")} />
            <Row k="Daylight today" v={fmt(num(w, "today.daylight_h"), 1, " h")} hint="sunrise → sunset" />
            <Row k="Daylight range" v={`${fmt(num(w, "today.daylight_h_shortest_day"))}–${fmt(num(w, "today.daylight_h_longest_day"), 1, " h")}`} />
            <Row k="Data day" v={str(w, "latest.date") || "—"} />
          </DataCard>
          <DataCard title="Last 7 / 30 days" ds={datasets.weather}>
            <Row k="Rain 7 d / 30 d" v={`${fmt(num(w, "last_7_days.precip_mm"), 0)} / ${fmt(num(w, "last_30_days.precip_mm"), 0, " mm")}`} />
            <Row k="Mean temp 30 d" v={fmt(num(w, "last_30_days.t_mean_c"), 1, " °C")} />
            <Row k="Normal for month" v={fmt(num(w, "last_30_days.normal_t_mean_c_this_month"), 1, " °C")} />
            <Row k="Humidity 7 d / 30 d" v={`${fmt(num(w, "last_7_days.rh_mean_pct"), 0)} / ${fmt(num(w, "last_30_days.rh_mean_pct"), 0, " %")}`} />
            <Row k="Sunshine fraction" v={fmt(num(w, "last_30_days.sunshine_fraction"), 2)} hint="1 = cloudless" />
            <Row k="Evapotranspiration 30 d" v={fmt(num(w, "last_30_days.evapotranspiration_mm"), 0, " mm")} />
            <Row k="Frost / heat days (7 d)" v={`${num(w, "last_7_days.frost_days") ?? "—"} / ${num(w, "last_7_days.heat_days_over_35c") ?? "—"}`} />
            <Row k="GDD since 1 Jan" v={fmt(num(w, "gdd_since_jan1.value"), 0, " °C·d")} />
          </DataCard>
          <DataCard title="Extremes · last 365 days" ds={datasets.weather}>
            <Row k="Hottest day" v={`${fmt(num(ext, "hottest_day.t_max_c"), 1, " °C")} · ${str(ext, "hottest_day.date") || ""}`} />
            <Row k="Coldest night" v={`${fmt(num(ext, "coldest_night.t_min_c"), 1, " °C")} · ${str(ext, "coldest_night.date") || ""}`} />
            <Row k="Wettest day" v={`${fmt(num(ext, "wettest_day.precip_mm"), 0, " mm")} · ${str(ext, "wettest_day.date") || ""}`} />
            <Row k="Windiest day" v={`${fmt(num(ext, "windiest_day.wind_max_ms"), 1, " m/s")} · ${str(ext, "windiest_day.date") || ""}`} />
            <Row k="Frost / heat days" v={`${num(ext, "frost_days") ?? "—"} / ${num(ext, "heat_days_over_35c") ?? "—"}`} />
            <Row k="Heavy-rain days (≥30 mm)" v={num(ext, "heavy_rain_days_over_30mm") ?? "—"} />
            <Row k="Gale days" v={num(ext, "gale_days_wind_over_10_8ms") ?? "—"} />
            <Row k="Longest dry spell" v={fmt(num(ext, "longest_dry_spell_days"), 0, " days")} />
            <Row k="Total rain" v={fmt(num(ext, "total_precip_mm"), 0, " mm")} />
          </DataCard>
        </div>
      </section>

      {/* Water */}
      <section className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Water &amp; water stress</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <DataCard title="Rainfall (satellite)" ds={datasets.rainfall}>
            <Row k="Last day" v={`${fmt(num(rain, "latest_day.precip_mm"), 1, " mm")} · ${str(rain, "latest_day.date") || ""}`} />
            <Row k="3 / 7 days" v={`${fmt(num(rain, "total_3d_mm"), 0)} / ${fmt(num(rain, "total_7d_mm"), 0, " mm")}`} />
            <Row k="30 days" v={fmt(num(rain, "total_30d_mm"), 0, " mm")} />
            <Row k="Dry days in a row" v={num(rain, "consecutive_dry_days") ?? "—"} />
          </DataCard>
          <DataCard title="Soil moisture" ds={datasets.soil_moisture}>
            <Row k="Surface 0–5 cm" v={fmt(num(sm, "surface_m3m3"), 3, " m³/m³")} />
            <Row k="Root zone 0–100 cm" v={fmt(num(sm, "rootzone_m3m3"), 3, " m³/m³")} />
            <Row k="Root-zone wetness" v={fmt((num(sm, "rootzone_wetness") ?? NaN) * 100, 0, " %")} hint="% of saturation" />
            <Row k="Time" v={(str(sm, "time") || "—").slice(0, 16)} />
          </DataCard>
          <DataCard title="Groundwater (regional)" ds={datasets.groundwater}>
            <Row k="Storage anomaly" v={`${fmt(num(gw, "latest.anomaly_cm"), 1, " cm")} · ${str(gw, "latest.month") || ""}`} />
            <Row k="12-month trend" v={fmt(num(gw, "trend_last_12_months_cm"), 1, " cm")} />
            <Row k="Percentile (same month)" v={fmt(num(gw, "percentile_vs_same_month_all_years"), 0)} />
            <div className="pt-1">
              <Pill text={str(gw, "interpretation") || "—"} tone={riskTone(str(gw, "interpretation"))} />
            </div>
          </DataCard>
          <DataCard title="Crop water use · field (ECOSTRESS)" ds={datasets.evapotranspiration_field}>
            <Row k="Evapotranspiration" v={`${fmt(num(etf, "et_daily.mean"), 1, " mm/day")}`} hint={str(etf, "et_daily.datetime") || ""} />
            <Row k="Stress index (ESI)" v={fmt(num(etf, "esi.mean"), 2)} hint="0–1, low = water stress" />
            <Row k="Surface temperature" v={fmt(num(etf, "lst.mean"), 1, " °C")} />
          </DataCard>
          <DataCard title="Crop water use · area (MODIS)" ds={datasets.evapotranspiration_area}>
            <Row k="ET (8-day)" v={fmt(num(eta, "et_mm_8day"), 1, " mm")} />
            <Row k="Potential ET (8-day)" v={fmt(num(eta, "pet_mm_8day"), 1, " mm")} />
            <Row k="ET per day" v={fmt(num(eta, "et_mm_per_day"), 2, " mm")} />
            <Row k="ET / PET" v={fmt(num(eta, "et_pet_ratio"), 2)} hint="low = water-limited" />
          </DataCard>
          <DataCard title="Crop health (HLS 30 m)" ds={datasets.crop_health}>
            <Row k="NDVI (vigour)" v={fmt(num(ch, "ndvi.mean"), 2)} />
            <Row k="NDMI (canopy water)" v={fmt(num(ch, "ndmi.mean"), 2)} />
            <Row k="NDRE (nitrogen)" v={fmt(num(ch, "ndre.mean"), 2)} />
            <Row k="Patchy share" v={fmt((num(ch, "low_vigor_fraction") ?? NaN) * 100, 0, " %")} />
            <Row k="Scene" v={`${str(ch, "sensor") || ""} · ${fmt((num(ch, "clear_fraction") ?? NaN) * 100, 0, "% clear")}`} />
          </DataCard>
        </div>
      </section>

      {/* Soil, terrain, erosion */}
      <section className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Soil, terrain &amp; erosion</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <DataCard title="Topsoil 0–5 cm" ds={datasets.soil}>
            <Row k="Texture" v={str(topsoil, "texture_class") || "—"} />
            <Row k="Clay / silt / sand" v={`${fmt(num(topsoil, "clay"), 0)} / ${fmt(num(topsoil, "silt"), 0)} / ${fmt(num(topsoil, "sand"), 0, " %")}`} />
            <Row k="Organic carbon" v={fmt(num(topsoil, "soc"), 1, " g/kg")} />
            <Row k="pH" v={fmt(num(topsoil, "phh2o"), 1)} />
            <Row k="Nitrogen" v={fmt(num(topsoil, "nitrogen"), 2, " g/kg")} />
            <Row k="CEC" v={fmt(num(topsoil, "cec"), 1, " cmol/kg")} />
            <Row k="Bulk density" v={fmt(num(topsoil, "bdod"), 2, " g/cm³")} />
          </DataCard>
          <DataCard title="Terrain (NASADEM)" ds={datasets.terrain}>
            <Row k="Elevation" v={`${fmt(num(terr, "elevation_m.mean"), 0, " m")} (${fmt(num(terr, "elevation_m.min"), 0)}–${fmt(num(terr, "elevation_m.max"), 0)})`} />
            <Row k="Slope mean / max" v={`${fmt(num(terr, "slope_deg.mean"))} / ${fmt(num(terr, "slope_deg.max"), 1, "°")}`} />
            <Row k="Aspect" v={fmt(num(terr, "aspect_deg"), 0, "°")} hint="0 = north-facing" />
            <Row k="Share steeper than 8°" v={fmt((num(terr, "share_steeper_than_8deg") ?? NaN) * 100, 0, " %")} />
            <Row k="Vs surroundings" v={fmt(num(terr, "relative_elevation_m"), 1, " m")} />
            <div className="pt-1">
              <Pill text={pick(terr, "low_spot") ? "low spot: waterlogging risk" : "no low spot"} tone={pick(terr, "low_spot") ? "warn" : "good"} />
            </div>
          </DataCard>
          <DataCard title="Erosion (RUSLE)" ds={datasets.erosion}>
            <Row k="Soil loss, bare" v={fmt(num(ero, "soil_loss_bare_t_ha_yr"), 1, " t/ha/yr")} />
            <Row k="Soil loss, current cover" v={fmt(num(ero, "soil_loss_current_cover_t_ha_yr"), 1, " t/ha/yr")} />
            <Row k="R · K · LS · C" v={`${fmt(num(ero, "r_factor"), 0)} · ${fmt(num(ero, "k_factor"), 3)} · ${fmt(num(ero, "ls_factor"), 2)} · ${fmt(num(ero, "c_factor_current"), 2)}`} />
            <div className="flex gap-1.5 pt-1">
              <Pill text={`bare: ${str(ero, "risk_bare") || "—"}`} tone={riskTone(str(ero, "risk_bare"))} />
              <Pill text={`now: ${str(ero, "risk_current_cover") || "—"}`} tone={riskTone(str(ero, "risk_current_cover"))} />
            </div>
          </DataCard>
        </div>
      </section>

      {/* Crop history */}
      <DataCard title="What grew here · last 5 years (HLS phenology)" ds={datasets.crop_history}>
        <table className="w-full text-xs">
          <thead className="text-[10px] font-mono text-[#6b675f]">
            <tr>
              <th className="text-left py-1">Year</th>
              <th className="text-left py-1">Crop group</th>
              <th className="text-left py-1">Peak</th>
              <th className="text-left py-1">Green season</th>
              <th className="text-left py-1">NDVI curve</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e7e5e0]">
            {seasons.map((s) => {
              const curve = seasonCurves.find((c) => c.year === s.year);
              const vals = ((curve?.ndvi_by_period as Array<Record<string, unknown>>) || []).map((p) => num(p, "ndvi"));
              return (
                <tr key={String(s.year)}>
                  <td className="py-1.5 font-mono">
                    {String(s.year)}
                    {s.complete ? "" : "*"}
                  </td>
                  <td className="py-1.5">
                    {String(s.crop_group)} <span className="text-[10px] text-[#6b675f]">({String(s.confidence)})</span>
                  </td>
                  <td className="py-1.5 font-mono">
                    {fmt(num(s, "peak_ndvi"), 2)} · {String(s.peak_period || "")}
                  </td>
                  <td className="py-1.5 font-mono">{String(s.green_season || "—")}</td>
                  <td className="py-1.5">
                    <Sparkline values={vals} min={-0.1} max={1} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="text-[10px] text-[#6b675f]">
          Most common: {str(hist, "most_common_crop_group") || "—"} · rotates: {pick(hist, "rotates") ? "yes" : "no"} · * = year in progress
        </p>
      </DataCard>

      {/* Climate projection */}
      <DataCard title="Climate projection · 2030s & 2050s (NEX-GDDP-CMIP6)" ds={datasets.climate_projection}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="text-[10px] font-mono text-[#6b675f]">
              <tr>
                <th className="text-left py-1">Window</th>
                <th className="text-right py-1">Rain mm/yr</th>
                <th className="text-right py-1">Water balance</th>
                <th className="text-right py-1">Summer Tmax</th>
                <th className="text-right py-1">Days &gt;35°C</th>
                <th className="text-right py-1">Dry spell</th>
                <th className="text-left py-1 pl-3">Drought risk</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e7e5e0] font-mono">
              {[["Baseline (2000s)", pick(proj, "baseline_2000s") as Record<string, unknown>], ...Object.entries(projections)].map(
                ([label, p]) =>
                  p && (
                    <tr key={String(label)}>
                      <td className="py-1.5 font-sans">{String(label).replace(/_/g, " ")}</td>
                      <td className="py-1.5 text-right">{fmt(num(p, "precip_mm"), 0)}</td>
                      <td className="py-1.5 text-right">{fmt(num(p, "water_balance_mm"), 0)}</td>
                      <td className="py-1.5 text-right">{fmt(num(p, "t_max_summer_c"), 1)}</td>
                      <td className="py-1.5 text-right">{fmt(num(p, "heat_days_over_35c"), 0)}</td>
                      <td className="py-1.5 text-right">{fmt(num(p, "longest_dry_spell_days"), 0)}</td>
                      <td className="py-1.5 pl-3">
                        {str(p, "drought_risk") ? <Pill text={str(p, "drought_risk")!} tone={riskTone(str(p, "drought_risk"))} /> : ""}
                      </td>
                    </tr>
                  )
              )}
            </tbody>
          </table>
        </div>
      </DataCard>

      {/* Prices */}
      <section className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Prices &amp; markets</h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <DataCard title="Local prices (Eurostat, Oil Bulletin)" ds={datasets.local_prices}>
            {((pick(local, "crop_selling_prices") as Array<Record<string, unknown>>) || [])
              .filter((c) => /wheat|maize|rice|barley|soya|sunflower|rape/i.test(String(c.crop)))
              .slice(0, 8)
              .map((c) => (
                <Row key={String(c.crop)} k={String(c.crop)} v={`€${fmt(num(c, "latest.eur_per_t"), 0)}/t · ${str(c, "latest.year") || ""}`} />
              ))}
            <Row
              k="Electricity (farm)"
              v={(() => {
                const s = pick(local, "energy.electricity.MWH500-1999.excl_taxes") as Array<Record<string, unknown>> | undefined;
                const last = s?.[s.length - 1];
                return last ? `€${fmt(num(last, "price"), 3)}/kWh · ${str(last, "semester")}` : "—";
              })()}
            />
            <Row
              k="Natural gas"
              v={(() => {
                const s = pick(local, "energy.natural_gas.GJ1000-9999.excl_taxes") as Array<Record<string, unknown>> | undefined;
                const last = s?.[s.length - 1];
                return last ? `€${fmt(num(last, "price"), 3)}/kWh` : "—";
              })()}
            />
            <Row k="Diesel (with / w/o tax)" v={`€${fmt(num(local, "fuel.diesel.latest_with_taxes.eur_per_litre"), 2)} / €${fmt(num(local, "fuel.diesel.latest_without_taxes.eur_per_litre"), 2)} /l`} />
          </DataCard>
          <DataCard title="World market (World Bank)" ds={datasets.market_prices}>
            {Object.entries(market || {})
              .filter(([k]) => ["crude_oil_brent", "natural_gas_europe", "urea", "dap", "potassium_chloride", "maize", "wheat_us_hrw", "rice_thai_5pct", "soybeans"].includes(k))
              .map(([k, v]) => {
                const ch12 = num(v, "change_12m_pct");
                return (
                  <Row
                    key={k}
                    k={str(v, "name") || k}
                    v={
                      <>
                        {fmt(num(v, "latest.price"), 1)} {str(v, "unit")}{" "}
                        <span className={ch12 !== null && ch12 >= 0 ? "text-rose-700" : "text-emerald-700"}>
                          {ch12 !== null ? `${ch12 >= 0 ? "+" : ""}${ch12.toFixed(0)}%` : ""}
                        </span>
                      </>
                    }
                  />
                );
              })}
          </DataCard>
          <DataCard title={`National crops (FAOSTAT${str(fao, "country.name") ? ` · ${str(fao, "country.name")}` : ""})`} ds={datasets.regional_production}>
            {((pick(fao, "crops") as Array<Record<string, unknown>>) || []).slice(0, 9).map((c) => (
              <Row
                key={String(c.crop)}
                k={String(c.crop)}
                v={`${fmt((num(c, "latest.yield_kg_per_ha") ?? NaN) / 1000, 1, " t/ha")}${
                  num(c, "latest.producer_price_lcu_per_t") !== null ? ` · ${fmt(num(c, "latest.producer_price_lcu_per_t"), 0)}/t` : ""
                }`}
              />
            ))}
          </DataCard>
        </div>
      </section>
    </div>
  );
}
