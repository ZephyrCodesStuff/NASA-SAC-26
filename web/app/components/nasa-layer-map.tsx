"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ChevronDown, ChevronUp, Info, Layers, Loader2 } from "lucide-react";
import { ImageryResponse, MapLayer, webApi } from "@/lib/api";

interface NasaLayerMapProps {
  plotId: string;
  token: string;
  geometry?: Record<string, unknown>;
  centroid?: { lat: number; lon: number };
}

interface ViewDef {
  key: string;
  group: "hls" | "lst" | "dem";
  label: string;
  explain: string;
}

// Field views from data-api /imagery, grouped by the question a farmer is asking
const VIEW_THEMES: Array<{ theme: string; views: ViewDef[] }> = [
  {
    theme: "Look",
    views: [
      { key: "true_color", group: "hls", label: "Photo", explain: "What the field looks like from space (30 m pixels)." },
      { key: "color_infrared", group: "hls", label: "Infrared", explain: "Healthy plants glow red; bare soil is grey or brown; water is black." },
    ],
  },
  {
    theme: "Plant health",
    views: [
      { key: "ndvi", group: "hls", label: "Vigour (NDVI)", explain: "Green = lush, growing crop. Yellow/brown = sparse, stressed or bare soil." },
      { key: "ndre", group: "hls", label: "Nitrogen (NDRE)", explain: "Leaf chlorophyll and nitrogen status. Only on Sentinel-2 days." },
      { key: "agriculture", group: "hls", label: "Crop vs soil", explain: "Crops show green, bare or tilled soil magenta: good for spotting gaps." },
    ],
  },
  {
    theme: "Water",
    views: [
      { key: "ndmi", group: "hls", label: "Moisture (NDMI)", explain: "Water in leaves and topsoil: teal = wet, brown = dry." },
      { key: "swir_moisture", group: "hls", label: "Wet soil", explain: "Dark = wet or irrigated soil, bright = dry soil." },
    ],
  },
  {
    theme: "Heat",
    views: [
      { key: "lst", group: "lst", label: "Surface temp", explain: "Midday ground/canopy temperature (ECOSTRESS, 70 m). Hot spots = drier or stressed." },
      { key: "thermal", group: "hls", label: "Thermal", explain: "Landsat thermal band. Only on Landsat days." },
    ],
  },
  {
    theme: "Terrain",
    views: [
      { key: "elevation", group: "dem", label: "Elevation", explain: "Height above sea level, stretched over this view (blue = low, red = high)." },
      { key: "slope", group: "dem", label: "Slope", explain: "Steepness: light = flat, dark blue = 15° or more." },
      { key: "hillshade", group: "dem", label: "Relief", explain: "Shaded relief, as if lit from the north-west." },
    ],
  },
];
const ALL_VIEWS = VIEW_THEMES.flatMap((t) => t.views);

// Short, plain names for the NASA GIBS regional layers
const TILE_LABELS: Record<string, string> = {
  precipitation: "Rain (today)",
  soil_moisture_rootzone: "Soil moisture",
  surface_water: "Surface water",
  groundwater_anomaly: "Groundwater",
  ndvi_modis_16day: "Vegetation (16-day)",
  ndvi_viirs_8day: "Vegetation (8-day)",
  leaf_area_index: "Leaf area",
  land_surface_temp_day: "Land temperature",
  shaded_relief_color: "Relief (colour)",
  shaded_relief_grey: "Relief (grey)",
  true_color_hls_sentinel2: "Photo · Sentinel-2",
  true_color_hls_landsat: "Photo · Landsat",
  true_color_modis: "Photo · daily",
  false_color_modis_721: "Vegetation/burn (7-2-1)",
};

function rampCss(ramp?: Array<[number, number[]]>): string {
  if (!ramp?.length) return "linear-gradient(90deg,#000,#fff)";
  return `linear-gradient(90deg,${ramp.map(([p, c]) => `rgb(${c.join(",")}) ${Math.round(p * 100)}%`).join(",")})`;
}

export function NasaLayerMap({ plotId, token, geometry, centroid }: NasaLayerMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const imageLayerRef = useRef<L.ImageOverlay | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);

  const [imagery, setImagery] = useState<ImageryResponse | null>(null);
  const [imageryError, setImageryError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Record<string, MapLayer>>({});
  const [view, setView] = useState<string>("ndvi");
  const [tile, setTile] = useState<string>("");
  const [opacity, setOpacity] = useState(0.85);
  const [showRegional, setShowRegional] = useState(false);

  // Base map + plot outline
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: centroid ? [centroid.lat, centroid.lon] : [45.07, 7.68],
      zoom: 15,
      zoomControl: true,
      attributionControl: true,
    });
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 20,
      maxNativeZoom: 18,
      attribution: "Esri World Imagery",
    }).addTo(map);
    map.createPane("outline");
    map.getPane("outline")!.style.zIndex = "650";
    if (geometry) {
      try {
        const outline = L.geoJSON(geometry as unknown as GeoJSON.GeoJsonObject, {
          pane: "outline",
          style: { color: "#ffffff", weight: 2, fill: false },
        }).addTo(map);
        const b = outline.getBounds();
        if (b.isValid()) map.fitBounds(b, { padding: [40, 40], maxZoom: 17, animate: false });
      } catch {
        // keep centroid view
      }
    }
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize({ animate: false }));
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      imageLayerRef.current = null;
      tileLayerRef.current = null;
    };
  }, [geometry, centroid]);

  // Field imagery + regional layer catalogue
  useEffect(() => {
    let cancelled = false;
    const loadImagery = (attempt: number) =>
      webApi
        .getPlotImagery(plotId, token)
        .then((res) => !cancelled && setImagery(res))
        .catch((err: unknown) => {
          // Cloudflare cuts requests at 100 s; data-api keeps rendering and caches, so retry a few times
          if (!cancelled && attempt < 3) setTimeout(() => loadImagery(attempt + 1), 8000 * (attempt + 1));
          else if (!cancelled) setImageryError(err instanceof Error ? err.message : String(err));
        });
    loadImagery(0);
    webApi
      .getMapLayers(token)
      .then((res) => !cancelled && setLayers(res.layers || {}))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [plotId, token]);

  const viewDef = useMemo(() => ALL_VIEWS.find((v) => v.key === view), [view]);
  const group = viewDef ? imagery?.groups?.[viewDef.group] : undefined;
  const uri = group?.layers?.[view];
  const legend = group?.legends?.[view];

  // Field image overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    imageLayerRef.current?.remove();
    imageLayerRef.current = null;
    if (uri && group?.bounds) {
      imageLayerRef.current = L.imageOverlay(uri, group.bounds, { opacity, zIndex: 400 }).addTo(map);
    }
  }, [uri, group?.bounds, opacity]);

  // One regional NASA layer at a time (under the field image)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    tileLayerRef.current?.remove();
    tileLayerRef.current = null;
    const meta = tile ? layers[tile] : undefined;
    if (meta) {
      tileLayerRef.current = L.tileLayer(meta.url.replace("{time}", meta.default_time || ""), {
        maxNativeZoom: meta.max_native_zoom,
        maxZoom: 20,
        opacity: 0.75,
        zIndex: 300,
        attribution: meta.attribution,
      }).addTo(map);
    }
  }, [tile, layers]);

  const tileMeta = tile ? layers[tile] : undefined;
  const available = (v: ViewDef) => !!imagery?.groups?.[v.group]?.layers?.[v.key];
  const dateOf = (g: string) => {
    const x = imagery?.groups?.[g];
    return x?.status === "ok" ? `${x.date?.slice(0, 10)}${x.sensor ? ` · ${x.sensor}` : ""}` : null;
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      {/* Map */}
      <div className="lg:col-span-8 relative h-[480px] rounded-xl overflow-hidden border border-[#e7e5e0] bg-[#1f1915]">
        <div ref={containerRef} className="h-full w-full" />
        {!imagery && !imageryError && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] rounded-full bg-black/70 px-3 py-1 text-[11px] text-white flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" /> Getting the latest satellite images of your field…
          </div>
        )}
        {viewDef && uri && (
          <div className="absolute top-3 left-14 z-[1000] rounded-lg bg-black/70 px-3 py-1.5 text-white max-w-[70%]">
            <p className="text-xs font-semibold">{viewDef.label}</p>
            <p className="text-[10px] text-white/75">
              {viewDef.group === "dem" ? "Terrain model" : `Captured ${dateOf(viewDef.group)}`}
            </p>
          </div>
        )}
        {legend && (
          <div className="absolute bottom-3 left-3 z-[1000] rounded-lg bg-black/70 px-3 py-2 text-[10px] text-white space-y-1 w-[220px]">
            <div className="h-2 rounded-full" style={{ background: rampCss(imagery?.ramps?.[legend.ramp || ""]) }} />
            <div className="flex justify-between font-mono">
              <span>{legend.min}</span>
              {legend.parcel_mean !== null && legend.parcel_mean !== undefined && (
                <span className="font-semibold">your field: {legend.parcel_mean}</span>
              )}
              <span>
                {legend.max}
                {legend.unit ? ` ${legend.unit}` : ""}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="lg:col-span-4 space-y-3 text-xs">
        <div className="rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="font-serif text-base font-semibold">Look at your field</p>
            <label className="flex items-center gap-1.5 text-[10px] text-[#6b675f]" title="Overlay opacity">
              <span>opacity</span>
              <input
                type="range"
                min={0.2}
                max={1}
                step={0.05}
                value={opacity}
                onChange={(e) => setOpacity(Number(e.target.value))}
                className="w-16 accent-[#20808d]"
              />
            </label>
          </div>
          {imageryError && <p className="text-rose-700">Images unavailable: {imageryError}</p>}
          {VIEW_THEMES.map((t) => (
            <div key={t.theme} className="space-y-1">
              <p className="text-[10px] uppercase tracking-wider text-[#6b675f]">{t.theme}</p>
              <div className="flex flex-wrap gap-1.5">
                {t.views.map((v) => {
                  const ok = available(v);
                  const active = view === v.key;
                  return (
                    <button
                      key={v.key}
                      type="button"
                      disabled={!ok}
                      onClick={() => setView(active ? "" : v.key)}
                      title={ok ? v.explain : "Not available for this field / date"}
                      className={`inline-flex items-center gap-1.5 rounded-full border pl-1 pr-2.5 py-0.5 transition ${
                        active
                          ? "border-[#20808d] bg-[#20808d] text-white"
                          : "border-[#e7e5e0] bg-white hover:border-[#20808d]"
                      } disabled:opacity-35 disabled:cursor-not-allowed`}
                    >
                      {ok ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={imagery!.groups[v.group].layers![v.key]} alt="" className="h-5 w-5 rounded-full object-cover" />
                      ) : (
                        <span className="h-5 w-5 rounded-full bg-[#f0eee8]" />
                      )}
                      {v.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          {viewDef && (
            <div className="flex gap-2 rounded-lg bg-[#20808d]/8 border border-[#20808d]/20 p-2.5 text-[11px] text-[#1f1915]">
              <Info className="h-3.5 w-3.5 shrink-0 text-[#20808d] mt-0.5" />
              <span>{viewDef.explain}</span>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-[#e7e5e0] bg-[#fdfbfa]">
          <button
            type="button"
            onClick={() => setShowRegional((v) => !v)}
            className="w-full px-4 py-3 flex items-center justify-between"
          >
            <span className="flex items-center gap-2 font-medium">
              <Layers className="h-3.5 w-3.5 text-[#20808d]" />
              Regional NASA layers
              {tileMeta && <span className="text-[#20808d]">· {TILE_LABELS[tile] || tile}</span>}
            </span>
            {showRegional ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {showRegional && (
            <div className="px-4 pb-4 space-y-2 border-t border-[#e7e5e0] pt-3">
              <p className="text-[11px] text-[#6b675f]">Wider-area context behind your field, from NASA GIBS. Zoom out to see it.</p>
              <div className="flex flex-wrap gap-1.5">
                {["", ...Object.keys(layers)].map((k) => (
                  <button
                    key={k || "none"}
                    type="button"
                    onClick={() => setTile(k)}
                    title={k ? layers[k].description : "No regional layer"}
                    className={`rounded-full border px-2.5 py-0.5 transition ${
                      tile === k ? "border-[#20808d] bg-[#20808d] text-white" : "border-[#e7e5e0] bg-white hover:border-[#20808d]"
                    }`}
                  >
                    {k ? TILE_LABELS[k] || k : "None"}
                  </button>
                ))}
              </div>
              {tileMeta && (
                <div className="text-[11px] text-[#6b675f] space-y-1">
                  <p>
                    {tileMeta.description}
                    {tileMeta.default_time ? ` · ${tileMeta.default_time}` : ""}
                  </p>
                  {tileMeta.legend_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={tileMeta.legend_url} alt="legend" className="max-h-10 bg-white rounded" />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
