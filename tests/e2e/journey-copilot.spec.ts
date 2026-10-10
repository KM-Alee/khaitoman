/**
 * Copilot journey (F19) against the REAL API and the configured hosted model: open a stored
 * plan run, open "Ask AabFlow", ask one plain question, and check that a server-built chart
 * and the run badge of the answer render. Screenshots of the welcome state, the answer and an
 * expanded chart go to evidence/screenshots/. Needs a configured key on the API; without one the
 * spec checks the honest offline state instead.
 */
import { expect, test, type Page } from "@playwright/test";
import { shot } from "./helpers";

test.use({ actionTimeout: 30_000 });
test.setTimeout(240_000);

const PILOT = "pilot-a";
const VERSION = "reviewed-v1";

async function planRun(page: Page): Promise<string> {
  const r = await page.request.get(`/api/v2/runs?pilot_id=${PILOT}&pilot_version=${VERSION}&limit=200`);
  expect(r.ok()).toBeTruthy();
  const runs = (await r.json()).runs as { run_id: string; plan_kind: string; outcome: string; analysis_id: string | null; season_id?: string }[];
  const p = runs.find((x) => x.plan_kind === "P" && x.outcome === "plan" && !x.analysis_id && x.season_id === "wheat-rabi-2027-28") ?? runs.find((x) => x.plan_kind === "P" && x.outcome === "plan" && !x.analysis_id);
  expect(p, "a stored P run with a plan exists for pilot-a").toBeTruthy();
  return p!.run_id;
}

test("ask one question and get a chart with the run badge", async ({ page }, info) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/v2/copilot") && r.status() >= 500) problems.push(`${r.status()} ${u.pathname}`);
  });
  const runId = await planRun(page);
  await page.goto(`/p/${PILOT}/${VERSION}/workspace?run=${runId}`);
  await page.getByTestId("ask-aabflow").click();
  const panel = page.getByTestId("copilot-panel");
  await expect(panel).toBeVisible();

  const status = await (await page.request.get("/api/v2/copilot/status")).json();
  if (!status.configured) {
    await expect(page.getByTestId("copilot-unavailable")).toBeVisible();
    await shot(page, info, "copilot-offline", "copilot");
    return;
  }
  await expect(panel.getByTestId("copilot-welcome")).toBeVisible();
  await expect(panel.getByTestId("copilot-suggestion").first()).toBeVisible();
  await shot(page, info, "copilot-welcome", "copilot");

  await panel.getByTestId("copilot-input").fill("What's the best plan for our canal? Keep it simple.");
  await panel.getByTestId("copilot-send").click();
  await expect(panel.getByTestId("copilot-question")).toBeVisible();
  await expect(panel.getByTestId("copilot-progress")).toBeVisible();
  await shot(page, info, "copilot-working", "copilot");

  const turn = panel.getByTestId("copilot-turn").last();
  await expect(turn).toHaveAttribute("data-status", /completed|clarification|budget_exhausted|provider_unavailable|failed/, { timeout: 180_000 });
  const finalStatus = await turn.getAttribute("data-status");
  expect(finalStatus, "the live turn completed").toBe("completed");

  const badge = turn.getByTestId("copilot-run-badge").first();
  await expect(badge).toBeVisible();
  await expect(badge).toHaveAttribute("data-run-id", runId);
  const visual = turn.getByTestId("copilot-visual").first();
  await expect(visual).toBeVisible();
  // A chart (ECharts SVG) or a server-built React view (cards, steps, map, table) is drawn.
  await expect(visual.locator("svg, [data-testid=copilot-kpi], [data-testid=copilot-steps], [data-testid=copilot-visual-table]").first()).toBeVisible();
  await visual.scrollIntoViewIfNeeded();
  await shot(page, info, "copilot-answer", "copilot");

  // The data twin lists the served rows.
  await visual.getByRole("radio", { name: /data/i }).click();
  await expect(visual.getByTestId("copilot-visual-table")).toBeVisible();
  await visual.getByRole("radio", { name: /chart|cards|steps|map/i }).click();

  // Expand opens the same visual large, with its table.
  await visual.getByRole("button", { name: "Expand" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await shot(page, info, "copilot-expanded", "copilot");
  await page.keyboard.press("Escape");

  // The run badge opens the run in the workspace.
  await badge.click();
  await expect(page).toHaveURL(new RegExp(`run=${runId}`));
  expect(problems).toEqual([]);
});
