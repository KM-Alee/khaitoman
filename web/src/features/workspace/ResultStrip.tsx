/**
 * Headline metric definitions and server comparison deltas shared by Plan, Compare and the
 * tour. The ids are the server's metric definition ids; labels come from lib/glossary.
 */
import type { RunResult } from "@/lib/api/types";
import { findMetric, runMetrics } from "@/lib/api/adapters";
import type { TermId } from "@/lib/glossary";

/** Headline run metrics in reading order; first match wins per row. */
export const HEADLINE: { key: string; label: string; plain: string; term: TermId; ids: string[]; goodWhen: "up" | "down" | "neutral" }[] = [
  { key: "production", label: "Modeled production", plain: "Crop harvested", term: "production", ids: ["production_kg", "modeled_production_kg", "total_production_kg"], goodWhen: "up" },
  { key: "tail", label: "Tail minimum service", plain: "Tail-end fields' fair share", term: "tailService", ids: ["tail_min_service", "tail_min_service_ratio", "min_tail_service_ratio"], goodWhen: "up" },
  { key: "groundwater", label: "Groundwater pumped", plain: "Groundwater pumped", term: "groundwater", ids: ["groundwater_m3", "total_groundwater_m3", "pumping_m3"], goodWhen: "neutral" },
  { key: "withdrawal", label: "Withdrawal productivity", plain: "Crop per drop", term: "productivity", ids: ["withdrawal_productivity_kg_m3"], goodWhen: "up" },
  { key: "capex", label: "Capital committed", plain: "Money for new works", term: "capex", ids: ["capex_pkr", "capital_commitment_pkr", "gross_project_cost_pkr"], goodWhen: "neutral" },
  { key: "opex", label: "Seasonal operating cost", plain: "Running cost this season", term: "opex", ids: ["seasonal_opex_pkr", "operating_cost_pkr", "operating_expenditure_pkr"], goodWhen: "neutral" },
  { key: "worse", label: "Fields worse off", plain: "Fields worse off", term: "worse", ids: ["fields_worse_off", "fields_worse_off_count"], goodWhen: "down" },
];

export function headlineMetrics(run: RunResult | null | undefined) {
  const ms = runMetrics(run);
  return HEADLINE.map((h) => ({ ...h, metric: findMetric(ms, ...h.ids) }));
}

export function headline(run: RunResult | null | undefined, key: string) {
  return headlineMetrics(run).find((h) => h.key === key) ?? null;
}

export type ResultState = "none" | "current" | "stale" | "draft" | "saved";

export interface ComparisonDelta {
  metric_id?: string;
  definition_id?: string;
  field_id?: string | null;
  a?: number | null;
  b?: number | null;
  delta?: number | null;
  unit?: string;
  status?: string;
}

/** Run-level deltas from POST /comparisons, keyed by definition id (server-computed). */
export function comparisonDeltas(cmp: Record<string, unknown> | undefined, _baseline: string | null) {
  const out = new Map<string, { value: number; unit: string }>();
  const list = (cmp?.deltas as ComparisonDelta[] | undefined) ?? [];
  for (const d of list) {
    if (d.field_id) continue;
    if (typeof d.delta !== "number" || (d.status && d.status !== "available")) continue;
    // Keyed by every name a caller may use: metric id, definition id, and the definition id
    // without its `@metrics-x.y.z` version or `namespace:` prefix.
    const v = { value: d.delta, unit: d.unit ?? "" };
    for (const id of [d.metric_id, d.definition_id]) {
      if (!id) continue;
      out.set(id, v);
      const bare = id.split("@")[0];
      out.set(bare, v);
      if (bare.includes(":")) out.set(bare.split(":").pop()!, v);
    }
  }
  return out;
}

/** Server delta for a headline row (first id that the comparison service returned). */
export function deltaFor(deltas: Map<string, { value: number; unit: string }>, ids: string[]) {
  return ids.map((id) => deltas.get(id)).find(Boolean) ?? null;
}
