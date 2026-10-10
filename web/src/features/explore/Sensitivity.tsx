/**
 * Finite-difference sensitivity (T7.3): child scenarios over an explicit range of one
 * uncertain input, each re-solved. Shows objective steps as supported intervals, where the
 * selected portfolio changes, and the measurement/quote that would resolve the decision.
 */
import { useEffect, useMemo, useState } from "react";
import { Play, SlidersHorizontal } from "lucide-react";
import { useSelection } from "@/app/selection";
import { formatPKR, formatPKRCompact, formatPercent, formatWithUnit, titleCase } from "@/lib/formatting";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/primitives";
import {
  instanceShort,
  objectiveLabel,
  paddedRange,
  useCurrentAnalysis,
  useLaunchAnalysis,
  type AnalysisView,
  type ExploreBase,
  type SensitivityParameter,
  type SensitivityResult,
  type ServiceGroup,
} from "./api";
import { AnalysisGate, AnalysisStatusBar, Card, CardHeader, OutcomeBadge, RunLink, differenceText } from "./kit";

const PARAMS: { value: SensitivityParameter; label: string; fraction: boolean }[] = [
  { value: "capital_budget_pkr", label: "Capital budget", fraction: false },
  { value: "operating_budget_pkr", label: "Operating budget", fraction: false },
  { value: "uniform_reduction_fraction", label: "Uniform supply reduction", fraction: true },
  { value: "minimum_service_ratio", label: "Minimum service floor", fraction: true },
];
const isFrac = (p: SensitivityParameter) => PARAMS.find((x) => x.value === p)!.fraction;
const fmtVal = (p: SensitivityParameter, v: number) => (isFrac(p) ? formatPercent(v, Math.abs(v * 100 - Math.round(v * 100)) > 1e-9 ? 1 : 0) : formatPKRCompact(v));

function defaults(p: SensitivityParameter, base: number | null | undefined): number[] {
  const r10k = (v: number) => Math.round(v / 10_000) * 10_000;
  if (p === "capital_budget_pkr" || p === "operating_budget_pkr") {
    const b = base && base > 0 ? base : p === "capital_budget_pkr" ? 1_500_000 : 250_000;
    return [...new Set([0.25, 0.5, 0.75, 1, 1.5, 2].map((f) => r10k(b * f)))];
  }
  if (p === "uniform_reduction_fraction") return [0, 0.1, 0.2, 0.3, 0.4];
  return [0.3, 0.4, 0.5, 0.6, 0.7];
}
function parseValues(p: SensitivityParameter, s: string): { values: number[]; error: string | null } {
  const parts = s
    .split(/[,;\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const vals: number[] = [];
  for (const x of parts) {
    const n = Number(x.replace(/%$/, "").replace(/_/g, ""));
    if (!Number.isFinite(n)) return { values: [], error: `“${x}” is not a number` };
    vals.push(isFrac(p) ? n / 100 : Math.round(n));
  }
  if (vals.length < 2 || vals.length > 12) return { values: vals, error: "Enter 2 to 12 values." };
  if (new Set(vals).size !== vals.length) return { values: vals, error: "Values must be distinct." };
  if (vals.some((v) => v < 0)) return { values: vals, error: "Values must be non-negative." };
  if (p === "uniform_reduction_fraction" && vals.some((v) => v >= 1)) return { values: vals, error: "A supply reduction must stay below 100%." };
  if (p === "minimum_service_ratio" && vals.some((v) => v > 1)) return { values: vals, error: "Service floors are at most 100%." };
  return { values: vals, error: null };
}
const toText = (p: SensitivityParameter, vs: number[]) => vs.map((v) => (isFrac(p) ? String(Math.round(v * 1000) / 10) : String(v))).join(", ");

export function Sensitivity({ base }: { base: ExploreBase }) {
  const sel = useSelection();
  const req = base.revision.data?.revision.request;
  const [param, setParam] = useState<SensitivityParameter>("capital_budget_pkr");
  const baseValue = req ? (param === "minimum_service_ratio" ? req.minimum_service_ratio : (req[param] as number)) : null;
  const [text, setText] = useState("");
  const [group, setGroup] = useState<ServiceGroup>("tail");
  const [limit, setLimit] = useState(8);
  const cur = useCurrentAnalysis("sensitivity", { revisionId: base.revisionId });
  const runner = useLaunchAnalysis("sensitivity");
  useEffect(() => {
    setText(toText(param, defaults(param, baseValue)));
  }, [param, baseValue]);
  const parsed = parseValues(param, text);

  return (
    <div className="flex flex-col gap-3" data-testid="sensitivity">
      <Card>
        <CardHeader icon={<SlidersHorizontal size={16} className="text-water" aria-hidden />} title="Which assumption should we check before spending?">
          A finite-difference sensitivity: one child scenario per value, each re-solved over the same candidate library. It is not a derivative, and selection frequency across these runs is
          not a probability.
        </CardHeader>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Select label="Uncertain input" value={param} onChange={(e) => setParam(e.target.value as SensitivityParameter)} className="min-w-[200px]">
            {PARAMS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
          <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Values {isFrac(param) ? "(%)" : "(PKR)"} · base {baseValue !== null && baseValue !== undefined ? fmtVal(param, baseValue) : "not set"}
            <input
              className="num h-9 rounded-[10px] border border-border-strong/70 bg-surface px-3 text-[13px] text-ink shadow-1"
              value={text}
              onChange={(e) => setText(e.target.value)}
              aria-invalid={!!parsed.error}
              aria-describedby="sens-err"
            />
          </label>
          {param === "minimum_service_ratio" ? (
            <Select label="Applies to" value={group} onChange={(e) => setGroup(e.target.value as ServiceGroup)} className="w-[130px]">
              {(["all", "head", "middle", "tail"] as const).map((g) => (
                <option key={g} value={g}>
                  {titleCase(g)}
                </option>
              ))}
            </Select>
          ) : null}
          <label className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Per point
            <select className="h-9 rounded-[10px] border border-border-strong/70 bg-surface px-2 text-[13px] text-ink" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[4, 8, 15, 30].map((v) => (
                <option key={v} value={v}>
                  {v} s
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="primary"
            size="sm"
            className="h-9"
            icon={<Play size={13} />}
            busy={runner.pending}
            disabled={!!parsed.error || !base.revisionId}
            onClick={() =>
              void runner.launch({
                contract_version: "2.0.0",
                base_revision_id: base.revisionId!,
                parameter: param,
                values: parsed.values,
                service_group: param === "minimum_service_ratio" ? group : null,
                time_limit_per_point_s: limit,
              })
            }
            data-testid="run-sensitivity"
          >
            Solve {parsed.values.length} values
          </Button>
        </div>
        <p id="sens-err" className="mt-1.5 text-[12px] text-warning" role="status">
          {parsed.error ?? ""}
        </p>
      </Card>
      <AnalysisGate cur={cur} title="Sensitivity" empty={<StatePanel state="empty" title="No sensitivity sweep for this revision yet">Choose an uncertain input and a range of values.</StatePanel>}>
        {(a) => <SensitivityView objective={req?.objective} a={a} history={cur.history} onPickAnalysis={(id) => sel.setParams({ analysis: id })} />}
      </AnalysisGate>
    </div>
  );
}

function SensitivityView({ a, history, onPickAnalysis, objective }: { objective?: string; a: AnalysisView<SensitivityResult>; history: ReturnType<typeof useCurrentAnalysis>["history"]; onPickAnalysis: (id: string) => void }) {
  const t = chartTokens();
  const r = a.result;
  const p = (r?.parameter ?? a.request.parameter) as SensitivityParameter;
  const unit = r?.objective_unit ?? "kg";
  const pts = useMemo(() => r?.points ?? [], [r]);
  const steps = r?.steps ?? [];
  const changeAt = new Set(steps.filter((s) => s.decision_changes).map((s) => s.to_value));
  const option = useMemo(() => {
    const b = baseOption();
    const feas = pts.filter((x) => x.objective_value !== null && x.objective_value !== undefined);
    return {
      ...b,
      grid: { left: 70, right: 24, top: 36, bottom: 48 },
      tooltip: { ...(b.tooltip as object), trigger: "axis", valueFormatter: (v: number) => formatWithUnit(v, unit) },
      legend: { top: 0, right: 8, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      xAxis: {
        ...(b.xAxis as object),
        type: "value",
        scale: true,
        name: PARAMS.find((x) => x.value === p)?.label,
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => fmtVal(p, v).replace("PKR ", "") },
      },
      yAxis: { ...(b.yAxis as object), type: "value", ...(paddedRange(feas.flatMap((x) => [x.objective_value, x.objective_upper_bound])) ?? { scale: true }), name: objectiveLabel(objective), axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatWithUnit(v, unit) } },
      series: [
        {
          type: "line",
          name: "Incumbent objective",
          data: feas.map((x) => ({
            value: [x.value, x.objective_value],
            symbol: changeAt.has(x.value) ? "diamond" : "circle",
            symbolSize: changeAt.has(x.value) ? 13 : 8,
            itemStyle: { color: changeAt.has(x.value) ? t.warning : t.water, borderColor: t.ink, borderWidth: changeAt.has(x.value) ? 1.5 : 0 },
          })),
          lineStyle: { color: t.water, width: 2 },
          itemStyle: { color: t.water },
          z: 3,
        },
        {
          type: "line",
          name: "Solver upper bound",
          data: feas.filter((x) => x.objective_upper_bound !== null && x.objective_upper_bound !== undefined).map((x) => [x.value, x.objective_upper_bound]),
          lineStyle: { color: t.ink3, width: 1, type: "dashed" },
          itemStyle: { color: t.ink3 },
          symbol: "none",
          z: 2,
        },
      ],
    };
  }, [pts, t, p, unit, changeAt, objective]);

  return (
    <div className="flex flex-col gap-3">
      <AnalysisStatusBar a={a} history={history} onPick={onPickAnalysis} unitLabel="value runs" />
      {!pts.length ? (
        <StatePanel state="busy" title="Solving child scenarios…">Points appear as each value's run finishes.</StatePanel>
      ) : (
        <>
          <div className={`rounded-[12px] border px-4 py-3 ${r?.decision_stable === false ? "border-warning/40 bg-warning-soft/60" : "border-border bg-surface"}`} data-testid="sensitivity-verdict">
            <div className="flex flex-wrap items-center gap-2">
              {r?.decision_stable === false ? <Chip tone="warning">Decision changes within the range</Chip> : r?.decision_stable ? <Chip tone="vegetation">Portfolio stable across the range</Chip> : null}
              <span className="text-[12px] text-ink-secondary">{r?.label}</span>
            </div>
            {r?.resolving_measurement ? <p className="mt-1.5 text-[13px] text-ink">{r.resolving_measurement}</p> : null}
          </div>
          <ChartPanel
            id="sensitivity-chart"
            title={`${objectiveLabel(objective)} vs ${PARAMS.find((x) => x.value === p)?.label.toLowerCase()}`}
            summary="Each point is an independently solved child scenario; lines are guides between solved values. Diamonds mark values where the selected portfolio changes."
            chart={<EChart option={option} height={300} ariaLabel="Objective against the swept input value" />}
            table={
              <DataTable
                caption="Sensitivity points"
                columns={[
                  { key: "v", label: "Value" },
                  { key: "st", label: "Solver" },
                  { key: "obj", label: "Objective", align: "right" },
                  { key: "ub", label: "Bound", align: "right" },
                  { key: "cap", label: "Capital committed", align: "right" },
                  { key: "run", label: "Run" },
                ]}
                rows={pts.map((x) => ({
                  v: fmtVal(p, x.value),
                  st: <OutcomeBadge status={x.solver_status} outcome={x.outcome} />,
                  obj: x.objective_value !== null && x.objective_value !== undefined ? formatWithUnit(x.objective_value, unit) : x.reason ?? "no plan",
                  ub: x.objective_upper_bound !== null && x.objective_upper_bound !== undefined ? formatWithUnit(x.objective_upper_bound, unit) : "—",
                  cap: x.capital_commitment_pkr !== null && x.capital_commitment_pkr !== undefined ? formatPKR(x.capital_commitment_pkr) : "—",
                  run: x.run_id ? <RunLink runId={x.run_id} /> : "—",
                }))}
              />
            }
          />
          {steps.length ? (
            <Card>
              <h3 className="mb-2 text-[13px] font-semibold text-ink">Steps between adjacent values</h3>
              <div className="overflow-x-auto">
                <DataTable
                  caption="Finite-difference steps"
                  columns={[
                    { key: "s", label: "Step" },
                    { key: "d", label: "Objective change", align: "right" },
                    { key: "m", label: "Marginal value", align: "right" },
                    { key: "c", label: "Portfolio", className: "pl-6" },
                  ]}
                  rows={steps.map((s) => ({
                    s: `${fmtVal(p, s.from_value)} → ${fmtVal(p, s.to_value)}`,
                    d: (
                      <span className="inline-flex flex-col items-end">
                        <span>{differenceText(s.objective_difference, unit)}</span>
                        {s.objective_difference.status !== "exact" && s.objective_difference.reason ? <span className="font-sans text-[11px] text-ink-tertiary">{s.objective_difference.reason}</span> : null}
                      </span>
                    ),
                    m: s.marginal_value_per_m3
                      ? `${formatRange(s.marginal_value_per_m3.lower, s.marginal_value_per_m3.upper, 2)} ${unit}/m³`
                      : s.marginal_value_per_pkr
                        ? `${formatRange(s.marginal_value_per_pkr.lower * 1000, s.marginal_value_per_pkr.upper * 1000, 2)} ${unit} per 1,000 PKR`
                        : "—",
                    c:
                      s.decision_changes === undefined ? (
                        "—"
                      ) : s.decision_changes ? (
                        <span className="inline-flex flex-col font-sans">
                          <span className="font-medium text-warning">Changes</span>
                          {s.instances_added?.length ? <span className="text-[11px] text-ink-secondary">+ {s.instances_added.map(instanceShort).join(", ")}</span> : null}
                          {s.instances_removed?.length ? <span className="text-[11px] text-ink-secondary">− {s.instances_removed.map(instanceShort).join(", ")}</span> : null}
                        </span>
                      ) : (
                        <span className="font-sans text-ink-secondary">Same</span>
                      ),
                  }))}
                />
              </div>
            </Card>
          ) : null}
          {r?.note ? <p className="px-1 text-[11px] leading-relaxed text-ink-tertiary">{r.note}</p> : null}
        </>
      )}
    </div>
  );
}

function formatRange(lo: number, hi: number, digits: number) {
  const f = (v: number) => (Math.abs(v) < 0.5 * 10 ** -digits ? "0" : v.toFixed(digits).replace("-", "−"));
  return Math.abs(hi - lo) < 10 ** -digits ? f(lo) : `${f(lo)} to ${f(hi)}`;
}

