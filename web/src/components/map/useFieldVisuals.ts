import { useMemo } from "react";
import type { MapMetric } from "@/app/store";
import { fieldMetricMap, runMetrics } from "@/lib/api/adapters";
import { useComparison, useRun } from "@/lib/api/queries";
import type { MetricValue } from "@/lib/api/types";
import type { FieldIndexEntry } from "@/app/pilotData";
import { GROUP_COLORS, makeScale, type Scale } from "./palette";
import type { FieldVisual } from "./engine";

export const METRIC_DEFS: Record<
  Exclude<MapMetric, "none">,
  { label: string; short: string; ids: string[]; unit: string; scale: "sequential-yield" | "sequential-service" | "diverging" | "categorical" }
> = {
  yield: { label: "Modeled yield", short: "Yield", ids: ["yield_kg_ha", "field_yield_kg_ha", "exact_yield_kg_ha"], unit: "kg/ha", scale: "sequential-yield" },
  service: {
    label: "Service ratio (receipt / reference allowance)",
    short: "Service",
    ids: ["field_service_ratio", "service_ratio"],
    unit: "fraction",
    scale: "sequential-service",
  },
  change: {
    label: "Yield change vs baseline",
    short: "Change",
    ids: ["yield_kg_ha", "field_yield_kg_ha", "production_kg", "field_production_kg"],
    unit: "kg/ha",
    scale: "diverging",
  },
  group: { label: "Head / middle / tail group", short: "Group", ids: [], unit: "", scale: "categorical" },
};

export interface FieldVisualResult {
  visuals: Map<string, FieldVisual>;
  values: Map<string, MetricValue | { value: number | null; unit: string; status: string }>;
  scale: Scale | null;
  status: "ready" | "no-run" | "loading" | "unavailable" | "no-baseline";
  reason: string | null;
  unit: string;
}

/** Map server per-field metrics to colour/height. `sharedDomain` keeps compared maps on one scale. */
export function useFieldVisuals(args: {
  runId: string | null;
  baselineRunId?: string | null;
  metric: MapMetric;
  fields: Map<string, FieldIndexEntry>;
  sharedDomain?: [number, number] | null;
}): FieldVisualResult {
  const { runId, baselineRunId, metric, fields, sharedDomain } = args;
  const run = useRun(metric === "group" || metric === "none" ? null : runId);
  const comparing = metric === "change" && !!runId && !!baselineRunId && baselineRunId !== runId;
  const cmp = useComparison(comparing ? [baselineRunId!, runId!] : []);

  return useMemo<FieldVisualResult>(() => {
    const empty = (status: FieldVisualResult["status"], reason: string | null): FieldVisualResult => ({
      visuals: new Map(),
      values: new Map(),
      scale: null,
      status,
      reason,
      unit: "",
    });
    if (metric === "none") return empty("ready", null);
    if (metric === "group") {
      const colors = GROUP_COLORS();
      const v = new Map<string, FieldVisual>();
      const order = { head: 0.85, middle: 0.55, tail: 0.25 } as const;
      for (const [id, f] of fields) {
        v.set(id, { value: null, color: f.group ? colors[f.group] : "#999999", norm: f.group ? order[f.group] : 0 });
      }
      return { visuals: v, values: new Map(), scale: null, status: "ready", reason: null, unit: "" };
    }
    if (!runId) return empty("no-run", "Run a plan or open a stored run to colour fields by result.");
    if (run.isLoading) return empty("loading", null);
    if (run.error || !run.data) return empty("unavailable", "Run could not be loaded.");
    if (run.data.outcome !== "plan") return empty("unavailable", "This run has no plan, so no field results exist.");
    const def = METRIC_DEFS[metric];
    let byField: Map<string, { value: number | null; unit: string; status: string }>;
    if (metric === "change") {
      if (!baselineRunId || baselineRunId === runId) return empty("no-baseline", "Choose a baseline run to show change.");
      if (cmp.isLoading) return empty("loading", null);
      const deltas = ((cmp.data?.deltas as unknown[]) ?? []) as {
        metric_id?: string;
        definition_id?: string;
        field_id?: string | null;
        delta?: number | null;
        unit?: string;
        status?: string;
      }[];
      byField = new Map();
      for (const d of deltas) {
        if (!d.field_id) continue;
        const id = d.definition_id ?? d.metric_id ?? "";
        if (!def.ids.some((x) => id === x || id.endsWith(`:${x}`))) continue;
        if (!byField.has(d.field_id) || id.includes("yield"))
          byField.set(d.field_id, { value: typeof d.delta === "number" ? d.delta : null, unit: d.unit ?? def.unit, status: d.status ?? "available" });
      }
      if (!byField.size) return empty("unavailable", cmp.error ? "Comparison failed." : "The comparison returned no per-field deltas.");
    } else {
      const m = fieldMetricMap(runMetrics(run.data), ...def.ids);
      byField = new Map(
        [...m.entries()].map(([k, v]) => [k, { value: v.status === "available" ? v.value : null, unit: v.unit, status: v.status }]),
      );
      if (!byField.size) return empty("unavailable", `This run reports no per-field ${def.short.toLowerCase()} metric.`);
    }
    const nums = [...byField.values()].map((v) => v.value).filter((v): v is number => typeof v === "number");
    const scale = makeScale(def.scale === "categorical" ? "sequential-yield" : def.scale, nums, sharedDomain ?? null);
    const visuals = new Map<string, FieldVisual>();
    for (const id of fields.keys()) {
      const v = byField.get(id)?.value ?? null;
      visuals.set(id, { value: v, color: scale.color(v), norm: v === null ? 0 : scale.norm(v) });
    }
    return { visuals, values: byField, scale, status: "ready", reason: null, unit: [...byField.values()][0]?.unit ?? def.unit };
  }, [metric, runId, baselineRunId, run.data, run.isLoading, run.error, cmp.data, cmp.isLoading, cmp.error, fields, sharedDomain]);
}
