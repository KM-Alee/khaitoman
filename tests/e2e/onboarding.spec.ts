/**
 * Onboarding wizard against the REAL API (PRD §5.3, T2.6, T9.3): AOI from a raw source
 * package → server AOI check → intake → process job (cached Delineate run, no new
 * inference) → review with a real 409 → validation. It stops before publish so no pilot
 * version is created. Not in the default testMatch (it writes intake records); run with
 * AAB_LIVE_SPECS=1 npx playwright test onboarding.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

interface RawPackage {
  bundle_id: string;
  pilot_id: string | null;
  bundle_ref: string;
  aoi?: unknown;
}

async function rawPackage(request: APIRequestContext): Promise<RawPackage> {
  const response = await request.get("/api/v2/onboarding/raw-packages");
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as { packages: RawPackage[] };
  const pkg = body.packages.find((p) => p.pilot_id === "pilot-b" && p.aoi) ?? body.packages.find((p) => p.aoi);
  expect(pkg, "a raw source bundle with a listed AOI").toBeTruthy();
  return pkg!;
}

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).include("[data-testid=onboarding]").exclude(".maplibregl-canvas").analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test("AOI and sources use the server check and the raw package list", async ({ page }) => {
  const pkg = await rawPackage(page.request);
  await page.goto("/onboarding");
  await expect(page.getByTestId("onboarding-new")).toBeVisible();
  await expect(page.getByTestId("start-onboarding")).toBeDisabled();
  await page.getByLabel("Raw source package").selectOption(pkg.bundle_ref);
  const check = page.getByTestId("aoi-check");
  await expect(check.getByText(/ha \(\d+\.\d+ km²\)/)).toBeVisible();
  await expect(check.getByText("Within the server limits")).toBeVisible();
  await expect(page.getByTestId("start-onboarding")).toBeEnabled();
  expect(await seriousViolations(page)).toEqual([]);

  await page.getByLabel("AOI GeoJSON").fill(JSON.stringify({ type: "Polygon", coordinates: [[[72, 30], [72.2, 30], [72.2, 30.2], [72, 30.2], [72, 30]]] }));
  await page.getByRole("button", { name: "Use GeoJSON" }).click();
  await expect(check.getByText(/exceeds the 25 km² limit/)).toBeVisible();
  await expect(page.getByTestId("start-onboarding")).toBeDisabled();
});

test("raw package intake runs the process job and opens a version-checked review", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-1920", "one real intake per run; the layout projects cover the AOI step");
  test.setTimeout(300_000);
  const pkg = await rawPackage(page.request);

  await page.goto("/onboarding");
  await page.getByLabel("Raw source package").selectOption(pkg.bundle_ref);
  await expect(page.getByTestId("aoi-check").getByText("Within the server limits")).toBeVisible();
  await page.getByLabel("Region name (optional)").fill(`e2e wizard ${pkg.pilot_id ?? ""}`.trim());
  await page.getByTestId("start-onboarding").click();

  await page.waitForURL(/\/onboarding\/onb_[0-9a-f]+$/);
  const intakeId = page.url().split("/").pop()!;
  await expect(page.getByTestId("processing")).toBeVisible();
  // Stage text comes from the worker; wait for the server state, never a timer.
  await expect(page.getByTestId("intake-state")).toHaveText(/Needs review|Awaiting inference|Failed/, { timeout: 240_000 });
  const state = await page.getByTestId("intake").getAttribute("data-state");
  expect(state, "cached Delineate run should yield a review").toBe("needs_review");
  await expect(page.getByTestId("stage-log")).toContainText("process:inference");

  const table = page.getByTestId("field-table");
  await expect(table.getByRole("row")).not.toHaveCount(0);
  await expect(page.getByTestId("imagery-table")).toBeVisible();
  await expect(page.getByTestId("validation")).toContainText("not reviewed");
  await expect(page.getByTestId("publish-button")).toBeDisabled();

  const firstField = table.getByRole("row").nth(1).getByRole("button");
  await firstField.click();
  await page.getByTestId("edit-reason").fill("e2e: rejected to exercise the review path");
  await page.getByTestId("add-edit").click();
  await expect(page.getByTestId("staged-edits")).toBeVisible();
  await page.getByTestId("capacity").fill("0.1");
  await page.getByTestId("acknowledge").check();
  await page.getByLabel("Reviewer (logged with this version)").fill("playwright e2e");
  await page.getByTestId("apply-review").click();
  await expect(page.getByTestId("apply-review")).toHaveText(/v1 → v2/, { timeout: 60_000 });
  await expect(page.getByTestId("staged-edits")).toContainText("e2e: rejected");

  // Another client moves the review to v2; this view still holds v1 → a real 409.
  const view = await (await page.request.get(`/api/v2/onboarding/${intakeId}`)).json();
  const bump = await page.request.patch(`/api/v2/onboarding/${intakeId}/review`, {
    data: { expected_version: view.review_version, field_edits: view.review?.field_edits ?? [], reviewer: "second client" },
    headers: { "Idempotency-Key": `e2e-bump-${intakeId}` },
  });
  expect(bump.status(), await bump.text()).toBe(200);
  await page.getByTestId("apply-review").click();
  const conflict = page.getByTestId("review-conflict");
  await expect(conflict).toContainText("Nothing was written");
  await conflict.getByRole("button", { name: "Reload the current review" }).click();
  await expect(page.getByTestId("apply-review")).toHaveText(/v2 → v3/);

  await expect(page.getByTestId("validation")).toBeVisible();
  await expect(page.getByTestId("publish-version")).toHaveValue(/^reviewed-v\d+$/);
  expect(await seriousViolations(page)).toEqual([]);
  // Stop here: publishing would create an immutable pilot version in the data directory.
});
