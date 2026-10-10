/**
 * Visual blocks (docs/COPILOT.md §3.1): server-built datasets drawn as charts, metric cards,
 * a field map, dated steps or a table. Every view has a table twin, copy, expand and a
 * source footer (tool, run/analysis IDs, basis). Values are only formatted, never computed.
 */
import { useMemo, useState, type ReactNode } from "react";
import { BarChart3, CalendarClock, Check, Copy, Database, Map as MapIcon, Maximize2, Table2, Wand2 } from "lucide-react";
import { EChart, chartTokens } from "@/components/charts/EChart";
import { cssVar } from "@/components/map/palette";
import { Chip } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog, DialogContent, Segmented } from "@/components/ui/primitives";
import { toast } from "@/components/ui/Toast";
import { useResolvedTheme } from "@/app/environment";
import { usePilotData } from "@/app/pilotData";
import { formatDate, shortId } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { buildChart, type ChartTheme } from "./charts";
import { BASIS_TEXT, cellText, colLabel, displayUnit, statusWord, toTSV, type Lang } from "./format";
import { refKind, useCopilotNav } from "./nav";
import type { Row, VisualBlock } from "./types";

const TOOL_TEXT: Record<string, string> = {
  inspect_run: "Run results",
  compare_runs: "Comparison service",
  get_plan_ladder: "Plan comparison",
  run_what_if: "What-if run",
  read_analysis: "Saved analysis",
  run_stress_test: "Stress test",
  build_frontier: "Trade-off analysis",
  water_accounting: "Water books",
  economics: "Cost books",
  equity: "Fairness check",
  impact_sdg: "Impact cards",
  action_plan: "Action plan",
  field_timeline: "Season replay",
  explain_decisions: "Decision reasons",
  evaluate_alternative: "Why-not analysis",
  analyze_sensitivity: "Sensitivity analysis",
  analyze_synergy: "Synergy analysis",
  server: "Server",
};

export function useChartTheme(): ChartTheme {
  const theme = useResolvedTheme();
  return useMemo(() => {
    const t = chartTokens();
    return {
      ink: t.ink,
      ink2: t.ink2,
      ink3: t.ink3,
      border: t.border,
      surface: t.surface,
      muted: t.muted,
      water: t.water,
      wheat: cssVar("--wheat"),
      warning: t.warning,
      danger: t.danger,
      // Validated order (CVD-separable): series-1, -2, -4, -3. Slots 5-6 fail separation, so at most four.
      series: [t.series[0], t.series[1], t.series[3], t.series[2]],
      seq: [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--seq-${i}`)),
      divNeg: cssVar("--div-neg-2"),
      divPos: cssVar("--div-pos-2"),
      font: t.font,
    };
  }, [theme]); // eslint-disable-line react-hooks/exhaustive-deps
}

function fieldIdsOf(b: VisualBlock): string[] {
  const c = b.columns.find((x) => x.ref === "field");
  if (!c) return [];
  return [...new Set(b.rows.map((r) => r[c.key]).filter((v): v is string => typeof v === "string"))];
}

/* ------------------------------------------------------------------ table twin */

export function VisualTable({ b, lang, maxHeight = 320 }: { b: VisualBlock; lang: Lang; maxHeight?: number }) {
  const cols = b.columns.filter((c) => !(c.kind === "text" && b.columns.some((x) => x.unit_column === c.key)));
  const hl = new Set(b.highlight_ids ?? []);
  return (
    <div className="overflow-auto rounded-[12px] border border-border" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[12px]" data-testid="copilot-visual-table">
        <caption className="sr-only">{b.title}</caption>
        <thead className="sticky top-0 bg-surface-muted">
          <tr>
            {cols.map((c) => (
              <th key={c.key} scope="col" className={cn("whitespace-nowrap px-2 py-1.5 font-medium text-ink-secondary", c.kind === "number" ? "text-right" : "text-left")}>
                {colLabel(c, lang)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {b.rows.map((r, i) => {
            const focus = cols.some((c) => c.ref && typeof r[c.key] === "string" && hl.has(r[c.key] as string));
            return (
              <tr key={i} className={cn("border-t border-border/70", focus && "bg-wheat-soft/60")}>
                {cols.map((c) => (
                  <td key={c.key} className={cn("px-2 py-1 text-ink", c.kind === "number" ? "num text-right" : "text-left", c.kind === "id" && "font-mono text-[11px] text-ink-secondary")}>
                    {cellText(r[c.key], c, r, lang)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ kpi, steps */

function KpiGrid({ b, lang }: { b: VisualBlock; lang: Lang }) {
  const lk = b.encoding.label ?? b.columns[0]?.key;
  const vk = b.encoding.value ?? "value";
  const sk = b.encoding.status;
  const lc = b.columns.find((c) => c.key === lk);
  const vc = b.columns.find((c) => c.key === vk);
  if (!vc) return <VisualTable b={b} lang={lang} />;
  return (
    <div className="grid grid-cols-2 gap-2" data-testid="copilot-kpi">
      {b.rows.map((r, i) => {
        const v = r[vk];
        const status = sk ? (r[sk] as string | undefined) : undefined;
        const missing = v === null || v === undefined;
        return (
          <div key={i} className="flex min-w-0 flex-col gap-0.5 rounded-[12px] border border-border bg-surface-muted/50 px-3 py-2">
            <span className="line-clamp-2 text-[11.5px] font-medium leading-snug text-ink-secondary">{lc ? cellText(r[lc.key], lc, r, lang) : ""}</span>
            {missing ? (
              <span className="text-[12.5px] font-medium text-ink-tertiary">{status ? statusWord(status) : "No value"}</span>
            ) : (
              <span className="num text-[17px] font-semibold tracking-[-0.01em] text-ink">{cellText(v, vc, r, lang)}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StepsList({ b, lang }: { b: VisualBlock; lang: Lang }) {
  const col = (k?: string | null) => b.columns.find((c) => c.key === k);
  const label = col(b.encoding.label ?? "title");
  const start = col(b.encoding.x ?? "start_date");
  const cost = col(b.encoding.value ?? "capex_pkr");
  const ready = col("commissioning_date");
  const who = col("responsible_role");
  const ok = col("required_approval");
  return (
    <ol className="relative flex flex-col gap-2.5 pl-6" data-testid="copilot-steps">
      <span className="absolute bottom-3 left-[9px] top-3 w-px bg-border" aria-hidden />
      {b.rows.map((r, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-6 top-1 grid h-[19px] w-[19px] place-items-center rounded-full bg-water text-[10.5px] font-bold text-on-water ring-4 ring-surface">{i + 1}</span>
          <div className="rounded-[12px] border border-border bg-surface px-3 py-2 shadow-1">
            <p className="text-[13px] font-semibold leading-snug text-ink">{label ? cellText(r[label.key], label, r, lang) : `Step ${i + 1}`}</p>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] text-ink-secondary">
              {start && r[start.key] ? (
                <span className="inline-flex items-center gap-1">
                  <CalendarClock size={11} aria-hidden /> {formatDate(String(r[start.key]))}
                  {ready && r[ready.key] ? ` → ready ${formatDate(String(r[ready.key]))}` : ""}
                </span>
              ) : null}
              {cost && typeof r[cost.key] === "number" ? <span className="num">{cellText(r[cost.key], cost, r, lang)}</span> : null}
            </div>
            {who && r[who.key] ? <p className="mt-1 text-[11.5px] text-ink-tertiary">Who: {String(r[who.key])}</p> : null}
            {ok && r[ok.key] ? <p className="text-[11.5px] text-ink-tertiary">Approval: {String(r[ok.key])}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ field map (SVG of the reviewed outlines) */

type Ring = [number, number][];
function rings(g: GeoJSON.Geometry | null): Ring[] {
  if (!g) return [];
  if (g.type === "Polygon") return [g.coordinates[0] as Ring];
  if (g.type === "MultiPolygon") return g.coordinates.map((p) => p[0] as Ring);
  return [];
}

export function FieldMapView({ b, lang, height = 260 }: { b: VisualBlock; lang: Lang; height?: number }) {
  const { fieldIndex } = usePilotData();
  const t = useChartTheme();
  const nav = useCopilotNav();
  const idKey = b.encoding.id ?? b.columns.find((c) => c.ref === "field")?.key;
  const vKey = b.encoding.value ?? b.encoding.color;
  const vc = b.columns.find((c) => c.key === vKey);
  const byId = new Map<string, Row>();
  for (const r of b.rows) if (idKey && typeof r[idKey] === "string") byId.set(r[idKey] as string, r);
  const hl = new Set(b.highlight_ids ?? []);
  const shapes = [...fieldIndex.values()].map((f) => ({ id: f.id, label: f.label, rings: rings(f.geometry) })).filter((s) => s.rings.length);
  if (!shapes.length || !vc) return <VisualTable b={b} lang={lang} />;
  // Projection bounds (presentational): equirectangular with a cos(latitude) x-scale.
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity; // prettier-ignore
  for (const s of shapes) for (const r of s.rings) for (const [x, y] of r) ((minX = Math.min(minX, x)), (maxX = Math.max(maxX, x)), (minY = Math.min(minY, y)), (maxY = Math.max(maxY, y))); // prettier-ignore
  const k = Math.cos(((minY + maxY) / 2) * (Math.PI / 180));
  const W = 400;
  const H = Math.max(160, Math.min(320, (W * (maxY - minY)) / Math.max(1e-9, (maxX - minX) * k)));
  const sx = (x: number) => ((x - minX) / Math.max(1e-12, maxX - minX)) * (W - 16) + 8;
  const sy = (y: number) => H - 8 - ((y - minY) / Math.max(1e-12, maxY - minY)) * (H - 16);
  const numeric = vc.kind === "number";
  const vals = b.rows.map((r) => r[vc.key]).filter((v): v is number => typeof v === "number");
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 1;
  const diverging = /delta|change/i.test(vc.key) && lo < 0;
  const ramp = vc.unit === "ratio" ? [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--svc-${i}`)) : t.seq;
  const cats = numeric ? [] : [...new Set(b.rows.map((r) => String(r[vc.key])))];
  const colorFor = (r: Row | undefined): string => {
    if (!r) return t.muted;
    const v = r[vc.key];
    if (!numeric) return t.series[cats.indexOf(String(v)) % t.series.length];
    if (typeof v !== "number") return t.muted;
    if (diverging) {
      const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
      const s = v / m;
      return s <= -0.5 ? t.divNeg : s < -0.05 ? cssVar("--div-neg-1") : s < 0.05 ? cssVar("--div-zero") : s < 0.5 ? cssVar("--div-pos-1") : t.divPos;
    }
    const step = hi > lo ? Math.min(ramp.length - 1, Math.floor(((v - lo) / (hi - lo)) * ramp.length)) : ramp.length - 1;
    return ramp[step];
  };
  const minRow = b.rows.find((r) => r[vc.key] === lo);
  const maxRow = b.rows.find((r) => r[vc.key] === hi);
  return (
    <figure className="flex flex-col gap-2" data-testid="copilot-map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${b.title}: field map`} className="w-full rounded-[12px] bg-surface-muted" style={{ maxHeight: height }}>
        {shapes.map((s) => {
          const r = byId.get(s.id);
          const focus = hl.has(s.id);
          return (
            <g key={s.id} onClick={() => nav.open("field", s.id)} className="cursor-pointer">
              <title>{`${s.label}: ${r ? cellText(r[vc.key], vc, r, lang) : "not in this answer"}`}</title>
              {s.rings.map((ring, i) => (
                <path
                  key={i}
                  d={`M${ring.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join("L")}Z`}
                  fill={colorFor(r)}
                  stroke={focus ? t.ink : t.surface}
                  strokeWidth={focus ? 2 : 0.8}
                  opacity={r ? 1 : 0.45}
                />
              ))}
            </g>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-ink-secondary">
        {numeric ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="num">{minRow ? cellText(lo, vc, minRow, lang) : ""}</span>
            <span className="flex h-2.5 overflow-hidden rounded-full" aria-hidden>
              {(diverging ? [t.divNeg, cssVar("--div-neg-1"), cssVar("--div-zero"), cssVar("--div-pos-1"), t.divPos] : ramp).map((c) => (
                <span key={c} className="w-4" style={{ background: c }} />
              ))}
            </span>
            <span className="num">{maxRow ? cellText(hi, vc, maxRow, lang) : ""}</span>
            <span className="text-ink-tertiary">{colLabel(vc, lang, false)}</span>
          </span>
        ) : (
          <span className="flex flex-wrap gap-2">
            {cats.map((c, i) => (
              <span key={c} className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: t.series[i % t.series.length] }} aria-hidden /> {statusWord(c)}
              </span>
            ))}
          </span>
        )}
        {hl.size ? <span className="text-ink-tertiary">Outlined: fields the answer talks about</span> : null}
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------ chart */

function ChartBody({ b, lang, tall }: { b: VisualBlock; lang: Lang; tall?: boolean }) {
  const t = useChartTheme();
  const nav = useCopilotNav();
  const built = useMemo(() => buildChart(b, t, lang), [b, t, lang]);
  const onEvents = useMemo(
    () => ({
      click: (p: unknown) => {
        const e = p as { seriesIndex?: number; dataIndex?: number };
        const row = built?.rowAt(e.seriesIndex ?? 0, e.dataIndex ?? 0);
        if (!row) return;
        for (const it of b.interactions ?? []) {
          const id = row[it.column];
          if (typeof id === "string") {
            nav.open(refKind(it.intent.replace("open_", ""), id), id);
            return;
          }
        }
      },
    }),
    [built, b.interactions, nav],
  );
  if (!built) return <VisualTable b={b} lang={lang} />;
  return <EChart option={built.option} height={tall ? Math.max(built.height, 360) : built.height} ariaLabel={`${b.title}. The table view lists every value.`} onEvents={onEvents} />;
}

export function VisualBody({ b, lang, tall }: { b: VisualBlock; lang: Lang; tall?: boolean }): ReactNode {
  switch (b.chart) {
    case "kpi":
      return <KpiGrid b={b} lang={lang} />;
    case "table":
      return <VisualTable b={b} lang={lang} maxHeight={tall ? 560 : 320} />;
    case "map":
      return <FieldMapView b={b} lang={lang} height={tall ? 520 : 260} />;
    case "steps":
      return <StepsList b={b} lang={lang} />;
    case "bar":
    case "grouped_bar":
    case "stacked_bar":
    case "delta_bar":
    case "line":
    case "area":
    case "scatter":
    case "frontier":
    case "heatmap":
    case "sankey":
      return <ChartBody b={b} lang={lang} tall={tall} />;
    default: {
      const never: never = b.chart;
      return never;
    }
  }
}

function SourceFooter({ b }: { b: VisualBlock }) {
  const runs = b.source.run_ids ?? [];
  const analyses = b.source.analysis_ids ?? [];
  const nav = useCopilotNav();
  return (
    <footer className="flex flex-col gap-1.5 border-t border-border/70 pt-2 text-[11px] text-ink-tertiary">
      <div className="flex flex-wrap items-center gap-1.5">
        <Database size={11} aria-hidden />
        <span>{TOOL_TEXT[b.source.tool] ?? b.source.tool}</span>
        {analyses.slice(0, 1).map((a) => (
          <button key={a} type="button" className="font-mono hover:text-water-deep hover:underline" onClick={() => nav.open("analysis", a)} title={a}>
            {shortId(a)}
          </button>
        ))}
        {runs.slice(0, 2).map((r) => (
          <button key={r} type="button" className="font-mono hover:text-water-deep hover:underline" onClick={() => nav.open("run", r)} title={r} data-testid="copilot-visual-run">
            {shortId(r)}
          </button>
        ))}
        {runs.length > 2 ? <span>+{runs.length - 2} runs</span> : null}
        {(b.basis ?? []).map((x) => (
          <Chip key={x} size="sm" tone={BASIS_TEXT[x]?.tone ?? "neutral"}>
            {BASIS_TEXT[x]?.en ?? x}
          </Chip>
        ))}
      </div>
      {(b.notes ?? []).filter(Boolean).length ? (
        <details className="group">
          <summary className="cursor-pointer select-none text-ink-secondary hover:text-ink">About this data</summary>
          <ul className="mt-1 list-disc pl-4 leading-snug">
            {(b.notes ?? []).filter(Boolean).map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </footer>
  );
}

const unitsLine = (b: VisualBlock) => {
  const units = [...new Set(b.columns.filter((c) => c.kind === "number" && c.unit && c.unit !== "count").map((c) => displayUnit(c.unit)))];
  return units.length ? `Units: ${units.join(", ")}` : "";
};

export function VisualCard({ b, lang }: { b: VisualBlock; lang: Lang }) {
  const [view, setView] = useState<"visual" | "table">("visual");
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const nav = useCopilotNav();
  const fields = fieldIdsOf(b);
  const mapIds = b.highlight_ids?.length ? b.highlight_ids.filter((h) => fields.includes(h)) : fields;
  const hasTwin = b.chart !== "table";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toTSV(b.columns, b.rows));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast({ tone: "warning", title: "Copy is blocked by this browser", description: "Use the table view and select the rows instead." });
    }
  };
  return (
    <section className="flex flex-col gap-2.5 rounded-[16px] border border-border bg-surface p-3 shadow-1" aria-label={b.title} data-testid="copilot-visual" data-chart={b.chart} data-dataset-kind={b.dataset_kind}>
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-[13.5px] font-semibold leading-snug text-ink" dir="auto">
            {b.title}
          </h4>
          {b.caption ? (
            <p className="mt-0.5 text-[12.5px] leading-snug text-ink-secondary" dir="auto">
              {b.caption}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton label={copied ? "Copied" : "Copy the data"} size="sm" onClick={copy}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </IconButton>
          <IconButton label="Expand" size="sm" onClick={() => setExpanded(true)}>
            <Maximize2 size={14} />
          </IconButton>
        </div>
      </header>
      <div className="flex flex-wrap items-center gap-1.5">
        {hasTwin ? (
          <Segmented
            size="sm"
            label="View"
            value={view}
            onChange={setView}
            options={[
              { value: "visual", label: <><BarChart3 size={12} aria-hidden /> {b.chart === "kpi" ? "Cards" : b.chart === "map" ? "Map" : b.chart === "steps" ? "Steps" : "Chart"}</> }, // prettier-ignore
              { value: "table", label: <><Table2 size={12} aria-hidden /> Data</> }, // prettier-ignore
            ]}
          />
        ) : null}
        {mapIds.length ? (
          <Button size="sm" variant="ghost" onClick={() => nav.showFields(mapIds)} data-testid="copilot-show-on-map">
            <MapIcon size={13} aria-hidden /> Show on map
          </Button>
        ) : null}
        {b.auto ? (
          <Chip size="sm" tone="info" icon={<Wand2 size={11} aria-hidden />}>
            Shown without explanation
          </Chip>
        ) : null}
      </div>
      <div className="min-w-0">{view === "visual" || !hasTwin ? <VisualBody b={b} lang={lang} /> : <VisualTable b={b} lang={lang} />}</div>
      {b.truncated ? (
        <p className="text-[11.5px] text-ink-tertiary">
          Showing {b.rows.length} of {b.row_count} rows
        </p>
      ) : null}
      <SourceFooter b={b} />
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent title={b.title} description={[b.caption, unitsLine(b)].filter(Boolean).join(" · ")} wide>
          <div className="flex flex-col gap-4 p-5">
            {hasTwin ? <VisualBody b={b} lang={lang} tall /> : null}
            <VisualTable b={b} lang={lang} maxHeight={480} />
            <SourceFooter b={b} />
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

