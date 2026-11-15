"use client";

import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Droplets,
  Leaf,
  RefreshCw,
  ShieldAlert,
  Sprout,
  TrendingUp,
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

function fmtSigned(val: number | undefined | null, digits = 2, suffix = ""): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "—";
  const sign = val > 0 ? "+" : "";
  return `${sign}${val.toFixed(digits)}${suffix}`;
}

export function ProjectionPlanPanel({
  data,
  loading,
  error,
  onRunProjection,
}: {
  data: ThreeYearPlanResponse | null;
  loading?: boolean;
  error?: string | null;
  onRunProjection?: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showProvenance, setShowProvenance] = useState(false);

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

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 rounded-lg border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
          ))}
        </div>
        <div className="h-20 rounded-lg border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-64 rounded-lg border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || !active) {
    return (
      <div className="rounded-lg border border-dashed border-[#e7e5e0] bg-[#fdfbfa] p-6 space-y-3">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sprout className="h-4 w-4 text-[#20808d]" />
              <h3 className="font-serif text-base font-semibold">
                3-Year Agronomic &amp; Financial Projection
              </h3>
            </div>
            <p className="text-xs text-[#6b675f] max-w-2xl">
              {error
                ? `Projection endpoint returned: ${error}`
                : "Awaiting connection to the 3-Year Projection Engine (analytics-api). Once wired, this view compares up to 5 rotation strategies year-by-year across profit, soil organic carbon, compaction, nitrogen credits, irrigation demand, and plain-language risk trade-offs."}
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

  return (
    <div className="space-y-6">
      {/* Header & Strategy Selector */}
      <div className="space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <p className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
              3-Year Projection Strategies ({strategyList.length})
            </p>
            {data.resolved_soil_type && (
              <p className="text-xs text-[#6b675f]">
                Soil: <span className="text-[#1f1915] font-medium">{data.resolved_soil_type}</span>
                {data.field_area_ha ? ` · ${data.field_area_ha.toFixed(2)} ha` : ""}
              </p>
            )}
          </div>
          {onRunProjection && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onRunProjection}
              className="h-7 text-xs gap-1.5"
            >
              <RefreshCw className="h-3 w-3" />
              Re-run Projection
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {strategyList.map((s) => {
            const isSelected = s.strategy_id === active.strategy_id;
            const scm = s.cumulative_metrics || {};
            return (
              <button
                key={s.strategy_id}
                type="button"
                onClick={() => setSelectedId(s.strategy_id)}
                className={`text-left rounded-lg border p-3.5 transition space-y-2 ${
                  isSelected
                    ? "border-[#20808d] bg-[#fdfbfa] ring-1 ring-[#20808d]"
                    : "border-[#e7e5e0] bg-[#fdfbfa] hover:border-[#20808d]/50"
                }`}
              >
                <div className="space-y-0.5">
                  <p className="font-serif text-sm font-semibold leading-snug">{s.strategy_title}</p>
                  <p className="text-[11px] font-mono text-[#6b675f] truncate">
                    {s.rotation_sequence.join(" → ")}
                  </p>
                </div>
                <div className="flex items-center justify-between text-xs font-mono tabular-nums pt-1 border-t border-[#e7e5e0]">
                  <span className="font-semibold text-[#1f1915]">
                    {fmtMoney(scm.total_net_profit_usd)}
                  </span>
                  <span className="text-[#20808d]">
                    {fmtNum(scm.cumulative_roi_pct, 1, "% ROI")}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] font-mono text-[#6b675f]">
                  <span>Soil {fmtNum(scm.cumulative_soil_health_score, 0, "/100")}</span>
                  <span>Risk {fmtNum(scm.composite_loss_risk_score, 0, "/100")}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Selected Strategy Cumulative Strip */}
      <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h3 className="font-serif text-lg font-semibold">{active.strategy_title}</h3>
            <p className="text-xs font-mono text-[#20808d]">
              {active.rotation_sequence.join(" → ")}
            </p>
          </div>
          {active.core_objective && (
            <Badge variant="outline" className="text-[11px] font-normal max-w-md truncate">
              {active.core_objective}
            </Badge>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-2 border-t border-[#e7e5e0] text-xs font-mono tabular-nums">
          <div>
            <p className="text-[10px] text-[#6b675f]">3-YR NET PROFIT</p>
            <p className="text-sm font-semibold text-[#1f1915]">{fmtMoney(cm.total_net_profit_usd)}</p>
            <p className="text-[10px] text-[#6b675f]">ROI {fmtNum(cm.cumulative_roi_pct, 1, "%")}</p>
          </div>
          <div>
            <p className="text-[10px] text-[#6b675f]">SOIL CARBON (SOC)</p>
            <p className="text-sm font-semibold text-[#1f1915]">
              {fmtSigned(cm.net_soc_change_pct, 3, "%")}
            </p>
            <p className="text-[10px] text-[#6b675f]">
              {fmtNum(cm.initial_soc_pct, 2)}% → {fmtNum(cm.final_soc_pct, 2)}%
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[#6b675f]">BIO N FIXED</p>
            <p className="text-sm font-semibold text-[#1f1915]">
              {fmtNum(cm.total_biological_n_fixed_kg_ha, 0, " kg/ha")}
            </p>
            <p className="text-[10px] text-[#6b675f]">
              Saved {fmtMoney(cm.synthetic_n_saved_usd)}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[#6b675f]">IRRIGATION (3 YR)</p>
            <p className="text-sm font-semibold text-[#1f1915]">
              {fmtNum(cm.total_irrigation_volume_m3, 0, " m³")}
            </p>
            <p className="text-[10px] text-[#6b675f]">
              Erosion {fmtNum(cm.average_annual_erosion_tons_ha, 2, " t/ha/yr")}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[#6b675f]">COMPACTION Δ</p>
            <p className="text-sm font-semibold text-[#1f1915]">
              {fmtSigned(cm.net_compaction_change_psi, 1, " psi")}
            </p>
            <p className="text-[10px] text-[#6b675f]">
              {fmtNum(cm.initial_compaction_psi, 0)} → {fmtNum(cm.final_compaction_psi, 0)} psi
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[#6b675f]">FIELD OPS (3 YR)</p>
            <p className="text-sm font-semibold text-[#1f1915]">
              {fmtNum(cm.total_labor_hours, 0, " hrs")}
            </p>
            <p className="text-[10px] text-[#6b675f]">
              {cm.total_machinery_passes ?? "—"} passes · {fmtNum(cm.total_diesel_liters, 0, " L")}
            </p>
          </div>
        </div>
      </div>

      {/* Year-by-Year Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {years.map((yr) => (
          <div
            key={yr.year_index}
            className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3 flex flex-col justify-between"
          >
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b675f]">
                    Year {yr.year_index} {yr.season_label ? `· ${yr.season_label}` : ""}
                  </p>
                  <h4 className="font-serif text-base font-semibold">{yr.crop_name}</h4>
                  {yr.botanical_family && (
                    <p className="text-[11px] text-[#6b675f]">{yr.botanical_family}</p>
                  )}
                </div>
                <Badge variant="outline" className="font-mono text-[11px] tabular-nums">
                  {fmtMoney(yr.net_profit_usd)}
                </Badge>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-2 border-t border-[#e7e5e0] text-xs font-mono tabular-nums">
                <div>
                  <span className="text-[10px] text-[#6b675f] block">Yield</span>
                  <span>
                    {fmtNum(yr.projected_yield_tons_ha, 2, " t/ha")}
                    {yr.total_yield_tons !== undefined ? ` (${fmtNum(yr.total_yield_tons, 1, " t")})` : ""}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-[#6b675f] block">ROI / Cost</span>
                  <span>
                    {fmtNum(yr.roi_pct, 1, "%")} · {fmtMoney(yr.total_cost_usd)}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-[#6b675f] block">Water (ETc / Irrig)</span>
                  <span>
                    {fmtNum(yr.water_demand_etc_mm, 0, " mm")} /{" "}
                    {fmtNum(yr.irrigation_water_applied_mm, 0, " mm")}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-[#6b675f] block">N Balance / Bio-N</span>
                  <span>
                    {fmtSigned(yr.nitrogen_balance_kg_ha, 0)} / +{fmtNum(yr.biological_n_fixed_kg_ha, 0, " kg")}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-[#6b675f] block">SOC Δ / Erosion</span>
                  <span>
                    {fmtSigned(yr.soc_change_pct, 3, "%")} · {fmtNum(yr.soil_erosion_tons_ha, 2, " t/ha")}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-[#6b675f] block">Compaction Δ</span>
                  <span>{fmtSigned(yr.compaction_change_psi, 1, " psi")}</span>
                </div>
              </div>

              {yr.ground_narrative && (
                <p className="text-xs text-[#6b675f] leading-relaxed pt-2 border-t border-[#e7e5e0]">
                  {yr.ground_narrative}
                </p>
              )}
            </div>

            <div className="flex items-center justify-between text-[11px] font-mono text-[#6b675f] pt-2 border-t border-[#e7e5e0]">
              <span>Vitality {fmtNum(yr.rhizosphere_vitality_score, 0)}</span>
              <span>Disease {fmtNum(yr.pathogen_disease_risk_score, 0)}</span>
              <span>Extreme {fmtNum(yr.extreme_event_vulnerability_score, 0)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Plain-Language Trade-offs & Local Verification Checklist */}
      {(advisory || active.strategic_summary || (active.risk_mitigation_actions?.length ?? 0) > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          <div className="lg:col-span-7 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[#20808d]" />
              <h4 className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                Plain-Language Agronomist Trade-Offs
              </h4>
            </div>
            {(advisory?.farmer_plain_language_summary || active.strategic_summary) && (
              <p className="text-xs text-[#1f1915] leading-relaxed">
                {advisory?.farmer_plain_language_summary || active.strategic_summary}
              </p>
            )}
            {activeBreakdown && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-[#e7e5e0] text-xs">
                {(activeBreakdown.benefits_plain_words?.length ?? 0) > 0 && (
                  <div className="space-y-1">
                    <p className="font-mono text-[10px] uppercase text-emerald-700 flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3" /> Benefits
                    </p>
                    <ul className="space-y-1 text-[#1f1915]">
                      {activeBreakdown.benefits_plain_words!.map((b, i) => (
                        <li key={i}>• {b}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(activeBreakdown.drawbacks_plain_words?.length ?? 0) > 0 && (
                  <div className="space-y-1">
                    <p className="font-mono text-[10px] uppercase text-amber-700 flex items-center gap-1">
                      <AlertTriangle className="h-3 w-3" /> Trade-offs &amp; Risks
                    </p>
                    <ul className="space-y-1 text-[#1f1915]">
                      {activeBreakdown.drawbacks_plain_words!.map((d, i) => (
                        <li key={i}>• {d}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {advisory?.farmer_decision_guide && (
              <p className="text-xs text-[#6b675f] pt-2 border-t border-[#e7e5e0]">
                <strong className="text-[#1f1915]">Decision guide:</strong> {advisory.farmer_decision_guide}
              </p>
            )}
          </div>

          <div className="lg:col-span-5 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-600" />
              <h4 className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                Where Satellite Data Needs Local Eyes
              </h4>
            </div>
            {(advisory?.ground_truth_field_checklist?.length ?? 0) > 0 ? (
              <ul className="space-y-1.5 text-xs text-[#1f1915]">
                {advisory!.ground_truth_field_checklist!.map((item, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <Leaf className="h-3.5 w-3.5 text-[#20808d] shrink-0 mt-0.5" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : (active.risk_mitigation_actions?.length ?? 0) > 0 ? (
              <ul className="space-y-1.5 text-xs text-[#1f1915]">
                {active.risk_mitigation_actions!.map((item, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <Droplets className="h-3.5 w-3.5 text-[#20808d] shrink-0 mt-0.5" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="text-[11px] text-[#6b675f] pt-2 border-t border-[#e7e5e0]">
              Recommendations support—and do not replace—local agronomist and farmer judgment.
            </p>
          </div>
        </div>
      )}

      {/* Expandable Sources & Provenance */}
      <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa]">
        <button
          type="button"
          onClick={() => setShowProvenance((v) => !v)}
          className="w-full px-4 py-2.5 flex items-center justify-between text-xs font-mono text-[#6b675f] hover:text-[#1f1915]"
        >
          <span>How this was calculated &amp; NASA / SoilGrids sources</span>
          {showProvenance ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {showProvenance && (
          <div className="px-4 pb-3 pt-1 border-t border-[#e7e5e0] text-[11px] font-mono text-[#6b675f] space-y-1.5">
            <p>
              Deterministic FAO-56 water balance, RUSLE erosion, and IPCC/FAO nitrogen + SOC budgets
              {advisory?.model_used ? ` · Plain-language summary via ${advisory.model_used}` : ""}
            </p>
            {data.data_layering_provenance && (
              <pre className="whitespace-pre-wrap break-all bg-[#faf9f5] p-2 rounded border border-[#e7e5e0] text-[10px]">
                {JSON.stringify(data.data_layering_provenance, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
