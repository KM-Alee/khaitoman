/**
 * Impact SDG cards against the real API (PRD §8.5, T10).
 * Playwright's default testMatch does not include this file yet; run it by path
 * once the suite config lists impact.spec.ts. Viewports are the config projects:
 * 1920×1200, 1366×768 and mobile.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

interface PilotRow {
  pilot_id: string;
  pilot_version: string;
  versions?: string[];
}
interface RunRow {
  run_id: string;
  outcome: string;
  pilot_id: string;
  pilot_version: string;
}

async function pilots(request: APIRequestContext): Promise<PilotRow[]> {
  const response = await request.get("/api/v2/pilots");
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as { pilots?: PilotRow[] } | PilotRow[];
  return Array.isArray(body) ? body : (body.pilots ?? []);
}

async function planRun(request: APIRequestContext, pilot: PilotRow): Promise<RunRow | null> {
  const version = pilot.pilot_version || pilot.versions?.[0];
  if (!version) return null;
  const response = await request.get(`/api/v2/runs?pilot_id=${encodeURIComponent(pilot.pilot_id)}&pilot_version=${encodeURIComponent(version)}`);
  if (!response.ok()) return null;
  const body = (await response.json()) as { runs?: RunRow[] };
  return (body.runs ?? []).find((run) => run.outcome === "plan") ?? null;
}

async function seriousViolations(page: Page, include: string) {
  const results = await new AxeBuilder({ page }).include(include).analyze();
  return results.violations.filter((item) => item.impact === "serious" || item.impact === "critical");
}

test("health, empty impact and a missing run use the API", async ({ page }) => {
  const health = await page.request.get("/api/v2/health");
  expect(health.ok(), await health.text()).toBeTruthy();
  const list = await pilots(page.request);
  const pilot = list[0];
  const pilotId = pilot?.pilot_id ?? "pilot-a";
  const version = pilot?.pilot_version ?? pilot?.versions?.[0] ?? "reviewed-v1";

  await page.goto(`/p/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/impact`);
  await expect(page.getByTestId("impact-empty")).toBeVisible();
  await expect(page.getByRole("button", { name: "Go to Workspace" })).toBeVisible();
  expect(await seriousViolations(page, "[data-testid=impact]")).toEqual([]);

  await page.goto(`/p/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/impact?run=missing-run-p06&tab=sdg`);
  await expect(page.getByTestId("impact-error")).toBeVisible();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(await seriousViolations(page, "[data-testid=impact]")).toEqual([]);
});

test("SDG cards follow the live impact response", async ({ page }) => {
  const list = await pilots(page.request);
  let found: { pilot: PilotRow; run: RunRow } | null = null;
  for (const pilot of list) {
    const run = await planRun(page.request, pilot);
    if (run) {
      found = { pilot, run };
      break;
    }
  }
  expect(found, "the API has no plan run whose impact cards can be opened").not.toBeNull();
  const pilot = found!.pilot;
  const run = found!.run;
  const version = run.pilot_version || pilot.pilot_version;
  const responsePromise = page.waitForResponse((response) => response.url().includes(`/runs/${encodeURIComponent(run.run_id)}/impact`) && response.ok());
  await page.goto(`/p/${encodeURIComponent(pilot.pilot_id)}/${encodeURIComponent(version)}/impact?run=${encodeURIComponent(run.run_id)}&tab=sdg`);
  const payload = (await (await responsePromise).json()) as {
    cards?: { card: string; official_target_text?: string; official_indicator?: boolean; limitations?: string[]; status?: string }[];
    co2?: { status?: string; value?: number | null };
  };
  await expect(page.getByTestId("sdg-card")).toHaveCount(payload.cards?.length ?? 0);
  for (const card of payload.cards ?? []) {
    const article = page.locator(`[data-testid=sdg-card][data-card="${card.card}"]`);
    await expect(article).toBeVisible();
    if (card.official_target_text) await expect(article.getByTestId("official-target")).toHaveText(card.official_target_text);
    await expect(article.getByTestId("official-indicator")).toHaveText("official_indicator = false");
    expect(card.official_indicator).toBe(false);
    for (const limitation of card.limitations ?? []) await expect(article.getByTestId("limitations")).toContainText(limitation);
    if (card.status) await expect(article).toHaveAttribute("data-status", card.status);
  }
  await expect(page.getByTestId("co2")).toHaveAttribute("data-status", "not_estimated");
  await expect(page.getByTestId("co2-value")).toHaveText("No CO₂ value is shown.");
  expect(payload.co2?.status).toBe("not_estimated");
  expect(payload.co2?.value ?? null).toBeNull();
  await expect(page.getByTestId("sdg-score")).toHaveCount(0);
  expect(await seriousViolations(page, "[data-testid=sdg]")).toEqual([]);
});
