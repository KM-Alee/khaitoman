import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { contrast, makeScale, ramp } from "./palette";

const css = readFileSync(resolve(process.cwd(), "src/app/index.css"), "utf8");
function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}
const light = block(":root {");
const dark = { ...light, ...block(':root[data-theme="dark"]') };

describe.each([
  ["light", light],
  ["dark", dark],
])("WCAG AA contrast (%s theme, measured)", (_name, t) => {
  test.each(["canvas", "surface", "surface-muted"])("text on %s", (bg) => {
    expect(contrast(t.ink, t[bg])).toBeGreaterThanOrEqual(7);
    expect(contrast(t["ink-secondary"], t[bg])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t["ink-tertiary"], t[bg])).toBeGreaterThanOrEqual(4.5);
  });
  test("status colours readable on their soft backgrounds and surface", () => {
    for (const k of ["water-deep", "vegetation", "warning", "danger"]) {
      expect(contrast(t[k], t.surface)).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(t["water-deep"], t["water-soft"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.warning, t["warning-soft"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.danger, t["danger-soft"])).toBeGreaterThanOrEqual(4.5);
  });
  test("primary button text and focus ring", () => {
    expect(contrast(t["on-water"], t.water)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t["on-water"], t["water-deep"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.focus, t.surface)).toBeGreaterThanOrEqual(3);
    expect(contrast(t["border-strong"], t.surface)).toBeGreaterThanOrEqual(3);
  });
});

test("diverging scale is symmetric with an explicit zero", () => {
  const s = makeScale("diverging", [-20, 50]);
  expect(s.domain).toEqual([-50, 50]);
  expect(s.norm(-50)).toBe(1);
  expect(s.norm(0)).toBe(0);
  expect(s.color(null)).toBe(s.noData);
});

test("shared domains keep compared maps on one scale", () => {
  const a = makeScale("sequential-yield", [3000, 4000], [2000, 5000]);
  expect(a.domain).toEqual([2000, 5000]);
  expect(a.norm(3500)).toBeCloseTo(0.5);
  expect(ramp(["#000000", "#ffffff"], 0.5)).toBe("#808080");
});
