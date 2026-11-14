"use client";

import React, { useState } from "react";
import dynamic from "next/dynamic";
import {
  ChevronDown,
  ChevronUp,
  CloudRain,
  Droplets,
  Leaf,
  Loader2,
  Mountain,
  Sprout,
  Sun,
  ThermometerSun,
  TrendingUp,
  Waves,
} from "lucide-react";
import { DatasetState, fmt, num, okValues, pick, str } from "@/lib/use-nasa-data";

const NasaLayerMap = dynamic(() => import("@/components/nasa-layer-map").then((m) => m.NasaLayerMap), {
  ssr: false,
  loading: () => <div className="h-[480px] rounded-xl border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />,
});

type Datasets = Record<string, DatasetState>;
type Tone = "good" | "warn" | "bad" | "neutral";

const TONE: Record<Tone, { text: string; bg: string; dot: string; border: string }> = {
  good: { text: "text-emerald-700", bg: "bg-emerald-50", dot: "bg-emerald-500", border: "border-emerald-200" },
  warn: { text: "text-amber-700", bg: "bg-amber-50", dot: "bg-amber-500", border: "border-amber-200" },
  bad: { text: "text-rose-700", bg: "bg-rose-50", dot: "bg-rose-500", border: "border-rose-200" },
  neutral: { text: "text-[#6b675f]", bg: "bg-[#f5f4ef]", dot: "bg-[#a8a29e]", border: "border-[#e7e5e0]" },
};

// ---------------------------------------------------------------- interpretations (plain language)
function vigour(ndvi: number | null): [string, Tone] {
  if (ndvi === null) return ["—", "neutral"];
  if (ndvi >= 0.6) return ["Lush, healthy crop", "good"];
  if (ndvi >= 0.35) return ["Moderate cover", "warn"];
  return ["Sparse or bare soil", "neutral"];
}
function thirst(esi: number | null): [string, Tone] {
  if (esi === null) return ["—", "neutral"];
  if (esi >= 0.7) return ["Not thirsty", "good"];
  if (esi >= 0.4) return ["Somewhat thirsty", "warn"];
  return ["Very thirsty", "bad"];
}
function wetness(w: number | null): [string, Tone] {
  if (w === null) return ["—", "neutral"];
  if (w > 0.85) return ["Waterlogged", "warn"];
  if (w >= 0.5) return ["Moist", "good"];
  if (w >= 0.3) return ["Drying", "warn"];
  return ["Dry", "bad"];
}
function rainVsNormal(ratio: number | null): [string, Tone] {
  if (ratio === null) return ["—", "neutral"];
  if (ratio < 0.5) return ["Much drier than normal", "bad"];
  if (ratio < 0.8) return ["Drier than normal", "warn"];
  if (ratio > 1.5) return ["Much wetter than normal", "warn"];
  return ["About normal", "good"];
}
function riskTone(r: string | null): Tone {
  if (!r) return "neutral";
  if (r.startsWith("low") || r.includes("wetter") || r === "near normal") return "good";
  if (r.startsWith("moderate") || r.includes("drier")) return "warn";
  return "bad";
}
const cap = (s: string | null) => (s ? s[0].toUpperCase() + s.slice(1) : "—");

// ---------------------------------------------------------------- building blocks
function Chip({ text, tone }: { text: string; tone: Tone }) {
  const t = TONE[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${t.text} ${t.bg} ${t.border}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
      {text}
    </span>
  );
}

function GlanceTile({
  icon: Icon,
  question,
  ds,
  verdict,
  tone,
  value,
  href,
}: {
  icon: React.ElementType;
  question: string;
  ds?: DatasetState;
  verdict: string;
  tone: Tone;
  value: string;
  href: string;
}) {
  const loading = !ds || ds.state === "loading";
  const t = TONE[loading ? "neutral" : tone];
  return (
    <a href={href} className={`rounded-xl border ${t.border} ${t.bg} p-3 space-y-1 hover:shadow-sm transition block`}>
      <div className="flex items-center gap-1.5 text-[11px] text-[#6b675f]">
        <Icon className="h-3.5 w-3.5" />
        {question}
      </div>
      {loading ? (
        <p className="flex items-center gap-1.5 text-xs text-[#6b675f]">
          <Loader2 className="h-3 w-3 animate-spin" /> checking…
        </p>
      ) : (
        <>
          <p className={`text-sm font-semibold leading-tight ${t.text}`}>{verdict}</p>
          <p className="text-[11px] font-mono text-[#6b675f]">{value}</p>
        </>
      )}
    </a>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: Tone }) {
  return (
    <div className="min-w-0" title={hint}>
      <p className="text-[11px] text-[#6b675f] truncate">{label}</p>
      <p className={`text-lg font-semibold tabular-nums leading-tight ${tone ? TONE[tone].text : "text-[#1f1915]"}`}>{value}</p>
    </div>
  );
}

function Row({ k, v, hint }: { k: string; v: React.ReactNode; hint?: string }) {
  return (
    <div className="flex justify-between gap-3 text-xs py-0.5" title={hint}>
      <span className="text-[#6b675f]">{k}</span>
      <span className="font-mono tabular-nums text-right">{v}</span>
    </div>
  );
}

function Card({
  title,
  subtitle,
  ds,
  verdict,
  children,
  details,
  className = "",
}: {
  title: string;
  subtitle?: string;
  ds?: DatasetState;
  verdict?: React.ReactNode;
  children?: React.ReactNode;
  details?: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const d = ds?.data;
  const loading = !ds || ds.state === "loading";
  const problem = ds?.state === "error" ? ds.error : d && d.status !== "ok" ? d.note || d.error || d.status : null;
  return (
    <div className={`rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] p-4 flex flex-col gap-3 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[#1f1915]">{title}</h3>
          {subtitle && <p className="text-[11px] text-[#6b675f]">{subtitle}</p>}
        </div>
        {!loading && !problem && verdict}
      </div>
      {loading ? (
        <div className="space-y-2">
          <div className="h-5 w-2/3 rounded bg-[#f0eee8] animate-pulse" />
          <div className="h-5 w-1/2 rounded bg-[#f0eee8] animate-pulse" />
        </div>
      ) : problem ? (
        <p className="text-xs text-[#6b675f]">
          <span className="font-medium text-amber-700">No data for this field. </span>
          {String(problem).slice(0, 160)}
        </p>
      ) : (
        <>
          {children}
          {details && (
            <div className="border-t border-[#e7e5e0] pt-2">
              <button type="button" onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 text-[11px] text-[#20808d] font-medium">
                {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {open ? "Hide details" : "More details"}
              </button>
              {open && <div className="pt-2">{details}</div>}
            </div>
          )}
        </>
      )}
      {d?.source && !loading && (
        <p className="mt-auto text-[10px] text-[#a8a29e]">
          {d.source}
          {d.scale ? ` · ${d.scale === "field" ? "measured on your field" : d.scale === "area" ? "surrounding area" : d.scale}` : ""}
          {d.date && d.date !== "static" && d.date !== "projection" && d.date !== "latest" ? ` · ${String(d.date).slice(0, 10)}` : ""}
        </p>
      )}
    </div>
  );
}

function Section({ id, icon: Icon, title, lead, children }: { id: string; icon: React.ElementType; title: string; lead: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-3 scroll-mt-28">
      <div className="flex items-baseline gap-2">
        <Icon className="h-4 w-4 text-[#20808d] self-center" />
        <h2 className="font-serif text-xl font-semibold">{title}</h2>
        <p className="text-xs text-[#6b675f] hidden md:block">{lead}</p>
      </div>
      {children}
    </section>
  );
}

function CompareBar({ label, now, future, unit, max }: { label: string; now: number | null; future: number | null; unit: string; max: number }) {
  const w = (v: number | null) => `${Math.max(2, Math.min(100, ((v ?? 0) / max) * 100))}%`;
  const delta = now !== null && future !== null ? future - now : null;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-[#1f1915]">{label}</span>
        <span className="font-mono text-[#6b675f]">
          {fmt(now, 0)} → <strong className="text-[#1f1915]">{fmt(future, 0)}</strong> {unit}
          {delta !== null && (
            <span className={delta > 0 ? "text-rose-700" : "text-emerald-700"}>
              {" "}
              ({delta > 0 ? "+" : ""}
              {delta.toFixed(0)})
            </span>
          )}
        </span>
      </div>
      <div className="space-y-0.5">
        <div className="h-1.5 rounded-full bg-[#a8a29e]" style={{ width: w(now) }} title="2000s" />
        <div className="h-1.5 rounded-full bg-[#d97706]" style={{ width: w(future) }} title="2050s" />
      </div>
    </div>
  );
}

const CROP_COLORS: Array<[RegExp, string]> = [
  [/rice/i, "bg-sky-100 text-sky-800 border-sky-200"],
  [/winter cereal/i, "bg-amber-100 text-amber-800 border-amber-200"],
  [/summer crop/i, "bg-lime-100 text-lime-800 border-lime-200"],
  [/double/i, "bg-violet-100 text-violet-800 border-violet-200"],
  [/grassland|meadow|perennial/i, "bg-emerald-100 text-emerald-800 border-emerald-200"],
  [/vineyard|orchard/i, "bg-rose-100 text-rose-800 border-rose-200"],
  [/bare|fallow/i, "bg-stone-100 text-stone-700 border-stone-200"],
];
const cropColor = (g: string) => CROP_COLORS.find(([re]) => re.test(g))?.[1] || "bg-[#f5f4ef] text-[#6b675f] border-[#e7e5e0]";
const shortCrop = (g: string) => g.split(" (")[0].replace(/ \/ .*/, "");

function Sparkline({ values }: { values: Array<number | null> }) {
  const w = 140, h = 28;
  const pts = values
    .map((v, i) => (v === null ? null : [(i / Math.max(1, values.length - 1)) * w, h - ((v + 0.1) / 1.1) * h]))
    .filter(Boolean) as number[][];
  if (pts.length < 2) return null;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-7 w-full">
      <path d={pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")} fill="none" stroke="#20808d" strokeWidth={1.6} />
    </svg>
  );
}

// ---------------------------------------------------------------- the tab
const NAV = [
  ["map", "Map"],
  ["weather", "Weather"],
  ["water", "Water"],
  ["crop", "Crop"],
  ["soil", "Soil & terrain"],
  ["future", "Future"],
  ["prices", "Prices"],
] as const;

export function NasaDataTab({
  datasets,
  plotId,
  token,
  geometry,
  centroid,
  loaded,
  total,
}: {
  datasets: Datasets;
  plotId: string;
  token: string;
  geometry?: Record<string, unknown>;
  centroid?: { lat: number; lon: number };
  loaded: number;
  total: number;
}) {
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

  const ndvi = num(ch, "ndvi.mean");
  const esi = num(etf, "esi.mean") ?? num(eta, "et_pet_ratio");
  const wet = num(sm, "rootzone_wetness");
  const rain30 = num(w, "last_30_days.precip_mm") ?? num(rain, "total_30d_mm");
  const normalDay = num(w, "last_30_days.normal_precip_mm_per_day_this_month");
  const rainRatio = rain30 !== null && normalDay ? rain30 / (normalDay * 30) : null;
  const eroRisk = str(ero, "risk_current_cover");
  const drought = str(proj, "headline");

  const [vText, vTone] = vigour(ndvi);
  const [tText, tTone] = thirst(esi);
  const [wText, wTone] = wetness(wet);
  const [rText, rTone] = rainVsNormal(rainRatio);

  const topsoil = (soil?.["0-5cm"] || {}) as Record<string, unknown>;
  const seasons = (pick(hist, "seasons") as Array<Record<string, unknown>>) || [];
  const curves = (datasets.crop_history?.data?.history as Array<Record<string, unknown>>) || [];
  const ext = (pick(w, "extremes_last_365_days") || {}) as Record<string, unknown>;
  const base = (pick(proj, "baseline_2000s") || {}) as Record<string, unknown>;
  const p245 = (pick(proj, "projections.ssp245_mid_2050s") || {}) as Record<string, unknown>;
  const p585 = (pick(proj, "projections.ssp585_mid_2050s") || {}) as Record<string, unknown>;
  const elecSeries = pick(local, "energy.electricity.MWH500-1999.excl_taxes") as Array<Record<string, unknown>> | undefined;
  const elec = elecSeries?.[elecSeries.length - 1];

  return (
    <div className="space-y-8">
      {/* At a glance */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl font-semibold">Your field at a glance</h2>
          <span className="text-[11px] font-mono text-[#6b675f]">
            {loaded < total ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> loading NASA data {loaded}/{total}
              </span>
            ) : (
              `${total} NASA & open datasets`
            )}
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <GlanceTile icon={Leaf} question="Are the plants healthy?" ds={datasets.crop_health} verdict={vText} tone={vTone} value={`NDVI ${fmt(ndvi, 2)}`} href="#crop" />
          <GlanceTile icon={Droplets} question="Are they thirsty?" ds={datasets.evapotranspiration_field} verdict={tText} tone={tTone} value={`stress index ${fmt(esi, 2)}`} href="#water" />
          <GlanceTile icon={Waves} question="Is the soil wet?" ds={datasets.soil_moisture} verdict={wText} tone={wTone} value={`${fmt(wet !== null ? wet * 100 : null, 0)}% of saturation`} href="#water" />
          <GlanceTile icon={CloudRain} question="Enough rain lately?" ds={datasets.weather} verdict={rText} tone={rTone} value={`${fmt(rain30, 0)} mm in 30 days`} href="#weather" />
          <GlanceTile icon={Mountain} question="Is soil washing away?" ds={datasets.erosion} verdict={eroRisk ? `${cap(eroRisk)} erosion` : "—"} tone={riskTone(eroRisk)} value={`${fmt(num(ero, "soil_loss_current_cover_t_ha_yr"), 1)} t/ha/yr`} href="#soil" />
          <GlanceTile icon={TrendingUp} question="Drought by 2050?" ds={datasets.climate_projection} verdict={drought ? `${cap(drought)} risk` : "—"} tone={riskTone(drought)} value={`water balance ${fmt(num(p245, "water_balance_change_mm"), 0)} mm`} href="#future" />
        </div>
      </div>

      {/* Section nav */}
      <nav className="sticky top-[52px] z-10 -mx-1 px-1 py-2 bg-[#faf9f5]/95 backdrop-blur flex gap-1.5 overflow-x-auto">
        {NAV.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="shrink-0 rounded-full border border-[#e7e5e0] bg-white px-3 py-1 text-xs hover:border-[#20808d] hover:text-[#20808d]">
            {label}
          </a>
        ))}
      </nav>

      <Section id="map" icon={Sun} title="Satellite views" lead="Pick a view to see it over your field.">
        <NasaLayerMap key={plotId} plotId={plotId} token={token} geometry={geometry} centroid={centroid} />
      </Section>

      <Section id="weather" icon={ThermometerSun} title="Weather" lead="NASA POWER, surrounding ~50 km.">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card title="Right now" subtitle={`Latest full day · ${str(w, "latest.date") || ""}`} ds={datasets.weather}
            details={<>
              <Row k="Min / max" v={`${fmt(num(w, "latest.T2M_MIN"))} / ${fmt(num(w, "latest.T2M_MAX"), 1, " °C")}`} />
              <Row k="Dew point" v={fmt(num(w, "latest.T2MDEW"), 1, " °C")} />
              <Row k="Wind (max)" v={`${fmt(num(w, "latest.WS2M"))} (${fmt(num(w, "latest.WS2M_MAX"))}) m/s`} />
              <Row k="Solar radiation" v={fmt(num(w, "latest.ALLSKY_SFC_SW_DWN"), 1, " MJ/m²")} />
              <Row k="Day length range" v={`${fmt(num(w, "today.daylight_h_shortest_day"))}–${fmt(num(w, "today.daylight_h_longest_day"), 1, " h")}`} />
            </>}>
            <div className="grid grid-cols-3 gap-3">
              <Metric label="Temperature" value={fmt(num(w, "latest.T2M"), 1, "°")} />
              <Metric label="Humidity" value={fmt(num(w, "latest.RH2M"), 0, "%")} />
              <Metric label="Daylight" value={fmt(num(w, "today.daylight_h"), 1, " h")} />
            </div>
          </Card>
          <Card title="Last 30 days" subtitle="Compared with the 1991–2020 average" ds={datasets.weather} verdict={<Chip text={rText} tone={rTone} />}
            details={<>
              <Row k="Rain last 7 days" v={fmt(num(w, "last_7_days.precip_mm"), 0, " mm")} />
              <Row k="Normal mean temperature" v={fmt(num(w, "last_30_days.normal_t_mean_c_this_month"), 1, " °C")} />
              <Row k="Humidity" v={fmt(num(w, "last_30_days.rh_mean_pct"), 0, " %")} />
              <Row k="Sunshine (1 = cloudless)" v={fmt(num(w, "last_30_days.sunshine_fraction"), 2)} />
              <Row k="Evapotranspiration" v={fmt(num(w, "last_30_days.evapotranspiration_mm"), 0, " mm")} />
              <Row k="Growing degree days since 1 Jan" v={fmt(num(w, "gdd_since_jan1.value"), 0, " °C·d")} />
            </>}>
            <div className="grid grid-cols-3 gap-3">
              <Metric label="Rain" value={fmt(rain30, 0, " mm")} />
              <Metric label="Normal" value={fmt(normalDay !== null ? normalDay * 30 : null, 0, " mm")} />
              <Metric label="Mean temp" value={fmt(num(w, "last_30_days.t_mean_c"), 1, "°")} />
            </div>
          </Card>
          <Card title="Extremes this year" subtitle="Last 365 days" ds={datasets.weather}
            details={<>
              <Row k="Windiest day" v={`${fmt(num(ext, "windiest_day.wind_max_ms"), 1, " m/s")} · ${str(ext, "windiest_day.date") || ""}`} />
              <Row k="Heavy-rain days (≥ 30 mm)" v={num(ext, "heavy_rain_days_over_30mm") ?? "—"} />
              <Row k="Gale days" v={num(ext, "gale_days_wind_over_10_8ms") ?? "—"} />
              <Row k="Total rain" v={fmt(num(ext, "total_precip_mm"), 0, " mm")} />
            </>}>
            <div className="grid grid-cols-2 gap-3">
              <Metric label={`Hottest · ${str(ext, "hottest_day.date")?.slice(5) || ""}`} value={fmt(num(ext, "hottest_day.t_max_c"), 1, "°")} tone="bad" />
              <Metric label={`Coldest · ${str(ext, "coldest_night.date")?.slice(5) || ""}`} value={fmt(num(ext, "coldest_night.t_min_c"), 1, "°")} tone="neutral" />
              <Metric label="Frost / heat days" value={`${num(ext, "frost_days") ?? "—"} / ${num(ext, "heat_days_over_35c") ?? "—"}`} />
              <Metric label="Longest dry spell" value={fmt(num(ext, "longest_dry_spell_days"), 0, " d")} />
            </div>
          </Card>
        </div>
      </Section>

      <Section id="water" icon={Droplets} title="Water" lead="Rain, soil moisture, crop thirst and groundwater.">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card title="Rainfall" subtitle="Satellite, ~10 km" ds={datasets.rainfall}
            details={<Row k="Last day" v={`${fmt(num(rain, "latest_day.precip_mm"), 1, " mm")} · ${str(rain, "latest_day.date") || ""}`} />}>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Last 7 days" value={fmt(num(rain, "total_7d_mm"), 0, " mm")} />
              <Metric label="Dry days in a row" value={num(rain, "consecutive_dry_days") ?? "—"} />
            </div>
          </Card>
          <Card title="Soil moisture" subtitle="Root zone, 0–100 cm" ds={datasets.soil_moisture} verdict={<Chip text={wText} tone={wTone} />}
            details={<>
              <Row k="Surface 0–5 cm" v={fmt(num(sm, "surface_m3m3"), 3, " m³/m³")} />
              <Row k="Root zone" v={fmt(num(sm, "rootzone_m3m3"), 3, " m³/m³")} />
            </>}>
            <Metric label="Wetness" value={fmt(wet !== null ? wet * 100 : null, 0, "%")} tone={wTone} hint="% of saturation" />
          </Card>
          <Card title="Crop thirst" subtitle="Measured on your field" ds={datasets.evapotranspiration_field} verdict={<Chip text={tText} tone={tTone} />}
            details={<>
              <Row k="Evaporative stress index" v={fmt(num(etf, "esi.mean"), 2)} hint="actual / potential ET; 1 = no stress" />
              <Row k="Surface temperature" v={fmt(num(etf, "lst.mean"), 1, " °C")} />
              <Row k="Area ET / potential (MODIS)" v={`${fmt(num(eta, "et_mm_8day"), 1)} / ${fmt(num(eta, "pet_mm_8day"), 1, " mm per 8 d")}`} />
            </>}>
            <Metric label="Water used by the crop" value={fmt(num(etf, "et_daily.mean"), 1, " mm/day")} />
          </Card>
          <Card title="Groundwater" subtitle="Regional, ~300 km" ds={datasets.groundwater} verdict={<Chip text={cap(str(gw, "interpretation"))} tone={riskTone(str(gw, "interpretation"))} />}
            details={<>
              <Row k="Anomaly" v={`${fmt(num(gw, "latest.anomaly_cm"), 1, " cm")} · ${str(gw, "latest.month") || ""}`} />
              <Row k="Percentile vs same month" v={fmt(num(gw, "percentile_vs_same_month_all_years"), 0)} />
            </>}>
            <Metric label="Change in 12 months" value={fmt(num(gw, "trend_last_12_months_cm"), 1, " cm")} />
          </Card>
        </div>
      </Section>

      <Section id="crop" icon={Sprout} title="Crop" lead="Health today and what grew here before.">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card title="Crop health today" subtitle={`${str(ch, "sensor") || ""} · ${str(ch, "date") || ""}`} ds={datasets.crop_health} verdict={<Chip text={vText} tone={vTone} />}
            details={<>
              <Row k="Canopy water (NDMI)" v={fmt(num(ch, "ndmi.mean"), 2)} />
              <Row k="Nitrogen (NDRE)" v={fmt(num(ch, "ndre.mean"), 2)} />
              <Row k="Cloud-free share" v={fmt(num(ch, "clear_fraction") !== null ? num(ch, "clear_fraction")! * 100 : null, 0, " %")} />
            </>}>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Vigour (NDVI)" value={fmt(ndvi, 2)} tone={vTone} />
              <Metric label="Patchy area" value={fmt(num(ch, "low_vigor_fraction") !== null ? num(ch, "low_vigor_fraction")! * 100 : null, 0, "%")} hint="share of the field well below its median vigour" />
            </div>
          </Card>
          <Card className="lg:col-span-2" title="What grew here" subtitle="Last 5 years, read from each season's vegetation curve" ds={datasets.crop_history}
            verdict={str(hist, "most_common_crop_group") ? <Chip text={pick(hist, "rotates") ? "Rotating" : "Same crop every year"} tone={pick(hist, "rotates") ? "good" : "warn"} /> : undefined}>
            <div className="grid grid-cols-5 gap-2">
              {seasons.map((s) => {
                const curve = curves.find((c) => c.year === s.year);
                const vals = ((curve?.ndvi_by_period as Array<Record<string, unknown>>) || []).map((p) => num(p, "ndvi"));
                const g = String(s.crop_group);
                return (
                  <div key={String(s.year)} className="space-y-1">
                    <p className="text-xs font-semibold">
                      {String(s.year)}
                      {s.complete ? "" : <span className="font-normal text-[#6b675f]"> so far</span>}
                    </p>
                    <span className={`inline-block rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-tight ${cropColor(g)}`} title={g}>
                      {shortCrop(g)}
                    </span>
                    <Sparkline values={vals} />
                    <p className="text-[10px] text-[#6b675f]">green {String(s.green_season || "—")}</p>
                  </div>
                );
              })}
            </div>
            <p className="text-[11px] text-[#6b675f]">Crop type, not exact species: confirm with the farmer.</p>
          </Card>
        </div>
      </Section>

      <Section id="soil" icon={Mountain} title="Soil & terrain" lead="Texture, nutrients, slope and erosion.">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card title="Topsoil" subtitle="0–5 cm, ~250 m" ds={datasets.soil} verdict={str(topsoil, "texture_class") ? <Chip text={cap(str(topsoil, "texture_class"))} tone="neutral" /> : undefined}
            details={<>
              <Row k="Clay / silt / sand" v={`${fmt(num(topsoil, "clay"), 0)} / ${fmt(num(topsoil, "silt"), 0)} / ${fmt(num(topsoil, "sand"), 0, " %")}`} />
              <Row k="Nutrient holding (CEC)" v={fmt(num(topsoil, "cec"), 1, " cmol/kg")} />
              <Row k="Bulk density" v={fmt(num(topsoil, "bdod"), 2, " g/cm³")} />
            </>}>
            <div className="grid grid-cols-3 gap-3">
              <Metric label="pH" value={fmt(num(topsoil, "phh2o"), 1)} />
              <Metric label="Organic C" value={fmt(num(topsoil, "soc"), 0, " g/kg")} />
              <Metric label="Nitrogen" value={fmt(num(topsoil, "nitrogen"), 1, " g/kg")} />
            </div>
          </Card>
          <Card title="Terrain" subtitle="NASADEM, 30 m" ds={datasets.terrain}
            verdict={terr ? <Chip text={pick(terr, "low_spot") ? "Low spot: may waterlog" : "Drains normally"} tone={pick(terr, "low_spot") ? "warn" : "good"} /> : undefined}
            details={<>
              <Row k="Elevation range" v={`${fmt(num(terr, "elevation_m.min"), 0)}–${fmt(num(terr, "elevation_m.max"), 0, " m")}`} />
              <Row k="Pixel slope mean / max" v={`${fmt(num(terr, "slope_deg.mean"))} / ${fmt(num(terr, "slope_deg.max"), 1, "°")}`} />
              <Row k="Faces (0 = north)" v={fmt(num(terr, "aspect_deg"), 0, "°")} />
              <Row k="Height vs surroundings" v={fmt(num(terr, "relative_elevation_m"), 1, " m")} />
            </>}>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Altitude" value={fmt(num(terr, "elevation_m.mean"), 0, " m")} />
              <Metric label="Field slope" value={fmt(num(terr, "field_gradient_deg") ?? num(terr, "slope_deg.mean"), 1, "°")} />
            </div>
          </Card>
          <Card title="Erosion risk" subtitle="RUSLE soil-loss estimate" ds={datasets.erosion} verdict={<Chip text={cap(eroRisk)} tone={riskTone(eroRisk)} />}
            details={<>
              <Row k="Rain erosivity R" v={fmt(num(ero, "r_factor"), 0)} />
              <Row k="Soil erodibility K" v={fmt(num(ero, "k_factor"), 3)} />
              <Row k="Slope factor LS" v={fmt(num(ero, "ls_factor"), 2)} />
              <Row k="Cover factor C (today)" v={fmt(num(ero, "c_factor_current"), 2)} />
            </>}>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="With today's cover" value={fmt(num(ero, "soil_loss_current_cover_t_ha_yr"), 1, " t/ha")} tone={riskTone(eroRisk)} />
              <Metric label="If left bare" value={fmt(num(ero, "soil_loss_bare_t_ha_yr"), 1, " t/ha")} tone={riskTone(str(ero, "risk_bare"))} />
            </div>
          </Card>
        </div>
      </Section>

      <Section id="future" icon={TrendingUp} title="Future climate" lead="2000s vs 2050s, NASA NEX-GDDP-CMIP6, ~25 km.">
        <Card title="How the 2050s could look" subtitle="Middle-of-the-road scenario (SSP2-4.5); grey = 2000s, orange = 2050s" ds={datasets.climate_projection}
          verdict={drought ? <Chip text={`Drought risk: ${drought}`} tone={riskTone(drought)} /> : undefined}
          details={<>
            <p className="text-[11px] text-[#6b675f] pb-1">High-emissions scenario (SSP5-8.5), 2050s:</p>
            <Row k="Rain" v={fmt(num(p585, "precip_mm"), 0, " mm/yr")} />
            <Row k="Water balance (rain − evaporation)" v={fmt(num(p585, "water_balance_mm"), 0, " mm/yr")} />
            <Row k="Days above 35 °C" v={fmt(num(p585, "heat_days_over_35c"), 0)} />
            <Row k="Drought risk" v={cap(str(p585, "drought_risk"))} />
          </>}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
            <CompareBar label="Rain per year" now={num(base, "precip_mm")} future={num(p245, "precip_mm")} unit="mm" max={Math.max(1500, num(p245, "precip_mm") ?? 0)} />
            <CompareBar label="Summer max temperature" now={num(base, "t_max_summer_c")} future={num(p245, "t_max_summer_c")} unit="°C" max={40} />
            <CompareBar label="Days above 35 °C" now={num(base, "heat_days_over_35c")} future={num(p245, "heat_days_over_35c")} unit="days" max={40} />
            <CompareBar label="Longest dry spell" now={num(base, "longest_dry_spell_days")} future={num(p245, "longest_dry_spell_days")} unit="days" max={45} />
          </div>
        </Card>
      </Section>

      <Section id="prices" icon={TrendingUp} title="Prices" lead="What you could earn and what inputs cost.">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card title="Farm-gate crop prices" subtitle={`${str(local, "country.name") || "Country"} · Eurostat`} ds={datasets.local_prices}>
            {((pick(local, "crop_selling_prices") as Array<Record<string, unknown>>) || [])
              .filter((c) => /wheat|maize|rice|barley|soya|sunflower|rape/i.test(String(c.crop)))
              .slice(0, 7)
              .map((c) => (
                <Row key={String(c.crop)} k={String(c.crop)} v={`€${fmt(num(c, "latest.eur_per_t"), 0)}/t · ${str(c, "latest.year") || ""}`} />
              ))}
          </Card>
          <Card title="Your input costs" subtitle="National averages, before taxes" ds={datasets.local_prices}>
            <div className="grid grid-cols-3 gap-3">
              <Metric label="Electricity" value={elec ? `€${fmt(num(elec, "price"), 3)}` : "—"} hint="per kWh, large farm" />
              <Metric label="Diesel" value={`€${fmt(num(local, "fuel.diesel.latest_without_taxes.eur_per_litre"), 2)}`} hint="per litre, without taxes (farm diesel is tax-reduced)" />
              <Metric label="Gas" value={(() => {
                const s = pick(local, "energy.natural_gas.GJ1000-9999.excl_taxes") as Array<Record<string, unknown>> | undefined;
                return s?.length ? `€${fmt(num(s[s.length - 1], "price"), 3)}` : "—";
              })()} hint="per kWh, greenhouse heating scale" />
            </div>
            <p className="text-[11px] text-[#6b675f]">Water and seed prices: enter your own in Soil &amp; Utility Inputs.</p>
          </Card>
          <Card title="World market" subtitle="World Bank, monthly · change vs a year ago" ds={datasets.market_prices}
            details={<>
              {((pick(fao, "crops") as Array<Record<string, unknown>>) || []).slice(0, 8).map((c) => (
                <Row key={String(c.crop)} k={`${String(c.crop)} (national yield)`} v={fmt(num(c, "latest.yield_kg_per_ha") !== null ? num(c, "latest.yield_kg_per_ha")! / 1000 : null, 1, " t/ha")} />
              ))}
            </>}>
            {Object.entries(market || {})
              .filter(([k]) => ["crude_oil_brent", "urea", "dap", "maize", "wheat_us_hrw", "rice_thai_5pct"].includes(k))
              .map(([k, v]) => {
                const ch12 = num(v, "change_12m_pct");
                return (
                  <Row key={k} k={str(v, "name") || k}
                    v={<>{fmt(num(v, "latest.price"), 0)} <span className="text-[#6b675f]">{str(v, "unit")}</span>{" "}
                      <span className={ch12 !== null && ch12 >= 0 ? "text-rose-700" : "text-emerald-700"}>{ch12 !== null ? `${ch12 >= 0 ? "▲" : "▼"}${Math.abs(ch12).toFixed(0)}%` : ""}</span></>} />
                );
              })}
          </Card>
        </div>
      </Section>
    </div>
  );
}
