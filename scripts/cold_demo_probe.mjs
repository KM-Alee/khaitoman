// W8 cold-start probe (run in the e2e image right after `make demo`): waits for the first healthy
// API response, then opens the landing page and starts the guided tour, and writes the measured
// times to evidence/benchmarks/cold-demo-<UTC>.json. T0 (epoch ms, when `make demo` was started)
// comes from the environment so the container's own start-up is included.
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = createRequire(join(root, "web", "package.json"))("@playwright/test");
const base = process.env.BASE_URL || "http://demo:8000";
const t0 = Number(process.env.T0_MS || Date.now());
const since = () => Date.now() - t0;

let health = null;
let healthyMs = null;
for (let i = 0; i < 600; i++) {
  try {
    const r = await fetch(`${base}/api/v2/health`);
    if (r.ok) {
      health = await r.json();
      healthyMs = since();
      break;
    }
  } catch {
    /* not up yet */
  }
  await new Promise((r) => setTimeout(r, 250));
}
if (healthyMs === null) {
  console.error("demo never became healthy");
  process.exit(1);
}
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1200 } });
await page.goto(base);
await page.getByTestId("headline-insight").waitFor({ timeout: 120_000 });
const landingMs = since();
await page.getByTestId("landing-tour").click();
await page.getByTestId("tour-card").waitFor({ timeout: 120_000 });
const tourMs = since();
await browser.close();
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
const out = {
  check: "W8 cold start: make down, then make demo (frozen app image)",
  started_at: new Date(t0).toISOString(),
  base_url: base,
  ms_to_first_healthy_response: healthyMs,
  ms_to_landing_with_headline: landingMs,
  ms_to_first_tour_step: tourMs,
  health,
};
mkdirSync(join(root, "evidence", "benchmarks"), { recursive: true });
const file = join(root, "evidence", "benchmarks", `cold-demo-${stamp}.json`);
writeFileSync(file, JSON.stringify(out, null, 2) + "\n");
console.log(JSON.stringify(out));
