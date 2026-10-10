import { openTurnStream, type EventSourceLike } from "./stream";
import { smokeEvents } from "./__fixtures__/smoke";
import type { CopilotEventEnvelope } from "./types";

/** TEST FIXTURE: an EventSource double the test drives by hand. */
class FakeES implements EventSourceLike {
  static made: FakeES[] = [];
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  closed = false;
  constructor(public url: string) {
    FakeES.made.push(this);
  }
  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  emit(ev: CopilotEventEnvelope) {
    for (const fn of this.listeners.get(ev.type) ?? []) fn(new MessageEvent(ev.type, { data: JSON.stringify(ev) }));
  }
  fail() {
    this.onerror?.(new Event("error"));
  }
}

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  FakeES.made = [];
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => vi.useRealTimers());

test("SSE events apply once, in order, and the stream closes on turn_finished", () => {
  const evs = smokeEvents("S7");
  const got: number[] = [];
  const states: string[] = [];
  const s = openTurnStream({ turnId: "t", onEvent: (e) => got.push(e.event_id), onState: (x) => states.push(x), createEventSource: (u) => new FakeES(u), fetchLog: async () => [] });
  const es = FakeES.made[0];
  expect(es.url).toBe("/api/v2/copilot/turns/t/events");
  es.open();
  for (const e of evs.slice(0, 4)) es.emit(e);
  es.emit(evs[2]); // duplicate after reconnect
  for (const e of evs.slice(4)) es.emit(e);
  expect(got).toEqual(evs.map((e) => e.event_id));
  expect(states).toEqual(["connecting", "live", "closed"]);
  expect(es.closed).toBe(true);
  expect(s.state()).toBe("closed");
});

test("a dropped connection catches up from the event log, then resumes SSE after the last event", async () => {
  const evs = smokeEvents("S1");
  const got: number[] = [];
  const log = vi.fn(async (_id: string, after: number) => evs.filter((e) => e.event_id > after && e.event_id <= 6));
  openTurnStream({ turnId: "t", onEvent: (e) => got.push(e.event_id), createEventSource: (u) => new FakeES(u), fetchLog: log });
  const first = FakeES.made[0];
  first.open();
  first.emit(evs[0]);
  first.emit(evs[1]);
  first.fail();
  await flush();
  expect(log).toHaveBeenCalledWith("t", 2);
  expect(got).toEqual([1, 2, 3, 4, 5, 6]);
  await vi.advanceTimersByTimeAsync(600);
  const second = FakeES.made[1];
  expect(second.url).toBe("/api/v2/copilot/turns/t/events?after=6");
  second.open();
  for (const e of evs.slice(6)) second.emit(e);
  expect(got).toEqual(evs.map((e) => e.event_id));
  expect(second.closed).toBe(true);
});

test("without EventSource it polls the event log until the turn ends", async () => {
  const evs = smokeEvents("S6");
  let served = 0;
  const got: number[] = [];
  const log = vi.fn(async (_id: string, after: number) => {
    served += 3;
    return evs.filter((e) => e.event_id > after && e.event_id <= served);
  });
  const s = openTurnStream({ turnId: "t", onEvent: (e) => got.push(e.event_id), createEventSource: null, fetchLog: log, pollMs: 50 });
  for (let i = 0; i < 20 && s.state() !== "closed"; i++) await vi.advanceTimersByTimeAsync(60);
  expect(got).toEqual(evs.map((e) => e.event_id));
  expect(s.state()).toBe("closed");
});

test("repeated failures fall back to polling", async () => {
  const evs = smokeEvents("S4");
  const log = vi.fn(async () => [] as CopilotEventEnvelope[]);
  const states: string[] = [];
  const s = openTurnStream({ turnId: "t", onEvent: () => {}, onState: (x) => states.push(x), createEventSource: (u) => new FakeES(u), fetchLog: log, maxReconnects: 1, pollMs: 50 });
  FakeES.made[0].fail();
  await vi.advanceTimersByTimeAsync(600);
  FakeES.made[1].fail();
  await vi.advanceTimersByTimeAsync(60);
  expect(states).toContain("polling");
  log.mockResolvedValue(evs);
  await vi.advanceTimersByTimeAsync(120);
  expect(s.state()).toBe("closed");
});
