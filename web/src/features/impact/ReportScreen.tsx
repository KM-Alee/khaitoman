import { useEffect, useMemo, useState } from "react";
import { Download, FileText, Printer } from "lucide-react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { api, describeError } from "@/lib/api/client";
import { useCreateReport, useRun } from "@/lib/api/queries";
import { useQuery } from "@tanstack/react-query";
import type { PlanKind } from "@/lib/api/types";
import { formatDate, formatDateTime, formatPKR, shortId, titleCase } from "@/lib/formatting";
import { Chip, MetricValueView, SolverBadge, Skeleton, StatePanel, JobBadge, ReviewFlagChips } from "@/components/status";
import { Button, buttonClass } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { useScenario, PLAN_LABEL } from "@/features/workspace/useScenario";
import { CATEGORY_META } from "@/features/workspace/ScenarioPanel";
import { HEADLINE, headlineMetrics } from "@/features/workspace/ResultStrip";
import { useLadderRuns } from "@/features/compare/CompareScreen";
import { ImpactNav } from "./ImpactScreen";
import { toast } from "@/components/ui/Toast";

type Decision = "proposed" | "reviewed" | "accepted" | "rejected";
/** Local user's decision per action and run — not an authorization or work order (PRD §8.1). */
const useDecisions = create<{ d: Record<string, Decision>; set: (k: string, v: Decision) => void }>()(
  persist((set) => ({ d: {}, set: (k, v) => set((s) => ({ d: { ...s.d, [k]: v } })) }), { name: "aabflow-decisions" }),
);

export function ReportScreen() {
  const { sel, pilot } = usePilotData();
  const run = useRun(sel.runId);
  const s = useScenario();
  const ladder = useLadderRuns();
  const catalog = s.catalog.interventions.data ?? [];
  const decisions = useDecisions();
  const [reportId, setReportId] = useState<string | null>(null);
  const create = useCreateReport();
  const trackJob = useUI((st) => st.trackJob);
  const jobs = useUI((st) => st.jobs);
  const report = useQuery({
    queryKey: ["report", reportId ?? ""],
    enabled: !!reportId,
    queryFn: () => api.get<Record<string, unknown>>(`/reports/${encodeURIComponent(reportId!)}`),
    refetchInterval: (q) => (["succeeded", "completed", "ready", "failed"].includes(String(q.state.data?.status ?? "")) ? false : 1500),
  });
  const job = jobs.find((j) => j.operation === "report" && j.resultRef === reportId) ?? jobs.find((j) => j.operation === "report" && !j.dismissed && j.pilotKey === sel.pilotKey);

  useEffect(() => {
    document.title = run.data ? `AabFlow action plan · ${sel.pilotId} · ${shortId(run.data.run_id)}` : "AabFlow";
    return () => {
      document.title = "AabFlow";
    };
  }, [run.data, sel.pilotId]);

  const r = run.data;
  const actions = useMemo(() => (r?.outcome === "plan" ? r.selected_intervention_instance_ids.map((id) => ({ id, it: catalog.find((c) => c.instance_id === id) })) : []), [r, catalog]);
  const ladderKinds = (["B0", "B1", "P", "R"] as PlanKind[]).filter((k) => ladder.byKind.has(k));

  const exportReport = async () => {
    if (!r) return;
    try {
      const res = await create.mutateAsync({ run_ids: ladder.ids.length ? ladder.ids : [r.run_id], report_type: "action_plan" });
      const rid = String(res.report_id ?? "");
      if (rid) setReportId(rid);
      if (res.job_id) trackJob({ jobId: String(res.job_id), label: "Decision package export", operation: "report", revisionId: null, pilotKey: sel.pilotKey });
    } catch (e) {
      const d = describeError(e);
      toast({ tone: "danger", title: `Export failed: ${d.title}`, description: d.detail });
    }
  };
  const downloads = ((report.data?.downloads as { kind: string; url: string; label?: string }[] | undefined) ?? []).filter((d) => d.url);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="report">
      <ImpactNav />
      <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
        {!sel.runId ? (
          <div className="mx-auto max-w-[560px] p-6 pt-10">
            <StatePanel state="empty" title="No run to report" action={{ label: "Go to Workspace", onClick: () => sel.go("workspace") }}>
              The action plan is generated from a completed, validated run.
            </StatePanel>
          </div>
        ) : run.isLoading ? (
          <div className="mx-auto max-w-[920px] space-y-3 p-6">
            <Skeleton className="h-24" />
            <Skeleton className="h-64" />
          </div>
        ) : !r ? (
          <div className="p-6">
            <StatePanel state="error" error={run.error} title="Run unavailable" />
          </div>
        ) : (
          <article className="mx-auto my-4 max-w-[920px] rounded-[16px] border border-border bg-surface px-6 py-6 shadow-1 print:my-0 print:max-w-none print:rounded-none print:border-0 print:shadow-none md:px-10 md:py-9">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border pb-5">
              <div>
                <Eyebrow>Decision package · action plan</Eyebrow>
                <h1 className="mt-1 font-display text-[30px] font-[560] leading-tight tracking-[-0.015em] text-ink">{pilot.data?.pilot?.name ?? sel.pilotId}</h1>
                <p className="num mt-1 text-[13px] text-ink-secondary">
                  {sel.pilotId} · {sel.version} · {s.draft ? titleCase(s.draft.season_id) : ""} · run <span className="font-mono">{r.run_id}</span> · generated {formatDateTime(new Date())}
                </p>
                <ReviewFlagChips flags={pilot.data?.pilot?.review_flags} className="mt-3" />
              </div>
              <div className="no-print flex flex-wrap gap-2">
                <Button variant="secondary" icon={<Printer size={15} />} onClick={() => window.print()}>
                  Print / PDF
                </Button>
                <Button variant="primary" icon={<FileText size={15} />} busy={create.isPending} onClick={() => void exportReport()} data-testid="export-report">
                  Export versioned package
                </Button>
              </div>
            </header>

            {reportId || job ? (
              <section className="no-print mt-4 rounded-[12px] border border-border bg-surface-muted/60 p-3" data-testid="report-status">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="font-medium text-ink">Report {shortId(reportId)}</span>
                  {job ? <JobBadge state={job.state} /> : null}
                  {report.data?.status ? <Chip size="sm">{String(report.data.status)}</Chip> : null}
                </div>
                {downloads.length ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {downloads.map((d) => (
                      <a key={d.url} href={d.url} className={buttonClass("secondary", "sm")} download>
                        <Download size={13} aria-hidden /> {d.label ?? d.kind.toUpperCase()}
                      </a>
                    ))}
                  </div>
                ) : report.error ? (
                  <p className="mt-1 text-[12px] text-danger">{describeError(report.error).detail}</p>
                ) : null}
              </section>
            ) : null}

            <section className="mt-6" aria-labelledby="sum-h">
              <h2 id="sum-h" className="text-[15px] font-semibold text-ink">
                Result
              </h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Chip tone="ink">{r.plan_kind} · {PLAN_LABEL[r.plan_kind]}</Chip>
                <SolverBadge status={r.solver_status} showFriendly />
              </div>
              {r.outcome === "plan" ? (
                <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                  {headlineMetrics(r)
                    .filter((h) => h.metric)
                    .map((h) => (
                      <div key={h.key}>
                        <dt className="text-[12px] text-ink-secondary">{h.label}</dt>
                        <dd>
                          <MetricValueView metric={h.metric} size="md" />
                        </dd>
                      </div>
                    ))}
                </dl>
              ) : (
                <p className="mt-2 text-[13px] text-ink-secondary">This run has no plan; the report records the diagnostic outcome only.</p>
              )}
            </section>

            {ladderKinds.length > 1 ? (
              <section className="mt-7" aria-labelledby="inc-h">
                <h2 id="inc-h" className="text-[15px] font-semibold text-ink">
                  Incremental view
                </h2>
                <p className="text-[12px] text-ink-secondary">B0→B1 operational gain · B1→P investment gain · P→R risk trade-off. Where greater output also uses more pumping or expenditure, both are shown.</p>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[560px] text-[13px]">
                    <thead>
                      <tr className="border-b border-border text-left text-[12px] text-ink-tertiary">
                        <th className="py-1.5 font-medium">Metric</th>
                        {ladderKinds.map((k) => (
                          <th key={k} className="py-1.5 text-right font-medium">
                            {k}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {HEADLINE.map((h, i) => {
                        const cells = ladderKinds.map((k) => headlineMetrics(ladder.byKind.get(k))[i].metric);
                        if (!cells.some(Boolean)) return null;
                        return (
                          <tr key={h.key} className="border-b border-border/70">
                            <th scope="row" className="py-1.5 text-left font-normal text-ink-secondary">
                              {h.label}
                            </th>
                            {cells.map((m, j) => (
                              <td key={j} className="py-1.5 text-right">
                                <MetricValueView metric={m} size="sm" showReason={false} />
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            <section className="mt-7" aria-labelledby="act-h">
              <h2 id="act-h" className="text-[15px] font-semibold text-ink">
                Actions ({actions.length})
              </h2>
              {!actions.length ? (
                <p className="mt-1 text-[13px] text-ink-secondary">No new investment selected; the plan schedules existing assets only.</p>
              ) : (
                <ol className="mt-3 flex flex-col gap-3">
                  {actions.map(({ id, it }, n) => {
                    const key = `${r.run_id}|${id}`;
                    const dec = decisions.d[key] ?? "proposed";
                    return (
                      <li key={id} className="break-inside-avoid rounded-[12px] border border-border p-4" data-testid="action-card">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-1.5 text-[12px] text-ink-secondary">
                              <span className="num font-semibold text-ink">{n + 1}.</span>
                              {it ? CATEGORY_META[it.category]?.icon : null}
                              {it ? CATEGORY_META[it.category]?.label : "Intervention"}
                              {it?.shared ? <Chip size="sm" tone="water">Shared project · charged once</Chip> : null}
                            </div>
                            <h3 className="mt-0.5 text-[14px] font-semibold text-ink">{it?.label ?? id}</h3>
                            <div className="font-mono text-[11px] text-ink-tertiary">{id}</div>
                          </div>
                          <div className="no-print">
                            <Segmented
                              label={`Decision for ${id}`}
                              size="sm"
                              value={dec}
                              onChange={(v) => decisions.set(key, v as Decision)}
                              options={(["proposed", "reviewed", "accepted", "rejected"] as Decision[]).map((x) => ({ value: x, label: titleCase(x) }))}
                            />
                          </div>
                          <Chip size="sm" className="hidden print:inline-flex">{titleCase(dec)}</Chip>
                        </div>
                        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12px] sm:grid-cols-3">
                          <Fact k="Targets" v={(it?.target_ids ?? []).join(", ") || "—"} />
                          <Fact k="Capital" v={it ? formatPKR(it.capex_pkr) : "—"} />
                          <Fact k="Seasonal operating" v={it ? formatPKR(it.seasonal_opex_pkr) : "—"} />
                          <Fact k="Decision" v={s.draft ? formatDate(s.draft.decision_at.slice(0, 10)) : "—"} />
                          <Fact k="Commissioning" v={it?.earliest_commissioning ? formatDate(it.earliest_commissioning) : it ? `${it.procurement_delay_days + it.lead_time_days} days after decision` : "—"} />
                          <Fact k="Prerequisites" v={(it?.prerequisites ?? []).join(", ") || "None"} />
                          <Fact k="Payer / financing" v={param(it?.parameters, "payer", "financing") ?? "Not recorded in the package"} />
                          <Fact k="Responsible role" v={param(it?.parameters, "responsible_role", "responsible") ?? "Not recorded"} />
                          <Fact k="Required approval" v={param(it?.parameters, "required_approval", "approval") ?? "Not recorded"} />
                        </dl>
                        {it?.category === "pond" ? <p className="mt-2 text-[12px] text-ink-secondary">The pond footprint is removed from the field's cropped area in every metric.</p> : null}
                      </li>
                    );
                  })}
                </ol>
              )}
              <p className="mt-3 text-[11px] text-ink-tertiary">
                “Accepted” records this software user's decision only. It is not a government authorization, a work order, or an instruction to operate a canal.
              </p>
            </section>

            <section className="mt-7 border-t border-border pt-5 text-[12px] text-ink-secondary" aria-labelledby="prov-h">
              <h2 id="prov-h" className="text-[13px] font-semibold text-ink">
                Provenance
              </h2>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt>Run</dt>
                <dd className="font-mono">{r.run_id}</dd>
                <dt>Revision</dt>
                <dd className="font-mono">{r.scenario_revision_id}</dd>
                <dt>Scenario hash</dt>
                <dd className="truncate font-mono">{r.scenario_hash}</dd>
                <dt>Candidate library</dt>
                <dd className="truncate font-mono">{r.candidate_library_hash}</dd>
                <dt>Proof scope</dt>
                <dd>Finite candidate library — not a proof of the best possible real-world practice.</dd>
                {r.outcome === "plan" ? (
                  <>
                    <dt>Physical validation</dt>
                    <dd>{r.physical_validation.status}</dd>
                  </>
                ) : null}
                <dt>Created</dt>
                <dd>{formatDateTime(r.created_at)}</dd>
              </dl>
              {r.warnings.length ? (
                <ul className="mt-2 list-disc pl-5">
                  {r.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          </article>
        )}
      </div>
    </div>
  );
}

function param(p: Record<string, unknown> | undefined, ...keys: string[]): string | null {
  for (const k of keys) if (p && typeof p[k] === "string") return p[k] as string;
  return null;
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-ink-tertiary">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  );
}
