/**
 * Season replay (F09, PRD §7.1): one shared date cursor drives the map (edge activity,
 * pond inventory) and every trace. Values are the run's actual daily series; gaps stay gaps;
 * yield appears only at harvest — never as an interpolated daily curve.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useReducedMotion } from "@/app/environment";
import { useTimeline } from "@/lib/api/queries";
import { dateIndex, fieldMetricMap, runMetrics, type SeriesDef, type Timeline } from "@/lib/api/adapters";
import type { PlanKind, RunResult } from "@/lib/api/types";
import type { FieldVisual } from "@/components/map/engine";
import { ramp } from "@/components/map/palette";
import { useCanopyFrames } from "./useCanopyFrames";
import { formatDate, formatDateShort, formatWithUnit, shortId } from "@/lib/formatting";
import { MapSlot } from "@/components/map/MapSlot";
import { getEngine, useMapRuntime } from "@/components/map/runtime";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, EstimateBadge, Skeleton, StatePanel } from "@/components/status";
import { IconButton } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/primitives";
import { useShell } from "@/components/layout/AppShell";
import { CompareTabs } from "./CompareTabs";
import { GROUP_LABEL, planName } from "@/lib/glossary";
import { useLadderRuns } from "./useLadder";
import { PLAN_LABEL } from "@/features/workspace/useScenario";

type Panel = { key: string; title: string; summary: string; ids: string[]; lines: string[] };
/**
 * Fixed reading order of the run's daily series (T10.4): water ledger volumes, weather and
 * irrigation depths, crop growth, soil water. Any series the API adds later lands in "Other".
 */
const PANELS: Panel[] = [
  {
    key: "water",
    title: "Water at the field",
    summary: "Ledger volumes on each day: canal receipt, groundwater pumping and gross application.",
    ids: ["field_application_m3", "canal_receipt_m3", "pump_m3", "pond_release_m3", "permitted_receipt_m3"],
    lines: [],
  },
  {
    key: "weather",
    title: "Rain, irrigation and evaporative demand",
    summary: "Daily depths: precipitation and gross irrigation (bars) against reference ET₀ and crop ET (lines).",
    ids: ["precipitation_mm", "gross_irrigation_mm", "reference_et_mm", "et_mm"],
    lines: ["reference_et_mm", "et_mm"],
  },
  {
    key: "crop",
    title: "Crop growth",
    summary: "Canopy cover and above-ground biomass from the crop model. Yield exists only at harvest.",
    ids: ["canopy_fraction", "biomass_kg_ha"],
    lines: ["canopy_fraction", "biomass_kg_ha"],
  },
  {
    key: "soil",
    title: "Soil water",
    summary: "Root-zone and whole-profile water (lines); transpiration, soil evaporation, deep percolation and runoff (bars).",
    ids: ["root_zone_water_mm", "soil_profile_water_mm", "transpiration_mm", "evaporation_mm", "deep_percolation_mm", "runoff_mm"],
    lines: ["root_zone_water_mm", "soil_profile_water_mm"],
  },
];
const PANEL_IDS = new Set(PANELS.flatMap((p) => p.ids));

/** Bare soil → full canopy. Monotonic lightness so it reads without hue. */
const CANOPY_RAMP = ["#b8a07a", "#d9cb8e", "#a9c56f", "#5e9e55", "#24693f"];
const MAX_CANOPY_NORM = 1;

export function ReplayScreen() {
  const { sel, fieldIndex, sortedFields } = usePilotData();
  const { byKind } = useLadderRuns();
  const { mobile } = useShell();
  const kinds = (["B0", "B1", "P", "R"] as PlanKind[]).filter((k) => byKind.has(k));
  const [kind, setKind] = useState<PlanKind | null>(null);
  const [fieldsShow, setFieldsShow] = useState<"canopy" | "yield">("canopy");
  const k = kind && byKind.has(kind) ? kind : kinds.includes("P") ? "P" : kinds[0] ?? null;
  const run = k ? byKind.get(k)! : null;
  const runId = run?.run_id ?? sel.runId;
  const fieldId = sel.fieldId;
  const tl = useTimeline(runId, fieldId);
  const net = useTimeline(runId, null);
  const timeline = tl.data;
  const dates = timeline?.dates ?? net.data?.dates ?? [];
  const idx = Math.max(0, dateIndex(dates, sel.date));
  const cursor = dates[idx] ?? null;

  // Every field's exact canopy series: the 3D blocks grow with the crop model through the season.
  const fieldIds = useMemo(() => sortedFields.map((f) => f.id), [sortedFields]);
  const canopy = useCanopyFrames(runId, fieldIds, fieldsShow === "canopy");
  const canopyVisuals = useMemo(() => {
    if (fieldsShow !== "canopy" || !canopy.byField.size) return null;
    const ci = dateIndex(canopy.dates, cursor);
    const out = new Map<string, FieldVisual>();
    for (const id of fieldIds) {
      const vals = canopy.byField.get(id);
      const v = vals && ci >= 0 ? vals[ci] ?? null : null;
      out.set(id, { value: v, color: v === null ? "#c9c3b4" : ramp(CANOPY_RAMP, v / MAX_CANOPY_NORM), norm: v === null ? 0 : Math.min(1, v / MAX_CANOPY_NORM) });
    }
    return out;
  }, [fieldsShow, canopy, cursor, fieldIds]);

  // Default field for the replay: keep URL selection, else first tail field.
  useEffect(() => {
    if (!fieldId && sortedFields.length) {
      const tail = sortedFields.find((f) => f.group === "tail") ?? sortedFields[0];
      sel.setParams({ field: tail.id });
    }
  }, [fieldId, sortedFields]); // eslint-disable-line react-hooks/exhaustive-deps

  const setIdx = useCallback((i: number) => {
    const d = dates[Math.max(0, Math.min(dates.length - 1, i))];
    if (d) sel.setParams({ date: d.slice(0, 10) });
  }, [dates, sel]);

  // Drive the persistent map from the same cursor
  const ready = useMapRuntime((s) => s.ready);
  const source = net.data ?? timeline;
  useEffect(() => {
    const e = getEngine();
    if (!e || !ready || !source) return;
    const i = dateIndex(source.dates, cursor);
    const flows = new Map<string, number>();
    for (const [eid, vals] of Object.entries(source.edgeFlows)) {
      const v = i >= 0 ? vals[i] : null;
      if (typeof v === "number") flows.set(eid, v);
    }
    e.setEdgeFlows(Object.keys(source.edgeFlows).length ? flows : null);
    const ponds = new Map<string, { inventory_m3: number | null; capacity_m3: number | null }>();
    for (const [aid, p] of Object.entries(source.ponds)) ponds.set(aid, { inventory_m3: i >= 0 ? p.inventory[i] ?? null : null, capacity_m3: p.capacity });
    e.setPondLevels(ponds.size ? ponds : null);
  }, [ready, source, cursor]);
  useEffect(
    () => () => {
      getEngine()?.setEdgeFlows(null);
      getEngine()?.setPondLevels(null);
    },
    [],
  );

  const activeEdges = useMemo(() => {
    if (!source) return null;
    const i = dateIndex(source.dates, cursor);
    const entries = Object.entries(source.edgeFlows);
    if (!entries.length || i < 0) return null;
    const on = entries.filter(([, v]) => typeof v[i] === "number" && (v[i] as number) > 0);
    const total = on.reduce((a, [, v]) => a + (v[i] as number), 0);
    return { on: on.length, of: entries.length, total };
  }, [source, cursor]);

  if (!runId)
    return (
      <div className="flex flex-1 flex-col">
        <CompareTabs />
        <div className="grid flex-1 place-items-center p-6">
          <div className="max-w-[520px]">
            <StatePanel state="empty" art="chart" title="Nothing to replay yet" action={{ label: "Find the best plan first", onClick: () => sel.go("workspace") }}>
              The replay steps through a solved season day by day: when canal water arrived, when it was applied, pond levels and how the crop grew.
            </StatePanel>
          </div>
        </div>
      </div>
    );

  const field = fieldId ? fieldIndex.get(fieldId) : null;
  const ci = dateIndex(timeline?.dates ?? [], cursor);
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="replay">
      <CompareTabs />
      <div className="sticky top-0 z-30 border-b border-border bg-surface/95 px-3 py-3 backdrop-blur md:px-6" data-tour="timeline">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0">
            <div className="eyebrow">Season replay · one field, day by day</div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="display shrink-0 text-[20px] leading-tight text-ink">{field?.label ?? fieldId ?? "Select a field"}</span>
              {field?.group ? <Chip size="sm" tone={field.group === "tail" ? "wheat" : "neutral"}>{GROUP_LABEL[field.group] ?? field.group}</Chip> : null}
              <Chip size="sm" tone="info" title={run?.run_id ?? runId}>
                {k ? planName(k) : "run"} · {shortId(runId)}
              </Chip>
              <EstimateBadge kind="exact" />
            </div>
          </div>
          {kinds.length > 1 ? (
            <Segmented label="Plan to replay" size="sm" value={k ?? "P"} onChange={(v) => setKind(v as PlanKind)} options={kinds.map((x) => ({ value: x, label: planName(x), title: `${x} · ${PLAN_LABEL[x]}` }))} />
          ) : null}
          <select
            aria-label="Field to replay"
            className="h-9 rounded-[9px] border border-border-strong/55 bg-surface-raised px-2 text-[13px] text-ink"
            value={fieldId ?? ""}
            onChange={(e) => sel.setParams({ field: e.target.value || null })}
          >
            {sortedFields.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label} {f.group ? `· ${GROUP_LABEL[f.group] ?? f.group}` : ""}
              </option>
            ))}
          </select>
        </div>
        <TimelineController dates={dates} idx={idx} onIdx={setIdx} markers={timeline?.markers ?? []} loading={tl.isLoading && net.isLoading} />
      </div>

      <div className="grid gap-4 p-3 md:p-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className={mobile ? "relative h-[52vh] overflow-hidden rounded-[18px] border border-border" : "relative h-[min(68vh,720px)] overflow-hidden rounded-[18px] border border-border shadow-1 xl:sticky xl:top-[140px]"}>
          <MapSlot
            runId={runId}
            className="absolute inset-0"
            compactControls
            dimAmount={0.12}
            visualsOverride={canopyVisuals}
            hoverValue={(fid) => {
              const v = canopyVisuals?.get(fid)?.value;
              return typeof v === "number" ? `${Math.round(v * 100)}% canopy` : "No canopy value";
            }}
            legendOverride={<CanopyLegend loaded={canopy.loaded} total={canopy.total} failed={canopy.failed} />}
            label="Replay map: field canopy, canal activity and pond levels at the cursor date"
          >
            <div className="pointer-events-none absolute left-3 top-3 z-20 rounded-[12px] bg-ink/90 px-3 py-2 text-canvas shadow-2">
              <div className="text-[11px] opacity-75">Day shown</div>
              <div className="num text-[17px] font-semibold leading-tight" data-testid="replay-date">{cursor ? formatDate(cursor) : "—"}</div>
              {activeEdges ? (
                <div className="num mt-0.5 text-[11px] opacity-80">
                  {activeEdges.on}/{activeEdges.of} reaches flowing · {formatWithUnit(activeEdges.total, "m3")}
                </div>
              ) : null}
            </div>
            <div className={mobile ? "pointer-events-auto absolute left-3 top-[86px] z-20 rounded-[12px] shadow-2" : "pointer-events-auto absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-[12px] shadow-2"}>
              <Segmented
                label="Fields show"
                size="sm"
                value={fieldsShow}
                onChange={(v) => setFieldsShow(v as "canopy" | "yield")}
                className="bg-surface/95 backdrop-blur"
                options={[
                  { value: "canopy", label: mobile ? "Canopy" : "Canopy by date", title: "Crop-model canopy cover on the cursor date" },
                  { value: "yield", label: mobile ? "Yield" : "Harvest yield", title: "Exact modeled yield at harvest" },
                ]}
              />
            </div>
            {!Object.keys(source?.edgeFlows ?? {}).length && source ? (
              <div className="pointer-events-none absolute inset-x-3 bottom-14 z-20 mx-auto max-w-[360px] rounded-[10px] bg-surface/95 px-3 py-2 text-center text-[12px] text-ink-secondary shadow-2">
                This run's timeline has no per-edge delivery series, so canal activity is not animated by date.
              </div>
            ) : null}
          </MapSlot>
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          {tl.isLoading ? (
            [0, 1, 2].map((i) => <Skeleton key={i} className="h-60" />)
          ) : tl.error ? (
            <StatePanel state="error" error={tl.error} title="Timeline unavailable" />
          ) : timeline && timeline.series.length ? (
            <>
              <FieldDay timeline={timeline} cursorIdx={ci} run={run} fieldId={fieldId} />
              {PANELS.map((p) => {
                const series = p.ids.map((id) => timeline.series.find((x) => x.id === id)).filter((x): x is SeriesDef => !!x && x.values.some((v) => v !== null));
                if (!series.length) return null;
                return <TracePanel key={p.key} panel={p} series={series} dates={timeline.dates} cursorIdx={ci} onPick={setIdx} />;
              })}
              <OtherSeries timeline={timeline} cursorIdx={ci} onPick={setIdx} />
            </>
          ) : (
            <StatePanel state="empty" title="No series for this field">
              The run returned no daily series for {field?.label ?? "this field"}.
            </StatePanel>
          )}
        </div>
      </div>
    </div>
  );
}

function CanopyLegend({ loaded, total, failed }: { loaded: number; total: number; failed: number }) {
  return (
    <div className="pointer-events-auto w-[200px] rounded-[12px] md:w-[236px] border border-border bg-surface/95 px-3 py-2.5 text-[12px] shadow-2 backdrop-blur" data-testid="canopy-legend">
      <div className="font-semibold text-ink">Canopy cover (crop model)</div>
      <div className="mt-1.5 h-2.5 rounded-full" style={{ background: `linear-gradient(90deg, ${CANOPY_RAMP.join(",")})` }} aria-hidden />
      <div className="num mt-1 flex justify-between text-[11px] text-ink-secondary">
        <span>0% bare</span>
        <span>100% closed</span>
      </div>
      <p className="mt-1.5 hidden text-[11px] leading-snug text-ink-secondary md:block">
        Block height and colour are each field's exact daily canopy fraction. Grey = no model value that day.
      </p>
      {loaded < total ? (
        <p className="num mt-1 text-[11px] text-ink-tertiary">
          Loading field series {loaded}/{total}
          {failed ? ` · ${failed} failed` : ""}
        </p>
      ) : null}
    </div>
  );
}

/** Values at the cursor for the selected field, plus the exact harvest yield metric. */
function FieldDay({ timeline, cursorIdx, run, fieldId }: { timeline: Timeline; cursorIdx: number; run: RunResult | null; fieldId: string | null }) {
  const get = (id: string) => {
    const s = timeline.series.find((x) => x.id === id);
    const v = s && cursorIdx >= 0 ? s.values[cursorIdx] : null;
    return { v: v ?? null, unit: s?.unit ?? "" };
  };
  const yieldM = fieldId ? fieldMetricMap(runMetrics(run), "field_yield_kg_ha", "yield_kg_ha").get(fieldId) ?? null : null;
  const cells: { label: string; id: string; fmt?: (v: number) => string }[] = [
    { label: "Canopy", id: "canopy_fraction", fmt: (v) => `${Math.round(v * 100)}%` },
    { label: "Biomass", id: "biomass_kg_ha" },
    { label: "Root-zone water", id: "root_zone_water_mm" },
    { label: "Crop ET", id: "et_mm" },
    { label: "Applied", id: "field_application_m3" },
  ];
  return (
    <section className="rounded-[18px] border border-border bg-surface px-4 py-3 shadow-1" aria-label="Selected field on the cursor date" data-testid="field-day">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
        {cells.map((c) => {
          const { v, unit } = get(c.id);
          return (
            <div key={c.id} className="min-w-0">
              <div className="truncate text-[11px] text-ink-secondary">{c.label}</div>
              <div className="num text-[15px] font-semibold text-ink">{v === null ? <span className="text-ink-tertiary">—</span> : c.fmt ? c.fmt(v) : formatWithUnit(v, unit)}</div>
            </div>
          );
        })}
        <div className="min-w-0">
          <div className="truncate text-[11px] text-ink-secondary">Yield at harvest</div>
          <div className="num text-[15px] font-semibold text-vegetation">
            {yieldM && yieldM.status === "available" && typeof yieldM.value === "number" ? formatWithUnit(yieldM.value, yieldM.unit) : <span className="text-ink-tertiary">—</span>}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-ink-tertiary">Yield is reported only at harvest; daily traces show canopy and biomass, never an interpolated yield curve.</p>
    </section>
  );
}

function OtherSeries({ timeline, cursorIdx, onPick }: { timeline: Timeline; cursorIdx: number; onPick: (i: number) => void }) {
  const rest = timeline.series.filter((s) => !PANEL_IDS.has(s.id) && s.values.some((v) => v !== null));
  if (!rest.length) return null;
  return (
    <TracePanel
      panel={{ key: "other", title: "Other series", summary: "Additional daily series reported by the run.", ids: rest.map((s) => s.id), lines: rest.filter((s) => /water|state|storage|inventory/.test(s.id)).map((s) => s.id) }}
      series={rest}
      dates={timeline.dates}
      cursorIdx={cursorIdx}
      onPick={onPick}
    />
  );
}

function TracePanel({ panel, series, dates, cursorIdx, onPick }: { panel: Panel; series: SeriesDef[]; dates: string[]; cursorIdx: number; onPick: (i: number) => void }) {
  const t = chartTokens();
  const units = [...new Set(series.map((s) => s.unit))];
  const option = useMemo(() => {
    const b = baseOption();
    const legendRows = Math.ceil(series.length / 3);
    return {
      ...b,
      grid: { left: 56, right: units.length > 1 ? 56 : 18, top: 18 + legendRows * 18 + 16, bottom: 28 },
      legend: { top: 0, left: 0, right: 0, itemWidth: 12, itemHeight: 8, itemGap: 14, textStyle: { color: t.ink2, fontSize: 11 }, icon: "roundRect" },
      tooltip: { ...(b.tooltip as object), trigger: "axis", valueFormatter: (v: number | null) => (v === null || v === undefined ? "no data" : String(Math.round(v * 100) / 100)) },
      xAxis: { ...(b.xAxis as object), type: "category", data: dates.map((d) => d.slice(0, 10)), axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: string) => formatDateShort(v), hideOverlap: true }, boundaryGap: true },
      yAxis: units.slice(0, 2).map((u, i) => ({
        ...(b.yAxis as object),
        type: "value",
        name: unitLabel(u),
        nameGap: 10,
        nameTextStyle: { color: t.ink3, fontSize: 11, align: i === 0 ? "left" : "right", padding: i === 0 ? [0, 0, 0, -40] : [0, -40, 0, 0] },
        position: i === 0 ? "left" : "right",
        splitLine: { show: i === 0, lineStyle: { color: t.border, opacity: 0.7 } },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => compact(v) },
      })),
      series: series.map((s, i) => {
        const axis = Math.min(1, units.indexOf(s.unit));
        const line = panel.lines.includes(s.id);
        const color = SERIES_COLOR[s.id] ?? t.series[i % t.series.length];
        return {
          name: `${shortLabel(s.label)}`,
          type: line ? "line" : "bar",
          yAxisIndex: axis,
          data: s.values,
          connectNulls: false,
          showSymbol: false,
          smooth: false,
          // Daily bars overlap in one slot (largest series first) so a 1-day event stays visible at season scale.
          barWidth: "70%",
          barMinWidth: 2,
          barGap: "-100%",
          z: line ? 4 : 2 + i * 0.1,
          lineStyle: { width: 2, color },
          itemStyle: { color, opacity: line ? 1 : i === 0 && series.length > 1 ? 0.45 : 0.95, borderRadius: [2, 2, 0, 0] },
          areaStyle: line && (s.id === "canopy_fraction" || s.id === "root_zone_water_mm") ? { color, opacity: 0.1 } : undefined,
          markLine:
            i === 0 && cursorIdx >= 0
              ? { silent: true, symbol: "none", animation: false, lineStyle: { color: t.ink, width: 1.5, type: "solid" }, label: { show: false }, data: [{ xAxis: cursorIdx }] }
              : undefined,
        };
      }),
    };
  }, [series, dates, cursorIdx, units, t, panel.lines]);
  const near = useMemo(() => {
    const lo = Math.max(0, (cursorIdx < 0 ? 0 : cursorIdx) - 7);
    return dates.slice(lo, lo + 15).map((d, j) => ({ d, i: lo + j }));
  }, [dates, cursorIdx]);
  return (
    <ChartPanel
      id={`trace-${panel.key}`}
      title={panel.title}
      summary={panel.summary}
      chart={
        <EChart
          option={option}
          height={220}
          groupId="replay"
          ariaLabel={`${panel.title} daily chart; use the table view for values`}
          onEvents={{ click: (p) => { const i = (p as { dataIndex?: number }).dataIndex; if (typeof i === "number") onPick(i); } }}
        />
      }
      table={
        <DataTable
          dense
          caption={`${panel.title} around the cursor date`}
          columns={[{ key: "date", label: "Date" }, ...series.map((s) => ({ key: s.id, label: `${shortLabel(s.label)} (${unitLabel(s.unit)})`, align: "right" as const }))]}
          rows={near.map(({ d, i }) => ({
            date: <span className={i === cursorIdx ? "font-semibold" : ""}>{formatDate(d)}</span>,
            ...Object.fromEntries(series.map((s) => [s.id, s.values[i] === null || s.values[i] === undefined ? <span className="text-ink-tertiary">no data</span> : formatWithUnit(s.values[i]!, s.unit)])),
          }))}
        />
      }
    />
  );
}

const SERIES_COLOR: Record<string, string> = {
  canal_receipt_m3: "#087F8C",
  pump_m3: "#A35B08",
  field_application_m3: "#386A4B",
  precipitation_mm: "#245FBD",
  gross_irrigation_mm: "#3E9EA8",
  reference_et_mm: "#A63E32",
  et_mm: "#C7853A",
  canopy_fraction: "#386A4B",
  biomass_kg_ha: "#7A5C2E",
  root_zone_water_mm: "#087F8C",
  soil_profile_water_mm: "#4B6260",
  transpiration_mm: "#5E9E55",
  evaporation_mm: "#C7853A",
  deep_percolation_mm: "#245FBD",
  runoff_mm: "#A63E32",
};

function shortLabel(l: string) {
  return l.replace(/\s*\((crop model|crop model input)\)/i, "").trim();
}
function unitLabel(u: string) {
  return u.replace("m3", "m³").replace("fraction", "fraction");
}
function compact(v: number) {
  const a = Math.abs(v);
  if (a >= 1000) return `${Math.round(v / 100) / 10}k`;
  if (a > 0 && a < 1) return String(Math.round(v * 100) / 100);
  return String(Math.round(v));
}

export function TimelineController({
  dates,
  idx,
  onIdx,
  markers,
  loading,
}: {
  dates: string[];
  idx: number;
  onIdx: (i: number) => void;
  markers: { date: string; label: string }[];
  loading?: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const reduced = useReducedMotion();
  const idxRef = useRef(idx);
  idxRef.current = idx;
  useEffect(() => {
    if (!playing || !dates.length) return;
    const t = setInterval(() => {
      const n = idxRef.current + 1;
      if (n >= dates.length) {
        setPlaying(false);
        return;
      }
      onIdx(n);
    }, reduced ? 600 : 220);
    return () => clearInterval(t);
  }, [playing, dates.length, onIdx, reduced]);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === " " || e.key === "k") {
      e.preventDefault();
      setPlaying((p) => !p);
    } else if (e.key === "ArrowRight" && !(e.target as HTMLElement).matches("input[type=range]")) onIdx(idx + (e.shiftKey ? 7 : 1));
    else if (e.key === "ArrowLeft" && !(e.target as HTMLElement).matches("input[type=range]")) onIdx(idx - (e.shiftKey ? 7 : 1));
  };
  if (loading) return <Skeleton className="mt-2 h-9" />;
  if (!dates.length) return <p className="mt-2 text-[12px] text-ink-secondary">No dated series in this run.</p>;
  return (
    <div className="mt-2 flex items-center gap-2" onKeyDown={onKey} role="group" aria-label="Timeline. Space plays or pauses; arrow keys step by day, Shift+arrow by week." data-testid="timeline">
      <IconButton label="First day" size="sm" onClick={() => onIdx(0)}>
        <SkipBack size={15} />
      </IconButton>
      <IconButton label="Previous week" size="sm" onClick={() => onIdx(idx - 7)}>
        <StepBack size={15} />
      </IconButton>
      <IconButton label={playing ? "Pause" : "Play"} size="sm" variant="primary" onClick={() => setPlaying((p) => !p)} data-testid="play">
        {playing ? <Pause size={15} /> : <Play size={15} />}
      </IconButton>
      <IconButton label="Next week" size="sm" onClick={() => onIdx(idx + 7)}>
        <StepForward size={15} />
      </IconButton>
      <IconButton label="Last day" size="sm" onClick={() => onIdx(dates.length - 1)}>
        <SkipForward size={15} />
      </IconButton>
      <div className="relative flex-1">
        <input
          type="range"
          min={0}
          max={dates.length - 1}
          value={idx}
          onChange={(e) => onIdx(Number(e.target.value))}
          aria-label="Replay date"
          aria-valuetext={formatDate(dates[idx])}
          className="w-full accent-[var(--water)]"
          data-testid="date-slider"
        />
        <div className="pointer-events-none absolute inset-x-0 -bottom-1 h-2">
          {markers.map((m) => {
            const i = dateIndex(dates, m.date);
            if (i < 0) return null;
            return <span key={m.date + m.label} title={m.label} className="absolute h-2 w-px bg-vegetation" style={{ left: `${(i / Math.max(1, dates.length - 1)) * 100}%` }} />;
          })}
        </div>
      </div>
      <span className="num w-[92px] shrink-0 text-right text-[12px] font-medium text-ink">{formatDate(dates[idx])}</span>
    </div>
  );
}
