/**
 * Resilience frontier (PRD §7.2, T7.1): 6–24 independently solved settings around the base
 * revision. Points are plotted from their stored run metrics only; nondominance comes from
 * the server (`dominance`), and settings without a plan are listed separately.
 */
import { useEffect, useMemo, useState } from "react";
import { Play, Plus, Spline, X } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useRun } from "@/lib/api/queries";
import { formatPKR, formatPKRCompact, formatPercent, formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import { parsePKR } from "@/lib/units";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { makeScale } from "@/components/map/palette";
import { Chip, Skeleton, SolverBadge, StatePanel } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import {
  FRONTIER_MAX,
  FRONTIER_MIN,
  paddedRange,
  useCurrentAnalysis,
  useLaunchAnalysis,
  type AnalysisView,
  type ExploreBase,
  type FrontierPoint,
  type FrontierResult,
  type FrontierSetting,
  type ServiceGroup,
} from "./api";
import { AnalysisGate, AnalysisStatusBar, Card, CardHeader, OutcomeBadge, RunLink, Stat } from "./kit";

type Row = { capital: number; floor: number | null; group: ServiceGroup };
type Preset = "capital" | "service" | "grid";

const round = (v: number) => Math.max(0, Math.round(v / 10_000) * 10_000);
function presetRows(p: Preset, budget: number): Row[] {
  const B = budget > 0 ? budget : 1_500_000;
  if (p === "capital") return dedupe([0, 0.2, 0.4, 0.7, 1, 1.5, 2].map((f) => ({ capital: round(B * f), floor: null, group: "all" as ServiceGroup })));
  if (p === "service") return [null, 0.3, 0.4, 0.5, 0.6, 0.7].map((f) => ({ capital: round(B), floor: f, group: "tail" as ServiceGroup }));
  const out: Row[] = [];
  for (const f of [0, 0.5, 1, 2]) for (const fl of [null, 0.5]) out.push({ capital: round(B * f), floor: fl, group: "tail" });
  return dedupe(out);
}
/** The server's normalisation: no floor → no group; a floor without a group → "all". */
function toSetting(r: Row): FrontierSetting {
  return r.floor === null ? { capital_budget_pkr: Math.round(r.capital) } : { capital_budget_pkr: Math.round(r.capital), minimum_service_ratio: r.floor, service_group: r.group };
}
const keyOf = (r: Row) => JSON.stringify(toSetting(r));
function dedupe(rows: Row[]) {
  const seen = new Set<string>();
  return rows.filter((r) => (seen.has(keyOf(r)) ? false : (seen.add(keyOf(r)), true)));
}
function settingText(s: FrontierSetting) {
  return `${formatPKRCompact(s.capital_budget_pkr)}${s.minimum_service_ratio !== null && s.minimum_service_ratio !== undefined ? ` · ≥${formatPercent(s.minimum_service_ratio)} ${s.service_group ?? "all"}` : ""}`;
}

export function Frontier({ base, onHighlight }: { base: ExploreBase; onHighlight: (runId: string | null) => void }) {
  const sel = useSelection();
  const req = base.revision.data?.revision.request;
  const budget = req?.capital_budget_pkr ?? 0;
  const cur = useCurrentAnalysis("frontier", { revisionId: base.revisionId });
  const runner = useLaunchAnalysis("frontier");
  const [preset, setPreset] = useState<Preset>("capital");
  const [rows, setRows] = useState<Row[]>([]);
  const [limit, setLimit] = useState(8);
  const [planKind, setPlanKind] = useState<"P" | "R">("P");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (req) setRows(presetRows(preset, req.capital_budget_pkr));
  }, [preset, req?.capital_budget_pkr]); // eslint-disable-line react-hooks/exhaustive-deps

  const dupes = rows.length - dedupe(rows).length;
  const problem =
    rows.length < FRONTIER_MIN
      ? `At least ${FRONTIER_MIN} settings are needed (${rows.length} now).`
      : rows.length > FRONTIER_MAX
        ? `At most ${FRONTIER_MAX} settings.`
        : dupes
          ? `${dupes} duplicate setting${dupes > 1 ? "s" : ""}: every setting must be distinct.`
          : rows.some((r) => r.floor !== null && (r.floor < 0 || r.floor > 1))
            ? "Service floors are fractions between 0% and 100%."
            : null;
  const totalBudget = Math.min(900, Math.ceil(rows.length * limit + 20));

  const start = () =>
    void runner.launch({
      contract_version: "2.0.0",
      base_revision_id: base.revisionId!,
      settings: rows.map(toSetting),
      plan_kind: planKind,
      time_limit_per_point_s: limit,
      total_budget_s: totalBudget,
    });

  return (
    <div className="flex flex-col gap-3" data-testid="frontier">
      <Card>
        <CardHeader
          icon={<Spline size={16} className="text-water" aria-hidden />}
          title="Resilience frontier"
          aside={
            <Segmented
              label="Setting preset"
              size="sm"
              value={preset}
              onChange={setPreset}
              options={[
                { value: "capital", label: "Capital sweep" },
                { value: "service", label: "Service floor sweep" },
                { value: "grid", label: "Grid" },
              ]}
            />
          }
        >
          Each setting is a child revision of {req ? `the base (capital ${formatPKRCompact(budget)})` : "the base revision"} solved independently over the same finite candidate library.
          Nondominated means “among the evaluated plans”; time-limited points do not establish a complete Pareto frontier.
        </CardHeader>

        <ol className="mt-3 grid gap-x-6 gap-y-1.5 xl:grid-cols-2" aria-label="Frontier settings">
          {rows.map((r, i) => (
            <li key={`${i}-${rows.length}-${preset}`} className="flex min-w-0 items-center gap-1.5">
              <span className="num w-5 shrink-0 text-right text-[11px] text-ink-tertiary">{i + 1}</span>
              <span className="flex h-8 w-[92px] shrink-0 items-center rounded-[8px] border border-border-strong/60 bg-surface pl-2 text-[12px] text-ink sm:w-[132px]">
                <span className="hidden text-[11px] text-ink-tertiary sm:inline">PKR</span>
                <input
                  aria-label={`Setting ${i + 1} capital budget (PKR)`}
                  className="num h-full w-full min-w-0 bg-transparent px-1.5 text-right outline-none"
                  defaultValue={formatPKR(r.capital).replace("PKR ", "")}
                  onBlur={(e) => {
                    const v = parsePKR(e.target.value);
                    if (v === null || v < 0) {
                      e.target.value = formatPKR(r.capital).replace("PKR ", "");
                      return;
                    }
                    setRows((xs) => xs.map((x, j) => (j === i ? { ...x, capital: Math.round(v) } : x)));
                    e.target.value = formatPKR(Math.round(v)).replace("PKR ", "");
                  }}
                />
              </span>
              <select
                aria-label={`Setting ${i + 1} minimum service floor`}
                className="h-8 min-w-0 flex-1 rounded-[8px] border border-border-strong/60 bg-surface px-1.5 text-[12px] text-ink"
                value={r.floor === null ? "" : String(r.floor)}
                onChange={(e) => setRows((xs) => xs.map((x, j) => (j === i ? { ...x, floor: e.target.value === "" ? null : Number(e.target.value) } : x)))}
              >
                <option value="">No floor</option>
                {[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((v) => (
                  <option key={v} value={v}>
                    ≥ {formatPercent(v)} floor
                  </option>
                ))}
              </select>
              <select
                aria-label={`Setting ${i + 1} service group`}
                className="h-8 w-[68px] shrink-0 rounded-[8px] sm:w-[92px] border border-border-strong/60 bg-surface px-1.5 text-[12px] text-ink disabled:opacity-40"
                value={r.group}
                disabled={r.floor === null}
                title={r.floor === null ? "Only applies with a service floor" : undefined}
                onChange={(e) => setRows((xs) => xs.map((x, j) => (j === i ? { ...x, group: e.target.value as ServiceGroup } : x)))}
              >
                {(["all", "head", "middle", "tail"] as const).map((g) => (
                  <option key={g} value={g}>
                    {g === "all" ? "All" : titleCase(g)}
                  </option>
                ))}
              </select>
              <IconButton label={`Remove setting ${i + 1}`} size="sm" className="shrink-0" onClick={() => setRows((xs) => xs.filter((_, j) => j !== i))}>
                <X size={13} />
              </IconButton>
            </li>
          ))}
        </ol>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <Button
            size="sm"
            variant="ghost"
            icon={<Plus size={13} />}
            disabled={rows.length >= FRONTIER_MAX}
            onClick={() => setRows((xs) => [...xs, { capital: round((xs[xs.length - 1]?.capital ?? budget) + Math.max(100_000, budget * 0.25)), floor: null, group: "all" }])}
          >
            Add setting
          </Button>
          <label className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Time limit per point
            <select className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[12px] text-ink" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[4, 8, 15, 30].map((v) => (
                <option key={v} value={v}>
                  {v} s
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Plan type
            <Segmented
              label="Plan type for every point"
              size="sm"
              value={planKind}
              onChange={setPlanKind}
              options={[
                { value: "P", label: "Typical (P)" },
                { value: "R", label: "Robust (R)", title: "Solve every point robustly over the revision's uncertainty set (slower)" },
              ]}
            />
          </div>
          <div className="ml-auto flex flex-col items-end gap-1">
            <Button size="sm" variant="primary" icon={<Play size={13} />} busy={runner.pending} disabled={!base.revisionId || !!problem} onClick={start} data-testid="run-frontier">
              Evaluate {rows.length} settings
            </Button>
            <span className="text-[11px] text-ink-tertiary">Analysis budget ≤ {totalBudget} s; later points get the remaining time.</span>
          </div>
        </div>
        {problem ? (
          <p className="mt-2 text-[12px] text-warning" role="status">
            {problem}
          </p>
        ) : null}
      </Card>

      <AnalysisGate
        cur={cur}
        title="Frontier"
        empty={<StatePanel state="empty" title="No frontier evaluated for this revision yet">Choose at least six settings and evaluate them. Each point becomes an immutable run you can open.</StatePanel>}
      >
        {(a) => (
          <FrontierResultView
            a={a}
            history={cur.history}
            selected={selected}
            onPick={(p) => {
              setSelected(p?.point_id ?? null);
              onHighlight(p?.run_id ?? null);
            }}
            onPickAnalysis={(id) => {
              setSelected(null);
              onHighlight(null);
              sel.setParams({ analysis: id });
            }}
          />
        )}
      </AnalysisGate>
    </div>
  );
}

function FrontierResultView({
  a,
  history,
  selected,
  onPick,
  onPickAnalysis,
}: {
  a: AnalysisView<FrontierResult>;
  history: ReturnType<typeof useCurrentAnalysis>["history"];
  selected: string | null;
  onPick: (p: FrontierPoint | null) => void;
  onPickAnalysis: (id: string) => void;
}) {
  const t = chartTokens();
  const r = a.result;
  const pts = useMemo(() => r?.points ?? [], [r]);
  const yKey = (r?.axes?.y.metric_id ?? "production_kg") as keyof FrontierPoint;
  const yLabel = yKey === "worst_tested_production_kg" ? "Worst tested production" : "Modeled production";
  const yOf = (p: FrontierPoint) => (typeof p[yKey] === "number" ? (p[yKey] as number) : null);
  const plotted = pts.filter((p) => p.outcome === "plan" && p.capital_commitment_pkr !== null && p.capital_commitment_pkr !== undefined && yOf(p) !== null);
  const off = pts.filter((p) => !plotted.includes(p));
  const front = plotted.filter((p) => p.dominance === "nondominated").sort((x, y) => x.capital_commitment_pkr! - y.capital_commitment_pkr! || yOf(x)! - yOf(y)!);
  const svc = makeScale("sequential-service", [], [0, 1]);
  const requested = ((a.request.settings as FrontierSetting[] | undefined) ?? []).length;
  const sel = pts.find((p) => p.point_id === selected) ?? null;

  const option = useMemo(() => {
    const b = baseOption();
    return {
      ...b,
      grid: { left: 70, right: 24, top: 28, bottom: 48 },
      tooltip: {
        ...(b.tooltip as object),
        trigger: "item",
        formatter: (p: { data?: { p?: FrontierPoint } }) => (p.data?.p ? tooltipFor(p.data.p, yOf(p.data.p), yLabel) : ""),
      },
      xAxis: {
        ...(b.xAxis as object),
        type: "value",
        name: "Capital commitment (PKR)",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatPKRCompact(v).replace("PKR ", "") },
        splitLine: { show: true, lineStyle: { color: t.border, opacity: 0.5 } },
      },
      yAxis: {
        ...(b.yAxis as object),
        type: "value",
        name: yLabel,
        nameTextStyle: { color: t.ink3, fontSize: 11, align: "left" },
        ...(paddedRange(plotted.map(yOf)) ?? { scale: true }),
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatWithUnit(v, "kg") },
      },
      series: [
        {
          type: "line",
          name: "Visual guide between nondominated evaluated plans (not interpolated outcomes)",
          data: front.map((p) => [p.capital_commitment_pkr, yOf(p)]),
          showSymbol: false,
          lineStyle: { color: t.ink3, width: 1.25, type: "dashed", opacity: 0.6 },
          silent: true,
          z: 1,
        },
        {
          type: "scatter",
          name: "Evaluated settings",
          data: plotted.map((p) => {
            const nd = p.dominance === "nondominated";
            const unres = p.dominance === "dominance_unresolved";
            const isSel = p.point_id === selected;
            return {
              value: [p.capital_commitment_pkr, yOf(p)],
              p,
              symbol: nd ? "circle" : unres ? "diamond" : "circle",
              symbolSize: isSel ? 20 : nd ? 15 : 10,
              itemStyle: {
                color: svc.color(p.min_service_ratio ?? null),
                borderColor: nd || isSel ? t.ink : t.ink3,
                borderWidth: isSel ? 3 : nd ? 2 : 1,
                borderType: unres ? "dashed" : "solid",
                opacity: nd || isSel ? 1 : 0.55,
              },
            };
          }),
          z: 3,
          emphasis: { scale: 1.15 },
        },
      ],
    };
  }, [plotted, front, selected, t, svc, yLabel]); // eslint-disable-line react-hooks/exhaustive-deps

  const onEvents = useMemo(() => ({ click: (p: unknown) => onPick((p as { data?: { p?: FrontierPoint } }).data?.p ?? null) }), [onPick]);
  const c = r?.counts;

  return (
    <div className="flex flex-col gap-3">
      <AnalysisStatusBar a={a} history={history} onPick={onPickAnalysis} />
      {!r || !pts.length ? (
        <StatePanel state="busy" title={`Solving ${requested} settings…`}>
          Points appear here as each independent solve finishes.
        </StatePanel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="frontier-counts">
            <Stat label="Evaluated" value={`${c?.evaluated ?? pts.length} of ${requested}`} sub={r.distinct_portfolios !== undefined ? `${r.distinct_portfolios} distinct portfolio${r.distinct_portfolios === 1 ? "" : "s"}` : undefined} />
            <Stat label="Nondominated" value={c?.nondominated ?? "—"} sub={c?.dominance_unresolved ? `${c.dominance_unresolved} unresolved by solver bounds` : "among evaluated plans"} />
            <Stat label="Dominated" value={c?.dominated ?? "—"} sub="another plan is at least as good on every axis" />
            <Stat label="Without a plan" value={(c?.infeasible ?? 0) + (c?.unknown_or_other ?? 0)} sub={`${c?.infeasible ?? 0} infeasible · ${c?.unknown_or_other ?? 0} unknown, rejected or not run`} />
          </div>
          <ChartPanel
            id="frontier-chart"
            title={`Capital commitment vs ${yLabel.toLowerCase()}`}
            summary={
              <>
                {r.label ?? "Nondominated among evaluated plans"} ·{" "}
                {r.proof_status === "all_points_optimal" ? "every point proven optimal or infeasible" : "some points are time-limited (bounds in the table)"}. Click a point to inspect its run
                and portfolio.
              </>
            }
            aside={r.proof_status === "all_points_optimal" ? <Chip tone="vegetation" size="sm">All proven</Chip> : <Chip tone="warning" size="sm">Some unproven</Chip>}
            chart={
              <div>
                <EChart option={option} height={360} ariaLabel={`Frontier scatter of capital commitment against ${yLabel.toLowerCase()}, colour encodes minimum service ratio`} onEvents={onEvents} />
                <Legend svc={svc} />
              </div>
            }
            table={<PointsTable pts={pts} yOf={yOf} yLabel={yLabel} onPick={onPick} />}
          />
          {off.length ? (
            <Card>
              <Eyebrow className="mb-2">Settings without a plan · shown separately, never plotted as outcomes</Eyebrow>
              <ul className="flex flex-col divide-y divide-border">
                {off.map((p) => (
                  <li key={p.point_id} className="flex flex-wrap items-center gap-2 py-2 text-[12px]" data-testid="frontier-noplan">
                    <span className="font-mono text-[11px] text-ink-tertiary">{p.point_id}</span>
                    <span className="num font-medium text-ink">{settingText(p.setting)}</span>
                    <OutcomeBadge status={p.solver_status} outcome={p.outcome} />
                    <span className="min-w-0 flex-1 text-ink-secondary">{noPlanReason(p)}</span>
                    {p.run_id ? <RunLink runId={p.run_id} /> : null}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
          {sel ? <SelectedPoint p={sel} y={yOf(sel)} yLabel={yLabel} onClose={() => onPick(null)} /> : null}
          {r.note ? <p className="px-1 text-[11px] leading-relaxed text-ink-tertiary">{r.note}</p> : null}
        </>
      )}
    </div>
  );
}

function Legend({ svc }: { svc: ReturnType<typeof makeScale> }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-3 pt-1 text-[11px] text-ink-secondary">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded-full border-2 border-ink bg-water" aria-hidden /> Nondominated
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full border border-ink-tertiary bg-water opacity-55" aria-hidden /> Dominated
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rotate-45 border border-dashed border-ink bg-water" aria-hidden /> Dominance unresolved (solver bound)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-0 w-5 border-t border-dashed border-ink-tertiary" aria-hidden /> Visual guide only
      </span>
      <span className="inline-flex items-center gap-1.5">
        Min service ratio
        <span className="num text-ink-tertiary">0%</span>
        <span className="h-2 w-24 rounded-full" style={{ background: `linear-gradient(90deg, ${svc.stops.map((s) => `${s.color} ${s.t * 100}%`).join(",")})` }} aria-hidden />
        <span className="num text-ink-tertiary">100%</span>
      </span>
    </div>
  );
}

function PointsTable({ pts, yOf, yLabel, onPick }: { pts: FrontierPoint[]; yOf: (p: FrontierPoint) => number | null; yLabel: string; onPick: (p: FrontierPoint) => void }) {
  return (
    <DataTable
      caption="Frontier points"
      columns={[
        { key: "id", label: "Point" },
        { key: "setting", label: "Setting" },
        { key: "status", label: "Solver" },
        { key: "capex", label: "Capital committed", align: "right" },
        { key: "prod", label: yLabel, align: "right" },
        { key: "svc", label: "Min service", align: "right" },
        { key: "gap", label: "Gap", align: "right" },
        { key: "dom", label: "Dominance" },
        { key: "run", label: "Run" },
      ]}
      rows={pts.map((p) => ({
        id: (
          <button type="button" className="font-mono text-[11px] text-ink hover:underline" onClick={() => onPick(p)} disabled={p.outcome !== "plan"}>
            {p.point_id}
          </button>
        ),
        setting: settingText(p.setting),
        status: <OutcomeBadge status={p.solver_status} outcome={p.outcome} />,
        capex: p.capital_commitment_pkr !== null && p.capital_commitment_pkr !== undefined ? formatPKR(p.capital_commitment_pkr) : "—",
        prod: yOf(p) !== null ? formatWithUnit(yOf(p)!, "kg") : "no plan",
        svc: p.min_service_ratio !== null && p.min_service_ratio !== undefined ? formatPercent(p.min_service_ratio, 1) : "—",
        gap: p.relative_gap !== null && p.relative_gap !== undefined ? formatPercent(p.relative_gap, 2) : p.solver_status === "OPTIMAL" ? "0%" : "—",
        dom: (
          <span className="inline-flex flex-col">
            <span>{dominanceLabel(p)}</span>
            {p.same_portfolio_as?.length ? <span className="text-[11px] text-ink-tertiary">same portfolio as {p.same_portfolio_as.join(", ")}</span> : null}
          </span>
        ),
        run: p.run_id ? <RunLink runId={p.run_id} /> : "—",
      }))}
    />
  );
}

function dominanceLabel(p: FrontierPoint) {
  switch (p.dominance) {
    case "nondominated":
      return "Nondominated";
    case "dominated":
      return `Dominated by ${p.dominated_by?.join(", ") || "another point"}`;
    case "dominance_unresolved":
      return "Unresolved (bound overlaps)";
    default:
      return "Not applicable";
  }
}

function noPlanReason(p: FrontierPoint) {
  if (p.reason) return p.reason;
  if (p.solver_status === "INFEASIBLE") {
    const cfg = p.diagnostics?.configurations?.map((c) => c.reason).filter(Boolean) ?? [];
    return `No feasible plan under this setting${p.infeasibility_kind ? ` (${p.infeasibility_kind.replace(/_/g, " ")})` : ""}${cfg.length ? `: ${cfg[0]}` : "."}`;
  }
  if (p.solver_status === "UNKNOWN") return "The time limit ended before a feasible plan was found; this is not proof of infeasibility.";
  return "No validated plan.";
}

function tooltipFor(p: FrontierPoint, y: number | null, yLabel: string) {
  return [
    `<b>${p.point_id} · ${dominanceLabel(p)}</b>`,
    `Setting: ${settingText(p.setting)}`,
    `Capital committed: ${p.capital_commitment_pkr !== null && p.capital_commitment_pkr !== undefined ? formatPKR(p.capital_commitment_pkr) : "—"}`,
    `${yLabel}: ${y !== null ? formatWithUnit(y, "kg") : "—"}`,
    p.min_service_ratio !== null && p.min_service_ratio !== undefined ? `Min service: ${formatPercent(p.min_service_ratio, 1)}` : "",
    `Solver: ${p.solver_status ?? "—"}${p.relative_gap ? ` · gap ${formatPercent(p.relative_gap, 2)}` : ""}`,
    p.same_portfolio_as?.length ? `Same portfolio as ${p.same_portfolio_as.join(", ")}` : "",
    p.run_id ? `Run ${shortId(p.run_id)}` : "",
  ]
    .filter(Boolean)
    .join("<br/>");
}

function SelectedPoint({ p, y, yLabel, onClose }: { p: FrontierPoint; y: number | null; yLabel: string; onClose: () => void }) {
  const run = useRun(p.run_id);
  const inst = p.selected_intervention_instance_ids ?? [];
  const byCat = inst.reduce<Record<string, number>>((m, id) => {
    const k = id.split(":").pop()?.replace(/-(small|medium|large)$/, "") ?? "other";
    m[k] = (m[k] ?? 0) + 1;
    return m;
  }, {});
  return (
    <section className="rounded-[14px] border border-water/30 bg-water-soft/40 p-4" data-testid="frontier-selected" aria-label={`Selected frontier point ${p.point_id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-ink-secondary">
            Selected point {p.point_id} · {settingText(p.setting)}
          </div>
          <div className="mt-0.5 text-[14px] font-semibold text-ink">
            {inst.length} investment{inst.length === 1 ? "" : "s"} · {formatPKR(p.capital_commitment_pkr ?? 0)} committed · {y !== null ? formatWithUnit(y, "kg") : "—"} {yLabel.toLowerCase()}
          </div>
          {inst.length ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {Object.entries(byCat).map(([k, n]) => (
                <Chip key={k} size="sm" tone="water">
                  {n} × {k.replace(/-/g, " ")}
                </Chip>
              ))}
            </div>
          ) : (
            <div className="mt-1 text-[12px] text-ink-secondary">No investments: operations-only plan.</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {run.isLoading ? <Skeleton className="h-6 w-20" /> : run.data ? <SolverBadge status={run.data.solver_status} /> : null}
          {p.run_id ? <RunLink runId={p.run_id} label="Open run in Workspace" className={cn("font-sans text-[12px] font-medium")} /> : null}
          <IconButton label="Clear selection" size="sm" onClick={onClose}>
            <X size={14} />
          </IconButton>
        </div>
      </div>
    </section>
  );
}
