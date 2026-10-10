import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/**
 * W8 fallback recording: the guided tour with video on, one 1920×1080 project. The spec reads
 * AAB_RECORD=1 and overlays a permanent "RECORDED" badge so the video can never pass as live.
 * `make record-tour` copies the video to evidence/rehearsal/tour-<UTC>.webm.
 */
export default defineConfig({
  ...base,
  testMatch: /journey-tour\.spec\.ts/,
  outputDir: "../evidence/playwright-record",
  reporter: [["list"]],
  timeout: 900_000,
  use: {
    ...base.use,
    viewport: { width: 1920, height: 1080 },
    video: { mode: "on", size: { width: 1920, height: 1080 } },
  },
  projects: [{ name: "record-1080", use: { viewport: { width: 1920, height: 1080 } } }],
});
