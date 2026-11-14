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
};
