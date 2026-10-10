/**
 * "Why this plan": the deterministic GET /runs/{id}/explanations view (PRD §7.5). Works
 * offline and without the hosted assistant. Every figure is a value from the payload;
 * opportunity costs stay "needs a new solve" exactly as the server says.
 */
import { useState, type ReactNode } from "react";
import { AlertTriangle, ChevronDown, CircleSlash, Gauge, Lightbulb, ListChecks, ListX } from "lucide-react";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { useFieldLabel } from "@/features/impact/viewKit";
import { formatPKR, formatPercent, formatVolume, titleCase } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { useRunExplanations, type RunExplanations } from "./api";
import { CitationChip } from "./blocks";

const CATEGORY_LABEL: Record<string, string> = {
  timing: "Timing with existing assets",
  leveling: "Leveling service",
  pond: "New pond",
  shared_repair: "Shared repair",
  pump_supplement: "Existing-pump supplement",
};
const REJECT_LABEL: Record<string, string> = {
  not_selected: "Eligible, not chosen",
  ineligible: "Ineligible",
  excluded_by_scenario: "Excluded by scenario",
  not_allowed: "Not allowed",
  no_new_capital: "No new capital (baseline)",
  over_budget: "Over the whole budget",
};

function groupBy<T>(xs: T[], k: (x: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const x of xs) m.set(k(x), [...(m.get(k(x)) ?? []), x]);
  return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
}

/** Questions grounded in what the explanation actually contains (prompts, never numbers). */
export function suggestedQuestions(e: RunExplanations | undefined, fieldLabel: string | null): string[] {
  const out: string[] = [];
  if (!e) return ["What does the selected run recommend, and how sure is it?", "Which assumption should we check before spending?"];
  if (e.outcome !== "plan") {
    out.push("Why is there no feasible plan, and which relaxation should we try first?");
  } else {
    out.push("Why was this plan selected over the baseline?");
    const binding = e.bottlenecks?.budgets.find((b) => b.binding);
    if (binding) out.push(`Is the ${binding.constraint.replace(/_/g, " ")} what limits this plan?`);
    else if (e.bottlenecks?.saturated_count) out.push("Which water resource limits this plan, and when?");
    const pond = e.rejected?.find((r) => r.category === "pond" && r.kind !== "ineligible");
    if (pond) out.push(`What if we build the pond ${pond.instance_id.replace(/^[^:]+:/, "").replace(/:pond$/, "")} anyway?`);
    else if (e.rejected?.some((r) => r.category === "pond" && r.kind === "ineligible")) out.push("Why can't a new pond be part of this plan?");
    else if (e.rejected?.some((r) => r.kind === "not_selected")) out.push("Why were the other eligible investments not chosen?");
  }
  if (fieldLabel) out.push(`Why does field ${fieldLabel} get this allocation?`);
  out.push("Which assumption should we check before spending?");
  return out.slice(0, 4);
}

function Disclosure({ icon, title, count, children, defaultOpen = false }: { icon: ReactNode; title: string; count?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-2 text-left text-[12.5px] font-medium text-ink hover:text-water-deep"
      >
        <span className="text-ink-tertiary" aria-hidden>
          {icon}
        </span>
        <span className="flex-1">{title}</span>
        {count !== undefined ? <span className="num text-[12px] text-ink-secondary">{count}</span> : null}
        <ChevronDown size={13} aria-hidden className={cn("text-ink-tertiary transition-transform", open && "rotate-180")} />
      </button>
      {open ? <div className="pb-2.5">{children}</div> : null}
    </div>
  );
}

export function WhyThisPlan({ runId, defaultOpen }: { runId: string | null; defaultOpen: boolean }) {
  const q = useRunExplanations(runId);
  const [open, setOpen] = useState(defaultOpen);
  const fieldLabel = useFieldLabel();
  const e = q.data;

  const body = (() => {
    if (!runId)
      return (
        <p className="text-[12.5px] text-ink-secondary">Select a run (B0, B1 or P) to see why it chose what it chose. Explanations are computed from the run itself and work offline.</p>
      );
    if (q.isLoading)
      return (
        <div className="flex flex-col gap-2" aria-busy>
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-16" />
        </div>
      );
    if (q.error || !e) return <StatePanel compact state="error" error={q.error} title="Explanations unavailable" />;
    if (e.outcome !== "plan") {
      const w = e.why_no_solution;
      return (
        <div className="flex flex-col gap-2 text-[12.5px]">
          <div className="flex items-start gap-2 rounded-[10px] border border-warning/30 bg-warning-soft/60 p-2.5">
            <CircleSlash size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden />
            <div>
              <div className="font-semibold text-ink">{w?.solver_status ? titleCase(String(w.solver_status)) : titleCase(e.outcome)}</div>
              <p className="mt-0.5 leading-relaxed text-ink-secondary">{w?.statement ?? "The server returned no explanation for this outcome."}</p>
            </div>
          </div>
          {w?.coverage_note ? <p className="text-ink-secondary">{w.coverage_note}</p> : null}
          {w?.relaxation_branches?.length ? (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Explicit branches you can solve</div>
              <ul className="flex flex-col gap-1">
                {w.relaxation_branches.map((b, i) => (
                  <li key={i} className="rounded-[8px] bg-surface-muted px-2.5 py-1.5 text-ink">
                    {b.label}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11.5px] text-ink-tertiary">{w.relaxation_note}</p>
            </div>
          ) : null}
        </div>
      );
    }
    const selected = e.selected ?? [];
    const rejected = e.rejected ?? [];
    const bn = e.bottlenecks;
    return (
      <div className="flex flex-col">
        <Disclosure icon={<ListChecks size={14} />} title="Selected investments" count={selected.length} defaultOpen>
          {selected.length ? (
            <ul className="flex flex-col gap-1.5">
              {groupBy(selected, (s) => s.category).map(([cat, xs]) => (
                <li key={cat} className="rounded-[10px] bg-surface-muted/60 px-2.5 py-2">
                  <div className="flex items-center justify-between gap-2 text-[12.5px]">
                    <span className="font-medium text-ink">{CATEGORY_LABEL[cat] ?? titleCase(cat)}</span>
                    <span className="num text-ink-secondary">{xs.length}</span>
                  </div>
                  <p className="mt-0.5 text-[11.5px] leading-snug text-ink-secondary">{xs[0].why[0]}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {[...new Set(xs.flatMap((x) => x.evidence_ids))].slice(0, 3).map((id) => (
                      <CitationChip key={id} c={{ ref_id: id, kind: "evidence" }} />
                    ))}
                  </div>
                  {xs.length <= 3 ? (
                    <ul className="mt-1 text-[11.5px] text-ink-tertiary">
                      {xs.map((x) => (
                        <li key={x.instance_id} className="num">
                          {x.affected_field_ids.length === 1 ? fieldLabel(x.affected_field_ids[0]) : x.instance_id.replace(/^[^:]+:/, "")} · {formatPKR(x.capex_pkr)}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-ink-secondary">This plan selects no new investment.</p>
          )}
          <p className="mt-1.5 text-[11.5px] text-ink-tertiary">Marginal value of each selection needs a new solve (Explore → Why-not, exclude).</p>
        </Disclosure>

        {bn ? (
          <Disclosure icon={<Gauge size={14} />} title="What binds" count={bn.budgets.filter((b) => b.binding).length + bn.saturated_count || "none"}>
            <ul className="flex flex-col gap-2">
              {bn.budgets.map((b) => (
                <li key={b.constraint} className="text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-ink">{titleCase(b.constraint.replace(/_/g, " "))}</span>
                    {b.binding ? (
                      <Chip size="sm" tone="warning" icon={<AlertTriangle size={11} aria-hidden />}>
                        Binding
                      </Chip>
                    ) : (
                      <span className="text-[11px] text-ink-tertiary">Slack</span>
                    )}
                  </div>
                  <div className="num mt-0.5 text-ink-secondary">
                    {b.used_pkr === null ? "Use not reported" : formatPKR(b.used_pkr)} of {formatPKR(b.limit_pkr)}
                    {b.utilization !== null ? ` · ${formatPercent(b.utilization, 1)}` : ""}
                  </div>
                  {b.utilization !== null ? (
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                      <div className={cn("h-full rounded-full", b.binding ? "bg-warning" : "bg-water")} style={{ width: `${Math.min(100, Math.max(1, b.utilization * 100))}%` }} />
                    </div>
                  ) : null}
                </li>
              ))}
              <li className="text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-ink">Saturated water resources</span>
                  <span className="num text-ink-secondary">{bn.saturated_count}</span>
                </div>
                {bn.saturated_resources.slice(0, 3).map((r, i) => (
                  <div key={i} className="num mt-0.5 flex justify-between gap-2 text-[11.5px] text-ink-tertiary">
                    <span className="truncate" title={`${r.resource_id} · ${r.interval_id}`}>
                      {r.resource_id.replace(/^[^:]+:[^:]+:/, "").replace(/^pump:/, "pump ")} · {r.interval_id.replace(/^d/, "")}
                    </span>
                    <span className="shrink-0">
                      {formatVolume(r.used_m3)} / {formatVolume(r.capacity_m3)}
                    </span>
                  </div>
                ))}
              </li>
            </ul>
            <p className="mt-1.5 text-[11.5px] leading-snug text-ink-tertiary">{bn.note}</p>
          </Disclosure>
        ) : null}

        <Disclosure icon={<ListX size={14} />} title="Not selected" count={rejected.length}>
          <ul className="flex flex-col gap-1">
            {groupBy(rejected, (r) => r.kind).map(([kind, xs]) => (
              <li key={kind} className="rounded-[10px] bg-surface-muted/60 px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-2 text-[12.5px]">
                  <span className="font-medium text-ink">{REJECT_LABEL[kind] ?? titleCase(kind)}</span>
                  <span className="num text-ink-secondary">{xs.length}</span>
                </div>
                <p className="mt-0.5 text-[11.5px] leading-snug text-ink-secondary">{xs[0].why[0]}</p>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11.5px] text-ink-tertiary">Opportunity cost of forcing one in needs a new solve (Explore → Why-not, force).</p>
        </Disclosure>
      </div>
    );
  })();

  return (
    <section className="rounded-[14px] border border-border bg-surface shadow-1" data-testid="why-this-plan" aria-labelledby="why-plan-h">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-3 py-2.5 text-left">
        <Lightbulb size={15} className="text-water" aria-hidden />
        <span id="why-plan-h" className="flex-1 text-[13px] font-semibold text-ink">
          Why this plan
        </span>
        {e ? (
          <Chip size="sm" tone="info" title={`Proof scope: ${e.proof_scope.replace(/_/g, " ")}`}>
            {e.plan_kind} · deterministic
          </Chip>
        ) : (
          <Chip size="sm" tone="info">
            Deterministic
          </Chip>
        )}
        <ChevronDown size={14} aria-hidden className={cn("text-ink-tertiary transition-transform", open && "rotate-180")} />
      </button>
      {open ? <div className="border-t border-border px-3 pb-2 pt-1">{body}</div> : null}
    </section>
  );
}
