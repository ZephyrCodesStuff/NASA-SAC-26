"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  Sprout,
  ChevronDown,
  ChevronUp,
  Cpu,
  Wifi,
  SlidersHorizontal,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { PeriodChart, PeriodPoint } from "@/components/period-chart";
import { FarmRecord, PlotRecord, webApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const PlotSatelliteThumb = dynamic(
  () => import("@/components/plot-satellite-thumb").then((m) => m.PlotSatelliteThumb),
  {
    ssr: false,
    loading: () => (
      <div className="h-[132px] w-[220px] shrink-0 rounded-md border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
    ),
  }
);

type TabKey = "overview" | "rotation" | "devices";

interface SensorReading {
  ts: string;
  moisture: number;
  humidity: number;
  tempC: number;
}

const PERIOD_LABELS = [
  "Jan 1–15", "Jan 16–31", "Feb 1–15", "Feb 16–28",
  "Mar 1–15", "Mar 16–31", "Apr 1–15", "Apr 16–30",
  "May 1–15", "May 16–31", "Jun 1–15", "Jun 16–30",
  "Jul 1–15", "Jul 16–31", "Aug 1–15", "Aug 16–31",
  "Sep 1–15", "Sep 16–30", "Oct 1–15", "Oct 16–31",
  "Nov 1–15", "Nov 16–30", "Dec 1–15", "Dec 16–31",
];

// Deterministic Turin Po Valley seasonal curve fallback when telemetry isn't refreshed yet
function build24PeriodSeries(nasaSnapshot?: Record<string, unknown>): PeriodPoint[] {
  const datasets = (nasaSnapshot?.datasets || nasaSnapshot || {}) as Record<string, unknown>;
  const power = (datasets.power || {}) as Record<string, unknown>;
  const monthlyPrecip = Array.isArray(power.monthly_precip_mm) ? (power.monthly_precip_mm as number[]) : null;
  const monthlyTemp = Array.isArray(power.monthly_temp_c) ? (power.monthly_temp_c as number[]) : null;

  const defaultMonthlyPrecip = [48, 52, 68, 86, 98, 72, 42, 48, 78, 96, 84, 54];
  const defaultMonthlyTemp = [2.5, 4.8, 9.2, 13.1, 17.8, 21.9, 24.5, 23.8, 19.3, 13.6, 7.6, 3.4];

  return PERIOD_LABELS.map((label, idx) => {
    const m = Math.floor(idx / 2);
    const pMonth = monthlyPrecip?.[m] ?? defaultMonthlyPrecip[m];
    const tMonth = monthlyTemp?.[m] ?? defaultMonthlyTemp[m];
    const halfFactor = idx % 2 === 0 ? 0.94 : 1.06;
    const precipMm = Math.max(4, (pMonth / 2) * halfFactor);
    const etcMm = Math.max(8, (tMonth * 2.3 + 6) * (idx % 2 === 0 ? 0.97 : 1.03));
    return {
      period: idx + 1,
      label,
      precipMm,
      etcMm,
      tempC: tMonth,
    };
  });
}

export function PlotWorkspace({ plotId }: { plotId: string }) {
  const { token } = useAuth();
  const [tab, setTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [plot, setPlot] = useState<PlotRecord | null>(null);
  const [farm, setFarm] = useState<FarmRecord | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [analysisData, setAnalysisData] = useState<Record<string, unknown> | null>(null);

  // Soil & utility overrides editor
  const [editingOverrides, setEditingOverrides] = useState(false);
  const [phInput, setPhInput] = useState("6.8");
  const [elecPrice, setElecPrice] = useState("0.24");
  const [waterPrice, setWaterPrice] = useState("0.45");
  const [savingOverrides, setSavingOverrides] = useState(false);

  // P&L inline cost inputs (€/ha)
  const [workerCost, setWorkerCost] = useState(420);
  const [transportCost, setTransportCost] = useState(185);
  const [selectedStrategyIdx, setSelectedStrategyIdx] = useState(0);
  const [showSources, setShowSources] = useState(false);

  // Hardware / Devices tab state
  const [deviceCodeInput, setDeviceCodeInput] = useState("");
  const [pairedDeviceId, setPairedDeviceId] = useState<string | null>(null);
  const [livePolling, setLivePolling] = useState(true);
  const [readings, setReadings] = useState<SensorReading[]>([
    { ts: "22:08:10", moisture: 34.2, humidity: 58, tempC: 18.6 },
    { ts: "22:08:12", moisture: 34.5, humidity: 58, tempC: 18.6 },
    { ts: "22:08:14", moisture: 34.1, humidity: 59, tempC: 18.7 },
    { ts: "22:08:16", moisture: 34.4, humidity: 58, tempC: 18.6 },
  ]);

  const loadAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [plotRes, analysisRes] = await Promise.all([
        webApi.getPlot(plotId, token),
        webApi.getAnalysisPayload(plotId, token).catch(() => null),
      ]);
      setPlot(plotRes.plot);
      setFarm(plotRes.farm);
      setIsOwner(plotRes.is_owner);
      setAnalysisData(analysisRes);

      const ov = (plotRes.plot.soil_override || {}) as Record<string, unknown>;
      if (ov.ph !== undefined) setPhInput(String(ov.ph));
      if (ov.electricity_price_eur_kwh !== undefined) setElecPrice(String(ov.electricity_price_eur_kwh));
      if (ov.water_price_eur_m3 !== undefined) setWaterPrice(String(ov.water_price_eur_m3));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load plot");
    } finally {
      setLoading(false);
    }
  }, [plotId, token]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Restore paired device code for this plot
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(`paired_device_${plotId}`);
    if (saved) setPairedDeviceId(saved);
  }, [plotId]);

  // Live sensor polling tick when paired & polling enabled
  useEffect(() => {
    if (!pairedDeviceId || !livePolling) return;
    const timer = setInterval(() => {
      setReadings((prev) => {
        const last = prev[prev.length - 1] || { moisture: 34.2, humidity: 58, tempC: 18.6 };
        const jitter = (Math.random() - 0.5) * 0.6;
        const now = new Date().toTimeString().slice(0, 8);
        const next: SensorReading = {
          ts: now,
          moisture: Number(Math.max(5, Math.min(95, last.moisture + jitter)).toFixed(1)),
          humidity: Math.round(Math.max(20, Math.min(98, last.humidity + (Math.random() - 0.5) * 1.5))),
          tempC: Number((last.tempC + (Math.random() - 0.5) * 0.2).toFixed(1)),
        };
        return [...prev.slice(-23), next];
      });
    }, 2000);
    return () => clearInterval(timer);
  }, [pairedDeviceId, livePolling]);

  const handleRefreshTelemetry = async () => {
    if (!token) return;
    setRefreshing(true);
    try {
      const res = await webApi.refreshTelemetry(plotId, token);
      setPlot((prev) => (prev ? { ...prev, nasa_snapshot: res.nasa_snapshot } : prev));
      const analysisRes = await webApi.getAnalysisPayload(plotId, token).catch(() => null);
      if (analysisRes) setAnalysisData(analysisRes);
      toast.success("NASA & SoilGrids telemetry refreshed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Telemetry refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const handleSaveOverrides = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !plot) return;
    setSavingOverrides(true);
    try {
      const nextOverride = {
        ...(plot.soil_override || {}),
        ph: Number(phInput) || 6.8,
        electricity_price_eur_kwh: Number(elecPrice) || 0.24,
        water_price_eur_m3: Number(waterPrice) || 0.45,
      };
      const res = await webApi.updatePlot(plotId, { soil_override: nextOverride }, token);
      setPlot(res.plot);
      const analysisRes = await webApi.getAnalysisPayload(plotId, token).catch(() => null);
      if (analysisRes) setAnalysisData(analysisRes);
      setEditingOverrides(false);
      toast.success("Field & utility parameters updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save overrides");
    } finally {
      setSavingOverrides(false);
    }
  };

  const handlePairDevice = (e: React.FormEvent) => {
    e.preventDefault();
    const code = deviceCodeInput.trim().toUpperCase();
    if (!code) return;
    setPairedDeviceId(code);
    window.localStorage.setItem(`paired_device_${plotId}`, code);
    setDeviceCodeInput("");
    toast.success(`Connected sensor ${code}`);
  };

  const simulateProbeDip = () => {
    const now = new Date().toTimeString().slice(0, 8);
    setReadings((prev) => [
      ...prev.slice(-23),
      { ts: now, moisture: 68.4, humidity: 79, tempC: 17.8 },
    ]);
    toast.info("Probe spike recorded (68.4% moisture)");
  };

  const periodPoints = useMemo(() => build24PeriodSeries(plot?.nasa_snapshot), [plot?.nasa_snapshot]);

  const strategies = useMemo(() => {
    const preview = (analysisData?.baseline_preview || {}) as Record<string, unknown>;
    const list = Array.isArray(preview.strategies) ? (preview.strategies as Array<Record<string, unknown>>) : [];
    if (list.length > 0) return list;
    return [
      {
        name: "Maize → Winter Wheat → Soybean",
        tag: "Recommended · Matches Po Valley baseline",
        water_deficit_mm: -48,
        erosion_t_ha_yr: 1.4,
        nitrogen_balance_kg_ha: 18,
        yield_t_ha: 9.2,
        price_eur_t: 235,
        water_cost_eur_ha: 165,
        energy_cost_eur_ha: 95,
      },
      {
        name: "Winter Wheat → Alfalfa → Maize",
        tag: "Low Water Stress",
        water_deficit_mm: -22,
        erosion_t_ha_yr: 0.9,
        nitrogen_balance_kg_ha: 34,
        yield_t_ha: 8.1,
        price_eur_t: 242,
        water_cost_eur_ha: 110,
        energy_cost_eur_ha: 70,
      },
      {
        name: "Continuous Maize (Status Quo)",
        tag: "High Pest & Nitrogen Risk",
        water_deficit_mm: -74,
        erosion_t_ha_yr: 2.8,
        nitrogen_balance_kg_ha: -24,
        yield_t_ha: 8.6,
        price_eur_t: 220,
        water_cost_eur_ha: 230,
        energy_cost_eur_ha: 120,
      },
    ];
  }, [analysisData]);

  const activeStrategy = strategies[selectedStrategyIdx] || strategies[0];
  const areaHa = plot?.area_ha || 1.0;
  const grossRevenue =
    Number(activeStrategy.yield_t_ha ?? 9.0) * Number(activeStrategy.price_eur_t ?? 230);
  const waterCost = Number(activeStrategy.water_cost_eur_ha ?? 160);
  const energyCost = Number(activeStrategy.energy_cost_eur_ha ?? 90);
  const netMarginHa = grossRevenue - waterCost - energyCost - workerCost - transportCost;

  const latestReading = readings[readings.length - 1];
  const sensorStatus =
    latestReading.moisture >= 40
      ? { label: "OPTIMAL", tone: "text-emerald-700 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" }
      : latestReading.moisture >= 25
        ? { label: "WATCH", tone: "text-amber-700 bg-amber-50 border-amber-200", dot: "bg-amber-500" }
        : { label: "STRESS", tone: "text-rose-700 bg-rose-50 border-rose-200", dot: "bg-rose-500" };

  if (loading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-[#faf9f5] text-[#6b675f] gap-2 text-xs font-mono">
        <Loader2 className="h-4 w-4 animate-spin text-[#20808d]" />
        Loading plot workspace…
      </div>
    );
  }

  if (!plot) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-[#faf9f5] gap-3">
        <p className="text-sm text-[#6b675f]">Plot not found or access denied.</p>
        <Link href="/">
          <Button variant="outline" size="sm">Back to Map</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#faf9f5] text-[#1f1915]">
      {/* Sticky Top Bar */}
      <header className="sticky top-0 z-20 h-[52px] border-b border-[#e7e5e0] bg-[#fdfbfa]/95 backdrop-blur px-6 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            href={`/?farm=${encodeURIComponent(plot.farm)}&plot=${encodeURIComponent(plot.id)}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-[#6b675f] hover:text-[#1f1915]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Map
          </Link>
          <span className="text-[#e7e5e0]">/</span>
          <span className="text-xs text-[#6b675f] truncate hidden sm:inline">{farm?.name}</span>
          <span className="text-[#e7e5e0] hidden sm:inline">/</span>
          <span className="font-serif text-sm font-semibold truncate">{plot.label}</span>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 text-xs gap-1.5"
            disabled={refreshing}
            onClick={handleRefreshTelemetry}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Fetching NASA…" : "Refresh NASA Data"}
          </Button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {/* Compact Hero + Satellite Thumbnail */}
        <section className="flex flex-col md:flex-row gap-5 items-start md:items-center justify-between">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center min-w-0">
            <PlotSatelliteThumb geometry={plot.geometry} centroid={plot.centroid} />
            <div className="space-y-1.5 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-serif text-2xl font-semibold tracking-tight">{plot.label}</h1>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {plot.cadastral_ref || "Custom Polygon"}
                </Badge>
              </div>
              <p className="text-xs text-[#6b675f]">
                {plot.worldcover_label || "Cropland"} ·{" "}
                {plot.centroid
                  ? `${plot.centroid.lat.toFixed(4)}°N, ${plot.centroid.lon.toFixed(4)}°E`
                  : "Turin / Po Valley"}
              </p>
              <div className="flex items-center gap-2 pt-1">
                {isOwner && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1.5"
                    onClick={() => setEditingOverrides((v) => !v)}
                  >
                    <SlidersHorizontal className="h-3 w-3" />
                    Soil &amp; Utility Inputs
                  </Button>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Monospace Spec Strip (replaces 4 KPI cards) */}
        <div className="border-y border-[#e7e5e0] bg-[#fdfbfa] px-4 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-1.5 text-xs font-mono tabular-nums">
          <span>
            <strong className="text-[#6b675f] font-normal">AREA</strong>{" "}
            {areaHa.toFixed(2)} ha
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">SOIL pH</strong>{" "}
            {phInput}
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">WATER</strong>{" "}
            €{waterPrice}/m³
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">POWER</strong>{" "}
            €{elecPrice}/kWh
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">NASA SNAPSHOT</strong>{" "}
            {plot.nasa_snapshot ? "Cached" : "Baseline preview"}
          </span>
        </div>

        {/* Inline Overrides Drawer */}
        {editingOverrides && (
          <form
            onSubmit={handleSaveOverrides}
            className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 flex flex-wrap items-end gap-4"
          >
            <div className="space-y-1 w-32">
              <label className="text-[11px] font-mono text-[#6b675f]">Soil pH</label>
              <Input
                value={phInput}
                onChange={(e) => setPhInput(e.target.value)}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1 w-40">
              <label className="text-[11px] font-mono text-[#6b675f]">Water (€/m³)</label>
              <Input
                value={waterPrice}
                onChange={(e) => setWaterPrice(e.target.value)}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1 w-40">
              <label className="text-[11px] font-mono text-[#6b675f]">Electricity (€/kWh)</label>
              <Input
                value={elecPrice}
                onChange={(e) => setElecPrice(e.target.value)}
                className="h-8 text-xs font-mono"
              />
            </div>
            <Button type="submit" size="sm" className="h-8 text-xs" disabled={savingOverrides}>
              {savingOverrides ? "Saving…" : "Save Parameters"}
            </Button>
          </form>
        )}

        {/* 3-Tab Navigation */}
        <div className="border-b border-[#e7e5e0] flex items-center gap-6">
          {(
            [
              { key: "overview", label: "Overview & Conditions" },
              { key: "rotation", label: "Rotation & Profit" },
              { key: "devices", label: "Devices & Live Telemetry" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`pb-2.5 text-xs font-medium border-b-2 transition ${
                tab === t.key
                  ? "border-[#20808d] text-[#1f1915]"
                  : "border-transparent text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              {t.label}
              {t.key === "devices" && pairedDeviceId && (
                <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 align-middle" />
              )}
            </button>
          ))}
        </div>

        {/* TAB 1: OVERVIEW & CONDITIONS */}
        {tab === "overview" && (
          <div className="space-y-6">
            {/* Editorial Headline + Full-width 24-Period Chart */}
            <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-5 space-y-4">
              <div className="space-y-1">
                <p className="text-[11px] font-mono uppercase tracking-wider text-[#6b675f]">
                  24-Period Seasonal Balance (15-Day Intervals)
                </p>
                <p className="font-serif text-lg font-medium text-[#1f1915]">
                  Peak water deficit occurs in Jul–Aug (Periods 13–16); topsoil erosion remains low at{" "}
                  {Number(activeStrategy.erosion_t_ha_yr ?? 1.4).toFixed(1)} t/ha/yr.
                </p>
              </div>
              <PeriodChart points={periodPoints} />
            </div>

            {/* Asymmetric 2/3 Risk Matrix Table + 1/3 Local Extreme Weather Log */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <div className="lg:col-span-8 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] overflow-hidden">
                <div className="px-4 py-3 border-b border-[#e7e5e0]">
                  <h2 className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                    Agronomic Risk &amp; Readiness Ledger
                  </h2>
                </div>
                <table className="w-full text-xs">
                  <thead className="border-b border-[#e7e5e0] bg-[#faf9f5] text-[#6b675f] font-mono text-[11px]">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium">Condition</th>
                      <th className="text-left px-4 py-2 font-medium">Status</th>
                      <th className="text-right px-4 py-2 font-medium">Measured</th>
                      <th className="text-left px-4 py-2 font-medium">Driver / Window</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e7e5e0] tabular-nums">
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Water Stress (FAO-56)</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 text-amber-700">
                          <span className="h-2 w-2 rounded-full bg-amber-500" />
                          Moderate
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {Number(activeStrategy.water_deficit_mm ?? -48)} mm
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">Periods 13–16 (Jul–Aug)</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Topsoil Erosion (RUSLE)</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 text-emerald-700">
                          <span className="h-2 w-2 rounded-full bg-emerald-500" />
                          Low
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {Number(activeStrategy.erosion_t_ha_yr ?? 1.4).toFixed(1)} t/ha/yr
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">Po Valley low slope</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Extreme Heat / Frost</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 text-amber-700">
                          <span className="h-2 w-2 rounded-full bg-amber-500" />
                          Watch
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">24.5°C peak</td>
                      <td className="px-4 py-2.5 text-[#6b675f]">July heatwaves (P13–14)</td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Greenhouse Requirement</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5 text-emerald-700">
                          <span className="h-2 w-2 rounded-full bg-emerald-500" />
                          Open-field viable
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">Not required</td>
                      <td className="px-4 py-2.5 text-[#6b675f]">210 frost-free days</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* 1/3 Local Extreme Weather & Field Eyes */}
              <div className="lg:col-span-4 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
                <h2 className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                  5-Year Regional Events &amp; Local Eyes
                </h2>
                <div className="divide-y divide-[#e7e5e0] text-xs">
                  <div className="py-2 space-y-0.5">
                    <p className="font-mono text-[10px] text-[#6b675f]">2022 · PIEDMONT DROUGHT</p>
                    <p className="text-[#1f1915]">
                      Po basin summer irrigation restrictions; deep-root rotation reduced yield loss.
                    </p>
                  </div>
                  <div className="py-2 space-y-0.5">
                    <p className="font-mono text-[10px] text-[#6b675f]">2024 · SPRING FLOODING</p>
                    <p className="text-[#1f1915]">
                      Heavy May rainfall (140+ mm) delayed planting; verify field drainage ditches.
                    </p>
                  </div>
                  <div className="py-2 space-y-0.5">
                    <p className="font-mono text-[10px] text-[#6b675f]">LOCAL VERIFICATION</p>
                    <p className="text-[#6b675f]">
                      Confirm well/canal water allocation and topsoil compaction before spring tillage.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: ROTATION & PROFIT */}
        {tab === "rotation" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Strategy List */}
            <div className="lg:col-span-5 space-y-3">
              <p className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                3-Year Rotation Candidates
              </p>
              {strategies.map((s, idx) => {
                const selected = idx === selectedStrategyIdx;
                return (
                  <button
                    key={String(s.name)}
                    type="button"
                    onClick={() => setSelectedStrategyIdx(idx)}
                    className={`w-full text-left rounded-lg border p-4 transition space-y-1.5 ${
                      selected
                        ? "border-[#20808d] bg-[#fdfbfa] ring-1 ring-[#20808d]"
                        : "border-[#e7e5e0] bg-[#fdfbfa] hover:border-[#20808d]/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-serif text-sm font-semibold">{String(s.name)}</span>
                      {idx === 0 && (
                        <Badge variant="success" className="text-[10px]">
                          Recommended
                        </Badge>
                      )}
                    </div>
                    <p className="text-[11px] font-mono text-[#6b675f]">
                      {String(s.tag || "Evaluated via FAO-56 + RUSLE")}
                    </p>
                  </button>
                );
              })}

              {/* Scientific Transparency Disclosure */}
              <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa]">
                <button
                  type="button"
                  onClick={() => setShowSources((v) => !v)}
                  className="w-full px-4 py-2.5 flex items-center justify-between text-xs font-medium text-[#1f1915]"
                >
                  <span>How this was calculated &amp; NASA sources</span>
                  {showSources ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </button>
                {showSources && (
                  <div className="px-4 pb-3 pt-1 border-t border-[#e7e5e0] text-[11px] text-[#6b675f] space-y-1.5">
                    <p>
                      Water balance uses FAO-56 (
                      <code className="font-mono text-[#1f1915]">
                        ET<sub>c</sub> = K<sub>c</sub> &times; ET<sub>0</sub>
                      </code>
                      ), erosion uses RUSLE (
                      <code className="font-mono text-[#1f1915]">
                        A = R &middot; K &middot; LS &middot; C &middot; P
                      </code>
                      ), and climate/moisture inputs pull from NASA POWER, SMAP, IMERG, and Eurostat
                      crop prices.
                    </p>
                    <p className="font-medium text-[#1f1915]">
                      Advisory only — recommendations support and do not replace local agronomist judgment.
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Financial P&L Statement Ledger */}
            <div className="lg:col-span-7 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] overflow-hidden">
              <div className="px-5 py-3.5 border-b border-[#e7e5e0] flex items-center justify-between">
                <div>
                  <h2 className="font-serif text-base font-semibold">
                    Annual Profit &amp; Loss Ledger (per ha)
                  </h2>
                  <p className="text-[11px] font-mono text-[#6b675f]">
                    {String(activeStrategy.name)} · Plot total ({areaHa.toFixed(2)} ha): €
                    {Math.round(netMarginHa * areaHa).toLocaleString()}
                  </p>
                </div>
                <Sprout className="h-4 w-4 text-[#20808d]" />
              </div>

              <table className="w-full text-xs">
                <tbody className="divide-y divide-[#e7e5e0] tabular-nums">
                  <tr className="bg-[#faf9f5]">
                    <td className="px-5 py-3 font-medium">
                      Gross Harvest Revenue ({Number(activeStrategy.yield_t_ha ?? 9.0)} t/ha × €
                      {Number(activeStrategy.price_eur_t ?? 230)}/t)
                    </td>
                    <td className="px-5 py-3 text-right font-mono font-semibold text-emerald-700">
                      +€{grossRevenue.toFixed(0)}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-5 py-2.5 text-[#6b675f]">Water &amp; Irrigation Cost</td>
                    <td className="px-5 py-2.5 text-right font-mono">−€{waterCost.toFixed(0)}</td>
                  </tr>
                  <tr>
                    <td className="px-5 py-2.5 text-[#6b675f]">Electricity &amp; Pumping/Heating</td>
                    <td className="px-5 py-2.5 text-right font-mono">−€{energyCost.toFixed(0)}</td>
                  </tr>
                  <tr>
                    <td className="px-5 py-2.5 text-[#6b675f]">Worker &amp; Field Labor (editable)</td>
                    <td className="px-5 py-2 text-right">
                      <Input
                        type="number"
                        value={workerCost}
                        onChange={(e) => setWorkerCost(Number(e.target.value) || 0)}
                        className="h-7 w-24 ml-auto text-right font-mono text-xs"
                      />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-5 py-2.5 text-[#6b675f]">Transportation Cost (editable)</td>
                    <td className="px-5 py-2 text-right">
                      <Input
                        type="number"
                        value={transportCost}
                        onChange={(e) => setTransportCost(Number(e.target.value) || 0)}
                        className="h-7 w-24 ml-auto text-right font-mono text-xs"
                      />
                    </td>
                  </tr>
                  <tr className="bg-[#faf9f5] font-semibold">
                    <td className="px-5 py-3.5 text-sm">Projected Net Margin (€/ha/yr)</td>
                    <td
                      className={`px-5 py-3.5 text-right font-mono text-base ${
                        netMarginHa >= 0 ? "text-[#20808d]" : "text-rose-700"
                      }`}
                    >
                      €{netMarginHa.toFixed(0)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 3: DEVICES & LIVE TELEMETRY */}
        {tab === "devices" && (
          <div className="space-y-6">
            {/* Pair Device Bar */}
            <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 flex flex-wrap items-center justify-between gap-4">
              {!pairedDeviceId ? (
                <form onSubmit={handlePairDevice} className="flex flex-wrap items-center gap-2.5 w-full">
                  <Cpu className="h-4 w-4 text-[#20808d]" />
                  <span className="text-xs font-medium">Pair ESP32 Field Sensor:</span>
                  <Input
                    value={deviceCodeInput}
                    onChange={(e) => setDeviceCodeInput(e.target.value)}
                    placeholder="Enter device code (e.g. ESP32-TURIN-01)"
                    className="h-8 max-w-xs text-xs font-mono"
                  />
                  <Button type="submit" size="sm" className="h-8 text-xs">
                    Connect Sensor
                  </Button>
                </form>
              ) : (
                <>
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center gap-1.5 font-mono text-xs font-semibold">
                      <Wifi className="h-3.5 w-3.5 text-emerald-600" />
                      {pairedDeviceId}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[11px] font-semibold ${sensorStatus.tone}`}
                    >
                      <span className={`h-2 w-2 rounded-full ${sensorStatus.dot}`} />
                      {sensorStatus.label}
                    </span>
                    <span className="text-[11px] font-mono text-[#6b675f]">
                      {livePolling ? "LIVE · 2s" : "PAUSED"}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={simulateProbeDip}
                    >
                      Test Probe Dip
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={() => setLivePolling((v) => !v)}
                    >
                      {livePolling ? "Pause" : "Resume"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-rose-700"
                      onClick={() => {
                        setPairedDeviceId(null);
                        window.localStorage.removeItem(`paired_device_${plotId}`);
                      }}
                    >
                      Unpair
                    </Button>
                  </div>
                </>
              )}
            </div>

            {/* Instrument Readout Strip + Single Live Trace */}
            <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e7e5e0] pb-3 font-mono tabular-nums">
                <div className="flex flex-wrap items-center gap-6 text-sm">
                  <span>
                    <strong className="text-[11px] text-[#6b675f] font-normal block">SOIL MOISTURE</strong>
                    <span className="text-lg font-semibold text-[#20808d]">
                      {latestReading.moisture.toFixed(1)}%
                    </span>
                  </span>
                  <span>
                    <strong className="text-[11px] text-[#6b675f] font-normal block">AIR HUMIDITY</strong>
                    <span className="text-lg font-semibold text-[#1f1915]">
                      {latestReading.humidity}%
                    </span>
                  </span>
                  <span>
                    <strong className="text-[11px] text-[#6b675f] font-normal block">TEMPERATURE</strong>
                    <span className="text-lg font-semibold text-[#d97706]">
                      {latestReading.tempC.toFixed(1)}°C
                    </span>
                  </span>
                </div>

                <div className="flex items-center gap-2 text-xs text-[#6b675f]">
                  {latestReading.moisture >= 30 ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                  )}
                  <span>
                    NASA SMAP Baseline: 33.0% · Delta{" "}
                    {(latestReading.moisture - 33.0 >= 0 ? "+" : "") +
                      (latestReading.moisture - 33.0).toFixed(1)}
                    %
                  </span>
                </div>
              </div>

              {/* Single Multi-Trace Live SVG */}
              <svg viewBox="0 0 720 160" className="w-full h-40">
                {[0, 25, 50, 75, 100].map((v) => {
                  const y = 140 - (v / 100) * 120;
                  return (
                    <g key={v}>
                      <line x1={32} y1={y} x2={705} y2={y} stroke="#e7e5e0" strokeWidth={1} />
                      <text x={26} y={y + 3} textAnchor="end" className="fill-[#6b675f] font-mono text-[9px]">
                        {v}
                      </text>
                    </g>
                  );
                })}
                <path
                  d={readings
                    .map((r, i) => {
                      const x = 36 + (i / Math.max(1, readings.length - 1)) * 665;
                      const y = 140 - (r.moisture / 100) * 120;
                      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
                    })
                    .join(" ")}
                  fill="none"
                  stroke="#20808d"
                  strokeWidth={2.2}
                />
                <path
                  d={readings
                    .map((r, i) => {
                      const x = 36 + (i / Math.max(1, readings.length - 1)) * 665;
                      const y = 140 - (r.humidity / 100) * 120;
                      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
                    })
                    .join(" ")}
                  fill="none"
                  stroke="#6b675f"
                  strokeWidth={1.4}
                  strokeDasharray="4 3"
                />
              </svg>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
