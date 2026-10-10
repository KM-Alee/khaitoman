/**
 * "Plan my season" state (docs/COPILOT.md §12): a pure reducer over the copilot's turn events.
 *
 * The answer, status, errors and tool steps come from the copilot's own reducer (`applyEvent`,
 * reused, not forked). On top of it this adds what the planner screen needs: the server's
 * `plan_step` phase of every tool call (understand → test → decide), the newest run a step made
 * (shown on the map) and the fields a step named (highlighted). Nothing here computes a metric.
 */
import { applyEvent, newTurn, type LiveTurn, type Step } from "@/features/copilot/conversation";
import type { AnswerBlock, CopilotEventEnvelope, PlanPhase, PlanStepPayload, TurnError } from "@/features/copilot/types";
import { formatDateTime } from "@/lib/formatting";

export const PHASES: readonly { id: PlanPhase; title: string }[] = [
  { id: "understand", title: "Understanding your goal" },
  { id: "test", title: "Testing it" },
  { id: "decide", title: "Deciding" },
];

/**
 * Phase shown while a tool is still running (the server's `plan_step` replaces it when the call
 * finishes). Mirrors the server's grouping in `orchestrator.plan_phase`.
 */
const TEST_TOOLS = new Set(["build_frontier", "run_stress_test", "evaluate_alternative", "equity", "analyze_sensitivity", "analyze_synergy", "impact_sdg", "preview_policy"]);
const DECIDE_TOOLS = new Set(["create_report", "action_plan", "navigate_view"]);
export function provisionalPhase(tool: string): PlanPhase {
  if (DECIDE_TOOLS.has(tool)) return "decide";
  if (TEST_TOOLS.has(tool)) return "test";
  return "understand";
}

export interface PlanState {
  turn: LiveTurn;
  /** call_id → phase reported by the server's plan_step. */
  phaseByCall: Record<string, PlanPhase>;
  planSteps: PlanStepPayload[];
  /** Newest run a step created (the map shows it); null until one arrives. */
  mapRunId: string | null;
  /** Fields the latest step that named any (equity losers, targets) is about. */
  highlight: string[] | null;
}

export function initPlan(goal: string, turnId: string | null = null): PlanState {
  return {
    turn: newTurn(goal, turnId ? { turnId, key: turnId, status: "running" } : {}),
    phaseByCall: {},
    planSteps: [],
    mapRunId: null,
    highlight: null,
  };
}

export function reducePlan(s: PlanState, ev: CopilotEventEnvelope): PlanState {
  const turn = applyEvent(s.turn, ev);
  if (turn === s.turn) return s; // already applied (replayed after a reconnect)
  if (ev.type !== "plan_step") return { ...s, turn };
  const p = ev.payload;
  return {
    turn,
    phaseByCall: { ...s.phaseByCall, [p.call_id]: p.phase },
    planSteps: [...s.planSteps.filter((x) => x.call_id !== p.call_id), p],
    mapRunId: p.run_id ?? s.mapRunId,
    highlight: p.field_ids?.length ? p.field_ids : s.highlight,
  };
}

export interface TimelineRow {
  callId: string;
  tool: string;
  label: string;
  phase: PlanPhase;
  state: Step["state"];
  durationMs: number | null;
  error: TurnError | null;
  reused: boolean;
}

export interface TimelineGroup {
  phase: PlanPhase;
  title: string;
  rows: TimelineRow[];
  state: "waiting" | "running" | "done" | "failed";
}

/** Tool steps grouped under the three phase headings, in the order they happened. */
export function timelineGroups(s: PlanState): TimelineGroup[] {
  const rows: TimelineRow[] = s.turn.steps.map((st) => ({
    callId: st.callId,
    tool: st.tool,
    label: st.label,
    phase: s.phaseByCall[st.callId] ?? provisionalPhase(st.tool),
    state: st.state,
    durationMs: st.durationMs,
    error: st.error,
    reused: st.reused,
  }));
  return PHASES.map(({ id, title }) => {
    const mine = rows.filter((r) => r.phase === id);
    const state: TimelineGroup["state"] = !mine.length
      ? "waiting"
      : mine.some((r) => r.state === "running")
        ? "running"
        : mine.every((r) => r.state === "failed")
          ? "failed"
          : "done";
    return { phase: id, title, rows: mine, state };
  });
}

/** The answer blocks to show: the final answer, else the validated blocks streamed so far. */
export function briefBlocks(s: PlanState): AnswerBlock[] {
  return s.turn.answer?.blocks ?? s.turn.partial.filter(Boolean);
}

/**
 * The run the brief recommends: the first "open run" action, else the first run the turn
 * created (run badge), else the run the turn was pinned to. Only server IDs, never inferred.
 */
export function recommendedRunId(s: PlanState): string | null {
  const blocks = briefBlocks(s);
  const action = blocks.find((b) => b.type === "action" && b.action === "open_run");
  if (action && action.type === "action") return action.ref_id;
  const created = blocks.find((b) => b.type === "run_badge" && b.role === "created");
  if (created && created.type === "run_badge") return created.run_id;
  const ctxBadge = blocks.find((b) => b.type === "run_badge");
  if (ctxBadge && ctxBadge.type === "run_badge") return ctxBadge.run_id;
  return s.turn.context?.selected_run_id ?? null;
}

/* ------------------------------------------------------------------ saved vs live */

export type PlanSource = { kind: "saved"; turnId: string; computedAt: string | null } | { kind: "live" };

/** The provenance line above the investigation (UI_SYSTEM §5 "saved" state). */
export function sourceLabel(src: PlanSource): string {
  if (src.kind === "live") return "Live investigation";
  return `Saved investigation · computed ${src.computedAt ? formatDateTime(src.computedAt) : "time unknown"}`;
}

/**
 * Replay schedule for a stored event log: cumulative delays (ms) at `speed`× the server's
 * own timing, each gap capped so a long job does not stall the replay. Reduced motion → instant.
 */
export function replayDelays(events: Pick<CopilotEventEnvelope, "created_at">[], opts: { speed?: number; capMs?: number; reduced?: boolean } = {}): number[] {
  const speed = opts.speed ?? 3;
  const cap = opts.capMs ?? 3000;
  let acc = 0;
  let prev: number | null = null;
  return events.map((e) => {
    const t = Date.parse(e.created_at);
    if (!opts.reduced && prev !== null && Number.isFinite(t)) acc += Math.min(cap, Math.max(0, (t - prev) / speed));
    if (Number.isFinite(t)) prev = t;
    return opts.reduced ? 0 : Math.round(acc);
  });
}

/* ------------------------------------------------------------------ routes */

/** `/p/:pilot/:version/plan-season?turn=&goal=` */
export function planSeasonHref(pilotId: string, version: string, p: { turn?: string | null; goal?: string | null } = {}): string {
  const q = new URLSearchParams();
  if (p.turn) q.set("turn", p.turn);
  if (p.goal) q.set("goal", p.goal);
  const qs = q.toString();
  return `/p/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/plan-season${qs ? `?${qs}` : ""}`;
}

/** Example goals for the landing card (budget / fairness / dry year). */
export const EXAMPLE_GOALS: readonly { id: "budget" | "fairness" | "dry"; label: string; goal: string }[] = [
  { id: "budget", label: "₨10 lakh budget", goal: "We have ₨10 lakh. What is the best plan for this season?" },
  { id: "fairness", label: "Protect the tail", goal: "Don't hurt the tail farmers. What should we build and how should water be shared?" },
  {
    id: "dry",
    label: "Survive a dry year",
    goal: "We have ₨10 lakh. Don't hurt the tail farmers, and make sure it survives a dry year.",
  },
];
