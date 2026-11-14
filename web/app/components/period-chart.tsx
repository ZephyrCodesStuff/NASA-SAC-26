"use client";

import React, { useMemo, useState } from "react";

export interface PeriodPoint {
  period: number; // 1..24
  label: string;
  precipMm: number;
  etcMm: number;
  tempC: number;
}

interface PeriodChartProps {
  points: PeriodPoint[];
}

export function PeriodChart({ points }: PeriodChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const width = 760;
  const height = 220;
  const padL = 38;
  const padR = 38;
  const padT = 16;
  const padB = 28;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const maxWater = useMemo(() => {
    const vals = points.flatMap((p) => [p.precipMm, p.etcMm]);
    return Math.max(80, Math.ceil(Math.max(...vals, 10) / 10) * 10);
  }, [points]);

  const maxTemp = useMemo(() => {
    const vals = points.map((p) => p.tempC);
    return Math.max(35, Math.ceil(Math.max(...vals, 25) / 5) * 5);
  }, [points]);

  const barSlot = innerW / Math.max(1, points.length);
  const barW = Math.max(6, barSlot * 0.56);

  const etcPath = useMemo(() => {
    return points
      .map((p, i) => {
        const x = padL + i * barSlot + barSlot / 2;
        const y = padT + innerH - (p.etcMm / maxWater) * innerH;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [points, barSlot, innerH, maxWater]);

  const tempPath = useMemo(() => {
    return points
      .map((p, i) => {
        const x = padL + i * barSlot + barSlot / 2;
        const y = padT + innerH - (Math.max(0, p.tempC) / maxTemp) * innerH;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [points, barSlot, innerH, maxTemp]);

  const hovered = hoverIdx !== null ? points[hoverIdx] : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-[#6b675f]">
        <div className="flex items-center gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-xs bg-[#20808d]/75" />
            Precip (mm)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-3 bg-[#1f1915]" />
            Crop ETc (mm)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-3 border-t-2 border-dashed border-[#d97706]" />
            Mean Temp (°C)
          </span>
        </div>

        <div className="tabular-nums text-[#1f1915]">
          {hovered
            ? `P${hovered.period} (${hovered.label}) · Precip ${hovered.precipMm.toFixed(1)} mm · ETc ${hovered.etcMm.toFixed(1)} mm · ${hovered.tempC.toFixed(1)}°C`
            : "Hover any 15-day period (P1–P24)"}
        </div>
      </div>

      <div className="w-full overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[540px] h-auto select-none">
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const y = padT + innerH * (1 - t);
            return (
              <g key={t}>
                <line
                  x1={padL}
                  y1={y}
                  x2={width - padR}
                  y2={y}
                  stroke="#e7e5e0"
                  strokeWidth={1}
                />
                <text
                  x={padL - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-[#6b675f] font-mono text-[9px]"
                >
                  {Math.round(maxWater * t)}
                </text>
                <text
                  x={width - padR + 6}
                  y={y + 3}
                  textAnchor="start"
                  className="fill-[#d97706] font-mono text-[9px]"
                >
                  {Math.round(maxTemp * t)}°
                </text>
              </g>
            );
          })}

          {/* Precipitation bars */}
          {points.map((p, i) => {
            const x = padL + i * barSlot + (barSlot - barW) / 2;
            const h = (p.precipMm / maxWater) * innerH;
            const y = padT + innerH - h;
            const isHover = hoverIdx === i;
            return (
              <g
                key={p.period}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
                className="cursor-crosshair"
              >
                <rect
                  x={padL + i * barSlot}
                  y={padT}
                  width={barSlot}
                  height={innerH}
                  fill={isHover ? "#20808d" : "transparent"}
                  fillOpacity={isHover ? 0.06 : 0}
                />
                <rect
                  x={x}
                  y={y}
                  width={barW}
                  height={Math.max(1, h)}
                  rx={1.5}
                  fill="#20808d"
                  fillOpacity={isHover ? 0.95 : 0.7}
                />
                {i % 2 === 0 && (
                  <text
                    x={padL + i * barSlot + barSlot / 2}
                    y={height - 8}
                    textAnchor="middle"
                    className="fill-[#6b675f] font-mono text-[9px]"
                  >
                    P{p.period}
                  </text>
                )}
              </g>
            );
          })}

          {/* ETc line */}
          <path d={etcPath} fill="none" stroke="#1f1915" strokeWidth={1.75} />

          {/* Temp dashed line */}
          <path
            d={tempPath}
            fill="none"
            stroke="#d97706"
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        </svg>
      </div>
    </div>
  );
}
