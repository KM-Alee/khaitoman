import { useMemo, useState } from "react";
import { Play, Plus, X } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useRun } from "@/lib/api/queries";
import type { SolverStatus } from "@/lib/api/types";
import { formatDateTime, formatPKR, formatPKRCompact, formatPercent, formatWithUnit, shortId } from "@/lib/formatting";
import { parsePKR } from "@/lib/units";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, SolverBadge, Skeleton, StatePanel, JobBadge } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Eyebrow } from "@/components/ui/primitives";
import { useScenario } from "@/features/workspace/useScenario";
import { pickNum, useAnalysisRunner, useCurrentAnalysis } from "./analysis";

export interface FrontierPoint {
  runId: string | null;
  status: SolverStatus | string;
  capex: number | null;
  production: number | null;
  minService: number | null;
  nondominated: boolean;
  gap: number | null;
  setting: Record<string, unknown>;
  executedAt: string | null;
}

export function readPoints(a: Record<string, unknown> | undefined): FrontierPoint[] {
  const pts = (a?.points as Record<string, unknown>[] | undefined) ?? [];
  return pts.map((p) => {
    const setting = (p.setting ?? p.settings ?? {}) as Record<string, unknown>;
    return {
      runId: (p.run_id as string | undefined) ?? null,
      status: String(p.solver_status ?? p.status ?? "UNKNOWN"),
      capex: pickNum(p, "capex_pkr", "capital_commitment_pkr", "capital_pkr"),
      production: pickNum(p, "production_kg", "objective_value", "worst_tested_production_kg"),
      minService: pickNum(p, "min_service_ratio", "minimum_service_ratio", "tail_min_service"),
      nondominated: p.nondominated === true || p.pareto === true,
      gap: pickNum(p, "relative_gap"),
      setting,
      executedAt: (p.executed_at as string | undefined) ?? (p.created_at as string | undefined) ?? null,
    };
  });
}

const DEFAULT_BUDGETS = [0, 500_000, 1_000_000, 2_000_000, 3_500_000, 5_000_000];

export function Frontier({ onHighlight }: { onHighlight: (runId: string | null) => void }) {
  const sel = useSelection();
  const s = useScenario();
  const cur = useCurrentAnalysis("frontier");
  const runner = useAnalysisRunner("frontier");
  const [budgets, setBudgets] = useState<number[]>(DEFAULT_BUDGETS);
  const [floor, setFloor] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const points = useMemo(() => readPoints(cur.data), [cur.data]);
  const status = String(cur.data?.status ?? "");
  const t = chartTokens();

  const plotted = points.filter((p) => p.capex !== null && p.production !== null && (p.status === "OPTIMAL" || p.status === "FEASIBLE"));
  const noPlan = points.filter((p) => !(p.status === "OPTIMAL" || p.status === "FEASIBLE"));
  const front = plotted.filter((p) => p.nondominated).sort((a, b) => a.capex! - b.capex!);

  const option = useMemo(() => {
    const b = baseOption();
    return {
      ...b,
      grid: { left: 64, right: 24, top: 24, bottom: 44 },
      tooltip: { ...(b.tooltip as object), trigger: "item", formatter: (p: { data: { p: FrontierPoint } }) => tooltipFor(p.data.p) },
      xAxis: { ...(b.xAxis as object), type: "value", name: "Capital commitment (PKR)", nameLocation: "middle", nameGap: 28, axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatPKRCompact(v).replace("PKR ", "") }, splitLine: { show: true, lineStyle: { color: t.border, opacity: 0.5 } } },
      yAxis: { ...(b.yAxis as object), type: "value", name: "Modeled production (kg)", scale: true, axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatWithUnit(v, "kg") } },
      series: [
        {
          type: "line",
          name: "Visual guide between nondominated evaluated plans",
          data: front.map((p) => [p.capex, p.production]),
          showSymbol: false,
          lineStyle: { color: t.water, width: 1.5, type: "dashed", opacity: 0.7 },
          silent: true,
          z: 1,
        },
        {
          type: "scatter",
          name: "Evaluated settings",
          data: plotted.map((p) => ({
            value: [p.capex, p.production],
            p,
            symbolSize: p.runId === selected ? 18 : p.nondominated ? 14 : 9,
            itemStyle: {
              color: p.nondominated ? t.water : t.surface,
              borderColor: p.nondominated ? t.waterDeep : t.ink3,
              borderWidth: p.runId === selected ? 3 : 1.5,
              opacity: p.nondominated ? 1 : 0.75,
            },
          })),
          z: 3,
          emphasis: { scale: 1.2 },
        },
      ],
    };
  }, [plotted, front, selected, t]);

  const pick = (p: FrontierPoint | undefined) => {
    if (!p?.runId) return;
    setSelected(p.runId);
    onHighlight(p.runId);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="frontier">
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Resilience frontier</h2>
            <p className="mt-0.5 max-w-[60ch] text-[12px] text-ink-secondary">
              Each setting is an independent solve over the same candidate science. “Nondominated among evaluated plans” — time-limited points do not establish a complete Pareto frontier.
            </p>
          </div>
          {cur.data ? <JobOrStatus status={status} /> : null}
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Eyebrow className="w-full">Capital budget settings ({budgets.length})</Eyebrow>
          {budgets.map((b, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-muted py-0.5 pl-2.5 pr-1 text-[12px] text-ink">
              <input
                aria-label={`Budget setting ${i + 1} (PKR)`}
                className="num w-[86px] bg-transparent text-right outline-none"
                defaultValue={formatPKR(b).replace("PKR ", "")}
                onBlur={(e) => {
                  const v = parsePKR(e.target.value);
                  if (v === null) return;
                  setBudgets((xs) => xs.map((x, j) => (j === i ? v : x)));
                }}
              />
              <IconButton label={`Remove budget ${i + 1}`} size="sm" className="h-6 w-6" onClick={() => setBudgets((xs) => xs.filter((_, j) => j !== i))}>
                <X size={12} />
              </IconButton>
            </span>
          ))}
          <Button size="sm" variant="ghost" icon={<Plus size={13} />} onClick={() => setBudgets((xs) => [...xs, (xs[xs.length - 1] ?? 0) + 1_000_000])}>
            Add
          </Button>
          <label className="ml-2 flex items-center gap-1.5 text-[12px] text-ink-secondary">
            Tail service floor
            <select className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[13px] text-ink" value={floor ?? ""} onChange={(e) => setFloor(e.target.value === "" ? null : Number(e.target.value))}>
              <option value="">None</option>
              {[0.3, 0.4, 0.5, 0.6].map((v) => (
                <option key={v} value={v}>
                  {formatPercent(v)}
                </option>
              ))}
            </select>
          </label>
          <Button
            size="sm"
            variant="primary"
            className="ml-auto"
            icon={<Play size={13} />}
            busy={runner.pending}
            disabled={!s.active || budgets.length < 6}
            title={!s.active ? "Run a plan first: the frontier derives from the active revision" : budgets.length < 6 ? "At least six settings" : undefined}
            onClick={() =>
              void runner.run({
                base_revision_id: s.active!.revisionId,
                settings: budgets.map((b) => ({ capital_budget_pkr: b, ...(floor !== null ? { minimum_service_ratio: floor, service_group: "tail" } : {}) })),
              })
            }
            data-testid="run-frontier"
          >
            Evaluate {budgets.length} settings
          </Button>
        </div>
      </section>

      {cur.loading ? (
        <Skeleton className="h-80" />
      ) : cur.error ? (
        <StatePanel state="error" error={cur.error} title="Frontier unavailable" />
      ) : !cur.data ? (
        <StatePanel state="empty" title="No frontier evaluated yet">
          {s.active ? "Choose at least six capital settings and evaluate them. Each point becomes an immutable run you can open." : "Run a plan in Workspace first; the frontier sweeps budgets around that revision."}
        </StatePanel>
      ) : (
        <>
          <ChartPanel
            id="frontier-chart"
            title="Capital commitment vs modeled production"
            summary={`${plotted.length} plans with results · ${front.length} nondominated · ${noPlan.length} without a plan. Click a point to open its run and highlight its portfolio.`}
            chart={<EChart option={option} height={340} ariaLabel="Frontier scatter of capital commitment against modeled production" onEvents={{ click: (p) => pick((p as { data?: { p?: FrontierPoint } }).data?.p) }} />}
            table={
              <DataTable
                caption="Frontier settings"
                columns={[
                  { key: "setting", label: "Budget setting" },
                  { key: "status", label: "Status" },
                  { key: "capex", label: "Capital committed", align: "right" },
                  { key: "prod", label: "Production", align: "right" },
                  { key: "svc", label: "Min service", align: "right" },
                  { key: "nd", label: "Nondominated" },
                  { key: "run", label: "Run" },
                ]}
                rows={points.map((p) => ({
                  setting: formatPKRCompact(Number(p.setting.capital_budget_pkr ?? NaN)),
                  status: <SolverBadge status={(p.status as SolverStatus) ?? "UNKNOWN"} size="sm" />,
                  capex: p.capex !== null ? formatPKR(p.capex) : "—",
                  prod: p.production !== null ? formatWithUnit(p.production, "kg") : "no plan",
                  svc: p.minService !== null ? formatPercent(p.minService) : "—",
                  nd: p.nondominated ? "Yes" : "—",
                  run: p.runId ? (
                    <button type="button" className="font-mono text-[11px] text-water hover:underline" onClick={() => pick(p)}>
                      {shortId(p.runId)}
                    </button>
                  ) : (
                    "—"
                  ),
                }))}
              />
            }
          />
          {noPlan.length ? (
            <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
              <Eyebrow className="mb-2">Settings without a plan (shown separately, never plotted as outcomes)</Eyebrow>
              <ul className="flex flex-wrap gap-2">
                {noPlan.map((p, i) => (
                  <li key={i} className="flex items-center gap-2 rounded-[10px] bg-surface-muted px-3 py-1.5 text-[12px]">
                    <span className="num text-ink">{formatPKRCompact(Number(p.setting.capital_budget_pkr ?? NaN))}</span>
                    <SolverBadge status={(p.status as SolverStatus) ?? "UNKNOWN"} size="sm" />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {selected ? <SelectedPoint runId={selected} onOpen={() => sel.setParams({ run: selected })} /> : null}
        </>
      )}
    </div>
  );
}

function tooltipFor(p: FrontierPoint) {
  return [
    `<b>${p.nondominated ? "Nondominated" : "Dominated"} · ${p.status}</b>`,
    `Capital: ${p.capex !== null ? formatPKR(p.capex) : "—"}`,
    `Production: ${p.production !== null ? formatWithUnit(p.production, "kg") : "—"}`,
    p.minService !== null ? `Min service: ${formatPercent(p.minService)}` : "",
    p.gap !== null ? `Gap: ${formatPercent(p.gap, 1)}` : "",
    p.executedAt ? `Executed ${formatDateTime(p.executedAt)}` : "",
    p.runId ? `Run ${shortId(p.runId)}` : "",
  ]
    .filter(Boolean)
    .join("<br/>");
}

function JobOrStatus({ status }: { status: string }) {
  if (status === "running" || status === "queued") return <JobBadge state={status as "running"} size="md" />;
  if (status === "succeeded" || status === "completed") return <Chip tone="vegetation">Completed</Chip>;
  if (status === "partial") return <Chip tone="warning">Partially complete</Chip>;
  if (status === "failed") return <Chip tone="danger">Failed</Chip>;
  return status ? <Chip>{status}</Chip> : null;
}

function SelectedPoint({ runId, onOpen }: { runId: string; onOpen: () => void }) {
  const run = useRun(runId);
  if (run.isLoading) return <Skeleton className="h-20" />;
  if (!run.data) return null;
  const r = run.data;
  return (
    <section className="flex flex-wrap items-center gap-3 rounded-[14px] border border-water/30 bg-water-soft/50 px-4 py-3" data-testid="frontier-selected">
      <div>
        <div className="text-[12px] text-ink-secondary">Selected point · run {shortId(r.run_id)}</div>
        <div className="text-[13px] font-semibold text-ink">
          {r.outcome === "plan" ? `${r.selected_intervention_instance_ids.length} investment${r.selected_intervention_instance_ids.length === 1 ? "" : "s"} in portfolio` : "No plan"}
        </div>
      </div>
      <SolverBadge status={r.solver_status} />
      <Button size="sm" variant="secondary" className="ml-auto" onClick={onOpen}>
        Open this run
      </Button>
    </section>
  );
}
