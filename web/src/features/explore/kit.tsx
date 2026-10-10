/**
 * Shared Explore UI: analysis status/progress bar with cancel, a gate that renders honest
 * loading / error / failed states, run links, and objective-difference rendering.
 */
import type { ReactNode } from "react";
import { ArrowUpRight, History, Square } from "lucide-react";
import { useSelection } from "@/app/selection";
import { useCancelJob } from "@/lib/api/queries";
import type { SolverStatus } from "@/lib/api/types";
import { formatDateTime, formatDelta, formatDuration, shortId } from "@/lib/formatting";
import { Chip, JobBadge, Progress, Skeleton, SolverBadge, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { isLive, useAnalysisJob, type AnalysisRow, type AnalysisView, type ObjectiveDifference } from "./api";

/* ---------------------------------------------------------------- card shell */
export function Card({ children, className, testId, labelledBy }: { children: ReactNode; className?: string; testId?: string; labelledBy?: string }) {
  return (
    <section className={cn("min-w-0 rounded-[18px] border border-border bg-surface p-5 shadow-1", className)} data-testid={testId} aria-labelledby={labelledBy}>
      {children}
    </section>
  );
}

export function CardHeader({ icon, title, children, aside, id }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-[min(100%,300px)] flex-1">
        <h2 id={id} className="flex items-center gap-2 text-[16px] font-semibold tracking-[-0.012em] text-ink">
          {icon}
          {title}
        </h2>
        {children ? <p className="mt-1 max-w-[76ch] text-[12.5px] leading-relaxed text-ink-secondary">{children}</p> : null}
      </div>
      {aside ? <div className="flex flex-wrap items-center gap-2">{aside}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------------- status */
export function statusChip(status: string, jobState?: string | null) {
  if (status === "queued" || status === "running") return <JobBadge state={status} size="md" />;
  if (status === "completed") return <JobBadge state="succeeded" size="md" />;
  if (status === "failed") return <JobBadge state="failed" size="md" />;
  if (status === "cancelled") return <JobBadge state="cancelled" size="md" />;
  if (status === "interrupted") return <JobBadge state="interrupted" size="md" />;
  return <Chip>{status || jobState || "unknown"}</Chip>;
}

/** Status line for the selected analysis: state, measured progress, stage, cancel, history. */
export function AnalysisStatusBar({ a, history, onPick, unitLabel = "solves" }: { a: AnalysisView<unknown>; history: AnalysisRow[]; onPick: (id: string) => void; unitLabel?: string }) {
  const live = isLive(a);
  const job = useAnalysisJob(a.job_id, live);
  const cancel = useCancelJob();
  const wall = (a.result as { wall_ms?: number } | null)?.wall_ms;
  const j = job.data;
  const progress = j?.progress ?? null;
  return (
    <div className="flex flex-col gap-2 rounded-[18px] border border-border bg-surface-muted/50 px-3.5 py-3" data-testid="analysis-status" data-status={a.status}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-ink-secondary">
        {statusChip(a.status, a.job_state)}
        <span className="font-mono text-[11px] text-ink-tertiary" title={a.analysis_id}>
          {shortId(a.analysis_id)}
        </span>
        <span>Started {formatDateTime(a.created_at)}</span>
        {a.child_run_ids.length ? (
          <span>
            {a.child_run_ids.length} {a.child_run_ids.length === 1 ? unitLabel.replace(/s$/, "") : unitLabel} recorded as immutable run{a.child_run_ids.length === 1 ? "" : "s"}
          </span>
        ) : null}
        {wall !== undefined && !live ? <span>{formatDuration(wall)} wall time</span> : null}
        <div className="ml-auto flex items-center gap-1.5">
          {history.length > 1 ? (
            <label className="flex items-center gap-1 text-[12px] text-ink-secondary">
              <History size={13} aria-hidden />
              <span className="sr-only">Earlier analyses</span>
              <select
                className="h-7 max-w-[220px] rounded-[8px] border border-border-strong/60 bg-surface px-1.5 text-[12px] text-ink"
                value={a.analysis_id}
                onChange={(e) => onPick(e.target.value)}
                aria-label="Earlier analyses of this kind"
              >
                {!history.some((h) => h.analysis_id === a.analysis_id) ? <option value={a.analysis_id}>{shortId(a.analysis_id)} (linked)</option> : null}
                {history.map((h) => (
                  <option key={h.analysis_id} value={h.analysis_id}>
                    {formatDateTime(h.created_at)} · {h.status}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {live && a.job_id ? (
            <Button size="sm" variant="ghost" icon={<Square size={12} />} busy={cancel.isPending} onClick={() => cancel.mutate(a.job_id!)} disabled={j?.state === "cancel_requested"}>
              {j?.state === "cancel_requested" ? "Cancelling…" : "Cancel"}
            </Button>
          ) : null}
        </div>
      </div>
      {live ? (
        <div className="flex flex-col gap-1">
          <Progress value={progress} label="Analysis progress" />
          <span className="truncate text-[11px] text-ink-tertiary" aria-live="polite">
            {j?.stage ? `Now: ${j.stage}` : a.status === "queued" ? "Waiting for a solver worker…" : "Solving…"} Completed points appear as each child run finishes.
          </span>
        </div>
      ) : null}
      {a.status === "failed" || a.status === "interrupted" || a.job_error ? (
        <div role="alert" className="rounded-[8px] bg-danger-soft px-2.5 py-1.5 text-[12px] text-danger">
          {a.job_error?.code ? <span className="font-mono">{a.job_error.code}: </span> : null}
          {a.job_error?.detail ?? (a.status === "interrupted" ? "The service restarted while this analysis was running." : "The job reported a failure without detail.")}
          {a.result ? " Results recorded before the failure are shown below." : ""}
        </div>
      ) : null}
      {a.status === "cancelled" ? <div className="text-[12px] text-ink-secondary">Cancelled: only the points that finished before cancellation are shown.</div> : null}
    </div>
  );
}

/** Narrow the current-analysis state into loading / error / empty / ready. */
export function AnalysisGate<T>({
  cur,
  title,
  empty,
  children,
  skeleton = "h-72",
}: {
  cur: { data: AnalysisView<T> | null; loading: boolean; error: unknown };
  title: string;
  empty: ReactNode;
  children: (a: AnalysisView<T>) => ReactNode;
  skeleton?: string;
}) {
  if (cur.loading && !cur.data) return <Skeleton className={skeleton} />;
  if (cur.error && !cur.data) return <StatePanel state="error" error={cur.error} title={`${title} unavailable`} />;
  if (!cur.data) return <>{empty}</>;
  return <>{children(cur.data)}</>;
}

/* ---------------------------------------------------------------- runs */
export function RunLink({ runId, label, className }: { runId: string; label?: ReactNode; className?: string }) {
  const sel = useSelection();
  return (
    <a
      href={sel.hrefFor("workspace", { run: runId })}
      onClick={(e) => {
        e.preventDefault();
        sel.go("workspace", { run: runId });
      }}
      className={cn("inline-flex items-center gap-0.5 font-mono text-[11px] text-water hover:underline", className)}
      title={`Open run ${runId} in Workspace`}
    >
      {label ?? shortId(runId)}
      <ArrowUpRight size={11} aria-hidden />
    </a>
  );
}

const KNOWN_SOLVER = new Set(["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"]);
/** Solver status, or the analysis' own outcome when no solve happened (rejected / not run). */
export function OutcomeBadge({ status, outcome }: { status?: string | null; outcome?: string | null }) {
  if (outcome === "rejected") return <Chip tone="warning" size="sm">Rejected by validation</Chip>;
  if (outcome === "not_run") return <Chip size="sm">Not run</Chip>;
  if (outcome === "invalid_plan") return <Chip tone="danger" size="sm">Invalid plan</Chip>;
  if (status && KNOWN_SOLVER.has(status)) return <SolverBadge status={status as SolverStatus} size="sm" />;
  return <Chip size="sm">{status ?? "—"}</Chip>;
}

/* ---------------------------------------------------------------- objective differences */
export function differenceText(d: ObjectiveDifference | null | undefined, unit: string): string {
  if (!d) return "Not reported";
  if (d.status === "no_change") return `${formatDelta(0, unit)} (unchanged)`;
  if (d.status === "not_comparable" || d.lower === null || d.upper === null) return "Not comparable";
  if (d.status === "exact" && d.point !== null) return formatDelta(d.point, unit);
  return `${formatDelta(d.lower, unit)} to ${formatDelta(d.upper, unit)}`;
}

export function DifferenceChip({ d }: { d: ObjectiveDifference | null | undefined }) {
  if (!d) return null;
  const m = {
    exact: { t: "Exact (proven optimal)", tone: "vegetation" as const },
    interval: { t: "Interval: solver bounds overlap", tone: "warning" as const },
    not_comparable: { t: "Not comparable", tone: "neutral" as const },
    no_change: { t: "No change", tone: "neutral" as const },
  }[d.status];
  return (
    <Chip tone={m?.tone ?? "neutral"} size="sm">
      {m?.t ?? d.status}
    </Chip>
  );
}

/** Large stat tile. */
export function Stat({ label, value, sub, className, testId }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string; testId?: string }) {
  return (
    <div className={cn("min-w-0 rounded-[14px] border border-border/70 bg-surface-muted/60 p-3.5", className)} data-testid={testId}>
      <div className="text-[12px] font-medium text-ink-secondary">{label}</div>
      <div className="num mt-1 text-[20px] font-semibold tracking-[-0.015em] text-ink">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] leading-snug text-ink-tertiary">{sub}</div> : null}
    </div>
  );
}

/** Compact numeric input used by the analysis setup forms. */
export function NumInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
  className,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1 text-[12px] font-medium text-ink-secondary", className)}>
      {label}
      <span className="flex h-9 items-center rounded-[9px] border border-border-strong/55 bg-surface-raised pr-2 shadow-1">
        <input
          type="number"
          className="num h-full w-full min-w-0 bg-transparent px-2 text-right text-[13px] text-ink outline-none"
          value={Number.isFinite(value) ? value : ""}
          min={min}
          max={max}
          step={step}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (Number.isFinite(v)) onChange(v);
          }}
        />
        {suffix ? <span className="shrink-0 text-[12px] text-ink-tertiary">{suffix}</span> : null}
      </span>
    </label>
  );
}
