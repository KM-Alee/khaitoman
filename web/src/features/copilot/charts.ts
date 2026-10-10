/**
 * ECharts options for server-built visual blocks (docs/COPILOT.md §3.1). Pure functions:
 * every plotted value is a value from `block.rows`; the only client operations are
 * presentational (ordering categories, picking colours, choosing orientation). Gaps stay
 * gaps: a null value draws no mark and is labelled, never treated as zero.
 */
import type { EOption } from "@/components/charts/EChart";
import { formatDateShort } from "@/lib/formatting";
import { axisFormatter, axisName, cellText, colLabel, displayUnit, statusWord, unitOf, type Lang } from "./format";
import type { ChartKind, Row, VisualBlock, VisualColumn } from "./types";

export interface ChartTheme {
  ink: string;
  ink2: string;
  ink3: string;
  border: string;
  surface: string;
  muted: string;
  water: string;
  wheat: string;
  warning: string;
  danger: string;
  /** Categorical identity, fixed order (validated subset: series-1, -2, -4, -3). */
  series: string[];
  seq: string[];
  divNeg: string;
  divPos: string;
  font: string;
}

export interface BuiltChart {
  option: EOption;
  height: number;
  /** Row behind each clickable mark: (seriesIndex, dataIndex) → row. */
  rowAt: (seriesIndex: number, dataIndex: number) => Row | undefined;
}

/** Chart kinds drawn with ECharts; the rest are React views (kpi, table, map, steps). */
export const ECHART_KINDS: readonly ChartKind[] = ["bar", "grouped_bar", "stacked_bar", "delta_bar", "line", "area", "scatter", "frontier", "heatmap", "sankey"];
export const isEChartKind = (k: ChartKind) => ECHART_KINDS.includes(k);

const col = (b: VisualBlock, key: string | null | undefined): VisualColumn | undefined => (key ? b.columns.find((c) => c.key === key) : undefined);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (v === null || v === undefined ? "—" : String(v));

function uniq(values: unknown[]): string[] {
  const out: string[] = [];
  for (const v of values) {
    const s = str(v);
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

function tooltipBase(t: ChartTheme) {
  return {
    backgroundColor: t.surface,
    borderColor: t.border,
    textStyle: { color: t.ink, fontSize: 12, fontFamily: t.font },
    extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.14);max-width:260px;white-space:normal;",
    confine: true,
  };
}

function rowTooltip(b: VisualBlock, row: Row | undefined, lang: Lang, focus: string[]): string {
  if (!row) return "";
  const keys = [...new Set([b.encoding.label, b.encoding.x, ...(b.encoding.y ?? []), b.encoding.value, b.encoding.series, b.encoding.color, b.encoding.status, ...focus])].filter(
    (k): k is string => !!k,
  );
  return keys
    .map((k) => {
      const c = col(b, k);
      if (!c) return "";
      return `<div style="display:flex;justify-content:space-between;gap:12px"><span style="opacity:.75">${esc(colLabel(c, lang, false))}</span><b>${esc(cellText(row[k], c, row, lang))}</b></div>`;
    })
    .join("");
}

const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch] ?? ch);

function catLabel(b: VisualBlock, row: Row, key: string | null | undefined, lang: Lang): string {
  const c = col(b, key);
  if (!c || !key) return "";
  const v = row[key];
  if (c.kind === "date" && typeof v === "string") return formatDateShort(v);
  return cellText(v, c, row, lang);
}

function idOf(b: VisualBlock, row: Row): string | null {
  const k = b.encoding.id;
  if (k && row[k] !== null && row[k] !== undefined) return String(row[k]);
  return null;
}

/** Colour of a categorical value in fixed order of first appearance (never by rank). */
function catColors(values: string[], t: ChartTheme): Map<string, string> {
  const m = new Map<string, string>();
  values.forEach((v, i) => m.set(v, t.series[i % t.series.length]));
  return m;
}

/* ------------------------------------------------------------------ bars */

function bars(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart {
  const rows = b.rows;
  const x = b.encoding.x;
  const ys = (b.encoding.y ?? []).filter((k) => col(b, k));
  const highlight = new Set(b.highlight_ids ?? []);
  const cats = rows.map((r) => catLabel(b, r, x, lang));
  const horizontal = rows.length > 7 || cats.some((c) => c.length > 14);
  const unit = unitOf(col(b, ys[0])!, rows[0]);
  const maxAbs = Math.max(0, ...rows.flatMap((r) => ys.map((k) => Math.abs(num(r[k]) ?? 0))));
  const fmt = axisFormatter(unit, maxAbs);
  const delta = b.chart === "delta_bar";
  const stacked = b.chart === "stacked_bar";
  const colorKey = b.encoding.color && col(b, b.encoding.color)?.kind !== "number" ? b.encoding.color : null;
  const colorVals = colorKey ? uniq(rows.map((r) => r[colorKey])) : [];
  const colorMap = catColors(colorVals, t);
  const multi = ys.length > 1;
  const statusKey = b.encoding.status;

  const series = ys.map((yk, si) => {
    const c = col(b, yk)!;
    return {
      type: "bar",
      name: colLabel(c, lang, false),
      stack: stacked ? "total" : undefined,
      barMaxWidth: horizontal ? 16 : 34,
      barGap: "18%",
      itemStyle: {
        color: multi ? t.series[si % t.series.length] : t.water,
        borderRadius: stacked ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
        borderColor: t.surface,
        borderWidth: stacked || multi ? 1 : 0,
      },
      label: {
        show: !multi && rows.length <= 12,
        position: horizontal ? "right" : "top",
        color: t.ink2,
        fontSize: 11,
        formatter: (p: { dataIndex: number }) => {
          const r = rows[p.dataIndex];
          const v = num(r?.[yk]);
          if (v === null) return statusKey && r?.[statusKey] ? statusWord(String(r[statusKey])) : "no value";
          return cellText(v, c, r, lang);
        },
      },
      data: rows.map((r) => {
        const v = num(r[yk]);
        const id = idOf(b, r);
        let color = multi ? t.series[si % t.series.length] : t.water;
        if (!multi && colorKey) color = colorMap.get(str(r[colorKey])) ?? t.water;
        if (delta && v !== null) color = v < 0 ? t.divNeg : t.divPos;
        const focus = id && highlight.has(id);
        return {
          value: v === null ? "-" : v,
          itemStyle: { color: focus && !delta ? t.wheat : color, ...(focus ? { borderColor: t.ink, borderWidth: 1 } : {}) },
        };
      }),
    };
  });

  const catAxis = {
    type: "category",
    data: cats,
    inverse: horizontal,
    axisLine: { lineStyle: { color: t.border } },
    axisTick: { show: false },
    axisLabel: { color: t.ink2, fontSize: 11, width: horizontal ? 92 : 80, overflow: "truncate", interval: 0, rotate: !horizontal && cats.length > 4 ? 30 : 0 },
  };
  const valAxis = {
    type: "value",
    name: axisName(unit),
    splitNumber: 4,
    nameTextStyle: { color: t.ink3, fontSize: 11 },
    axisLabel: { color: t.ink3, fontSize: 11, formatter: fmt, hideOverlap: true },
    splitLine: { lineStyle: { color: t.border, opacity: 0.7 } },
  };
  const legend = multi || colorKey
    ? {
        top: 0,
        left: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: t.ink2, fontSize: 11 },
        data: multi ? series.map((s) => s.name) : colorVals,
      }
    : undefined;
  // A colour-by-category legend needs one (empty) series per category so the legend has swatches.
  const legendSeries =
    !multi && colorKey
      ? colorVals.map((v) => ({ type: "bar", name: v, data: [], itemStyle: { color: colorMap.get(v) } }))
      : [];
  const height = horizontal ? Math.max(160, Math.min(900, rows.length * 24 + 64)) : 240;
  return {
    option: {
      textStyle: { fontFamily: t.font, color: t.ink2 },
      grid: { left: horizontal ? 100 : 52, right: horizontal ? 64 : 16, top: legend ? 34 : 18, bottom: horizontal ? 24 : cats.length > 4 ? 64 : 32, containLabel: false },
      legend,
      tooltip: {
        ...tooltipBase(t),
        trigger: "item",
        formatter: (p: { dataIndex: number }) => `<b>${esc(cats[p.dataIndex] ?? "")}</b>${rowTooltip(b, rows[p.dataIndex], lang, [])}`,
      },
      xAxis: horizontal ? valAxis : catAxis,
      yAxis: horizontal ? catAxis : valAxis,
      series: [
        ...series,
        ...legendSeries,
        ...(delta
          ? [{ type: "line", data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: t.ink3, width: 1 }, data: [horizontal ? { xAxis: 0 } : { yAxis: 0 }], label: { show: false } } }]
          : []),
      ],
    },
    height,
    rowAt: (_s, i) => rows[i],
  };
}

/* ------------------------------------------------------------------ lines */

function lines(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart {
  const rows = b.rows;
  const xk = b.encoding.x;
  const ys = (b.encoding.y ?? []).filter((k) => col(b, k)).slice(0, 4);
  const xc = col(b, xk);
  const cats = rows.map((r) => (xc?.kind === "date" && typeof r[xk!] === "string" ? formatDateShort(String(r[xk!])) : catLabel(b, r, xk, lang)));
  const units = uniq(ys.map((k) => displayUnit(col(b, k)?.unit)));
  const area = b.chart === "area";
  return {
    option: {
      textStyle: { fontFamily: t.font, color: t.ink2 },
      grid: { left: 52, right: 16, top: ys.length > 1 ? 34 : 18, bottom: 32 },
      legend: ys.length > 1 ? { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: t.ink2, fontSize: 11 } } : undefined,
      tooltip: { ...tooltipBase(t), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.ink3 } } },
      xAxis: { type: "category", data: cats, boundaryGap: !area, axisLine: { lineStyle: { color: t.border } }, axisTick: { show: false }, axisLabel: { color: t.ink3, fontSize: 11, hideOverlap: true } },
      yAxis: {
        type: "value",
        name: units.length === 1 ? axisName(col(b, ys[0])?.unit) : "",
        splitNumber: 4,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: axisFormatter(col(b, ys[0])?.unit, Math.max(0, ...rows.flatMap((r) => ys.map((k) => Math.abs(num(r[k]) ?? 0))))) },
        splitLine: { lineStyle: { color: t.border, opacity: 0.7 } },
      },
      series: ys.map((k, i) => {
        const c = col(b, k)!;
        const color = t.series[i % t.series.length];
        return {
          type: area ? "line" : "line",
          name: colLabel(c, lang),
          stack: area && ys.length > 1 ? "total" : undefined,
          showSymbol: rows.length <= 16,
          symbolSize: 6,
          connectNulls: false,
          smooth: false,
          lineStyle: { width: 2, color },
          itemStyle: { color },
          areaStyle: area ? { color, opacity: 0.22 } : undefined,
          data: rows.map((r) => (num(r[k]) === null ? "-" : num(r[k]))),
          tooltip: { valueFormatter: (v: unknown) => (typeof v === "number" ? cellText(v, c, {}, lang) : "—") },
        };
      }),
    },
    height: 240,
    rowAt: (_s, i) => rows[i],
  };
}

/* ------------------------------------------------------------------ scatter / frontier */

function points(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart {
  const xk = b.encoding.x!;
  const yk = (b.encoding.y ?? [])[0];
  const xc = col(b, xk)!;
  const yc = col(b, yk)!;
  const colorKey = b.encoding.color;
  const plotted = b.rows.filter((r) => num(r[xk]) !== null && num(r[yk]) !== null);
  const missing = b.rows.filter((r) => !(num(r[xk]) !== null && num(r[yk]) !== null));
  const groups = colorKey ? uniq(plotted.map((r) => r[colorKey])) : ["all"];
  const highlight = new Set(b.highlight_ids ?? []);
  const frontier = b.chart === "frontier";
  const colorFor = (g: string, i: number) =>
    frontier ? (g === "nondominated" ? t.water : g === "dominated" ? t.ink3 : t.warning) : t.series[i % t.series.length];
  const bySeries: Row[][] = groups.map((g) => plotted.filter((r) => !colorKey || str(r[colorKey]) === g));
  const series: Record<string, unknown>[] = groups.map((g, i) => ({
    type: "scatter",
    name: colorKey ? statusWord(g) : colLabel(yc, lang, false),
    symbolSize: 11,
    itemStyle: { color: colorFor(g, i), borderColor: t.surface, borderWidth: 2 },
    data: bySeries[i].map((r) => {
      const id = idOf(b, r);
      const focus = id && highlight.has(id);
      return { value: [num(r[xk]), num(r[yk])], itemStyle: focus ? { color: t.wheat, borderColor: t.ink, borderWidth: 2 } : undefined, symbolSize: focus ? 15 : 11 };
    }),
  }));
  if (frontier) {
    const best = plotted.filter((r) => !colorKey || str(r[colorKey]) === "nondominated").sort((a, z) => (num(a[xk]) ?? 0) - (num(z[xk]) ?? 0));
    series.unshift({
      type: "line",
      name: "Best trade-offs",
      silent: true,
      showSymbol: false,
      lineStyle: { color: t.water, width: 2, opacity: 0.6 },
      data: best.map((r) => [num(r[xk]), num(r[yk])]),
      tooltip: { show: false },
    });
  }
  const offset = frontier ? 1 : 0;
  return {
    option: {
      textStyle: { fontFamily: t.font, color: t.ink2 },
      grid: { left: 56, right: 18, top: 34, bottom: 44 },
      legend: { top: 0, left: 0, icon: "circle", itemWidth: 9, itemHeight: 9, textStyle: { color: t.ink2, fontSize: 11 } },
      tooltip: {
        ...tooltipBase(t),
        trigger: "item",
        formatter: (p: { seriesIndex: number; dataIndex: number }) => rowTooltip(b, bySeries[p.seriesIndex - offset]?.[p.dataIndex], lang, [xk, yk]),
      },
      xAxis: {
        type: "value",
        name: colLabel(xc, lang),
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        splitNumber: 4,
        axisLabel: { color: t.ink3, fontSize: 11, formatter: axisFormatter(xc.unit, Math.max(0, ...plotted.map((r) => Math.abs(num(r[xk]) ?? 0)))), hideOverlap: true },
        splitLine: { lineStyle: { color: t.border, opacity: 0.5 } },
        scale: true,
      },
      yAxis: {
        type: "value",
        name: axisName(yc.unit),
        splitNumber: 4,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: axisFormatter(yc.unit, Math.max(0, ...plotted.map((r) => Math.abs(num(r[yk]) ?? 0)))) },
        splitLine: { lineStyle: { color: t.border, opacity: 0.7 } },
        scale: true,
      },
      series,
    },
    height: 260,
    rowAt: (s, i) => (s - offset >= 0 ? bySeries[s - offset]?.[i] : undefined) ?? missing[i],
  };
}

/* ------------------------------------------------------------------ heatmap (stress matrix) */

function heatmap(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart {
  const xk = b.encoding.x!;
  const yk = (b.encoding.y ?? [])[0];
  const vk = b.encoding.value!;
  const vc = col(b, vk)!;
  const sk = b.encoding.status;
  const xs = uniq(b.rows.map((r) => r[xk]));
  const ys = uniq(b.rows.map((r) => r[yk]));
  const filled: { value: [number, number, number]; row: Row }[] = [];
  const empty: { value: [number, number, number]; row: Row }[] = [];
  for (const r of b.rows) {
    const v = num(r[vk]);
    const cell = [xs.indexOf(str(r[xk])), ys.indexOf(str(r[yk])), v ?? 0] as [number, number, number];
    (v === null ? empty : filled).push({ value: cell, row: r });
  }
  const vals = filled.map((f) => f.value[2]);
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 0;
  // Colour step per served value (presentational only; no new number is shown).
  const step = (v: number) => (hi > lo ? Math.min(5, Math.floor(((v - lo) / (hi - lo)) * 6)) : 4);
  const label = (row: Row, v: number | null) => (v === null ? (sk && row[sk] ? statusWord(String(row[sk])).replace("No plan in this condition", "No plan") : "No value") : cellText(v, vc, row, lang));
  const cells = [...filled.map((f) => ({ ...f, has: true })), ...empty.map((e) => ({ ...e, has: false }))];
  type Api = { value: (i: number) => number; coord: (v: number[]) => number[]; size: (v: number[]) => number[] };
  return {
    option: {
      textStyle: { fontFamily: t.font, color: t.ink2 },
      grid: { left: 76, right: 12, top: 10, bottom: 54 },
      tooltip: {
        ...tooltipBase(t),
        trigger: "item",
        formatter: (p: { dataIndex: number }) => rowTooltip(b, cells[p.dataIndex]?.row, lang, [xk, yk, vk]),
      },
      xAxis: { type: "category", data: xs, splitArea: { show: false }, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: t.ink2, fontSize: 11, interval: 0, width: 96, overflow: "break" } },
      yAxis: { type: "category", data: ys, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: t.ink2, fontSize: 11, formatter: (v: string) => v.charAt(0).toUpperCase() + v.slice(1) } },
      series: [
        {
          // Cells drawn as rounded tiles: filled = deliverable with production; hatched = no plan.
          type: "custom",
          name: colLabel(vc, lang),
          renderItem: (_p: unknown, api: Api) => {
            const i = api.value(2);
            const c = cells[i];
            const [cx, cy] = api.coord([api.value(0), api.value(1)]);
            const [w, h] = api.size([1, 1]);
            const fill = c.has ? t.seq[step(c.value[2])] : t.muted;
            const dark = c.has && step(c.value[2]) >= 3;
            return {
              type: "group",
              children: [
                {
                  type: "rect",
                  shape: { x: cx - w / 2 + 3, y: cy - h / 2 + 3, width: w - 6, height: h - 6, r: 10 },
                  style: c.has ? { fill } : { fill, stroke: t.border, lineWidth: 1, lineDash: [4, 3] },
                },
                {
                  type: "text",
                  style: {
                    x: cx,
                    y: cy,
                    text: label(c.row, c.has ? c.value[2] : null),
                    align: "center",
                    verticalAlign: "middle",
                    fill: c.has ? (dark ? "#ffffff" : t.ink) : t.ink2,
                    font: `${c.has ? 600 : 500} ${c.has ? 12 : 11}px ${t.font}`,
                  },
                },
              ],
            };
          },
          data: cells.map((c, i) => [c.value[0], c.value[1], i]),
          encode: { x: 0, y: 1 },
        },
      ],
    },
    height: Math.max(180, ys.length * 62 + 70),
    rowAt: (_s, i) => [...filled, ...empty][i]?.row,
  };
}

/* ------------------------------------------------------------------ sankey (water ledger) */

function sankey(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart {
  const sk = b.encoding.source!;
  const tk = b.encoding.target!;
  const vk = b.encoding.value!;
  const vc = col(b, vk)!;
  const links = b.rows.filter((r) => num(r[vk]) !== null && str(r[sk]) !== str(r[tk]));
  const pretty = (v: unknown) => {
    const x = str(v);
    return /^[a-z0-9_]+$/.test(x) ? (x.charAt(0).toUpperCase() + x.slice(1)).replace(/_/g, " ") : x;
  };
  const names = uniq(links.flatMap((r) => [pretty(r[sk]), pretty(r[tk])]));
  const nodeColor = (n: string) => (/loss|lost|evapor|seepage|spill/i.test(n) ? t.warning : /ground|pump/i.test(n) ? t.series[1] : /pond/i.test(n) ? t.series[2] : /field|applied|outlet/i.test(n) ? t.series[3] : t.water);
  return {
    option: {
      textStyle: { fontFamily: t.font, color: t.ink2 },
      tooltip: {
        ...tooltipBase(t),
        trigger: "item",
        formatter: (p: { dataType: string; name: string; data: { source?: string; target?: string; value?: number } }) =>
          p.dataType === "edge" ? `${esc(String(p.data.source))} → ${esc(String(p.data.target))}<br/><b>${esc(cellText(p.data.value, vc, {}, lang))}</b>` : `<b>${esc(p.name)}</b>`,
      },
      series: [
        {
          type: "sankey",
          left: 92,
          right: 108,
          top: 8,
          bottom: 8,
          nodeWidth: 12,
          nodeGap: 16,
          layoutIterations: 48,
          // Sources are labelled on their left, everything else on the right, so labels never sit on links' starts.
          levels: [{ depth: 0, label: { position: "left", width: 84 } }],
          draggable: false,
          emphasis: { focus: "adjacency" },
          label: {
            color: t.ink,
            fontSize: 10.5,
            width: 104,
            overflow: "break",
            backgroundColor: t.surface,
            padding: [2, 4],
            borderRadius: 4,
          },
          lineStyle: { color: "gradient", opacity: 0.32, curveness: 0.5 },
          data: names.map((n) => ({ name: n, itemStyle: { color: nodeColor(n), borderColor: nodeColor(n) } })),
          links: links.map((r) => ({ source: pretty(r[sk]), target: pretty(r[tk]), value: num(r[vk]) })),
        },
      ],
    },
    height: Math.max(220, names.length * 34),
    rowAt: (_s, i) => links[i],
  };
}

/**
 * One axis per chart: bar/line y columns with different units become separate panels
 * (small multiples), never a second scale on the same axis.
 */
export function splitByUnit(b: VisualBlock): VisualBlock[] {
  const ys = (b.encoding.y ?? []).filter((k) => col(b, k));
  const groups = new Map<string, string[]>();
  for (const k of ys) {
    const u = col(b, k)?.unit ?? col(b, k)?.unit_column ?? "";
    groups.set(u, [...(groups.get(u) ?? []), k]);
  }
  if (groups.size <= 1) return [b];
  return [...groups.values()].map((y) => ({ ...b, encoding: { ...b.encoding, y } }));
}

export function buildChart(b: VisualBlock, t: ChartTheme, lang: Lang): BuiltChart | null {
  if (!b.rows.length) return null;
  switch (b.chart) {
    case "bar":
    case "grouped_bar":
    case "stacked_bar":
    case "delta_bar":
      return (b.encoding.y ?? []).some((k) => col(b, k)) && b.encoding.x ? bars(b, t, lang) : null;
    case "line":
    case "area":
      return b.encoding.x && (b.encoding.y ?? []).length ? lines(b, t, lang) : null;
    case "scatter":
    case "frontier":
      return b.encoding.x && (b.encoding.y ?? []).length ? points(b, t, lang) : null;
    case "heatmap":
      return b.encoding.x && (b.encoding.y ?? []).length && b.encoding.value ? heatmap(b, t, lang) : null;
    case "sankey":
      return b.encoding.source && b.encoding.target && b.encoding.value ? sankey(b, t, lang) : null;
    case "kpi":
    case "table":
    case "map":
    case "steps":
      return null;
    default: {
      const never: never = b.chart;
      return never;
    }
  }
}
