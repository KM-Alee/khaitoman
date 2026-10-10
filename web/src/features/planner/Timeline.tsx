/**
 * The investigation timeline: one row per tool call (plain activity label, spinner → tick or
 * failure, duration), grouped under "Understanding your goal" / "Testing it" / "Deciding".
 * Rows enter with `animate-rise`, which the design system collapses under reduced motion.
 */
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { plainToolError } from "@/features/copilot/TurnCard";
import { formatDuration } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import type { TimelineGroup, TimelineRow } from "./timeline";

function RowIcon({ s }: { s: TimelineRow["state"] }) {
  if (s === "running") return <Loader2 size={14} aria-label="Running" className="text-water [animation:spin_1s_linear_infinite]" />;
  if (s === "ok") return <CheckCircle2 size={14} aria-label="Done" className="text-vegetation" />;
  return <XCircle size={14} aria-label="Failed" className="text-danger" />;
}

function GroupIcon({ g, n }: { g: TimelineGroup; n: number }) {
  const cls = "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold";
  if (g.state === "running") return <span className={cn(cls, "bg-water text-on-water")}>{n}</span>;
  if (g.state === "done") return <span className={cn(cls, "bg-vegetation-soft text-vegetation")}>{n}</span>;
  if (g.state === "failed") return <span className={cn(cls, "bg-danger-soft text-danger")}>{n}</span>;
  return <span className={cn(cls, "border border-border text-ink-tertiary")}>{n}</span>;
}

export function Timeline({ groups, thinking, active }: { groups: TimelineGroup[]; thinking: string | null; active: boolean }) {
  return (
    <ol className="flex flex-col gap-4" data-testid="plan-timeline" aria-live="polite">
      {groups.map((g, gi) => (
        <li key={g.phase} className="flex flex-col gap-2" data-phase={g.phase} data-state={g.state}>
          <div className="flex items-center gap-2.5">
            <GroupIcon g={g} n={gi + 1} />
            <h3 className={cn("text-[13.5px] font-semibold", g.state === "waiting" ? "text-ink-tertiary" : "text-ink")}>{g.title}</h3>
          </div>
          {g.rows.length ? (
            <ul className="ml-3 flex flex-col gap-1.5 border-l border-border pl-5">
              {g.rows.map((r) => (
                <li key={r.callId} className="animate-rise flex items-start gap-2 text-[12.5px]" data-testid="plan-timeline-row" data-tool={r.tool} data-state={r.state}>
                  <span className="mt-0.5 shrink-0">
                    <RowIcon s={r.state} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={r.state === "failed" ? "text-danger" : "text-ink"}>{r.label}</span>
                    {r.reused ? <span className="ml-1 text-[11px] text-ink-tertiary">(reused)</span> : null}
                    {r.state === "failed" && r.error ? <span className="block text-[11.5px] text-ink-secondary">{plainToolError(r.error.code, r.error.detail)}</span> : null}
                  </span>
                  {r.durationMs !== null && r.state !== "running" ? <span className="num shrink-0 text-[11px] text-ink-tertiary">{formatDuration(r.durationMs)}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="ml-3 flex items-center gap-1.5 border-l border-border pl-5 text-[12px] text-ink-tertiary">
              <Circle size={10} aria-hidden /> {active ? "Not started yet" : "No steps in this phase"}
            </p>
          )}
        </li>
      ))}
      {active && thinking ? (
        <li className="flex items-center gap-2 text-[12.5px] font-medium text-water-deep" role="status">
          <span className="flex gap-0.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-water" style={{ animationDelay: `${i * 160}ms` }} />
            ))}
          </span>
          {thinking}
        </li>
      ) : null}
    </ol>
  );
}
