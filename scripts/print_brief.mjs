// W6: print the seeded plan's action-plan report to one PDF (evidence/print/brief-<UTC>.pdf).
// Runs in the e2e image:  make print-brief   (BASE_URL defaults to the dev web server).
// Uses the stored P run named by GET /api/v2/demo/session; fails loudly if there is none.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Resolve Playwright from the web workspace (ESM ignores NODE_PATH); write under the repo root.
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = createRequire(join(root, "web", "package.json"))("@playwright/test");

const base = process.env.BASE_URL || process.env.PLAYWRIGHT_BASE_URL || "http://web:5173";
const res = await fetch(`${base}/api/v2/demo/session`);
if (!res.ok) {
  console.error(`demo session unavailable (${res.status}); run make demo-seed`);
  process.exit(1);
}
const s = await res.json();
const run = s.base?.runs?.P;
if (!run) {
  console.error("demo session has no P run");
  process.exit(1);
}
const url = `${base}/p/${encodeURIComponent(s.pilot_id)}/${encodeURIComponent(s.pilot_version)}/report?run=${encodeURIComponent(run)}`;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
await page.addInitScript(() => localStorage.setItem("aabflow-ui", JSON.stringify({ state: { theme: "light", tourSeen: true }, version: 1 })));
await page.goto(url, { waitUntil: "networkidle" });
await page.locator('[data-tour="report"]').waitFor({ timeout: 60_000 });
await page.waitForTimeout(1500);
await page.evaluate(() => {
  document.documentElement.dataset.printBrief = "1";
});
await page.emulateMedia({ media: "print" });
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
mkdirSync(join(root, "evidence", "print"), { recursive: true });
const out = join(root, "evidence", "print", `brief-${stamp}.pdf`);
await page.pdf({ path: out, format: "A4", printBackground: true, margin: { top: "12mm", bottom: "12mm", left: "10mm", right: "10mm" } });
await browser.close();
console.log(`${out} · run ${run} · ${url}`);
