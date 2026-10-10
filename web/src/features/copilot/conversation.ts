/**
 * Copilot conversation state. One conversation per pilot key; turns stream over SSE
 * (`/copilot/turns/{id}/events`, resumable with ?after=<event_id>) with a GET poll fallback,
 * and the authoritative turn row is re-read when a turn finishes. Kept outside React so a
 * running turn survives inspector tab switches; the session id (never the transcript) is
 * remembered per tab in sessionStorage so a reload restores the conversation from the API.
 */
import { create } from "zustand";
import { ApiError, describeError } from "@/lib/api/client";
import {
  COPILOT_EVENT_TYPES,
  copilotApi,
  isTerminalTurn,
  type CopilotAnswer,
  type CopilotEventEnvelope,
  type CreatedRef,
  type JobUpdatePayload,
  type PinnedContextView,
  type SessionTurnRow,
  type ToolCallRow,
  type TurnAccepted,
  type TurnDetail,
  type TurnError,
  type TurnStatus,
  type UIContext,
  type ViewIntent,
} from "./api";

export interface ToolActivity {
  callId: string;
  tool: string;
  activity: string;
  semantics: string | null;
  state: "running" | "ok" | "failed";
  error: TurnError | null;
  reused: boolean;
}

export interface LiveTurn {
  /** Local key; equals turnId once the server accepted the message. */
  key: string;
  turnId: string | null;
  message: string;
  /** "sending" until 202; "rejected" when the POST itself failed. */
  status: TurnStatus | "sending" | "rejected" | "cancelling";
  context: PinnedContextView | null;
  activity: ToolActivity[];
  answer: CopilotAnswer | null;
  viewIntents: ViewIntent[];
  created: CreatedRef[];
  jobIds: string[];
  pendingJobIds: string[];
  jobUpdates: JobUpdatePayload[];
  jobsSettled: boolean;
  error: TurnError | null;
  /** Error from a request the client made (POST/cancel/retry), with friendly copy. */
  requestError: { title: string; detail: string } | null;
  rounds: number | null;
  toolCallCount: number | null;
  latencyMs: number | null;
  model: string | null;
  toolCalls: ToolCallRow[] | null;
  lastEventId: number;
  /** Streamed in this tab (view intents apply once); false for turns restored from the API. */
  live: boolean;
  intentsApplied: boolean;
  retryOf: string | null;
  createdAt: number;
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

export const useConversationStore = create<ConvStore>(() => ({ byPilot: {} }));

export function useConversation(pilotKey: string): Conversation {
  return useConversationStore((s) => s.byPilot[pilotKey]) ?? EMPTY;
}
const EMPTY = empty();

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
    context: null,
    activity: [],
    answer: null,
    viewIntents: [],
    created: [],
    jobIds: [],
    pendingJobIds: [],
    jobUpdates: [],
    jobsSettled: false,
    error: null,
    requestError: null,
    rounds: null,
    toolCallCount: null,
    latencyMs: null,
    model: null,
    toolCalls: null,
    lastEventId: 0,
    live: true,
    intentsApplied: false,
    retryOf: null,
    createdAt: Date.now(),
    ...p,
  };
}

/* ------------------------------------------------------------------ pure event reducer (tested) */

export function applyEvent(t: LiveTurn, ev: CopilotEventEnvelope): LiveTurn {
  if (ev.event_id && ev.event_id <= t.lastEventId) return t; // replayed after reconnect
  const n: LiveTurn = { ...t, lastEventId: Math.max(t.lastEventId, ev.event_id ?? 0) };
  switch (ev.type) {
    case "turn_started":
      return { ...n, context: ev.payload.context ?? n.context, status: n.status === "cancelling" ? n.status : "running" };
    case "tool_started": {
      const a: ToolActivity = {
        callId: ev.payload.call_id,
        tool: ev.payload.tool,
        activity: ev.payload.activity,
        semantics: ev.payload.semantics ?? null,
        state: "running",
        error: null,
        reused: false,
      };
      return { ...n, activity: [...n.activity.filter((x) => x.callId !== a.callId), a] };
    }
    case "tool_finished": {
      const p = ev.payload;
      const prev = n.activity.find((x) => x.callId === p.call_id);
      const a: ToolActivity = {
        callId: p.call_id,
        tool: p.tool,
        activity: p.activity ?? prev?.activity ?? p.tool,
        semantics: prev?.semantics ?? null,
        state: p.ok ? "ok" : "failed",
        error: p.error ?? null,
        reused: !!p.reused,
      };
      return {
        ...n,
        activity: prev ? n.activity.map((x) => (x.callId === p.call_id ? a : x)) : [...n.activity, a],
        jobIds: p.job_ids ?? n.jobIds,
        created: p.created ?? n.created,
      };
    }
    case "answer":
      return { ...n, answer: ev.payload };
    case "view_intents":
      return { ...n, viewIntents: ev.payload.intents ?? [] };
    case "error":
      return { ...n, error: ev.payload };
    case "turn_finished": {
      const p = ev.payload;
      return {
        ...n,
        status: p.status,
        rounds: p.rounds ?? n.rounds,
        toolCallCount: p.tool_calls ?? n.toolCallCount,
        latencyMs: p.latency_ms ?? n.latencyMs,
        pendingJobIds: p.pending_job_ids ?? [],
        jobsSettled: !(p.pending_job_ids ?? []).length,
        error: p.error ?? n.error,
        activity: n.activity.map((a) => (a.state === "running" ? { ...a, state: "failed" as const } : a)),
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
    default:
      return n;
  }
}

/** Merge the authoritative turn row (GET /turns/{id}) into a live turn. */
export function mergeDetail(t: LiveTurn, d: TurnDetail | SessionTurnRow): LiveTurn {
  const full = d as TurnDetail;
  let next: LiveTurn = {
    ...t,
    turnId: d.turn_id,
    message: d.user_message ?? t.message,
    status: t.status === "cancelling" && d.status === "running" ? "cancelling" : d.status,
    answer: d.answer ?? t.answer,
    viewIntents: d.view_intents?.length ? d.view_intents : t.viewIntents,
    created: d.created_refs?.length ? d.created_refs : t.created,
    jobIds: d.job_ids?.length ? d.job_ids : t.jobIds,
    error: d.error ?? t.error,
  };
  if (full.context) next.context = { ...(next.context ?? {}), ...pickContext(full.context) } as PinnedContextView;
  if (typeof full.rounds === "number") next.rounds = full.rounds;
  if (typeof full.latency_ms === "number") next.latencyMs = full.latency_ms;
  if (full.model) next.model = full.model;
  if (full.tool_calls) {
    next.toolCalls = full.tool_calls;
    next.toolCallCount = next.toolCallCount ?? full.tool_calls.length;
  }
  // Rebuild activity / job events that were missed (e.g. restored turns).
  if (full.events?.length) for (const ev of full.events) next = applyEvent(next, ev);
  return next;
}

function pickContext(c: TurnDetail["context"]): PinnedContextView {
  const keys = [
    "pilot_id",
    "pilot_version",
    "pilot_name",
    "season_id",
    "crop",
    "scenario_id",
    "scenario_revision_id",
    "selected_run_id",
    "selected_run_plan_kind",
    "selected_run_outcome",
    "selected_field_id",
    "timeline_date",
    "view",
    "language",
    "role",
    "notes",
  ] as const;
  const out: Record<string, unknown> = {};
  for (const k of keys) if (c[k as keyof typeof c] !== null && c[k as keyof typeof c] !== undefined) out[k] = c[k as keyof typeof c];
  return out as unknown as PinnedContextView;
}

/* ------------------------------------------------------------------ streaming */

interface Stream {
  es: EventSource | null;
  timer: ReturnType<typeof setTimeout> | null;
  closed: boolean;
}
const streams = new Map<string, Stream>();

function stopStream(turnId: string) {
  const s = streams.get(turnId);
  if (!s) return;
  s.closed = true;
  s.es?.close();
  if (s.timer) clearTimeout(s.timer);
  streams.delete(turnId);
}

function findTurn(pilotKey: string, turnId: string): LiveTurn | undefined {
  return getConv(pilotKey).turns.find((t) => t.turnId === turnId);
}

async function refreshTurn(pilotKey: string, turnId: string) {
  try {
    const d = await copilotApi.getTurn(turnId, true);
    const t = findTurn(pilotKey, turnId);
    if (t) patchTurn(pilotKey, t.key, (x) => mergeDetail(x, d));
    return d;
  } catch {
    return null;
  }
}

/** Follow a turn: SSE first, GET poll as a fallback; stops after the turn and its jobs settle. */
export function follow(pilotKey: string, turnId: string, eventsUrl?: string) {
  if (streams.has(turnId)) return;
  const s: Stream = { es: null, timer: null, closed: false };
  streams.set(turnId, s);

  const finishIfDone = (t: LiveTurn | undefined) => {
    if (!t) return;
    if (isTerminalTurn(t.status) && (t.jobsSettled || !t.pendingJobIds.length)) {
      stopStream(turnId);
      void refreshTurn(pilotKey, turnId);
    }
  };

  const onEvent = (raw: MessageEvent) => {
    if (s.closed) return;
    let ev: CopilotEventEnvelope;
    try {
      ev = JSON.parse(raw.data) as CopilotEventEnvelope;
    } catch {
      return;
    }
    const t = findTurn(pilotKey, turnId);
    if (!t) return;
    patchTurn(pilotKey, t.key, (x) => applyEvent(x, ev));
    if (ev.type === "turn_finished") void refreshTurn(pilotKey, turnId); // tool trace + authoritative row
    finishIfDone(findTurn(pilotKey, turnId));
  };

  // Poll fallback: also the safety net if SSE is buffered by a proxy.
  let delay = 1500;
  const poll = async () => {
    if (s.closed) return;
    try {
      const d = await copilotApi.getTurn(turnId, true);
      const t = findTurn(pilotKey, turnId);
      if (t) patchTurn(pilotKey, t.key, (x) => mergeDetail(x, d));
      const after = findTurn(pilotKey, turnId);
      if (after && isTerminalTurn(after.status) && !after.pendingJobIds.length) {
        stopStream(turnId);
        return;
      }
      if (after && isTerminalTurn(after.status) && after.jobsSettled) {
        stopStream(turnId);
        return;
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        const t = findTurn(pilotKey, turnId);
        if (t) patchTurn(pilotKey, t.key, (x) => ({ ...x, status: "failed", error: { code: "NOT_FOUND", detail: "The API no longer knows this turn." } }));
        stopStream(turnId);
        return;
      }
    }
    delay = s.es && s.es.readyState === 1 ? 4000 : 1500; // SSE healthy → poll rarely
    s.timer = setTimeout(poll, delay);
  };

  try {
    if (typeof EventSource !== "undefined") {
      const t = findTurn(pilotKey, turnId);
      const url = copilotApi.eventsUrl({ turn_id: turnId, events_url: eventsUrl ?? "" }, t?.lastEventId ?? 0);
      const es = new EventSource(url);
      s.es = es;
      for (const type of COPILOT_EVENT_TYPES) es.addEventListener(type, onEvent as EventListener);
      es.onmessage = onEvent;
      // EventSource reconnects with Last-Event-ID by itself; the poll keeps state fresh meanwhile.
    }
  } catch {
    s.es = null;
  }
  s.timer = setTimeout(poll, 1500);
}

/* ------------------------------------------------------------------ actions */

function storageKey(pilotKey: string) {
  return `aabflow-copilot-session:${pilotKey}`;
}
function rememberSession(pilotKey: string, id: string | null) {
  try {
    if (id) sessionStorage.setItem(storageKey(pilotKey), id);
    else sessionStorage.removeItem(storageKey(pilotKey));
  } catch {
    /* storage unavailable: conversation simply won't survive reload */
  }
}
function recallSession(pilotKey: string): string | null {
  try {
    return sessionStorage.getItem(storageKey(pilotKey));
  } catch {
    return null;
  }
}

/** Restore this tab's conversation for the pilot from the API (once). */
export async function restore(pilotKey: string) {
  const conv = getConv(pilotKey);
  if (conv.sessionId || conv.restoring || conv.turns.length) return;
  const id = recallSession(pilotKey);
  if (!id) return;
  patchConv(pilotKey, { restoring: true });
  try {
    const s = await copilotApi.getSession(id);
    const turns = s.turns.map((row) => mergeDetail(newTurn(row.user_message, { turnId: row.turn_id, key: row.turn_id, live: false, intentsApplied: true }), row));
    patchConv(pilotKey, { sessionId: s.session_id, turns, restoring: false, restoreNote: null });
    for (const t of turns) if (t.status === "running" && t.turnId) follow(pilotKey, t.turnId);
    // Session rows omit the pinned context and run stats; fill them for recent turns in the background.
    for (const t of turns.slice(-8)) if (t.turnId && t.status !== "running") void refreshTurn(pilotKey, t.turnId);
  } catch (e) {
    rememberSession(pilotKey, null);
    patchConv(pilotKey, {
      restoring: false,
      restoreNote: e instanceof ApiError && e.status === 404 ? "The previous conversation is no longer on the server; a new one starts with your next question." : null,
    });
  }
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
  follow(pilotKey, a.turn_id, a.events_url);
}

export async function send(pilotKey: string, message: string, context: UIContext) {
  const t = newTurn(message);
  patchConv(pilotKey, (c) => ({ turns: [...c.turns, t], restoreNote: null }));
  try {
    let sid = await ensureSession(pilotKey, context);
    let a: TurnAccepted;
    try {
      a = await copilotApi.postMessage(sid, message, context);
    } catch (e) {
      // The session vanished (server DB reset): start a fresh one once.
      if (e instanceof ApiError && e.status === 404) {
        sid = await ensureSession(pilotKey, context, true);
        a = await copilotApi.postMessage(sid, message, context);
      } else throw e;
    }
    accept(pilotKey, t.key, a);
  } catch (e) {
    patchTurn(pilotKey, t.key, (x) => ({ ...x, status: "rejected", requestError: describeError(e), error: errorOf(e) }));
  }
}

export async function retry(pilotKey: string, turn: LiveTurn, context: UIContext) {
  // A rejected POST never reached the server: send it again as a new message.
  if (!turn.turnId) {
    patchConv(pilotKey, (c) => ({ turns: c.turns.filter((x) => x.key !== turn.key) }));
    return send(pilotKey, turn.message, context);
  }
  const t = newTurn(turn.message, { retryOf: turn.turnId });
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
    if (!r.cancel_requested) {
      // The server no longer runs this turn; adopt its recorded status.
      await refreshTurn(pilotKey, turn.turnId);
    }
  } catch (e) {
    patchTurn(pilotKey, turn.key, (x) => ({ ...x, status: x.status === "cancelling" ? "running" : x.status, requestError: describeError(e) }));
  }
}

export function markIntentsApplied(pilotKey: string, key: string) {
  patchTurn(pilotKey, key, (x) => ({ ...x, intentsApplied: true }));
}

export async function loadToolCalls(pilotKey: string, turn: LiveTurn) {
  if (!turn.turnId || turn.toolCalls) return;
  await refreshTurn(pilotKey, turn.turnId);
}

/** Start over: forget the session (the server keeps it for audit) and stop following turns. */
export function reset(pilotKey: string) {
  for (const t of getConv(pilotKey).turns) if (t.turnId) stopStream(t.turnId);
  rememberSession(pilotKey, null);
  patchConv(pilotKey, empty());
}

function errorOf(e: unknown): TurnError | null {
  if (e instanceof ApiError) {
    const b = (e.body ?? {}) as Record<string, unknown>;
    return { code: e.code, detail: e.message, retryable: e.status >= 500 || e.status === 0 || undefined, ...(b.provider_code ? { provider_code: b.provider_code } : {}) } as TurnError;
  }
  return null;
}

/** Test hook. */
export function __resetConversations() {
  for (const id of [...streams.keys()]) stopStream(id);
  useConversationStore.setState({ byPilot: {} });
}
