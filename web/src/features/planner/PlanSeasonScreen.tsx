/**
 * "Plan my season" (WIN_PLAN P2, docs/COPILOT.md §12): one sentence → the copilot runs a full
 * planning investigation in plan mode and the screen tells it as a story.
 *
 *   left   the investigation timeline (understand → test → decide)
 *   centre the persistent map, reacting to plan_step events (new run colours, highlighted fields)
 *   right  the decision brief, rendered by the copilot's own block renderer
 *
 * Route `/p/:pilotId/:version/plan-season?turn=<id>&goal=<text>`. A finished `?turn=` is replayed
 * from its stored event log and labelled as saved; "Run it live" posts the same goal as a new
 * plan-mode turn. Every number shown comes from server blocks; this screen computes none.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams, useNavigate } from "react-router";
import { ArrowLeft, FileText, MessageCircle, Play, Printer, Sparkles, StepForward } from "lucide-react";
import { useUI } from "@/app/store";
import { useAppActions } from "@/app/actions";
import { BREAKPOINTS, useMediaQuery, useReducedMotion } from "@/app/environment";
import { MapBinder } from "@/components/map/MapBinder";
import { MapSlot } from "@/components/map/MapSlot";
import { AssistantPanel } from "@/components/layout/AssistantPanel";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { AnswerView } from "@/features/copilot/blocks";
import { openSession, send } from "@/features/copilot/conversation";
import { cn } from "@/lib/cn";
import { PlanSeasonCard } from "./PlanSeasonCard";
import { Timeline } from "./Timeline";
import { briefBlocks, recommendedRunId, sourceLabel, timelineGroups } from "./timeline";
import { usePlanInvestigation } from "./usePlanInvestigation";

const TERMINAL_COPY: Record<string, { tone: "warning" | "danger"; title: string }> = {
  budget_exhausted: { tone: "warning", title: "The investigation reached its time budget; the brief below is partial." },
  provider_unavailable: { tone: "danger", title: "The hosted AI was unavailable, so the investigation could not finish." },
  failed: { tone: "danger", title: "The investigation failed." },
  cancelled: { tone: "warning", title: "The investigation was stopped." },
  clarification: { tone: "warning", title: "The AI needs one detail before it can plan." },
};

export function PlanSeasonScreen() {
  const { pilotId = "", version = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const turnParam = sp.get("turn");
  const goalParam = sp.get("goal");
  const runParam = sp.get("run");
  const reduced = useReducedMotion();
  const wide = !useMediaQuery(BREAKPOINTS.tablet);
  const assistantOpen = useUI((s) => s.assistantOpen);
  const setUI = useUI((s) => s.set);
  const actions = useAppActions();

  const onLiveTurn = useCallback(
    (tid: string) =>
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("turn", tid);
          next.delete("goal");
          return next;
        },
        { replace: true },
      ),
    [setSp],
  );
  const inv = usePlanInvestigation({ pilotId, version, turnId: turnParam, goal: goalParam, runId: runParam, reducedMotion: reduced, onLiveTurn });
  const st = inv.state;
  const turn = st?.turn ?? null;
  const groups = st ? timelineGroups(st) : [];
  const blocks = st ? briefBlocks(st) : [];
  const recommended = st && (inv.phase === "done" || turn?.answer) ? recommendedRunId(st) : null;
  const active = inv.phase === "running" || inv.phase === "replaying";
  const contextRun = turn?.context?.selected_run_id ?? inv.context.selected_run_id ?? runParam ?? null;
  const mapRun = st?.mapRunId ?? recommended ?? contextRun;
  const pilotKey = `${pilotId}@${version}`;
  const terminal = turn && turn.status !== "completed" ? TERMINAL_COPY[turn.status] : undefined;

  useEffect(() => {
    document.title = "Plan my season · AabFlow";
  }, []);

  const [asking, setAsking] = useState(false);
  const askFollowUp = async (q?: string) => {
    setAsking(true);
    try {
      if (inv.sessionId) {
        await openSession(pilotKey, inv.sessionId);
        if (q) await send(pilotKey, q, inv.context);
      }
    } finally {
      setAsking(false);
      actions.openAssistant();
    }
  };
  const reportHref = (print: boolean) => {
    const q = new URLSearchParams();
    if (recommended) q.set("run", recommended);
    if (print) q.set("print", "1");
    return `/p/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/report?${q.toString()}`;
  };

  /* ------------------------------------------------------------ columns */

  const timelineCol = (
    <Card className="flex min-h-0 flex-col" as="section" aria-label="How the AI worked it out">
      <CardHeader eyebrow="Investigation" title="How the AI worked it out" description={turn ? `${turn.steps.length} ${turn.steps.length === 1 ? "step" : "steps"} with the app's real tools` : undefined} />
      <CardBody className="min-h-0 flex-1 overflow-y-auto">
        {st ? (
          <Timeline groups={groups} thinking={turn?.thinking?.label ?? (turn?.status === "sending" ? "Sending your goal" : null)} active={active} />
        ) : (
          <div className="flex flex-col gap-2" aria-busy>
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        )}
      </CardBody>
    </Card>
  );

  const mapCol = (
    <section className={cn("relative overflow-hidden rounded-[18px] border border-border bg-surface-sunken", wide ? "min-h-0" : "h-[52vh] shrink-0")} aria-label="Map">
      <MapSlot
        runId={mapRun}
        className="absolute inset-0"
        label="Map of the watercourse during the investigation"
        highlightFieldIds={st?.highlight ?? null}
        compactControls
      >
        {st?.highlight?.length ? (
          <div className="pointer-events-none absolute left-3 top-3 z-10">
            <Chip tone="water" size="sm">
              {st.highlight.length} {st.highlight.length === 1 ? "field" : "fields"} in focus
            </Chip>
          </div>
        ) : null}
      </MapSlot>
    </section>
  );

  const briefCol = (
    <Card tone={turn?.answer ? "hero" : "default"} className="flex min-h-0 flex-col" as="section" aria-label="Decision brief" data-testid="plan-brief">
      <CardHeader eyebrow="Decision brief" title={turn?.answer ? "What we recommend" : "The brief appears when the investigation finishes"} />
      <CardBody className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-3">
          {terminal && (inv.phase === "done" || !active) ? (
            <StatePanel compact state={terminal.tone === "danger" ? "error" : "blocked"} title={terminal.title}>
              {turn?.error ? `${turn.error.code}${turn.error.detail ? `: ${turn.error.detail}` : ""}` : null}
            </StatePanel>
          ) : null}
          {blocks.length ? (
            <AnswerView blocks={blocks} ctx={{ lang: turn?.answer?.language ?? turn?.language ?? "en", onAsk: (q) => void askFollowUp(q), busy: active || asking }} testId="plan-answer" />
          ) : active ? (
            <div className="flex flex-col gap-2" aria-busy>
              <Skeleton className="h-6 w-4/5" />
              <div className="grid grid-cols-2 gap-2">
                <Skeleton className="h-16" />
                <Skeleton className="h-16" />
              </div>
              <Skeleton className="h-40 w-full" />
            </div>
          ) : null}
          {turn?.answer ? (
            <div className="flex flex-wrap gap-2 border-t border-border pt-3" data-testid="plan-brief-actions">
              <Button size="sm" variant="primary" icon={<FileText size={14} />} disabled={!recommended} onClick={() => void navigate(reportHref(false))} data-testid="plan-open-report">
                Open the action plan
              </Button>
              <Button size="sm" variant="secondary" icon={<Printer size={14} />} disabled={!recommended} onClick={() => void navigate(reportHref(true))} data-testid="plan-print">
                Print brief
              </Button>
              <Button size="sm" variant="secondary" icon={<MessageCircle size={14} />} busy={asking} onClick={() => void askFollowUp()} data-testid="plan-ask">
                Ask a follow-up
              </Button>
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );

  /* ------------------------------------------------------------ page */

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-canvas text-ink" data-testid="plan-season" data-phase={inv.phase}>
      <MapBinder />
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-surface px-4 py-3 md:px-6">
        <Link to={`/p/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/workspace${contextRun ? `?run=${encodeURIComponent(contextRun)}` : ""}`} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-secondary hover:text-ink">
          <ArrowLeft size={15} aria-hidden /> Back to the plan
        </Link>
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-water-grad text-on-water shadow-1" aria-hidden>
            <Sparkles size={16} />
          </span>
          <div className="min-w-0">
            <h1 className="display text-[19px] leading-tight text-ink">Plan my season</h1>
            {inv.goal ? (
              <p className="truncate text-[12.5px] text-ink-secondary" title={inv.goal} data-testid="plan-goal">
                “{inv.goal}”
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {inv.source ? (
            <span data-testid="plan-source" data-kind={inv.source.kind}>
              <Chip tone={inv.source.kind === "saved" ? "wheat" : "water"}>{sourceLabel(inv.source)}</Chip>
            </span>
          ) : null}
          {inv.phase === "replaying" ? (
            <Button size="sm" variant="ghost" icon={<StepForward size={14} />} onClick={inv.finishReplay} data-testid="plan-skip">
              Skip to the end
            </Button>
          ) : null}
          {inv.goal && inv.source?.kind === "saved" && !active ? (
            <Button size="sm" variant="primary" icon={<Play size={14} />} onClick={() => inv.runLive(inv.goal!)} data-testid="plan-run-live">
              Run it live
            </Button>
          ) : null}
        </div>
      </header>

      {inv.phase === "idle" ? (
        <main className="mx-auto flex w-full max-w-[640px] flex-1 flex-col justify-center overflow-y-auto p-4">
          <PlanSeasonCard pilotId={pilotId} version={version} />
        </main>
      ) : inv.requestError && !st?.turn.turnId ? (
        <main className="mx-auto flex w-full max-w-[720px] flex-1 flex-col gap-4 overflow-y-auto p-4 md:p-8">
          <StatePanel state="error" title={inv.requestError.title}>
            {inv.requestError.detail}
          </StatePanel>
          <PlanSeasonCard pilotId={pilotId} version={version} initialGoal={inv.goal ?? ""} title="Try again" />
        </main>
      ) : wide ? (
        <main className="grid min-h-0 flex-1 grid-cols-[minmax(300px,360px)_minmax(0,1fr)_minmax(420px,520px)] gap-4 p-4">
          {timelineCol}
          {mapCol}
          {briefCol}
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          {mapCol}
          {timelineCol}
          {briefCol}
        </main>
      )}

      <Dialog open={assistantOpen} onOpenChange={(o) => setUI({ assistantOpen: o })}>
        <DialogContent title="Ask AabFlow" description="Answers cite the saved runs they come from" side={wide ? "right" : "bottom"} className={wide ? "w-[min(440px,100vw)]" : "h-[90vh]"}>
          <AssistantPanel className="border-0" header={false} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
