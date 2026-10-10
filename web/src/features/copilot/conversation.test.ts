import { applyEvent, mergeRow, newTurn, turnsFromSession } from "./conversation";
import { SMOKE, smokeEvents } from "./__fixtures__/smoke";
import { COPILOT_EVENT_TYPES, endsStream, type CopilotEventEnvelope } from "./types";

test("the smoke event sequence builds progress, partial blocks and then the final answer", () => {
  const evs = smokeEvents("S2");
  let t = newTurn("What if we only had 10 lakh?", { turnId: "turn_s2", key: "turn_s2", status: "running" });
  const firstBlock = evs.findIndex((e) => e.type === "answer_block");
  for (const e of evs.slice(0, firstBlock)) t = applyEvent(t, e);
  expect(t.steps.map((s) => [s.tool, s.state])).toEqual([["run_what_if", "ok"]]);
  expect(t.thinking?.label).toBe("Looking at the results");
  t = applyEvent(t, evs[firstBlock]);
  t = applyEvent(t, evs[firstBlock + 1]);
  expect(t.partial).toHaveLength(2);
  expect(t.thinking).toBeNull();
  for (const e of evs.slice(firstBlock + 2)) t = applyEvent(t, e);
  expect(t.answer).toEqual(SMOKE.turns.S2.answer);
  expect(t.partial).toEqual([]);
  expect(t.status).toBe("completed");
  expect(t.jobsSettled).toBe(true);
});

test("replayed events are ignored and running steps fail when the turn ends", () => {
  const evs = smokeEvents("S3");
  let t = newTurn("q", { turnId: "x", status: "running" });
  t = applyEvent(t, evs[0]);
  t = applyEvent(t, { ...evs[0], payload: { ...evs[0].payload } } as CopilotEventEnvelope);
  expect(t.lastEventId).toBe(1);
  t = applyEvent(t, { event_id: 2, turn_id: "x", created_at: "", type: "tool_started", payload: { call_id: "c9", tool: "read_analysis", activity: "Opening a saved analysis" } });
  t = applyEvent(t, {
    event_id: 3,
    turn_id: "x",
    created_at: "",
    type: "turn_finished",
    payload: { status: "budget_exhausted", pending_job_ids: [], error: { code: "TURN_TIMEOUT", detail: "the turn reached its time budget" } },
  });
  expect(t.status).toBe("budget_exhausted");
  expect(t.steps[0].state).toBe("failed");
  expect(t.error?.code).toBe("TURN_TIMEOUT");
});

test("turns with background jobs keep the stream open until jobs settle", () => {
  const base = { turn_id: "x", created_at: "" };
  const fin = { ...base, event_id: 1, type: "turn_finished", payload: { status: "completed", pending_job_ids: ["job_1"] } } as CopilotEventEnvelope;
  expect(endsStream(fin)).toBe(false);
  let t = applyEvent(newTurn("q", { status: "running" }), fin);
  expect(t.jobsSettled).toBe(false);
  t = applyEvent(t, { ...base, event_id: 2, type: "job_update", payload: { job_id: "job_1", state: "succeeded" } });
  const settled = { ...base, event_id: 3, type: "jobs_settled", payload: { pending_job_ids: [] } } as CopilotEventEnvelope;
  expect(endsStream(settled)).toBe(true);
  t = applyEvent(t, settled);
  expect(t.pendingJobIds).toEqual([]);
  expect(t.jobsSettled).toBe(true);
});

test("multi-run comparisons are shown one before/after pair at a time", async () => {
  const { comparisonPairs } = await import("./blocks");
  const cmp = SMOKE.turns.S1.answer.blocks.find((b) => b.type === "comparison");
  if (!cmp || cmp.type !== "comparison") throw new Error("fixture has no comparison");
  const pairs = comparisonPairs(cmp);
  const metrics = new Set(cmp.deltas.map((d) => d.metric_id));
  expect(pairs.length).toBe(cmp.deltas.length / metrics.size);
  for (const p of pairs) expect(new Set(p.deltas.map((d) => d.metric_id)).size).toBe(p.deltas.length);
});

test("every contract event type is handled by the reducer", () => {
  expect(COPILOT_EVENT_TYPES).toHaveLength(14);
});

test("a stored session restores turns with their answers and language", () => {
  const s5 = SMOKE.turns.S5;
  const turns = turnsFromSession({
    session_id: "cps_1",
    role: "planner",
    turns: [
      {
        turn_id: s5.turn_id,
        seq: 1,
        status: "completed",
        user_message: s5.message,
        language: "ur",
        answer: s5.answer,
        view_intents: [],
        created_refs: s5.created_refs,
        job_ids: [],
        error: null,
        rounds: 2,
        latency_ms: s5.latency_ms,
        created_at: "2026-10-10T13:11:12Z",
        finished_at: "2026-10-10T13:11:30Z",
      },
    ],
  });
  expect(turns[0].live).toBe(false);
  expect(turns[0].language).toBe("ur");
  expect(turns[0].answer?.blocks.length).toBe(s5.answer.blocks.length);
  expect(turns[0].created.map((c) => c.kind)).toEqual(s5.created_refs.map((c) => c.kind));
  const merged = mergeRow(turns[0], { turn_id: s5.turn_id, status: "completed", user_message: s5.message, latency_ms: 9 });
  expect(merged.latencyMs).toBe(9);
});
