/**
 * Drives one "Plan my season" investigation on the planner screen:
 *  - saved: `?turn=` of a finished plan turn → replay its stored event log (3× the server's timing,
 *    instant with reduced motion), labelled "Saved investigation · computed <server time>";
 *  - live: a new copilot session + one plan-mode message, streamed over SSE (features/copilot/stream).
 * A live failure shows its real status and error; the saved result is discarded, never shown instead.
 * State is local to the screen (no shared store).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { describeError, api } from "@/lib/api/client";
import { copilotApi } from "@/features/copilot/api";
import { openTurnStream, type TurnStream } from "@/features/copilot/stream";
import { mergeRow } from "@/features/copilot/conversation";
import { isTerminalTurn, type CopilotEventEnvelope, type TurnViewRow, type UIContext } from "@/features/copilot/types";
import { initPlan, reducePlan, replayDelays, type PlanSource, type PlanState } from "./timeline";

export type PlanPhaseUI = "idle" | "loading" | "replaying" | "running" | "done" | "error";

export interface PlanInvestigation {
  phase: PlanPhaseUI;
  source: PlanSource | null;
  state: PlanState | null;
  goal: string | null;
  sessionId: string | null;
  /** A request that never became a turn (session/message rejected, saved turn missing). */
  requestError: { title: string; detail: string } | null;
  /** Skip the rest of a saved replay. */
  finishReplay: () => void;
  /** Start a new live plan-mode turn with this goal. */
  runLive: (goal: string) => void;
  /** The pinned context a live run uses (the saved turn's, else the URL run, else the demo plan). */
  context: UIContext;
}

interface Args {
  pilotId: string;
  version: string;
  turnId: string | null;
  goal: string | null;
  runId: string | null;
  reducedMotion: boolean;
  /** Called with the new turn id once a live run is accepted (the screen puts it in the URL). */
  onLiveTurn?: (turnId: string) => void;
}

interface DemoPlanContext {
  pilot_id: string;
  pilot_version: string;
  season_id?: string | null;
  base?: { revision_id?: string; runs?: Record<string, string> };
}

export function usePlanInvestigation({ pilotId, version, turnId, goal, runId, reducedMotion, onLiveTurn }: Args): PlanInvestigation {
  const [phase, setPhase] = useState<PlanPhaseUI>(turnId || goal ? "loading" : "idle");
  const [source, setSource] = useState<PlanSource | null>(null);
  const [state, setState] = useState<PlanState | null>(null);
  const [goalText, setGoalText] = useState<string | null>(goal);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<PlanInvestigation["requestError"]>(null);
  const [savedContext, setSavedContext] = useState<UIContext | null>(null);

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const pendingReplay = useRef<CopilotEventEnvelope[]>([]);
  const stream = useRef<TurnStream | null>(null);
  const startedFor = useRef<string | null>(null); // `${turn}|${goal}` the screen already started
  const generation = useRef(0); // bumps on every new investigation; stale callbacks are ignored
  const onLiveRef = useRef(onLiveTurn);
  onLiveRef.current = onLiveTurn;

  const stopAll = useCallback(() => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
    pendingReplay.current = [];
    stream.current?.close();
    stream.current = null;
  }, []);
  useEffect(() => stopAll, [stopAll]);

  const baseContext: UIContext = savedContext ?? { pilot_id: pilotId, pilot_version: version, selected_run_id: runId, view: "plan-season", language: "en" };

  /* ------------------------------------------------------------ live */

  const follow = useCallback((gen: number, tid: string) => {
    stream.current = openTurnStream({
      turnId: tid,
      onEvent: (ev) => {
        if (gen !== generation.current) return;
        setState((s) => (s ? reducePlan(s, ev) : s));
        if (ev.type === "turn_finished") {
          setPhase("done");
          void copilotApi
            .getTurn(tid)
            .then((row) => {
              if (gen === generation.current) setState((s) => (s ? { ...s, turn: mergeRow(s.turn, row) } : s));
            })
            .catch(() => undefined); // keep the streamed state
        }
      },
    });
  }, []);

  const runLive = useCallback(
    (g: string) => {
      const text = g.trim();
      if (!text) return;
      stopAll();
      const gen = ++generation.current;
      setGoalText(text);
      setSource({ kind: "live" });
      setRequestError(null);
      setState(initPlan(text));
      setPhase("running");
      void (async () => {
        try {
          const ctx = await liveContext(savedContext, pilotId, version, runId);
          if (gen !== generation.current) return;
          const s = await copilotApi.createSession(ctx);
          if (gen !== generation.current) return;
          setSessionId(s.session_id);
          const a = await copilotApi.postMessage(s.session_id, text, ctx, "plan");
          if (gen !== generation.current) return;
          setState((st) => (st ? { ...st, turn: { ...st.turn, turnId: a.turn_id, key: a.turn_id, status: "running", context: a.context } } : st));
          startedFor.current = `${a.turn_id}|`; // the URL gets ?turn=<this turn>; it must not restart as a replay
          onLiveRef.current?.(a.turn_id);
          follow(gen, a.turn_id);
        } catch (e) {
          if (gen !== generation.current) return;
          setRequestError(describeError(e));
          setState((st) => (st ? { ...st, turn: { ...st.turn, status: "rejected" } } : st));
          setPhase("error");
        }
      })();
    },
    [follow, pilotId, runId, savedContext, stopAll, version],
  );

  /* ------------------------------------------------------------ saved */

  const finishReplay = useCallback(() => {
    const rest = pendingReplay.current;
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
    pendingReplay.current = [];
    if (rest.length) setState((s) => (s ? rest.reduce(reducePlan, s) : s));
    setPhase((p) => (p === "replaying" ? "done" : p));
  }, []);

  useEffect(() => {
    const key = `${turnId ?? ""}|${goal ?? ""}`;
    if (startedFor.current === key) return;
    startedFor.current = key;
    if (!turnId) {
      if (goal) runLive(goal);
      return;
    }
    stopAll();
    const gen = ++generation.current;
    setPhase("loading");
    void (async () => {
      let row: TurnViewRow;
      try {
        row = await copilotApi.getTurn(turnId);
      } catch (e) {
        if (gen !== generation.current) return;
        setRequestError(describeError(e));
        setPhase("error");
        return;
      }
      if (gen !== generation.current) return;
      const ctx = row.context as Record<string, unknown>;
      setSavedContext({
        pilot_id: (ctx.pilot_id as string) ?? pilotId,
        pilot_version: (ctx.pilot_version as string) ?? version,
        season_id: (ctx.season_id as string) ?? null,
        scenario_revision_id: (ctx.scenario_revision_id as string) ?? null,
        selected_run_id: (ctx.selected_run_id as string) ?? null,
        view: "plan-season",
        language: "en",
      });
      setGoalText(row.user_message);
      setSessionId(row.session_id);
      const base = initPlan(row.user_message, row.turn_id);
      if (!isTerminalTurn(row.status)) {
        // still running (started in another tab): follow it live from the start
        setSource({ kind: "live" });
        setState(base);
        setPhase("running");
        follow(gen, row.turn_id);
        return;
      }
      let events: CopilotEventEnvelope[];
      try {
        events = await copilotApi.eventLog(row.turn_id);
      } catch (e) {
        if (gen !== generation.current) return;
        setRequestError(describeError(e));
        setPhase("error");
        return;
      }
      if (gen !== generation.current) return;
      setSource({ kind: "saved", turnId: row.turn_id, computedAt: row.finished_at ?? null });
      const sorted = [...events].sort((a, b) => a.event_id - b.event_id);
      const finalize = (s: PlanState) => ({ ...s, turn: mergeRow(s.turn, row) });
      const delays = replayDelays(sorted, { reduced: reducedMotion });
      if (reducedMotion || !sorted.length) {
        setState(finalize(sorted.reduce(reducePlan, base)));
        setPhase("done");
        return;
      }
      setState(base);
      setPhase("replaying");
      pendingReplay.current = [...sorted];
      sorted.forEach((ev, i) => {
        timers.current.push(
          setTimeout(() => {
            if (gen !== generation.current) return;
            pendingReplay.current = pendingReplay.current.filter((x) => x.event_id !== ev.event_id);
            setState((s) => (s ? reducePlan(s, ev) : s));
            if (i === sorted.length - 1) {
              setState((s) => (s ? finalize(s) : s));
              setPhase("done");
            }
          }, delays[i]),
        );
      });
    })();
  }, [turnId, goal, reducedMotion, runLive, stopAll, follow, pilotId, version]);

  return {
    phase,
    source,
    state,
    goal: goalText,
    sessionId,
    requestError,
    finishReplay,
    runLive,
    context: baseContext,
  };
}

/** Context for a live run: the saved turn's, else the URL run, else the seeded demo plan's base P run. */
async function liveContext(saved: UIContext | null, pilotId: string, version: string, runId: string | null): Promise<UIContext> {
  const base: UIContext = { pilot_id: pilotId, pilot_version: version, view: "plan-season", language: "en" };
  if (saved) return saved;
  if (runId) return { ...base, selected_run_id: runId };
  try {
    const demo = await api.get<DemoPlanContext>("/demo/session");
    if (demo.pilot_id === pilotId && demo.pilot_version === version) {
      return {
        ...base,
        season_id: demo.season_id ?? null,
        scenario_revision_id: demo.base?.revision_id ?? null,
        selected_run_id: demo.base?.runs?.P ?? null,
      };
    }
  } catch {
    /* no seeded session: the server resolves the pilot's default context */
  }
  return base;
}
