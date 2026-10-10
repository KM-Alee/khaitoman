import { defineConfig } from "@playwright/test";

/**
 * Two suites (T10.6, T12.4):
 *  - default: the real demo journey against the REAL API (frozen demo image via `make ui-checks`,
 *    or the dev stack with PLAYWRIGHT_BASE_URL=http://web:5173).
 *  - AAB_DESIGN=1: screenshot design review with a labelled DESIGN FIXTURE (tests/e2e/fixtures),
 *    served by a local Vite dev server inside the e2e container. Never claims analytical results.
 * Viewports from T10.6: 1920×1200, 1366×768 and a mobile viewport.
 */
const design = process.env.AAB_DESIGN === "1";
// AAB_LIVE_SPECS=1 adds the live-API specs that write records (impact, onboarding intake/review).
const live = process.env.AAB_LIVE_SPECS === "1";
const gl = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];

export default defineConfig({
  testDir: "../tests/e2e",
  testMatch: design
    ? /design-.*\.spec\.ts/
    : live
      ? /impact.*\.spec\.ts|onboarding.*\.spec\.ts/
      : /journey.*\.spec\.ts|offline.*\.spec\.ts|a11y.*\.spec\.ts/,
  outputDir: "../evidence/playwright-output",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "../evidence/playwright-output/results.json" }]],
  use: {
    baseURL: design ? "http://127.0.0.1:5174" : process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8000",
    launchOptions: { args: gl },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: design
    ? { command: "npx vite --host 127.0.0.1 --port 5174 --strictPort", url: "http://127.0.0.1:5174", reuseExistingServer: true, timeout: 120_000 }
    : undefined,
  projects: [
    { name: "desktop-1920", use: { viewport: { width: 1920, height: 1200 } } },
    { name: "laptop-1366", use: { viewport: { width: 1366, height: 768 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } },
  ],
});
