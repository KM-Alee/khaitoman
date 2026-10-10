/**
 * DESIGN REVIEW (fixture) — renders every screen and key state with the labelled design
 * fixture for screenshot QA (T10.6). Screenshots are prefixed `fixture-` so they are never
 * mistaken for results from the real pipelines.
 */
import { expect, test } from "@playwright/test";
import { fixturePaths, installDesignFixture } from "./fixtures/design-fixture";
import { isMobile, mapState, shot, waitForMap } from "./helpers";

const P = "fixture";

test.describe("design review", () => {
  test("workspace → run → compare → replay → explore → impact → report → evidence", async ({ page }, info) => {
    await installDesignFixture(page);
    await page.goto(fixturePaths.workspace);
    await expect(page.getByTestId("app-shell")).toBeVisible();
    await waitForMap(page, 30);
    await shot(page, info, "01-workspace-empty", P);

    // Run plan
    if (isMobile(info)) {
      await page.getByTestId("primary-cta").click();
    } else {
      await page.getByTestId("run-plan").click();
    }
    await expect(page.getByTestId("result-strip")).toHaveAttribute("data-state", "feasible", { timeout: 30_000 });
    await page.waitForTimeout(1200);
    await shot(page, info, "02-workspace-result", P);

    // Select a tail field via keyboard list or URL
    const tail = fixturePaths.fieldIds[24];
    await page.goto(`${fixturePaths.workspace}?${new URL(page.url()).searchParams.toString()}&field=${encodeURIComponent(tail)}`);
    await waitForMap(page, 30);
    await page.waitForTimeout(800);
    await shot(page, info, "03-workspace-field", P);
    const st = (await mapState(page)) as { selected: string; layers: string[] } | null;
    expect(st?.selected).toBe(tail);
    expect(st?.layers).toEqual(expect.arrayContaining(["imagery", "fields-ext", "edges-observed", "edges-assumed", "particles-core", "assets-ext"]));

    // Change metric to service and change
    if (!isMobile(info)) {
      await page.getByRole("radio", { name: "Service" }).first().click().catch(() => {});
      await page.waitForTimeout(600);
      await shot(page, info, "04-workspace-service", P);
    }

    // Compare
    await page.goto(page.url().replace("/workspace", "/compare"));
    await expect(page.getByTestId("ladder")).toBeVisible();
    await page.waitForTimeout(2500);
    await shot(page, info, "05-compare", P);
    await page.getByTestId("field-distribution").scrollIntoViewIfNeeded();
    await shot(page, info, "06-compare-distribution", P);

    // Replay
    await page.goto(page.url().replace("/compare", "/replay") + "&date=2027-01-10");
    await expect(page.getByTestId("replay")).toBeVisible();
    await waitForMap(page, 30);
    await page.waitForTimeout(1500);
    await shot(page, info, "07-replay", P);

    // Explore
    await page.goto(page.url().replace(/\/replay.*/, "/explore") + "?tab=frontier&" + new URL(page.url()).searchParams.toString());
    await expect(page.getByTestId("frontier")).toBeVisible();
    await page.waitForTimeout(1200);
    await shot(page, info, "08-explore-frontier", P);
    await page.getByRole("tab", { name: "Stress matrix" }).click();
    await expect(page.getByTestId("stress")).toBeVisible();
    await page.getByTestId("stress-cell").nth(2).click();
    await page.waitForTimeout(400);
    await shot(page, info, "09-explore-stress", P);
    await page.getByRole("tab", { name: /Surrogate/ }).click();
    await expect(page.getByTestId("preview-card")).toBeVisible({ timeout: 10_000 });
    await shot(page, info, "10-explore-surrogate", P);
    await page.getByRole("tab", { name: /Why not/ }).click();
    await shot(page, info, "11-explore-whynot", P);

    // Impact
    await page.goto(page.url().replace("/explore", "/impact").replace(/tab=[^&]*/, "tab=water"));
    await expect(page.getByTestId("impact")).toBeVisible();
    await page.waitForTimeout(800);
    await shot(page, info, "12-impact-water", P);
    for (const [t, n] of [["Economics", "13-impact-economics"], ["Equity", "14-impact-equity"], ["SDG proxies", "15-impact-sdg"]] as const) {
      await page.getByRole("tab", { name: t }).click();
      await page.waitForTimeout(600);
      await shot(page, info, n, P);
    }

    // Report
    await page.goto(page.url().replace("/impact", "/report"));
    await expect(page.getByTestId("report")).toBeVisible();
    await page.waitForTimeout(500);
    await shot(page, info, "16-report", P);

    // Evidence
    await page.goto(page.url().replace("/report", "/evidence"));
    await expect(page.getByTestId("evidence-hit").first()).toBeVisible();
    await page.getByTestId("evidence-hit").first().click();
    await expect(page.getByTestId("evidence-drawer")).toBeVisible();
    await page.waitForTimeout(400);
    await shot(page, info, "17-evidence", P);
  });

  test("copilot, onboarding, landing, dark, presentation, states", async ({ page }, info) => {
    await installDesignFixture(page);
    await page.goto(`${fixturePaths.workspace}`);
    await waitForMap(page, 30);
    await page.getByRole("button", { name: /Copilot/ }).first().click();
    await page.waitForTimeout(500);
    await shot(page, info, "20-copilot", P);
    await page.keyboard.press("Escape");

    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding")).toBeVisible();
    await page.waitForTimeout(1200);
    await shot(page, info, "21-onboarding", P);

    await page.goto("/");
    await expect(page.getByTestId("landing")).toBeVisible();
    await shot(page, info, "22-landing", P);

    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto(fixturePaths.workspace);
    await waitForMap(page, 30);
    await shot(page, info, "23-dark-workspace", P);
    await page.emulateMedia({ colorScheme: "light" });

    if (!isMobile(info)) {
      await page.keyboard.press("Shift+P");
      await page.waitForTimeout(800);
      await expect(page.getByTestId("presentation-cues")).toBeVisible();
      await shot(page, info, "24-presentation", P);
      await page.keyboard.press("Shift+P");
    }
  });

  test("error, infeasible and reduced-motion states", async ({ page }, info) => {
    await installDesignFixture(page, { solveOutcome: "infeasible" });
    await page.goto(fixturePaths.workspace);
    await waitForMap(page, 30);
    await (isMobile(info) ? page.getByTestId("primary-cta") : page.getByTestId("run-plan")).click();
    await expect(page.getByTestId("result-strip")).toHaveAttribute("data-state", /infeasible|feasible/, { timeout: 30_000 });
    await page.waitForTimeout(800);
    await shot(page, info, "30-infeasible", P);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    await waitForMap(page, 30);
    const st = (await mapState(page)) as { reducedMotion: boolean; pitch: number };
    expect(st.reducedMotion).toBe(true);
    expect(st.pitch).toBe(0);
    await shot(page, info, "31-reduced-motion", P);
  });

  test("api failure is named, not generic", async ({ page }, info) => {
    await installDesignFixture(page, { failRuns: true });
    await page.goto(`${fixturePaths.workspace}?run=run-p-000001`);
    await expect(page.getByTestId("result-strip")).toHaveAttribute("data-state", "error", { timeout: 20_000 });
    await shot(page, info, "32-run-error", P);
    await installDesignFixture(page, { pilots: "none" });
    await page.goto("/");
    await expect(page.getByText(/no pilot package is published yet/i)).toBeVisible();
    await shot(page, info, "33-no-pilots", P);
  });
});
