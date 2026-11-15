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
  const outlineLayerRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const worldBounds: L.LatLngBoundsExpression = [
      [-85, -180],
      [85, 180],
    ];

    const map = L.map(containerRef.current, {
      center: centroid ? [centroid.lat, centroid.lon] : [44.8467, 7.7178],
      zoom: 16,
      minZoom: 2,
      maxBounds: worldBounds,
      maxBoundsViscosity: 1.0,
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
      {
        maxZoom: 20,
        maxNativeZoom: 18,
        noWrap: true,
        bounds: worldBounds,
        updateWhenZooming: false,
        updateWhenIdle: true,
      }
    ).addTo(map);

    mapRef.current = map;
    let rafId = 0;
    const ro = new ResizeObserver(() => {
      const el = containerRef.current;
      if (!el || el.clientWidth === 0 || el.clientHeight === 0) return;
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (mapRef.current) mapRef.current.invalidateSize({ animate: false });
      });
    });
    ro.observe(containerRef.current);
    return () => {
      cancelAnimationFrame(rafId);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      outlineLayerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    outlineLayerRef.current?.remove();
    outlineLayerRef.current = null;

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
        outlineLayerRef.current = layer;
        const bounds = layer.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [14, 14], maxZoom: 19, animate: false });
          return;
        }
      } catch {
        // Fallback to centroid
      }
    }

    if (centroid) {
      map.setView([centroid.lat, centroid.lon], 16, { animate: false });
    }
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
