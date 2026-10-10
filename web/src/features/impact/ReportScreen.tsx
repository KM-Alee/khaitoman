import { useEffect, useState } from "react";
import { Download, FileJson, FileText, Printer } from "lucide-react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { api, describeError } from "@/lib/api/client";
import { backendUrl } from "@/lib/api/urls";
import { useCreateReport, useRun, useRunActionPlan } from "@/lib/api/queries";
import { useQuery } from "@tanstack/react-query";
import type { PlanKind, RunResult } from "@/lib/api/types";
import { formatDate, formatDateTime, formatMass, formatNumber, formatPKR, formatPercent, shortId, titleCase } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { useFieldLabel } from "./viewKit";
import { Chip, MetricValueView, SolverBadge, Skeleton, StatePanel, JobBadge, ReviewFlagChips } from "@/components/status";
import { Button, buttonClass } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { useScenario, PLAN_LABEL } from "@/features/workspace/useScenario";
import { CATEGORY_META } from "@/features/workspace/ScenarioPanel";
import { HEADLINE, headlineMetrics } from "@/features/workspace/ResultStrip";
import { useLadderRuns } from "@/features/compare/useLadder";
import { ImpactNav } from "./ImpactScreen";
import { useRunContext } from "@/features/workspace/useRunContext";
import { useSelection } from "@/app/selection";
import { toast } from "@/components/ui/Toast";

type Decision = "proposed" | "reviewed" | "accepted" | "rejected";
/** Local user's decision per action and run — not an authorization or work order (PRD §8.1). */
const useDecisions = create<{ d: Record<string, Decision>; set: (k: string, v: Decision) => void }>()(
  persist((set) => ({ d: {}, set: (k, v) => set((s) => ({ d: { ...s.d, [k]: v } })) }), { name: "aabflow-decisions" }),
);

export function ReportScreen() {
  const rc = useRunContext(useSelection().runId);
  const { sel, pilot } = usePilotData();
  const run = useRun(sel.runId);
  const s = useScenario();
  const ladder = useLadderRuns();
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
    <div className="flex min-h-0 flex-1 flex-col print:block" data-testid="report">
      <ImpactNav />
      <div className="min-h-0 flex-1 overflow-y-auto bg-canvas print:overflow-visible print:bg-white">
        {!sel.runId ? (
          <div className="mx-auto max-w-[560px] p-6 pt-10">
            <StatePanel state="empty" art="plan" title="No plan to report yet" action={{ label: "Find the best plan first", onClick: () => sel.go("workspace") }}>
              The action plan for the committee is generated from a completed, validated plan: what to do, when, what it costs and who it affects.
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
          <article data-tour="report" className="mx-auto my-6 max-w-[960px] rounded-[22px] border border-border bg-surface px-6 py-6 shadow-2 print:my-0 print:max-w-none print:rounded-none print:border-0 print:shadow-none md:px-10 md:py-9">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border pb-5">
              <div>
                <Eyebrow>Decision package · action plan</Eyebrow>
                <h1 className="mt-1 font-display text-[30px] font-[560] leading-tight tracking-[-0.015em] text-ink">{pilot.data?.pilot?.name ?? sel.pilotId}</h1>
                <p className="num mt-1 text-[13px] text-ink-secondary">
                  {sel.pilotId} · {sel.version} · {(() => { const id = rc.request?.season_id ?? s.draft?.season_id ?? ""; return s.catalog.seasons.data?.find((x) => x.season_id === id)?.label ?? titleCase(id); })()} · run <span className="font-mono">{r.run_id}</span> · generated {formatDateTime(new Date())}
                </p>
                <ReviewFlagChips flags={pilot.data?.pilot?.review_flags} className="mt-3" />
              </div>
              <div className="no-print flex flex-wrap gap-2">
                <DataDownloads runId={r.run_id} run={r} />
                <Button variant="secondary" icon={<Printer size={15} />} onClick={() => printBrief()} data-testid="print-brief">
                  Print one-page brief
                </Button>
                <Button variant="ghost" icon={<Printer size={15} />} onClick={() => window.print()}>
                  Print full plan
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
                      <a key={d.url} href={backendUrl(d.url)} className={buttonClass("secondary", "sm")} download>
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

            <ActionsSection runId={r.run_id} />

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

/* ---------------------------------------------------------------- client-side data downloads */
function saveBlob(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const csvCell = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** CSV of `schedules` and JSON run metadata, built from server responses only (PRD §8.1). */
function DataDownloads({ runId, run }: { runId: string; run: RunResult }) {
  const plan = useRunActionPlan(runId);
  const ready = plan.data && plan.data.available !== false ? plan.data : null;
  const downloadCsv = () => {
    if (!ready) return;
    const head = ["field_id", "date", "gross_depth_mm", "policy_family"];
    const lines = [head.join(","), ...ready.schedules.map((r) => [r.field_id, r.date, r.gross_depth_mm, r.policy_family].map(csvCell).join(","))];
    saveBlob(`aabflow_schedule_${runId}.csv`, lines.join("\n") + "\n", "text/csv;charset=utf-8");
  };
  const downloadJson = () => {
    const o = run as unknown as Record<string, unknown>;
    const keys = ["run_id", "plan_kind", "outcome", "solver_status", "scenario_revision_id", "scenario_hash", "candidate_library_hash", "created_at", "warnings", "selected_intervention_instance_ids", "physical_validation"];
    const meta: Record<string, unknown> = {};
    for (const k of keys) if (k in o) meta[k] = o[k];
    if (ready) meta.action_plan = { plan_kind: ready.plan_kind, action_count: ready.actions.length, schedule_events: ready.schedules.length, status_note: ready.status_note, actions: ready.actions };
    saveBlob(`aabflow_run_${runId}.json`, JSON.stringify(meta, null, 2), "application/json");
  };
  return (
    <>
      <Button variant="secondary" icon={<Download size={15} />} disabled={!ready || !ready.schedules.length} onClick={downloadCsv} data-testid="download-schedule-csv" title={ready ? `${ready.schedules.length} irrigation events` : "Action plan unavailable"}>
        Schedule CSV
      </Button>
      <Button variant="secondary" icon={<FileJson size={15} />} onClick={downloadJson} data-testid="download-run-json">
        Run JSON
      </Button>
    </>
  );
}

/* ---------------------------------------------------------------- actions (GET /runs/{id}/action-plan) */
function ActionsSection({ runId }: { runId: string }) {
  const q = useRunActionPlan(runId);
  const decisions = useDecisions();
  const label = useFieldLabel();
  const fields = (ids: string[]) => (ids.length ? ids.map(label).join(", ") : "None");
  const d = q.data;
  return (
    <section className="mt-7" aria-labelledby="act-h" data-print-detail>
      <h2 id="act-h" className="text-[15px] font-semibold text-ink">
        Actions{d && d.available !== false ? ` (${d.actions.length})` : ""}
      </h2>
      {q.isLoading ? (
        <Skeleton className="mt-3 h-40" />
      ) : q.error || !d ? (
        <StatePanel className="mt-3" state="error" error={q.error} title="Action plan unavailable" />
      ) : d.available === false ? (
        <StatePanel className="mt-3" state="unknown" title="Action plan: unavailable">
          {d.reason}
        </StatePanel>
      ) : (
        <>
          <p className="text-[12px] text-ink-secondary">
            {d.actions.length ? "Every field below is returned by the server's action-plan view for this run." : "No new investment selected; the plan schedules existing assets only."}{" "}
            {d.schedules.length ? `${d.schedules.length} dated irrigation events are in the schedule CSV.` : ""}
          </p>
          {d.actions.length ? (
            <ol className="mt-3 flex flex-col gap-3">
              {d.actions.map((a, n) => {
                const key = `${a.run_id}|${a.action_id}`;
                const dec = decisions.d[key] ?? ((["proposed", "reviewed", "accepted", "rejected"] as Decision[]).includes(a.status as Decision) ? (a.status as Decision) : "proposed");
                const meta = CATEGORY_META[a.category as keyof typeof CATEGORY_META];
                const change = Object.entries(a.modeled_change).filter(([, v]) => typeof v === "number");
                return (
                  <li key={a.action_id} className="break-inside-avoid rounded-[12px] border border-border p-4" data-testid="action-card">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 text-[12px] text-ink-secondary">
                          <span className="num font-semibold text-ink">{n + 1}.</span>
                          {meta?.icon}
                          {meta?.label ?? titleCase(a.category)}
                          {a.crop_season ? <span className="font-mono text-[11px] text-ink-tertiary">· {a.crop_season}</span> : null}
                        </div>
                        <h3 className="mt-0.5 text-[14px] font-semibold text-ink">
                          {titleCase(a.category)} · {fields(a.target_ids)}
                        </h3>
                        {a.description && a.description !== `${a.category} ${a.action_id}` ? <div className="text-[12px] text-ink-secondary">{a.description}</div> : null}
                        <div className="font-mono text-[11px] text-ink-tertiary">{a.action_id}</div>
                      </div>
                      <div className="no-print flex flex-col items-end gap-1">
                        <Segmented
                          label={`Local decision for ${a.action_id}`}
                          size="sm"
                          value={dec}
                          onChange={(v) => decisions.set(key, v as Decision)}
                          options={(["proposed", "reviewed", "accepted", "rejected"] as Decision[]).map((x) => ({ value: x, label: titleCase(x) }))}
                        />
                        <span className="text-[11px] text-ink-tertiary">Local decision only · server status: {a.status}</span>
                      </div>
                      <Chip size="sm" className="hidden print:inline-flex">
                        Local decision: {titleCase(dec)}
                      </Chip>
                    </div>
                    <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-[12px] sm:grid-cols-3">
                      <Fact k="Targets" v={fields(a.target_ids)} />
                      <Fact k="Capital" v={typeof a.capex_pkr === "number" ? formatPKR(a.capex_pkr) : "Not reported"} />
                      <Fact k="Seasonal operating" v={typeof a.seasonal_opex_pkr === "number" ? formatPKR(a.seasonal_opex_pkr) : "Not reported"} />
                      <Fact k="Decision" v={formatDate(a.decision_date)} />
                      <Fact k="Start" v={formatDate(a.start_date)} />
                      <Fact k="Commissioning" v={formatDate(a.commissioning_date)} />
                      <Fact k="Quantity" v={quantityText(a.quantity)} />
                      <Fact k="Payer / financing" v={a.payer ?? "Not recorded"} />
                      <Fact k="Responsible role" v={a.responsible_role ?? "Not recorded"} />
                      <Fact k="Required approval" v={a.required_approval ?? "Not recorded"} />
                      <Fact k="Prerequisites" v={a.prerequisites.length ? a.prerequisites.join(", ") : "None"} />
                      <Fact k="Affected fields" v={fields(a.affected_fields)} />
                      <Fact k="Modeled production" v={change.length ? change.map(([f, v]) => `${label(f)}: ${formatMass(v as number)}`).join("; ") : "Not reported"} />
                      <Fact k="Sources" v={a.source_refs.length ? a.source_refs.join(", ") : "None"} mono />
                    </dl>
                    {a.uncertainty ? <p className="mt-2 text-[12px] text-ink-secondary">Uncertainty: {a.uncertainty}</p> : null}
                    {a.category === "pond" ? <p className="mt-1 text-[12px] text-ink-secondary">The pond footprint is removed from the field's cropped area in every metric.</p> : null}
                  </li>
                );
              })}
            </ol>
          ) : null}
          <p className="mt-3 text-[11px] text-ink-tertiary">
            {d.status_note ?? "“Accepted” records this software user's decision only. It is not a government authorization, a work order, or an instruction to operate a canal."} Decisions are stored in this browser only.
          </p>
        </>
      )}
    </section>
  );
}

function quantityText(q: Record<string, number | string | null>): string {
  const e = Object.entries(q ?? {});
  if (!e.length) return "—";
  return e
    .map(([k, v]) => {
      const name = titleCase(k);
      if (typeof v !== "number") return `${name}: ${v ?? "—"}`;
      if (/efficiency|fraction|ratio/.test(k)) return `${name}: ${formatPercent(v)}`;
      if (/_m3$/.test(k)) return `${name.replace(/ M3$/, "")}: ${formatNumber(v, 0)} m³`;
      if (/_m2$/.test(k)) return `${name.replace(/ M2$/, "")}: ${formatNumber(v, 0)} m²`;
      return `${name}: ${formatNumber(v, 2)}`;
    })
    .join("; ");
}

function Fact({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-ink-tertiary">{k}</dt>
      <dd className={cn("break-words text-ink", mono && "font-mono text-[11px]")}>{v}</dd>
    </div>
  );
}

/** One-page brief: the summary and incremental view, without the per-action detail. */
export function printBrief() {
  const el = document.documentElement;
  el.dataset.printBrief = "1";
  const done = () => {
    delete el.dataset.printBrief;
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}
