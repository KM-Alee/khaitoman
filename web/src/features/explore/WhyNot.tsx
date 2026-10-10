/**
 * Decision explanations (PRD §7.5, T7.3–T7.4): a forced/excluded alternative solve for one
 * intervention ("why not?") and the four matched solves behind a synergy estimate.
 * Differences are exact only when the server proves them; otherwise the supported interval
 * or "not comparable" is shown with the server's reason.
 */
import { useMemo, useState, type ReactNode } from "react";
import { HelpCircle, Play, Sigma } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useInterventions } from "@/lib/api/queries";
import type { InterventionInstance } from "@/lib/api/types";
import { formatDate, formatDelta, formatPKR, formatWithUnit, titleCase } from "@/lib/formatting";
import { DataTable } from "@/components/charts/EChart";
import { Chip, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Eyebrow, Segmented, Select } from "@/components/ui/primitives";
import { Rows } from "@/features/impact/viewKit";
import {
  instanceShort,
  objectiveLabel,
  objectiveUnit,
  useCurrentAnalysis,
  useLaunchAnalysis,
  type AnalysisView,
  type ArmKey,
  type ChildPoint,
  type ExploreBase,
  type InstanceFacts,
  type SynergyResult,
  type WhyNotResult,
} from "./api";
import { AnalysisGate, AnalysisStatusBar, Card, CardHeader, DifferenceChip, OutcomeBadge, RunLink, Stat, differenceText } from "./kit";

const CATEGORY_LABEL: Record<string, string> = {
  leveling: "Field leveling",
  pond: "On-farm pond",
  shared_repair: "Shared watercourse repair",
  pump_supplement: "Pump supplement",
  timing: "Timing / operations",
};

function useCatalog(base: ExploreBase) {
  const sel = useSelection();
  const req = base.revision.data?.revision.request;
  return useInterventions(sel.pilotId, req?.season_id, req?.decision_at);
}

function InstanceOptions({ items, selected, filter }: { items: InterventionInstance[]; selected: string[]; filter?: (i: InterventionInstance) => boolean }) {
  const groups = useMemo(() => {
    const m = new Map<string, InterventionInstance[]>();
    for (const it of items.filter(filter ?? (() => true))) m.set(it.category, [...(m.get(it.category) ?? []), it]);
    return [...m.entries()];
  }, [items, filter]);
  return (
    <>
      {groups.map(([cat, xs]) => (
        <optgroup key={cat} label={CATEGORY_LABEL[cat] ?? titleCase(cat)}>
          {xs.map((it) => (
            <option key={it.instance_id} value={it.instance_id}>
              {selected.includes(it.instance_id) ? "✓ in plan · " : ""}
              {instanceShort(it.instance_id)}
              {it.capex_pkr ? ` · ${formatPKR(it.capex_pkr)}` : ""}
              {it.eligible === false ? " · ineligible" : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/* ================================================================ why not */
export function WhyNot({ base }: { base: ExploreBase }) {
  const sel = useSelection();
  const catalog = useCatalog(base);
  const items = catalog.data ?? [];
  const run = base.run.data;
  const planRun = run?.outcome === "plan" && run.scenario_revision_id === base.revisionId ? run : null;
  const inPlan = planRun?.selected_intervention_instance_ids ?? [];
  const [instance, setInstance] = useState("");
  const [action, setAction] = useState<"force" | "exclude">("force");
  const [limit, setLimit] = useState(10);
  const cur = useCurrentAnalysis("why-not", { revisionId: base.revisionId });
  const runner = useLaunchAnalysis("why-not");
  const it = items.find((i) => i.instance_id === instance);
  const already = instance ? (action === "force" ? inPlan.includes(instance) : !inPlan.includes(instance)) : false;

  return (
    <div className="flex flex-col gap-3" data-testid="why-not">
      <Card>
        <CardHeader icon={<HelpCircle size={16} className="text-water" aria-hidden />} title="Why not this investment?">
          Ineligible, too late or over budget is explained from validations. A quantitative opportunity cost needs a forced-inclusion (or exclusion) solve against the base plan; if solver
          bounds are unresolved the difference is shown as an interval.
        </CardHeader>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Select
            label="Intervention instance"
            value={instance}
            onChange={(e) => {
              setInstance(e.target.value);
              setAction(inPlan.includes(e.target.value) ? "exclude" : "force");
            }}
            className="min-w-[260px] flex-1"
            disabled={catalog.isLoading}
          >
            <option value="">{catalog.isLoading ? "Loading catalog…" : "Choose…"}</option>
            <InstanceOptions items={items} selected={inPlan} />
          </Select>
          <div className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Treatment
            <Segmented
              label="Treatment"
              size="sm"
              value={action}
              onChange={setAction}
              options={[
                { value: "force", label: "Force include" },
                { value: "exclude", label: "Exclude" },
              ]}
            />
          </div>
          <label className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
            Time limit
            <select className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[12px] text-ink" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[5, 10, 20, 40].map((v) => (
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
            disabled={!instance || !base.revisionId}
            onClick={() =>
              void runner.launch({
                contract_version: "2.0.0",
                base_revision_id: base.revisionId!,
                instance_id: instance,
                action,
                base_run_id: planRun?.run_id ?? null,
                time_limit_s: limit,
              })
            }
            data-testid="run-why-not"
          >
            Solve alternative
          </Button>
        </div>
        {it ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-ink-secondary">
            <Chip size="sm">{CATEGORY_LABEL[it.category] ?? it.category}</Chip>
            <span>capital {formatPKR(it.capex_pkr)}</span>
            {it.earliest_commissioning ? <span>· commissions {formatDate(it.earliest_commissioning)}</span> : null}
            {inPlan.includes(it.instance_id) ? <Chip size="sm" tone="vegetation">In the base plan</Chip> : null}
            {already ? <span className="text-ink-tertiary">· the server will report “no change” for this treatment</span> : null}
          </div>
        ) : null}
        {it?.eligible === false ? (
          <div className="mt-2 rounded-[10px] bg-warning-soft px-3 py-2 text-[12px] text-warning">
            Not eligible: {it.eligibility_reasons?.join("; ") || "see validation"}. Forcing it is expected to fail validation or be infeasible; no penalty is invented.
          </div>
        ) : null}
        {!planRun ? <p className="mt-2 text-[12px] text-ink-tertiary">No plan run of this revision is linked; the server reuses the latest plan of the revision or solves one first.</p> : null}
      </Card>

      <AnalysisGate cur={cur} title="Why-not result" skeleton="h-48" empty={<StatePanel state="empty" title="No why-not solve for this revision yet">Pick an investment and solve the alternative.</StatePanel>}>
        {(a) => <WhyNotView a={a} history={cur.history} onPickAnalysis={(id) => sel.setParams({ analysis: id })} />}
      </AnalysisGate>

      <Synergy base={base} />
    </div>
  );
}

function objText(p: ChildPoint | null | undefined, unit: string) {
  if (!p) return "—";
  if (p.outcome === "rejected") return "Rejected by validation";
  if (p.objective_value === null || p.objective_value === undefined) return p.solver_status === "INFEASIBLE" ? "No feasible plan" : "No plan";
  return formatWithUnit(p.objective_value, unit);
}
function boundText(p: ChildPoint | null | undefined, unit: string) {
  if (!p || p.objective_value === null || p.objective_value === undefined) return null;
  if (p.solver_status === "OPTIMAL") return "proven optimal";
  if (p.objective_upper_bound !== null && p.objective_upper_bound !== undefined && p.objective_upper_bound !== p.objective_value) return `bound ≤ ${formatWithUnit(p.objective_upper_bound, unit)}`;
  return p.solver_status ?? null;
}

function WhyNotView({ a, history, onPickAnalysis }: { a: AnalysisView<WhyNotResult>; history: ReturnType<typeof useCurrentAnalysis>["history"]; onPickAnalysis: (id: string) => void }) {
  const r = a.result;
  const unit = objectiveUnit(r?.objective);
  const inst = String(r?.instance_id ?? a.request.instance_id ?? "");
  const action = String(r?.action ?? a.request.action ?? "force");
  const deltas = (r?.deltas ?? []).filter((d) => d.status === "available" && d.delta !== null && d.delta !== 0);
  return (
    <div className="flex flex-col gap-3" data-testid="why-not-result">
      <AnalysisStatusBar a={a} history={history} onPick={onPickAnalysis} />
      {!r?.base && !r?.difference ? (
        <StatePanel state="busy" title="Solving the alternative…">
          The base plan is reused or solved first, then the {action === "force" ? "forced" : "excluded"} alternative.
        </StatePanel>
      ) : (
        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h3 className="text-[13px] font-semibold text-ink">
              {action === "force" ? "Force include" : "Exclude"} {instanceShort(inst)}
            </h3>
            <DifferenceChip d={r.difference} />
            {r.certificate ? <Chip size="sm" tone={r.certificate.compatible ? "neutral" : "warning"}>{r.certificate.label}</Chip> : null}
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Stat label={`Base plan · ${objectiveLabel(r.objective)}`} value={objText(r.base, unit)} sub={<>{boundText(r.base, unit)} {r.base?.run_id ? <RunLink runId={r.base.run_id} /> : null}</>} />
            <Stat
              label="Alternative"
              value={r.alternative === null ? "Same as base" : objText(r.alternative, unit)}
              sub={
                r.alternative ? (
                  <>
                    {r.alternative.outcome === "rejected" ? r.alternative.reason : boundText(r.alternative, unit)} {r.alternative.run_id ? <RunLink runId={r.alternative.run_id} /> : null}
                  </>
                ) : (
                  "no alternative solve was needed"
                )
              }
            />
            <Stat
              label="Difference (alternative − base)"
              value={differenceText(r.difference, unit)}
              sub={r.difference?.reason ?? (r.difference?.status === "exact" ? "both runs proven optimal" : r.difference?.definition)}
              testId="why-not-difference"
            />
          </div>
          {r.explanation?.length ? (
            <ul className="mt-3 list-disc pl-5 text-[13px] leading-relaxed text-ink-secondary">
              {r.explanation.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          ) : null}
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {r.instance ? <FactsPanel f={r.instance} /> : null}
            {deltas.length ? (
              <div className="min-w-0">
                <Eyebrow className="mb-1">Network metrics that change{r.certificate && !r.certificate.compatible ? " (not causal)" : ""}</Eyebrow>
                <DataTable
                  dense
                  caption="Metric deltas between base and alternative"
                  columns={[
                    { key: "m", label: "Metric" },
                    { key: "a", label: "Base", align: "right" },
                    { key: "b", label: "Alternative", align: "right" },
                    { key: "d", label: "Δ", align: "right" },
                  ]}
                  rows={deltas.map((d) => ({
                    m: <span className="font-sans">{metricLabel(d.metric_id)}</span>,
                    a: d.a !== null ? formatWithUnit(d.a, d.unit) : "—",
                    b: d.b !== null ? formatWithUnit(d.b, d.unit) : "—",
                    d: formatDelta(d.delta!, d.unit),
                  }))}
                />
              </div>
            ) : null}
          </div>
        </Card>
      )}
    </div>
  );
}

function metricLabel(id: string) {
  const t = id.replace(/^sdg_(\d+)_(\d+)_/, "SDG $1.$2 · ").replace(/_(kg_m3|m3|kg|pkr|count)$/, "").replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function FactsPanel({ f }: { f: InstanceFacts }) {
  if (!f.exists) return <p className="text-[12px] text-ink-secondary">{f.instance_id} is not in this pilot version.</p>;
  const rows: [string, ReactNode][] = [
    ["Category", CATEGORY_LABEL[f.category ?? ""] ?? f.category ?? "—"],
    ["Capital cost", f.capex_pkr !== undefined ? `${formatPKR(f.capex_pkr)}${f.over_capital_budget ? " · over budget" : ""}` : "—"],
    ["Capital budget", f.capital_budget_pkr !== undefined ? formatPKR(f.capital_budget_pkr) : "—"],
    ["Commissioned", f.commissioned_on ? formatDate(f.commissioned_on) : "—"],
    ["Candidate options using it", f.candidate_policies_or_configurations_using_it ?? "—"],
  ];
  if (f.mutually_exclusive_with?.length) rows.push(["Mutually exclusive with", f.mutually_exclusive_with.map(instanceShort).join(", ")]);
  if (f.prerequisites?.length) rows.push(["Prerequisites", f.prerequisites.map(instanceShort).join(", ")]);
  return (
    <div className="min-w-0">
      <Eyebrow className="mb-1">Validation facts</Eyebrow>
      <Rows rows={rows} />
    </div>
  );
}

/* ================================================================ synergy */
const ARM_LABEL: Record<ArmKey, string> = { none: "Neither", a: "A only", b: "B only", ab: "A + B" };

function Synergy({ base }: { base: ExploreBase }) {
  const sel = useSelection();
  const catalog = useCatalog(base);
  const items = useMemo(() => (catalog.data ?? []).filter((i) => i.category !== "timing"), [catalog.data]);
  const run = base.run.data;
  const planRun = run?.outcome === "plan" && run.scenario_revision_id === base.revisionId ? run : null;
  const inPlan = planRun?.selected_intervention_instance_ids ?? [];
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [rule, setRule] = useState<"fixed" | "reoptimize">("reoptimize");
  const [limit, setLimit] = useState(8);
  const cur = useCurrentAnalysis("synergy", { revisionId: base.revisionId });
  const runner = useLaunchAnalysis("synergy");
  const groupA = items.find((x) => x.instance_id === a)?.mutually_exclusive_group ?? null;
  const filterB = useMemo(() => (i: InterventionInstance) => i.instance_id !== a && (!groupA || i.mutually_exclusive_group !== groupA), [a, groupA]);
  return (
    <Card testId="synergy">
      <CardHeader icon={<Sigma size={16} className="text-water" aria-hidden />} title="Synergy between two investments">
        Four matched solves: neither, A, B, and A+B. Synergy = outcome(A+B) − outcome(A) − outcome(B) + outcome(neither), in the objective's unit; negative synergy is valid. Infeasible or
        unmatched combinations are explained, not turned into a number.
      </CardHeader>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Select label="Investment A" value={a} onChange={(e) => setA(e.target.value)} className="min-w-[220px] flex-1">
          <option value="">Choose…</option>
          <InstanceOptions items={items} selected={inPlan} />
        </Select>
        <Select label="Investment B" value={b} onChange={(e) => setB(e.target.value)} className="min-w-[220px] flex-1">
          <option value="">Choose…</option>
          <InstanceOptions items={items} selected={inPlan} filter={filterB} />
        </Select>
        <div className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
          Other investments
          <Segmented
            label="Other investments"
            size="sm"
            value={rule}
            onChange={setRule}
            options={[
              { value: "reoptimize", label: "Re-optimised" },
              { value: "fixed", label: "Held fixed", title: "Hold the base plan's other investments fixed in all four runs" },
            ]}
          />
        </div>
        <label className="flex flex-col gap-1 text-[12px] font-medium text-ink-secondary">
          Per arm
          <select className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[12px] text-ink" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[4, 8, 15, 30].map((v) => (
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
          disabled={!a || !b || a === b || !base.revisionId}
          onClick={() =>
            void runner.launch({
              contract_version: "2.0.0",
              base_revision_id: base.revisionId!,
              instance_a: a,
              instance_b: b,
              other_actions: rule,
              base_run_id: planRun?.run_id ?? null,
              time_limit_per_arm_s: limit,
            })
          }
          data-testid="run-synergy"
        >
          Run 4 solves
        </Button>
      </div>
      <div className="mt-4">
        <AnalysisGate cur={cur} title="Synergy" skeleton="h-40" empty={<p className="text-[12px] text-ink-tertiary">No synergy evaluated for this revision yet.</p>}>
          {(x) => <SynergyView a={x} history={cur.history} onPickAnalysis={(id) => sel.setParams({ analysis: id })} />}
        </AnalysisGate>
      </div>
    </Card>
  );
}

function SynergyView({ a, history, onPickAnalysis }: { a: AnalysisView<SynergyResult>; history: ReturnType<typeof useCurrentAnalysis>["history"]; onPickAnalysis: (id: string) => void }) {
  const r = a.result;
  const unit = objectiveUnit(r?.objective);
  const syn = r?.synergy;
  const arms = r?.arms ?? {};
  const synText = !syn
    ? a.status === "running" || a.status === "queued"
      ? "Solving…"
      : "Not reported"
    : syn.status === "exact" && syn.value !== null
      ? formatDelta(syn.value, unit)
      : syn.status === "interval" && syn.lower !== null && syn.upper !== null
        ? `${formatDelta(syn.lower, unit)} to ${formatDelta(syn.upper, unit)}`
        : "Not computable";
  return (
    <div className="flex flex-col gap-3" data-testid="synergy-result">
      <AnalysisStatusBar a={a} history={history} onPick={onPickAnalysis} unitLabel="arm runs" />
      <div className="text-[12px] text-ink-secondary">
        A = <span className="font-medium text-ink">{instanceShort(String(r?.instance_a ?? a.request.instance_a ?? ""))}</span> · B ={" "}
        <span className="font-medium text-ink">{instanceShort(String(r?.instance_b ?? a.request.instance_b ?? ""))}</span> · other investments{" "}
        {(r?.other_actions ?? a.request.other_actions) === "fixed" ? `held fixed${r?.held_fixed_instance_ids ? ` (${r.held_fixed_instance_ids.length})` : ""}` : "re-optimised"}
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-w-0 overflow-x-auto">
          <DataTable
            caption="Synergy arms"
            columns={[
              { key: "k", label: "Combination" },
              { key: "v", label: objectiveLabel(r?.objective), align: "right" },
              { key: "ub", label: "Bound", align: "right" },
              { key: "st", label: "Solver", className: "pl-5" },
              { key: "run", label: "Run", className: "pl-3" },
            ]}
            rows={(["none", "a", "b", "ab"] as ArmKey[]).map((k) => {
              const arm = arms[k];
              return {
                k: <span className="font-sans font-medium">{ARM_LABEL[k]}</span>,
                v: arm ? objText(arm, unit) : a.status === "running" || a.status === "queued" ? "pending" : "—",
                ub: arm ? boundText(arm, unit) ?? "—" : "—",
                st: arm ? <OutcomeBadge status={arm.solver_status} outcome={arm.outcome} /> : "—",
                run: arm?.run_id ? <RunLink runId={arm.run_id} /> : "—",
              };
            })}
          />
        </div>
        <div className="rounded-[12px] bg-surface-muted p-4">
          <div className="text-[11px] text-ink-secondary">Synergy (A+B − A − B + neither)</div>
          <div className="num mt-1 text-[22px] font-semibold tracking-[-0.01em] text-ink" data-testid="synergy-value">
            {synText}
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {syn ? <Chip size="sm" tone={syn.status === "exact" ? "vegetation" : syn.status === "interval" ? "warning" : "neutral"}>{titleCase(syn.status)}</Chip> : null}
            {syn?.sign ? <Chip size="sm">{syn.sign}</Chip> : null}
          </div>
          {syn?.reason ? <p className="mt-2 text-[12px] text-ink-secondary">{syn.reason}</p> : null}
          {syn?.status === "interval" && syn.incumbent_value !== null && syn.incumbent_value !== undefined ? (
            <p className="mt-1 text-[11px] text-ink-tertiary">Incumbent arithmetic {formatDelta(syn.incumbent_value, unit)} (not proven).</p>
          ) : null}
        </div>
      </div>
      {syn?.explanations && Object.keys(syn.explanations).length ? (
        <div>
          <Eyebrow className="mb-1">Why some arms have no plan</Eyebrow>
          <ul className="list-disc pl-5 text-[12px] text-ink-secondary">
            {Object.entries(syn.explanations).map(([k, xs]) => (
              <li key={k}>
                <span className="font-medium text-ink">{ARM_LABEL[k as ArmKey] ?? k}:</span> {xs.filter(Boolean).join("; ")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {r?.certificate ? <p className="text-[11px] text-ink-tertiary">Comparison certificate: {r.certificate.label}.</p> : null}
    </div>
  );
}
