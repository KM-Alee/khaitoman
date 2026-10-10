import { applyEvent, mergeDetail, newTurn } from "./conversation";
import type { CopilotEventEnvelope, TurnDetail } from "./api";

const env = (event_id: number, e: Omit<CopilotEventEnvelope, "event_id" | "turn_id" | "created_at">) =>
  ({ ...e, event_id, turn_id: "turn_1", created_at: "2026-10-10T00:00:00Z" }) as CopilotEventEnvelope;

test("tool events build a live activity list and turn_finished settles it", () => {
  let t = newTurn("Why this plan?", { turnId: "turn_1", key: "turn_1", status: "running" });
  t = applyEvent(t, env(1, { type: "turn_started", payload: { turn_id: "turn_1", context: { pilot_id: "pilot-a", pilot_version: "v1", selected_run_id: "run_x" }, badge: { pilot_id: "pilot-a", pilot_version: "v1", run_id: "run_x", season_id: null } } }));
  t = applyEvent(t, env(2, { type: "tool_started", payload: { call_id: "c1", tool: "inspect_run", activity: "Reading run", semantics: "read" } }));
  t = applyEvent(t, env(3, { type: "tool_started", payload: { call_id: "c2", tool: "search_evidence", activity: "Searching evidence", semantics: "read" } }));
  expect(t.activity.map((a) => a.state)).toEqual(["running", "running"]);
  t = applyEvent(t, env(4, { type: "tool_finished", payload: { call_id: "c2", tool: "search_evidence", ok: false, activity: "Searching evidence", error: { code: "TOOL_TIMEOUT", detail: "slow" } } }));
  t = applyEvent(t, env(5, { type: "tool_finished", payload: { call_id: "c1", tool: "inspect_run", ok: true, activity: "Reading run" } }));
  expect(t.activity.map((a) => [a.tool, a.state])).toEqual([
    ["inspect_run", "ok"],
    ["search_evidence", "failed"],
  ]);
  expect(t.context?.selected_run_id).toBe("run_x");
  t = applyEvent(t, env(6, { type: "answer", payload: { language: "en", blocks: [{ type: "text", text: "Hi", citations: [{ ref_id: "run_x", kind: "run" }] }], needs_clarification: false, clarification_question: null, validated: true, issues: [] } }));
  t = applyEvent(t, env(7, { type: "turn_finished", payload: { status: "completed", rounds: 2, tool_calls: 2, latency_ms: 2400, pending_job_ids: [] } }));
  expect(t.status).toBe("completed");
  expect(t.jobsSettled).toBe(true);
  expect(t.rounds).toBe(2);
  expect(t.answer?.validated).toBe(true);
  expect(t.lastEventId).toBe(7);
});

test("replayed events after an SSE reconnect are ignored", () => {
  let t = newTurn("q", { turnId: "turn_1", status: "running" });
  t = applyEvent(t, env(2, { type: "tool_started", payload: { call_id: "c1", tool: "inspect_run", activity: "Reading run", semantics: "read" } }));
  const again = applyEvent(t, env(2, { type: "tool_started", payload: { call_id: "c9", tool: "x", activity: "dup", semantics: "read" } }));
  expect(again).toBe(t);
});

test("pending jobs keep following until job_update/jobs_settled", () => {
  let t = newTurn("solve it", { turnId: "turn_1", status: "running" });
  t = applyEvent(t, env(1, { type: "turn_finished", payload: { status: "completed", pending_job_ids: ["job_a"] } }));
  expect(t.jobsSettled).toBe(false);
  expect(t.pendingJobIds).toEqual(["job_a"]);
  t = applyEvent(t, env(2, { type: "job_update", payload: { job_id: "job_a", state: "succeeded", run: { run_id: "run_new", plan_kind: "P" } } }));
  expect(t.pendingJobIds).toEqual([]);
  t = applyEvent(t, env(3, { type: "jobs_settled", payload: { pending_job_ids: [] } }));
  expect(t.jobsSettled).toBe(true);
  expect(t.jobUpdates[0].run?.run_id).toBe("run_new");
});

test("mergeDetail adopts the authoritative row, tool calls and missed events", () => {
  const t = newTurn("q", { turnId: "turn_1", status: "running" });
  const d = {
    turn_id: "turn_1",
    session_id: "cps_1",
    seq: 1,
    status: "provider_unavailable",
    user_message: "q",
    answer: { language: "en", blocks: [{ type: "uncertainty", text: "unavailable", citations: [] }], needs_clarification: false, clarification_question: null, validated: true, issues: [], deterministic: true },
    view_intents: [],
    created_refs: [],
    job_ids: [],
    error: { code: "PROVIDER_NOT_CONFIGURED", detail: "no API key" },
    created_at: "",
    finished_at: "",
    context: { pilot_id: "pilot-a", pilot_version: "v1", selected_run_id: "run_x" },
    model: "m",
    prompt_version: "p",
    tool_schema_version: "t",
    request_ids: [],
    rounds: 0,
    latency_ms: 12,
    tool_calls: [],
    events: [env(1, { type: "error", payload: { code: "PROVIDER_NOT_CONFIGURED", detail: "no API key" } })],
  } as unknown as TurnDetail;
  const m = mergeDetail(t, d);
  expect(m.status).toBe("provider_unavailable");
  expect(m.answer?.deterministic).toBe(true);
  expect(m.toolCalls).toEqual([]);
  expect(m.error?.code).toBe("PROVIDER_NOT_CONFIGURED");
  expect(m.context?.selected_run_id).toBe("run_x");
  expect(m.lastEventId).toBe(1);
});
