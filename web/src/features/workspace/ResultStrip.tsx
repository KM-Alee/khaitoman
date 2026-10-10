import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, History, Info, ShieldAlert } from "lucide-react";
import { findMetric, runMetrics } from "@/lib/api/adapters";
import { useComparison, useRun } from "@/lib/api/queries";
import type { RunResult } from "@/lib/api/types";
import { formatDuration, formatPercent, shortId, titleCase } from "@/lib/formatting";
import { Chip, MetricValueView, SolverBadge, Skeleton, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

/** Headline run metrics in reading order; first match wins per row. */
export const HEADLINE: { key: string; label: string; ids: string[]; goodWhen: "up" | "down" | "neutral" }[] = [
  { key: "production", label: "Modeled production", ids: ["production_kg", "modeled_production_kg", "total_production_kg"], goodWhen: "up" },
  { key: "tail", label: "Tail minimum service", ids: ["tail_min_service", "tail_min_service_ratio", "min_tail_service_ratio"], goodWhen: "up" },
  { key: "groundwater", label: "Groundwater pumped", ids: ["groundwater_m3", "total_groundwater_m3", "pumping_m3"], goodWhen: "neutral" },
  { key: "withdrawal", label: "Withdrawal productivity", ids: ["withdrawal_productivity_kg_m3"], goodWhen: "up" },
  { key: "capex", label: "Capital committed", ids: ["capex_pkr", "capital_commitment_pkr", "gross_project_cost_pkr"], goodWhen: "neutral" },
  { key: "opex", label: "Seasonal operating cost", ids: ["seasonal_opex_pkr", "operating_cost_pkr", "operating_expenditure_pkr"], goodWhen: "neutral" },
  { key: "worse", label: "Fields worse off", ids: ["fields_worse_off", "fields_worse_off_count"], goodWhen: "down" },
];

export function headlineMetrics(run: RunResult | null | undefined) {
  const ms = runMetrics(run);
  return HEADLINE.map((h) => ({ ...h, metric: findMetric(ms, ...h.ids) }));
}

export type ResultState = "none" | "current" | "stale" | "draft";

export function ResultBar({ state, runId, revisionId, onRun }: { state: ResultState; runId: string | null; revisionId: string | null; onRun: () => void }) {
  if (state === "current" || state === "none") return null;
  return (
    <div
      role="status"
      data-testid="result-bar"
      data-state={state}
      className={cn(
        "flex items-center gap-2 rounded-[12px] border px-3 py-2 text-[13px] shadow-2 backdrop-blur",
        state === "draft" ? "border-warning/40 bg-warning-soft/95 text-warning" : "border-border-strong/50 bg-surface/95 text-ink-secondary",
      )}
    >
      {state === "draft" ? <AlertTriangle size={15} aria-hidden /> : <History size={15} aria-hidden />}
      <span className="min-w-0 flex-1">
        {state === "draft" ? (
          <>
            <strong className="font-semibold">Inputs changed — run again.</strong> The map shows run {shortId(runId)} from the previous inputs.
          </>
        ) : (
          <>
            <strong className="font-semibold text-ink">Stale result.</strong> Run {shortId(runId)} belongs to an earlier revision{revisionId ? ` (current ${shortId(revisionId)})` : ""}.
          </>
        )}
      </span>
      <Button size="sm" variant={state === "draft" ? "primary" : "secondary"} onClick={onRun}>
        Run again
      </Button>
    </div>
  );
}

export function ResultStrip({ runId, baselineRunId, className }: { runId: string | null; baselineRunId?: string | null; className?: string }) {
  const run = useRun(runId);
  const base = useRun(baselineRunId && baselineRunId !== runId ? baselineRunId : null);
  const rows = useMemo(() => headlineMetrics(run.data), [run.data]);
  const cmp = useComparison(baselineRunId && runId && baselineRunId !== runId ? [baselineRunId, runId] : []);
  const deltas = useMemo(() => comparisonDeltas(cmp.data, baselineRunId ?? null), [cmp.data, baselineRunId]);

  if (!runId)
    return (
      <div className={cn("rounded-[14px] border border-border bg-surface/95 px-4 py-3 shadow-2 backdrop-blur", className)} data-testid="result-strip" data-state="empty">
        <div className="flex items-start gap-2 text-[13px] text-ink-secondary">
          <Info size={15} className="mt-0.5 shrink-0 text-water" aria-hidden />
          <p>
            No result yet. Review the inputs, then <strong className="font-semibold text-ink">Run plan</strong> to solve the fixed baseline, the no-capital plan and the integrated portfolio.
          </p>
        </div>
      </div>
    );
  if (run.isLoading)
    return (
      <div className={cn("flex gap-3 rounded-[14px] border border-border bg-surface/95 p-3 shadow-2", className)} data-testid="result-strip" data-state="busy" aria-busy>
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-12 flex-1" />
        ))}
      </div>
    );
  if (run.error || !run.data)
    return (
      <div className={className} data-testid="result-strip" data-state="error">
        <StatePanel compact state="error" error={run.error} title={`Run ${shortId(runId)} could not be loaded`} />
      </div>
    );
  const r = run.data;
  if (r.outcome !== "plan") {
    const diag = r.outcome === "no_plan" ? r : null;
    return (
      <div
        className={cn("rounded-[14px] border bg-surface/95 px-4 py-3 shadow-2 backdrop-blur", r.solver_status === "INFEASIBLE" ? "border-warning/40" : "border-border", className)}
        data-testid="result-strip"
        data-state={r.solver_status === "INFEASIBLE" ? "infeasible" : r.outcome === "invalid_plan" ? "error" : "unknown"}
      >
        <div className="flex flex-wrap items-center gap-3">
          <SolverBadge status={r.solver_status} />
          <span className="text-[13px] text-ink">
            {r.outcome === "invalid_plan"
              ? "The solver's incumbent failed original-precision validation (INVALID_PLAN). No recommendation is shown."
              : diag?.infeasibility_kind
                ? `${titleCase(diag.infeasibility_kind)} — no plan metrics exist for this run.`
                : "No plan metrics exist for this run."}
          </span>
          <Chip size="sm" tone="info">{r.plan_kind} · {shortId(r.run_id)}</Chip>
        </div>
        {diag && Object.keys(diag.diagnostics ?? {}).length ? (
          <ul className="mt-2 grid gap-1 text-[12px] text-ink-secondary sm:grid-cols-2">
            {Object.entries(diag.diagnostics)
              .slice(0, 6)
              .map(([k, v]) => (
                <li key={k}>
                  <span className="font-medium text-ink">{titleCase(k)}:</span> {typeof v === "object" ? JSON.stringify(v).slice(0, 120) : String(v)}
                </li>
              ))}
          </ul>
        ) : null}
      </div>
    );
  }
  const present = rows.filter((x) => x.metric);
  const shown = (present.length ? present : rows).slice(0, 6);
  return (
    <div className={cn("@container rounded-[14px] border border-border bg-surface/95 shadow-2 backdrop-blur", className)} data-testid="result-strip" data-state={r.solver_status === "OPTIMAL" ? "feasible" : "feasible"}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2">
        <span className="text-[12px] font-semibold text-ink">{r.plan_kind === "P" ? "Integrated plan" : r.plan_kind === "B1" ? "No new capital" : r.plan_kind === "B0" ? "Fixed-roster baseline" : "Robust plan"}</span>
        <SolverBadge status={r.solver_status} size="sm" />
        <ValidationChip run={r} />
        {r.relative_gap !== null && r.relative_gap !== undefined ? (
          <Chip size="sm" tone="info" title="Relative gap to the finite-library bound">
            gap {formatPercent(r.relative_gap, 1)}
          </Chip>
        ) : null}
        <span className="num ml-auto text-[11px] text-ink-tertiary" title={r.run_id}>
          run {shortId(r.run_id)} · {formatDuration(r.solve_wall_ms)} · proof scope: finite candidate library
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-b-[14px] bg-border @md:grid-cols-3 @4xl:grid-cols-6">
        {shown.map((h) => {
          const delta = h.ids.map((id) => deltas.get(id)).find(Boolean) ?? null;
          return (
            <div key={h.key} className="bg-surface px-4 py-2.5" data-metric={h.key}>
              <dt className="truncate text-[11px] font-medium text-ink-secondary" title={h.label}>{h.label}</dt>
              <dd className="mt-0.5">
                <MetricValueView metric={h.metric} size="md" delta={delta ? { ...delta, goodWhen: h.goodWhen } : null} showReason={false} />
              </dd>
            </div>
          );
        })}
      </dl>
      {base.data ? (
        <div className="border-t border-border px-4 py-1.5 text-[11px] text-ink-tertiary">
          {cmp.data
            ? `Deltas vs ${base.data.plan_kind} run ${shortId(base.data.run_id)} from the comparison service${cmp.data.compatible === false ? " — not a matched comparison (non-causal)" : ""}.`
            : `Baseline ${base.data.plan_kind} run ${shortId(base.data.run_id)}; comparison deltas unavailable.`}
        </div>
      ) : null}
    </div>
  );
}

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
    const id = d.definition_id ?? d.metric_id ?? "";
    const key = id.includes(":") ? id.split(":").pop()! : id;
    out.set(key, { value: d.delta, unit: d.unit ?? "" });
    out.set(id, { value: d.delta, unit: d.unit ?? "" });
  }
  return out;
}

function ValidationChip({ run }: { run: RunResult }) {
  if (run.outcome !== "plan") return null;
  const st = run.physical_validation?.status;
  if (st === "passed")
    return (
      <Chip size="sm" tone="vegetation" icon={<CheckCircle2 size={11} aria-hidden />} title="Original-precision ledger reconstruction passed">
        Physically validated
      </Chip>
    );
  return (
    <Chip size="sm" tone="warning" icon={<ShieldAlert size={11} aria-hidden />}>
      Validation {st ?? "unknown"}
    </Chip>
  );
}
