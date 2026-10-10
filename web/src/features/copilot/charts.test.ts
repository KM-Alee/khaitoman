import { buildChart, ECHART_KINDS, type ChartTheme } from "./charts";
import { cellText, toTSV } from "./format";
import { SMOKE, smokeVisuals } from "./__fixtures__/smoke";
import { CHART_KINDS, type VisualBlock } from "./types";

const T: ChartTheme = {
  ink: "#111",
  ink2: "#222",
  ink3: "#333",
  border: "#ccc",
  surface: "#fff",
  muted: "#eee",
  water: "#087f8c",
  wheat: "#b07d1c",
  warning: "#975306",
  danger: "#a63e32",
  series: ["#087f8c", "#a35b08", "#6b4ea0", "#386a4b"],
  seq: ["#0", "#1", "#2", "#3", "#4", "#5"],
  divNeg: "#neg",
  divPos: "#pos",
  font: "Inter",
};

type Series = { type: string; name?: string; data: unknown[]; links?: { value: number }[] };
const seriesOf = (b: VisualBlock) => (buildChart(b, T, "en")!.option as { series: Series[] }).series;

/** All smoke visuals (real gpt-6-luna answers) with the chart kind each one used. */
const ALL = Object.keys(SMOKE.turns).flatMap((k) => smokeVisuals(k).map((v) => [k, v] as const));

test("the fixture covers the chart kinds the live smoke produced", () => {
  expect(new Set(ALL.map(([, v]) => v.chart))).toEqual(new Set(["bar", "steps", "table", "heatmap", "kpi", "grouped_bar", "map", "sankey", "stacked_bar"]));
});

test("every chart kind is either an ECharts option or a React view", () => {
  for (const k of CHART_KINDS) {
    const b = { ...smokeVisuals("S1")[0], chart: k } as VisualBlock;
    const out = buildChart(b, T, "en");
    if (ECHART_KINDS.includes(k)) expect(out === null || typeof out.option === "object").toBe(true);
    else expect(out).toBeNull();
  }
});

test("bar values are the served row values, one per row, gaps stay gaps", () => {
  for (const [, v] of ALL.filter(([, x]) => ["bar", "grouped_bar", "stacked_bar"].includes(x.chart))) {
    const ys = v.encoding.y ?? [];
    const series = seriesOf(v).filter((s) => s.type === "bar" && s.data.length);
    expect(series).toHaveLength(ys.length);
    series.forEach((s, i) => {
      const want = v.rows.map((r) => (typeof r[ys[i]] === "number" ? r[ys[i]] : "-"));
      expect(s.data.map((d) => (d as { value: unknown }).value)).toEqual(want);
    });
  }
});

test("the stress matrix draws one tile per cell; undeliverable cells are tiles without a value", () => {
  const hm = smokeVisuals("S3").find((v) => v.chart === "heatmap")!;
  const built = buildChart(hm, T, "en")!;
  const [tiles] = (built.option as { series: Series[] }).series;
  expect(tiles.type).toBe("custom");
  expect(tiles.data).toHaveLength(hm.rows.length);
  const deliverable = hm.rows.filter((r) => typeof r.production_kg === "number");
  const order = hm.rows.map((_, i) => built.rowAt(0, i)!);
  expect(order.slice(0, deliverable.length).map((r) => r.production_kg)).toEqual(deliverable.map((r) => r.production_kg));
  expect(order.slice(deliverable.length).every((r) => r.production_kg === null && r.status === "undeliverable")).toBe(true);
});

test("the water sankey links carry the ledger volumes", () => {
  const sk = smokeVisuals("S7").find((v) => v.chart === "sankey")!;
  const links = seriesOf(sk)[0].links!;
  expect(links.map((l) => l.value)).toEqual(sk.rows.map((r) => r.m3));
});

test("frontier joins only the nondominated points", () => {
  const base = smokeVisuals("S1")[0];
  const fr: VisualBlock = {
    ...base,
    chart: "frontier",
    // TEST FIXTURE rows (labelled synthetic), shaped like the frontier dataset.
    columns: [
      { key: "capital_commitment_pkr", label: "Capital spent", kind: "number", unit: "PKR" },
      { key: "production_kg", label: "Crop production", kind: "number", unit: "kg" },
      { key: "dominance", label: "Trade-off position", kind: "status" },
      { key: "run_id", label: "Run", kind: "id", ref: "run" },
    ],
    rows: [
      { capital_commitment_pkr: 3, production_kg: 30, dominance: "nondominated", run_id: "run_c" },
      { capital_commitment_pkr: 1, production_kg: 10, dominance: "nondominated", run_id: "run_a" },
      { capital_commitment_pkr: 2, production_kg: 5, dominance: "dominated", run_id: "run_b" },
      { capital_commitment_pkr: 4, production_kg: null, dominance: "not_applicable", run_id: "run_x" },
    ],
    encoding: { x: "capital_commitment_pkr", y: ["production_kg"], color: "dominance", id: "run_id" },
  };
  const [line, ...pts] = seriesOf(fr);
  expect(line.type).toBe("line");
  expect(line.data).toEqual([
    [1, 10],
    [3, 30],
  ]);
  expect(pts.reduce((n, s) => n + s.data.length, 0)).toBe(3); // the infeasible point has no coordinates
});

test("cells format with the column or row unit; null is a dash, never zero", () => {
  const kpi = smokeVisuals("S3").find((v) => v.chart === "kpi")!;
  const vc = kpi.columns.find((c) => c.key === "value")!;
  const prod = kpi.rows.find((r) => r.metric_id === "production_kg")!;
  expect(cellText(prod.value, vc, prod)).toMatch(/t$/);
  expect(cellText(null, vc, prod)).toBe("—");
  const ratio = kpi.rows.find((r) => r.unit === "ratio")!;
  expect(cellText(ratio.value, vc, ratio)).toMatch(/%$/);
});

test("copied data keeps server values and units", () => {
  const sk = smokeVisuals("S7").find((v) => v.chart === "sankey")!;
  const tsv = toTSV(sk.columns, sk.rows).split("\n");
  expect(tsv[0]).toContain("[m3]");
  expect(tsv[1].split("\t")[2]).toBe(String(sk.rows[0].m3));
});

test("bar columns with different units become separate panels, never a second axis", async () => {
  const { splitByUnit } = await import("./charts");
  const side = smokeVisuals("S5").find((v) => v.chart === "grouped_bar")!;
  const parts = splitByUnit(side);
  expect(parts.length).toBeGreaterThan(1);
  for (const p of parts) expect(new Set((p.encoding.y ?? []).map((k) => side.columns.find((c) => c.key === k)!.unit)).size).toBe(1);
});
