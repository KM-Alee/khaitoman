import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page, TestInfo } from "@playwright/test";

export const SHOTS = resolve(__dirname, "../../evidence/screenshots");
mkdirSync(SHOTS, { recursive: true });

/** Save a full-viewport screenshot to evidence/screenshots/<prefix>-<project>-<name>.png */
export async function shot(page: Page, info: TestInfo, name: string, prefix = "real") {
  const file = resolve(SHOTS, `${prefix}-${info.project.name}-${name}.png`);
  // Software WebGL (swiftshader) can take tens of seconds to rasterise a full 1920×1200 frame.
  await page.screenshot({ path: file, fullPage: false, animations: "disabled", timeout: 120_000 });
  return file;
}

/** Wait until the persistent map has data and its style/tiles are idle. */
export async function waitForMap(page: Page, minFields = 1) {
  await page.waitForFunction(
    (n) => {
      const m = (window as unknown as { __aabMap?: { debugState: () => { fields: number }; map: { isStyleLoaded: () => boolean; areTilesLoaded: () => boolean } } }).__aabMap;
      // Not map.loaded(): the animated flow particles update a GeoJSON source every frame,
      // which keeps MapLibre's "sources dirty" flag set even when style and tiles are idle.
      return !!m && m.debugState().fields >= n && m.map.isStyleLoaded() && m.map.areTilesLoaded();
    },
    minFields,
    { timeout: 60_000 },
  );
  await page.waitForTimeout(900);
}

export async function mapState(page: Page) {
  return page.evaluate(() => (window as unknown as { __aabMap?: { debugState: () => unknown } }).__aabMap?.debugState() ?? null);
}

export const isMobile = (info: TestInfo) => info.project.name === "mobile";
