import { useMemo, useState } from "react";
import { ArrowRight, BadgeCheck, Columns2, PlayCircle, SplitSquareHorizontal, TriangleAlert } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI, type MapMetric } from "@/app/store";
import { useComparison, useRuns } from "@/lib/api/queries";
import type { PlanKind, RunResult } from "@/lib/api/types";
import { fieldMetricMap, runMetrics } from "@/lib/api/adapters";
import { formatWithUnit, formatDelta, shortId, titleCase } from "@/lib/formatting";
import { MapSlot } from "@/components/map/MapSlot";
import { SecondaryMap } from "@/components/map/SecondaryMap";
import { METRIC_DEFS } from "@/components/map/useFieldVisuals";
import { niceDomain } from "@/components/map/palette";
import { Chip, MetricValueView, SolverBadge, Skeleton, StatePanel } from "@/components/status";
import { Segmented, Eyebrow } from "@/components/ui/primitives";
import { Button } from "@/components/ui/Button";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { HEADLINE, comparisonDeltas, headlineMetrics } from "@/features/workspace/ResultStrip";
import { PLAN_LABEL, useScenario } from "@/features/workspace/useScenario";
import { useShell } from "@/components/layout/AppShell";
import { cn } from "@/lib/cn";
import { CompareTabs } from "./CompareTabs";

const ORDER: PlanKind[] = ["B0", "B1", "P", "R"];

export function useLadderRuns() {
  const { sel } = usePilotData();
  const s = useScenario();
  const ids = useMemo(() => {
    const fromUrl = sel.compareRunIds;
    if (fromUrl.length) return fromUrl;
    const r = s.revisionRuns;
    return ORDER.map((k) => r[k]).filter(Boolean) as string[];
  }, [sel.compareRunIds, s.revisionRuns]);
  const runs = useRuns(ids);
  const byKind = useMemo(() => {
    const m = new Map<PlanKind, RunResult>();
    for (const r of runs.data ?? []) if (!m.has(r.plan_kind)) m.set(r.plan_kind, r);
    return m;
  }, [runs.data]);
  return { ids, runs, byKind };
}

export function CompareScreen() {
  const { sel } = usePilotData();
  const { mobile } = useShell();
  const { ids, runs, byKind } = useLadderRuns();
  const [view, setView] = useState<"paired" | "swipe">(mobile ? "swipe" : "paired");
  const [metric, setMetric] = useState<MapMetric>("yield");
  const kinds = ORDER.filter((k) => byKind.has(k));
  const [left, setLeft] = useState<PlanKind | null>(null);
  const [right, setRight] = useState<PlanKind | null>(null);
  const l = left && byKind.has(left) ? left : kinds.includes("B1") ? "B1" : kinds[0] ?? null;
  const r = right && byKind.has(right) ? right : kinds.includes("P") ? "P" : kinds[kinds.length - 1] ?? null;
  const leftRun = l ? byKind.get(l)! : null;
  const rightRun = r ? byKind.get(r)! : null;
  const cmp = useComparison(leftRun && rightRun && leftRun.run_id !== rightRun.run_id ? [leftRun.run_id, rightRun.run_id] : []);

  // Common colour domain across both maps (T10.4: common scales across comparisons)
  const shared = useMemo<[number, number] | null>(() => {
    if (metric === "group" || metric === "change" || metric === "none") return null;
    const def = METRIC_DEFS[metric];
    const vals: number[] = [];
    for (const run of [leftRun, rightRun]) {
      if (!run) continue;
      for (const m of fieldMetricMap(runMetrics(run), ...def.ids).values()) if (m.status === "available" && typeof m.value === "number") vals.push(m.value);
    }
    return vals.length ? niceDomain(vals, def.scale === "categorical" ? "sequential-yield" : def.scale) : null;
  }, [metric, leftRun, rightRun]);

  if (!ids.length)
    return (
      <div className="flex flex-1 flex-col">
        <CompareTabs />
        <div className="grid flex-1 place-items-center p-6">
          <div className="max-w-[520px]">
            <StatePanel state="empty" title="Nothing to compare yet" action={{ label: "Go to Workspace and run a plan", onClick: () => sel.go("workspace") }}>
              Compare shows the fixed-roster baseline (B0), the optimized no-capital plan (B1) and the integrated portfolio (P) solved under the same conditions.
            </StatePanel>
          </div>
        </div>
      </div>
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="compare">
      <CompareTabs />
      <div className="flex flex-col gap-4 p-3 md:p-4">
        <Ladder byKind={byKind} loading={runs.isLoading} error={runs.error} />
        <Compatibility cmp={cmp.data} loading={cmp.isLoading} error={cmp.error} leftRun={leftRun} rightRun={rightRun} />

        <section className="overflow-hidden rounded-[14px] border border-border bg-surface shadow-1" aria-label="Paired maps">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
            <PlanPicker label="Left" value={l} kinds={kinds} onChange={setLeft} />
            <ArrowRight size={14} className="text-ink-tertiary" aria-hidden />
            <PlanPicker label="Right" value={r} kinds={kinds} onChange={setRight} />
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Segmented<MapMetric>
                label="Map metric"
                size="sm"
                value={metric}
                onChange={setMetric}
                options={(["yield", "service", "group"] as const).map((k) => ({ value: k, label: METRIC_DEFS[k].short }))}
              />
              <Segmented
                label="Comparison layout"
                size="sm"
                value={view}
                onChange={(v) => setView(v as "paired" | "swipe")}
                options={[
                  { value: "paired", label: <><Columns2 size={13} aria-hidden /> Paired</> },
                  { value: "swipe", label: <><SplitSquareHorizontal size={13} aria-hidden /> Swipe</> },
                ]}
              />
            </div>
          </div>
          <PairedMaps view={view} metric={metric} shared={shared} leftRun={leftRun} rightRun={rightRun} mobile={mobile} />
        </section>

        <Distribution leftRun={leftRun} rightRun={rightRun} cmp={cmp.data} />
      </div>
    </div>
  );
}

function PlanPicker({ label, value, kinds, onChange }: { label: string; value: PlanKind | null; kinds: PlanKind[]; onChange: (k: PlanKind) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-ink-secondary">
      {label}
      <select
        className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[13px] font-medium text-ink"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value as PlanKind)}
      >
        {kinds.map((k) => (
          <option key={k} value={k}>
            {k} · {PLAN_LABEL[k]}
          </option>
        ))}
      </select>
    </label>
  );
}

function PairedMaps({
  view,
  metric,
  shared,
  leftRun,
  rightRun,
  mobile,
}: {
  view: "paired" | "swipe";
  metric: MapMetric;
  shared: [number, number] | null;
  leftRun: RunResult | null;
  rightRun: RunResult | null;
  mobile: boolean;
}) {
  const [split, setSplit] = useState(50);
  const h = mobile ? "h-[62vh]" : "h-[min(58vh,620px)]";
  if (view === "paired" && !mobile)
    return (
      <div className={cn("grid grid-cols-2 gap-px bg-border", h)}>
        <div className="relative">
          <MapSlot runId={leftRun?.run_id ?? null} metric={metric} sharedDomain={shared} className="absolute inset-0" compactControls label={`Left map: ${leftRun?.plan_kind ?? "none"}`}>
            <MapTag run={leftRun} side="left" />
          </MapSlot>
        </div>
        <div className="relative overflow-hidden bg-[var(--map-bg)]">
          <SecondaryMap runId={rightRun?.run_id ?? null} metric={metric} sharedDomain={shared} label={`Right map: ${rightRun?.plan_kind ?? "none"}`} />
          <MapTag run={rightRun} side="right" />
        </div>
      </div>
    );
  return (
    <div className={cn("relative", h)}>
      <MapSlot runId={leftRun?.run_id ?? null} metric={metric} sharedDomain={shared} className="absolute inset-0" compactControls label={`Swipe comparison, base: ${leftRun?.plan_kind ?? "none"}`}>
        <MapTag run={leftRun} side="left" />
      </MapSlot>
      <div className="pointer-events-none absolute inset-0 z-[15]" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <div className="pointer-events-auto absolute inset-0">
          <SecondaryMap runId={rightRun?.run_id ?? null} metric={metric} sharedDomain={shared} label={`Swipe overlay: ${rightRun?.plan_kind ?? "none"}`} />
        </div>
        <MapTag run={rightRun} side="right" />
      </div>
      <div className="pointer-events-none absolute inset-y-0 z-[16] w-0.5 bg-surface shadow-2" style={{ left: `${split}%` }} aria-hidden />
      <label className="absolute bottom-3 left-1/2 z-[17] flex w-[min(360px,80%)] -translate-x-1/2 items-center gap-2 rounded-full border border-border bg-surface/95 px-3 py-1.5 text-[12px] shadow-2 backdrop-blur">
        <span className="font-medium text-ink">{leftRun?.plan_kind}</span>
        <input type="range" min={5} max={95} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="flex-1 accent-[var(--water)]" aria-label="Swipe position" />
        <span className="font-medium text-ink">{rightRun?.plan_kind}</span>
      </label>
    </div>
  );
}

function MapTag({ run, side }: { run: RunResult | null; side: "left" | "right" }) {
  if (!run) return null;
  return (
    <div className={cn("pointer-events-none absolute top-3 z-20 rounded-[10px] bg-ink/90 px-2.5 py-1.5 text-[12px] font-semibold text-canvas shadow-2", side === "left" ? "left-3" : "right-14")}>
      {run.plan_kind} · {PLAN_LABEL[run.plan_kind]}
    </div>
  );
}

function Ladder({ byKind, loading, error }: { byKind: Map<PlanKind, RunResult>; loading: boolean; error: unknown }) {
  const { sel } = usePilotData();
  if (loading) return <Skeleton className="h-44" />;
  if (error) return <StatePanel state="error" error={error} title="Runs could not be loaded" />;
  const kinds = ORDER.filter((k) => byKind.has(k));
  const rows = HEADLINE;
  const metrics = new Map(kinds.map((k) => [k, headlineMetrics(byKind.get(k))]));
  return (
    <section className="overflow-hidden rounded-[14px] border border-border bg-surface shadow-1" aria-labelledby="ladder-h" data-testid="ladder">
      <header className="flex flex-wrap items-baseline justify-between gap-2 px-4 pb-2 pt-3.5">
        <div>
          <h2 id="ladder-h" className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Baseline ladder</h2>
          <p className="text-[12px] text-ink-secondary">B0 → B1 is operational gain; B1 → P is investment gain; P → R is the robustness trade-off.</p>
        </div>
        <Button size="sm" variant="secondary" icon={<PlayCircle size={14} />} onClick={() => sel.go("replay")}>
          Replay a field
        </Button>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-[13px]">
          <thead>
            <tr className="border-y border-border bg-surface-muted/60">
              <th scope="col" className="px-4 py-2 text-left text-[12px] font-medium text-ink-tertiary">
                Metric
              </th>
              {kinds.map((k) => {
                const run = byKind.get(k)!;
                return (
                  <th key={k} scope="col" className="px-4 py-2 text-right align-bottom">
                    <div className="text-[13px] font-semibold text-ink">{k}</div>
                    <div className="text-[11px] font-normal text-ink-secondary">{PLAN_LABEL[k]}</div>
                    <div className="mt-1 flex justify-end">
                      <SolverBadge status={run.solver_status} size="sm" />
                    </div>
                    <button type="button" className="num mt-1 font-mono text-[11px] font-normal text-water hover:underline" onClick={() => sel.setParams({ run: run.run_id })} title={run.run_id}>
                      {shortId(run.run_id)}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((h, i) => {
              if (!kinds.some((k) => metrics.get(k)![i].metric)) return null;
              return (
                <tr key={h.key} className="border-b border-border/70 last:border-0">
                  <th scope="row" className="px-4 py-2 text-left font-normal text-ink-secondary">
                    {h.label}
                  </th>
                  {kinds.map((k) => (
                    <td key={k} className="px-4 py-2 text-right">
                      {byKind.get(k)!.outcome === "plan" ? <MetricValueView metric={metrics.get(k)![i].metric} size="sm" showReason={false} /> : <span className="text-[12px] text-ink-tertiary">no plan</span>}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {kinds.length < 3 ? (
        <p className="border-t border-border px-4 py-2 text-[12px] text-ink-secondary">
          {ORDER.filter((k) => !byKind.has(k) && k !== "R").map((k) => `${k} (${PLAN_LABEL[k]})`).join(", ") || "R"} not solved for this revision yet.
        </p>
      ) : null}
    </section>
  );
}

function Compatibility({ cmp, loading, error, leftRun, rightRun }: { cmp?: Record<string, unknown>; loading: boolean; error: unknown; leftRun: RunResult | null; rightRun: RunResult | null }) {
  if (!leftRun || !rightRun || leftRun.run_id === rightRun.run_id) return null;
  if (loading) return <Skeleton className="h-16" />;
  if (error) return <StatePanel compact state="error" error={error} title="Compatibility check failed">The two runs cannot be presented as a matched comparison until the check succeeds.</StatePanel>;
  if (!cmp) return null;
  const compatible = cmp.compatible === true;
  const cert = (cmp.certificate ?? {}) as { shared?: unknown[]; differences?: unknown[] };
  const shared = (cert.shared ?? []).map(String);
  const diffs = (cert.differences ?? (cmp.differences as unknown[]) ?? []).map((d) => (typeof d === "string" ? d : JSON.stringify(d)));
  return (
    <section
      className={cn("rounded-[14px] border px-4 py-3", compatible ? "border-vegetation/30 bg-vegetation-soft/60" : "border-warning/40 bg-warning-soft/70")}
      data-testid="compatibility"
      data-compatible={compatible}
    >
      <div className="flex flex-wrap items-center gap-2">
        {compatible ? <BadgeCheck size={16} className="text-vegetation" aria-hidden /> : <TriangleAlert size={16} className="text-warning" aria-hidden />}
        <span className="text-[13px] font-semibold text-ink">
          {compatible ? `Matched comparison: ${leftRun.plan_kind} vs ${rightRun.plan_kind}` : `Not a matched comparison — differences are non-causal`}
        </span>
        {cmp.compatibility_key ? <Chip size="sm" tone="info">key {shortId(String(cmp.compatibility_key))}</Chip> : null}
      </div>
      {shared.length ? (
        <p className="mt-1 text-[12px] text-ink-secondary">
          Shared: {shared.slice(0, 8).map(titleCase).join(" · ")}
        </p>
      ) : null}
      {diffs.length ? (
        <p className="mt-1 text-[12px] text-ink-secondary">
          Differences: {diffs.slice(0, 6).join(" · ")}
        </p>
      ) : null}
    </section>
  );
}

function Distribution({ leftRun, rightRun, cmp }: { leftRun: RunResult | null; rightRun: RunResult | null; cmp?: Record<string, unknown> }) {
  const { fieldIndex, sel } = usePilotData();
  const areaUnit = useUI((s) => s.areaUnit);
  void areaUnit;
  const data = useMemo(() => {
    const list = ((cmp?.deltas as { field_id?: string | null; definition_id?: string; metric_id?: string; delta?: number | null; a?: number | null; b?: number | null; unit?: string; status?: string }[]) ?? []).filter(
      (d) => d.field_id && /yield/.test(d.definition_id ?? d.metric_id ?? ""),
    );
    return list
      .map((d) => ({ id: d.field_id!, label: fieldIndex.get(d.field_id!)?.label ?? d.field_id!, group: fieldIndex.get(d.field_id!)?.group ?? null, a: d.a ?? null, b: d.b ?? null, delta: typeof d.delta === "number" ? d.delta : null, unit: d.unit ?? "kg/ha" }))
      .sort((x, y) => (x.delta ?? -Infinity) - (y.delta ?? -Infinity));
  }, [cmp, fieldIndex]);
  const run = useMemo(() => comparisonDeltas(cmp, null), [cmp]);
  void run;
  if (!leftRun || !rightRun || leftRun.run_id === rightRun.run_id) return null;
  if (!data.length)
    return (
      <StatePanel state="empty" title="Field distribution unavailable">
        The comparison service returned no per-field yield deltas for {leftRun.plan_kind} → {rightRun.plan_kind}.
      </StatePanel>
    );
  const t = chartTokens();
  const worse = data.filter((d) => (d.delta ?? 0) < 0);
  const unit = data[0].unit;
  const option = {
    ...baseOption(),
    grid: { left: 56, right: 16, top: 16, bottom: 56 },
    tooltip: { ...(baseOption().tooltip as object), trigger: "axis", valueFormatter: (v: number) => formatDelta(v, unit) },
    xAxis: { ...(baseOption().xAxis as object), type: "category", data: data.map((d) => d.label), axisLabel: { color: t.ink3, fontSize: 10, rotate: 50, interval: 0 } },
    yAxis: { ...(baseOption().yAxis as object), type: "value", name: unit, axisLabel: { color: t.ink3, fontSize: 11 } },
    series: [
      {
        type: "bar",
        data: data.map((d) => ({
          value: d.delta,
          itemStyle: { color: d.delta === null ? t.border : d.delta < 0 ? t.danger : t.water, borderRadius: d.delta !== null && d.delta < 0 ? [0, 0, 4, 4] : [4, 4, 0, 0] },
        })),
        barMaxWidth: 18,
        markLine: { silent: true, symbol: "none", lineStyle: { color: t.ink, width: 1 }, data: [{ yAxis: 0 }], label: { show: true, formatter: "0", color: t.ink2 } },
      },
    ],
  };
  return (
    <ChartPanel
      id="field-distribution"
      title={`Field-by-field yield change, ${leftRun.plan_kind} → ${rightRun.plan_kind}`}
      summary={
        <>
          {data.length} fields · <strong className="font-semibold text-ink">{worse.length} worse off</strong>
          {worse.length ? ` (${worse.slice(0, 3).map((w) => w.label).join(", ")}${worse.length > 3 ? "…" : ""})` : ""}. Zero line shown; red bars are reductions.
        </>
      }
      chart={
        <EChart
          option={option}
          height={260}
          ariaLabel="Bar chart of per-field yield change; see table for values"
          onEvents={{ click: (p) => { const i = (p as { dataIndex?: number }).dataIndex; if (typeof i === "number") sel.setParams({ field: data[i].id }, false); } }}
        />
      }
      table={
        <DataTable
          caption="Per-field yield change"
          columns={[
            { key: "field", label: "Field" },
            { key: "group", label: "Group" },
            { key: "a", label: leftRun.plan_kind, align: "right" },
            { key: "b", label: rightRun.plan_kind, align: "right" },
            { key: "d", label: "Change", align: "right" },
          ]}
          rows={data.map((d) => ({
            field: (
              <button type="button" className="text-water hover:underline" onClick={() => sel.setParams({ field: d.id }, false)}>
                {d.label}
              </button>
            ),
            group: d.group ? titleCase(d.group) : "—",
            a: d.a !== null ? formatWithUnit(d.a, unit) : "—",
            b: d.b !== null ? formatWithUnit(d.b, unit) : "—",
            d: d.delta !== null ? <span className={d.delta < 0 ? "text-danger" : ""}>{formatDelta(d.delta, unit)}</span> : "—",
          }))}
        />
      }
    />
  );
}

export { Eyebrow };
