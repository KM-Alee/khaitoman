/**
 * Five-minute stage route (PRD §13.2) against the REAL API, driven the way a presenter does:
 * landing → workspace run (B0·B1·P) → live budget change → compare ladder → replay →
 * frontier and stress through the UI → impact/SDG → report → evidence, then a reload of a
 * shared compare link. Every number on screen comes from the server; this spec checks that
 * each step shows real records (run and analysis IDs that resolve through the API) and that
 * no console error or 5xx API response happens on the way.
 */
import { expect, test, type Page } from "@playwright/test";
import { shot, waitForMap } from "./helpers";

test.use({ actionTimeout: 30_000 });

const PILOT = "pilot-a";
const VERSION = "reviewed-v1";

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/") && r.status() >= 500) problems.push(`${r.status()} ${u.pathname}`);
  });
  return problems;
}

const runParam = (page: Page) => new URL(page.url()).searchParams.get("run");

async function planKind(page: Page, runId: string | null) {
  if (!runId) return null;
  const r = await page.request.get(`/api/v2/runs/${runId}`);
  return r.ok() ? ((await r.json()).run.plan_kind as string) : null;
}

/** The workspace solves B0, B1 and P in turn; wait until the URL points at a finished P run. */
async function waitForPortfolio(page: Page, previous: string | null) {
  await expect
    .poll(async () => {
      const id = runParam(page);
      return id && id !== previous ? await planKind(page, id) : null;
    }, { timeout: 300_000, intervals: [1000] })
    .toBe("P");
  await expect(page.getByTestId("run-plan")).toBeEnabled({ timeout: 120_000 });
  return runParam(page)!;
}

async function nav(page: Page, label: string) {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: label }).first().click();
}

test("stage route on the real API", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "the stage route is presented on a laptop or projector");
  test.setTimeout(900_000);
  const problems = watch(page);

  // 0:00 — landing and the pilot
  await page.goto("/");
  await expect(page.getByTestId("landing")).toBeVisible();
  await shot(page, info, "00-landing", "stage");
  await page.getByTestId("pilot-card").filter({ hasText: "pilot-a" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/p/${PILOT}/${VERSION}/workspace`));
  await waitForMap(page, 30);
  await shot(page, info, "01-workspace", "stage");

  // 1:00 — run B0, B1 and P under identical conditions
  const runPlan = page.getByTestId("run-plan");
  await runPlan.click();
  const first = await waitForPortfolio(page, runParam(page));
  await expect(page.getByTestId("result-strip")).toContainText(/t\b|kg/);
  await shot(page, info, "02-workspace-portfolio", "stage");

  // 1:50 — change the capital budget and re-solve live
  const capital = page.getByRole("textbox", { name: /Capital budget/ });
  await capital.fill("300000");
  await capital.press("Enter");
  await runPlan.click();
  const second = await waitForPortfolio(page, first);
  expect(second).not.toBe(first);
  const firstRun = await (await page.request.get(`/api/v2/runs/${first}`)).json();
  const secondRun = await (await page.request.get(`/api/v2/runs/${second}`)).json();
  expect(secondRun.run.scenario_revision_id).not.toBe(firstRun.run.scenario_revision_id);
  await shot(page, info, "03-workspace-budget", "stage");

  // Compare: the ladder shows B0, B1 and P with a matched-comparison certificate
  await nav(page, "Compare");
  await expect(page.getByTestId("ladder")).toBeVisible();
  for (const k of ["B0", "B1", "P"]) await expect(page.getByTestId("ladder")).toContainText(k);
  await expect(page.getByText(/Matched comparison/)).toBeVisible();
  await shot(page, info, "04-compare", "stage");

  // 2:35 — replay the decisive interval
  await page.getByRole("link", { name: "Season replay" }).click();
  await expect(page.getByTestId("replay")).toBeVisible();
  await page.getByTestId("date-slider").focus();
  for (let i = 0; i < 12; i++) await page.keyboard.press("PageUp");
  await expect(page.getByTestId("replay-date")).not.toHaveText("");
  await shot(page, info, "05-replay", "stage");

  // 3:15 — frontier and stress matrix, solved now through the UI
  await nav(page, "Explore");
  await expect(page.getByTestId("frontier")).toBeVisible();
  await page.getByTestId("run-frontier").click();
  await expect(page.getByTestId("frontier-counts")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByTestId("analysis-status").first()).toHaveAttribute("data-status", "completed", { timeout: 300_000 });
  const frontierId = new URL(page.url()).searchParams.get("analysis");
  expect(frontierId).toBeTruthy();
  const frontier = await (await page.request.get(`/api/v2/analyses/${frontierId}`)).json();
  expect(frontier.result.points.length).toBeGreaterThanOrEqual(6);
  for (const p of frontier.result.points) if (p.outcome === "plan" || p.outcome === "no_plan") expect(p.run_id).toMatch(/^run_/);
  await shot(page, info, "06-frontier", "stage");

  await page.getByRole("tab", { name: "Stress matrix" }).click();
  await expect(page.getByTestId("run-stress")).toBeEnabled({ timeout: 60_000 });
  await page.getByTestId("run-stress").click();
  await expect(page.getByTestId("stress-matrix")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByTestId("analysis-status").first()).toHaveAttribute("data-status", "completed", { timeout: 300_000 });
  await expect(page.getByTestId("stress-cell")).toHaveCount(9);
  const stressId = new URL(page.url()).searchParams.get("analysis");
  const stress = await (await page.request.get(`/api/v2/analyses/${stressId}`)).json();
  expect(stress.result.cells).toHaveLength(9);
  for (const c of stress.result.cells) {
    expect(c.run_id).toMatch(/^run_/);
    if (!c.deliverable) expect(c.production_kg).toBeNull();
  }
  await shot(page, info, "07-stress", "stage");

  // Impact and SDG proxies from the server
  await nav(page, "Impact");
  await expect(page.getByTestId("impact")).toBeVisible();
  await page.getByRole("tab", { name: "SDG proxies" }).click();
  await expect(page.getByTestId("sdg-card").first()).toBeVisible();
  await expect(page.getByTestId("sdg-score")).toHaveCount(0);
  await shot(page, info, "08-impact-sdg", "stage");

  // 4:25 — report
  await page.getByRole("navigation", { name: "Impact views" }).getByRole("link", { name: "Action plan & report" }).click();
  await expect(page.getByTestId("report")).toBeVisible();
  await expect(page.getByTestId("report")).toContainText(second);
  await shot(page, info, "09-report", "stage");

  // Evidence for the viewed pilot only
  await nav(page, "Evidence");
  await expect(page.getByTestId("evidence")).toBeVisible();
  await expect(page.getByTestId("evidence-hit").filter({ hasText: "AOI selection" }).first()).toContainText("pilot A");
  await shot(page, info, "10-evidence", "stage");

  // A shared compare link rebuilds the ladder from the server after a reload
  await page.goto(`/p/${PILOT}/${VERSION}/compare?run=${second}`);
  await expect(page.getByTestId("ladder")).toBeVisible();
  for (const k of ["B0", "B1", "P"]) await expect(page.getByTestId("ladder")).toContainText(k);

  expect(problems).toEqual([]);
});
