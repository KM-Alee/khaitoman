/**
 * Typed turn event stream (docs/COPILOT.md §2).
 *
 * Primary transport: SSE `/copilot/turns/{id}/events?after=N`. When the connection drops,
 * the client first catches up from the JSON event log (`/event-log?after=<last id>`), then
 * reopens SSE from the last event it applied, with backoff. After repeated failures (or when
 * EventSource is missing, or a proxy buffers SSE) it falls back to polling the event log.
 * Events are applied at most once and in event_id order. The stream closes itself once the
 * turn finished with no pending job, or its jobs settled.
 */
import { copilotApi } from "./api";
import { COPILOT_EVENT_TYPES, endsStream, type CopilotEventEnvelope } from "./types";

export type StreamState = "connecting" | "live" | "reconnecting" | "polling" | "closed";

export interface EventSourceLike {
  readyState: number;
  onopen: ((ev: Event) => void) | null;
  onerror: ((ev: Event) => void) | null;
  addEventListener: (type: string, fn: (ev: MessageEvent) => void) => void;
  close: () => void;
}

export interface StreamOptions {
  turnId: string;
  /** Last event already applied (0 = from the start). */
  after?: number;
  onEvent: (ev: CopilotEventEnvelope) => void;
  onState?: (s: StreamState) => void;
  createEventSource?: ((url: string) => EventSourceLike) | null;
  fetchLog?: (turnId: string, after: number) => Promise<CopilotEventEnvelope[]>;
  pollMs?: number;
  maxReconnects?: number;
  /** No event for this long while "live" → catch up from the event log (buffered SSE safety net). */
  watchdogMs?: number;
}

export interface TurnStream {
  close: () => void;
  lastEventId: () => number;
  state: () => StreamState;
}

const defaultCreate = (): ((url: string) => EventSourceLike) | null =>
  typeof EventSource === "undefined" ? null : (url: string) => new EventSource(url) as unknown as EventSourceLike;

export function openTurnStream(o: StreamOptions): TurnStream {
  const create = o.createEventSource === undefined ? defaultCreate() : o.createEventSource;
  const fetchLog = o.fetchLog ?? ((id: string, after: number) => copilotApi.eventLog(id, after));
  const pollMs = o.pollMs ?? 1500;
  const maxReconnects = o.maxReconnects ?? 3;
  const watchdogMs = o.watchdogMs ?? 6000;

  let last = o.after ?? 0;
  let state: StreamState = "connecting";
  let done = false;
  let es: EventSourceLike | null = null;
  let failures = 0;
  let lastSeen = Date.now();
  const timers = new Set<ReturnType<typeof setTimeout>>();

  const setState = (s: StreamState) => {
    if (state === s) return;
    state = s;
    o.onState?.(s);
  };
  const later = (fn: () => void, ms: number) => {
    const t = setTimeout(() => {
      timers.delete(t);
      fn();
    }, ms);
    timers.add(t);
  };
  const finish = () => {
    if (done) return;
    done = true;
    es?.close();
    es = null;
    for (const t of timers) clearTimeout(t);
    timers.clear();
    setState("closed");
  };
  const deliver = (ev: CopilotEventEnvelope) => {
    if (done || !ev || typeof ev.event_id !== "number" || ev.event_id <= last) return;
    last = ev.event_id;
    lastSeen = Date.now();
    o.onEvent(ev);
    if (endsStream(ev)) finish();
  };
  const catchUp = async () => {
    try {
      const evs = await fetchLog(o.turnId, last);
      for (const ev of [...evs].sort((a, b) => a.event_id - b.event_id)) deliver(ev);
      return true;
    } catch {
      return false;
    }
  };
  const poll = async () => {
    if (done) return;
    setState("polling");
    await catchUp();
    if (!done) later(poll, pollMs);
  };
  const watchdog = () => {
    if (done || state !== "live") return;
    if (Date.now() - lastSeen >= watchdogMs) void catchUp();
    later(watchdog, watchdogMs);
  };
  const connect = () => {
    if (done) return;
    if (!create) {
      void poll();
      return;
    }
    let source: EventSourceLike;
    try {
      source = create(copilotApi.eventsUrl(o.turnId, last));
    } catch {
      void poll();
      return;
    }
    es = source;
    const onMessage = (m: MessageEvent) => {
      try {
        deliver(JSON.parse(String(m.data)) as CopilotEventEnvelope);
      } catch {
        /* a keepalive or malformed frame: ignore */
      }
    };
    for (const t of COPILOT_EVENT_TYPES) source.addEventListener(t, onMessage);
    source.onopen = () => {
      failures = 0;
      lastSeen = Date.now();
      setState("live");
      later(watchdog, watchdogMs);
    };
    source.onerror = () => {
      if (done || es !== source) return;
      source.close();
      es = null;
      failures += 1;
      setState("reconnecting");
      void catchUp().then(() => {
        if (done) return;
        if (failures > maxReconnects) void poll();
        else later(connect, Math.min(4000, 500 * 2 ** (failures - 1)));
      });
    };
  };

  o.onState?.(state);
  connect();
  return { close: finish, lastEventId: () => last, state: () => state };
}
