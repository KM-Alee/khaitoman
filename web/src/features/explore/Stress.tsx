/**
 * Stress matrix (PRD §7.3, T7.2): the chosen plan in every tested weather × supply state.
 * Each cell first answers "can this plan be delivered?"; undeliverable cells carry the
 * violated rule and never an achievable yield. Worst case means worst within the tested states.
 */
import { useMemo, useState } from "react";
import { Ban, CheckCircle2, Grid3x3, Play } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useUncertaintySets } from "@/lib/api/queries";
import { formatVolume, formatWithUnit, titleCase } from "@/lib/formatting";
import { DataTable } from "@/components/charts/EChart";
import { makeScale } from "@/components/map/palette";
import { Chip, MetricValueView, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { useFieldLabel } from "@/features/impact/viewKit";
import { cn } from "@/lib/cn";
import { useCurrentAnalysis, useLaunchAnalysis, type AnalysisView, type ExploreBase, type StressCell, type StressResult } from "./api";
import { AnalysisGate, AnalysisStatusBar, Card, CardHeader, OutcomeBadge, RunLink, Stat } from "./kit";

const METRIC_LABEL: Record<string, string> = {
  worst_tested_production_kg: "Worst tested production",
  sdg_13_1_worst_tested_production_kg: "SDG 13.1 proxy · worst tested production",
  sdg_2_4_production_retained_fraction: "SDG 2.4 proxy · production retained (worst ÷ typical)",
};

export function Stress({ base }: { base: ExploreBase }) {
  const sel = useSelection();
  const run = base.run.data;
  const req = base.revision.data?.revision.request;
  const uc = useUncertaintySets(sel.pilotId, req?.season_id).data;
  const usId = req?.uncertainty_set_id ?? uc?.sets?.[0]?.uncertainty_set_id ?? null;
  const us = uc?.sets?.find((s) => s.uncertainty_set_id === usId) ?? null;
  const nStates = us?.states?.length ?? null;
  const cur = useCurrentAnalysis("stress", { runId: base.runId });
  const runner = useLaunchAnalysis("stress");
  const [mode, setMode] = useState<"fixed_plan" | "recovery_plan">("fixed_plan");
  const [limit, setLimit] = useState(6);
  const isPlan = run?.outcome === "plan";
  const blocked = !base.runId ? "Open a run first: stress testing evaluates one chosen plan." : !run ? "Loading the run…" : !isPlan ? `Run ${run.plan_kind} has no validated plan (${run.solver_status}); only plans can be stress-tested.` : null;

  return (
    <div className="flex flex-col gap-3" data-testid="stress">
      <Card>
        <CardHeader
          icon={<Grid3x3 size={16} className="text-water" aria-hidden />}
          title="Stress matrix"
          aside={
            <>
              <Segmented
                label="Stress mode"
                size="sm"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "fixed_plan", label: "Fixed plan" },
                  { value: "recovery_plan", label: "Recovery replanning", title: "Investments held fixed; operations re-optimised separately in each state" },
                ]}
              />
              <label className="flex items-center gap-1.5 text-[12px] text-ink-secondary">
                Per cell
                <select className="h-7 rounded-[8px] border border-border-strong/60 bg-surface px-1.5 text-[12px] text-ink" value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="Solver time limit per cell">
                  {[3, 6, 12, 30].map((v) => (
                    <option key={v} value={v}>
                      {v} s
                    </option>
                  ))}
                </select>
              </label>
              <Button
                size="sm"
                variant="primary"
                icon={<Play size={13} />}
                busy={runner.pending}
                disabled={!!blocked}
                title={blocked ?? undefined}
                onClick={() => void runner.launch({ contract_version: "2.0.0", run_id: base.runId!, mode, time_limit_per_cell_s: limit })}
                data-testid="run-stress"
              >
                Evaluate {nStates ?? "all"} states
              </Button>
            </>
          }
        >
          {mode === "fixed_plan"
            ? "Holds the plan's dated receipts, pond operations and pumping fixed and asks whether they can be delivered in each tested weather analog × supply profile."
            : "Holds the plan's investments fixed and re-optimises operations separately in each state: scenario-specific replanning, not one prospective plan."}{" "}
          {us ? `States come from the uncertainty set ${us.uncertainty_set_id.split(":").pop()}${nStates ? ` (${nStates} states)` : ""}.` : ""} Worst case means worst within these tested
          states; no probability is implied.
        </CardHeader>
        {blocked && base.runId && run ? <p className="mt-2 text-[12px] text-warning">{blocked}</p> : null}
      </Card>

      <AnalysisGate
        cur={cur}
        title="Stress matrix"
        empty={
          <StatePanel state="empty" title="No stress evaluation for this run yet">
            Evaluate the {run ? `${run.plan_kind} run` : "linked run"} across the published states. Each cell becomes its own immutable run.
          </StatePanel>
        }
      >
        {(a) => <StressView a={a} history={cur.history} onPickAnalysis={(id) => sel.setParams({ analysis: id })} />}
      </AnalysisGate>
    </div>
  );
}

function StressView({ a, history, onPickAnalysis }: { a: AnalysisView<StressResult>; history: ReturnType<typeof useCurrentAnalysis>["history"]; onPickAnalysis: (id: string) => void }) {
  const r = a.result;
  const cells = useMemo(() => r?.cells ?? [], [r]);
  const [picked, setPicked] = useState<string | null>(null);
  const rows = r?.matrix?.rows ?? [...new Set(cells.map((c) => c.weather_scenario_id))];
  const cols = r?.matrix?.columns ?? [...new Set(cells.map((c) => c.supply_profile_id))];
  const byState = new Map(cells.map((c) => [c.state_id, c]));
  const cellAt = (w: string, s: string) => cells.find((c) => c.weather_scenario_id === w && c.supply_profile_id === s);
  const scale = useMemo(() => makeScale("sequential-yield", cells.filter((c) => c.deliverable && c.production_kg !== null).map((c) => c.production_kg!)), [cells]);
  const sum = r?.summary;
  const metrics = r?.mode === "recovery_plan" ? r?.recovery_metrics ?? {} : r?.metrics_by_id ?? {};
  const pc = (picked ? byState.get(picked) : null) ?? null;
  const supplyLabel = (s: string) => cells.find((c) => c.supply_profile_id === s)?.supply_label ?? s;
  const recovery = r?.mode === "recovery_plan";

  return (
    <div className="flex flex-col gap-3">
      <AnalysisStatusBar a={a} history={history} onPick={onPickAnalysis} unitLabel="state runs" />
      {!r || !cells.length ? (
        <StatePanel state="busy" title="Evaluating states…">Cells fill in as each state's run finishes.</StatePanel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" data-testid="stress-summary">
            <Stat
              label={recovery ? "Recovery plan found" : "Deliverable"}
              value={`${sum?.deliverable ?? cells.filter((c) => c.deliverable).length} of ${sum?.tested ?? cells.length}`}
              sub={sum?.undeliverable_state_ids.length ? `${sum.undeliverable_state_ids.length} state${sum.undeliverable_state_ids.length > 1 ? "s" : ""} ${recovery ? "without a recovery plan" : "undeliverable"}` : "every tested state"}
            />
            <Stat
              label={recovery ? "Worst tested · conditional on replanning" : "Worst tested production"}
              value={sum?.worst_tested_production_kg !== null && sum?.worst_tested_production_kg !== undefined ? formatWithUnit(sum.worst_tested_production_kg, "kg") : "Blocked"}
              sub={sum?.worst_tested_production_kg === null ? "the plan is undeliverable in some tested states, so no worst case is claimed" : r.worst_case_scope}
            />
            <Stat
              label="Minimum over deliverable cells"
              value={sum?.conditional_min_over_deliverable_kg !== null && sum?.conditional_min_over_deliverable_kg !== undefined ? formatWithUnit(sum.conditional_min_over_deliverable_kg, "kg") : "—"}
              sub={sum?.conditional_label ?? "same as worst tested when all cells deliver"}
            />
            <Stat
              label="Typical state production"
              value={sum?.typical_production_kg !== null && sum?.typical_production_kg !== undefined ? formatWithUnit(sum.typical_production_kg, "kg") : "—"}
              sub={sum?.best_tested_production_kg !== null && sum?.best_tested_production_kg !== undefined ? `best tested ${formatWithUnit(sum.best_tested_production_kg, "kg")}` : undefined}
            />
          </div>

          <Card labelledBy="stress-h">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h3 id="stress-h" className="text-[13px] font-semibold text-ink">
                {r.label ?? titleCase(String(r.mode ?? ""))} · {r.source_plan_kind ?? ""} plan
              </h3>
              {sum?.undeliverable_state_ids.length ? (
                <Chip tone="warning" icon={<Ban size={11} aria-hidden />}>
                  {sum.undeliverable_state_ids.length} {recovery ? "without plan" : "undeliverable"}
                </Chip>
              ) : (
                <Chip tone="vegetation" icon={<CheckCircle2 size={11} aria-hidden />}>
                  {recovery ? "Recovery plan in every state" : "All deliverable"}
                </Chip>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[540px] table-fixed border-separate border-spacing-1.5" aria-label="Stress matrix: weather analogs by supply profiles" data-testid="stress-matrix">
                <thead>
                  <tr>
                    <th scope="col" className="w-[84px] text-left text-[11px] font-medium leading-tight text-ink-tertiary">
                      Weather ↓<br />Supply →
                    </th>
                    {cols.map((s) => (
                      <th key={s} scope="col" className="text-left text-[12px] font-semibold text-ink">
                        {titleCase(supplyLabel(s))}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((w) => (
                    <tr key={w}>
                      <th scope="row" className="pr-2 text-left text-[12px] font-semibold text-ink">
                        {titleCase(w)}
                      </th>
                      {cols.map((s) => {
                        const c = cellAt(w, s);
                        if (!c)
                          return (
                            <td key={s} className="rounded-[12px] border border-dashed border-border bg-surface-muted/60 p-3 text-[12px] text-ink-tertiary">
                              {a.status === "running" || a.status === "queued" ? "Pending…" : "Not evaluated"}
                            </td>
                          );
                        return <MatrixCell key={s} c={c} recovery={recovery} color={scale.color(c.production_kg)} active={picked === c.state_id} typical={c.state_id === r.typical_state} onClick={() => setPicked(picked === c.state_id ? null : c.state_id)} />;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-tertiary">
              <span>Deliverability is shown by icon, text and hatch; colour encodes production only for deliverable cells.</span>
              <span className="inline-flex items-center gap-1.5">
                {formatWithUnit(scale.domain[0], "kg")}
                <span className="h-2 w-20 rounded-full" style={{ background: `linear-gradient(90deg, ${scale.stops.map((x) => `${x.color} ${x.t * 100}%`).join(",")})` }} aria-hidden />
                {formatWithUnit(scale.domain[1], "kg")}
              </span>
            </div>
            {pc ? <CellDetail c={pc} recovery={recovery} /> : <p className="mt-3 text-[12px] text-ink-secondary">Select a cell to see its violations or outcome and open its run.</p>}
          </Card>

          {Object.keys(metrics).length || r.foregone_typical_output ? (
            <div className="grid gap-3 md:grid-cols-2">
              {Object.keys(metrics).length ? (
                <Card>
                  <Eyebrow className="mb-2">{recovery ? "Conditional recovery metrics" : "Robustness metrics"}</Eyebrow>
                  {recovery ? <p className="mb-1 text-[12px] text-ink-secondary">Operations were re-optimised separately in each state; these are not the worst case of one prospective plan.</p> : null}
                  <dl className="flex flex-col divide-y divide-border">
                    {Object.entries(metrics).map(([k, m]) => (
                      <div key={k} className="flex flex-col gap-1 py-2">
                        <dt className="text-[12px] text-ink-secondary">{METRIC_LABEL[k] ?? titleCase(k)}</dt>
                        <dd>
                          <MetricValueView metric={m} size="sm" />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              ) : null}
              {r.foregone_typical_output ? (
                <Card>
                  <Eyebrow className="mb-2">Foregone typical-state output</Eyebrow>
                  <p className="num text-[20px] font-semibold text-ink">
                    {r.foregone_typical_output.foregone_kg !== null ? formatWithUnit(r.foregone_typical_output.foregone_kg, "kg") : "Not computable"}
                  </p>
                  <p className="mt-1 text-[12px] text-ink-secondary">{r.foregone_typical_output.note}</p>
                  <p className="mt-1 text-[12px] text-ink-tertiary">
                    Reference <RunLink runId={r.foregone_typical_output.reference_run_id} />
                  </p>
                </Card>
              ) : null}
            </div>
          ) : null}
          {r.note ? <p className="px-1 text-[11px] leading-relaxed text-ink-tertiary">{r.note}</p> : null}
        </>
      )}
    </div>
  );
}

function MatrixCell({ c, color, active, typical, onClick, recovery }: { c: StressCell; recovery: boolean; color: string; active: boolean; typical: boolean; onClick: () => void }) {
  const ok = c.deliverable;
  return (
    <td className="p-0">
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        aria-label={`${titleCase(c.weather_scenario_id)} weather, ${c.supply_label ?? c.supply_profile_id}: ${ok ? `deliverable, ${c.production_kg !== null ? formatWithUnit(c.production_kg, "kg") : "no production reported"}` : "not deliverable"}`}
        className={cn(
          "relative flex h-[96px] w-full flex-col justify-between overflow-hidden rounded-[12px] border p-2.5 text-left transition-shadow hover:shadow-2 focus-visible:outline-2",
          active ? "border-ink ring-2 ring-ink/20" : "border-border",
          !ok && "bg-[repeating-linear-gradient(135deg,var(--warning-soft)_0_8px,var(--surface)_8px_16px)]",
        )}
        style={ok ? { background: color } : undefined}
        data-testid="stress-cell"
        data-deliverable={String(ok)}
      >
        <span className="flex items-center justify-between gap-1">
          <span className={cn("inline-flex w-fit items-center gap-1 rounded-full bg-surface/90 px-1.5 py-0.5 text-[11px] font-semibold", ok ? "text-vegetation" : "text-warning")}>
            {ok ? <CheckCircle2 size={11} aria-hidden /> : <Ban size={11} aria-hidden />}
            {ok ? (recovery ? "Recovery plan" : "Deliverable") : recovery ? "No recovery plan" : "Not deliverable"}
          </span>
          {typical ? <span className="rounded-full bg-surface/90 px-1.5 py-0.5 text-[10px] font-medium text-ink-secondary">typical</span> : null}
        </span>
        <span className="num w-fit rounded-[6px] bg-surface/90 px-1.5 py-0.5 text-[13px] font-semibold text-ink">
          {ok ? (c.production_kg !== null ? formatWithUnit(c.production_kg, "kg") : "—") : `${c.violations?.length ?? 0} violation${c.violations?.length === 1 ? "" : "s"}`}
        </span>
      </button>
    </td>
  );
}

function CellDetail({ c, recovery }: { c: StressCell; recovery: boolean }) {
  const label = useFieldLabel();
  const v = c.violations ?? [];
  return (
    <div className="mt-3 rounded-[12px] border border-border bg-surface-muted/50 p-3" data-testid="stress-detail">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Eyebrow>
          {titleCase(c.weather_scenario_id)} weather × {c.supply_label ?? c.supply_profile_id}
        </Eyebrow>
        <OutcomeBadge status={c.solver_status} />
        {c.run_id ? <RunLink runId={c.run_id} label="Open state run" className="font-sans text-[12px] font-medium" /> : null}
      </div>
      {!c.deliverable ? (
        <>
          <p className="text-[13px] text-ink">
            {recovery
              ? "No recovery plan exists in this state with the investments held fixed."
              : "The planned receipts cannot be delivered in this state. The original schedule's yield is not shown as achievable."}
          </p>
          {v.length ? (
            <div className="mt-2 max-h-[260px] overflow-auto">
              <DataTable
                dense
                caption="Violations"
                columns={[
                  { key: "rule", label: "Rule" },
                  { key: "where", label: "Field / resource" },
                  { key: "when", label: "Period" },
                  { key: "detail", label: "Detail" },
                ]}
                rows={v.map((x) => ({
                  rule: titleCase(x.rule),
                  where: x.field_id ? label(x.field_id) : x.resource_id ? `${x.resource_id}${x.interval_id ? ` · ${x.interval_id}` : ""}` : "—",
                  when: x.period ? `${x.period[0].slice(0, 10)} → ${x.period[1].slice(0, 10)}` : "—",
                  detail: (
                    <span className="whitespace-normal font-sans text-ink-secondary">
                      {x.detail ?? "—"}
                      {x.used_m3 !== undefined && x.capacity_m3 !== undefined ? ` (${formatVolume(x.used_m3)} of ${formatVolume(x.capacity_m3)})` : ""}
                    </span>
                  ),
                }))}
              />
            </div>
          ) : null}
        </>
      ) : (
        <div className="flex flex-col gap-1 text-[13px] text-ink">
          <span className="num">
            Production {c.production_kg !== null ? formatWithUnit(c.production_kg, "kg") : "—"}
            {c.objective_upper_bound !== null && c.objective_upper_bound !== undefined && c.solver_status !== "OPTIMAL" ? ` · objective bound ≤ ${formatWithUnit(c.objective_upper_bound, "kg")}` : ""}
          </span>
          {recovery && c.unused_fixed_investments?.length ? (
            <span className="text-[12px] text-ink-secondary">
              {c.unused_fixed_investments.length} fixed investment{c.unused_fixed_investments.length > 1 ? "s" : ""} unused by the recovery plan in this state.
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}

