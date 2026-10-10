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
  Sparkles,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { formatDelta, formatWithUnit } from "@/lib/formatting";
import type { JobState, MetricValue, ReviewFlags, SolverStatus } from "@/lib/api/types";
import { describeError } from "@/lib/api/client";
import { Button } from "@/components/ui/Button";

export type Tone = "neutral" | "water" | "vegetation" | "warning" | "danger" | "info" | "ink";

const toneCls: Record<Tone, string> = {
  neutral: "bg-surface-muted text-ink-secondary border-border",
  water: "bg-water-soft text-water-deep border-water/25",
  vegetation: "bg-vegetation-soft text-vegetation border-vegetation/25",
  warning: "bg-warning-soft text-warning border-warning/30",
  danger: "bg-danger-soft text-danger border-danger/30",
  info: "bg-surface text-ink-secondary border-border-strong/60",
  ink: "bg-ink text-canvas border-ink",
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
        size === "sm" ? "h-5 px-1.5 text-[11px]" : "h-6 px-2 text-[12px]",
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

function flagTone(k: keyof ReviewFlags, v: ReviewFlags[keyof ReviewFlags]): { tone: Tone; text: string; icon: ReactNode } {
  const ok = <CheckCircle2 size={12} aria-hidden />;
  const warn = <AlertTriangle size={12} aria-hidden />;
  const no = <XCircle size={12} aria-hidden />;
  switch (k) {
    case "geography_reviewed":
      return v ? { tone: "vegetation", text: "reviewed", icon: ok } : { tone: "warning", text: "not reviewed", icon: warn };
    case "topology_structurally_valid":
      return v ? { tone: "vegetation", text: "structurally valid", icon: ok } : { tone: "danger", text: "invalid", icon: no };
    case "rights_verification":
      return v === "verified"
        ? { tone: "vegetation", text: "verified", icon: ok }
        : { tone: "warning", text: String(v), icon: warn };
    case "cost_evidence":
      return v === "quoted"
        ? { tone: "vegetation", text: "quoted", icon: ok }
        : { tone: "warning", text: String(v), icon: warn };
    case "crop_calibration":
      return v === "calibrated"
        ? { tone: "vegetation", text: "calibrated", icon: ok }
        : { tone: "warning", text: String(v).replace(/_/g, " "), icon: warn };
  }
}

export function ReviewFlagChips({ flags, size = "sm", className }: { flags?: ReviewFlags | null; size?: "sm" | "md"; className?: string }) {
  if (!flags) return <Chip tone="neutral" size={size}>Review flags unavailable</Chip>;
  return (
    <ul className={cn("flex flex-wrap items-center gap-1", className)} aria-label="Pilot review flags">
      {(Object.keys(flagMeta) as (keyof ReviewFlags)[]).map((k) => {
        const t = flagTone(k, flags[k]);
        return (
          <li key={k}>
            <Chip tone={t.tone} icon={t.icon} size={size} title={`${flagMeta[k].label}: ${t.text}`}>
              <span className="font-semibold">{flagMeta[k].label}</span> {t.text}
            </Chip>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------- solver status (PRD §4.3, §9.5) */
export const SOLVER_COPY: Record<SolverStatus, { label: string; friendly: string; tone: Tone }> = {
  OPTIMAL: {
    label: "Optimal",
    friendly: "Best plan proven within the finite candidate library.",
    tone: "vegetation",
  },
  FEASIBLE: {
    label: "Feasible",
    friendly: "Valid plan found; search ended before optimality was proven.",
    tone: "water",
  },
  INFEASIBLE: {
    label: "Infeasible",
    friendly: "No plan in the finite candidate model satisfies every constraint. This is not proof of physical impossibility.",
    tone: "warning",
  },
  UNKNOWN: {
    label: "Unknown",
    friendly: "Search ended without finding a valid plan. Not a proof of infeasibility.",
    tone: "neutral",
  },
  MODEL_INVALID: {
    label: "Model invalid",
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
    <span className="inline-flex flex-col gap-1">
      <Chip tone={c.tone} icon={icon} size={size} title={c.friendly}>
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

export function StatePanel({
  state,
  title,
  children,
  action,
  error,
  className,
  compact,
}: {
  state: "empty" | "busy" | "error" | "unknown" | "infeasible" | "blocked";
  title?: ReactNode;
  children?: ReactNode;
  action?: { label: string; onClick: () => void } | ReactNode;
  error?: unknown;
  className?: string;
  compact?: boolean;
}) {
  const e = error ? describeError(error) : null;
  const icon = {
    empty: <CircleDashed size={20} aria-hidden className="text-ink-tertiary" />,
    busy: <Loader2 size={20} aria-hidden className="text-water [animation:spin_1s_linear_infinite]" />,
    error: <XCircle size={20} aria-hidden className="text-danger" />,
    unknown: <CircleHelp size={20} aria-hidden className="text-ink-tertiary" />,
    infeasible: <CircleSlash size={20} aria-hidden className="text-warning" />,
    blocked: <Ban size={20} aria-hidden className="text-warning" />,
  }[state];
  return (
    <div
      role={state === "error" ? "alert" : state === "busy" ? "status" : undefined}
      aria-live={state === "busy" ? "polite" : undefined}
      data-state={state}
      className={cn(
        "flex flex-col items-start gap-2 rounded-[12px] border border-dashed border-border-strong/60 bg-surface/60",
        compact ? "p-3" : "p-5",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {icon}
        <div className="text-[13px] font-semibold text-ink">{title ?? e?.title}</div>
      </div>
      {children || e ? <div className="text-[13px] leading-relaxed text-ink-secondary">{children ?? e?.detail}</div> : null}
      {action ? (
        isActionObj(action) ? (
          <Button size="sm" variant="secondary" onClick={action.onClick}>
            {action.label}
          </Button>
        ) : (
          action
        )
      ) : null}
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
