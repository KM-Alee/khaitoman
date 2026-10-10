/**
 * Compare: "How much better is it than today?" The ladder of plans solved under identical
 * conditions, told in words from the comparison service's incremental view, then the full
 * table, the matched-comparison certificate, paired maps and the field-by-field change.
 */
import { useMemo, useState } from "react";
import { ArrowRight, BadgeCheck, Columns2, PlayCircle, SplitSquareHorizontal, TriangleAlert, Trophy } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI, type MapMetric } from "@/app/store";
import { useComparison } from "@/lib/api/queries";
import type { PlanKind, RunResult } from "@/lib/api/types";
import { fieldMetricMap, runMetrics } from "@/lib/api/adapters";
import { formatDelta, formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import { GLOSSARY, planName } from "@/lib/glossary";
import { MapSlot } from "@/components/map/MapSlot";
import { SecondaryMap } from "@/components/map/SecondaryMap";
import { METRIC_DEFS } from "@/components/map/useFieldVisuals";
import { niceDomain } from "@/components/map/palette";
import { Chip, MetricValueView, Provenance, SolverBadge, Skeleton, SOLVER_COPY, StatePanel } from "@/components/status";
import { Segmented, Eyebrow } from "@/components/ui/primitives";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { MetricTile } from "@/components/ui/MetricTile";
import { NextStep, PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { HEADLINE, comparisonDeltas, headlineMetrics } from "@/features/workspace/ResultStrip";
import { useShell } from "@/components/layout/AppShell";
import { cn } from "@/lib/cn";
import { CompareTabs } from "./CompareTabs";
import { LADDER_ORDER, useLadderRuns } from "./useLadder";

export { useLadderRuns };

const ORDER = LADDER_ORDER;

interface IncrementalStep {
  from_run_id: string;
  to_run_id: string;
  step: string;
  production_kg?: number | null;
  operating_cost_pkr?: number | null;
  capital_commitment_pkr?: number | null;
  groundwater_m3?: number | null;
  min_service_ratio?: number | null;
  note?: string;
}

export function CompareScreen() {
  const { sel } = usePilotData();
  const { mobile } = useShell();
  const { ids, runs, byKind, siblingsLoading } = useLadderRuns();
  const [view, setView] = useState<"paired" | "swipe">(mobile ? "swipe" : "paired");
  const [metric, setMetric] = useState<MapMetric>("yield");
  const kinds = ORDER.filter((k) => byKind.has(k));
  const [left, setLeft] = useState<PlanKind | null>(null);
  const [right, setRight] = useState<PlanKind | null>(null);
  const l = left && byKind.has(left) ? left : kinds.includes("B0") ? "B0" : kinds[0] ?? null;
  const r = right && byKind.has(right) ? right : kinds.includes("P") ? "P" : kinds[kinds.length - 1] ?? null;
  const leftRun = l ? byKind.get(l)! : null;
  const rightRun = r ? byKind.get(r)! : null;
  const cmp = useComparison(leftRun && rightRun && leftRun.run_id !== rightRun.run_id ? [leftRun.run_id, rightRun.run_id] : []);
  // The B0 → B1 → P ladder (matched), and P → R separately (R spans the tested states).
  const ladderIds = (["B0", "B1", "P"] as PlanKind[]).map((k) => byKind.get(k)?.run_id).filter(Boolean) as string[];
  const ladderCmp = useComparison(ladderIds.length >= 2 ? ladderIds : []);
  const robustCmp = useComparison(byKind.get("P") && byKind.get("R") ? [byKind.get("P")!.run_id, byKind.get("R")!.run_id] : []);

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

  if (!ids.length && (siblingsLoading || runs.isLoading))
    return (
      <div className="flex flex-1 flex-col" aria-busy data-testid="compare-loading">
        <CompareTabs />
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-4 p-4 md:p-8">
          <Skeleton className="h-24 w-2/3" />
          <div className="grid gap-4 md:grid-cols-3">
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
          </div>
        </div>
      </div>
    );
  if (!ids.length)
    return (
      <div className="flex flex-1 flex-col overflow-y-auto">
        <CompareTabs />
        <div className="mx-auto w-full max-w-[1400px] p-4 md:p-8">
          <PageHeader />
          <div className="mt-8 max-w-[620px]">
            <StatePanel state="empty" art="compare" title="Nothing to compare yet" action={{ label: "Find the best plan first", onClick: () => sel.go("workspace") }}>
              Compare puts today's routine, smarter timing and the recommended plan side by side, solved under the same weather, water and costs. Run a plan on the Plan step, or open a shared link.
            </StatePanel>
          </div>
        </div>
      </div>
    );

  const steps = [...((ladderCmp.data?.incremental as IncrementalStep[] | undefined) ?? []), ...((robustCmp.data?.incremental as IncrementalStep[] | undefined) ?? [])];
  const pRun = byKind.get("P") ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="compare">
      <CompareTabs />
      <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-6 p-4 md:p-8">
        <PageHeader
          lead="The same season solved several ways, under identical weather, water and prices, so every difference comes from the plan itself."
          meta={pRun ? <Provenance run={pRun} /> : null}
          actions={
            <Button variant="secondary" icon={<PlayCircle size={15} />} onClick={() => sel.go("replay")}>
              Replay the season
            </Button>
          }
        />

        <PlanCards byKind={byKind} loading={runs.isLoading} error={runs.error} />
        {steps.length ? <StepStory steps={steps} matched={ladderCmp.data?.compatible === true} /> : ladderCmp.isLoading ? <Skeleton className="h-32" /> : null}

        <Ladder byKind={byKind} loading={runs.isLoading} error={runs.error} />
        <Compatibility cmp={cmp.data} loading={cmp.isLoading} error={cmp.error} leftRun={leftRun} rightRun={rightRun} />

        <Card aria-label="Side-by-side maps" className="overflow-hidden">
          <CardHeader
            title="See the difference on the map"
            description="Both maps share one colour scale, so the same colour means the same value."
            aside={
              <>
                <PlanPicker label="Left" value={l} kinds={kinds} onChange={setLeft} />
                <ArrowRight size={14} className="text-ink-tertiary" aria-hidden />
                <PlanPicker label="Right" value={r} kinds={kinds} onChange={setRight} />
              </>
            }
          />
          <div className="flex flex-wrap items-center gap-2 border-y border-border px-5 py-2.5">
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
              className="ml-auto"
              value={view}
              onChange={(v) => setView(v as "paired" | "swipe")}
              options={[
                { value: "paired", label: <><Columns2 size={13} aria-hidden /> Side by side</> },
                { value: "swipe", label: <><SplitSquareHorizontal size={13} aria-hidden /> Swipe</> },
              ]}
            />
          </div>
          <PairedMaps view={view} metric={metric} shared={shared} leftRun={leftRun} rightRun={rightRun} mobile={mobile} />
        </Card>

        <Distribution leftRun={leftRun} rightRun={rightRun} cmp={cmp.data} />
        <NextStep />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ plan cards */
const KIND_BLURB: Record<PlanKind, string> = {
  B0: "How water is used today",
  B1: "Same assets, smarter timing",
  P: "With new works, within budget",
  R: "Best in the worst tested year",
};

function PlanCards({ byKind, loading, error }: { byKind: Map<PlanKind, RunResult>; loading: boolean; error: unknown }) {
  const { sel } = usePilotData();
  if (loading) return <div className="grid gap-4 md:grid-cols-3"><Skeleton className="h-64" /><Skeleton className="h-64" /><Skeleton className="h-64" /></div>;
  if (error) return <StatePanel state="error" error={error} title="The saved plans could not be loaded" />;
  const kinds = ORDER.filter((k) => byKind.has(k));
  return (
    <ol className={cn("grid gap-4", kinds.length >= 4 ? "md:grid-cols-2 xl:grid-cols-4" : "md:grid-cols-3")} aria-label="Plans compared" data-tour="plan-cards">
      {kinds.map((k, i) => {
        const run = byKind.get(k)!;
        const m = headlineMetrics(run);
        const get = (key: string) => m.find((x) => x.key === key)!.metric;
        const recommended = k === "P";
        const active = sel.runId === run.run_id;
        return (
          <li key={k} className="min-w-0">
            <article
              className={cn(
                "relative flex h-full flex-col gap-4 rounded-[20px] border bg-surface p-5 shadow-1 transition-[box-shadow,border-color] duration-200 animate-rise",
                recommended ? "border-water/45 shadow-glow" : "border-border",
                active && !recommended && "border-border-strong",
              )}
              style={{ animationDelay: `${i * 70}ms` }}
              data-testid="plan-card"
              data-kind={k}
            >
              {recommended ? (
                <span className="absolute -top-3 left-5 inline-flex items-center gap-1 rounded-full bg-wheat-soft px-2.5 py-1 text-[11.5px] font-semibold text-wheat-ink shadow-1 ring-1 ring-wheat/30">
                  <Trophy size={12} aria-hidden /> Recommended
                </span>
              ) : null}
              <header className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: `var(--plan-${k.toLowerCase()})` }} aria-hidden />
                    <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-ink">
                      <Term id={k}>{planName(k)}</Term>
                    </h2>
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-ink-secondary">{KIND_BLURB[k]}</p>
                </div>
                <span className="rounded-full bg-surface-muted px-2 py-0.5 font-mono text-[11px] font-semibold text-ink-secondary" title={GLOSSARY[k].precise}>
                  {k}
                </span>
              </header>
              {run.outcome === "plan" ? (
                <>
                  <MetricTile size="lg" label="Crop harvested" metric={get("production")} />
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-border pt-3 text-[12.5px]">
                    {[
                      ["Money for new works", get("capex")],
                      ["Running cost", get("opex")],
                      ["Tail-end fair share", get("tail")],
                      ["Groundwater", get("groundwater")],
                    ].map(([label, metric]) => (
                      <div key={label as string} className="min-w-0">
                        <dt className="truncate text-ink-tertiary">{label as string}</dt>
                        <dd>
                          <MetricValueView metric={metric as ReturnType<typeof get>} size="sm" showReason={false} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              ) : (
                <p className="text-[13px] text-ink-secondary">No plan: {SOLVER_COPY[run.solver_status].plain.toLowerCase()}.</p>
              )}
              <footer className="mt-auto flex items-center justify-between gap-2 text-[11.5px] text-ink-tertiary">
                <span title={SOLVER_COPY[run.solver_status].friendly}>{SOLVER_COPY[run.solver_status].plain}</span>
                <button type="button" className="font-mono text-water-deep hover:underline" onClick={() => sel.setParams({ run: run.run_id })} title={`Show run ${run.run_id}`}>
                  {shortId(run.run_id)}
                </button>
              </footer>
            </article>
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------------------ the story in words */
function StepStory({ steps, matched }: { steps: IncrementalStep[]; matched: boolean }) {
  const label: Record<string, { title: string; body: string }> = {
    "B0->B1": { title: "Smarter timing alone", body: "Same canal water and existing ponds and pumps, scheduled better. No new spending." },
    "B1->P": { title: "Then the new works", body: "What levelling, ponds, repairs and extra pumping add on top, within your budgets." },
    "P->R": { title: "Protecting against a bad year", body: "The bad-year-proof plan gives up some typical-year harvest to do better in the worst tested condition." },
  };
  return (
    <Card tone="quiet" data-testid="step-story" data-tour="step-story">
      <CardHeader
        eyebrow="Where the gain comes from"
        title="Step by step, in the server's own numbers"
        description={matched ? "Each step changes one thing; the rest is held identical." : "Some steps are not a matched comparison; read their differences as descriptive, not causal."}
      />
      <CardBody>
        <ol className="grid gap-3 md:grid-cols-3">
          {steps.map((st) => {
            const l = label[st.step] ?? { title: st.step, body: "" };
            const prod = st.production_kg;
            return (
              <li key={st.step} className="flex flex-col gap-2 rounded-[16px] border border-border bg-surface p-4">
                <div className="flex items-center gap-2 text-[12px] font-semibold text-ink-secondary">
                  <span className="font-mono">{st.step.replace("->", " → ")}</span>
                </div>
                <div className="text-[15px] font-semibold text-ink">{l.title}</div>
                {typeof prod === "number" ? (
                  <div className={cn("display-num text-[30px] leading-none", prod >= 0 ? "text-vegetation" : "text-danger")}>{formatDelta(prod, "kg")}</div>
                ) : (
                  <div className="text-[13px] text-ink-tertiary">Harvest change not available</div>
                )}
                <p className="text-[12.5px] leading-snug text-ink-secondary">{l.body}</p>
                <ul className="mt-auto flex flex-wrap gap-1.5 text-[11.5px]">
                  {typeof st.capital_commitment_pkr === "number" && st.capital_commitment_pkr !== 0 ? <Chip size="sm">{formatDelta(st.capital_commitment_pkr, "PKR")} works</Chip> : null}
                  {typeof st.operating_cost_pkr === "number" && st.operating_cost_pkr !== 0 ? <Chip size="sm">{formatDelta(st.operating_cost_pkr, "PKR")} running</Chip> : null}
                  {typeof st.groundwater_m3 === "number" && st.groundwater_m3 !== 0 ? <Chip size="sm">{formatDelta(st.groundwater_m3, "m3")} pumped</Chip> : null}
                </ul>
                {st.note ? <p className="text-[11.5px] italic text-ink-tertiary">Note: {st.note}.</p> : null}
              </li>
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}

function PlanPicker({ label, value, kinds, onChange }: { label: string; value: PlanKind | null; kinds: PlanKind[]; onChange: (k: PlanKind) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-ink-secondary">
      {label}
      <select
        className="h-8 rounded-[9px] border border-border-strong/55 bg-surface-raised px-2 text-[13px] font-medium text-ink"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value as PlanKind)}
      >
        {kinds.map((k) => (
          <option key={k} value={k}>
            {planName(k)} ({k})
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
          <MapSlot runId={leftRun?.run_id ?? null} metric={metric} sharedDomain={shared} className="absolute inset-0" compactControls label={`Left map: ${leftRun ? planName(leftRun.plan_kind) : "none"}`}>
            <MapTag run={leftRun} side="left" />
          </MapSlot>
        </div>
        <div className="relative overflow-hidden bg-[var(--map-bg)]">
          <SecondaryMap runId={rightRun?.run_id ?? null} metric={metric} sharedDomain={shared} label={`Right map: ${rightRun ? planName(rightRun.plan_kind) : "none"}`} />
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
        <span className="font-medium text-ink">{leftRun ? planName(leftRun.plan_kind) : ""}</span>
        <input type="range" min={5} max={95} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="flex-1 accent-[var(--water)]" aria-label="Swipe position" />
        <span className="font-medium text-ink">{rightRun ? planName(rightRun.plan_kind) : ""}</span>
      </label>
    </div>
  );
}

function MapTag({ run, side }: { run: RunResult | null; side: "left" | "right" }) {
  if (!run) return null;
  return (
    <div className={cn("pointer-events-none absolute top-3 z-20 flex items-center gap-2 rounded-[12px] bg-ink/90 px-3 py-1.5 text-[12.5px] font-semibold text-canvas shadow-2", side === "left" ? "left-3" : "right-14")}>
      <span className="h-2 w-2 rounded-full" style={{ background: `var(--plan-${run.plan_kind.toLowerCase()})` }} aria-hidden />
      {planName(run.plan_kind)} <span className="font-mono text-[11px] opacity-70">{run.plan_kind}</span>
    </div>
  );
}

function Ladder({ byKind, loading, error }: { byKind: Map<PlanKind, RunResult>; loading: boolean; error: unknown }) {
  const { sel } = usePilotData();
  const { mobile } = useShell();
  const [open, setOpen] = useState(!mobile);
  const cell = mobile ? "px-2 py-2" : "px-4 py-2.5";
  if (loading) return <Skeleton className="h-44" />;
  if (error) return <StatePanel state="error" error={error} title="Runs could not be loaded" />;
  const kinds = ORDER.filter((k) => byKind.has(k));
  const rows = HEADLINE;
  const metrics = new Map(kinds.map((k) => [k, headlineMetrics(byKind.get(k))]));
  return (
    <section className="overflow-hidden rounded-[18px] border border-border bg-surface shadow-1" aria-labelledby="ladder-h" data-testid="ladder">
      <header className="flex flex-wrap items-baseline justify-between gap-2 px-5 pb-3 pt-4">
        <div>
          <h2 id="ladder-h" className="text-[15px] font-semibold tracking-[-0.01em] text-ink">
            All the numbers
          </h2>
          <p className="text-[12.5px] text-ink-secondary">Baseline ladder: B0 → B1 is the operational gain; B1 → P the investment gain; P → R the robustness trade-off.</p>
        </div>
        <button type="button" className="text-[12.5px] font-medium text-water-deep hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide table" : "Show table"}
        </button>
      </header>
      {open ? (
        <div className="overflow-x-auto">
          <table className={cn("w-full border-collapse text-[13px]", mobile ? "" : "min-w-[640px]")}>
            <thead>
              <tr className="border-y border-border bg-surface-muted/60">
                <th scope="col" className={cn(cell, "pl-5 text-left text-[12px] font-medium text-ink-tertiary")}>
                  Measure
                </th>
                {kinds.map((k) => {
                  const run = byKind.get(k)!;
                  return (
                    <th key={k} scope="col" className={cn(cell, "text-right align-bottom last:pr-5")}>
                      <div className="text-[13px] font-semibold text-ink">{k}</div>
                      <div className="hidden text-[11.5px] font-normal text-ink-secondary sm:block">{planName(k)}</div>
                      <div className="mt-1 flex justify-end">
                        <SolverBadge status={run.solver_status} size="sm" />
                      </div>
                      <button type="button" className="num mt-1 hidden font-mono text-[11px] font-normal text-water-deep hover:underline sm:inline" onClick={() => sel.setParams({ run: run.run_id })} title={run.run_id}>
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
                    <th scope="row" className={cn(cell, "pl-5 text-left font-normal text-ink-secondary", mobile && "text-[12px] leading-snug")}>
                      <Term id={h.term}>{h.plain}</Term>
                    </th>
                    {kinds.map((k) => (
                      <td key={k} className={cn(cell, "text-right last:pr-5")}>
                        {byKind.get(k)!.outcome === "plan" ? <MetricValueView metric={metrics.get(k)![i].metric} size="sm" showReason={false} /> : <span className="text-[12px] text-ink-tertiary">no plan</span>}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {kinds.length < 3 ? (
        <p className="border-t border-border px-5 py-2.5 text-[12px] text-ink-secondary">
          {ORDER.filter((k) => !byKind.has(k) && k !== "R").map((k) => `${planName(k)} (${k})`).join(", ") || "R"} not solved for these settings yet.
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
  const shared = (cert.shared ?? []).map(readCondition);
  const diffs = (cert.differences ?? (cmp.differences as unknown[]) ?? []).map(readCondition);
  return (
    <section
      className={cn("rounded-[18px] border px-5 py-4", compatible ? "border-vegetation/30 bg-vegetation-soft/60" : "border-warning/40 bg-warning-soft/70")}
      data-testid="compatibility"
      data-compatible={compatible}
    >
      <div className="flex flex-wrap items-center gap-2">
        {compatible ? <BadgeCheck size={17} className="text-vegetation" aria-hidden /> : <TriangleAlert size={17} className="text-warning" aria-hidden />}
        <span className="text-[14px] font-semibold text-ink">
          {compatible
            ? `Matched comparison: ${planName(leftRun.plan_kind)} vs ${planName(rightRun.plan_kind)}`
            : `Not a matched comparison: differences are descriptive, not causal`}
        </span>
        {cmp.compatibility_key ? <Chip size="sm" tone="info">key {shortId(String(cmp.compatibility_key))}</Chip> : null}
      </div>
      <p className="mt-1 text-[12.5px] text-ink-secondary">
        {compatible ? "Same weather, water, crop, soil and prices. Only the plan differs, so the difference is caused by the plan." : "Something other than the plan differs between these two runs."}
      </p>
      {diffs.length ? (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12px]">
          <span className="font-semibold text-ink">{compatible ? "What changes" : "Differs"}</span>
          {diffs.map((d) => (
            <span key={d.key} className="rounded-[8px] bg-surface/80 px-2 py-0.5 text-ink">
              {d.label}: <span className="num font-medium">{d.value}</span>
              {d.note ? <span className="text-ink-secondary"> · {d.note}</span> : null}
            </span>
          ))}
        </div>
      ) : null}
      {shared.length ? (
        <details className="mt-1.5 text-[12px] text-ink-secondary">
          <summary className="cursor-pointer select-none hover:text-ink">Held identical across both runs ({shared.length} conditions)</summary>
          <dl className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5">
            {shared.map((c) => (
              <div key={c.key} className="contents">
                <dt>{c.label}</dt>
                <dd className="num break-all text-ink">{c.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </section>
  );
}

/** Certificate condition rows arrive as `{condition, value|values, kind?, note?}` or plain strings. */
function readCondition(c: unknown, i: number): { key: string; label: string; value: string; note: string | null } {
  if (typeof c === "string") return { key: `${c}-${i}`, label: titleCase(c), value: "", note: null };
  const o = (c ?? {}) as { condition?: string; value?: unknown; values?: unknown; note?: string };
  const v = o.values ?? o.value;
  const fmt = (x: unknown): string =>
    Array.isArray(x) ? (x.length ? x.map(fmt).join(o.values ? " → " : ", ") : "none") : x === null || x === undefined ? "—" : String(x);
  const cond = o.condition ?? `condition ${i + 1}`;
  return { key: `${cond}-${i}`, label: titleCase(cond.replace(/_/g, " ")), value: fmt(v), note: o.note ?? null };
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
      <StatePanel state="empty" art="chart" title="Field-by-field change unavailable">
        The comparison service returned no per-field harvest change for {planName(leftRun.plan_kind)} → {planName(rightRun.plan_kind)}.
      </StatePanel>
    );
  const t = chartTokens();
  const worse = data.filter((d) => (d.delta ?? 0) < 0);
  const better = data.filter((d) => (d.delta ?? 0) > 0);
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
      title={`Who gains and who loses: ${planName(leftRun.plan_kind)} → ${planName(rightRun.plan_kind)}`}
      summary={
        <>
          {better.length} of {data.length} fields harvest more per hectare;{" "}
          <strong className={cn("font-semibold", worse.length ? "text-danger" : "text-ink")}>{worse.length} harvest less</strong>
          {worse.length ? ` (${worse.slice(0, 3).map((w) => w.label).join(", ")}${worse.length > 3 ? "…" : ""})` : ""}. Bars below the zero line are reductions. Click a bar to open the field.
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
            { key: "a", label: planName(leftRun.plan_kind), align: "right" },
            { key: "b", label: planName(rightRun.plan_kind), align: "right" },
            { key: "d", label: "Change", align: "right" },
          ]}
          rows={data.map((d) => ({
            field: (
              <button type="button" className="text-water-deep hover:underline" onClick={() => sel.setParams({ field: d.id }, false)}>
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
