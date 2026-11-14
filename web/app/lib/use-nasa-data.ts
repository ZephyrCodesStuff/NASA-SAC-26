"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DatasetResult, webApi } from "@/lib/api";

/** Every data-api dataset the visualizer shows, and how to ask for it. One request each, in parallel,
 * so fast sources (weather, soil, prices) render while slow ones (crop history, projections) still load. */
export const NASA_DATASETS: Array<{ name: string; year?: boolean; history?: boolean }> = [
  { name: "weather", year: true }, // 24 half-month periods for the seasonal chart
  { name: "soil" },
  { name: "terrain" },
  { name: "groundwater" },
  { name: "market_prices" },
  { name: "local_prices" },
  { name: "regional_production" },
  { name: "crop_health" },
  { name: "soil_moisture" },
  { name: "rainfall" },
  { name: "evapotranspiration_field" },
  { name: "evapotranspiration_area" },
  { name: "erosion" },
  { name: "crop_history" },
  { name: "climate_projection" },
];

export interface DatasetState {
  state: "loading" | "ok" | "error";
  data?: DatasetResult;
  error?: string;
  seconds?: number;
  gen?: number;
}

export function useNasaData(plotId: string, token: string | null | undefined) {
  const [datasets, setDatasets] = useState<Record<string, DatasetState>>({});
  const generation = useRef(0);

  const load = useCallback(() => {
    if (!token) return;
    const gen = ++generation.current;
    // No synchronous reset: datasets without an entry (or from an older generation) read as "loading"
    for (const d of NASA_DATASETS) {
      const t0 = performance.now();
      webApi
        .getPlotData(plotId, d.name, token, { year: d.year, history: d.history })
        .then((res) => {
          if (gen !== generation.current) return;
          const data = res.datasets?.[d.name];
          setDatasets((prev) => ({
            ...prev,
            [d.name]: data
              ? { state: "ok", data, seconds: (performance.now() - t0) / 1000, gen }
              : { state: "error", error: "No data returned", gen },
          }));
        })
        .catch((err: unknown) => {
          if (gen !== generation.current) return;
          setDatasets((prev) => ({
            ...prev,
            [d.name]: { state: "error", error: err instanceof Error ? err.message : String(err), gen },
          }));
        });
    }
  }, [plotId, token]);

  useEffect(() => {
    load();
  }, [load]);

  const loaded = NASA_DATASETS.filter((d) => datasets[d.name] && datasets[d.name].state !== "loading").length;
  const view: Record<string, DatasetState> = Object.fromEntries(
    NASA_DATASETS.map((d) => [d.name, datasets[d.name] ?? { state: "loading" as const }])
  );
  return { datasets: view, reload: load, loaded, total: NASA_DATASETS.length };
}

// ---------------------------------------------------------------- safe accessors for loose JSON
export function pick(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const key of path.split(".")) {
    if (cur === null || cur === undefined || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[key];
  }
  return cur;
}

export function num(obj: unknown, path?: string): number | null {
  const v = path ? pick(obj, path) : obj;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function str(obj: unknown, path?: string): string | null {
  const v = path ? pick(obj, path) : obj;
  return typeof v === "string" ? v : null;
}

export function fmt(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}${unit}`;
}

/** Values of an ok dataset, or undefined while loading / on error / no data. */
export function okValues(ds: DatasetState | undefined): Record<string, unknown> | undefined {
  return ds?.state === "ok" && ds.data?.status === "ok" ? ds.data.values : undefined;
}
