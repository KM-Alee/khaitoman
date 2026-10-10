/**
 * Shared rendering helpers for the server's dedicated run views (/accounting, /equity,
 * /economics, /action-plan, /impact). Values are displayed exactly as returned; any
 * `{available:false, reason}` answer renders as an honest unavailable state.
 */
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { CircleDashed, MinusCircle, Ban } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import type { RunView, StatusReason } from "@/lib/api/queries";
import { Skeleton, StatePanel } from "@/components/status";
import { Eyebrow } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";

/** Narrow a run-view query into loading / error / unavailable / ready. */
export function ViewGate<T>({
  q,
  title,
  children,
  skeleton = "h-72",
  testId,
}: {
  q: UseQueryResult<RunView<T>, unknown>;
  title: string;
  children: (d: T & { available: true }) => ReactNode;
  skeleton?: string;
  testId?: string;
}) {
  if (q.isLoading)
    return (
      <div className="grid gap-3 md:grid-cols-2" aria-busy="true" role="status" aria-label={`${title} loading`} data-testid={testId ? `${testId}-loading` : undefined}>
        <Skeleton className={skeleton} />
        <Skeleton className={skeleton} />
      </div>
    );
  if (q.error || !q.data)
    return (
      <div data-testid={testId ? `${testId}-error` : undefined}>
        <StatePanel state="error" error={q.error} title={`${title} unavailable`} />
      </div>
    );
  if (q.data.available === false)
    return (
      <div data-testid={testId ? `${testId}-unavailable` : undefined}>
        <StatePanel state="unknown" title={`${title}: unavailable`}>
          {q.data.reason || "The server did not return a reason."}
        </StatePanel>
      </div>
    );
  return <>{children(q.data)}</>;
}

/** Field id → display label ("A-001"), falling back to the id without the pilot prefix. */
export function useFieldLabel() {
  const { fieldIndex } = usePilotData();
  return (id: string) => fieldIndex.get(id)?.label ?? id.replace(/^[^:]+:/, "");
}

export function isStatusReason(v: unknown): v is StatusReason {
  return !!v && typeof v === "object" && "status" in (v as object);
}

/** Inline rendering of a server `{status, reason}` pair. */
export function StatusReasonView({ v, className }: { v: StatusReason | null | undefined; className?: string }) {
  if (!v) return <span className={cn("text-[12px] text-ink-tertiary", className)}>Not reported</span>;
  const icon = v.status === "blocked" ? <Ban size={13} aria-hidden /> : v.status === "not_applicable" ? <MinusCircle size={13} aria-hidden /> : <CircleDashed size={13} aria-hidden />;
  return (
    <span className={cn("inline-flex flex-col", className)} data-status={v.status}>
      <span className="inline-flex items-center gap-1 text-[12px] font-medium text-ink-tertiary">
        {icon}
        {statusLabel(v.status)}
      </span>
      {v.reason ? <span className="text-[12px] text-ink-secondary">{v.reason}</span> : null}
    </span>
  );
}

export function Panel({ title, children, className, aside }: { title: ReactNode; children: ReactNode; className?: string; aside?: ReactNode }) {
  return (
    <section className={cn("min-w-0 rounded-[18px] border border-border bg-surface p-5 shadow-1", className)}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <Eyebrow>{title}</Eyebrow>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** Label / value row list. */
export function Rows({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="flex flex-col divide-y divide-border">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-3 py-2">
          <dt className="text-[13px] text-ink-secondary">{k}</dt>
          <dd className="num text-right text-[13px] text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Spend vs. budget bar; a pure ratio display of two server numbers. */
export function BudgetMeter({ used, budget, label }: { used: number; budget: number; label: string }) {
  const pct = budget > 0 ? Math.min(1, used / budget) : 0;
  const over = budget > 0 && used > budget;
  return (
    <div className="mt-2" aria-label={label}>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-muted">
        <div className={cn("h-full rounded-full", over ? "bg-danger" : "bg-water")} style={{ width: `${Math.max(pct * 100, used > 0 ? 1 : 0)}%` }} />
      </div>
      <div className="num mt-1 text-[11px] text-ink-tertiary">
        {budget > 0 ? `${((used / budget) * 100).toFixed(1)}% of budget${over ? " · over budget" : ""}` : "No budget reported"}
      </div>
    </div>
  );
}

export function statusLabel(s: string): string {
  const t = String(s).replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
