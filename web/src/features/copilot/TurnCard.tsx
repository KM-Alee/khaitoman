/**
 * One question and its answer: the visitor's message, live tool progress with plain labels,
 * validated blocks as they arrive, honest failure states with retry, and jobs that finish
 * after the turn. Every value shown comes from the server.
 */
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Ban, CheckCircle2, ChevronDown, CircleHelp, Clock, Loader2, RotateCcw, ServerCrash, ShieldCheck, Sparkles, Square, WifiOff, XCircle } from "lucide-react";
import { Chip } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { formatDuration } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { AnswerView, type BlockContext } from "./blocks";
import { isBusy, type LiveTurn, type Step } from "./conversation";
import { VisualCard } from "./visual";
import type { AnswerBlock } from "./types";

/* ------------------------------------------------------------------ progress */

function StepIcon({ s }: { s: Step["state"] }) {
  if (s === "running") return <Loader2 size={13} aria-hidden className="text-water [animation:spin_1s_linear_infinite]" />;
  if (s === "ok") return <CheckCircle2 size={13} aria-hidden className="text-vegetation" />;
  return <XCircle size={13} aria-hidden className="text-danger" />;
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="num">{Math.max(0, Math.round((now - since) / 1000))} s</span>;
}

export function Progress({ t }: { t: LiveTurn }) {
  const busy = isBusy(t);
  const [open, setOpen] = useState(false);
  const failed = t.steps.filter((s) => s.state === "failed").length;
  if (!busy && !t.steps.length) return null;
  if (!busy) {
    return (
      <div className="text-[11.5px] text-ink-tertiary">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 hover:text-ink-secondary">
          <ShieldCheck size={12} aria-hidden />
          Checked {t.steps.length} {t.steps.length === 1 ? "source" : "sources"}
          {failed ? ` · ${failed} failed` : ""}
          {t.latencyMs ? ` · ${formatDuration(t.latencyMs)}` : ""}
          <ChevronDown size={12} aria-hidden className={cn("transition-transform", open && "rotate-180")} />
        </button>
        {open ? <StepList steps={t.steps} /> : null}
      </div>
    );
  }
  return (
    <div className="rounded-[14px] border border-water/20 bg-water-soft/40 px-3 py-2.5" role="status" aria-live="polite" data-testid="copilot-progress">
      <StepList steps={t.steps} />
      <p className="mt-1 flex items-center gap-2 text-[12.5px] font-medium text-water-deep">
        <span className="flex gap-0.5" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-water" style={{ animationDelay: `${i * 160}ms` }} />
          ))}
        </span>
        {t.status === "sending" ? "Sending your question" : t.status === "cancelling" ? "Stopping" : (t.thinking?.label ?? "Getting started")}
        <span className="ml-auto text-[11.5px] font-normal text-ink-tertiary">
          <Elapsed since={t.startedAt} />
        </span>
      </p>
      {t.stream === "reconnecting" || t.stream === "polling" ? (
        <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-ink-tertiary">
          <WifiOff size={11} aria-hidden /> Live updates interrupted; catching up from the server
        </p>
      ) : null}
    </div>
  );
}

function StepList({ steps }: { steps: Step[] }) {
  if (!steps.length) return null;
  return (
    <ol className="mb-1.5 flex flex-col gap-1" data-testid="copilot-steps-progress">
      {steps.map((s) => (
        <li key={s.callId} className="flex items-start gap-2 text-[12.5px] animate-rise" data-tool={s.tool} data-state={s.state}>
          <span className="mt-0.5 shrink-0">
            <StepIcon s={s.state} />
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn(s.state === "failed" ? "text-danger" : "text-ink")}>{s.label}</span>
            {s.state === "failed" && s.error ? <span className="block text-[11.5px] text-ink-secondary">{plainToolError(s.error.code, s.error.detail)}</span> : null}
          </span>
          {s.durationMs !== null && s.state !== "running" ? <span className="num shrink-0 text-[11px] text-ink-tertiary">{formatDuration(s.durationMs)}</span> : null}
        </li>
      ))}
    </ol>
  );
}

export function plainToolError(code: string, detail?: string): string {
  switch (code) {
    case "NOT_FOUND":
      return `Not found${detail ? `: ${detail}` : ""}`;
    case "CROSS_PILOT_REFERENCE":
      return "That belongs to another watercourse, so it can't be used here.";
    case "NO_PLAN":
      return "That run has no valid plan, so there is nothing to show for it.";
    case "TOOL_TIMEOUT":
      return "This step took too long; anything it started keeps running.";
    case "TURN_JOB_LIMIT":
      return "Too many new calculations for one question.";
    case "NEEDS_CLARIFICATION":
      return "The amount or unit was unclear.";
    case "CAPABILITY_UNAVAILABLE":
      return "This build cannot do that yet.";
    default:
      return detail ?? code;
  }
}

/* ------------------------------------------------------------------ terminal states */

function StateNote({ t, onRetry }: { t: LiveTurn; onRetry?: () => void }) {
  const retry = onRetry ? (
    <Button size="sm" variant="secondary" onClick={onRetry}>
      <RotateCcw size={13} aria-hidden /> Try again
    </Button>
  ) : null;
  const box = (icon: ReactNode, title: string, body: string, tone: "warning" | "danger" | "neutral") => (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex flex-col gap-2 rounded-[14px] border px-3 py-2.5",
        tone === "danger" ? "border-danger/30 bg-danger-soft/40" : tone === "warning" ? "border-warning/30 bg-warning-soft/50" : "border-border bg-surface-muted",
      )}
      data-testid="copilot-turn-state"
      data-status={t.status}
    >
      <p className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
        {icon} {title}
      </p>
      <p className="text-[12.5px] leading-snug text-ink-secondary">{body}</p>
      {retry ? <div>{retry}</div> : null}
    </div>
  );
  switch (t.status) {
    case "rejected":
      return box(<XCircle size={14} aria-hidden className="text-danger" />, t.requestError?.title ?? "Not sent", t.requestError?.detail ?? "The question did not reach the server.", "danger");
    case "provider_unavailable":
      return box(
        <WifiOff size={14} aria-hidden className="text-warning" />,
        "The assistant couldn't be reached",
        `${t.error?.detail ?? "The hosted model did not answer."} Nothing was made up; saved results, the map and all controls still work.`,
        "warning",
      );
    case "budget_exhausted":
      return box(
        <Clock size={14} aria-hidden className="text-warning" />,
        "This took longer than the 90-second limit",
        "The answer was stopped so it would not guess. Anything below came straight from the tools. Ask again, or ask a narrower question.",
        "warning",
      );
    case "failed":
      return box(
        <ServerCrash size={14} aria-hidden className="text-danger" />,
        t.error?.code === "INTERRUPTED" ? "The server restarted during this question" : "Something went wrong with this answer",
        t.error?.code === "ANSWER_INVALID" ? "The assistant's reply did not pass the app's checks, so it was not shown." : (t.error?.detail ?? "No answer was produced."),
        "danger",
      );
    case "cancelled":
      return box(<Ban size={14} aria-hidden />, "Stopped", "You stopped this question. Any calculation it started was cancelled.", "neutral");
    default:
      return null;
  }
}

/* ------------------------------------------------------------------ turn */

export function TurnCard({ t, ctx, onRetry, onStop, latest }: { t: LiveTurn; ctx: BlockContext; onRetry?: () => void; onStop?: () => void; latest: boolean }) {
  const busy = isBusy(t);
  const blocks: AnswerBlock[] = t.answer?.blocks ?? t.partial.filter(Boolean);
  const lang = t.answer?.language ?? t.language ?? ctx.lang;
  const canRetry = ["rejected", "provider_unavailable", "budget_exhausted", "failed", "cancelled"].includes(t.status);
  const jobVisuals = t.jobUpdates.flatMap((j) => j.visuals ?? []);
  return (
    <article className="flex flex-col gap-3" aria-label={`Question: ${t.message}`} data-testid="copilot-turn" data-status={t.status}>
      <div className="flex justify-end">
        <p className="max-w-[88%] whitespace-pre-line rounded-[16px] rounded-br-[6px] bg-water px-3.5 py-2 text-[13.5px] leading-relaxed text-on-water shadow-1" dir="auto" data-testid="copilot-question">
          {t.message}
        </p>
      </div>
      <div className="flex gap-2.5">
        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-water-grad text-on-water shadow-1" aria-hidden>
          <Sparkles size={14} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <Progress t={t} />
          {t.answer?.needs_clarification && t.answer.clarification_question ? (
            <div className="rounded-[14px] border border-water/30 bg-water-soft/50 px-3 py-2.5" dir="auto">
              <p className="mb-1 inline-flex items-center gap-1 text-[11.5px] font-semibold text-water-deep">
                <CircleHelp size={12} aria-hidden /> One question first
              </p>
              <p className="text-[13.5px] text-ink">{t.answer.clarification_question}</p>
            </div>
          ) : null}
          {t.answer?.deterministic ? (
            <Chip size="sm" tone="info" icon={<AlertTriangle size={11} aria-hidden />} className="self-start">
              System message, not the assistant
            </Chip>
          ) : null}
          <StateNote t={t} onRetry={canRetry && latest ? onRetry : undefined} />
          {blocks.length ? <AnswerView blocks={blocks} ctx={{ ...ctx, lang, busy: ctx.busy || busy }} /> : null}
          {t.pendingJobIds.length && !t.jobsSettled ? (
            <p className="inline-flex items-center gap-1.5 text-[12px] text-ink-secondary" role="status">
              <Loader2 size={12} aria-hidden className="[animation:spin_1s_linear_infinite]" /> Still calculating in the background; results appear here when ready.
            </p>
          ) : null}
          {jobVisuals.length ? (
            <div className="flex flex-col gap-2">
              <p className="text-[12px] font-medium text-ink-secondary">Finished after the answer</p>
              {jobVisuals.map((v) => (
                <VisualCard key={v.visual_id} b={v} lang={lang} />
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-tertiary">
            {busy && onStop && t.turnId ? (
              <Button size="sm" variant="ghost" onClick={onStop} aria-label="Stop this question">
                <Square size={12} aria-hidden /> Stop
              </Button>
            ) : null}
            {t.answer && !t.answer.deterministic ? (
              t.answer.validated ? (
                <span className="inline-flex items-center gap-1" title="Every number and reference was checked against this turn's tool results">
                  <ShieldCheck size={11} aria-hidden className="text-vegetation" /> Numbers checked against the tool results
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-warning" title={(t.answer.issues ?? []).join("\n")}>
                  <AlertTriangle size={11} aria-hidden /> Some unsupported figures or charts were removed
                </span>
              )
            ) : null}
            {t.retryOf ? <span>Retry of an earlier question</span> : null}
          </div>
        </div>
      </div>
    </article>
  );
}
