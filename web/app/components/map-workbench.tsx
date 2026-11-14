"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  Sprout,
  Eye,
  Pencil,
  LogOut,
  Plus,
  Layers,
  MapPin,
  Trash2,
  ArrowRight,
  Undo2,
  X,
  Check,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Satellite,
  Map as MapIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { FarmRecord, PlotRecord, webApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const TURIN_PRESETS = [
  { key: "carmagnola_po_valley", name: "Carmagnola (Po Valley)", lat: 44.8467, lon: 7.7178, zoom: 15 },
  { key: "torino_stura_farmland", name: "Torino Stura", lat: 45.1185, lon: 7.716, zoom: 15 },
  { key: "chieri", name: "Chieri Hills", lat: 45.0139, lon: 7.8225, zoom: 15 },
  { key: "torino_centro", name: "Torino Centro", lat: 45.0703, lon: 7.6869, zoom: 15 },
];

const CATASTO_WMS_URL = "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php";

function isOwner(
  farm: FarmRecord | undefined,
  userId: string | undefined,
  role: string | undefined,
  email?: string
) {
  if (!farm || !userId || role !== "farm_admin") return false;
  if (farm.is_public_demo && email?.toLowerCase() === "marco@turinfarm.it") return true;
  return farm.owner === userId;
}

export function MapWorkbench() {
  const { user, token, logout } = useAuth();

  const [farms, setFarms] = useState<FarmRecord[]>([]);
  const [selectedFarmId, setSelectedFarmId] = useState<string>("");
  const [plots, setPlots] = useState<PlotRecord[]>([]);
  const [selectedPlotId, setSelectedPlotId] = useState<string | null>(null);
  const [loadingData, setLoadingData] = useState(true);

  const [railOpen, setRailOpen] = useState(true);
  const [mapReady, setMapReady] = useState(false);
  const [mode, setMode] = useState<"viewer" | "editor">("viewer");
  const [baseLayer, setBaseLayer] = useState<"osm" | "satellite">("satellite");
  const [showCatasto, setShowCatasto] = useState(true);

  // New farm inline state
  const [creatingFarm, setCreatingFarm] = useState(false);
  const [newFarmName, setNewFarmName] = useState("");

  // Drawing polygon state ([lat, lon][])
  const [drawPoints, setDrawPoints] = useState<Array<[number, number]>>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoveredParcels, setDiscoveredParcels] = useState<Array<Record<string, unknown>> | null>(null);
  const [catastoParcels, setCatastoParcels] = useState<Array<Record<string, unknown>>>([]);
  const [useCatastoGeometry, setUseCatastoGeometry] = useState(false);
  const [newPlotLabel, setNewPlotLabel] = useState("");
  const [newPlotCrop, setNewPlotCrop] = useState("");
  const [savingPlot, setSavingPlot] = useState(false);

  // Leaflet refs
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const baseTileRef = useRef<L.TileLayer | null>(null);
  const catastoLayerRef = useRef<L.TileLayer.WMS | null>(null);
  const plotsLayerRef = useRef<L.LayerGroup | null>(null);
  const drawLayerRef = useRef<L.LayerGroup | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const initialQueryRef = useRef<{ farmId: string | null; plotId: string | null } | null>(null);
  const focusedInitialPlotRef = useRef(false);

  if (initialQueryRef.current === null && typeof window !== "undefined") {
    const sp = new URLSearchParams(window.location.search);
    initialQueryRef.current = {
      farmId: sp.get("farm"),
      plotId: sp.get("plot"),
    };
  }

  const selectedFarm = useMemo(
    () => farms.find((f) => f.id === selectedFarmId),
    [farms, selectedFarmId]
  );
  const canEdit = useMemo(
    () => isOwner(selectedFarm, user?.user_id || user?.id, user?.role, user?.email),
    [selectedFarm, user]
  );
  const selectedPlot = useMemo(
    () => plots.find((p) => p.id === selectedPlotId) || null,
    [plots, selectedPlotId]
  );

  // Load farms on mount
  const loadFarms = useCallback(async () => {
    if (!token) return;
    setLoadingData(true);
    try {
      const res = await webApi.listFarms(token);
      setFarms(res.farms);
      if (res.farms.length > 0) {
        const requestedFarm = initialQueryRef.current?.farmId;
        setSelectedFarmId((prev) => {
          if (requestedFarm && res.farms.some((f) => f.id === requestedFarm)) {
            return requestedFarm;
          }
          return prev && res.farms.some((f) => f.id === prev) ? prev : res.farms[0].id;
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load farms");
    } finally {
      setLoadingData(false);
    }
  }, [token]);

  useEffect(() => {
    loadFarms();
  }, [loadFarms]);

  // Load plots when farm changes
  const loadPlots = useCallback(async () => {
    if (!token || !selectedFarmId) {
      setPlots([]);
      return;
    }
    try {
      const res = await webApi.listPlots(selectedFarmId, token);
      setPlots(res.plots);
      setSelectedPlotId((prev) =>
        prev && res.plots.some((p) => p.id === prev) ? prev : null
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load plots");
    }
  }, [token, selectedFarmId]);

  useEffect(() => {
    loadPlots();
  }, [loadPlots]);

  // Force viewer mode if user doesn't own selected farm
  useEffect(() => {
    if (!canEdit && mode === "editor") {
      setMode("viewer");
      setDrawPoints([]);
      setDiscoveredParcels(null);
    }
  }, [canEdit, mode]);

  // Initialize Leaflet map once
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [TURIN_PRESETS[0].lat, TURIN_PRESETS[0].lon],
      zoom: TURIN_PRESETS[0].zoom,
      zoomControl: false,
    });
    L.control.zoom({ position: "bottomleft" }).addTo(map);

    plotsLayerRef.current = L.layerGroup().addTo(map);
    drawLayerRef.current = L.layerGroup().addTo(map);

    map.on("click", (e: L.LeafletMouseEvent) => {
      if (modeRef.current !== "editor") return;
      setDrawPoints((prev) => [...prev, [e.latlng.lat, e.latlng.lng]]);
    });

    mapRef.current = map;
    map.invalidateSize({ animate: false });
    setMapReady(true);

    // Ensure Leaflet recalculates container dimensions after flex layout / sidebar toggles
    const ro = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
    });
    ro.observe(mapContainerRef.current);
    const t = setTimeout(() => map.invalidateSize({ animate: false }), 120);

    return () => {
      clearTimeout(t);
      ro.disconnect();
      setMapReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Sync base tile layer
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (baseTileRef.current) {
      map.removeLayer(baseTileRef.current);
      baseTileRef.current = null;
    }
    const isSat = baseLayer === "satellite";
    const url = isSat
      ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
    const attribution = isSat
      ? "Tiles &copy; Esri"
      : "&copy; OpenStreetMap contributors";

    baseTileRef.current = L.tileLayer(url, {
      maxZoom: 20,
      maxNativeZoom: isSat ? 18 : 19,
      zIndex: 1,
      attribution,
    }).addTo(map);
    baseTileRef.current.bringToBack();
  }, [baseLayer, mapReady]);

  // Sync Catasto WMS layer
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (catastoLayerRef.current) {
      map.removeLayer(catastoLayerRef.current);
      catastoLayerRef.current = null;
    }
    if (showCatasto) {
      catastoLayerRef.current = L.tileLayer
        .wms(CATASTO_WMS_URL, {
          layers: "CP.CadastralParcel",
          format: "image/png",
          transparent: true,
          version: "1.3.0",
          minZoom: 15,
          maxZoom: 20,
          zIndex: 2,
          attribution: "AdE Catasto CC BY 4.0",
        })
        .addTo(map);
    }
  }, [showCatasto, mapReady]);

  // Render plots on map
  useEffect(() => {
    const map = mapRef.current;
    const group = plotsLayerRef.current;
    if (!mapReady || !map || !group) return;
    group.clearLayers();

    const allBounds: L.LatLngBounds[] = [];
    for (const plot of plots) {
      if (!plot.geometry) continue;
      const isSelected = plot.id === selectedPlotId;
      try {
        const layer = L.geoJSON(plot.geometry as unknown as GeoJSON.GeoJsonObject, {
          style: {
            color: isSelected ? "#0f766e" : "#20808d",
            weight: isSelected ? 3 : 2,
            fillColor: isSelected ? "#14b8a6" : "#20808d",
            fillOpacity: isSelected ? 0.35 : 0.18,
          },
        });
        layer.on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          if (modeRef.current === "viewer") {
            setSelectedPlotId(plot.id);
          }
        });
        layer.addTo(group);
        const b = layer.getBounds();
        if (b.isValid()) allBounds.push(b);
      } catch {
        // Ignore malformed geometry
      }
    }

    if (allBounds.length > 0 && !selectedPlotId && drawPoints.length === 0) {
      const combined = allBounds.reduce((acc, b) => acc.extend(b), L.latLngBounds(allBounds[0].getSouthWest(), allBounds[0].getNorthEast()));
      if (combined.isValid()) {
        map.invalidateSize({ animate: false });
        map.fitBounds(combined, { padding: [48, 48], maxZoom: 16 });
      }
    }
  }, [plots, selectedPlotId, drawPoints.length, mapReady]);

  // Render drawing polygon preview (and Catasto snap preview when selected)
  useEffect(() => {
    const group = drawLayerRef.current;
    if (!group) return;
    group.clearLayers();

    if (useCatastoGeometry && catastoParcels.length > 0) {
      for (const feat of catastoParcels) {
        const geom = feat.geometry as GeoJSON.GeoJsonObject | undefined;
        if (!geom) continue;
        try {
          L.geoJSON(geom, {
            style: {
              color: "#d97706",
              weight: 2.5,
              fillColor: "#f59e0b",
              fillOpacity: 0.25,
            },
          }).addTo(group);
        } catch {
          // Ignore malformed geometry
        }
      }
      return;
    }

    if (drawPoints.length === 0) return;

    drawPoints.forEach(([lat, lon], idx) => {
      L.circleMarker([lat, lon], {
        radius: 5,
        color: "#0f766e",
        weight: 2,
        fillColor: idx === 0 ? "#f59e0b" : "#ffffff",
        fillOpacity: 1,
      }).addTo(group);
    });

    if (drawPoints.length >= 2) {
      L.polygon(drawPoints, {
        color: "#0f766e",
        weight: 2,
        dashArray: "6 4",
        fillColor: "#20808d",
        fillOpacity: 0.2,
      }).addTo(group);
    }
  }, [drawPoints, useCatastoGeometry, catastoParcels]);

  const focusPlot = useCallback((plot: PlotRecord) => {
    setSelectedPlotId(plot.id);
    const map = mapRef.current;
    if (!map || !plot.geometry) return;
    try {
      const bounds = L.geoJSON(plot.geometry as unknown as GeoJSON.GeoJsonObject).getBounds();
      if (bounds.isValid()) {
        map.invalidateSize({ animate: false });
        map.fitBounds(bounds, { padding: [60, 60], maxZoom: 17 });
      }
    } catch {
      if (plot.centroid) {
        map.setView([plot.centroid.lat, plot.centroid.lon], 16);
      }
    }
  }, []);

  useEffect(() => {
    const targetPlotId = initialQueryRef.current?.plotId;
    if (!mapReady || focusedInitialPlotRef.current || !targetPlotId || plots.length === 0) return;
    const target = plots.find((p) => p.id === targetPlotId);
    if (target) {
      focusedInitialPlotRef.current = true;
      focusPlot(target);
    }
  }, [mapReady, plots, focusPlot]);

  const handleCreateFarm = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newFarmName.trim()) return;
    try {
      const res = await webApi.createFarm(newFarmName.trim(), token);
      setFarms((prev) => [...prev, res.farm]);
      setSelectedFarmId(res.farm.id);
      setNewFarmName("");
      setCreatingFarm(false);
      toast.success(`Created farm "${res.farm.name}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create farm");
    }
  };

  const buildDrawnGeoJson = () => {
    const ring = [...drawPoints.map(([lat, lon]) => [lon, lat])];
    if (ring.length > 0) ring.push(ring[0]);
    const avgLat = drawPoints.reduce((s, p) => s + p[0], 0) / drawPoints.length;
    const avgLon = drawPoints.reduce((s, p) => s + p[1], 0) / drawPoints.length;
    return {
      geometry: { type: "Polygon", coordinates: [ring] },
      centroid: [avgLat, avgLon],
    };
  };

  const handleDiscover = async () => {
    if (!token || drawPoints.length < 3) return;
    setDiscovering(true);
    try {
      const { geometry, centroid } = buildDrawnGeoJson();
      const drawnFeature: Record<string, unknown> = {
        type: "Feature",
        geometry,
        properties: {
          cadastral_ref: "CUSTOM-POLYGON",
          worldcover_label: "Custom Field Boundary",
        },
      };
      const res = await webApi.catastoDiscover(geometry, centroid, token);
      setDiscoveredParcels([drawnFeature]);
      setCatastoParcels(res.parcels);
      setUseCatastoGeometry(false);
      if (res.parcels.length > 0) {
        toast.success(`Found ${res.parcels.length} Catasto parcel(s) — keep drawn boundary or snap to Catasto.`);
      } else {
        toast.info("No Catasto parcels matched — ready to save your drawn boundary.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Parcel discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const handleSavePlot = async () => {
    if (!token || !selectedFarmId || !discoveredParcels) return;
    const featuresToSave =
      useCatastoGeometry && catastoParcels.length > 0 ? catastoParcels : discoveredParcels;
    setSavingPlot(true);
    try {
      const res = await webApi.createPlot(
        selectedFarmId,
        {
          features: featuresToSave,
          label: newPlotLabel.trim() || undefined,
          crop: newPlotCrop.trim() || undefined,
          use_catasto_names: useCatastoGeometry && !newPlotLabel.trim(),
        },
        token
      );
      setPlots((prev) => [...prev, res.plot]);
      setSelectedPlotId(res.plot.id);
      setDrawPoints([]);
      setDiscoveredParcels(null);
      setCatastoParcels([]);
      setUseCatastoGeometry(false);
      setNewPlotLabel("");
      setNewPlotCrop("");
      setMode("viewer");
      toast.success(`Saved plot "${res.plot.label}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save plot");
    } finally {
      setSavingPlot(false);
    }
  };

  const handleDeletePlot = async (plotId: string) => {
    if (!token) return;
    try {
      await webApi.deletePlot(plotId, token);
      setPlots((prev) => prev.filter((p) => p.id !== plotId));
      if (selectedPlotId === plotId) setSelectedPlotId(null);
      toast.success("Plot deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete plot");
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[#faf9f5] text-[#1f1915]">
      {/* Thin Top Bar */}
      <header className="h-[52px] shrink-0 border-b border-[#e7e5e0] bg-[#fdfbfa] px-4 flex items-center justify-between gap-4 z-20">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={() => setRailOpen((v) => !v)}
            className="p-1.5 rounded-md border border-[#e7e5e0] bg-white hover:bg-[#f5f4ef] text-[#6b675f]"
            title={railOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {railOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </button>

          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-[#20808d] text-white flex items-center justify-center">
              <Sprout className="h-4 w-4" />
            </div>
            <span className="font-serif text-sm font-semibold tracking-tight hidden sm:inline">
              Turin Crop Planner
            </span>
          </div>

          <span className="text-[#e7e5e0] hidden sm:inline">|</span>

          {/* Farm Selector */}
          <div className="flex items-center gap-1.5">
            <select
              value={selectedFarmId}
              onChange={(e) => setSelectedFarmId(e.target.value)}
              className="h-8 rounded-md border border-[#e7e5e0] bg-white px-2.5 text-xs font-medium text-[#1f1915] focus:outline-none focus:ring-1 focus:ring-[#20808d]"
              disabled={loadingData || farms.length === 0}
            >
              {farms.length === 0 && <option value="">No farms</option>}
              {farms.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>

            {user?.role === "farm_admin" && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 px-2 text-xs"
                onClick={() => setCreatingFarm((v) => !v)}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Viewer / Editor Segmented Toggle */}
          <div className="flex items-center rounded-md border border-[#e7e5e0] bg-[#f5f4ef] p-0.5">
            <button
              type="button"
              onClick={() => {
                setMode("viewer");
                setDrawPoints([]);
                setDiscoveredParcels(null);
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition ${
                mode === "viewer"
                  ? "bg-white text-[#1f1915] shadow-xs"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              <Eye className="h-3.5 w-3.5" />
              Viewer
            </button>
            <button
              type="button"
              disabled={!canEdit}
              onClick={() => setMode("editor")}
              title={canEdit ? "Draw polygon to add plots" : "Select a farm you own to edit"}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${
                mode === "editor"
                  ? "bg-[#20808d] text-white shadow-xs"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              <Pencil className="h-3.5 w-3.5" />
              Editor
            </button>
          </div>

          <div className="hidden md:flex items-center gap-2 pl-2 border-l border-[#e7e5e0] text-xs">
            <span className="font-medium text-[#1f1915]">{user?.name}</span>
            <Badge variant="outline" className="font-mono text-[10px]">
              {user?.role === "farm_admin" ? "admin" : "viewer"}
            </Badge>
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={logout}
            className="h-8 px-2 text-[#6b675f] hover:text-[#1f1915]"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Inline New Farm Bar */}
      {creatingFarm && (
        <form
          onSubmit={handleCreateFarm}
          className="border-b border-[#e7e5e0] bg-[#fdfbfa] px-4 py-2 flex items-center gap-2 z-20"
        >
          <Input
            value={newFarmName}
            onChange={(e) => setNewFarmName(e.target.value)}
            placeholder="New farm name (e.g. Cascina San Marco)"
            className="h-8 max-w-xs text-xs"
            autoFocus
          />
          <Button type="submit" size="sm" className="h-8 text-xs">
            Create Farm
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 text-xs"
            onClick={() => setCreatingFarm(false)}
          >
            Cancel
          </Button>
        </form>
      )}

      {/* Main Split Workbench */}
      <div className="flex-1 flex min-h-0 relative">
        {/* Left Rail */}
        {railOpen && (
          <aside className="w-[330px] shrink-0 border-r border-[#e7e5e0] bg-[#fdfbfa] flex flex-col min-h-0 z-10">
            <div className="px-4 py-3 border-b border-[#e7e5e0] flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[#6b675f] font-mono">
                  Plots ({plots.length})
                </p>
              </div>
              {canEdit && mode === "viewer" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  onClick={() => setMode("editor")}
                >
                  <Plus className="h-3 w-3" />
                  Draw Plot
                </Button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-[#e7e5e0]">
              {plots.length === 0 ? (
                <div className="p-6 text-xs text-[#6b675f] space-y-2">
                  <p className="font-medium text-[#1f1915]">No plots in this farm yet.</p>
                  <p>
                    {canEdit
                      ? "Switch to Editor mode and click on the map to outline a field."
                      : "Switch to a farm with plots or ask an editor to add one."}
                  </p>
                </div>
              ) : (
                plots.map((plot) => {
                  const active = plot.id === selectedPlotId;
                  return (
                    <button
                      key={plot.id}
                      type="button"
                      onClick={() => focusPlot(plot)}
                      className={`w-full text-left px-4 py-3 transition flex items-start justify-between gap-2 ${
                        active ? "bg-[#20808d]/8 border-l-2 border-l-[#20808d]" : "hover:bg-[#f5f4ef]"
                      }`}
                    >
                      <div className="min-w-0 space-y-0.5">
                        <p className="text-sm font-medium text-[#1f1915] truncate">{plot.label}</p>
                        <p className="text-[11px] font-mono text-[#6b675f] truncate">
                          {plot.cadastral_ref || "Custom boundary"}
                        </p>
                      </div>
                      <span className="shrink-0 font-mono text-xs tabular-nums text-[#20808d] font-medium">
                        {plot.area_ha ? `${plot.area_ha.toFixed(2)} ha` : "—"}
                      </span>
                    </button>
                  );
                })
              )}
            </div>

            {/* Turin Presets Footer */}
            <div className="p-3 border-t border-[#e7e5e0] bg-[#faf9f5] space-y-2">
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b675f]">
                Turin Quick Jump
              </p>
              <div className="flex flex-wrap gap-1.5">
                {TURIN_PRESETS.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    onClick={() => mapRef.current?.setView([p.lat, p.lon], p.zoom)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded border border-[#e7e5e0] bg-white hover:border-[#20808d] text-[11px] text-[#1f1915] transition"
                  >
                    <MapPin className="h-3 w-3 text-[#20808d]" />
                    {p.name}
                  </button>
                ))}
              </div>
            </div>
          </aside>
        )}

        {/* Map Canvas */}
        <main className={`flex-1 relative min-w-0 min-h-0 ${mode === "editor" ? "cursor-crosshair" : ""}`}>
          <div ref={mapContainerRef} className="h-full w-full" />

          {/* Floating Layer Switcher Pill (Top Right) */}
          <div className="absolute top-3 right-3 z-[500] flex items-center gap-1.5 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa]/95 backdrop-blur px-2 py-1.5 shadow-sm">
            <button
              type="button"
              onClick={() => setBaseLayer("osm")}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition ${
                baseLayer === "osm" ? "bg-[#1f1915] text-white" : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              <MapIcon className="h-3.5 w-3.5" />
              Map
            </button>
            <button
              type="button"
              onClick={() => setBaseLayer("satellite")}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition ${
                baseLayer === "satellite"
                  ? "bg-[#1f1915] text-white"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              <Satellite className="h-3.5 w-3.5" />
              Satellite
            </button>
            <span className="text-[#e7e5e0]">|</span>
            <button
              type="button"
              onClick={() => setShowCatasto((v) => !v)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition ${
                showCatasto
                  ? "bg-[#20808d]/15 text-[#20808d]"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              Catasto
            </button>
          </div>

          {/* Editor Draw Toolbar (Bottom Center) */}
          {mode === "editor" && !discoveredParcels && (
            <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-[500] flex items-center gap-2 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa]/95 backdrop-blur px-3 py-2 shadow-md">
              <span className="text-xs font-mono text-[#6b675f] px-1">
                {drawPoints.length === 0
                  ? "Click map to place polygon vertices"
                  : `${drawPoints.length} vertices`}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1"
                disabled={drawPoints.length === 0}
                onClick={() => setDrawPoints((p) => p.slice(0, -1))}
              >
                <Undo2 className="h-3 w-3" />
                Undo
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                disabled={drawPoints.length === 0}
                onClick={() => setDrawPoints([])}
              >
                Clear
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-7 text-xs gap-1"
                disabled={drawPoints.length < 3 || discovering}
                onClick={handleDiscover}
              >
                {discovering ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Discover &amp; Save
              </Button>
            </div>
          )}

          {/* Save Discovered Plot Sheet */}
          {discoveredParcels && (
            <div className="absolute bottom-5 right-5 z-[500] w-80 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] p-4 shadow-lg space-y-3">
              <div className="flex items-center justify-between">
                <p className="font-serif text-sm font-semibold">
                  {useCatastoGeometry && catastoParcels.length > 0
                    ? `Save Plot (${catastoParcels.length} Catasto parcel${catastoParcels.length > 1 ? "s" : ""})`
                    : "Save Drawn Plot"}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setDiscoveredParcels(null);
                    setCatastoParcels([]);
                    setUseCatastoGeometry(false);
                  }}
                  className="text-[#6b675f] hover:text-[#1f1915]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {catastoParcels.length > 0 && (
                <div className="space-y-1">
                  <span className="text-[11px] font-medium text-[#6b675f]">Boundary source</span>
                  <div className="grid grid-cols-2 gap-1.5">
                    <button
                      type="button"
                      onClick={() => setUseCatastoGeometry(false)}
                      className={`px-2.5 py-1.5 rounded text-xs font-medium border transition-colors ${
                        !useCatastoGeometry
                          ? "bg-[#20808d] text-white border-[#20808d]"
                          : "bg-white text-[#1f1915] border-[#e7e5e0] hover:bg-[#f5f4ef]"
                      }`}
                    >
                      My drawing
                    </button>
                    <button
                      type="button"
                      onClick={() => setUseCatastoGeometry(true)}
                      className={`px-2.5 py-1.5 rounded text-xs font-medium border transition-colors ${
                        useCatastoGeometry
                          ? "bg-[#d97706] text-white border-[#d97706]"
                          : "bg-white text-[#1f1915] border-[#e7e5e0] hover:bg-[#f5f4ef]"
                      }`}
                    >
                      Catasto ({catastoParcels.length})
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-[#6b675f]">
                    {useCatastoGeometry ? "Plot Label (optional — defaults to Catasto ref)" : "Plot Label"}
                  </label>
                  <Input
                    value={newPlotLabel}
                    onChange={(e) => setNewPlotLabel(e.target.value)}
                    placeholder="North Maize Field"
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-[#6b675f]">
                    Current / Baseline Crop (optional)
                  </label>
                  <Input
                    value={newPlotCrop}
                    onChange={(e) => setNewPlotCrop(e.target.value)}
                    placeholder="e.g. Maize, Winter Wheat"
                    className="h-8 text-xs"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs"
                  onClick={() => {
                    setDiscoveredParcels(null);
                    setCatastoParcels([]);
                    setUseCatastoGeometry(false);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 text-xs"
                  disabled={savingPlot}
                  onClick={handleSavePlot}
                >
                  {savingPlot ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save Plot"}
                </Button>
              </div>
            </div>
          )}

          {/* Selected Plot Quick-Inspect Sheet */}
          {selectedPlot && mode === "viewer" && (
            <div className="absolute bottom-5 right-5 z-[500] w-80 rounded-lg border border-[#e7e5e0] bg-[#fdfbfa]/95 backdrop-blur p-4 shadow-lg space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-serif text-base font-semibold truncate">{selectedPlot.label}</p>
                  <p className="text-[11px] font-mono text-[#6b675f] truncate">
                    {selectedPlot.cadastral_ref || "Custom polygon"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedPlotId(null)}
                  className="text-[#6b675f] hover:text-[#1f1915]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="border-y border-[#e7e5e0] py-2 flex items-center justify-between text-xs font-mono">
                <span>{selectedPlot.area_ha ? `${selectedPlot.area_ha.toFixed(2)} ha` : "Area n/a"}</span>
                <span className="text-[#6b675f] truncate max-w-[160px]">
                  {selectedPlot.worldcover_label || "Farmland"}
                </span>
              </div>

              <div className="flex items-center justify-between gap-2">
                <Link href={`/plots/${selectedPlot.id}`} className="flex-1">
                  <Button type="button" size="sm" className="w-full h-8 text-xs gap-1.5">
                    Open Plot Workspace
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
                {canEdit && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-rose-700 hover:bg-rose-50"
                    onClick={() => handleDeletePlot(selectedPlot.id)}
                    title="Delete plot"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
