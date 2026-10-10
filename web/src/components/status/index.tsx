import type { ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  CircleSlash,
  Clock,
  FlaskConical,
  Loader2,
  MinusCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDelta, formatWithUnit, shortId } from "@/lib/formatting";
import type { JobState, MetricValue, ReviewFlags, RunResult, SolverStatus } from "@/lib/api/types";
import { describeError } from "@/lib/api/client";
import { Button } from "@/components/ui/Button";
import { SpotArt, type SpotKind } from "@/components/ui/Art";

export type Tone = "neutral" | "water" | "vegetation" | "warning" | "danger" | "info" | "ink" | "wheat";

const toneCls: Record<Tone, string> = {
  neutral: "bg-surface-muted text-ink-secondary border-border",
  water: "bg-water-soft text-water-deep border-water/20",
  vegetation: "bg-vegetation-soft text-vegetation border-vegetation/20",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  info: "bg-surface text-ink-secondary border-border-strong/45",
  ink: "bg-ink text-canvas border-ink",
  wheat: "bg-wheat-soft text-wheat-ink border-wheat/30",
};

/** Small chip; status is always icon + text, never colour alone. */
export function Chip({
  tone = "neutral",
  icon,
  children,
  className,
  title,
  size = "md",
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
  size?: "sm" | "md";
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border font-medium leading-none whitespace-nowrap",
        size === "sm" ? "h-[22px] px-2 text-[11.5px]" : "h-[26px] px-2.5 text-[12px]",
        toneCls[tone],
        className,
      )}
    >
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

/* ---------------------------------------------------------------- review flags: five, separate (PRD §2.3) */
const flagMeta = {
  geography_reviewed: { label: "Geography" },
  topology_structurally_valid: { label: "Topology" },
  rights_verification: { label: "Rights" },
  cost_evidence: { label: "Costs" },
  crop_calibration: { label: "Crop model" },
} as const;

function flagTone(k: keyof ReviewFlags, v: ReviewFlags[keyof ReviewFlags]): { tone: Tone; text: string; icon: ReactNode; ok: boolean } {
  const ok = <CheckCircle2 size={12} aria-hidden />;
  const warn = <AlertTriangle size={12} aria-hidden />;
  const no = <XCircle size={12} aria-hidden />;
  switch (k) {
    case "geography_reviewed":
      return v ? { tone: "vegetation", text: "reviewed", icon: ok, ok: true } : { tone: "warning", text: "not reviewed", icon: warn, ok: false };
    case "topology_structurally_valid":
      return v ? { tone: "vegetation", text: "structurally valid", icon: ok, ok: true } : { tone: "danger", text: "invalid", icon: no, ok: false };
    case "rights_verification":
      return v === "verified" ? { tone: "vegetation", text: "verified", icon: ok, ok: true } : { tone: "warning", text: String(v), icon: warn, ok: false };
    case "cost_evidence":
      return v === "quoted" ? { tone: "vegetation", text: "quoted", icon: ok, ok: true } : { tone: "warning", text: String(v), icon: warn, ok: false };
    case "crop_calibration":
      return v === "calibrated"
        ? { tone: "vegetation", text: "calibrated", icon: ok, ok: true }
        : { tone: "warning", text: String(v).replace(/_/g, " "), icon: warn, ok: false };
  }
}

/** Plain meaning of each flag for first-time readers (shown in TrustSummary). */
export const FLAG_PLAIN: Record<keyof ReviewFlags, { ok: string; not: string }> = {
  geography_reviewed: { ok: "Field boundaries and canals were checked by a person.", not: "Field boundaries have not been checked by a person yet." },
  topology_structurally_valid: { ok: "The canal network's connections are consistent.", not: "The canal network has structural problems." },
  rights_verification: { ok: "Water turns come from verified records.", not: "Water turns are assumed from typical rosters, not local records." },
  cost_evidence: { ok: "Costs come from dated quotes.", not: "Costs are documented estimates, not local quotes." },
  crop_calibration: { ok: "The crop model is calibrated to local harvests.", not: "The crop model uses standard settings, not calibrated to local harvests." },
};

export function ReviewFlagChips({ flags, size = "sm", className }: { flags?: ReviewFlags | null; size?: "sm" | "md"; className?: string }) {
  if (!flags) return <Chip tone="neutral" size={size}>Review flags unavailable</Chip>;
  return (
    <ul className={cn("flex flex-wrap items-center gap-1", className)} aria-label="Pilot review flags">
      {(Object.keys(flagMeta) as (keyof ReviewFlags)[]).map((k) => {
        const t = flagTone(k, flags[k]);
        return (
          <li key={k}>
            <Chip tone={t.tone} icon={t.icon} size={size} title={`${flagMeta[k].label}: ${t.text}. ${t.ok ? FLAG_PLAIN[k].ok : FLAG_PLAIN[k].not}`}>
              <span className="font-semibold">{flagMeta[k].label}</span> {t.text}
            </Chip>
          </li>
        );
      })}
    </ul>
  );
}

/** Five flags as plain sentences: what is checked and what is still assumed. */
export function TrustSummary({ flags, className }: { flags?: ReviewFlags | null; className?: string }) {
  if (!flags) return null;
  const keys = Object.keys(flagMeta) as (keyof ReviewFlags)[];
  return (
    <ul className={cn("flex flex-col gap-2", className)} aria-label="What is checked and what is assumed">
      {keys.map((k) => {
        const t = flagTone(k, flags[k]);
        return (
          <li key={k} className="flex items-start gap-2.5 text-[13px] leading-snug">
            <span className={cn("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full", t.ok ? "bg-vegetation-soft text-vegetation" : "bg-warning-soft text-warning")}>{t.icon}</span>
            <span className="min-w-0">
              <span className="font-semibold text-ink">{flagMeta[k].label}</span>
              <span className="text-ink-tertiary"> · {t.text}</span>
              <span className="block text-ink-secondary">{t.ok ? FLAG_PLAIN[k].ok : FLAG_PLAIN[k].not}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------- solver status (PRD §4.3, §9.5) */
export const SOLVER_COPY: Record<SolverStatus, { label: string; plain: string; friendly: string; tone: Tone }> = {
  OPTIMAL: {
    label: "Optimal",
    plain: "Best plan proven",
    friendly: "Best plan proven within the finite candidate library.",
    tone: "vegetation",
  },
  FEASIBLE: {
    label: "Feasible",
    plain: "Good plan found",
    friendly: "Valid plan found; search ended before optimality was proven.",
    tone: "water",
  },
  INFEASIBLE: {
    label: "Infeasible",
    plain: "No plan fits every rule",
    friendly: "No plan in the finite candidate model satisfies every constraint. This is not proof of physical impossibility.",
    tone: "warning",
  },
  UNKNOWN: {
    label: "Unknown",
    plain: "No answer yet",
    friendly: "Search ended without finding a valid plan. Not a proof of infeasibility.",
    tone: "neutral",
  },
  MODEL_INVALID: {
    label: "Model invalid",
    plain: "Model error",
    friendly: "The generated optimization model was invalid. Engineering diagnostic only; no recommendation.",
    tone: "danger",
  },
};

export function SolverBadge({ status, showFriendly, size = "md" }: { status: SolverStatus; showFriendly?: boolean; size?: "sm" | "md" }) {
  const c = SOLVER_COPY[status] ?? SOLVER_COPY.UNKNOWN;
  const icon =
    status === "OPTIMAL" ? (
      <CheckCircle2 size={12} aria-hidden />
    ) : status === "FEASIBLE" ? (
      <CircleDashed size={12} aria-hidden />
    ) : status === "INFEASIBLE" ? (
      <CircleSlash size={12} aria-hidden />
    ) : status === "UNKNOWN" ? (
      <CircleHelp size={12} aria-hidden />
    ) : (
      <Ban size={12} aria-hidden />
    );
  return (
    <span className="inline-flex flex-col items-start gap-1" data-solver-status={status}>
      <Chip tone={c.tone} icon={icon} size={size} title={`${c.label.toUpperCase()}: ${c.friendly}`}>
        {c.label}
      </Chip>
      {showFriendly ? <span className="text-[12px] text-ink-secondary">{c.friendly}</span> : null}
    </span>
  );
}

export const JOB_COPY: Record<JobState, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "water" },
  waiting_for_review: { label: "Waiting for review", tone: "warning" },
  succeeded: { label: "Completed", tone: "vegetation" },
  failed: { label: "Failed", tone: "danger" },
  cancel_requested: { label: "Cancelling", tone: "warning" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  interrupted: { label: "Interrupted", tone: "warning" },
};

export function JobBadge({ state, size = "sm" }: { state: JobState; size?: "sm" | "md" }) {
  const c = JOB_COPY[state] ?? JOB_COPY.queued;
  const icon =
    state === "running" || state === "queued" ? (
      <Loader2 size={11} className="[animation:spin_1s_linear_infinite]" aria-hidden />
    ) : state === "succeeded" ? (
      <CheckCircle2 size={11} aria-hidden />
    ) : state === "failed" ? (
      <XCircle size={11} aria-hidden />
    ) : (
      <Clock size={11} aria-hidden />
    );
  return (
    <Chip tone={c.tone} icon={icon} size={size}>
      {c.label}
    </Chip>
  );
}

/* ---------------------------------------------------------------- estimate kinds (PRD §0.3 #6) */
export type EstimateKind = "exact" | "preview" | "retrospective" | "observation" | "assumption";
export function EstimateBadge({ kind, size = "sm" }: { kind: EstimateKind; size?: "sm" | "md" }) {
  const m = {
    exact: { t: "Exact crop model", tone: "vegetation" as Tone, i: <FlaskConical size={11} aria-hidden /> },
    preview: { t: "Approximate preview", tone: "warning" as Tone, i: <Sparkles size={11} aria-hidden /> },
    retrospective: { t: "Retrospective", tone: "info" as Tone, i: <RefreshCw size={11} aria-hidden /> },
    observation: { t: "Observation", tone: "water" as Tone, i: <CheckCircle2 size={11} aria-hidden /> },
    assumption: { t: "Assumption", tone: "warning" as Tone, i: <AlertTriangle size={11} aria-hidden /> },
  }[kind];
  return (
    <Chip tone={m.tone} icon={m.i} size={size}>
      {m.t}
    </Chip>
  );
}

/* ---------------------------------------------------------------- provenance: which run, when, how sure */
/**
 * The quiet "where does this number come from" line. Always shows the run id (traceable),
 * when the server computed it, the solver status and the physical-validation result.
 */
export function Provenance({
  run,
  saved,
  className,
  revisionId,
}: {
  run: RunResult | null | undefined;
  /** A stored result opened from a link or the tour (not the user's current settings). */
  saved?: boolean;
  className?: string;
  revisionId?: string | null;
}) {
  if (!run) return null;
  const v = run.outcome === "plan" ? run.physical_validation?.status : null;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-ink-tertiary", className)} data-testid="provenance" data-run-id={run.run_id}>
      {saved ? (
        <Chip size="sm" tone="wheat" icon={<Clock size={11} aria-hidden />}>
          Saved result
        </Chip>
      ) : null}
      <span className="num" title={run.run_id}>
        run <span className="font-mono text-ink-secondary">{shortId(run.run_id)}</span>
      </span>
      <span aria-hidden>·</span>
      <span>computed {formatDateTime(run.created_at)}</span>
      <span aria-hidden>·</span>
      <span title={SOLVER_COPY[run.solver_status]?.friendly}>{SOLVER_COPY[run.solver_status]?.plain ?? run.solver_status}</span>
      {v ? (
        <>
          <span aria-hidden>·</span>
          <span className={cn("inline-flex items-center gap-1", v === "passed" ? "text-vegetation" : "text-warning")} title="Original-precision ledger reconstruction">
            {v === "passed" ? <ShieldCheck size={12} aria-hidden /> : <AlertTriangle size={12} aria-hidden />}
            {v === "passed" ? "water books balance" : `validation ${v}`}
          </span>
        </>
      ) : null}
      {revisionId ? (
        <>
          <span aria-hidden>·</span>
          <span className="num" title={revisionId}>
            settings <span className="font-mono">{shortId(revisionId)}</span>
          </span>
        </>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- MetricValue renderer (T7.5) */
export function metricText(m: Pick<MetricValue, "status" | "value" | "unit"> | null | undefined): string {
  if (!m) return "Unavailable";
  if (m.status === "available" && m.value !== null && m.value !== undefined) return formatWithUnit(m.value, m.unit);
  if (m.status === "not_estimated") return "Not estimated";
  if (m.status === "not_applicable") return "Not applicable";
  if (m.status === "blocked") return "Blocked";
  return "Unavailable";
}

export function MetricValueView({
  metric,
  size = "md",
  delta,
  className,
  showReason = true,
}: {
  metric: MetricValue | null | undefined;
  size?: "sm" | "md" | "lg" | "xl";
  delta?: { value: number; unit: string; goodWhen?: "up" | "down" | "neutral" } | null;
  className?: string;
  showReason?: boolean;
}) {
  const sz = { sm: "text-[13px]", md: "text-[15px]", lg: "text-[22px] tracking-[-0.01em]", xl: "text-[30px] tracking-[-0.02em]" }[size];
  if (!metric) {
    return (
      <span className={cn("inline-flex items-center gap-1 text-ink-tertiary", sz, className)}>
        <MinusCircle size={14} aria-hidden /> <span className="text-[13px]">Unavailable</span>
      </span>
    );
  }
  if (metric.status !== "available" || metric.value === null) {
    const label = metricText(metric);
    const icon =
      metric.status === "blocked" ? <Ban size={13} aria-hidden /> : metric.status === "not_applicable" ? <MinusCircle size={13} aria-hidden /> : <CircleDashed size={13} aria-hidden />;
    return (
      <span className={cn("inline-flex flex-col", className)} data-status={metric.status}>
        <span className={cn("inline-flex items-center gap-1 font-medium", metric.status === "blocked" ? "text-warning" : "text-ink-tertiary", size === "sm" ? "text-[12px]" : "text-[13px]")}>
          {icon}
          {label}
        </span>
        {showReason && metric.reason ? <span className="text-[12px] text-ink-secondary">{metric.reason}</span> : null}
      </span>
    );
  }
  const dTone =
    delta && delta.value !== 0 && delta.goodWhen && delta.goodWhen !== "neutral"
      ? (delta.value > 0) === (delta.goodWhen === "up")
        ? "text-vegetation"
        : "text-danger"
      : "text-ink-secondary";
  return (
    <span className={cn("inline-flex items-baseline gap-2", className)} data-status="available">
      <span className={cn("num font-semibold text-ink", sz)}>{formatWithUnit(metric.value, metric.unit)}</span>
      {delta ? <span className={cn("num text-[12px] font-medium", dTone)}>{formatDelta(delta.value, delta.unit)}</span> : null}
    </span>
  );
}

/* ---------------------------------------------------------------- section states */
export type ViewState = "empty" | "busy" | "ready" | "stale" | "feasible" | "infeasible" | "unknown" | "error";

const STATE_ART: Record<string, SpotKind> = { empty: "plan", busy: "busy", error: "error", unknown: "search", infeasible: "infeasible", blocked: "infeasible" };

/**
 * Empty / busy / error / unknown / infeasible / blocked state with a named reason and the
 * next step. `art` swaps the spot illustration; `compact` drops it for tight panels.
 */
export function StatePanel({
  state,
  title,
  children,
  action,
  error,
  className,
  compact,
  art,
}: {
  state: "empty" | "busy" | "error" | "unknown" | "infeasible" | "blocked";
  title?: ReactNode;
  children?: ReactNode;
  action?: { label: string; onClick: () => void } | ReactNode;
  error?: unknown;
  className?: string;
  compact?: boolean;
  art?: SpotKind;
}) {
  const e = error ? describeError(error) : null;
  const icon = {
    empty: <CircleDashed size={18} aria-hidden className="text-ink-tertiary" />,
    busy: <Loader2 size={18} aria-hidden className="text-water [animation:spin_1s_linear_infinite]" />,
    error: <XCircle size={18} aria-hidden className="text-danger" />,
    unknown: <CircleHelp size={18} aria-hidden className="text-ink-tertiary" />,
    infeasible: <CircleSlash size={18} aria-hidden className="text-warning" />,
    blocked: <Ban size={18} aria-hidden className="text-warning" />,
  }[state];
  return (
    <div
      role={state === "error" ? "alert" : state === "busy" ? "status" : undefined}
      aria-live={state === "busy" ? "polite" : undefined}
      data-state={state}
      className={cn(
        "flex items-start gap-4 rounded-[18px] border bg-surface",
        state === "error" ? "border-danger/30" : state === "infeasible" || state === "blocked" ? "border-warning/30" : "border-border",
        compact ? "gap-3 p-3.5" : "p-5",
        className,
      )}
    >
      {compact ? <span className="mt-0.5 shrink-0">{icon}</span> : <SpotArt kind={art ?? STATE_ART[state]} className="shrink-0" />}
      <div className="flex min-w-0 flex-col items-start gap-1.5">
        <div className={cn("font-semibold text-ink", compact ? "text-[13px]" : "text-[15px] tracking-[-0.01em]")}>{title ?? e?.title}</div>
        {children || e ? <div className="text-[13px] leading-relaxed text-ink-secondary">{children ?? e?.detail}</div> : null}
        {action ? (
          <div className="mt-1.5">
            {isActionObj(action) ? (
              <Button size="sm" variant={state === "empty" ? "primary" : "secondary"} onClick={action.onClick}>
                {action.label}
              </Button>
            ) : (
              action
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
function isActionObj(a: unknown): a is { label: string; onClick: () => void } {
  return !!a && typeof a === "object" && "label" in (a as object) && "onClick" in (a as object);
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton", className)} />;
}

/** Indeterminate or measured progress — never fake percentages (PRD §9.5). */
export function Progress({ value, label, className }: { value: number | null | undefined; label: string; className?: string }) {
  const measured = typeof value === "number" && Number.isFinite(value);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={measured ? 0 : undefined}
      aria-valuemax={measured ? 100 : undefined}
      aria-valuenow={measured ? Math.round(value! * 100) : undefined}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken", !measured && "indeterminate", className)}
    >
      {measured ? <div className="h-full rounded-full bg-water transition-[width] duration-300" style={{ width: `${Math.max(2, value! * 100)}%` }} /> : null}
    </div>
  );
}
