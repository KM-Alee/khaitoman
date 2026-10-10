import { useMemo, useState } from "react";
import { HelpCircle, Play, Sigma } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useRun } from "@/lib/api/queries";
import { formatDelta, formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Segmented, Select } from "@/components/ui/primitives";
import { DataTable } from "@/components/charts/EChart";
import { useScenario } from "@/features/workspace/useScenario";
import { CATEGORY_META } from "@/features/workspace/ScenarioPanel";
import { num, pickNum, useAnalysisRunner, useCurrentAnalysis } from "./analysis";

export function WhyNot() {
  const sel = useSelection();
  const s = useScenario();
  const run = useRun(sel.runId);
  const items = s.catalog.interventions.data ?? [];
  const selectedIds = run.data?.outcome === "plan" ? run.data.selected_intervention_instance_ids : [];
  const [instance, setInstance] = useState<string>("");
  const [mode, setMode] = useState<"force" | "exclude">("force");
  const cur = useCurrentAnalysis("why-not");
  const runner = useAnalysisRunner("why-not");
  const effectiveMode = selectedIds.includes(instance) ? "exclude" : mode;
  return (
    <div className="flex flex-col gap-3" data-testid="why-not">
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink">
          <HelpCircle size={16} className="text-water" aria-hidden /> Why not this investment?
        </h2>
        <p className="mt-0.5 max-w-[64ch] text-[12px] text-ink-secondary">
          Ineligible, too late or over budget is explained from validations. A quantitative opportunity cost needs a forced-inclusion solve; if bounds are unresolved the difference is
          shown as an interval or labelled provisional.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Select label="Intervention instance" value={instance} onChange={(e) => setInstance(e.target.value)} className="min-w-[280px] flex-1">
            <option value="">Choose…</option>
            {items.map((it) => (
              <option key={it.instance_id} value={it.instance_id}>
                {selectedIds.includes(it.instance_id) ? "✓ " : ""}
                {CATEGORY_META[it.category]?.label ?? it.category} · {it.label ?? it.instance_id}
                {it.eligible === false ? " (ineligible)" : ""}
              </option>
            ))}
          </Select>
          <Segmented
            label="Treatment"
            size="sm"
            value={effectiveMode}
            onChange={(v) => setMode(v as "force" | "exclude")}
            options={[
              { value: "force", label: "Force include", disabled: selectedIds.includes(instance) },
              { value: "exclude", label: "Exclude" },
            ]}
          />
          <Button
            size="sm"
            variant="primary"
            icon={<Play size={13} />}
            busy={runner.pending}
            disabled={!instance || !sel.runId}
            onClick={() => void runner.run({ base_run_id: sel.runId, instance_id: instance, mode: effectiveMode })}
            data-testid="run-why-not"
          >
            Solve alternative
          </Button>
        </div>
        {instance && items.find((i) => i.instance_id === instance)?.eligible === false ? (
          <div className="mt-2 rounded-[10px] bg-warning-soft px-3 py-2 text-[12px] text-warning">
            Not eligible: {items.find((i) => i.instance_id === instance)?.eligibility_reasons?.join("; ") || "see validation"}. A forced solve would be rejected; no penalty is invented.
          </div>
        ) : null}
      </section>
      {cur.loading ? <Skeleton className="h-40" /> : cur.error ? <StatePanel state="error" error={cur.error} title="Why-not result unavailable" /> : cur.data ? <WhyNotResult a={cur.data} /> : null}
      <Synergy />
    </div>
  );
}

function WhyNotResult({ a }: { a: Record<string, unknown> }) {
  const sel = useSelection();
  const r = (a.result ?? {}) as Record<string, unknown>;
  const unit = String(r.unit ?? "kg");
  const base = pickNum(r, "base_objective", "base_objective_value");
  const alt = pickNum(r, "alt_objective", "alt_objective_value");
  const altUb = pickNum(r, "alt_upper_bound");
  const interval = (r.delta_interval as [number | null, number | null] | undefined) ?? null;
  const provisional = r.provisional === true;
  const status = String(a.status ?? "");
  const expl = (r.explanation as string[] | undefined) ?? (r.reasons as string[] | undefined) ?? [];
  if (status === "running" || status === "queued") return <StatePanel state="busy" title="Solving the alternative…">The forced/excluded solve is running; the result appears when the exact solve completes.</StatePanel>;
  return (
    <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1" data-testid="why-not-result">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13px] font-semibold text-ink">{titleCase(String(r.mode ?? "alternative"))}: {String(r.instance_id ?? a.instance_id ?? "")}</h3>
        {provisional ? <Chip tone="warning">Provisional — bounds unresolved</Chip> : <Chip tone="vegetation">Exact objectives</Chip>}
      </div>
      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-[12px] bg-surface-muted p-3">
          <dt className="text-[11px] text-ink-secondary">Base plan</dt>
          <dd className="num mt-0.5 text-[16px] font-semibold text-ink">{base !== null ? formatWithUnit(base, unit) : "—"}</dd>
        </div>
        <div className="rounded-[12px] bg-surface-muted p-3">
          <dt className="text-[11px] text-ink-secondary">Alternative</dt>
          <dd className="num mt-0.5 text-[16px] font-semibold text-ink">
            {alt !== null ? formatWithUnit(alt, unit) : "No feasible plan"}
            {altUb !== null && alt !== null && altUb !== alt ? <span className="block text-[11px] font-normal text-ink-secondary">bound ≤ {formatWithUnit(altUb, unit)}</span> : null}
          </dd>
        </div>
        <div className="rounded-[12px] bg-surface-muted p-3">
          <dt className="text-[11px] text-ink-secondary">Opportunity cost</dt>
          <dd className="num mt-0.5 text-[16px] font-semibold text-ink">
            {interval && interval[0] !== null && interval[1] !== null
              ? interval[0] === interval[1]
                ? formatDelta(interval[0], unit)
                : `${formatDelta(interval[0], unit)} to ${formatDelta(interval[1], unit)}`
              : "Not quantified"}
          </dd>
        </div>
      </dl>
      {expl.length ? (
        <ul className="mt-3 list-disc pl-5 text-[13px] text-ink-secondary">
          {expl.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      ) : null}
      {((r.child_run_ids as string[] | undefined) ?? (a.child_run_ids as string[] | undefined) ?? []).length ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[12px]">
          {((r.child_run_ids as string[] | undefined) ?? (a.child_run_ids as string[])).map((id) => (
            <button key={id} type="button" onClick={() => sel.setParams({ run: id })} className="font-mono text-water hover:underline">
              run {shortId(id)}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Synergy() {
  const s = useScenario();
  const items = s.catalog.interventions.data ?? [];
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [rule, setRule] = useState<"fixed" | "reoptimize">("fixed");
  const cur = useCurrentAnalysis("synergy");
  const runner = useAnalysisRunner("synergy");
  const res = (cur.data?.result ?? {}) as Record<string, unknown>;
  const outcomes = (res.outcomes ?? {}) as Record<string, Record<string, unknown>>;
  const unit = String(res.unit ?? "kg");
  const syn = num(res.synergy);
  const synInt = (res.synergy_interval as [number, number] | null | undefined) ?? null;
  const rows = useMemo(
    () =>
      (["none", "a", "b", "ab"] as const).map((k) => {
        const o = outcomes[k] ?? {};
        return {
          k: { none: "Neither", a: "A only", b: "B only", ab: "A + B" }[k],
          v: num(o.value) !== null ? formatWithUnit(num(o.value)!, unit) : String(o.status ?? "—").replace(/_/g, " "),
          ub: num(o.upper_bound) !== null ? formatWithUnit(num(o.upper_bound)!, unit) : "—",
          st: String(o.status ?? "—"),
        };
      }),
    [outcomes, unit],
  );
  return (
    <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1" data-testid="synergy">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink">
        <Sigma size={16} className="text-water" aria-hidden /> Synergy between two investments
      </h2>
      <p className="mt-0.5 max-w-[64ch] text-[12px] text-ink-secondary">
        Four matched solves: none, A, B, A+B. Synergy = AB − A − B + none, in the same unit. Negative synergy is valid. Infeasible or unresolved combinations are explained, not
        turned into a percentage.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Select label="Investment A" value={a} onChange={(e) => setA(e.target.value)} className="min-w-[220px] flex-1">
          <option value="">Choose…</option>
          {items.filter((i) => i.category !== "timing").map((it) => (
            <option key={it.instance_id} value={it.instance_id}>
              {it.label ?? it.instance_id}
            </option>
          ))}
        </Select>
        <Select label="Investment B" value={b} onChange={(e) => setB(e.target.value)} className="min-w-[220px] flex-1">
          <option value="">Choose…</option>
          {items.filter((i) => i.category !== "timing" && i.instance_id !== a && (!i.mutually_exclusive_group || i.mutually_exclusive_group !== items.find((x) => x.instance_id === a)?.mutually_exclusive_group)).map((it) => (
            <option key={it.instance_id} value={it.instance_id}>
              {it.label ?? it.instance_id}
            </option>
          ))}
        </Select>
        <Segmented
          label="Other investments"
          size="sm"
          value={rule}
          onChange={(v) => setRule(v as typeof rule)}
          options={[
            { value: "fixed", label: "Others fixed" },
            { value: "reoptimize", label: "Others re-optimize" },
          ]}
        />
        <Button size="sm" variant="primary" icon={<Play size={13} />} busy={runner.pending} disabled={!a || !b || !s.active} onClick={() => void runner.run({ base_revision_id: s.active?.revisionId, instance_a: a, instance_b: b, other_actions: rule })}>
          Run 4 solves
        </Button>
      </div>
      {cur.loading ? (
        <Skeleton className="mt-3 h-32" />
      ) : cur.data ? (
        <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
          <DataTable
            caption="Synergy outcomes"
            columns={[
              { key: "k", label: "Combination" },
              { key: "v", label: "Outcome", align: "right" },
              { key: "ub", label: "Bound", align: "right" },
              { key: "st", label: "Status" },
            ]}
            rows={rows}
          />
          <div className="rounded-[12px] bg-surface-muted p-4">
            <div className="text-[11px] text-ink-secondary">Synergy (AB − A − B + none)</div>
            <div className="num mt-1 text-[22px] font-semibold tracking-[-0.01em] text-ink" data-testid="synergy-value">
              {syn !== null ? formatDelta(syn, unit) : synInt ? `${formatDelta(synInt[0], unit)} … ${formatDelta(synInt[1], unit)}` : "Not computable"}
            </div>
            <div className="mt-1 text-[12px] text-ink-secondary">{String(res.note ?? (rule === "fixed" ? "Other investments held fixed in all four runs." : "Other investments re-optimized in all four runs."))}</div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
