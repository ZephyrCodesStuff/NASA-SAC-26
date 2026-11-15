"use client";

import React, { useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  ChevronDown,
  ChevronUp,
  Droplets,
  FlaskConical,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sprout,
  Table2,
  ClipboardCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface AnnualGroundImpact {
  year_index: number;
  crop_id?: string;
  crop_name: string;
  botanical_family?: string;
  season_label?: string;
  projected_yield_tons_ha?: number;
  total_yield_tons?: number;
  gross_revenue_usd?: number;
  total_cost_usd?: number;
  net_profit_usd?: number;
  roi_pct?: number;
  labor_hours_total?: number;
  machinery_passes_count?: number;
  fuel_consumed_liters?: number;
  nitrogen_balance_kg_ha?: number;
  biological_n_fixed_kg_ha?: number;
  synthetic_n_applied_kg_ha?: number;
  legume_n_credit_used_kg_ha?: number;
  soc_pct_start?: number;
  soc_pct_end?: number;
  soc_change_pct?: number;
  compaction_psi_start?: number;
  compaction_psi_end?: number;
  compaction_change_psi?: number;
  water_demand_etc_mm?: number;
  effective_precipitation_mm?: number;
  irrigation_water_applied_mm?: number;
  irrigation_volume_m3?: number;
  water_stress_coefficient_ks?: number;
  soil_erosion_tons_ha?: number;
  rhizosphere_vitality_score?: number;
  pathogen_disease_risk_score?: number;
  extreme_event_vulnerability_score?: number;
  ground_narrative?: string;
}

export interface ThreeYearCumulativeMetrics {
  total_gross_revenue_usd?: number;
  total_cost_usd?: number;
  total_net_profit_usd?: number;
  cumulative_roi_pct?: number;
  total_labor_hours?: number;
  total_machinery_passes?: number;
  total_diesel_liters?: number;
  net_soc_change_pct?: number;
  initial_soc_pct?: number;
  final_soc_pct?: number;
  total_carbon_input_tons_ha?: number;
  total_biological_n_fixed_kg_ha?: number;
  synthetic_n_saved_usd?: number;
  initial_compaction_psi?: number;
  final_compaction_psi?: number;
  net_compaction_change_psi?: number;
  total_irrigation_volume_m3?: number;
  average_annual_erosion_tons_ha?: number;
  cumulative_soil_health_score?: number;
  composite_loss_risk_score?: number;
  botanical_families_count?: number;
}

export interface ThreeYearCultivationPlan {
  strategy_id: string;
  strategy_title: string;
  core_objective?: string;
  rotation_sequence: string[];
  year_1: AnnualGroundImpact;
  year_2: AnnualGroundImpact;
  year_3: AnnualGroundImpact;
  cumulative_metrics: ThreeYearCumulativeMetrics;
  strategic_summary?: string;
  risk_mitigation_actions?: string[];
}

export interface StrategyPlainLanguageBreakdown {
  strategy_id: string;
  strategy_name?: string;
  rotation_sequence?: string[];
  benefits_plain_words?: string[];
  drawbacks_plain_words?: string[];
  risks_taken?: string[];
  expected_rewards?: string[];
  three_year_action_overview?: string;
}

export interface GeminiAdvisoryReport {
  model_used?: string;
  farmer_plain_language_summary?: string;
  strategies_breakdown?: StrategyPlainLanguageBreakdown[];
  three_year_operational_overview?: string;
  risk_vs_reward_comparison?: string;
  farmer_decision_guide?: string;
  ground_truth_field_checklist?: string[];
  executive_summary?: string;
  parcel_climate_context?: string;
  strategy_tradeoff_matrix?: string;
  year_by_year_soil_transformation?: string;
  extreme_event_resilience_playbook?: string;
}

export interface ThreeYearPlanResponse {
  cadastral_parcel_id?: string;
  field_area_ha?: number;
  resolved_soil_type?: string;
  simulation_timestamp?: string;
  climate_baseline?: Record<string, unknown>;
  data_layering_provenance?: Record<string, unknown>;
  strategies: Record<string, ThreeYearCultivationPlan> | ThreeYearCultivationPlan[];
  gemini_advisory?: GeminiAdvisoryReport | null;
}

function fmtNum(val: number | undefined | null, digits = 1, suffix = ""): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "—";
  return `${val.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}${suffix}`;
}

function fmtMoney(val: number | undefined | null): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "—";
  const sign = val < 0 ? "-" : "";
  return `${sign}$${Math.abs(val).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtCompactMoney(val: number | undefined | null): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "—";
  if (Math.abs(val) >= 1000) {
    return `${val < 0 ? "-" : ""}$${Math.round(Math.abs(val) / 1000)}k`;
  }
  return fmtMoney(val);
}

function fmtSigned(val: number | undefined | null, digits = 1, suffix = ""): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "—";
  const sign = val > 0 ? "+" : "";
  return `${sign}${val.toFixed(digits)}${suffix}`;
}

/** Highlight key quantitative tokens ($643,983, 568 kg/ha, +149 psi, 29.1 ha, 218%) inside plain prose. */
function renderHighlightedProse(text: string): React.ReactNode {
  const regex = /(\$[\d,]+(?:\.\d+)?|[+-]?\d+(?:,\d{3})*(?:\.\d+)?\s?(?:kg\/ha|m³|psi|PSI|mm\/year|t\/ha|ha|%))/g;
  const parts = text.split(regex);
  return parts.map((part, i) => {
    if (!part) return null;
    if (regex.test(part)) {
      regex.lastIndex = 0;
      return (
        <span
          key={i}
          className="inline-block bg-emerald-50 text-emerald-800 px-1.5 py-0.5 rounded font-medium font-mono tabular-nums text-[0.92em]"
        >
          {part}
        </span>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

function goalPillMeta(s: ThreeYearCultivationPlan): { label: string; metric: string } {
  const id = (s.strategy_id || "").toLowerCase();
  const title = (s.strategy_title || "").toLowerCase();
  const cm = s.cumulative_metrics || {};

  if (id.includes("income") || title.includes("income")) {
    return { label: "Max Income", metric: fmtCompactMoney(cm.total_net_profit_usd) };
  }
  if (id.includes("soil") || title.includes("soil")) {
    return { label: "Soil Health", metric: fmtNum(cm.cumulative_soil_health_score, 0, "/100") };
  }
  if (id.includes("effort") || id.includes("labor") || title.includes("effort") || title.includes("labour")) {
    return { label: "Least Effort", metric: fmtNum(cm.total_labor_hours, 0, "h") };
  }
  if (id.includes("roi") || title.includes("roi")) {
    return { label: "Highest ROI", metric: fmtNum(cm.cumulative_roi_pct, 0, "%") };
  }
  if (id.includes("risk") || title.includes("risk") || title.includes("loss")) {
    return { label: "Low Risk", metric: fmtNum(cm.composite_loss_risk_score, 0, "/100") };
  }
  return {
    label: s.strategy_title.replace(/\s*Strategy$/i, ""),
    metric: fmtCompactMoney(cm.total_net_profit_usd),
  };
}

/** Parse numbered/inline "Choose 'Plan' if: ..." clauses from farmer_decision_guide. */
function parseDecisionRules(guide?: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (!guide) return out;
  // "Choose 'Most Income' or 'Highest ROI' if you need cash now. Choose 'Least Effort' if ..." (one or more plan
  // names per clause, quoted or not, optionally numbered)
  const re = /(?:^|\s)(?:\d+\.\s*)?Choose\s+(.+?)\s+if\b[:\s]*([\s\S]*?)(?=\s*(?:\d+\.\s*)?Choose\s|$)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(guide)) !== null) {
    const raw = m[2].trim().replace(/\.$/, "");
    if (!raw) continue;
    const quoted = Array.from(m[1].matchAll(/['"\u2018\u2019\u201c\u201d]([^'"\u2018\u2019\u201c\u201d]+)['"\u2018\u2019\u201c\u201d]/g)).map((q) => q[1]);
    const names = quoted.length > 0 ? quoted : m[1].split(/\s*(?:,|\bor\b|\band\b)\s*/i);
    for (const name of names) {
      const key = name.trim().toLowerCase();
      if (key) out[key] = raw.charAt(0).toLowerCase() + raw.slice(1);
    }
  }
  return out;
}

/** "google-genai/gemini-3.1-flash-lite" -> "Gemini 3.1 Flash Lite"; null for the built-in (offline) engine. */
function aiModelLabel(modelUsed?: string): string | null {
  if (!modelUsed || !modelUsed.startsWith("google-genai/")) return null;
  return modelUsed
    .replace("google-genai/", "")
    .split("-")
    .map((w) => (/^\d/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

const BRIEFING_SECTIONS: Array<{ key: keyof GeminiAdvisoryReport; title: string }> = [
  { key: "three_year_operational_overview", title: "Your three years at a glance" },
  { key: "risk_vs_reward_comparison", title: "Risk vs reward" },
  { key: "strategy_tradeoff_matrix", title: "How the plans trade off" },
  { key: "year_by_year_soil_transformation", title: "What happens to your soil" },
  { key: "extreme_event_resilience_playbook", title: "Drought & heavy-rain playbook" },
  { key: "farmer_decision_guide", title: "How to choose" },
];

/** The AI agronomist's plain-language briefing (Gemini, or the built-in engine when Gemini is unavailable). */
function AdvisoryBriefing({ advisory }: { advisory: GeminiAdvisoryReport }) {
  const [open, setOpen] = useState(false);
  const model = aiModelLabel(advisory.model_used);
  const lead = advisory.executive_summary || advisory.farmer_plain_language_summary;
  const second =
    advisory.executive_summary && advisory.farmer_plain_language_summary ? advisory.farmer_plain_language_summary : null;
  const sections = BRIEFING_SECTIONS.filter((s) => typeof advisory[s.key] === "string" && (advisory[s.key] as string).trim());
  if (!lead && !advisory.parcel_climate_context && sections.length === 0) return null;

  return (
    <section className="rounded-xl border border-[#20808d]/25 bg-gradient-to-b from-[#20808d]/[0.06] to-transparent p-4 sm:p-5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#20808d]">
          <Sparkles className="h-3.5 w-3.5" />
          Agronomist briefing
        </p>
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] font-mono ${
            model ? "border-[#20808d]/30 text-[#20808d] bg-white/70" : "border-[#e7e5e0] text-[#6b675f] bg-white/70"
          }`}
          title={advisory.model_used}
        >
          {model ? `AI · ${model}` : "Offline briefing · built-in rules"}
        </span>
      </div>

      {lead && <p className="text-[15px] leading-relaxed text-[#1f1915] max-w-3xl">{renderHighlightedProse(lead)}</p>}
      {advisory.parcel_climate_context && (
        <p className="text-sm leading-relaxed text-[#4a4640] max-w-3xl">
          {renderHighlightedProse(advisory.parcel_climate_context)}
        </p>
      )}

      {(second || sections.length > 0) && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 text-xs font-medium text-[#20808d] hover:underline"
          >
            {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {open ? "Hide the full briefing" : `Read the full briefing (${sections.length + (second ? 1 : 0)} sections)`}
          </button>
          {open && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 pt-1">
              {second && (
                <div className="space-y-1 md:col-span-2">
                  <p className="text-xs font-semibold text-[#1f1915]">In plain words</p>
                  <p className="text-sm leading-relaxed text-[#4a4640]">{renderHighlightedProse(second)}</p>
                </div>
              )}
              {sections.map((s) => (
                <div key={s.key} className="space-y-1">
                  <p className="text-xs font-semibold text-[#1f1915]">{s.title}</p>
                  <p className="text-sm leading-relaxed text-[#4a4640]">
                    {renderHighlightedProse(advisory[s.key] as string)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <p className="text-[11px] text-[#6b675f]">
        {model ? "Written by AI from the simulated numbers below; the numbers themselves are computed, not generated." : "Gemini was unavailable, so this briefing was written by the built-in rules from the same numbers."}{" "}
        Advisory only.
      </p>
    </section>
  );
}

function editorialBulletForStrategy(
  s: ThreeYearCultivationPlan,
  rules: Record<string, string>
): {
  title: string;
  crops: string;
  lead: string;
  metric: string;
  tail: string;
  criteria: string;
} {
  const id = (s.strategy_id || "").toLowerCase();
  const titleLower = (s.strategy_title || "").toLowerCase();
  const cm = s.cumulative_metrics || {};
  const crops = (s.rotation_sequence || []).join(" → ");

  const matchedRule =
    Object.entries(rules).find(
      ([k]) =>
        titleLower.includes(k) ||
        k.includes(titleLower.replace(/\s*strategy$/i, "")) ||
        (id.includes("income") && k.includes("income")) ||
        (id.includes("roi") && k.includes("roi")) ||
        (id.includes("soil") && k.includes("soil")) ||
        ((id.includes("effort") || id.includes("labor")) && (k.includes("effort") || k.includes("labor"))) ||
        ((id.includes("risk") || id.includes("loss")) && (k.includes("risk") || k.includes("loss")))
    )?.[1] || "";

  if (id.includes("income") || titleLower.includes("income")) {
    return {
      title: "Most Income",
      crops,
      lead: "Delivers ",
      metric: fmtMoney(cm.total_net_profit_usd),
      tail: " in 3-year net profit",
      criteria:
        matchedRule ||
        "you have working capital, market contracts in hand, and want maximum total return",
    };
  }
  if (id.includes("roi") || titleLower.includes("roi")) {
    return {
      title: "Highest ROI",
      crops,
      lead: "Generates ",
      metric: fmtNum(cm.cumulative_roi_pct, 0, "% ROI"),
      tail: " per dollar invested",
      criteria: matchedRule || "working capital is tight and input efficiency matters most",
    };
  }
  if (id.includes("soil") || titleLower.includes("soil")) {
    return {
      title: "Best Soil Health",
      crops,
      lead: "Fixes ",
      metric: fmtNum(cm.total_biological_n_fixed_kg_ha, 0, " kg/ha"),
      tail: " of free nitrogen and rebuilds structure",
      criteria: matchedRule || "your ground is tired (>250 PSI) and needs long-term restoration",
    };
  }
  if (id.includes("effort") || id.includes("labor") || titleLower.includes("effort")) {
    return {
      title: "Least Effort",
      crops,
      lead: "Keeps total fieldwork down to ",
      metric: fmtNum(cm.total_labor_hours, 0, " hours"),
      tail: " over 3 years",
      criteria: matchedRule || "you farm part-time, run older machinery, or lack hired labor",
    };
  }
  if (id.includes("risk") || id.includes("loss") || titleLower.includes("risk")) {
    return {
      title: "Least Crop Loss Risk",
      crops,
      lead: "Holds weather & yield risk to ",
      metric: fmtNum(cm.composite_loss_risk_score, 0, "/100"),
      tail: "",
      criteria: matchedRule || "your top priority is yield stability against erratic rain and heat spikes",
    };
  }
  return {
    title: s.strategy_title.replace(/\s*Strategy$/i, ""),
    crops,
    lead: "Projects ",
    metric: fmtMoney(cm.total_net_profit_usd),
    tail: " net profit",
    criteria: matchedRule || "this aligns with your seasonal priorities",
  };
}

export function ProjectionPlanPanel({
  data,
  plotName,
  loading,
  error,
  onRunProjection,
}: {
  data: ThreeYearPlanResponse | null;
  plotName?: string;
  loading?: boolean;
  error?: string | null;
  onRunProjection?: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showTableDrawer, setShowTableDrawer] = useState(false);
  const [showChecklistDrawer, setShowChecklistDrawer] = useState(false);
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({});

  const strategyList = useMemo<ThreeYearCultivationPlan[]>(() => {
    if (!data?.strategies) return [];
    if (Array.isArray(data.strategies)) return data.strategies;
    return Object.values(data.strategies);
  }, [data]);

  const active = useMemo(() => {
    if (strategyList.length === 0) return null;
    if (selectedId) {
      const found = strategyList.find((s) => s.strategy_id === selectedId);
      if (found) return found;
    }
    return strategyList[0];
  }, [strategyList, selectedId]);

  const activeBreakdown = useMemo(() => {
    if (!active || !data?.gemini_advisory?.strategies_breakdown) return null;
    return (
      data.gemini_advisory.strategies_breakdown.find(
        (b) => b.strategy_id === active.strategy_id
      ) ?? null
    );
  }, [active, data]);

  const planRef = useRef<HTMLDivElement>(null);
  useGSAP(
    () => {
      if (!active) return;
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          ".kpi-card-animate",
          { opacity: 0, y: 6 },
          { opacity: 1, y: 0, duration: 0.22, stagger: 0.035, ease: "power2.out", clearProps: "transform,opacity" }
        );
        gsap.fromTo(
          ".year-card-animate",
          { opacity: 0, y: 10 },
          { opacity: 1, y: 0, duration: 0.26, stagger: 0.06, ease: "power2.out", clearProps: "transform,opacity" }
        );
      });
      return () => mm.revert();
    },
    { scope: planRef, dependencies: [active?.strategy_id ?? ""] }
  );

  if (loading) {
    return (
      <div className="space-y-6 font-sans">
        <div className="space-y-2 max-w-3xl">
          <div className="h-4 w-48 rounded bg-[#e7e5e0] animate-pulse" />
          <div className="h-5 w-full rounded bg-[#e7e5e0] animate-pulse" />
          <div className="h-5 w-11/12 rounded bg-[#e7e5e0] animate-pulse" />
        </div>
        <div className="flex gap-2 flex-wrap">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-9 w-36 rounded-full bg-[#e7e5e0] animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-52 rounded-xl border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || !active) {
    return (
      <div className="rounded-xl border border-dashed border-[#e7e5e0] bg-[#fdfbfa] p-6 font-sans">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <Sprout className="h-4 w-4 text-[#20808d]" />
              <h3 className="font-serif text-base font-semibold text-[#1f1915]">
                3-Year Agronomic &amp; Financial Projection
              </h3>
            </div>
            <p className="text-sm text-[#6b675f] max-w-2xl leading-relaxed">
              {error
                ? `Projection endpoint returned: ${error}`
                : "Awaiting 3-Year Projection Engine output for this plot. Refresh telemetry to run the 5-strategy simulation."}
            </p>
          </div>
          {onRunProjection && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onRunProjection}
              className="h-8 text-xs gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Run 3-Year Projection
            </Button>
          )}
        </div>
      </div>
    );
  }

  const cm = active.cumulative_metrics || {};
  const years: AnnualGroundImpact[] = [active.year_1, active.year_2, active.year_3].filter(Boolean);
  const advisory = data.gemini_advisory;
  const friendlyPlotName = plotName?.trim() || "this parcel";
  const decisionRules = parseDecisionRules(advisory?.farmer_decision_guide);
  const asList = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && !!x.trim()) : typeof v === "string" && v.trim() ? [v] : [];
  const pros = activeBreakdown ? [...asList(activeBreakdown.benefits_plain_words), ...asList(activeBreakdown.expected_rewards)] : [];
  const cons = activeBreakdown ? [...asList(activeBreakdown.drawbacks_plain_words), ...asList(activeBreakdown.risks_taken)] : [];
  const checklistItems =
    (advisory?.ground_truth_field_checklist?.length ?? 0) > 0
      ? advisory!.ground_truth_field_checklist!
      : active.risk_mitigation_actions || [];

  return (
    <div ref={planRef} className="space-y-7 font-sans">
      {advisory && <AdvisoryBriefing advisory={advisory} />}

      {/* 1. Hero: Editorial Briefing (No Card, Max-Width Prose + 5-Pathway Bullets) */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="max-w-2xl space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-[#20808d]">
            Your options
            {data.resolved_soil_type ? ` · ${data.resolved_soil_type}` : ""}
            {data.field_area_ha ? ` · ${data.field_area_ha.toFixed(2)} ha` : ""}
          </p>

          <p className="text-[15px] leading-relaxed text-[#1f1915]">
            Here is your 3-year roadmap for <strong className="font-semibold">{friendlyPlotName}</strong>
            {data.field_area_ha || data.resolved_soil_type
              ? ` (${[
                  data.field_area_ha ? `${data.field_area_ha.toFixed(2)} ha` : null,
                  data.resolved_soil_type || null,
                ]
                  .filter(Boolean)
                  .join(", ")})`
              : ""}
            , simulated across {strategyList.length} pathways to match your farm priorities:
          </p>

          <ul className="space-y-2 pl-4 list-disc marker:text-[#20808d] text-[14.5px] leading-relaxed text-[#1f1915]">
            {strategyList.map((s) => {
              const b = editorialBulletForStrategy(s, decisionRules);
              return (
                <li key={s.strategy_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(s.strategy_id)}
                    className="text-left font-semibold text-[#1f1915] hover:text-[#20808d] transition-colors"
                  >
                    {b.title}
                  </button>
                  {b.crops ? (
                    <span className="italic text-[#6b675f]"> ({b.crops})</span>
                  ) : null}
                  {": "}
                  {b.lead}
                  <strong className="font-semibold font-mono tabular-nums text-[#1f1915]">
                    {b.metric}
                  </strong>
                  {b.tail}—best if {b.criteria}.
                </li>
              );
            })}
          </ul>
        </div>
        {onRunProjection && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onRunProjection}
            className="h-8 text-xs gap-1.5 shrink-0"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Re-run
          </Button>
        )}
      </div>

      {/* 2. Selector: Horizontal 5-Goal Pill Bar */}
      <div className="space-y-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {strategyList.map((s) => {
            const isSelected = s.strategy_id === active.strategy_id;
            const pill = goalPillMeta(s);
            return (
              <button
                key={s.strategy_id}
                type="button"
                onClick={() => setSelectedId(s.strategy_id)}
                className={`inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-medium border transition-colors ${
                  isSelected
                    ? "bg-[#20808d] text-white border-[#20808d] shadow-sm"
                    : "bg-[#fdfbfa] text-[#1f1915] border-[#e7e5e0] hover:border-[#20808d]/60"
                }`}
              >
                <span>{pill.label}</span>
                <span
                  className={`font-mono tabular-nums text-[11px] px-1.5 py-0.5 rounded-full ${
                    isSelected
                      ? "bg-white/20 text-white"
                      : "bg-[#f5f4ef] text-[#6b675f]"
                  }`}
                >
                  {pill.metric}
                </span>
              </button>
            );
          })}
        </div>

        {/* Full untruncated rotation sequence for the active goal */}
        <div className="flex flex-wrap items-baseline justify-between gap-2 pt-1">
          <h3 className="font-serif text-lg font-semibold text-[#1f1915]">
            {active.rotation_sequence.join(" → ")}
          </h3>
          {active.core_objective && (
            <span className="text-xs text-[#6b675f]">{active.core_objective}</span>
          )}
        </div>
      </div>

      {/* 3. Plan Overview: 4 Headline KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="kpi-card-animate rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] px-4 py-3">
          <p className="text-xs text-[#6b675f]">3-Year Net Profit</p>
          <p className="text-xl font-semibold text-[#1f1915] font-mono tabular-nums mt-0.5">
            {fmtMoney(cm.total_net_profit_usd)}
          </p>
          <p className="text-xs text-[#20808d] font-mono tabular-nums">
            {fmtNum(cm.cumulative_roi_pct, 1, "% ROI")}
          </p>
        </div>
        <div className="kpi-card-animate rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] px-4 py-3">
          <p className="text-xs text-[#6b675f]">3-Year Irrigation</p>
          <p className="text-xl font-semibold text-[#1f1915] font-mono tabular-nums mt-0.5">
            {fmtNum(cm.total_irrigation_volume_m3, 0, " m³")}
          </p>
          <p className="text-xs text-[#6b675f] font-mono tabular-nums">
            Erosion {fmtNum(cm.average_annual_erosion_tons_ha, 2, " t/ha/yr")}
          </p>
        </div>
        <div className="kpi-card-animate rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] px-4 py-3">
          <p className="text-xs text-[#6b675f]">Soil Carbon &amp; Free N</p>
          <p className="text-xl font-semibold text-[#1f1915] font-mono tabular-nums mt-0.5">
            {fmtSigned(cm.net_soc_change_pct, 3, "% SOC")}
          </p>
          <p className="text-xs text-emerald-700 font-mono tabular-nums">
            +{fmtNum(cm.total_biological_n_fixed_kg_ha, 0, " kg/ha N")} fixed
          </p>
        </div>
        <div className="kpi-card-animate rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] px-4 py-3">
          <p className="text-xs text-[#6b675f]">Field Labor &amp; Compaction</p>
          <p className="text-xl font-semibold text-[#1f1915] font-mono tabular-nums mt-0.5">
            {fmtNum(cm.total_labor_hours, 0, " hrs")}
          </p>
          <p className="text-xs text-[#6b675f] font-mono tabular-nums">
            {fmtSigned(cm.net_compaction_change_psi, 0, " psi")} ·{" "}
            {cm.total_machinery_passes ?? "—"} passes
          </p>
        </div>
      </div>

      {/* 4. Layer 1: Farmer View — 3-Step Visual Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {years.map((yr) => {
          const irrig = yr.irrigation_water_applied_mm ?? 0;
          const nBal = yr.nitrogen_balance_kg_ha ?? 0;
          const compDelta = yr.compaction_change_psi ?? 0;

          const irrigTone =
            irrig <= 40
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : irrig <= 140
                ? "bg-amber-50 text-amber-800 border-amber-200"
                : "bg-rose-50 text-rose-800 border-rose-200";
          const nTone =
            nBal >= 0
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : nBal >= -40
                ? "bg-amber-50 text-amber-800 border-amber-200"
                : "bg-rose-50 text-rose-800 border-rose-200";
          const compTone =
            compDelta <= 0
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : compDelta <= 30
                ? "bg-amber-50 text-amber-800 border-amber-200"
                : "bg-rose-50 text-rose-800 border-rose-200";

          return (
            <div
              key={yr.year_index}
              className="year-card-animate rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] p-4 flex flex-col justify-between gap-3"
            >
              <div className="space-y-3">
                {/* 1. Header */}
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[#6b675f]">
                    Year {yr.year_index}
                    {yr.season_label ? ` · ${yr.season_label}` : ""}
                  </span>
                  <Badge variant="outline" className="font-mono tabular-nums text-xs">
                    {fmtMoney(yr.net_profit_usd)}
                  </Badge>
                </div>

                {/* 2. Crop & Role */}
                <div>
                  <h4 className="font-serif text-base font-semibold text-[#1f1915]">
                    {yr.crop_name}
                  </h4>
                  {yr.botanical_family && (
                    <p className="text-xs text-[#6b675f]">{yr.botanical_family}</p>
                  )}
                </div>

                {/* 3. Three Simple Traffic-Light Status Pills */}
                <div className="flex flex-wrap gap-1.5">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium font-mono tabular-nums ${irrigTone}`}
                  >
                    <Droplets className="h-3 w-3" />
                    {fmtNum(irrig, 0, " mm")} irrig
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium font-mono tabular-nums ${nTone}`}
                  >
                    <FlaskConical className="h-3 w-3" />
                    {fmtSigned(nBal, 0, " kg/ha")} N
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium font-mono tabular-nums ${compTone}`}
                  >
                    <Gauge className="h-3 w-3" />
                    {fmtSigned(compDelta, 0, " psi")}
                  </span>
                </div>
              </div>

              {/* 4. One-Sentence Takeaway */}
              {yr.ground_narrative && (
                <p className="text-xs text-[#6b675f] leading-relaxed pt-2.5 border-t border-[#e7e5e0]">
                  {yr.ground_narrative}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Strategy Trade-off Highlights (compact prose if available) */}
      {activeBreakdown && (pros.length > 0 || cons.length > 0 || activeBreakdown.three_year_action_overview) && (
        <div className="space-y-3">
          {activeBreakdown.three_year_action_overview && (
            <p className="text-sm leading-relaxed text-[#1f1915] max-w-3xl">
              <span className="font-semibold">This plan in practice: </span>
              {renderHighlightedProse(activeBreakdown.three_year_action_overview)}
            </p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            {pros.length > 0 && (
              <div className="rounded-lg border border-emerald-200/70 bg-emerald-50/40 p-3.5 space-y-1">
                <p className="font-semibold text-emerald-800">Why pick this plan</p>
                <ul className="space-y-1 text-[#1f1915] leading-relaxed">
                  {pros.map((b, i) => (
                    <li key={i}>• {b}</li>
                  ))}
                </ul>
              </div>
            )}
            {cons.length > 0 && (
              <div className="rounded-lg border border-amber-200/70 bg-amber-50/40 p-3.5 space-y-1">
                <p className="font-semibold text-amber-800">Trade-offs &amp; risks</p>
                <ul className="space-y-1 text-[#1f1915] leading-relaxed">
                  {cons.map((d, i) => (
                    <li key={i}>• {d}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 5. Layer 2: Collapsible Drawers (Closed by Default) */}
      <div className="space-y-2.5">
        {/* Drawer 1: Full Agronomic & Financial Table */}
        <div className="rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] overflow-hidden">
          <button
            type="button"
            onClick={() => setShowTableDrawer((v) => !v)}
            className="w-full px-4 py-3 flex items-center justify-between text-xs font-medium text-[#1f1915] hover:bg-[#f5f4ef]/60 transition-colors"
          >
            <span className="inline-flex items-center gap-2">
              <Table2 className="h-4 w-4 text-[#20808d]" />
              Detailed Year-by-Year Agronomic &amp; Financial Table
            </span>
            {showTableDrawer ? <ChevronUp className="h-4 w-4 text-[#6b675f]" /> : <ChevronDown className="h-4 w-4 text-[#6b675f]" />}
          </button>
          {showTableDrawer && (
            <div className="border-t border-[#e7e5e0] overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-[#faf9f5] border-b border-[#e7e5e0] text-[#6b675f]">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">Metric</th>
                    {years.map((yr) => (
                      <th key={yr.year_index} className="text-right px-4 py-2 font-medium">
                        Year {yr.year_index} ({yr.crop_name})
                      </th>
                    ))}
                    <th className="text-right px-4 py-2 font-semibold text-[#1f1915]">3-Year Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#e7e5e0] font-mono tabular-nums">
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">Projected Yield (t/ha)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtNum(yr.projected_yield_tons_ha, 2)}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold">—</td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">Net Profit &amp; ROI</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtMoney(yr.net_profit_usd)} ({fmtNum(yr.roi_pct, 0, "%")})
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold text-[#20808d]">
                      {fmtMoney(cm.total_net_profit_usd)} ({fmtNum(cm.cumulative_roi_pct, 1, "%")})
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">Water Demand ETc / Irrig (mm)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtNum(yr.water_demand_etc_mm, 0)} / {fmtNum(yr.irrigation_water_applied_mm, 0)}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold">
                      {fmtNum(cm.total_irrigation_volume_m3, 0, " m³")}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">N Balance / Bio-N (kg/ha)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtSigned(yr.nitrogen_balance_kg_ha, 0)} / +{fmtNum(yr.biological_n_fixed_kg_ha, 0)}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold text-emerald-700">
                      +{fmtNum(cm.total_biological_n_fixed_kg_ha, 0, " kg/ha")}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">SOC Δ &amp; Erosion (t/ha)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtSigned(yr.soc_change_pct, 3, "%")} · {fmtNum(yr.soil_erosion_tons_ha, 2)}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold">
                      {fmtSigned(cm.net_soc_change_pct, 3, "%")} · {fmtNum(cm.average_annual_erosion_tons_ha, 2, " avg")}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">Compaction Δ (psi)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtSigned(yr.compaction_change_psi, 1)}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold">
                      {fmtSigned(cm.net_compaction_change_psi, 1, " psi")}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-sans text-[#6b675f]">Tractor Hours &amp; Diesel (L)</td>
                    {years.map((yr) => (
                      <td key={yr.year_index} className="px-4 py-2 text-right">
                        {fmtNum(yr.labor_hours_total, 0, "h")} · {fmtNum(yr.fuel_consumed_liters, 0, "L")}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-right font-semibold">
                      {fmtNum(cm.total_labor_hours, 0, "h")} · {fmtNum(cm.total_diesel_liters, 0, "L")}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Drawer 2: Local Field Verification Checklist & Formula Sources */}
        <div className="rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] overflow-hidden">
          <button
            type="button"
            onClick={() => setShowChecklistDrawer((v) => !v)}
            className="w-full px-4 py-3 flex items-center justify-between text-xs font-medium text-[#1f1915] hover:bg-[#f5f4ef]/60 transition-colors"
          >
            <span className="inline-flex items-center gap-2">
              <ClipboardCheck className="h-4 w-4 text-[#20808d]" />
              Field checklist{checklistItems.length ? ` (${checklistItems.length})` : ""} &amp; how this was calculated
            </span>
            {showChecklistDrawer ? <ChevronUp className="h-4 w-4 text-[#6b675f]" /> : <ChevronDown className="h-4 w-4 text-[#6b675f]" />}
          </button>
          {showChecklistDrawer && (
            <div className="px-4 pb-4 pt-3 border-t border-[#e7e5e0] space-y-4">
              {checklistItems.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold text-[#1f1915]">
                    Where Satellite Data Needs Local Eyes
                  </p>
                  <div className="space-y-1.5">
                    {checklistItems.map((item, idx) => (
                      <label
                        key={idx}
                        className="flex items-start gap-2.5 text-xs text-[#1f1915] cursor-pointer select-none"
                      >
                        <input
                          type="checkbox"
                          checked={Boolean(checkedItems[idx])}
                          onChange={(e) =>
                            setCheckedItems((prev) => ({ ...prev, [idx]: e.target.checked }))
                          }
                          className="mt-0.5 rounded border-[#e7e5e0] text-[#20808d] focus:ring-[#20808d]"
                        />
                        <span className={checkedItems[idx] ? "line-through text-[#6b675f]" : ""}>
                          {item}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div className="pt-3 border-t border-[#e7e5e0] space-y-1.5 text-xs text-[#6b675f]">
                <div className="flex items-center gap-1.5 text-[#1f1915] font-medium">
                  <ShieldCheck className="h-3.5 w-3.5 text-[#20808d]" />
                  <span>Models &amp; Data Provenance</span>
                </div>
                <p>
                  Water balance via FAO-56 (<code className="font-mono">ETc = Kc × ET0</code>),
                  erosion via RUSLE (<code className="font-mono">A = R · K · LS · C · P</code>),
                  organic carbon via Henin-Dupuis, and compaction via ASAE machinery load curves
                  {advisory?.model_used ? ` · Plain-language translation via ${advisory.model_used}` : ""}.
                </p>
                <p className="text-[11px]">
                  Advisory only — recommendations support and do not replace local agronomist and farmer judgment.
                </p>
                {data.data_layering_provenance && (
                  <pre className="whitespace-pre-wrap break-all bg-[#faf9f5] p-2.5 rounded border border-[#e7e5e0] font-mono text-[10px]">
                    {JSON.stringify(data.data_layering_provenance, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
