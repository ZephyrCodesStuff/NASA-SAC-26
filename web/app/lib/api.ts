export const WEB_API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "/api"
).replace(/\/$/, "");

export interface ApiUser {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: "farm_admin" | "viewer";
  is_demo?: boolean;
  token?: string | null;
}

export interface FarmRecord {
  id: string;
  name: string;
  owner: string;
  is_public_demo?: boolean;
  constraints?: Record<string, unknown>;
}

export interface PlotRecord {
  id: string;
  farm: string;
  label: string;
  cadastral_ref?: string;
  area_ha?: number;
  centroid?: { lat: number; lon: number };
  geometry?: Record<string, unknown>;
  sub_plots?: Array<Record<string, unknown>>;
  soil_override?: Record<string, unknown>;
  overridden_fields?: string[];
  baseline_rotation?: string[];
  worldcover_class?: number;
  worldcover_label?: string;
  nasa_snapshot?: Record<string, unknown>;
  active_plan?: Record<string, unknown>;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${WEB_API_URL}${path}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface DeviceReadingRecord {
  device_id: string;
  ts: string;
  soil_moisture: number;
  humidity: number;
  temperature: number;
}

export interface DeviceRecord {
  device_id: string;
  farm_id: string;
  plot_id: string;
  name?: string;
  last_seen?: string;
  latest_reading?: DeviceReadingRecord;
}

/** One data-api dataset entry (see docs/data-catalog.md for every field). */
export interface DatasetResult {
  status: "ok" | "no_data" | "error" | "timeout" | "unavailable";
  scale?: string;
  resolution_m?: number | null;
  source?: string;
  date?: string;
  values?: Record<string, unknown>;
  units?: Record<string, string>;
  history?: unknown;
  periods?: Array<Record<string, unknown>>;
  note?: string;
  error?: string;
}

export interface PlotDataResponse {
  parcel?: Record<string, unknown>;
  datasets: Record<string, DatasetResult>;
  timings_s?: Record<string, number>;
}

export interface ImageryLegend {
  min: number | null;
  max: number | null;
  unit?: string;
  ramp?: string;
  parcel_mean?: number | null;
}

export interface ImageryGroup {
  status: string;
  source?: string;
  date?: string;
  sensor?: string;
  scene?: string;
  bounds?: [[number, number], [number, number]];
  pixel_size_m?: number;
  legends?: Record<string, ImageryLegend>;
  layers?: Record<string, string>;
  note?: string;
  error?: string;
}

export interface ImageryResponse {
  groups: Record<string, ImageryGroup>;
  descriptions?: Record<string, string>;
  ramps?: Record<string, Array<[number, number[]]>>;
}

export interface MapLayer {
  group: string;
  description: string;
  gibs_layer: string;
  url: string;
  default_time: string | null;
  max_native_zoom: number;
  legend_url?: string | null;
  attribution?: string;
}

export const webApi = {
  health: () => apiFetch<{ status: string; pb_url: string; data_api_url: string }>("/health"),
  login: (email: string, password: string) =>
    apiFetch<{ user: ApiUser; token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, name: string, password: string, role: "farm_admin" | "viewer") =>
    apiFetch<{ user: ApiUser; token: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, name, password, role }),
    }),
  me: (token: string) => apiFetch<{ user: ApiUser }>("/auth/me", {}, token),
  listFarms: (token: string) => apiFetch<{ farms: FarmRecord[] }>("/farms", {}, token),
  createFarm: (name: string, token: string, constraints: Record<string, unknown> = {}) =>
    apiFetch<{ farm: FarmRecord }>(
      "/farms",
      { method: "POST", body: JSON.stringify({ name, constraints }) },
      token
    ),
  deleteFarm: (farmId: string, token: string) =>
    apiFetch<{ deleted: boolean; deleted_plots?: number }>(`/farms/${farmId}`, { method: "DELETE" }, token),
  listPlots: (farmId: string, token: string) =>
    apiFetch<{ plots: PlotRecord[] }>(`/farms/${farmId}/plots`, {}, token),
  createPlot: (
    farmId: string,
    payload: {
      features: Array<Record<string, unknown>>;
      label?: string;
      crop?: string;
      use_catasto_names?: boolean;
    },
    token: string
  ) =>
    apiFetch<{ plot: PlotRecord }>(
      `/farms/${farmId}/plots`,
      { method: "POST", body: JSON.stringify(payload) },
      token
    ),
  deletePlot: (plotId: string, token: string) =>
    apiFetch<{ deleted: boolean }>(`/plots/${plotId}`, { method: "DELETE" }, token),
  catastoDiscover: (
    geometry: Record<string, unknown>,
    centroid: number[] | undefined,
    token: string
  ) =>
    apiFetch<{ parcels: Array<Record<string, unknown>> }>(
      "/catasto/discover",
      { method: "POST", body: JSON.stringify({ geometry, centroid }) },
      token
    ),
  getPlot: (plotId: string, token: string) =>
    apiFetch<{ plot: PlotRecord; farm: FarmRecord; is_owner: boolean; bounds: number[][] | null }>(
      `/plots/${plotId}`,
      {},
      token
    ),
  updatePlot: (plotId: string, patch: Record<string, unknown>, token: string) =>
    apiFetch<{ plot: PlotRecord }>(`/plots/${plotId}`, { method: "PATCH", body: JSON.stringify(patch) }, token),
  refreshTelemetry: (plotId: string, token: string) =>
    apiFetch<{ nasa_snapshot: Record<string, unknown> }>(
      `/plots/${plotId}/telemetry/refresh`,
      { method: "POST" },
      token
    ),
  getAnalysisPayload: (plotId: string, token: string) =>
    apiFetch<Record<string, unknown>>(`/plots/${plotId}/analysis-payload`, {}, token),
  getPlotData: (plotId: string, datasets: string, token: string, opts: { year?: boolean; history?: boolean; start?: string; end?: string } = {}) =>
    apiFetch<PlotDataResponse>(
      `/plots/${plotId}/data?datasets=${encodeURIComponent(datasets)}` +
        (opts.year ? "&year=true" : "") +
        (opts.history ? "&history=true" : "") +
        (opts.start ? `&start=${opts.start}` : "") +
        (opts.end ? `&end=${opts.end}` : ""),
      {},
      token
    ),
  getPlotImagery: (plotId: string, token: string, opts: { groups?: string; date?: string } = {}) =>
    apiFetch<ImageryResponse>(
      `/plots/${plotId}/imagery?` +
        new URLSearchParams(Object.entries(opts).filter(([, v]) => !!v) as [string, string][]).toString(),
      {},
      token
    ),
  getMapLayers: (token: string) => apiFetch<{ layers: Record<string, MapLayer>; usage?: string }>("/layers", {}, token),
  listPlotDevices: (plotId: string) =>
    apiFetch<{ devices: DeviceRecord[] }>(`/plots/${plotId}/devices`),
  claimPlotDevice: (
    plotId: string,
    payload: { serial_number: string; name?: string },
    token: string
  ) =>
    apiFetch<{ status: string; device: DeviceRecord }>(
      `/plots/${plotId}/devices`,
      { method: "POST", body: JSON.stringify(payload) },
      token
    ),
  unclaimPlotDevice: (plotId: string, serialNumber: string, token: string) =>
    apiFetch<{ removed: boolean }>(
      `/plots/${plotId}/devices/${encodeURIComponent(serialNumber)}`,
      { method: "DELETE" },
      token
    ),
  getDeviceReadings: (serialNumber: string, limit = 60) =>
    apiFetch<{ device: DeviceRecord | null; readings: DeviceReadingRecord[] }>(
      `/devices/${encodeURIComponent(serialNumber)}/readings?limit=${limit}`
    ),
  ingestDeviceReading: (
    serialNumber: string,
    payload: { soil_moisture: number; humidity: number; temperature: number }
  ) =>
    apiFetch<{ ok: boolean; reading: DeviceReadingRecord }>("/devices/ingest", {
      method: "POST",
      headers: { "X-NASA-Board-SN": serialNumber },
      body: JSON.stringify(payload),
    }),
};
