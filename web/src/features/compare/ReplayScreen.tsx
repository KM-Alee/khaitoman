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
import { dateIndex, type SeriesDef, type Timeline } from "@/lib/api/adapters";
import type { PlanKind } from "@/lib/api/types";
import { formatDate, formatDateShort, formatWithUnit, shortId } from "@/lib/formatting";
import { MapSlot } from "@/components/map/MapSlot";
import { getEngine, useMapRuntime } from "@/components/map/runtime";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, EstimateBadge, Skeleton, StatePanel } from "@/components/status";
import { IconButton } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/primitives";
import { useShell } from "@/components/layout/AppShell";
import { CompareTabs } from "./CompareTabs";
import { useLadderRuns } from "./CompareScreen";
import { PLAN_LABEL } from "@/features/workspace/useScenario";

type Panel = { key: string; title: string; summary: string; match: (s: SeriesDef) => boolean };
const PANELS: Panel[] = [
  {
    key: "water",
    title: "Water at the field",
    summary: "Permitted and actual canal receipts, field application, rain and pumping.",
    match: (s) => /water|receipt|application|irrigation|rain|precip|pump|groundwater/i.test(`${s.kind} ${s.id}`) && !/pond|storage|soil/i.test(`${s.kind} ${s.id}`),
  },
  { key: "storage", title: "Pond storage", summary: "Inventory, fill and release of storage serving this field.", match: (s) => /pond|storage/i.test(`${s.kind} ${s.id}`) },
  {
    key: "crop",
    title: "Crop and soil state",
    summary: "Canopy cover, biomass and root-zone soil water from the crop model.",
    match: (s) => /crop|canopy|biomass|soil|cc|et|transp/i.test(`${s.kind} ${s.id}`),
  },
];

const LINE_KIND = /canopy|biomass|soil|storage|inventory|cumulative|state|cc\b/i;

export function ReplayScreen() {
  const { sel, fieldIndex, sortedFields } = usePilotData();
  const { byKind } = useLadderRuns();
  const { mobile } = useShell();
  const kinds = (["B0", "B1", "P", "R"] as PlanKind[]).filter((k) => byKind.has(k));
  const [kind, setKind] = useState<PlanKind | null>(null);
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

  if (!runId)
    return (
      <div className="flex flex-1 flex-col">
        <CompareTabs />
        <div className="grid flex-1 place-items-center p-6">
          <div className="max-w-[520px]">
            <StatePanel state="empty" title="No run to replay" action={{ label: "Go to Workspace", onClick: () => sel.go("workspace") }}>
              Replay needs a completed run. Solve a plan first; replay then shows its dated receipts, storage and crop traces.
            </StatePanel>
          </div>
        </div>
      </div>
    );

  const field = fieldId ? fieldIndex.get(fieldId) : null;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="replay">
      <CompareTabs />
      <div className="sticky top-0 z-30 border-b border-border bg-surface/95 px-3 py-2 backdrop-blur md:px-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0">
            <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">Replaying</div>
            <div className="flex items-center gap-2">
              <span className="truncate text-[15px] font-semibold text-ink">{field?.label ?? fieldId ?? "Select a field"}</span>
              <Chip size="sm" tone="info">{k ? `${k} · ${PLAN_LABEL[k]}` : "run"} {shortId(runId)}</Chip>
              <EstimateBadge kind="exact" />
            </div>
          </div>
          {kinds.length > 1 ? (
            <Segmented label="Run to replay" size="sm" value={k ?? "P"} onChange={(v) => setKind(v as PlanKind)} options={kinds.map((x) => ({ value: x, label: x, title: PLAN_LABEL[x] }))} />
          ) : null}
          <select
            aria-label="Field to replay"
            className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[13px] text-ink"
            value={fieldId ?? ""}
            onChange={(e) => sel.setParams({ field: e.target.value || null })}
          >
            {sortedFields.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label} {f.group ? `· ${f.group}` : ""}
              </option>
            ))}
          </select>
        </div>
        <TimelineController dates={dates} idx={idx} onIdx={setIdx} markers={timeline?.markers ?? []} loading={tl.isLoading} />
      </div>

      <div className="grid gap-3 p-3 md:p-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className={mobile ? "relative h-[52vh] overflow-hidden rounded-[14px] border border-border" : "relative h-[min(64vh,680px)] overflow-hidden rounded-[14px] border border-border xl:sticky xl:top-[124px]"}>
          <MapSlot runId={runId} className="absolute inset-0" compactControls label="Replay map: canal activity and pond levels at the cursor date">
            <div className="pointer-events-none absolute left-3 top-3 z-20 rounded-[10px] bg-ink/90 px-3 py-1.5 text-canvas shadow-2">
              <div className="text-[11px] opacity-75">Cursor</div>
              <div className="num text-[15px] font-semibold" data-testid="replay-date">{cursor ? formatDate(cursor) : "—"}</div>
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
              <HarvestLine timeline={timeline} />
              {PANELS.map((p) => {
                const series = timeline.series.filter((s) => p.match(s));
                if (!series.length) return null;
                return <TracePanel key={p.key} panel={p} series={series} dates={timeline.dates} cursorIdx={dateIndex(timeline.dates, cursor)} onPick={setIdx} />;
              })}
              <OtherSeries timeline={timeline} cursorIdx={dateIndex(timeline.dates, cursor)} onPick={setIdx} />
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

function HarvestLine({ timeline }: { timeline: Timeline }) {
  if (!timeline.harvest) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-[12px] border border-border bg-surface px-4 py-2.5 text-[13px] shadow-1">
      <span className="font-semibold text-ink">Harvest</span>
      <span className="num text-ink-secondary">{formatDate(timeline.harvest.date)}</span>
      {typeof timeline.harvest.yieldKgHa === "number" ? <span className="num font-semibold text-ink">{formatWithUnit(timeline.harvest.yieldKgHa, "kg/ha")}</span> : null}
      <span className="text-[12px] text-ink-tertiary">Yield exists only at harvest; pre-harvest traces show canopy and biomass.</span>
    </div>
  );
}

function OtherSeries({ timeline, cursorIdx, onPick }: { timeline: Timeline; cursorIdx: number; onPick: (i: number) => void }) {
  const rest = timeline.series.filter((s) => !PANELS.some((p) => p.match(s)));
  if (!rest.length) return null;
  return <TracePanel panel={{ key: "other", title: "Other series", summary: "Additional daily series reported by the run.", match: () => true }} series={rest} dates={timeline.dates} cursorIdx={cursorIdx} onPick={onPick} />;
}

function TracePanel({ panel, series, dates, cursorIdx, onPick }: { panel: Panel; series: SeriesDef[]; dates: string[]; cursorIdx: number; onPick: (i: number) => void }) {
  const t = chartTokens();
  const units = [...new Set(series.map((s) => s.unit))];
  const option = useMemo(() => {
    const b = baseOption();
    return {
      ...b,
      grid: { left: 52, right: units.length > 1 ? 52 : 16, top: 30, bottom: 28 },
      legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: t.ink2, fontSize: 11 }, icon: "roundRect" },
      tooltip: { ...(b.tooltip as object), trigger: "axis", valueFormatter: (v: number | null) => (v === null || v === undefined ? "no data" : String(Math.round(v * 100) / 100)) },
      xAxis: { ...(b.xAxis as object), type: "category", data: dates.map((d) => d.slice(0, 10)), axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: string) => formatDateShort(v) }, boundaryGap: true },
      yAxis: units.slice(0, 2).map((u, i) => ({ ...(b.yAxis as object), type: "value", name: u.replace("m3", "m³"), position: i === 0 ? "left" : "right", splitLine: { show: i === 0, lineStyle: { color: t.border, opacity: 0.7 } } })),
      series: series.map((s, i) => {
        const axis = Math.min(1, units.indexOf(s.unit));
        const line = LINE_KIND.test(`${s.id} ${s.kind}`);
        const color = t.series[i % t.series.length];
        return {
          name: `${s.label} (${s.unit.replace("m3", "m³")})`,
          type: line ? "line" : "bar",
          yAxisIndex: axis,
          data: s.values,
          connectNulls: false,
          showSymbol: false,
          smooth: false,
          barMaxWidth: 6,
          lineStyle: { width: 2, color },
          itemStyle: { color },
          areaStyle: line && i === 0 ? { color, opacity: 0.08 } : undefined,
          markLine:
            i === 0 && cursorIdx >= 0
              ? { silent: true, symbol: "none", animation: false, lineStyle: { color: t.ink, width: 1.5, type: "solid" }, label: { show: false }, data: [{ xAxis: cursorIdx }] }
              : undefined,
        };
      }),
    };
  }, [series, dates, cursorIdx, units, t]);
  const near = useMemo(() => {
    // Table twin: ±7 days around the cursor, plus totals computed by the server are not assumed here.
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
          height={210}
          groupId="replay"
          ariaLabel={`${panel.title} daily chart; use the table view for values`}
          onEvents={{ click: (p) => { const i = (p as { dataIndex?: number }).dataIndex; if (typeof i === "number") onPick(i); } }}
        />
      }
      table={
        <DataTable
          dense
          caption={`${panel.title} around the cursor date`}
          columns={[{ key: "date", label: "Date" }, ...series.map((s) => ({ key: s.id, label: `${s.label} (${s.unit.replace("m3", "m³")})`, align: "right" as const }))]}
          rows={near.map(({ d, i }) => ({
            date: <span className={i === cursorIdx ? "font-semibold" : ""}>{formatDate(d)}</span>,
            ...Object.fromEntries(series.map((s) => [s.id, s.values[i] === null || s.values[i] === undefined ? <span className="text-ink-tertiary">no data</span> : formatWithUnit(s.values[i]!, s.unit)])),
          }))}
        />
      }
    />
  );
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
