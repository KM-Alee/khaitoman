/**
 * Conversation state (one conversation per pilot key). Turns stream over SSE (stream.ts);
 * the authoritative turn row is re-read when a turn ends. State lives outside React so a
 * running turn survives the panel closing. Only the session id is remembered in
 * sessionStorage; the transcript is restored from the API.
 */
import { create } from "zustand";
import { ApiError, describeError } from "@/lib/api/client";
import { copilotApi, type SessionDetail, type TurnAccepted } from "./api";
import { openTurnStream, type StreamState, type TurnStream } from "./stream";
import {
  isTerminalTurn,
  type AnswerBlock,
  type CopilotAnswer,
  type CopilotEventEnvelope,
  type CopilotLanguage,
  type CreatedRef,
  type DatasetDescriptor,
  type JobUpdatePayload,
  type PinnedContextView,
  type TurnError,
  type TurnStatus,
  type TurnViewRow,
  type UIContext,
  type ViewIntent,
} from "./types";

export interface Step {
  callId: string;
  tool: string;
  label: string;
  semantics: string | null;
  state: "running" | "ok" | "failed";
  error: TurnError | null;
  durationMs: number | null;
  datasets: number;
  reused: boolean;
}

export type LiveStatus = TurnStatus | "sending" | "rejected" | "cancelling";

export interface LiveTurn {
  /** Local key; equals turnId once the server accepted the message. */
  key: string;
  turnId: string | null;
  message: string;
  status: LiveStatus;
  language: CopilotLanguage | null;
  context: PinnedContextView | null;
  thinking: { round: number; label: string } | null;
  steps: Step[];
  datasets: DatasetDescriptor[];
  /** Validated blocks as they arrive (answer_block); replaced by the full answer. */
  partial: AnswerBlock[];
  answer: CopilotAnswer | null;
  viewIntents: ViewIntent[];
  created: CreatedRef[];
  error: TurnError | null;
  requestError: { title: string; detail: string } | null;
  rounds: number | null;
  latencyMs: number | null;
  providerMs: number | null;
  pendingJobIds: string[];
  jobUpdates: JobUpdatePayload[];
  jobsSettled: boolean;
  lastEventId: number;
  stream: StreamState | null;
  /** Streamed in this tab (view intents apply once); false for restored turns. */
  live: boolean;
  intentsApplied: boolean;
  retryOf: string | null;
  startedAt: number;
}

export interface Conversation {
  sessionId: string | null;
  turns: LiveTurn[];
  restoring: boolean;
  restoreNote: string | null;
}

interface ConvStore {
  byPilot: Record<string, Conversation>;
}

const empty = (): Conversation => ({ sessionId: null, turns: [], restoring: false, restoreNote: null });
const EMPTY = empty();

export const useConversationStore = create<ConvStore>(() => ({ byPilot: {} }));

export function useConversation(pilotKey: string): Conversation {
  return useConversationStore((s) => s.byPilot[pilotKey]) ?? EMPTY;
}

function getConv(pilotKey: string): Conversation {
  return useConversationStore.getState().byPilot[pilotKey] ?? empty();
}
function patchConv(pilotKey: string, p: Partial<Conversation> | ((c: Conversation) => Partial<Conversation>)) {
  useConversationStore.setState((s) => {
    const cur = s.byPilot[pilotKey] ?? empty();
    const next = typeof p === "function" ? p(cur) : p;
    return { byPilot: { ...s.byPilot, [pilotKey]: { ...cur, ...next } } };
  });
}
function patchTurn(pilotKey: string, key: string, f: (t: LiveTurn) => LiveTurn) {
  patchConv(pilotKey, (c) => ({ turns: c.turns.map((t) => (t.key === key ? f(t) : t)) }));
}

export function newTurn(message: string, p: Partial<LiveTurn> = {}): LiveTurn {
  const key = p.turnId ?? `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  return {
    key,
    turnId: null,
    message,
    status: "sending",
    language: null,
    context: null,
    thinking: null,
    steps: [],
    datasets: [],
    partial: [],
    answer: null,
    viewIntents: [],
    created: [],
    error: null,
    requestError: null,
    rounds: null,
    latencyMs: null,
    providerMs: null,
    pendingJobIds: [],
    jobUpdates: [],
    jobsSettled: false,
    lastEventId: 0,
    stream: null,
    live: true,
    intentsApplied: false,
    retryOf: null,
    startedAt: Date.now(),
    ...p,
  };
}

export const isBusy = (t: LiveTurn) => t.status === "sending" || t.status === "running" || t.status === "cancelling";

/* ------------------------------------------------------------------ pure reducer */

export function applyEvent(t: LiveTurn, ev: CopilotEventEnvelope): LiveTurn {
  if (ev.event_id && ev.event_id <= t.lastEventId) return t; // replayed after a reconnect
  const n: LiveTurn = { ...t, lastEventId: Math.max(t.lastEventId, ev.event_id ?? 0) };
  switch (ev.type) {
    case "turn_started":
      return {
        ...n,
        context: ev.payload.context ?? n.context,
        language: ev.payload.language ?? ev.payload.context?.language ?? n.language,
        status: n.status === "cancelling" ? n.status : "running",
      };
    case "thinking":
      return { ...n, thinking: { round: ev.payload.round, label: ev.payload.label } };
    case "tool_started": {
      const s: Step = {
        callId: ev.payload.call_id,
        tool: ev.payload.tool,
        label: ev.payload.activity,
        semantics: ev.payload.semantics ?? null,
        state: "running",
        error: null,
        durationMs: null,
        datasets: 0,
        reused: false,
      };
      return { ...n, steps: [...n.steps.filter((x) => x.callId !== s.callId), s] };
    }
    case "dataset_ready":
      return { ...n, datasets: [...n.datasets.filter((d) => d.dataset_id !== ev.payload.dataset_id), ev.payload] };
    case "tool_finished": {
      const p = ev.payload;
      const prev = n.steps.find((x) => x.callId === p.call_id);
      const s: Step = {
        callId: p.call_id,
        tool: p.tool,
        label: p.activity ?? prev?.label ?? p.tool,
        semantics: prev?.semantics ?? null,
        state: p.ok ? "ok" : "failed",
        error: p.error ?? null,
        durationMs: p.duration_ms ?? null,
        datasets: p.datasets?.length ?? 0,
        reused: !!p.reused,
      };
      return {
        ...n,
        steps: prev ? n.steps.map((x) => (x.callId === p.call_id ? s : x)) : [...n.steps, s],
        created: p.created ?? n.created,
      };
    }
    case "answer_block": {
      const blocks = [...n.partial];
      blocks[ev.payload.index] = ev.payload.block;
      return { ...n, partial: blocks, thinking: null };
    }
    case "answer":
      return { ...n, answer: ev.payload, partial: [], thinking: null, language: ev.payload.language };
    case "view_intents":
      return { ...n, viewIntents: ev.payload.intents ?? [] };
    case "error":
      return { ...n, error: ev.payload };
    case "turn_finished": {
      const p = ev.payload;
      const pending = p.pending_job_ids ?? [];
      return {
        ...n,
        status: p.status,
        thinking: null,
        rounds: p.rounds ?? n.rounds,
        latencyMs: p.latency_ms ?? n.latencyMs,
        providerMs: p.provider_ms ?? n.providerMs,
        pendingJobIds: pending,
        jobsSettled: !pending.length,
        error: p.error ?? n.error,
        steps: n.steps.map((s) => (s.state === "running" ? { ...s, state: "failed" as const } : s)),
      };
    }
    case "job_update": {
      const jobs = n.jobUpdates.filter((j) => j.job_id !== ev.payload.job_id);
      return { ...n, jobUpdates: [...jobs, ev.payload], pendingJobIds: n.pendingJobIds.filter((id) => id !== ev.payload.job_id) };
    }
    case "jobs_settled":
      return { ...n, jobsSettled: true, pendingJobIds: ev.payload.pending_job_ids ?? [] };
    case "jobs_cancelled":
      return { ...n, jobsSettled: true, pendingJobIds: [] };
    case "plan_step": // plan-mode grouping/map hints; the planner screen reads them (features/planner)
      return n;
    default: {
      const never: never = ev;
      return never;
    }
  }
}

type RowLike = Partial<TurnViewRow> & Pick<TurnViewRow, "turn_id" | "status" | "user_message">;

/** Merge the authoritative turn row (GET /turns/{id} or a session row) into a turn. */
export function mergeRow(t: LiveTurn, d: RowLike): LiveTurn {
  return {
    ...t,
    turnId: d.turn_id,
    message: d.user_message ?? t.message,
    status: t.status === "cancelling" && d.status === "running" ? "cancelling" : d.status,
    language: (d.language as CopilotLanguage | null | undefined) ?? d.answer?.language ?? t.language,
    answer: d.answer ?? t.answer,
    partial: d.answer ? [] : t.partial,
    viewIntents: d.view_intents?.length ? (d.view_intents as unknown as ViewIntent[]) : t.viewIntents,
    created: d.created_refs?.length ? d.created_refs : t.created,
    error: (d.error as TurnError | null | undefined) ?? t.error,
    rounds: typeof d.rounds === "number" ? d.rounds : t.rounds,
    latencyMs: typeof d.latency_ms === "number" ? d.latency_ms : t.latencyMs,
    context: d.context ? ({ ...(t.context ?? {}), ...(d.context as unknown as PinnedContextView) } as PinnedContextView) : t.context,
  };
}

/* ------------------------------------------------------------------ streaming */

const streams = new Map<string, TurnStream>();

function findTurn(pilotKey: string, turnId: string): LiveTurn | undefined {
  return getConv(pilotKey).turns.find((t) => t.turnId === turnId);
}

async function refreshTurn(pilotKey: string, turnId: string) {
  try {
    const d = await copilotApi.getTurn(turnId);
    const t = findTurn(pilotKey, turnId);
    if (t) patchTurn(pilotKey, t.key, (x) => mergeRow(x, d));
  } catch {
    /* keep the streamed state */
  }
}

export function follow(pilotKey: string, turnId: string, after = 0) {
  if (streams.has(turnId)) return;
  const s = openTurnStream({
    turnId,
    after,
    onEvent: (ev) => {
      const t = findTurn(pilotKey, turnId);
      if (!t) return;
      patchTurn(pilotKey, t.key, (x) => applyEvent(x, ev));
      if (ev.type === "turn_finished") void refreshTurn(pilotKey, turnId);
    },
    onState: (state) => {
      const t = findTurn(pilotKey, turnId);
      if (t) patchTurn(pilotKey, t.key, (x) => ({ ...x, stream: state }));
      if (state === "closed") streams.delete(turnId);
    },
  });
  streams.set(turnId, s);
}

function stopStream(turnId: string) {
  streams.get(turnId)?.close();
  streams.delete(turnId);
}

/* ------------------------------------------------------------------ sessions */

const storageKey = (pilotKey: string) => `aabflow-copilot-session:${pilotKey}`;
function rememberSession(pilotKey: string, id: string | null) {
  try {
    if (id) sessionStorage.setItem(storageKey(pilotKey), id);
    else sessionStorage.removeItem(storageKey(pilotKey));
  } catch {
    /* storage unavailable: the conversation won't survive a reload */
  }
}
function recallSession(pilotKey: string): string | null {
  try {
    return sessionStorage.getItem(storageKey(pilotKey));
  } catch {
    return null;
  }
}

export function turnsFromSession(s: SessionDetail): LiveTurn[] {
  return s.turns.map((row) =>
    mergeRow(newTurn(row.user_message, { turnId: row.turn_id, key: row.turn_id, live: false, intentsApplied: true, status: row.status }), row as RowLike),
  );
}

/** Load a stored conversation (history menu or this tab's last session). */
export async function openSession(pilotKey: string, sessionId: string) {
  for (const t of getConv(pilotKey).turns) if (t.turnId) stopStream(t.turnId);
  patchConv(pilotKey, { restoring: true, restoreNote: null });
  try {
    const s = await copilotApi.getSession(sessionId);
    const turns = turnsFromSession(s);
    patchConv(pilotKey, { sessionId: s.session_id, turns, restoring: false });
    rememberSession(pilotKey, s.session_id);
    for (const t of turns) if (t.status === "running" && t.turnId) follow(pilotKey, t.turnId);
  } catch (e) {
    rememberSession(pilotKey, null);
    patchConv(pilotKey, {
      ...empty(),
      restoreNote:
        e instanceof ApiError && e.status === 404
          ? "That conversation is no longer on the server. Ask a new question to start again."
          : describeError(e).detail,
    });
  }
}

/** Restore this tab's conversation for the pilot (once). */
export async function restore(pilotKey: string) {
  const c = getConv(pilotKey);
  if (c.sessionId || c.restoring || c.turns.length) return;
  const id = recallSession(pilotKey);
  if (id) await openSession(pilotKey, id);
}

async function ensureSession(pilotKey: string, context: UIContext, force = false): Promise<string> {
  const cur = getConv(pilotKey).sessionId;
  if (cur && !force) return cur;
  const s = await copilotApi.createSession(context);
  patchConv(pilotKey, { sessionId: s.session_id });
  rememberSession(pilotKey, s.session_id);
  return s.session_id;
}

function accept(pilotKey: string, key: string, a: TurnAccepted) {
  patchConv(pilotKey, (c) => ({
    turns: c.turns.map((t) => (t.key === key ? { ...t, turnId: a.turn_id, status: "running" as const, context: a.context } : t)),
  }));
  follow(pilotKey, a.turn_id);
}

function errorOf(e: unknown): TurnError | null {
  if (e instanceof ApiError) return { code: e.code, detail: e.message, retryable: e.status >= 500 || e.status === 0 || e.status === 409 };
  return null;
}

export async function send(pilotKey: string, message: string, context: UIContext) {
  const t = newTurn(message, { language: context.language ?? null });
  patchConv(pilotKey, (c) => ({ turns: [...c.turns, t], restoreNote: null }));
  try {
    let sid = await ensureSession(pilotKey, context);
    let a: TurnAccepted;
    try {
      a = await copilotApi.postMessage(sid, message, context);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        sid = await ensureSession(pilotKey, context, true); // the server lost the session (DB reset)
        a = await copilotApi.postMessage(sid, message, context);
      } else throw e;
    }
    accept(pilotKey, t.key, a);
  } catch (e) {
    patchTurn(pilotKey, t.key, (x) => ({ ...x, status: "rejected", requestError: describeError(e), error: errorOf(e) }));
  }
}

export async function retry(pilotKey: string, turn: LiveTurn, context: UIContext) {
  if (!turn.turnId) {
    patchConv(pilotKey, (c) => ({ turns: c.turns.filter((x) => x.key !== turn.key) }));
    return send(pilotKey, turn.message, context);
  }
  const t = newTurn(turn.message, { retryOf: turn.turnId, language: turn.language });
  patchConv(pilotKey, (c) => ({ turns: [...c.turns, t] }));
  try {
    accept(pilotKey, t.key, await copilotApi.retryTurn(turn.turnId));
  } catch (e) {
    patchTurn(pilotKey, t.key, (x) => ({ ...x, status: "rejected", requestError: describeError(e), error: errorOf(e) }));
  }
}

export async function cancel(pilotKey: string, turn: LiveTurn) {
  if (!turn.turnId) return;
  patchTurn(pilotKey, turn.key, (x) => ({ ...x, status: "cancelling" }));
  try {
    const r = await copilotApi.cancelTurn(turn.turnId);
    if (!r.cancel_requested) await refreshTurn(pilotKey, turn.turnId);
  } catch (e) {
    patchTurn(pilotKey, turn.key, (x) => ({ ...x, status: x.status === "cancelling" ? "running" : x.status, requestError: describeError(e) }));
  }
}

export function markIntentsApplied(pilotKey: string, key: string) {
  patchTurn(pilotKey, key, (x) => ({ ...x, intentsApplied: true }));
}

/** Start a new conversation (the server keeps the old one; it stays in History). */
export function reset(pilotKey: string) {
  for (const t of getConv(pilotKey).turns) if (t.turnId) stopStream(t.turnId);
  rememberSession(pilotKey, null);
  patchConv(pilotKey, empty());
}

export const isFinished = (t: LiveTurn) => isTerminalTurn(t.status);

/** Test hook. */
export function __resetConversations() {
  for (const id of [...streams.keys()]) stopStream(id);
  useConversationStore.setState({ byPilot: {} });
}
