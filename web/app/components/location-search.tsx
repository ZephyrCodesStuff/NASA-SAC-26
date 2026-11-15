"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { Loader2, MapPin, Search, X } from "lucide-react";

export interface LocationSelection {
  label: string;
  lat: number;
  lon: number;
  bounds?: [[number, number], [number, number]];
}

interface SearchCandidate extends LocationSelection {
  id: string;
  subtitle?: string;
}

interface PhotonFeature {
  geometry?: { coordinates?: [number, number] };
  properties?: {
    osm_id?: number;
    osm_type?: string;
    name?: string;
    street?: string;
    housenumber?: string;
    city?: string;
    town?: string;
    village?: string;
    county?: string;
    state?: string;
    country?: string;
    extent?: [number, number, number, number];
  };
}

function parseCoordinatePair(raw: string): SearchCandidate | null {
  const m = raw.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    return null;
  }
  return {
    id: `coord-${lat}-${lon}`,
    label: `${lat.toFixed(5)}, ${lon.toFixed(5)}`,
    subtitle: "Direct coordinates",
    lat,
    lon,
  };
}

function formatPhotonFeature(f: PhotonFeature, idx: number): SearchCandidate | null {
  const coords = f.geometry?.coordinates;
  if (!coords || coords.length < 2) return null;
  const [lon, lat] = coords;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  const p = f.properties || {};
  const streetLine = [p.street, p.housenumber].filter(Boolean).join(" ");
  const locality = p.city || p.town || p.village;
  const primary = p.name || streetLine || locality || p.county || p.state || p.country || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;

  const parts: string[] = [];
  for (const v of [streetLine && streetLine !== primary ? streetLine : "", locality, p.county, p.state, p.country]) {
    if (v && v !== primary && !parts.includes(v)) {
      parts.push(v);
    }
  }

  let bounds: [[number, number], [number, number]] | undefined;
  if (Array.isArray(p.extent) && p.extent.length === 4) {
    // Photon extent is [minLon, maxLat, maxLon, minLat]
    const [minLon, maxLat, maxLon, minLat] = p.extent;
    if (
      [minLon, maxLat, maxLon, minLat].every(Number.isFinite) &&
      Math.abs(maxLat - minLat) > 0.002 &&
      Math.abs(maxLon - minLon) > 0.002
    ) {
      bounds = [
        [minLat, minLon],
        [maxLat, maxLon],
      ];
    }
  }

  return {
    id: `photon-${p.osm_type || "n"}-${p.osm_id || idx}-${lat.toFixed(4)}`,
    label: primary,
    subtitle: parts.join(", ") || undefined,
    lat,
    lon,
    bounds,
  };
}

interface LocationSearchProps {
  onSelect: (loc: LocationSelection) => void;
  onDismiss?: () => void;
  autoFocus?: boolean;
  placeholder?: string;
  className?: string;
}

export function LocationSearch({
  onSelect,
  onDismiss,
  autoFocus = false,
  placeholder = "Search address, town, or lat, lon…",
  className = "",
}: LocationSearchProps) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
    }
  }, [autoFocus]);

  useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        if (!query.trim()) onDismiss?.();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [onDismiss, query]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      setErrorMsg(null);
      setActiveIdx(-1);
      return;
    }

    const coord = parseCoordinatePair(trimmed);
    if (coord) {
      setResults([coord]);
      setLoading(false);
      setErrorMsg(null);
      setOpen(true);
      setActiveIdx(0);
      return;
    }

    if (trimmed.length < 2) {
      setResults([]);
      setLoading(false);
      setErrorMsg(null);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setErrorMsg(null);
      try {
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(trimmed)}&limit=5&lang=en`;
        const resp = await fetch(url, { signal: controller.signal });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = (await resp.json()) as { features?: PhotonFeature[] };
        const parsed = (json.features || [])
          .map((f, idx) => formatPhotonFeature(f, idx))
          .filter((item): item is SearchCandidate => item !== null);
        setResults(parsed);
        setOpen(true);
        setActiveIdx(parsed.length > 0 ? 0 : -1);
      } catch (err) {
        if ((err as { name?: string })?.name === "AbortError") return;
        setResults([]);
        setErrorMsg("Location search unavailable");
        setOpen(true);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, 320);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const handleChoose = (item: SearchCandidate) => {
    setQuery(item.label);
    setOpen(false);
    setActiveIdx(-1);
    onSelect(item);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      if (results.length > 0) {
        e.preventDefault();
        setOpen(true);
        setActiveIdx((i) => (i + 1) % results.length);
      }
    } else if (e.key === "ArrowUp") {
      if (results.length > 0) {
        e.preventDefault();
        setOpen(true);
        setActiveIdx((i) => (i <= 0 ? results.length - 1 : i - 1));
      }
    } else if (e.key === "Enter") {
      if (open && results.length > 0) {
        e.preventDefault();
        const idx = activeIdx >= 0 && activeIdx < results.length ? activeIdx : 0;
        handleChoose(results[idx]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (open) {
        setOpen(false);
      } else {
        onDismiss?.();
      }
    }
  };

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <div className="relative flex items-center">
        <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-[#6b675f]" />
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-label="Search address or location"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            if (results.length > 0 || errorMsg) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="h-8 w-full rounded-md border border-[#e7e5e0] bg-white pl-8 pr-7 text-xs text-[#1f1915] placeholder:text-[#8a857c] focus:outline-none focus:ring-1 focus:ring-[#20808d]"
        />
        {loading ? (
          <Loader2 className="absolute right-2 h-3.5 w-3.5 animate-spin text-[#20808d]" />
        ) : query || onDismiss ? (
          <button
            type="button"
            onClick={() => {
              if (query) {
                setQuery("");
                setResults([]);
                setOpen(false);
                inputRef.current?.focus();
              } else {
                onDismiss?.();
              }
            }}
            className="absolute right-1.5 p-0.5 text-[#6b675f] hover:text-[#1f1915]"
            aria-label={query ? "Clear search" : "Close search"}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {open && (results.length > 0 || errorMsg || (!loading && query.trim().length >= 2)) && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute top-full left-0 right-0 mt-1.5 z-[1200] max-h-[45dvh] overflow-y-auto rounded-lg border border-[#e7e5e0] bg-[#fdfbfa] py-1 shadow-lg divide-y divide-[#f5f4ef]"
        >
          {errorMsg ? (
            <li className="px-3 py-2 text-xs text-[#6b675f]">{errorMsg}</li>
          ) : results.length === 0 ? (
            <li className="px-3 py-2 text-xs text-[#6b675f]">No matching places found</li>
          ) : (
            results.map((item, idx) => (
              <li key={item.id} role="option" aria-selected={idx === activeIdx}>
                <button
                  type="button"
                  onClick={() => handleChoose(item)}
                  className={`w-full text-left px-3 py-2 flex items-start gap-2 transition ${
                    idx === activeIdx ? "bg-[#20808d]/10 text-[#1f1915]" : "hover:bg-[#f5f4ef]"
                  }`}
                >
                  <MapPin className="h-3.5 w-3.5 mt-0.5 shrink-0 text-[#20808d]" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-[#1f1915] truncate">{item.label}</p>
                    {item.subtitle && (
                      <p className="text-[11px] text-[#6b675f] truncate">{item.subtitle}</p>
                    )}
                  </div>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
