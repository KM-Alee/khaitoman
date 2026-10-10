/**
 * Guided tour (docs/UI_SYSTEM.md §8) against the REAL API and the seeded demo session
 * (`make demo-seed`): landing headline → start the tour → every step in order → finish card.
 * Each step must show either the "Saved result" label (a stored run/analysis that resolves
 * through the API) or the "Live" label, and no console error or 5xx may happen on the way.
 * A screenshot per step goes to evidence/screenshots/tour-<project>-NN-<slug>.png.
 */
import { expect as baseExpect, test, type Page } from "@playwright/test";
import { shot, waitForMap } from "./helpers";

test.use({ actionTimeout: 60_000 });
const expect = baseExpect.configure({ timeout: 60_000 });

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

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);

test("guided tour over the saved session", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "the tour is presented on a laptop or projector");
  test.setTimeout(900_000);
  const session = await page.request.get("/api/v2/demo/session");
  test.skip(!session.ok(), "no seeded demo session (make demo-seed)");
  expect((await session.json()).complete).toBe(true);
  const problems = watch(page);

  const recording = process.env.AAB_RECORD === "1";
  await page.addInitScript((rec) => {
    localStorage.setItem("aabflow-ui", JSON.stringify({ state: { tourSeen: true, motion: rec ? "full" : "reduced", theme: "dark" }, version: 1 }));
    if (!rec) return;
    // The fallback video must never pass as a live demo.
    const badge = () => {
      if (document.getElementById("aab-recorded")) return;
      const d = document.createElement("div");
      d.id = "aab-recorded";
      d.textContent = "● RECORDED";
      d.style.cssText =
        "position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:2147483647;padding:4px 14px;border-radius:999px;background:#A63E32;color:#fff;font:600 14px/1.4 Inter,system-ui,sans-serif;letter-spacing:.12em;pointer-events:none";
      document.body.appendChild(d);
    };
    document.addEventListener("DOMContentLoaded", badge);
  }, recording);
  await page.goto("/");
  await expect(page.getByTestId("headline-insight")).toBeVisible();
  await expect(page.getByTestId("ai-stack")).toBeVisible();
  await shot(page, info, "00-landing", "tour");

  await page.getByTestId("landing-tour").click();
  const card = page.getByTestId("tour-card");
  await expect(card).toBeVisible();

  const seen: string[] = [];
  for (let i = 1; i <= 20; i++) {
    const title = (await page.getByTestId("tour-title").innerText()).trim();
    seen.push(title);
    if (await page.getByTestId("tour-finish").isVisible()) {
      await shot(page, info, `${String(i).padStart(2, "0")}-finish`, "tour");
      break;
    }
    // Every step is labelled: a saved record that resolves, or explicitly live.
    const saved = page.getByTestId("tour-saved");
    if (await saved.isVisible()) {
      const id = await saved.getAttribute("data-id");
      if (id?.startsWith("run_")) expect((await page.request.get(`/api/v2/runs/${id}`)).ok()).toBe(true);
      if (id?.startsWith("ana_")) expect((await page.request.get(`/api/v2/analyses/${id}`)).ok()).toBe(true);
      if (id?.startsWith("turn_")) expect((await page.request.get(`/api/v2/copilot/turns/${id}`)).ok()).toBe(true);
    } else {
      await expect(page.getByTestId("tour-live")).toBeVisible();
    }
    if (await page.locator('[data-testid="map-slot"]').isVisible()) await waitForMap(page).catch(() => undefined);
    if (title.toLowerCase().includes("reveal")) {
      await expect(page.getByTestId("ai-reveal")).toHaveAttribute("data-phase", "reviewed", { timeout: 20_000 });
    }
    await page.waitForTimeout(recording ? 6000 : 1200);
    await shot(page, info, `${String(i).padStart(2, "0")}-${slug(title)}`, "tour");
    await page.getByTestId("tour-next").click();
    await expect(page.getByTestId("tour-title")).not.toHaveText(title);
  }
  expect(seen.length).toBeGreaterThanOrEqual(10);
  expect(problems).toEqual([]);
});
