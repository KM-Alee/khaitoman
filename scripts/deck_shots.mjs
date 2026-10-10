// Clean 1920×1080 screenshots of the real app for the pitch deck (docs/pitch/shots/*.png).
// Runs in the e2e image against a running stack: BASE_URL defaults to the frozen demo.
// Every screen shows stored results from the seeded demo session; nothing is staged.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = createRequire(join(root, "web", "package.json"))("@playwright/test");
const base = process.env.BASE_URL || "http://demo:8000";
const outDir = join(root, "docs", "pitch", "shots");
mkdirSync(outDir, { recursive: true });

const s = await (await fetch(`${base}/api/v2/demo/session`)).json();
const p = `/p/${s.pilot_id}/${s.pilot_version}`;
const P = s.base.runs.P;
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });

async function page(theme = "dark") {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await ctx.addInitScript((t) => localStorage.setItem("aabflow-ui", JSON.stringify({ state: { tourSeen: true, theme: t, motion: "reduced" }, version: 1 })), theme);
  return ctx.newPage();
}
async function mapIdle(pg) {
  await pg
    .waitForFunction(() => {
      const m = window.__aabMap;
      return !!m && m.debugState().fields > 0 && m.map.isStyleLoaded() && m.map.areTilesLoaded();
    }, null, { timeout: 90_000 })
    .catch(() => undefined);
  await pg.waitForTimeout(2500);
}
async function shot(pg, name) {
  await pg.screenshot({ path: join(outDir, `${name}.png`), timeout: 120_000 });
  console.log(name);
}

const pg = await page("dark");
await pg.goto(`${base}/`);
await pg.getByTestId("headline-insight").waitFor();
await pg.waitForTimeout(1500);
await shot(pg, "01-landing");
await pg.getByTestId("headline-insight").scrollIntoViewIfNeeded();
await pg.evaluate(() => window.scrollBy(0, -40));
await pg.waitForTimeout(800);
await shot(pg, "02-headline");

// 3D map of the recommended plan, assistant closed, orbit pose.
await pg.goto(`${base}${p}/workspace?run=${P}`);
await mapIdle(pg);
await pg.evaluate(() => {
  const m = window.__aabMap.map;
  m.jumpTo({ pitch: 58, bearing: -28, zoom: m.getZoom() + 0.25 });
});
await mapIdle(pg);
await shot(pg, "03-map-3d");

// Raw AI outlines (the reveal), 2D-ish for clarity.
const raw = await page("dark");
await raw.goto(`${base}${p}/workspace?run=${P}`);
await mapIdle(raw);
await raw.evaluate(() => {
  window.__aabMap.setRawVisible(true);
  window.__aabMap.setRawOpacity(1, 0);
  window.__aabMap.map.jumpTo({ pitch: 0, bearing: 0 });
});
await mapIdle(raw);
await shot(raw, "04-ai-raw-fields");

await pg.goto(`${base}${p}/explore?tab=surrogate&run=${P}&field=${encodeURIComponent(s.focus_field_id)}`);
await pg.getByTestId("preview-yield").waitFor({ timeout: 60_000 });
await pg.waitForTimeout(1200);
await shot(pg, "05-instant-crop");

await pg.goto(`${base}${p}/explore?tab=frontier&analysis=${s.analyses.frontier}&run=${P}`);
await pg.getByTestId("frontier-chart").waitFor({ timeout: 60_000 });
await pg.waitForTimeout(2000);
await shot(pg, "06-frontier");

await pg.goto(`${base}${p}/explore?tab=stress&analysis=${s.analyses.stress}&run=${s.base.runs.R}`);
await pg.getByTestId("stress-matrix").waitFor({ timeout: 60_000 });
await pg.waitForTimeout(2000);
await shot(pg, "07-stress");

if (s.plan_turn_id) {
  await pg.goto(`${base}${p}/plan-season?turn=${s.plan_turn_id}`);
  await pg.getByTestId("plan-timeline").waitFor({ timeout: 60_000 });
  const skip = pg.getByTestId("plan-skip");
  if (await skip.isVisible().catch(() => false)) await skip.click();
  await pg.getByTestId("plan-brief").waitFor({ timeout: 120_000 });
  await mapIdle(pg);
  await shot(pg, "08-plan-season");
}

await pg.goto(`${base}${p}/report?run=${P}`);
await pg.locator('[data-tour="report"]').waitFor({ timeout: 60_000 });
await pg.waitForTimeout(1500);
await shot(pg, "09-report");

await pg.goto(`${base}${p}/evidence?run=${P}`);
await pg.locator('[data-tour="trust"]').waitFor({ timeout: 60_000 }).catch(() => undefined);
await pg.waitForTimeout(1500);
await shot(pg, "10-trust");

await browser.close();
