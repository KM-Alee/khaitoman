/**
 * Copilot accessibility and visual review (TEST FIXTURE). The copilot routes are answered from the recorded live
 * gpt-6-luna smoke transcript (web/src/features/copilot/__fixtures__/smoke.json, copied from
 * evidence/copilot/smoke-20261010T131112Z.json) so every chart kind can be reviewed without new
 * hosted-model calls. Everything else (pilot, map, runs) comes from the real API. Screenshots go
 * to evidence/screenshots/copilot-gallery-*.png. This is a design check, not evidence of F19.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { shot } from "./helpers";

test.setTimeout(180_000);

const SMOKE = JSON.parse(readFileSync(resolve(__dirname, "../../web/src/features/copilot/__fixtures__/smoke.json"), "utf8")) as {
  turns: Record<string, { message: string; turn_id: string; status: string; rounds: number; latency_ms: number; answer: { language: string; blocks: unknown[] }; tools: { tool: string; status: string }[]; created_refs: unknown[]; error: unknown }>;
};

function events(caseId: string) {
  const t = SMOKE.turns[caseId];
  const evs: { type: string; payload: unknown }[] = [
    { type: "turn_started", payload: { turn_id: t.turn_id, context: { pilot_id: "pilot-a", pilot_version: "reviewed-v1" }, language: t.answer.language } },
    ...t.tools.flatMap((x, i) => [
      { type: "tool_started", payload: { call_id: `c${i}`, tool: x.tool, activity: x.tool.replace(/_/g, " "), semantics: "read" } },
      { type: "tool_finished", payload: { call_id: `c${i}`, tool: x.tool, ok: x.status === "succeeded", activity: x.tool.replace(/_/g, " "), duration_ms: 40 } },
    ]),
    { type: "answer", payload: t.answer },
    { type: "turn_finished", payload: { status: t.status, rounds: t.rounds, latency_ms: t.latency_ms, pending_job_ids: [], error: t.error } },
  ];
  return evs.map((e, i) => ({ ...e, event_id: i + 1, turn_id: t.turn_id, created_at: "2026-10-10T13:11:12Z" }));
}

async function mockCopilot(page: Page) {
  const byMessage = new Map(Object.entries(SMOKE.turns).map(([k, t]) => [t.message, k]));
  const byTurn = new Map(Object.entries(SMOKE.turns).map(([k, t]) => [t.turn_id, k]));
  const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/v2/copilot/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    if (p.endsWith("/copilot/status")) return route.fulfill(json({ configured: true, state: "ready", model: "gpt-6-luna (recorded)", prompt_version: "copilot-prompt-2.1.0", tool_schema_version: "fixture", offline_note: "" }));
    if (p.endsWith("/copilot/sessions") && req.method() === "GET") return route.fulfill(json({ sessions: [] }));
    if (p.endsWith("/copilot/sessions") && req.method() === "POST") return route.fulfill(json({ session_id: "cps_fixture", role: "planner", status: {} }));
    if (p.endsWith("/messages")) {
      const msg = JSON.parse(req.postData() ?? "{}").message as string;
      const k = byMessage.get(msg) ?? "S1";
      return route.fulfill(json({ turn_id: SMOKE.turns[k].turn_id, session_id: "cps_fixture", context: { pilot_id: "pilot-a", pilot_version: "reviewed-v1" }, events_url: "" }));
    }
    const m = p.match(/\/copilot\/turns\/([^/]+)(\/[a-z-]+)?$/);
    if (m) {
      const k = byTurn.get(m[1]) ?? "S1";
      if (m[2] === "/events") return route.abort();
      if (m[2] === "/event-log") return route.fulfill(json(events(k).filter((e) => e.event_id > Number(url.searchParams.get("after") ?? 0))));
      const t = SMOKE.turns[k];
      return route.fulfill(json({ ...t, session_id: "cps_fixture", seq: 1, user_message: t.message, context: {}, created_at: "", view_intents: [], job_ids: [], request_ids: [] }));
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ code: "NOT_FOUND", detail: p }) });
  });
}

async function ask(page: Page, caseId: string) {
  const panel = page.getByTestId("copilot-panel");
  await panel.getByTestId("copilot-input").fill(SMOKE.turns[caseId].message);
  await panel.getByTestId("copilot-send").click();
  const turn = panel.getByTestId("copilot-turn").last();
  await expect(turn).toHaveAttribute("data-status", SMOKE.turns[caseId].status, { timeout: 30_000 });
  return turn;
}

for (const caseId of ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]) {
  test(`fixture answer ${caseId} renders cleanly`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => m.type() === "error" && /copilot|echarts|render/i.test(m.text()) && errors.push(m.text()));
    await mockCopilot(page);
    const runs = (await (await page.request.get("/api/v2/runs?pilot_id=pilot-a&pilot_version=reviewed-v1&limit=50")).json()).runs as { run_id: string; plan_kind: string; outcome: string }[];
    const run = runs.find((r) => r.plan_kind === "P" && r.outcome === "plan")?.run_id ?? "";
    await page.goto(`/p/pilot-a/reviewed-v1/workspace?run=${run}`);
    await page.getByTestId("ask-aabflow").click();
    const turn = await ask(page, caseId);
    const visuals = turn.getByTestId("copilot-visual");
    for (let i = 0; i < (await visuals.count()); i++) {
      await visuals.nth(i).scrollIntoViewIfNeeded();
      await shot(page, info, `${caseId}-v${i + 1}`, "copilot-gallery");
    }
    if (!(await visuals.count())) await shot(page, info, `${caseId}`, "copilot-gallery");
    const axe = await new AxeBuilder({ page }).include("[data-testid=copilot-panel]").analyze();
    const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    expect(errors).toEqual([]);
  });
}
