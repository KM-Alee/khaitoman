/**
 * The Plan screen's answer: what the recommended plan achieves, what it costs, who is
 * protected and what it actually does, in plain words, with every number from the server
 * (run metrics + the comparison service's deltas). States: none, solving, loading, error,
 * no plan (infeasible / unknown / invalid), inputs changed, saved result, current.
 */
import { useMemo, useState } from "react";
import { ArrowRight, ChevronDown, History, PlayCircle, RotateCcw, Sparkles, TriangleAlert } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useUI } from "@/app/store";
import { useComparison } from "@/lib/api/queries";
import type { ActionCategory, PlanKind, RunResult } from "@/lib/api/types";
import { formatDateTime, formatPKRCompact, shortId, titleCase } from "@/lib/formatting";
import { planName } from "@/lib/glossary";
import { Chip, Progress, Provenance, Skeleton, SOLVER_COPY, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { MetricTile } from "@/components/ui/MetricTile";
import { Explain, Term } from "@/components/ui/Term";
import { SpotArt } from "@/components/ui/Art";
import { useLadderRuns } from "@/features/compare/useLadder";
import { cn } from "@/lib/cn";
import { comparisonDeltas, deltaFor, headlineMetrics } from "./ResultStrip";
import { useRunContext } from "./useRunContext";
import { useScenario } from "./useScenario";
import { CATEGORY_META } from "./categories";

export function ResultPanel({ className }: { className?: string }) {
  const sel = useSelection();
  const s = useScenario();
  const ctx = useRunContext(sel.runId);
  const { byKind } = useLadderRuns();
  const r = ctx.run.data ?? null;
  const base = byKind.get("B0") ?? byKind.get("B1") ?? null;
  const baseKind: PlanKind | null = base && r && base.run_id !== r.run_id ? base.plan_kind : null;
  const cmp = useComparison(base && r && base.run_id !== r.run_id ? [base.run_id, r.run_id] : []);
  const deltas = useMemo(() => comparisonDeltas(cmp.data, base?.run_id ?? null), [cmp.data, base?.run_id]);
  const rows = useMemo(() => headlineMetrics(r), [r]);
  const row = (k: string) => rows.find((x) => x.key === k)!;

  if (s.phase === "running" && (!sel.runId || !r || r.scenario_revision_id !== s.active?.revisionId)) return <Solving className={className} />;
  if (!sel.runId) return <NoPlanYet className={className} />;
  if (ctx.run.isLoading) return <div className={cn("flex flex-col gap-3 p-5", className)} aria-busy data-testid="result-panel" data-state="busy"><Skeleton className="h-6 w-40" /><Skeleton className="h-16 w-56" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>;
  if (ctx.run.error || !r)
    return (
      <div className={cn("p-4", className)} data-testid="result-panel" data-state="error">
        <StatePanel state="error" error={ctx.run.error} title={`Saved calculation ${shortId(sel.runId)} could not be loaded`} action={{ label: "Clear and start over", onClick: () => sel.setParams({ run: null, runs: null }) }} />
      </div>
    );

  const dirty = s.phase === "dirty" && !ctx.saved;
  const crop = s.catalog.seasons.data?.find((x) => x.season_id === ctx.request?.season_id)?.crop ?? null;
  const vsBase = baseKind ? `vs ${planName(baseKind).toLowerCase()}` : undefined;
  const delta = (k: string, withAgainst = false) => {
    const d = deltaFor(deltas, row(k).ids);
    return d ? { ...d, goodWhen: row(k).goodWhen, against: withAgainst ? vsBase : undefined } : null;
  };

  return (
    <div className={cn("flex flex-col gap-5 p-5", className)} data-testid="result-panel" data-state={r.outcome === "plan" ? (dirty ? "stale" : ctx.saved ? "saved" : "ready") : r.solver_status === "INFEASIBLE" ? "infeasible" : "unknown"} data-tour="result">
      {dirty ? <ChangedBanner onRun={() => void s.run()} onReset={s.reset} busy={s.busy} /> : null}
      {ctx.saved ? <SavedBanner run={r} request={ctx.request} onAdopt={() => ctx.request && s.adopt(ctx.request)} /> : null}

      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: `var(--plan-${r.plan_kind.toLowerCase()})` }} aria-hidden />
          <span className="text-[13px] font-semibold text-ink">
            <Term id={r.plan_kind}>{planName(r.plan_kind)}</Term>
          </span>
          <Chip size="sm" tone={SOLVER_COPY[r.solver_status].tone} title={SOLVER_COPY[r.solver_status].friendly}>
            {SOLVER_COPY[r.solver_status].plain}
          </Chip>
        </div>
      </div>

      {r.outcome !== "plan" ? (
        <NoPlanAnswer run={r} />
      ) : (
        <>
          <MetricTile size="hero" label={crop ? `${titleCase(crop)} harvested` : "Crop harvested"} term="production" metric={row("production").metric} delta={delta("production", true)} testId="hero-production" />
          <div className="grid grid-cols-2 gap-x-4 gap-y-5 rounded-[16px] border border-border bg-surface-muted/50 p-4" data-testid="result-strip">
            <MetricTile size="sm" label="Money for new works" term="capex" metric={row("capex").metric} hint={ctx.request ? `budget ${formatPKRCompact(ctx.request.capital_budget_pkr)}` : undefined} />
            <MetricTile size="sm" label="Running cost" term="opex" metric={row("opex").metric} hint={ctx.request ? `budget ${formatPKRCompact(ctx.request.operating_budget_pkr)}` : undefined} />
            <MetricTile size="sm" label="Tail-end fair share" term="tailService" metric={row("tail").metric} delta={delta("tail")} />
            <MetricTile size="sm" label="Groundwater pumped" term="groundwater" metric={row("groundwater").metric} delta={delta("groundwater")} />
          </div>
          <WorseOff run={r} />
          <PlanActions run={r} byId={ctx.byId} loading={ctx.interventions.isLoading} />
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<ArrowRight size={15} />} onClick={() => sel.go("compare")} data-testid="result-compare">
              How much better than today?
            </Button>
            <Button variant="secondary" icon={<PlayCircle size={15} />} onClick={() => sel.go("replay")}>
              Replay the season
            </Button>
          </div>
        </>
      )}
      <Provenance run={r} saved={ctx.saved} revisionId={r.scenario_revision_id} className="border-t border-border pt-3" />
    </div>
  );
}

function ChangedBanner({ onRun, onReset, busy }: { onRun: () => void; onReset: () => void; busy: boolean }) {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-[14px] border border-warning/35 bg-warning-soft px-3.5 py-3 text-[13px] text-warning" data-testid="result-bar" data-state="draft">
      <div className="flex items-start gap-2">
        <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
        <p>
          <strong className="font-semibold">You changed the settings.</strong> The numbers below are from before; run again to see the new answer.
        </p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={onRun} busy={busy}>
          Run again
        </Button>
        <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={onReset}>
          Undo changes
        </Button>
      </div>
    </div>
  );
}

function SavedBanner({ run, request, onAdopt }: { run: RunResult; request: ReturnType<typeof useRunContext>["request"]; onAdopt: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-wheat/35 bg-wheat-soft/70 px-3.5 py-3 text-[13px] text-wheat-ink" data-testid="result-bar" data-state="saved">
      <div className="flex items-start gap-2">
        <History size={16} className="mt-0.5 shrink-0" aria-hidden />
        <p>
          <strong className="font-semibold">Saved result</strong>, computed {formatDateTime(run.created_at)}
          {request ? (
            <>
              {" "}
              with {formatPKRCompact(request.capital_budget_pkr)} for new works and {formatPKRCompact(request.operating_budget_pkr)} running budget.
            </>
          ) : (
            "."
          )}{" "}
          Your own settings are unchanged.
        </p>
      </div>
      {request ? (
        <Button size="sm" variant="secondary" className="self-start" onClick={onAdopt} data-testid="adopt-settings">
          Use these settings
        </Button>
      ) : null}
    </div>
  );
}

function NoPlanAnswer({ run }: { run: RunResult }) {
  const diag = run.outcome === "no_plan" ? run : null;
  const infeasible = run.solver_status === "INFEASIBLE";
  return (
    <div className="flex flex-col gap-3" data-testid="no-plan">
      <div className="flex items-start gap-3">
        <SpotArt kind={infeasible ? "infeasible" : run.outcome === "invalid_plan" ? "error" : "search"} />
        <div>
          <h3 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">
            {run.outcome === "invalid_plan" ? "This result failed its water check" : infeasible ? "No plan can meet every rule you set" : "No plan found yet"}
          </h3>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
            {run.outcome === "invalid_plan"
              ? "The solver's best answer did not balance when every litre was re-traced day by day, so no recommendation is shown."
              : infeasible
                ? "Usually a protection level is set higher than the water can reach, or the budgets are too tight. Lower the protection level or raise a budget, then run again."
                : "The search ended without finding a valid plan or proving there is none. Try again with a longer time or looser settings."}
          </p>
        </div>
      </div>
      <Explain label="Show the technical detail">
        <p>{SOLVER_COPY[run.solver_status].friendly}</p>
        {diag?.infeasibility_kind ? <p className="mt-1">Kind: {titleCase(diag.infeasibility_kind)}.</p> : null}
        {diag && Object.keys(diag.diagnostics ?? {}).length ? (
          <ul className="mt-1.5 grid gap-1 text-[12px]">
            {Object.entries(diag.diagnostics)
              .slice(0, 6)
              .map(([k, v]) => (
                <li key={k}>
                  <span className="font-medium text-ink">{titleCase(k)}:</span> {typeof v === "object" ? JSON.stringify(v).slice(0, 140) : String(v)}
                </li>
              ))}
          </ul>
        ) : null}
      </Explain>
    </div>
  );
}

function WorseOff({ run }: { run: RunResult }) {
  const m = headlineMetrics(run).find((h) => h.key === "worse")?.metric;
  if (!m || m.status !== "available" || typeof m.value !== "number") return null;
  const n = m.value;
  return (
    <p className={cn("flex items-start gap-2 rounded-[12px] px-3 py-2.5 text-[13px]", n > 0 ? "bg-danger-soft text-danger" : "bg-vegetation-soft text-vegetation")} data-testid="worse-off">
      <span className="num text-[15px] font-bold leading-5">{n}</span>
      <span>
        <Term id="worse">{n === 1 ? "field is worse off" : "fields are worse off"}</Term> than under today's routine.
        {n > 0 ? " Compare shows which ones and by how much." : " Every field does at least as well."}
      </span>
    </p>
  );
}

function PlanActions({ run, byId, loading }: { run: RunResult; byId: ReturnType<typeof useRunContext>["byId"]; loading: boolean }) {
  const [open, setOpen] = useState(false);
  const sel = useSelection();
  const set = useUI((s) => s.set);
  const ids = run.outcome === "plan" ? run.selected_intervention_instance_ids : [];
  const groups = useMemo(() => {
    const m = new Map<ActionCategory | "other", string[]>();
    for (const id of ids) {
      const c = byId.get(id)?.category ?? "other";
      m.set(c, [...(m.get(c) ?? []), id]);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [ids, byId]);
  return (
    <section aria-labelledby="plan-actions-h" data-testid="plan-actions">
      <h3 id="plan-actions-h" className="eyebrow mb-2">
        What the plan does
      </h3>
      {!ids.length ? (
        <p className="text-[13px] leading-relaxed text-ink-secondary">No new works: the gain comes from timing water better with the ponds and pumps that already exist. That is a valid answer under these budgets.</p>
      ) : loading ? (
        <Skeleton className="h-16" />
      ) : (
        <>
          <ul className="flex flex-wrap gap-1.5">
            {groups.map(([c, list]) => (
              <li key={c}>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[12.5px] text-ink">
                  <span className="text-water-deep">{c === "other" ? <Sparkles size={13} aria-hidden /> : CATEGORY_META[c].icon}</span>
                  <span className="num font-semibold">{list.length}</span> {c === "other" ? "other actions" : CATEGORY_META[c].plural}
                </span>
              </li>
            ))}
          </ul>
          <button type="button" className="mt-2 inline-flex items-center gap-1 text-[12.5px] font-medium text-water-deep hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Hide" : "List"} all {ids.length} actions <ChevronDown size={13} className={cn("transition-transform", open && "rotate-180")} aria-hidden />
          </button>
          {open ? (
            <ul className="mt-2 flex max-h-[260px] flex-col gap-1 overflow-y-auto pr-1" data-testid="actions-inspector">
              {ids.map((id) => {
                const it = byId.get(id);
                const target = it?.target_ids?.find((t) => t.includes(":field-"));
                return (
                  <li key={id} className="flex items-center justify-between gap-2 rounded-[10px] px-2 py-1.5 text-[12.5px] hover:bg-surface-muted">
                    <button
                      type="button"
                      className="min-w-0 truncate text-left text-ink hover:text-water-deep"
                      title={id}
                      onClick={() => {
                        if (target) {
                          sel.setParams({ field: target }, false);
                          set({ inspectorTab: "field" });
                        }
                      }}
                    >
                      {it?.label ?? id.split(":").slice(1).join(" · ")}
                    </button>
                    {it ? <span className="num shrink-0 text-ink-tertiary">{it.capex_pkr ? formatPKRCompact(it.capex_pkr) : "no capex"}</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}

function NoPlanYet({ className }: { className?: string }) {
  const s = useScenario();
  return (
    <div className={cn("flex flex-col gap-4 p-5", className)} data-testid="result-panel" data-state="empty">
      <SpotArt kind="plan" className="h-16 w-16" />
      <div>
        <h3 className="display text-[22px] leading-tight text-ink">No plan yet</h3>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-secondary">
          Pick the season, how short water is and how much money there is, then <strong className="font-semibold text-ink">Find the best plan</strong>. AabFlow solves three plans under identical conditions:
        </p>
      </div>
      <ol className="flex flex-col gap-2 text-[13px]">
        {(["B0", "B1", "P"] as const).map((k, i) => (
          <li key={k} className="flex items-start gap-2.5">
            <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold text-on-water" style={{ background: `var(--plan-${k.toLowerCase()})` }} aria-hidden>
              {i + 1}
            </span>
            <span>
              <Term id={k} className="font-semibold text-ink">
                {planName(k)}
              </Term>
              <span className="block text-ink-secondary">{k === "B0" ? "how water is used today" : k === "B1" ? "same assets, smarter timing" : "with new works, within your budgets"}</span>
            </span>
          </li>
        ))}
      </ol>
      <Button variant="hero" size="lg" icon={<Sparkles size={16} />} onClick={() => void s.run()} busy={s.busy} disabled={!s.draft || !s.draft.weather_scenario_ids.length} data-testid="result-run">
        Find the best plan
      </Button>
    </div>
  );
}

function Solving({ className }: { className?: string }) {
  const s = useScenario();
  return (
    <div className={cn("flex flex-col gap-4 p-5", className)} data-testid="result-panel" data-state="busy" role="status" aria-live="polite">
      <SpotArt kind="busy" className="h-16 w-16" />
      <div>
        <h3 className="display text-[22px] leading-tight text-ink">Finding the best plan…</h3>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-secondary">Each plan is solved and then every litre is re-traced day by day before it is shown. This usually takes a few seconds.</p>
      </div>
      <ul className="flex flex-col gap-3">
        {s.activeJobs.map((j) => (
          <li key={j.jobId}>
            <div className="mb-1 flex items-center justify-between text-[12.5px]">
              <span className="font-medium text-ink">{j.planKind ? planName(j.planKind) : j.label}</span>
              <span className="text-ink-tertiary">{j.stage ?? j.state}</span>
            </div>
            <Progress value={j.progress} label={`${j.label} progress`} />
          </li>
        ))}
      </ul>
    </div>
  );
}
