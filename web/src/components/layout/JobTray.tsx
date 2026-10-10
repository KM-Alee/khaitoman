import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Square, X } from "lucide-react";
import { isTerminal, useUI, type TrackedJob } from "@/app/store";
import { useSelection } from "@/app/selection";
import { watchJob } from "@/lib/events/jobs";
import { useCancelJob, qk } from "@/lib/api/queries";
import { formatDuration, shortId } from "@/lib/formatting";
import { JobBadge, Progress } from "@/components/status";
import { IconButton } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";

/** Subscribes to every non-terminal job and applies results only to their own revision. */
export function JobWatchers() {
  const jobs = useUI((s) => s.jobs);
  const live = jobs.filter((j) => !isTerminal(j.state));
  return (
    <>
      {live.map((j) => (
        <JobWatcher key={j.jobId} job={j} />
      ))}
    </>
  );
}

function JobWatcher({ job }: { job: TrackedJob }) {
  const qc = useQueryClient();
  const sel = useSelection();
  const selRef = useRef(sel);
  selRef.current = sel;
  useEffect(() => {
    return watchJob(job.jobId, (u) => {
      const st = useUI.getState();
      const prev = st.jobs.find((x) => x.jobId === job.jobId);
      const patch: Partial<TrackedJob> = {};
      if (u.state) patch.state = u.state;
      if (u.stage !== undefined && u.stage !== null && u.stage !== "") patch.stage = u.stage;
      if (u.progress !== undefined) patch.progress = u.progress;
      if (u.resultRef !== undefined) patch.resultRef = u.resultRef;
      if (u.error !== undefined) patch.error = u.error;
      st.updateJob(job.jobId, patch);
      if (u.state && isTerminal(u.state) && prev && !isTerminal(prev.state)) onTerminal({ ...prev, ...patch } as TrackedJob);
    });
    function onTerminal(j: TrackedJob) {
      const st = useUI.getState();
      if (j.state === "succeeded" && j.resultRef) {
        if (j.operation === "solve" && j.revisionId && j.planKind) {
          st.recordRun(j.revisionId, j.planKind, j.resultRef);
          void qc.invalidateQueries({ queryKey: qk.run(j.resultRef) });
          void qc.invalidateQueries({ queryKey: ["runs"] });
          // Late-result guard: bind to the URL only when this revision is still the active one.
          const active = st.active[j.pilotKey];
          const s = selRef.current;
          if (active?.revisionId === j.revisionId && s.pilotKey === j.pilotKey) {
            const runs = useUI.getState().runsByRevision[j.revisionId] ?? {};
            const patch: Record<string, string | null> = { runs: [runs.B0, runs.B1, runs.P, runs.R].filter(Boolean).join(",") };
            if (j.planKind === "P" || !s.runId) patch.run = j.resultRef;
            s.setParams(patch);
          } else {
            toast({ tone: "info", title: `${j.label} finished for an earlier revision`, description: `Run ${shortId(j.resultRef)} stays inspectable; it does not replace your current draft.` });
          }
        } else if (j.analysisKind) {
          void qc.invalidateQueries({ queryKey: qk.analysis(j.resultRef) });
          void qc.invalidateQueries({ queryKey: ["analyses"] });
          const s = selRef.current;
          if (s.pilotKey === j.pilotKey && s.screen === "explore") s.setParams({ analysis: j.resultRef });
        } else if (j.operation === "report") {
          void qc.invalidateQueries({ queryKey: qk.report(j.resultRef) });
        }
      } else if (j.state === "failed") {
        toast({ tone: "danger", title: `${j.label} failed`, description: j.error ?? "The job reported a failure. Earlier results remain inspectable." });
      } else if (j.state === "interrupted") {
        toast({ tone: "warning", title: `${j.label} was interrupted`, description: j.error ?? "The service restarted while this job was running." });
      }
    }
  }, [job.jobId, qc]);
  return null;
}

/** `scopeKey` overrides the pilot key for screens outside a pilot route (e.g. onboarding). */
export function JobTray({ className, scopeKey }: { className?: string; scopeKey?: string }) {
  const jobs = useUI((s) => s.jobs);
  const dismiss = useUI((s) => s.dismissJob);
  const sel = useSelection();
  const [open, setOpen] = useState(true);
  const scope = scopeKey ?? sel.pilotKey;
  const visible = jobs.filter((j) => !j.dismissed && j.pilotKey === scope).slice(0, 6);
  const running = visible.filter((j) => !isTerminal(j.state));
  const [, tick] = useState(0);
  // Succeeded jobs leave the tray once their result is bound; failures stay until dismissed.
  useEffect(() => {
    const done = visible.filter((j) => j.state === "succeeded");
    if (!done.length) return;
    const t = setTimeout(() => done.forEach((j) => dismiss(j.jobId)), 4500);
    return () => clearTimeout(t);
  }, [visible.map((j) => `${j.jobId}:${j.state}`).join("|"), dismiss]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!running.length) return;
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [running.length]);
  if (!visible.length) return null;
  return (
    <section
      aria-label="Jobs"
      className={cn("pointer-events-auto w-[320px] max-w-[calc(100vw-24px)] overflow-hidden rounded-[18px] border border-border bg-surface/97 shadow-3 backdrop-blur", className)}
      data-testid="job-tray"
    >
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between px-3.5 py-2.5 text-left">
        <span className="text-[13px] font-semibold text-ink">
          {running.length ? `${running.length} job${running.length > 1 ? "s" : ""} running` : "Recent jobs"}
        </span>
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}
      </button>
      {open ? (
        <ul className="flex max-h-[300px] flex-col divide-y divide-border overflow-auto border-t border-border">
          {visible.map((j) => (
            <JobRow key={j.jobId} job={j} onDismiss={() => dismiss(j.jobId)} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function JobRow({ job, onDismiss }: { job: TrackedJob; onDismiss: () => void }) {
  const cancel = useCancelJob();
  const terminal = isTerminal(job.state);
  const elapsed = (terminal ? job.lastUpdate : Date.now()) - job.startedAt;
  const sinceUpdate = Date.now() - job.lastUpdate;
  return (
    <li className="px-3.5 py-2.5" data-testid="job-row" data-state={job.state}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-ink">{job.label}</div>
          <div className="num text-[11px] text-ink-tertiary">
            {shortId(job.jobId)} · {formatDuration(elapsed)}
            {!terminal && sinceUpdate > 4000 ? ` · last update ${formatDuration(sinceUpdate)} ago` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <JobBadge state={job.state} />
          {!terminal ? (
            <IconButton label="Cancel job" size="sm" onClick={() => cancel.mutate(job.jobId)} disabled={job.state === "cancel_requested"}>
              <Square size={12} />
            </IconButton>
          ) : (
            <IconButton label="Dismiss" size="sm" onClick={onDismiss}>
              <X size={14} />
            </IconButton>
          )}
        </div>
      </div>
      {!terminal ? (
        <div className="mt-2">
          <Progress value={job.progress} label={`${job.label} progress`} />
          {job.stage ? <div className="mt-1 truncate text-[11px] text-ink-secondary">{job.stage}</div> : null}
        </div>
      ) : job.error ? (
        <div className="mt-1 text-[12px] text-danger">{job.error}</div>
      ) : null}
    </li>
  );
}
