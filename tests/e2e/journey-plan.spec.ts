/**
 * "Plan my season" journey (WIN_PLAN P2) against the REAL API and the configured hosted model.
 * (a) the seeded plan turn (`plan_turn_id` in GET /demo/session, written by
 *     `seed_demo_session.py --plan-goal`) replays from its stored event log, labelled as saved;
 * (b) "Run it live" posts the same goal as a new plan-mode turn and must finish with a brief that
 *     has at least one kpi/metric block and a run badge whose run resolves via /api/v2/runs/{id}.
 * Skips (a)+(b) when no plan turn was seeded, and (b) when no hosted-model key is configured.
 */
import { expect, test } from "@playwright/test";
import { shot } from "./helpers";

test.use({ actionTimeout: 30_000 });
test.setTimeout(330_000);

interface DemoSession {
  pilot_id: string;
  pilot_version: string;
  plan_turn_id?: string | null;
  plan_goal?: string | null;
}

test("saved investigation replays, then one live goal produces a brief", async ({ page }, info) => {
  const r = await page.request.get("/api/v2/demo/session");
  test.skip(!r.ok(), "no demo session seeded (make demo-seed)");
  const demo = (await r.json()) as DemoSession;
  test.skip(!demo.plan_turn_id, "no plan turn seeded (seed_demo_session.py --plan-goal)");

  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("response", (res) => {
    const u = new URL(res.url());
    if (u.pathname.startsWith("/api/v2/copilot") && res.status() >= 500) problems.push(`${res.status()} ${u.pathname}`);
  });

  // (a) saved replay
  await page.goto(`/p/${demo.pilot_id}/${demo.pilot_version}/plan-season?turn=${demo.plan_turn_id}`);
  const screen = page.getByTestId("plan-season");
  await expect(screen).toBeVisible();
  await expect(page.getByTestId("plan-source")).toContainText("Saved investigation · computed");
  await expect(page.getByTestId("plan-timeline-row").first()).toBeVisible({ timeout: 30_000 });
  if (await page.getByTestId("plan-skip").isVisible()) await page.getByTestId("plan-skip").click();
  await expect(screen).toHaveAttribute("data-phase", "done", { timeout: 120_000 });
  const savedBrief = page.getByTestId("plan-answer");
  await expect(savedBrief).toBeVisible();
  await expect(savedBrief.locator("[data-testid=copilot-metrics], [data-testid=copilot-visual], [data-testid=copilot-run-badge]").first()).toBeVisible();
  await expect(page.getByTestId("plan-timeline").locator("[data-phase=understand] [data-testid=plan-timeline-row]").first()).toBeVisible();
  await shot(page, info, "plan-saved", "plan");

  // (b) one live goal
  const status = await (await page.request.get("/api/v2/copilot/status")).json();
  test.skip(!status.configured, "no hosted-model key configured: live planning unavailable");
  await page.getByTestId("plan-run-live").click();
  await expect(page.getByTestId("plan-source")).toContainText("Live investigation");
  await expect(page).toHaveURL(/turn=turn_/, { timeout: 30_000 });
  const liveTurn = new URL(page.url()).searchParams.get("turn");
  expect(liveTurn).not.toBe(demo.plan_turn_id);
  await expect(page.getByTestId("plan-timeline-row").first()).toBeVisible({ timeout: 60_000 });
  await shot(page, info, "plan-live-working", "plan");
  await expect(screen).toHaveAttribute("data-phase", /done|error/, { timeout: 260_000 });

  const turn = await (await page.request.get(`/api/v2/copilot/turns/${liveTurn}`)).json();
  expect(turn.mode).toBe("plan");
  expect(turn.status, `live plan turn ended ${turn.status}: ${JSON.stringify(turn.error)}`).toBe("completed");
  const brief = page.getByTestId("plan-answer");
  await expect(brief).toBeVisible();
  await expect(brief.locator("[data-testid=copilot-metrics], [data-testid=copilot-kpi]").first()).toBeVisible();
  const badge = brief.getByTestId("copilot-run-badge").first();
  await expect(badge).toBeVisible();
  const runId = await badge.getAttribute("data-run-id");
  expect(runId).toBeTruthy();
  const run = await page.request.get(`/api/v2/runs/${runId}`);
  expect(run.ok(), `run ${runId} resolves`).toBeTruthy();
  await expect(page.getByTestId("plan-open-report")).toBeEnabled();
  await shot(page, info, "plan-live-brief", "plan");
  expect(problems).toEqual([]);
});
