/**
 * Planner timeline reducer and saved/live labelling.
 * TEST FIXTURE: the events below are hand-written in the server's event shapes (docs/COPILOT.md §2);
 * their IDs and timings are invented.
 */
import { expect, test } from "vitest";
import type { CopilotEventEnvelope } from "@/features/copilot/types";
import { formatDateTime } from "@/lib/formatting";
import { EXAMPLE_GOALS, briefBlocks, initPlan, planSeasonHref, provisionalPhase, recommendedRunId, reducePlan, replayDelays, sourceLabel, timelineGroups } from "./timeline";

let id = 0;
const t0 = Date.parse("2026-10-10T08:00:00Z");
function ev<T extends CopilotEventEnvelope["type"]>(type: T, payload: Extract<CopilotEventEnvelope, { type: T }>["payload"], atS = id): CopilotEventEnvelope {
  id += 1;
  return { event_id: id, turn_id: "turn_fx", created_at: new Date(t0 + atS * 1000).toISOString(), type, payload } as CopilotEventEnvelope;
}
const step = (n: number, call: string, tool: string, phase: "understand" | "test" | "decide", extra: Record<string, unknown> = {}) =>
  ev("plan_step", { step: n, phase, label: tool, tool, call_id: call, ok: true, run_id: null, analysis_id: null, report_id: null, field_ids: [], ...extra });

function investigation(): CopilotEventEnvelope[] {
  id = 0;
  return [
    ev("turn_started", { turn_id: "turn_fx", context: { pilot_id: "pilot-a", pilot_version: "v1", selected_run_id: "run_ctx" } }, 0),
    ev("thinking", { round: 1, label: "Reading your question and planning" }, 1),
    ev("tool_started", { call_id: "c1", tool: "get_plan_ladder", activity: "Comparing the plans" }, 2),
    ev("tool_started", { call_id: "c2", tool: "run_what_if", activity: "Running your what-if as a new scenario" }, 2),
    ev("tool_finished", { call_id: "c1", tool: "get_plan_ladder", ok: true, activity: "Comparing the plans", duration_ms: 800 }, 3),
    step(1, "c1", "get_plan_ladder", "understand"),
    ev("tool_finished", { call_id: "c2", tool: "run_what_if", ok: true, activity: "Running your what-if as a new scenario", duration_ms: 12_000 }, 14),
    step(2, "c2", "run_what_if", "understand", { run_id: "run_new" }),
    ev("tool_started", { call_id: "c3", tool: "run_stress_test", activity: "Running a stress test" }, 15),
    ev("tool_started", { call_id: "c4", tool: "equity", activity: "Checking fairness" }, 15),
    ev("tool_finished", { call_id: "c4", tool: "equity", ok: true, activity: "Checking fairness", duration_ms: 500 }, 16),
    step(3, "c4", "equity", "test", { field_ids: ["f7", "f9"] }),
    ev("tool_finished", { call_id: "c3", tool: "run_stress_test", ok: false, activity: "Running a stress test", duration_ms: 45_000, error: { code: "TOOL_TIMEOUT", detail: "too slow" } }, 60),
    step(4, "c3", "run_stress_test", "test", { ok: false }),
  ];
}

test("events become rows grouped by the server's phases, with failures and durations", () => {
  const s = investigation().reduce(reducePlan, initPlan("goal"));
  const groups = timelineGroups(s);
  expect(groups.map((g) => g.title)).toEqual(["Understanding your goal", "Testing it", "Deciding"]);
  const [u, t, d] = groups;
  expect(u.rows.map((r) => r.tool)).toEqual(["get_plan_ladder", "run_what_if"]);
  expect(u.rows.map((r) => r.durationMs)).toEqual([800, 12_000]);
  expect(u.state).toBe("done");
  expect(t.rows.map((r) => [r.tool, r.state])).toEqual([
    ["run_stress_test", "failed"],
    ["equity", "ok"],
  ]);
  expect(t.rows[0].error?.code).toBe("TOOL_TIMEOUT");
  expect(d.rows).toEqual([]);
  expect(d.state).toBe("waiting");
  // map hints come from plan_step only
  expect(s.mapRunId).toBe("run_new");
  expect(s.highlight).toEqual(["f7", "f9"]);
  expect(s.planSteps).toHaveLength(4);
});

test("a running tool sits in its provisional phase until the server's plan_step arrives", () => {
  const evs = investigation().slice(0, 9); // stress test started, not finished
  const s = evs.reduce(reducePlan, initPlan("goal"));
  const test_ = timelineGroups(s)[1];
  expect(test_.state).toBe("running");
  expect(test_.rows[0]).toMatchObject({ tool: "run_stress_test", state: "running", durationMs: null });
  expect(provisionalPhase("create_report")).toBe("decide");
  expect(provisionalPhase("get_context")).toBe("understand");
});

test("replayed events are applied once", () => {
  const evs = investigation();
  const once = evs.reduce(reducePlan, initPlan("goal"));
  const twice = evs.reduce(reducePlan, once);
  expect(twice).toBe(once);
});

test("turn_finished marks steps still running as failed (no fake success)", () => {
  const evs = investigation().slice(0, 9);
  evs.push(ev("turn_finished", { status: "budget_exhausted", error: { code: "TURN_TIMEOUT" }, pending_job_ids: [] }));
  const s = evs.reduce(reducePlan, initPlan("goal"));
  expect(s.turn.status).toBe("budget_exhausted");
  expect(timelineGroups(s)[1].rows[0].state).toBe("failed");
});

test("the recommended run is a server id from the brief, else the pinned context", () => {
  const evs = investigation();
  let s = evs.reduce(reducePlan, initPlan("goal"));
  expect(recommendedRunId(s)).toBe("run_ctx");
  s = reducePlan(
    s,
    ev("answer", {
      language: "en",
      validated: true,
      deterministic: false,
      needs_clarification: false,
      blocks: [
        { type: "run_badge", role: "created", run_id: "run_new", pilot_id: "pilot-a", pilot_version: "v1" },
        { type: "action", action: "open_run", ref_id: "run_rec", label: "Open", auto: false },
      ],
    }),
  );
  expect(briefBlocks(s)).toHaveLength(2);
  expect(recommendedRunId(s)).toBe("run_rec");
});

test("saved vs live labelling", () => {
  const at = "2026-10-10T08:04:00Z";
  expect(sourceLabel({ kind: "saved", turnId: "turn_fx", computedAt: at })).toBe(`Saved investigation · computed ${formatDateTime(at)}`);
  expect(sourceLabel({ kind: "saved", turnId: "turn_fx", computedAt: null })).toBe("Saved investigation · computed time unknown");
  expect(sourceLabel({ kind: "live" })).toBe("Live investigation");
});

test("replay runs at 3x the server timing, caps long gaps, and is instant with reduced motion", () => {
  id = 0;
  const evs = [ev("thinking", { round: 1, label: "x" }, 0), ev("thinking", { round: 1, label: "x" }, 3), ev("thinking", { round: 1, label: "x" }, 63)];
  expect(replayDelays(evs)).toEqual([0, 1000, 4000]);
  expect(replayDelays(evs, { reduced: true })).toEqual([0, 0, 0]);
});

test("planner links", () => {
  expect(planSeasonHref("pilot-a", "reviewed-v1")).toBe("/p/pilot-a/reviewed-v1/plan-season");
  expect(planSeasonHref("pilot-a", "reviewed-v1", { turn: "turn_1" })).toBe("/p/pilot-a/reviewed-v1/plan-season?turn=turn_1");
  const href = planSeasonHref("pilot-a", "v1", { goal: EXAMPLE_GOALS[2].goal });
  expect(new URL(href, "http://x").searchParams.get("goal")).toBe(EXAMPLE_GOALS[2].goal);
  expect(EXAMPLE_GOALS.map((g) => g.id)).toEqual(["budget", "fairness", "dry"]);
});

describe("plainLabel", () => {
  it("shortens long record IDs inside activity labels", async () => {
    const { plainLabel } = await import("./InvestigationTimeline");
    expect(plainLabel("Reading run run_1bfb48ecb7404e1e9d9733f92ce3841c")).toBe("Reading run …e3841c");
    expect(plainLabel("Running a stress test")).toBe("Running a stress test");
  });
});
