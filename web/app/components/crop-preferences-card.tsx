"use client";

import { useState } from "react";
import { Ban, Check, ChevronDown, ChevronUp, ListFilter, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

/** The crops the rotation optimizer can pick from (analytics-api `MASTER_CROPS_CATALOG`; ids must match). */
export const ROTATION_CROPS: Array<{ id: string; name: string; family: string }> = [
  { id: "corn", name: "Corn (maize)", family: "Grasses" },
  { id: "winter_wheat", name: "Winter wheat", family: "Grasses" },
  { id: "grain_sorghum", name: "Grain sorghum", family: "Grasses" },
  { id: "soybeans", name: "Soybeans", family: "Legumes" },
  { id: "alfalfa", name: "Alfalfa", family: "Legumes" },
  { id: "field_peas", name: "Field peas, chickpeas", family: "Legumes" },
  { id: "sunflowers", name: "Sunflowers", family: "Daisy family" },
  { id: "canola", name: "Canola (rapeseed)", family: "Cabbage family" },
  { id: "daikon_radish_cover", name: "Daikon radish (cover)", family: "Cabbage family" },
  { id: "processing_tomatoes", name: "Processing tomatoes", family: "Nightshades" },
  { id: "bell_peppers", name: "Bell peppers", family: "Nightshades" },
  { id: "spinach", name: "Spinach", family: "Amaranth family" },
];

/** The optimizer only applies an "only grow" list of 3+ crops, and drops all choices if fewer than 2 remain. */
const MIN_CROPS = 3;

type Choice = "any" | "grow" | "never";

export interface CropPreferences {
  whitelist: string[];
  blacklist: string[];
}

export function readCropPreferences(override: Record<string, unknown> | undefined | null): CropPreferences {
  const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  const blacklist = list(override?.crop_blacklist);
  return { whitelist: list(override?.crop_whitelist).filter((c) => !blacklist.includes(c)), blacklist };
}

function summarize(whitelist: string[], blacklist: string[]) {
  const pool = (whitelist.length > 0 ? whitelist : ROTATION_CROPS.map((c) => c.id)).filter((c) => !blacklist.includes(c));
  let problem: string | null = null;
  if (whitelist.length > 0 && whitelist.length < MIN_CROPS) {
    problem = `Pick at least ${MIN_CROPS} crops under "Grow" so the planner can build a rotation, or clear them all to let it choose freely.`;
  } else if (pool.length < MIN_CROPS) {
    problem = `At least ${MIN_CROPS} crops must stay available. Unblock a few.`;
  }
  const names = (ids: string[]) => ids.map((id) => ROTATION_CROPS.find((c) => c.id === id)?.name ?? id).join(", ");
  let text: string;
  if (whitelist.length === 0 && blacklist.length === 0) text = `Any of the ${ROTATION_CROPS.length} crops`;
  else if (whitelist.length > 0) text = `Only ${names(whitelist)}`;
  else text = `${pool.length} of ${ROTATION_CROPS.length} crops`;
  if (blacklist.length > 0) text += ` · never ${names(blacklist)}`;
  return { pool, problem, text };
}

const CHOICES: Array<{ value: Choice; label: string; icon?: typeof Check; active: string }> = [
  { value: "any", label: "Maybe", active: "bg-white text-[#1f1915] shadow-sm" },
  { value: "grow", label: "Grow", icon: Check, active: "bg-[#20808d] text-white shadow-sm" },
  { value: "never", label: "Never", icon: Ban, active: "bg-rose-600 text-white shadow-sm" },
];

/**
 * Farmer crop whitelist / blacklist for the 3-year rotation planner. Remount it (via `key`) when the saved lists
 * change; it keeps a local draft until "Save & re-plan".
 */
export function CropPreferencesCard({
  saved,
  editable,
  saving,
  onSave,
  defaultOpen = false,
}: {
  saved: CropPreferences;
  editable: boolean;
  saving?: boolean;
  onSave: (prefs: CropPreferences) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [choices, setChoices] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(
      ROTATION_CROPS.map((c) => [
        c.id,
        saved.blacklist.includes(c.id) ? "never" : saved.whitelist.includes(c.id) ? "grow" : "any",
      ])
    )
  );

  const whitelist = ROTATION_CROPS.filter((c) => choices[c.id] === "grow").map((c) => c.id);
  const blacklist = ROTATION_CROPS.filter((c) => choices[c.id] === "never").map((c) => c.id);
  const draft = summarize(whitelist, blacklist);
  const current = summarize(saved.whitelist, saved.blacklist);
  const dirty =
    whitelist.join() !== ROTATION_CROPS.filter((c) => saved.whitelist.includes(c.id)).map((c) => c.id).join() ||
    blacklist.join() !== ROTATION_CROPS.filter((c) => saved.blacklist.includes(c.id)).map((c) => c.id).join();

  const setAll = (value: Choice) => setChoices(Object.fromEntries(ROTATION_CROPS.map((c) => [c.id, value])));

  return (
    <section className="rounded-xl border border-[#e7e5e0] bg-[#fdfbfa] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 text-left hover:bg-[#f5f4ef]/60 transition-colors"
      >
        <span className="flex items-center gap-2.5 min-w-0">
          <ListFilter className="h-4 w-4 text-[#20808d] shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-[#1f1915]">Crops the planner may use</span>
            <span className="block text-xs text-[#6b675f] truncate">
              {current.text}
              {dirty ? " · unsaved changes" : ""}
            </span>
          </span>
        </span>
        <span className="flex items-center gap-2 shrink-0 text-xs text-[#20808d] font-medium">
          {open ? "Hide" : editable ? "Choose crops" : "View"}
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>

      {open && (
        <div className="border-t border-[#e7e5e0] px-4 py-4 space-y-4">
          <p className="text-xs text-[#6b675f] leading-relaxed max-w-2xl">
            Mark crops you want in the plan as <strong className="text-[#20808d]">Grow</strong>: the planner then picks
            only among them (choose at least {MIN_CROPS}). Mark crops you can&apos;t or won&apos;t grow (no buyer, no
            machinery, no water) as <strong className="text-rose-700">Never</strong>. Leave the rest on Maybe.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
            {ROTATION_CROPS.map((crop) => {
              const choice = choices[crop.id];
              const tone =
                choice === "grow"
                  ? "border-[#20808d]/50 bg-[#20808d]/5"
                  : choice === "never"
                    ? "border-rose-200 bg-rose-50/50"
                    : "border-[#e7e5e0] bg-white";
              return (
                <div
                  key={crop.id}
                  className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 transition-colors ${tone}`}
                >
                  <div className="min-w-0">
                    <p
                      className={`text-sm font-medium leading-snug ${
                        choice === "never" ? "text-[#6b675f] line-through decoration-rose-400" : "text-[#1f1915]"
                      }`}
                    >
                      {crop.name}
                    </p>
                    <p className="text-[11px] text-[#6b675f]">{crop.family}</p>
                  </div>
                  <div
                    role="radiogroup"
                    aria-label={`${crop.name} in the rotation`}
                    className="flex shrink-0 rounded-md bg-[#f0eee9] p-0.5"
                  >
                    {CHOICES.map((c) => {
                      const selected = choice === c.value;
                      const Icon = c.icon;
                      return (
                        <button
                          key={c.value}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={!editable || saving}
                          onClick={() => setChoices((prev) => ({ ...prev, [crop.id]: c.value }))}
                          className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors disabled:cursor-default ${
                            selected ? c.active : "text-[#6b675f] enabled:hover:text-[#1f1915]"
                          }`}
                        >
                          {Icon && <Icon className="h-3 w-3" />}
                          {c.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <p className={`text-xs ${draft.problem ? "text-rose-700" : "text-[#6b675f]"}`}>
              {draft.problem ?? `The planner will choose from ${draft.pool.length} crop${draft.pool.length === 1 ? "" : "s"}.`}
            </p>
            {editable ? (
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 text-xs gap-1.5"
                  disabled={saving || (whitelist.length === 0 && blacklist.length === 0)}
                  onClick={() => setAll("any")}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Clear all
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  disabled={!dirty || !!draft.problem || saving}
                  onClick={() => onSave({ whitelist, blacklist })}
                >
                  {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {saving ? "Re-planning…" : "Save & re-plan"}
                </Button>
              </div>
            ) : (
              <p className="text-xs text-[#6b675f]">Only the farm owner can change these.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
