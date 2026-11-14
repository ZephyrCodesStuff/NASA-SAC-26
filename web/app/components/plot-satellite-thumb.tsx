"use client";

import React, { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

interface PlotSatelliteThumbProps {
  geometry?: Record<string, unknown>;
  centroid?: { lat: number; lon: number };
}

export function PlotSatelliteThumb({ geometry, centroid }: PlotSatelliteThumbProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: centroid ? [centroid.lat, centroid.lon] : [44.8467, 7.7178],
      zoom: 16,
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: false,
    });

    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 20, maxNativeZoom: 18 }
    ).addTo(map);

    if (geometry) {
      try {
        const layer = L.geoJSON(geometry as unknown as GeoJSON.GeoJsonObject, {
          style: {
            color: "#2dd4bf",
            weight: 2.5,
            fillColor: "#14b8a6",
            fillOpacity: 0.22,
          },
        }).addTo(map);
        const bounds = layer.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [14, 14], maxZoom: 19, animate: false });
        }
      } catch {
        // Fallback to centroid
      }
    }

    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize({ animate: false }));
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [geometry, centroid]);

  return (
    <div className="relative isolate h-[132px] w-[220px] shrink-0 overflow-hidden rounded-md border border-[#e7e5e0] bg-[#1f1915]">
      <div ref={containerRef} className="h-full w-full" />
      <span className="pointer-events-none absolute bottom-1.5 right-1.5 rounded bg-black/65 px-1.5 py-0.5 font-mono text-[9px] text-white/90">
        Esri World_Imagery
      </span>
    </div>
  );
}
