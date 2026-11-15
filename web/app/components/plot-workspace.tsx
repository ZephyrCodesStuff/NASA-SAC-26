"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
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
  Map,
  Droplets,
  Coins,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { PeriodChart, PeriodPoint } from "@/components/period-chart";
import { DeviceReadingRecord, DeviceRecord, FarmRecord, PlotRecord, webApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  FieldAndMapSections,
  MarketsAndCostsSections,
  WaterSoilClimateSections,
} from "@/components/nasa-data-panel";
import { ProjectionPlanPanel, ThreeYearPlanResponse } from "@/components/projection-plan-panel";
import { CropPreferences, CropPreferencesCard, readCropPreferences } from "@/components/crop-preferences-card";
import { fmt, num, okValues, pick, str, useNasaData } from "@/lib/use-nasa-data";


const PlotSatelliteThumb = dynamic(
  () => import("@/components/plot-satellite-thumb").then((m) => m.PlotSatelliteThumb),
  {
    ssr: false,
    loading: () => (
      <div className="h-[132px] w-[220px] shrink-0 rounded-md border border-[#e7e5e0] bg-[#f5f4ef] animate-pulse" />
    ),
  }
);

type TabKey = "field" | "climate" | "rotation" | "markets";

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

// Build 24-period series only when cached nasa_snapshot actually contains monthly_precip_mm
function build24PeriodSeries(nasaSnapshot?: Record<string, unknown>): PeriodPoint[] | null {
  const datasets = (nasaSnapshot?.datasets || nasaSnapshot || {}) as Record<string, unknown>;
  const power = (datasets.power || {}) as Record<string, unknown>;
  const monthlyPrecip = Array.isArray(power.monthly_precip_mm) ? (power.monthly_precip_mm as number[]) : null;
  const monthlyTemp = Array.isArray(power.monthly_temp_c) ? (power.monthly_temp_c as number[]) : null;
  if (!monthlyPrecip || monthlyPrecip.length < 12) return null;

  return PERIOD_LABELS.map((label, idx) => {
    const m = Math.floor(idx / 2);
    const pMonth = monthlyPrecip[m] ?? 0;
    const tMonth = monthlyTemp?.[m] ?? 12;
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

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Real last-12-months series from data-api weather `periods` (NASA POWER, 24 half-months)
function realPeriodSeries(periods: Array<Record<string, unknown>> | undefined): PeriodPoint[] | null {
  if (!periods || periods.length < 12) return null;
  return periods.map((p, idx) => {
    const [y, m, half] = String(p.period).split("-");
    const mi = Number(m) - 1;
    const label = `${MONTHS[mi]} ${half === "H1" ? "1–15" : "16–end"} '${y.slice(2)}`;
    return {
      period: idx + 1,
      label,
      precipMm: num(p, "PRECTOTCORR") ?? 0,
      etcMm: num(p, "EVPTRNS") ?? 0,
      tempC: num(p, "T2M") ?? 0,
    };
  });
}

export function PlotWorkspace({ plotId }: { plotId: string }) {
  const { token } = useAuth();
  const nasa = useNasaData(plotId, token);
  const [tab, setTab] = useState<TabKey>("field");
  const tabContainerRef = useRef<HTMLDivElement>(null);
  useGSAP(
    () => {
      if (!tabContainerRef.current) return; // still loading: no tab panel yet
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          ".tab-panel-animate",
          { opacity: 0, y: 8 },
          { opacity: 1, y: 0, duration: 0.24, ease: "power2.out", clearProps: "transform,opacity" }
        );
      });
      return () => mm.revert();
    },
    { scope: tabContainerRef, dependencies: [tab] }
  );
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [plot, setPlot] = useState<PlotRecord | null>(null);
  const [farm, setFarm] = useState<FarmRecord | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [analysisData, setAnalysisData] = useState<Record<string, unknown> | null>(null);

  // Soil & utility overrides editor (empty string = no override, use NASA / baseline)
  const [editingOverrides, setEditingOverrides] = useState(false);
  const [phInput, setPhInput] = useState("");
  const [elecPrice, setElecPrice] = useState("");
  const [waterPrice, setWaterPrice] = useState("");
  const [savingOverrides, setSavingOverrides] = useState(false);
  const [replanning, setReplanning] = useState(false);

  // P&L inline cost inputs (€/ha)
  const [workerCost, setWorkerCost] = useState(420);
  const [transportCost, setTransportCost] = useState(185);
  const [selectedStrategyIdx, setSelectedStrategyIdx] = useState(0);
  const [showSources, setShowSources] = useState(false);

  // Hardware / Devices tab state
  const [deviceCodeInput, setDeviceCodeInput] = useState("");
  const [plotDevices, setPlotDevices] = useState<DeviceRecord[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [livePolling, setLivePolling] = useState(true);
  const [readings, setReadings] = useState<SensorReading[]>([]);

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
      setPhInput(ov.ph !== undefined && ov.ph !== null ? String(ov.ph) : "");
      setElecPrice(
        ov.electricity_price_eur_kwh !== undefined && ov.electricity_price_eur_kwh !== null
          ? String(ov.electricity_price_eur_kwh)
          : ""
      );
      setWaterPrice(
        ov.water_price_eur_m3 !== undefined && ov.water_price_eur_m3 !== null
          ? String(ov.water_price_eur_m3)
          : ""
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load plot");
    } finally {
      setLoading(false);
    }
  }, [plotId, token]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const loadDevices = useCallback(async () => {
    try {
      const res = await webApi.listPlotDevices(plotId);
      setPlotDevices(res.devices);
      setSelectedDeviceId((prev) => {
        if (prev && res.devices.some((d) => d.device_id === prev)) return prev;
        return res.devices[0]?.device_id || null;
      });
    } catch {
      // Ignore transient errors
    }
  }, [plotId]);

  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

  const loadReadings = useCallback(async (deviceId: string) => {
    try {
      const res = await webApi.getDeviceReadings(deviceId, 60);
      setReadings(
        res.readings.map((r: DeviceReadingRecord) => ({
          ts: r.ts.slice(11, 19),
          moisture: r.soil_moisture,
          humidity: r.humidity,
          tempC: r.temperature,
        }))
      );
    } catch {
      // Ignore transient errors
    }
  }, []);

  // Poll real device readings & device list every 2s when on Devices tab
  useEffect(() => {
    if (!selectedDeviceId) {
      setReadings([]);
      return;
    }
    loadReadings(selectedDeviceId);
    if (!livePolling) return;
    const timer = setInterval(() => {
      loadReadings(selectedDeviceId);
      loadDevices();
    }, 2000);
    return () => clearInterval(timer);
  }, [selectedDeviceId, livePolling, loadReadings, loadDevices]);

  const handleRefreshTelemetry = async () => {
    if (!token) return;
    setRefreshing(true);
    try {
      const res = await webApi.refreshTelemetry(plotId, token);
      setPlot((prev) => (prev ? { ...prev, nasa_snapshot: res.nasa_snapshot } : prev));
      const analysisRes = await webApi.getAnalysisPayload(plotId, token).catch(() => null);
      if (analysisRes) setAnalysisData(analysisRes);
      nasa.reload();
      toast.success("NASA & SoilGrids telemetry refreshed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Telemetry refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const applyOverrides = async (nextOverride: Record<string, unknown>, msg: string) => {
    if (!token || !plot) return;
    setSavingOverrides(true);
    try {
      const res = await webApi.updatePlot(plotId, { soil_override: nextOverride }, token);
      setPlot(res.plot);
      const analysisRes = await webApi.getAnalysisPayload(plotId, token).catch(() => null);
      if (analysisRes) setAnalysisData(analysisRes);
      setEditingOverrides(false);
      toast.success(msg);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save overrides");
    } finally {
      setSavingOverrides(false);
    }
  };

  const handleSaveOverrides = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!plot) return;
    const nextOverride: Record<string, unknown> = { ...(plot.soil_override || {}) };

    const applyField = (key: string, raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) {
        delete nextOverride[key];
      } else {
        const num = Number(trimmed);
        if (!Number.isNaN(num)) nextOverride[key] = num;
      }
    };

    applyField("ph", phInput);
    applyField("electricity_price_eur_kwh", elecPrice);
    applyField("water_price_eur_m3", waterPrice);

    await applyOverrides(nextOverride, "Field & utility parameters updated");
  };

  const handleClearAllOverrides = async () => {
    setPhInput("");
    setElecPrice("");
    setWaterPrice("");
    // Keep the farmer's crop choices: they live in soil_override too but are not soil data
    const { crop_whitelist, crop_blacklist } = (plot?.soil_override || {}) as Record<string, unknown>;
    const kept: Record<string, unknown> = {};
    if (crop_whitelist !== undefined) kept.crop_whitelist = crop_whitelist;
    if (crop_blacklist !== undefined) kept.crop_blacklist = crop_blacklist;
    await applyOverrides(kept, "Cleared overrides — reverted to NASA data");
  };

  const handleSaveCropPreferences = async (prefs: CropPreferences) => {
    if (!plot) return;
    const nextOverride: Record<string, unknown> = { ...(plot.soil_override || {}) };
    delete nextOverride.crop_whitelist;
    delete nextOverride.crop_blacklist;
    if (prefs.whitelist.length) nextOverride.crop_whitelist = prefs.whitelist;
    if (prefs.blacklist.length) nextOverride.crop_blacklist = prefs.blacklist;
    setReplanning(true);
    try {
      await applyOverrides(nextOverride, "Crop choices saved — rotation plan updated");
    } finally {
      setReplanning(false);
    }
  };

  const handlePairDevice = async (e: React.FormEvent) => {
    e.preventDefault();
    const sn = deviceCodeInput.trim();
    if (!sn || !plot || !token) return;
    try {
      await webApi.claimPlotDevice(plot.id, { serial_number: sn }, token);
      setDeviceCodeInput("");
      setSelectedDeviceId(sn);
      await loadDevices();
      toast.success(`Added device ${sn} to plot`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add device");
    }
  };

  const handleRemoveDevice = async (sn: string) => {
    if (!plot || !token) return;
    try {
      await webApi.unclaimPlotDevice(plot.id, sn, token);
      if (selectedDeviceId === sn) {
        setSelectedDeviceId(null);
        setReadings([]);
      }
      await loadDevices();
      toast.success(`Removed ${sn} from plot`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove device");
    }
  };

  const simulateProbeDip = async () => {
    if (!selectedDeviceId) return;
    try {
      await webApi.ingestDeviceReading(selectedDeviceId, {
        soil_moisture: 68.4,
        humidity: 79.0,
        temperature: 17.8,
      });
      await loadReadings(selectedDeviceId);
      toast.info("Probe spike ingested (68.4% moisture)");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to post reading");
    }
  };

  const weatherPeriods = nasa.datasets.weather?.data?.periods;
  const realPeriods = useMemo(() => realPeriodSeries(weatherPeriods), [weatherPeriods]);
  const periodPoints = useMemo(
    () => realPeriods ?? build24PeriodSeries(plot?.nasa_snapshot),
    [realPeriods, plot?.nasa_snapshot]
  );

  // Live values for the risk ledger (fall back to the strategy preview while loading)
  const wv = okValues(nasa.datasets.weather);
  const soilDs = okValues(nasa.datasets.soil);
  const topsoil = (soilDs?.["0-5cm"] || {}) as Record<string, unknown>;
  const nasaPh = num(topsoil, "phh2o");
  const localPrices = okValues(nasa.datasets.local_prices);
  const elecSeries = pick(localPrices, "energy.electricity.MWH500-1999.excl_taxes") as
    | Array<Record<string, unknown>>
    | undefined;
  const latestElec = elecSeries?.[elecSeries.length - 1];
  const eurostatElec = latestElec ? num(latestElec, "price") : null;
  const ero = okValues(nasa.datasets.erosion);
  const etf = okValues(nasa.datasets.evapotranspiration_field);
  const eta = okValues(nasa.datasets.evapotranspiration_area);
  const proj = okValues(nasa.datasets.climate_projection);
  const hist = okValues(nasa.datasets.crop_history);
  const weatherLoading = nasa.datasets.weather?.state === "loading";
  const etLoading =
    nasa.datasets.evapotranspiration_field?.state === "loading" &&
    nasa.datasets.evapotranspiration_area?.state === "loading";
  const eroLoading = nasa.datasets.erosion?.state === "loading";
  const projLoading = nasa.datasets.climate_projection?.state === "loading";
  const histLoading = nasa.datasets.crop_history?.state === "loading";

  const esi = num(etf, "esi.mean");
  const etPet = num(eta, "et_pet_ratio");
  const stressIdx = esi ?? etPet;
  const waterStress =
    stressIdx === null ? null : stressIdx < 0.4 ? "High" : stressIdx < 0.7 ? "Moderate" : "Low";
  const erosionNow = num(ero, "soil_loss_current_cover_t_ha_yr");
  const erosionRisk = str(ero, "risk_current_cover");
  const hottest = num(wv, "extremes_last_365_days.hottest_day.t_max_c");
  const frostDays = num(wv, "extremes_last_365_days.frost_days");
  const heatDays = num(wv, "extremes_last_365_days.heat_days_over_35c");
  const droughtRisk = str(proj, "headline");
  const peakDeficit = useMemo(() => {
    if (!realPeriods) return null;
    let worst = realPeriods[0];
    for (const p of realPeriods) if (p.precipMm - p.etcMm < worst.precipMm - worst.etcMm) worst = p;
    return worst;
  }, [realPeriods]);

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

  const latestReading = readings.length > 0 ? readings[readings.length - 1] : null;
  const sensorStatus = !latestReading
    ? { label: "NO DATA", tone: "text-[#6b675f] bg-[#f5f4ef] border-[#e7e5e0]", dot: "bg-[#6b675f]" }
    : latestReading.moisture >= 40
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
                  : "Coordinates pending"}
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
            {phInput
              ? `${phInput} (override)`
              : nasaPh !== null
                ? `${nasaPh.toFixed(1)} (SoilGrids)`
                : nasa.datasets.soil?.state === "loading"
                  ? "Loading…"
                  : "NASA / SoilGrids"}
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">WATER</strong>{" "}
            {waterPrice ? `€${waterPrice}/m³ (override)` : "Regional default"}
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">POWER</strong>{" "}
            {elecPrice
              ? `€${elecPrice}/kWh (override)`
              : eurostatElec !== null
                ? `€${eurostatElec.toFixed(3)}/kWh (Eurostat)`
                : nasa.datasets.local_prices?.state === "loading"
                  ? "Loading…"
                  : "Eurostat default"}
          </span>
          <span className="text-[#e7e5e0]">|</span>
          <span>
            <strong className="text-[#6b675f] font-normal">NASA SNAPSHOT</strong>{" "}
            {nasa.loaded > 0 ? `${nasa.loaded}/${nasa.total} live` : plot.nasa_snapshot ? "Cached" : "Baseline preview"}
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
                placeholder="NASA default"
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1 w-40">
              <label className="text-[11px] font-mono text-[#6b675f]">Water (€/m³)</label>
              <Input
                value={waterPrice}
                onChange={(e) => setWaterPrice(e.target.value)}
                placeholder="Regional default"
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1 w-40">
              <label className="text-[11px] font-mono text-[#6b675f]">Electricity (€/kWh)</label>
              <Input
                value={elecPrice}
                onChange={(e) => setElecPrice(e.target.value)}
                placeholder="Eurostat default"
                className="h-8 text-xs font-mono"
              />
            </div>
            <Button type="submit" size="sm" className="h-8 text-xs" disabled={savingOverrides}>
              {savingOverrides ? "Saving…" : "Save Parameters"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 text-xs text-[#6b675f]"
              disabled={savingOverrides}
              onClick={handleClearAllOverrides}
            >
              Clear All
            </Button>
            <span className="text-[11px] text-[#6b675f]">
              Leave any field blank and save to revert to NASA / regional data.
            </span>
          </form>
        )}

        {/* 4-Tab Navigation */}
        <div className="border-b border-[#e7e5e0] flex items-center gap-6 overflow-x-auto">
          {(
            [
              { key: "field", label: "Field & Map", icon: Map },
              { key: "climate", label: "Water, Soil & Climate", icon: Droplets },
              { key: "rotation", label: "Rotation Plan", icon: Sprout },
              { key: "markets", label: "Markets & Costs", icon: Coins },
            ] as const
          ).map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={`pb-2.5 text-xs font-medium border-b-2 transition inline-flex items-center gap-1.5 whitespace-nowrap ${
                  tab === t.key
                    ? "border-[#20808d] text-[#1f1915]"
                    : "border-transparent text-[#6b675f] hover:text-[#1f1915]"
                }`}
              >
                <Icon className={`h-3.5 w-3.5 ${tab === t.key ? "text-[#20808d]" : "text-[#6b675f]"}`} />
                {t.label}
                {t.key === "field" && plotDevices.length > 0 && (
                  <span
                    title="Live ground sensors connected"
                    className="ml-0.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 align-middle"
                  />
                )}
              </button>
            );
          })}
        </div>

        <div ref={tabContainerRef}>
        {/* TAB 1: FIELD & MAP */}
        {tab === "field" && (
          <div className="tab-panel-animate space-y-8">
            {token && (
              <FieldAndMapSections
                datasets={nasa.datasets}
                plotId={plotId}
                token={token}
                geometry={plot.geometry}
                centroid={plot.centroid}
                loaded={nasa.loaded}
                total={nasa.total}
                onNavigateTab={setTab}
              />
            )}

            {/* Ground Telemetry (Live Sensors) */}
            <section className="space-y-3">
              <div className="flex items-baseline justify-between border-b border-[#e7e5e0] pb-1.5">
                <h2 className="text-[11px] font-mono uppercase tracking-wider text-[#6b675f]">
                  Ground telemetry · ESP32 field sensors
                </h2>
                <span className="text-[10px] font-mono text-[#6b675f]">
                  {plotDevices.length > 0 ? `${plotDevices.length} board(s) paired` : "Optional ground truth"}
                </span>
              </div>
              <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  {isOwner ? (
                    <form onSubmit={handlePairDevice} className="flex flex-wrap items-center gap-2.5">
                      <Cpu className="h-4 w-4 text-[#20808d]" />
                      <span className="text-xs font-medium">Add Board by S/N:</span>
                      <Input
                        value={deviceCodeInput}
                        onChange={(e) => setDeviceCodeInput(e.target.value)}
                        placeholder="Enter serial number"
                        className="h-8 w-52 text-xs font-mono"
                      />
                      <Button type="submit" size="sm" className="h-8 text-xs">
                        Add to Plot
                      </Button>
                    </form>
                  ) : (
                    <span className="text-xs text-[#6b675f] flex items-center gap-2">
                      <Cpu className="h-4 w-4 text-[#20808d]" />
                      Sensors assigned to this plot
                    </span>
                  )}

                  {selectedDeviceId && (
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[11px] font-semibold ${sensorStatus.tone}`}
                      >
                        <span className={`h-2 w-2 rounded-full ${sensorStatus.dot}`} />
                        {sensorStatus.label}
                      </span>
                      <span className="text-[11px] font-mono text-[#6b675f]">
                        {livePolling ? "LIVE · 2s" : "PAUSED"}
                      </span>
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
                    </div>
                  )}
                </div>

                {/* Registered devices selector */}
                <div className="border-t border-[#e7e5e0] pt-3 flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-mono text-[#6b675f] mr-1">
                    PLOT DEVICES ({plotDevices.length}):
                  </span>
                  {plotDevices.length === 0 ? (
                    <span className="text-xs text-[#6b675f]">
                      No boards claimed on this plot yet. Enter the physical board serial number above.
                    </span>
                  ) : (
                    plotDevices.map((d) => {
                      const active = d.device_id === selectedDeviceId;
                      return (
                        <div
                          key={d.device_id}
                          className={`inline-flex items-center rounded-md border text-xs font-mono transition ${
                            active
                              ? "border-[#20808d] bg-[#20808d]/10 text-[#1f1915] font-semibold"
                              : "border-[#e7e5e0] bg-white text-[#6b675f] hover:border-[#20808d]/50"
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => setSelectedDeviceId(d.device_id)}
                            className="inline-flex items-center gap-2 px-2.5 py-1"
                          >
                            <Wifi className={`h-3 w-3 ${active ? "text-emerald-600" : "text-[#6b675f]"}`} />
                            {d.device_id}
                            {d.latest_reading && (
                              <span className="text-[10px] text-[#20808d]">
                                {d.latest_reading.soil_moisture.toFixed(1)}%
                              </span>
                            )}
                          </button>
                          {isOwner && (
                            <button
                              type="button"
                              onClick={() => handleRemoveDevice(d.device_id)}
                              title="Remove device from plot"
                              className="px-1.5 py-1 border-l border-[#e7e5e0] text-[#6b675f] hover:text-rose-700"
                            >
                              &times;
                            </button>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {plotDevices.length > 0 && (
                <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e7e5e0] pb-3 font-mono tabular-nums">
                    <div className="flex flex-wrap items-center gap-6 text-sm">
                      <span>
                        <strong className="text-[11px] text-[#6b675f] font-normal block">SOIL MOISTURE</strong>
                        <span className="text-lg font-semibold text-[#20808d]">
                          {latestReading ? `${latestReading.moisture.toFixed(1)}%` : "—"}
                        </span>
                      </span>
                      <span>
                        <strong className="text-[11px] text-[#6b675f] font-normal block">AIR HUMIDITY</strong>
                        <span className="text-lg font-semibold text-[#1f1915]">
                          {latestReading ? `${latestReading.humidity.toFixed(0)}%` : "—"}
                        </span>
                      </span>
                      <span>
                        <strong className="text-[11px] text-[#6b675f] font-normal block">TEMPERATURE</strong>
                        <span className="text-lg font-semibold text-[#d97706]">
                          {latestReading ? `${latestReading.tempC.toFixed(1)}°C` : "—"}
                        </span>
                      </span>
                    </div>

                    <div className="flex items-center gap-2 text-xs text-[#6b675f]">
                      {latestReading && latestReading.moisture >= 30 ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      ) : (
                        <AlertTriangle className="h-4 w-4 text-amber-600" />
                      )}
                      <span>
                        {latestReading
                          ? `Last reading ${latestReading.ts} UTC`
                          : "Waiting for ESP32 readings…"}
                      </span>
                    </div>
                  </div>

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
                    {readings.length > 1 && (
                      <>
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
                      </>
                    )}
                  </svg>
                </div>
              )}
            </section>
          </div>
        )}

        {/* TAB 2: WATER, SOIL & CLIMATE */}
        {tab === "climate" && (
          <div className="tab-panel-animate space-y-6">
            {/* Editorial Headline + Full-width 24-Period Chart */}
            <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-5 space-y-4">
              <div className="space-y-1">
                <p className="text-[11px] font-mono uppercase tracking-wider text-[#6b675f]">
                  24-Period Seasonal Balance (15-Day Intervals)
                </p>
                <p className="font-serif text-lg font-medium text-[#1f1915]">
                  {peakDeficit
                    ? `Last 12 months: biggest water deficit in ${peakDeficit.label} (P${peakDeficit.period}); `
                    : "Peak water deficit occurs in Jul–Aug (Periods 13–16); "}
                  topsoil erosion{" "}
                  {erosionNow !== null
                    ? `${erosionRisk} at ${erosionNow.toFixed(1)} t/ha/yr with today's cover.`
                    : "estimate pending."}
                </p>
                <p className="text-[11px] font-mono text-[#6b675f]">
                  {realPeriods
                    ? "NASA POWER · last 24 half-months · bars = rain, line = evapotranspiration, dashed = mean temp"
                    : weatherLoading
                      ? "Loading NASA POWER 24-period telemetry…"
                      : periodPoints
                        ? "Cached NASA POWER snapshot · bars = rain, line = evapotranspiration, dashed = mean temp"
                        : "NASA POWER weather data unavailable"}
                </p>
              </div>
              {periodPoints ? (
                <PeriodChart points={periodPoints} />
              ) : weatherLoading ? (
                <div className="h-[240px] w-full rounded-md bg-[#f5f4ef] animate-pulse" />
              ) : (
                <div className="h-[240px] w-full rounded-md border border-dashed border-[#e7e5e0] flex items-center justify-center text-xs text-[#6b675f]">
                  NASA POWER weather series unavailable for this plot.
                </div>
              )}
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
                        {etLoading && !waterStress ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : (
                          <LedgerStatus
                            text={waterStress ?? "Unavailable"}
                            tone={!waterStress ? "neutral" : waterStress === "High" ? "bad" : waterStress === "Low" ? "good" : "warn"}
                          />
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {etLoading && stressIdx === null ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : stressIdx !== null ? (
                          `${esi !== null ? "ESI" : "ET/PET"} ${stressIdx.toFixed(2)}`
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">
                        {weatherLoading && !peakDeficit ? (
                          <span className="inline-block h-3.5 w-28 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : peakDeficit ? (
                          `Worst: ${peakDeficit.label}`
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Topsoil Erosion (RUSLE)</td>
                      <td className="px-4 py-2.5">
                        {eroLoading && !erosionRisk ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : (
                          <LedgerStatus
                            text={erosionRisk ? erosionRisk[0].toUpperCase() + erosionRisk.slice(1) : "Unavailable"}
                            tone={!erosionRisk ? "neutral" : erosionRisk === "low" ? "good" : erosionRisk === "moderate" ? "warn" : "bad"}
                          />
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {eroLoading && erosionNow === null ? (
                          <span className="inline-block h-3.5 w-20 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : erosionNow !== null ? (
                          `${erosionNow.toFixed(1)} t/ha/yr`
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">
                        {eroLoading && !ero ? (
                          <span className="inline-block h-3.5 w-28 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : ero ? (
                          `Slope ${fmt(num(ero, "slope_deg"), 1, "°")} · bare soil ${fmt(num(ero, "soil_loss_bare_t_ha_yr"), 1)} t/ha`
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Extreme Heat / Frost</td>
                      <td className="px-4 py-2.5">
                        {weatherLoading && heatDays === null ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : heatDays !== null ? (
                          <LedgerStatus
                            text={heatDays > 5 ? "High" : "Watch"}
                            tone={heatDays > 5 ? "bad" : "warn"}
                          />
                        ) : (
                          <LedgerStatus text="Unavailable" tone="neutral" />
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {weatherLoading && hottest === null ? (
                          <span className="inline-block h-3.5 w-20 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : hottest !== null ? (
                          `${hottest.toFixed(1)}°C peak`
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">
                        {weatherLoading && heatDays === null ? (
                          <span className="inline-block h-3.5 w-32 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : heatDays !== null ? (
                          `${heatDays} days >35°C · ${frostDays ?? "—"} frost days (12 mo)`
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Greenhouse Requirement</td>
                      <td className="px-4 py-2.5">
                        {weatherLoading && frostDays === null ? (
                          <span className="inline-block h-3.5 w-24 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-emerald-700">
                            <span className="h-2 w-2 rounded-full bg-emerald-500" />
                            Open-field viable
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">Not required</td>
                      <td className="px-4 py-2.5 text-[#6b675f]">
                        {weatherLoading && frostDays === null ? (
                          <span className="inline-block h-3.5 w-28 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : frostDays !== null ? (
                          `${365 - frostDays} frost-free days (12 mo)`
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 font-medium">Drought Risk 2050s (CMIP6)</td>
                      <td className="px-4 py-2.5">
                        {projLoading && !droughtRisk ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : (
                          <LedgerStatus
                            text={droughtRisk ? droughtRisk[0].toUpperCase() + droughtRisk.slice(1) : "Unavailable"}
                            tone={!droughtRisk ? "neutral" : droughtRisk === "low" ? "good" : droughtRisk === "moderate" ? "warn" : "bad"}
                          />
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {projLoading && !proj ? (
                          <span className="inline-block h-3.5 w-16 rounded bg-[#e7e5e0] animate-pulse" />
                        ) : (
                          fmt(num(proj, "projections.ssp245_mid_2050s.water_balance_change_mm"), 0, " mm")
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-[#6b675f]">Water-balance change vs 2000s (SSP2-4.5)</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* 1/3 Local Extreme Weather & Field Eyes */}
              <div className="lg:col-span-4 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
                <h2 className="text-xs font-mono uppercase tracking-wider text-[#6b675f]">
                  12-Month Extremes &amp; Local Eyes
                </h2>
                {weatherLoading && !wv && (
                  <div className="space-y-2 py-2">
                    <div className="h-3 w-36 rounded bg-[#e7e5e0] animate-pulse" />
                    <div className="h-4 w-full rounded bg-[#e7e5e0] animate-pulse" />
                  </div>
                )}
                {wv && (
                  <div className="py-1 space-y-1 text-xs">
                    <p className="font-mono text-[10px] text-[#6b675f]">LAST 12 MONTHS · EXTREMES</p>
                    <p className="text-[#1f1915]">
                      Hottest {fmt(hottest, 1, "°C")} ({str(wv, "extremes_last_365_days.hottest_day.date")}), wettest day{" "}
                      {fmt(num(wv, "extremes_last_365_days.wettest_day.precip_mm"), 0, " mm")}, longest dry spell{" "}
                      {fmt(num(wv, "extremes_last_365_days.longest_dry_spell_days"), 0, " days")}.
                    </p>
                  </div>
                )}
                <div className="divide-y divide-[#e7e5e0] text-xs border-t border-[#e7e5e0]">
                  <div className="py-2 space-y-0.5">
                    <p className="font-mono text-[10px] text-[#6b675f]">LOCAL VERIFICATION</p>
                    <p className="text-[#6b675f]">
                      Confirm well/canal water allocation and topsoil compaction before spring tillage.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <WaterSoilClimateSections datasets={nasa.datasets} />
          </div>
        )}

        {/* TAB 3: ROTATION PLAN */}
        {tab === "rotation" && (
          <div className="tab-panel-animate space-y-6">
            <CropPreferencesCard
              key={JSON.stringify(readCropPreferences(plot.soil_override))}
              saved={readCropPreferences(plot.soil_override)}
              editable={isOwner}
              saving={replanning}
              onSave={handleSaveCropPreferences}
            />
            <ProjectionPlanPanel
              data={(analysisData?.projection as ThreeYearPlanResponse | undefined) ?? null}
              plotName={plot.label}
              loading={loading || replanning}
              onRunProjection={isOwner ? handleRefreshTelemetry : undefined}
            />
          </div>
        )}

        {/* TAB 4: MARKETS & COSTS */}
        {tab === "markets" && (
          <div className="tab-panel-animate space-y-8">
            <MarketsAndCostsSections datasets={nasa.datasets} />

            {/* Farm Cost & Soil Overrides */}
            <section className="space-y-3">
              <div className="flex items-baseline justify-between border-b border-[#e7e5e0] pb-1.5">
                <h2 className="text-[11px] font-mono uppercase tracking-wider text-[#6b675f]">
                  Farm cost &amp; soil overrides
                </h2>
                <span className="text-[10px] font-mono text-[#6b675f]">
                  {isOwner ? "Editable · feeds rotation profit model" : "Read-only"}
                </span>
              </div>
              {isOwner ? (
                <form
                  onSubmit={handleSaveOverrides}
                  className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 flex flex-wrap items-end gap-4"
                >
                  <div className="space-y-1 w-32">
                    <label className="text-[11px] font-mono text-[#6b675f]">Soil pH</label>
                    <Input
                      value={phInput}
                      onChange={(e) => setPhInput(e.target.value)}
                      placeholder="NASA default"
                      className="h-8 text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1 w-40">
                    <label className="text-[11px] font-mono text-[#6b675f]">Water (€/m³)</label>
                    <Input
                      value={waterPrice}
                      onChange={(e) => setWaterPrice(e.target.value)}
                      placeholder="Regional default"
                      className="h-8 text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1 w-40">
                    <label className="text-[11px] font-mono text-[#6b675f]">Electricity (€/kWh)</label>
                    <Input
                      value={elecPrice}
                      onChange={(e) => setElecPrice(e.target.value)}
                      placeholder="Eurostat default"
                      className="h-8 text-xs font-mono"
                    />
                  </div>
                  <Button type="submit" size="sm" className="h-8 text-xs" disabled={savingOverrides}>
                    {savingOverrides ? "Saving…" : "Save Parameters"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 text-xs text-[#6b675f]"
                    disabled={savingOverrides}
                    onClick={handleClearAllOverrides}
                  >
                    Clear All
                  </Button>
                  <span className="text-[11px] text-[#6b675f]">
                    Leave any field blank and save to revert to NASA / regional data.
                  </span>
                </form>
              ) : (
                <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 text-xs text-[#6b675f]">
                  Using regional Eurostat energy defaults and NASA/SoilGrids soil baseline for this plot.
                </div>
              )}
            </section>
          </div>
        )}
        </div>
      </main>
    </div>
  );
}

function LedgerStatus({ text, tone }: { text: string; tone: "good" | "warn" | "bad" | "neutral" }) {
  const cls = {
    good: ["text-emerald-700", "bg-emerald-500"],
    warn: ["text-amber-700", "bg-amber-500"],
    bad: ["text-rose-700", "bg-rose-500"],
    neutral: ["text-[#6b675f]", "bg-[#6b675f]"],
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 ${cls[0]}`}>
      <span className={`h-2 w-2 rounded-full ${cls[1]}`} />
      {text}
    </span>
  );
}
