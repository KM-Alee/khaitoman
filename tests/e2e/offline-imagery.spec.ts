/**
 * High-resolution display imagery (docs/IMAGERY.md). Esri tiles are ALWAYS mocked here — CI never
 * calls the real ArcGIS API. Covers: tiles requested with the key, the Layers switch, visible
 * attribution, and the Sentinel-2 fallback when the network fails or the key is rejected.
 * Builds without VITE_ARCGIS_KEY assert the switch is disabled instead.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { mapState, shot, waitForMap } from "./helpers";

const TILE = readFileSync(resolve(__dirname, "fixtures/hd-tile.png"));
const ESRI = /ibasemaps-api\.arcgis\.com/;

type St = { layers: string[] };
const layers = async (page: Page) => ((await mapState(page)) as St | null)?.layers ?? [];
const hdVisibility = (page: Page) =>
  page.evaluate(() => {
    const m = (window as unknown as { __aabMap?: { map: { getLayer: (id: string) => unknown; getLayoutProperty: (id: string, p: string) => unknown } } }).__aabMap?.map;
    return m?.getLayer("imagery-hd") ? (m.getLayoutProperty("imagery-hd", "visibility") ?? "visible") : "absent";
  });

async function openLayers(page: Page) {
  await page.getByRole("button", { name: "Map layers" }).first().click();
  return page.getByRole("switch", { name: /High-res imagery/ });
}

test.describe("high-res imagery (mocked Esri)", () => {
  test("tiles, layers switch, attribution", async ({ page }, info) => {
    const hits: string[] = [];
    await page.route(ESRI, (r) => {
      hits.push(r.request().url());
      return r.fulfill({ status: 200, contentType: "image/png", body: TILE });
    });
    await page.goto("/");
    await waitForMap(page);
    const keyed = (await layers(page)).includes("imagery-hd");
    const sw = await openLayers(page);
    if (!keyed) {
      await expect(sw).toBeDisabled();
      await expect(page.getByText("Add VITE_ARCGIS_KEY to .env to enable")).toBeVisible();
      expect(hits).toHaveLength(0);
      return;
    }
    await expect.poll(() => hits.length).toBeGreaterThan(0);
    expect(hits.every((u) => /[?&]token=[^&]+/.test(u))).toBe(true);
    await expect(sw).toBeChecked();
    expect(await hdVisibility(page)).toBe("visible");
    const attrib = await page.locator(".maplibregl-ctrl-attrib-inner").first().textContent();
    expect(attrib ?? "").toContain("Esri");
    await page.keyboard.press("Escape");
    await shot(page, info, "imagery-hd-on");

    await (await openLayers(page)).click();
    await expect.poll(() => hdVisibility(page)).toBe("none");
    await page.keyboard.press("Escape");
    await shot(page, info, "imagery-hd-off");
    await (await openLayers(page)).click();
    await expect.poll(() => hdVisibility(page)).toBe("visible");
  });

  test("network failure keeps Sentinel-2 and raises no errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route(ESRI, (r) => r.abort("internetdisconnected"));
    await page.goto("/");
    await waitForMap(page);
    expect(await layers(page)).toContain("imagery");
    expect(errors).toEqual([]);
  });

  test("rejected key drops the HD layer, Sentinel-2 remains", async ({ page }) => {
    await page.route(ESRI, (r) => r.fulfill({ status: 498, contentType: "application/json", body: '{"error":{"code":498,"message":"Invalid token."}}' }));
    await page.goto("/");
    await waitForMap(page);
    await expect.poll(async () => (await layers(page)).includes("imagery-hd"), { timeout: 20_000 }).toBe(false);
    expect(await layers(page)).toContain("imagery");
    const sw = await openLayers(page);
    await expect(sw).toBeDisabled();
  });
});
