"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Loader2 } from "lucide-react";
import { ImageryGroup, ImageryResponse, MapLayer, webApi } from "@/lib/api";

interface NasaLayerMapProps {
  plotId: string;
  token: string;
  geometry?: Record<string, unknown>;
  centroid?: { lat: number; lon: number };
}

// Field images returned by data-api /imagery, in display order
const IMAGE_LAYERS: Array<{ key: string; group: string; label: string }> = [
  { key: "true_color", group: "hls", label: "True colour" },
  { key: "color_infrared", group: "hls", label: "Colour infrared" },
  { key: "agriculture", group: "hls", label: "Agriculture (SWIR)" },
  { key: "swir_moisture", group: "hls", label: "SWIR moisture" },
  { key: "ndvi", group: "hls", label: "NDVI (vigour)" },
  { key: "ndmi", group: "hls", label: "NDMI (water)" },
  { key: "ndre", group: "hls", label: "NDRE (nitrogen)" },
  { key: "thermal", group: "hls", label: "Thermal (Landsat)" },
  { key: "lst", group: "lst", label: "Surface temp (ECOSTRESS)" },
  { key: "elevation", group: "dem", label: "Elevation" },
  { key: "hillshade", group: "dem", label: "Hillshade" },
  { key: "slope", group: "dem", label: "Slope" },
];

function rampCss(ramp?: Array<[number, number[]]>): string {
  if (!ramp?.length) return "linear-gradient(90deg,#000,#fff)";
  return `linear-gradient(90deg,${ramp.map(([p, c]) => `rgb(${c.join(",")}) ${Math.round(p * 100)}%`).join(",")})`;
}

export function NasaLayerMap({ plotId, token, geometry, centroid }: NasaLayerMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const imageLayerRef = useRef<L.ImageOverlay | null>(null);
  const tileLayersRef = useRef<Record<string, L.TileLayer>>({});

  const [imagery, setImagery] = useState<ImageryResponse | null>(null);
  const [imageryError, setImageryError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Record<string, MapLayer>>({});
  const [selectedImage, setSelectedImage] = useState<string>("ndvi");
  const [activeTiles, setActiveTiles] = useState<string[]>([]);
  const [opacity, setOpacity] = useState(0.85);

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
      tileLayersRef.current = {};
    };
  }, [geometry, centroid]);

  // Fetch field imagery + GIBS layer catalogue
  useEffect(() => {
    let cancelled = false;
    webApi
      .getPlotImagery(plotId, token)
      .then((res) => !cancelled && setImagery(res))
      .catch((err: unknown) => !cancelled && setImageryError(err instanceof Error ? err.message : String(err)));
    webApi
      .getMapLayers(token)
      .then((res) => !cancelled && setLayers(res.layers || {}))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [plotId, token]);

  const selectedMeta = useMemo(() => IMAGE_LAYERS.find((l) => l.key === selectedImage), [selectedImage]);
  const selectedGroup: ImageryGroup | undefined = selectedMeta ? imagery?.groups?.[selectedMeta.group] : undefined;
  const selectedUri = selectedGroup?.layers?.[selectedImage];
  const legend = selectedGroup?.legends?.[selectedImage];

  // Field image overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    imageLayerRef.current?.remove();
    imageLayerRef.current = null;
    if (selectedUri && selectedGroup?.bounds) {
      imageLayerRef.current = L.imageOverlay(selectedUri, selectedGroup.bounds, { opacity, zIndex: 400 }).addTo(map);
    }
  }, [selectedUri, selectedGroup?.bounds, opacity]);

  // GIBS tile layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const [key, layer] of Object.entries(tileLayersRef.current)) {
      if (!activeTiles.includes(key)) {
        layer.remove();
        delete tileLayersRef.current[key];
      }
    }
    for (const key of activeTiles) {
      const meta = layers[key];
      if (!meta) continue;
      const existing = tileLayersRef.current[key];
      if (existing) {
        existing.setOpacity(opacity);
        continue;
      }
      const url = meta.url.replace("{time}", meta.default_time || "");
      tileLayersRef.current[key] = L.tileLayer(url, {
        maxNativeZoom: meta.max_native_zoom,
        maxZoom: 20,
        opacity,
        zIndex: 300,
        attribution: meta.attribution,
      }).addTo(map);
    }
  }, [activeTiles, layers, opacity]);

  const groupedTiles = useMemo(() => {
    const out: Record<string, Array<[string, MapLayer]>> = {};
    for (const [k, v] of Object.entries(layers)) (out[v.group] ||= []).push([k, v]);
    return out;
  }, [layers]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-8 relative h-[460px] rounded-lg overflow-hidden border border-[#e7e5e0] bg-[#1f1915]">
        <div ref={containerRef} className="h-full w-full" />
        {!imagery && !imageryError && (
          <div className="absolute top-2 left-1/2 -translate-x-1/2 z-[1000] rounded bg-black/70 px-2.5 py-1 text-[11px] font-mono text-white flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" /> Fetching satellite images (first time ~30 s)…
          </div>
        )}
        {legend && (
          <div className="absolute bottom-2 left-2 z-[1000] rounded bg-black/70 px-2.5 py-1.5 text-[10px] font-mono text-white space-y-1 min-w-[180px]">
            <div className="flex justify-between gap-3">
              <span>{selectedMeta?.label}</span>
              {legend.parcel_mean !== null && legend.parcel_mean !== undefined && (
                <span>
                  field avg {legend.parcel_mean}
                  {legend.unit ? ` ${legend.unit}` : ""}
                </span>
              )}
            </div>
            <div className="h-2 rounded" style={{ background: rampCss(imagery?.ramps?.[legend.ramp || ""]) }} />
            <div className="flex justify-between">
              <span>{legend.min}</span>
              <span>{legend.max}{legend.unit ? ` ${legend.unit}` : ""}</span>
            </div>
          </div>
        )}
      </div>

      <div className="lg:col-span-4 space-y-4 text-xs">
        <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-3 space-y-2">
          <p className="font-mono text-[11px] uppercase tracking-wider text-[#6b675f]">Field images</p>
          {imageryError && <p className="text-rose-700">{imageryError}</p>}
          <div className="grid grid-cols-2 gap-1.5">
            {IMAGE_LAYERS.map((l) => {
              const g = imagery?.groups?.[l.group];
              const available = !!g?.layers?.[l.key];
              const active = selectedImage === l.key;
              return (
                <button
                  key={l.key}
                  type="button"
                  disabled={!available}
                  onClick={() => setSelectedImage(active ? "" : l.key)}
                  title={imagery?.descriptions?.[l.key]}
                  className={`flex items-center gap-1.5 rounded border px-1.5 py-1 text-left transition ${
                    active
                      ? "border-[#20808d] bg-[#20808d]/10 font-semibold"
                      : "border-[#e7e5e0] bg-white hover:border-[#20808d]/50"
                  } disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  {available ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={g!.layers![l.key]} alt="" className="h-7 w-7 rounded-sm object-cover shrink-0" />
                  ) : (
                    <span className="h-7 w-7 rounded-sm bg-[#f5f4ef] shrink-0" />
                  )}
                  <span className="leading-tight">{l.label}</span>
                </button>
              );
            })}
          </div>
          <div className="text-[10px] font-mono text-[#6b675f] space-y-0.5">
            {imagery &&
              Object.entries(imagery.groups).map(([k, g]) => (
                <p key={k}>
                  {k.toUpperCase()}: {g.status === "ok" ? `${g.source} · ${g.date?.slice(0, 10)}${g.sensor ? ` · ${g.sensor}` : ""}` : g.note || g.error || g.status}
                </p>
              ))}
          </div>
        </div>

        <div className="rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-3 space-y-2">
          <p className="font-mono text-[11px] uppercase tracking-wider text-[#6b675f]">NASA map layers (GIBS)</p>
          {Object.keys(groupedTiles).length === 0 && <p className="text-[#6b675f]">Loading layer catalogue…</p>}
          {Object.entries(groupedTiles).map(([group, items]) => (
            <div key={group} className="space-y-1">
              <p className="text-[10px] font-mono uppercase text-[#6b675f]">{group}</p>
              {items.map(([key, meta]) => (
                <label key={key} className="flex items-start gap-2 cursor-pointer" title={meta.description}>
                  <input
                    type="checkbox"
                    className="mt-0.5 accent-[#20808d]"
                    checked={activeTiles.includes(key)}
                    onChange={(e) =>
                      setActiveTiles((prev) => (e.target.checked ? [...prev, key] : prev.filter((x) => x !== key)))
                    }
                  />
                  <span>
                    {meta.description}
                    {meta.default_time && <span className="text-[#6b675f] font-mono"> · {meta.default_time}</span>}
                  </span>
                </label>
              ))}
            </div>
          ))}
          <label className="flex items-center gap-2 pt-1 border-t border-[#e7e5e0]">
            <span className="font-mono text-[10px] text-[#6b675f]">OPACITY</span>
            <input
              type="range"
              min={0.2}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              className="flex-1 accent-[#20808d]"
            />
          </label>
        </div>
      </div>
    </div>
  );
}
