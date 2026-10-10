/**
 * "AI inside" (docs/WIN_PLAN.md W2): the four engines with one server fact each, and a link to
 * where the proof lives in the app. Facts come from GET /ai-stack; a missing source renders the
 * server's reason instead of a number.
 */
import { useNavigate } from "react-router";
import { ArrowRight, Cpu, MessagesSquare, Route as RouteIcon, Satellite } from "lucide-react";
import type { ReactNode } from "react";
import { useAiStack, useHeadline, type AiEngine } from "@/lib/api/showcase";
import { formatWithUnit } from "@/lib/formatting";
import { useUI } from "@/app/store";
import { Skeleton } from "@/components/status";
import { cn } from "@/lib/cn";

const ICON: Record<AiEngine["id"], ReactNode> = {
  sees: <Satellite size={18} />,
  predicts: <Cpu size={18} />,
  plans: <RouteIcon size={18} />,
  explains: <MessagesSquare size={18} />,
};

const PROOF: Record<AiEngine["id"], string> = {
  sees: "Show the raw AI outlines",
  predicts: "Try the instant estimate",
  plans: "Open the proven plan",
  explains: "Ask a question",
};

export function bigFact(e: AiEngine): string {
  if (e.status !== "available" || e.fact_value === null || e.fact_value === undefined) return "—";
  if (typeof e.fact_value === "string") return e.fact_value;
  return formatWithUnit(e.fact_value, e.unit ?? "");
}

/** Where each engine's proof lives; the target is a stored run on the seeded watercourse. */
export function useAiProof() {
  const navigate = useNavigate();
  const set = useUI((s) => s.set);
  const h = useHeadline();
  const base = h.data ? `/p/${encodeURIComponent(h.data.pilot_id)}/${encodeURIComponent(h.data.pilot_version)}` : null;
  const runP = h.data?.plans.P.run_id ?? null;
  return (e: AiEngine) => {
    if (!base) return null;
    return () => {
      const run = e.id === "plans" && e.evidence_ref?.startsWith("run_") ? e.evidence_ref : runP;
      const qs = run ? `?run=${encodeURIComponent(run)}` : "";
      if (e.id === "sees") {
        set({ showRawFields: true });
        navigate(`${base}/workspace${qs}`);
      } else if (e.id === "predicts") navigate(`${base}/explore?tab=surrogate${run ? `&run=${encodeURIComponent(run)}` : ""}`);
      else if (e.id === "plans") navigate(`${base}/workspace${qs}`);
      else {
        set({ assistantOpen: true });
        navigate(`${base}/workspace${qs}`);
      }
    };
  };
}

export function AiStackStrip({ compact = false, className, onPick }: { compact?: boolean; className?: string; onPick?: () => void }) {
  const q = useAiStack();
  const proof = useAiProof();
  if (q.isLoading) return <Skeleton className={cn("h-[150px] rounded-[20px]", className)} />;
  if (q.error || !q.data) return null;
  return (
    <ul className={cn("grid gap-3", compact ? "grid-cols-1" : "sm:grid-cols-2 lg:grid-cols-4", className)} data-testid="ai-stack" aria-label="How the AI works">
      {q.data.engines.map((e) => {
        const go = proof(e);
        const body = (
          <>
            <span className="flex items-center gap-2.5">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[11px] bg-water-soft text-water-deep" aria-hidden>
                {ICON[e.id]}
              </span>
              <span className="text-[15px] font-semibold text-ink">{e.label}</span>
              {e.status !== "available" ? <span className="ml-auto rounded-full bg-warning-soft px-2 py-0.5 text-[11px] font-medium text-warning">unavailable</span> : null}
            </span>
            <span className="text-[13px] leading-snug text-ink-secondary">{e.plain}</span>
            {e.status === "available" ? (
              <span className="mt-auto flex flex-col">
                <span className={cn("display-num leading-none text-ink", compact ? "text-[22px]" : "text-[30px]")} data-testid={`ai-fact-${e.id}`}>
                  {bigFact(e)}
                </span>
                <span className="mt-1 text-[12px] text-ink-tertiary">{e.fact}</span>
              </span>
            ) : (
              <span className="mt-auto text-[12px] text-warning">{e.reason}</span>
            )}
            {go ? (
              <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-water-deep">
                {PROOF[e.id]} <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
              </span>
            ) : null}
          </>
        );
        const cls = "group flex h-full w-full flex-col gap-2.5 rounded-[18px] border border-border bg-surface p-4 text-left shadow-1";
        return (
          <li key={e.id} data-engine={e.id}>
            {go ? (
              <button type="button" onClick={() => { go(); onPick?.(); }} className={cn(cls, "transition-[box-shadow,border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-water/35 hover:shadow-2")} data-testid={`ai-link-${e.id}`}>
                {body}
              </button>
            ) : (
              <div className={cls}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
