"use client";

import React, { useMemo, useState } from "react";

export interface SpectralPoint {
  date: string;
  sensor?: string;
  ndvi?: number | null;
  ndmi?: number | null;
  ndre?: number | null;
}

const SERIES = [
  { key: "ndvi", label: "Vigour (NDVI)", color: "#16a34a" },
  { key: "ndmi", label: "Moisture (NDMI)", color: "#2563eb" },
  { key: "ndre", label: "Nitrogen (NDRE)", color: "#7c3aed" },
] as const;

type Key = (typeof SERIES)[number]["key"];

const fmtV = (v: number | null | undefined) => (typeof v === "number" ? v.toFixed(2) : "—");

export function SpectralHistoryChart({ points }: { points: SpectralPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const data = useMemo(() => {
    const xs = points.filter((p) => SERIES.some((s) => typeof p[s.key] === "number"));
    xs.sort((a, b) => (a.date < b.date ? -1 : 1));
    return xs;
  }, [points]);

  const width = 760;
  const height = 220;
  const padL = 34;
  const padR = 16;
  const padT = 14;
  const padB = 26;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const [lo, hi] = useMemo(() => {
    let l = 0;
    let h = 1;
    for (const p of data) {
      for (const s of SERIES) {
        const v = p[s.key];
        if (typeof v === "number") {
          l = Math.min(l, v);
          h = Math.max(h, v);
        }
      }
    }
    if (h - l < 0.3) {
      const m = (l + h) / 2;
      l = m - 0.2;
      h = m + 0.2;
    }
    return [Math.floor(l * 10) / 10, Math.ceil(h * 10) / 10];
  }, [data]);

  if (data.length < 2) {
    return (
      <p className="text-xs text-[#6b675f]">
        Not enough cloud-free scenes in this window to chart a trend (need at least two).
      </p>
    );
  }

  const x = (i: number) => padL + (i / (data.length - 1)) * innerW;
  const y = (v: number) => padT + innerH - ((v - lo) / (hi - lo)) * innerH;

  const path = (key: Key) =>
    data
      .map((p, i) => {
        const v = p[key];
        if (typeof v !== "number") return null;
        return `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  const hovered = hover !== null ? data[hover] : null;
  const labelEvery = Math.max(1, Math.floor(data.length / 6));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-[#6b675f]">
        <div className="flex items-center gap-3">
          {SERIES.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-3 rounded" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
        <div className="tabular-nums text-[#1f1915]">
          {hovered
            ? `${hovered.date}${hovered.sensor ? ` · ${hovered.sensor}` : ""} · NDVI ${fmtV(hovered.ndvi)} · NDMI ${fmtV(
                hovered.ndmi
              )} · NDRE ${fmtV(hovered.ndre)}`
            : "Hover a scene"}
        </div>
      </div>

      <div className="w-full overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[540px] h-auto select-none">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const yy = padT + innerH * (1 - t);
            return (
              <g key={t}>
                <line x1={padL} y1={yy} x2={width - padR} y2={yy} stroke="#e7e5e0" strokeWidth={1} />
                <text x={padL - 6} y={yy + 3} textAnchor="end" className="fill-[#6b675f] font-mono text-[9px]">
                  {(lo + (hi - lo) * t).toFixed(1)}
                </text>
              </g>
            );
          })}

          {data.map((p, i) => (
            <text
              key={`x-${i}-${p.date}`}
              x={x(i)}
              y={height - 8}
              textAnchor="middle"
              className="fill-[#6b675f] font-mono text-[9px]"
            >
              {i % labelEvery === 0 ? p.date.slice(5) : ""}
            </text>
          ))}

          {SERIES.map((s) => (
            <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth={1.6} />
          ))}

          {data.map((p, i) => (
            <g key={`${i}-${p.date}`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect
                x={x(i) - 12}
                y={padT}
                width={24}
                height={innerH}
                fill={hover === i ? "#20808d" : "transparent"}
                fillOpacity={hover === i ? 0.06 : 0}
                className="cursor-crosshair"
              />
              {SERIES.map((s) => {
                const v = p[s.key];
                return typeof v === "number" ? (
                  <circle key={s.key} cx={x(i)} cy={y(v)} r={hover === i ? 3.2 : 2} fill={s.color} />
                ) : null;
              })}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
