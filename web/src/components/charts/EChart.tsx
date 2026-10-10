/**
 * Thin ECharts wrapper: tree-shaken imports, token-driven theme, ResizeObserver,
 * reduced-motion aware, and keyboard/touch accessible via the paired table twin.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, ScatterChart, SankeyChart, CustomChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { SVGRenderer, CanvasRenderer } from "echarts/renderers";
import { Table2, BarChart3 } from "lucide-react";
import { useReducedMotion, useResolvedTheme } from "@/app/environment";
import { cssVar } from "@/components/map/palette";
import { cn } from "@/lib/cn";

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  ScatterChart,
  SankeyChart,
  CustomChart,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
  SVGRenderer,
  CanvasRenderer,
]);

export type EOption = echarts.EChartsCoreOption;

export function chartTokens() {
  return {
    ink: cssVar("--ink"),
    ink2: cssVar("--ink-secondary"),
    ink3: cssVar("--ink-tertiary"),
    border: cssVar("--border"),
    surface: cssVar("--surface"),
    muted: cssVar("--surface-muted"),
    water: cssVar("--water"),
    waterDeep: cssVar("--water-deep"),
    veg: cssVar("--vegetation"),
    warning: cssVar("--warning"),
    danger: cssVar("--danger"),
    series: [1, 2, 3, 4, 5, 6].map((i) => cssVar(`--series-${i}`)),
    font: "Inter, ui-sans-serif, system-ui, sans-serif",
  };
}

/** Shared axis/tooltip styling. */
export function baseOption(): EOption {
  const t = chartTokens();
  return {
    textStyle: { fontFamily: t.font, color: t.ink2, fontSize: 12 },
    grid: { left: 52, right: 16, top: 24, bottom: 32, containLabel: false },
    tooltip: {
      trigger: "axis",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.ink, fontSize: 12 },
      extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.12);",
      confine: true,
    },
    xAxis: { axisLine: { lineStyle: { color: t.border } }, axisTick: { show: false }, axisLabel: { color: t.ink3, fontSize: 11 }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, axisLabel: { color: t.ink3, fontSize: 11 }, splitLine: { lineStyle: { color: t.border, opacity: 0.7 } }, nameTextStyle: { color: t.ink3, fontSize: 11 } },
  };
}

export function EChart({
  option,
  className,
  height = 240,
  ariaLabel,
  onEvents,
  renderer = "svg",
  groupId,
  onReady,
}: {
  option: EOption;
  className?: string;
  height?: number | string;
  ariaLabel: string;
  onEvents?: Record<string, (p: unknown) => void>;
  renderer?: "svg" | "canvas";
  groupId?: string;
  onReady?: (c: echarts.ECharts) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const reduced = useReducedMotion();
  const theme = useResolvedTheme();

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer, devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2) });
    chart.current = c;
    if (groupId) {
      (c as unknown as { group: string }).group = groupId;
      echarts.connect(groupId);
    }
    onReady?.(c);
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, [renderer, groupId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Animations are off: data transitions must not imply uncomputed intermediate values.
    chart.current?.setOption({ animation: false, ...option }, { notMerge: true });
  }, [option, reduced, theme]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    for (const [k, fn] of Object.entries(onEvents)) c.on(k, fn as never);
    return () => {
      for (const [k, fn] of Object.entries(onEvents)) c.off(k, fn as never);
    };
  }, [onEvents]);

  return <div ref={ref} role="img" aria-label={ariaLabel} className={cn("w-full", className)} style={{ height }} />;
}

/** Chart with its required table/summary twin (T10.4). */
export function ChartPanel({
  title,
  summary,
  chart,
  table,
  aside,
  className,
  defaultView = "chart",
  id,
}: {
  title: ReactNode;
  summary?: ReactNode;
  chart: ReactNode;
  table: ReactNode;
  aside?: ReactNode;
  className?: string;
  defaultView?: "chart" | "table";
  id?: string;
}) {
  const [view, setView] = useState<"chart" | "table">(defaultView);
  return (
    <section className={cn("rounded-[18px] border border-border bg-surface shadow-1", className)} aria-labelledby={id ? `${id}-h` : undefined} data-testid={id}>
      <header className="flex items-start justify-between gap-3 px-5 pb-1 pt-4">
        <div className="min-w-0">
          <h3 id={id ? `${id}-h` : undefined} className="text-[14.5px] font-semibold tracking-[-0.01em] text-ink">
            {title}
          </h3>
          {summary ? <p className="mt-1 max-w-[80ch] text-[12.5px] leading-snug text-ink-secondary">{summary}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {aside}
          <button
            type="button"
            onClick={() => setView(view === "chart" ? "table" : "chart")}
            className="inline-flex h-8 items-center gap-1.5 rounded-[9px] border border-border px-2.5 text-[12px] font-medium text-ink-secondary transition-colors hover:bg-surface-muted hover:text-ink"
            aria-pressed={view === "table"}
            aria-label={view === "chart" ? "Show as table" : "Show as chart"}
          >
            {view === "chart" ? <Table2 size={13} aria-hidden /> : <BarChart3 size={13} aria-hidden />}
            {view === "chart" ? "Table" : "Chart"}
          </button>
        </div>
      </header>
      <div className="px-3 pb-4">{view === "chart" ? chart : <div className="max-h-[420px] overflow-auto px-2">{table}</div>}</div>
    </section>
  );
}

export function DataTable({
  columns,
  rows,
  caption,
  dense,
}: {
  columns: { key: string; label: ReactNode; align?: "left" | "right"; className?: string }[];
  rows: Record<string, ReactNode>[];
  caption?: string;
  dense?: boolean;
}) {
  return (
    <table className="w-full border-collapse text-[12px]">
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      <thead className="sticky top-0 bg-surface">
        <tr>
          {columns.map((c) => (
            <th key={c.key} scope="col" className={cn("border-b border-border pb-1.5 pt-1 font-medium text-ink-tertiary", c.align === "right" ? "text-right" : "text-left", c.className)}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-b border-border/70 last:border-0">
            {columns.map((c) => (
              <td key={c.key} className={cn("num text-ink", dense ? "py-1" : "py-1.5", c.align === "right" ? "text-right" : "text-left", c.className)}>
                {r[c.key] ?? "—"}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
