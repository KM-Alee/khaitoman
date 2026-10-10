/**
 * Presentation of server dataset values. Every value comes from a server row; these helpers
 * only choose units and wording (lib/formatting), never compute analytical numbers.
 */
import { autoDigits, formatDate, formatMass, formatNumber, formatPKRCompact, formatPercent, formatVolume, formatWithUnit, shortId } from "@/lib/formatting";
import { GLOSSARY } from "@/lib/glossary";
import type { CopilotLanguage, Row, VisualColumn } from "./types";

export type Lang = CopilotLanguage | null | undefined;
export const isUrdu = (l: Lang) => l === "ur";

/** Unit of a cell: the column's unit, or the row's own unit for mixed-unit (metric card) columns. */
export function unitOf(col: VisualColumn, row?: Row): string | null {
  if (col.unit) return col.unit;
  if (col.unit_column && row) {
    const u = row[col.unit_column];
    return typeof u === "string" ? u : null;
  }
  return null;
}

/** Short display unit for labels: ratio → %, m3 → m³. */
export function displayUnit(unit: string | null | undefined): string {
  if (!unit) return "";
  if (unit === "ratio" || unit === "fraction") return "%";
  return unit.replace("m3", "m³").replace("m2", "m²");
}

export function colLabel(col: VisualColumn, lang: Lang, withUnit = true): string {
  const base = isUrdu(lang) && col.label_ur ? col.label_ur : col.label;
  const u = withUnit && col.unit ? displayUnit(col.unit) : "";
  return u && col.unit !== "count" ? `${base} (${u})` : base;
}

const STATUS_WORDS: Record<string, string> = {
  available: "Available",
  not_estimated: "Not estimated",
  not_applicable: "Not applicable",
  blocked: "Blocked",
  deliverable: "Deliverable",
  undeliverable: "No plan in this condition",
  nondominated: "Best trade-off",
  dominated: "Beaten by another point",
  dominance_unresolved: "Unresolved",
  not_applicable_dominance: "Not applicable",
  selected: "Chosen",
  not_selected: "Not chosen",
  over_budget: "Over budget",
  ineligible: "Not eligible",
  OPTIMAL: "Best plan proven",
  FEASIBLE: "Valid plan",
  INFEASIBLE: "No valid plan",
  UNKNOWN: "Unknown",
};

export function statusWord(v: string): string {
  return STATUS_WORDS[v] ?? v.replace(/_/g, " ");
}

/** Text for one cell; null is a gap ("—"), never zero. */
export function cellText(v: unknown, col: VisualColumn, row: Row, lang: Lang = "en"): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return isUrdu(lang) ? (v ? "ہاں" : "نہیں") : v ? "Yes" : "No";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    const u = unitOf(col, row);
    if (u === "count") return formatNumber(v, autoDigits(v));
    return u ? formatWithUnit(v, u) : formatNumber(v, autoDigits(v));
  }
  const s = String(v);
  if (col.kind === "date") return formatDate(s);
  if (col.kind === "status") return statusWord(s);
  if (col.kind === "id" && col.ref !== "field") return shortId(s);
  if (col.kind === "id" && col.ref === "field") return s.replace(/^[^:]+:/, "");
  return s;
}

/** Compact axis ticks for a unit (PKR in lakh/crore, kg as t, ratios as %). */
export function axisFormatter(unit: string | null | undefined, maxAbs = 0): (v: number) => string {
  switch (unit) {
    case "PKR":
      return (v) => formatPKRCompact(v).replace("PKR ", "");
    case "kg":
      // Display conversion only (lib/formatting does the same): one unit along the whole axis.
      return maxAbs >= 10_000 ? (v) => `${formatNumber(v / 1000, Math.abs(v) < 10_000 && v !== 0 ? 1 : 0)} t` : (v) => formatMass(v);
    case "ratio":
    case "fraction":
      return (v) => formatPercent(v);
    case "m3":
      return (v) => formatVolume(v);
    default:
      return (v) => formatNumber(v, autoDigits(v));
  }
}

/** Axis title only when the tick labels do not already carry the unit. */
export function axisName(unit: string | null | undefined): string {
  if (!unit || ["kg", "ratio", "fraction", "m3", "count"].includes(unit)) return "";
  return displayUnit(unit);
}

/** Tab-separated copy of the rows exactly as served (header carries units). */
export function toTSV(cols: VisualColumn[], rows: Row[]): string {
  const head = cols.map((c) => (c.unit ? `${c.label} [${c.unit}]` : c.label)).join("\t");
  const body = rows.map((r) =>
    cols
      .map((c) => {
        const v = r[c.key];
        if (v === null || v === undefined) return "";
        const u = c.unit_column ? r[c.unit_column] : null;
        return typeof u === "string" && typeof v === "number" ? `${v} ${u}` : String(v);
      })
      .join("\t"),
  );
  return [head, ...body].join("\n");
}

export const BASIS_TEXT: Record<string, { en: string; tone: "warning" | "neutral" | "water" | "vegetation" }> = {
  model_output: { en: "Crop-model estimate", tone: "neutral" },
  computed_from_inputs: { en: "Water & cost books", tone: "water" },
  assumption: { en: "Uses assumptions", tone: "warning" },
  observed: { en: "Observed (imagery)", tone: "vegetation" },
  surrogate_preview: { en: "Quick preview", tone: "warning" },
  solver_result: { en: "Optimizer result", tone: "water" },
};

export const PLAN_TOKEN: Record<string, string> = { B0: "--plan-b0", B1: "--plan-b1", P: "--plan-p", R: "--plan-r" };
export const PLAN_PLAIN: Record<string, string> = {
  B0: GLOSSARY.B0.plain,
  B1: GLOSSARY.B1.plain,
  P: GLOSSARY.P.plain,
  R: GLOSSARY.R.plain,
};
