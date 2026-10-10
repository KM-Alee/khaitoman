import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  Box,
  Compass,
  Layers,
  Maximize2,
  Minus,
  Mountain,
  Orbit,
  Plus,
  Square,
} from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI, type MapMetric } from "@/app/store";
import { useReducedMotion } from "@/app/environment";
import { cn } from "@/lib/cn";
import { formatArea, formatWithUnit } from "@/lib/formatting";
import { IconButton } from "@/components/ui/Button";
import { Popover, PopoverContent, PopoverTrigger, Segmented, Switch } from "@/components/ui/primitives";
import { attachMap, detachMap, getEngine, useMapRuntime } from "./runtime";
import { METRIC_DEFS, useFieldVisuals, type FieldVisualResult } from "./useFieldVisuals";
import type { FieldVisual } from "./engine";
import { useHdStatus } from "./hdImagery";
import { MapLegend } from "./MapLegend";

export interface MapSlotProps {
  runId: string | null;
  baselineRunId?: string | null;
  metric?: MapMetric;
  sharedDomain?: [number, number] | null;
  className?: string;
  /** Hide the metric switcher (e.g. replay drives its own). */
  compactControls?: boolean;
  showLegend?: boolean;
  children?: ReactNode;
  label?: string;
  highlightFieldIds?: string[] | null;
  onVisuals?: (r: FieldVisualResult) => void;
  /** Screen-owned field colouring (e.g. replay canopy by date); replaces the metric visuals. */
  visualsOverride?: Map<string, FieldVisual> | null;
  /** Legend shown instead of the metric legend while an override is active. */
  legendOverride?: ReactNode;
  /** Fade of unselected fields (0 = none). Defaults to the engine's standard dimming. */
  dimAmount?: number;
  /** Hover-card value while an override is active (e.g. "62% canopy on 10 Jan"). */
  hoverValue?: (fieldId: string) => ReactNode;
}

/** A place where the persistent map is shown, plus its overlay chrome. */
export function MapSlot({
  runId,
  baselineRunId,
  metric: metricProp,
  sharedDomain,
  className,
  compactControls,
  showLegend = true,
  children,
  label = "Pilot map",
  highlightFieldIds,
  onVisuals,
  visualsOverride,
  legendOverride,
  dimAmount,
  hoverValue,
}: MapSlotProps) {
  const slotId = useId();
  const hostRef = useRef<HTMLDivElement>(null);
  const ready = useMapRuntime((s) => s.ready);
  const attachedTo = useMapRuntime((s) => s.attachedTo);
  const storeMetric = useUI((s) => s.mapMetric);
  const metric = metricProp ?? storeMetric;
  const { fieldIndex, sel, map, geoError } = usePilotData();
  const visuals = useFieldVisuals({ runId, baselineRunId, metric, fields: fieldIndex, sharedDomain });

  useLayoutEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    attachMap(el, slotId);
    return () => detachMap(slotId);
  }, [slotId]);

  const attached = attachedTo === slotId;
  useEffect(() => {
    if (!attached || !ready) return;
    getEngine()?.setFieldVisuals(visualsOverride ?? visuals.visuals);
  }, [attached, ready, visuals.visuals, visualsOverride]);
  useEffect(() => {
    if (!attached || !ready || dimAmount === undefined) return;
    getEngine()?.setDimAmount(dimAmount);
    return () => getEngine()?.setDimAmount(0.42);
  }, [attached, ready, dimAmount]);
  useEffect(() => {
    if (!attached || !ready) return;
    getEngine()?.setHighlight(highlightFieldIds ?? null);
    return () => getEngine()?.setHighlight(null);
  }, [attached, ready, highlightFieldIds]);
  useEffect(() => {
    onVisuals?.(visuals);
  }, [visuals, onVisuals]);

  // Keyboard field travel (never when typing in inputs)
  const onKeyDown = (e: React.KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest("input,textarea,select,[contenteditable=true]")) return;
    const eng = getEngine();
    if (!eng) return;
    const ids = eng.fieldIds();
    if (!ids.length) return;
    if (e.key === "]" || e.key === "[") {
      e.preventDefault();
      const cur = sel.fieldId ? ids.indexOf(sel.fieldId) : -1;
      const next = e.key === "]" ? (cur + 1) % ids.length : (cur - 1 + ids.length) % ids.length;
      sel.setParams({ field: ids[next] }, false);
    } else if (e.key === "Escape" && sel.fieldId) {
      sel.setParams({ field: null });
    }
  };

  return (
    <div
      className={cn("relative isolate overflow-hidden bg-[var(--map-bg)]", className)}
      role="region"
      aria-label={label}
      onKeyDown={onKeyDown}
      data-testid="map-slot"
    >
      <div ref={hostRef} className="absolute inset-0 z-0" />
      {!map.data && !map.error ? <MapLoading /> : null}
      {map.error || geoError ? <MapUnavailable /> : null}
      <HoverCard visuals={visuals} override={visualsOverride && hoverValue ? hoverValue : undefined} />
      {showLegend ? (
        <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[calc(100%-96px)] flex-col items-start gap-2">
          {visualsOverride && legendOverride ? legendOverride : <MapLegend metric={metric} visuals={visuals} />}
        </div>
      ) : null}
      <MapControls compact={compactControls} metric={metric} metricControlled={!!metricProp} />
      {children}
    </div>
  );
}

function MapLoading() {
  return (
    <div className="absolute inset-0 z-[5] grid place-items-center bg-[var(--map-bg)]" role="status" aria-live="polite">
      <div className="flex flex-col items-center gap-3 text-ink-secondary">
        <div className="skeleton h-28 w-44 rounded-[16px] opacity-70 [transform:perspective(400px)_rotateX(40deg)]" />
        <span className="text-[12px] font-medium">Loading local imagery and field boundaries…</span>
      </div>
    </div>
  );
}

function MapUnavailable() {
  return (
    <div className="absolute inset-x-3 top-3 z-20 rounded-[12px] border border-danger/30 bg-surface/95 p-3 text-[13px] shadow-2" role="alert">
      <span className="font-semibold text-danger">Map layers unavailable.</span>{" "}
      <span className="text-ink-secondary">The pilot package's map bundle or GeoJSON could not be read from the local API.</span>
    </div>
  );
}

function HoverCard({ visuals, override }: { visuals: FieldVisualResult; override?: (fieldId: string) => ReactNode }) {
  const hovered = useUI((s) => s.hoveredFieldId);
  const hoveredEdge = useUI((s) => s.hoveredEdgeId);
  const areaUnit = useUI((s) => s.areaUnit);
  const { fieldIndex, map } = usePilotData();
  const [pt, setPt] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    const eng = getEngine();
    if (!eng) return;
    return eng.on((e) => {
      if ((e.type === "field-hover" && e.fieldId) || (e.type === "edge-hover" && e.edgeId)) setPt({ x: e.x, y: e.y });
    });
  }, []);
  const f = hovered ? fieldIndex.get(hovered) : null;
  const edge = !f && hoveredEdge ? map.data?.edges.find((e) => e.edge_id === hoveredEdge) : null;
  if ((!f && !edge) || !pt) return null;
  const v = f ? visuals.values.get(f.id) : null;
  return (
    <div
      className="pointer-events-none absolute z-30 min-w-[160px] -translate-x-1/2 rounded-[10px] border border-border bg-surface/95 px-3 py-2 shadow-3 backdrop-blur"
      style={{ left: pt.x, top: Math.max(8, pt.y - 86) }}
      aria-hidden
    >
      {f ? (
        <>
          <div className="text-[12px] font-semibold text-ink">{f.label}</div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-secondary">
            {f.group ? <span className="capitalize">{f.group}</span> : null}
            {f.areaM2 ? <span className="num">{formatArea(f.areaM2, areaUnit)}</span> : null}
          </div>
          {override ? (
            <div className="num mt-1 text-[13px] font-semibold text-ink">{override(f.id)}</div>
          ) : v ? (
            <div className="num mt-1 text-[13px] font-semibold text-ink">
              {typeof v.value === "number" ? formatWithUnit(v.value, v.unit) : v.status.replace(/_/g, " ")}
            </div>
          ) : null}
        </>
      ) : edge ? (
        <>
          <div className="text-[12px] font-semibold text-ink">{edge.reach_label ?? edge.edge_id}</div>
          <div className="mt-0.5 text-[11px] text-ink-secondary">
            {edge.geometry_ref ? "Observed canal geometry" : "Assumed connection (no observed geometry)"}
          </div>
          <div className="num mt-1 text-[12px] text-ink">Delivery factor {formatWithUnit(edge.delivery_factor, "fraction")}</div>
        </>
      ) : null}
    </div>
  );
}

function MapControls({ compact, metric, metricControlled }: { compact?: boolean; metric: MapMetric; metricControlled: boolean }) {
  const mode = useUI((s) => s.mapMode);
  const set = useUI((s) => s.set);
  const toggle = useUI((s) => s.toggle);
  const orbiting = useUI((s) => s.orbiting);
  const showImagery = useUI((s) => s.showImagery);
  const showRaw = useUI((s) => s.showRawFields);
  const showParcels = useUI((s) => s.showParcels);
  const showHd = useUI((s) => s.showHdImagery);
  const hd = useHdStatus();
  const showTerrain = useUI((s) => s.showTerrain);
  const reduced = useReducedMotion();
  const terrain = getEngine()?.terrainInfo();
  const { map, rawFC } = usePilotData();
  const rawCount = rawFC?.features.length ?? 0;
  return (
    <>
      {!compact && !metricControlled ? (
        <div className="absolute left-3 top-3 z-10 max-w-[calc(100%-72px)] overflow-x-auto rounded-[12px] shadow-2">
          <Segmented<MapMetric>
            label="Colour fields by"
            size="sm"
            value={metric}
            onChange={(v) => set({ mapMetric: v })}
            className="bg-surface/95 backdrop-blur"
            options={(["yield", "service", "change", "group"] as const).map((k) => ({ value: k, label: METRIC_DEFS[k].short, title: METRIC_DEFS[k].label }))}
          />
        </div>
      ) : null}
      <div className="absolute right-3 top-3 z-10 flex flex-col gap-1.5">
        <div className="flex flex-col overflow-hidden rounded-[12px] border border-border bg-surface/95 shadow-2 backdrop-blur">
          <IconButton label="Zoom in" size="sm" onClick={() => getEngine()?.zoomBy(0.8)}>
            <Plus size={16} />
          </IconButton>
          <IconButton label="Zoom out" size="sm" onClick={() => getEngine()?.zoomBy(-0.8)}>
            <Minus size={16} />
          </IconButton>
          <IconButton label="Reset bearing to north" size="sm" onClick={() => getEngine()?.resetNorth()}>
            <Compass size={16} />
          </IconButton>
          <IconButton label="Fit pilot area" size="sm" onClick={() => getEngine()?.fitAOI(true)}>
            <Maximize2 size={15} />
          </IconButton>
        </div>
        <div className="flex flex-col overflow-hidden rounded-[12px] border border-border bg-surface/95 shadow-2 backdrop-blur">
          <IconButton
            label={mode === "3d" ? "Switch to flat 2D map" : "Switch to 3D map"}
            size="sm"
            pressed={mode === "3d" && !reduced}
            disabled={reduced}
            title={reduced ? "Reduced motion: 2D map" : undefined}
            onClick={() => set({ mapMode: mode === "3d" ? "2d" : "3d" })}
          >
            {mode === "3d" && !reduced ? <Box size={16} /> : <Square size={15} />}
          </IconButton>
          {!compact ? (
            <IconButton label={orbiting ? "Stop orbit" : "Orbit camera"} size="sm" pressed={orbiting} disabled={reduced || mode !== "3d"} onClick={() => toggle("orbiting")}>
              <Orbit size={16} />
            </IconButton>
          ) : null}
          <Popover>
            <PopoverTrigger asChild>
              <IconButton label="Map layers" size="sm">
                <Layers size={16} />
              </IconButton>
            </PopoverTrigger>
            <PopoverContent side="left" align="start" className="w-[280px]">
              <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Layers</div>
              <div className="flex flex-col gap-3">
                <Switch
                  label="Sentinel-2 imagery"
                  description={map.data?.imagery[0]?.acquiredAt ? `Scene ${map.data.imagery[0].sceneId.slice(0, 32)}` : "No imagery in package"}
                  checked={showImagery}
                  onChange={(v) => set({ showImagery: v })}
                  disabled={!map.data?.imagery.length}
                />
                <Switch
                  label="High-res imagery (Esri)"
                  description={
                    hd === "ok"
                      ? "Sub-metre display basemap, online only; analysis stays on Sentinel-2"
                      : hd === "rejected"
                        ? "Esri key rejected; showing Sentinel-2"
                        : "Add VITE_ARCGIS_KEY to .env to enable"
                  }
                  checked={hd === "ok" && showHd}
                  onChange={(v) => set({ showHdImagery: v })}
                  disabled={hd !== "ok" || !showImagery}
                />
                <Switch
                  label="All delineated parcels"
                  description={`Every AI-delineated parcel as quiet outlines${rawCount ? ` (${rawCount})` : ""}; modeled fields stand up in 3D`}
                  checked={showParcels}
                  onChange={(v) => set({ showParcels: v })}
                  disabled={!map.data?.fieldsRaw}
                />
                <Switch
                  label="Raw AI boundaries"
                  description="Untouched Delineate output (review overlay)"
                  checked={showRaw}
                  onChange={(v) => set({ showRawFields: v })}
                  disabled={!map.data?.fieldsRaw}
                />
                <Switch
                  label={
                    <span className="inline-flex items-center gap-1">
                      <Mountain size={13} aria-hidden /> Terrain relief
                    </span>
                  }
                  description={
                    map.data?.terrain
                      ? terrain?.available
                        ? `Local DEM, vertical ×${terrain.exaggeration}`
                        : "Local DEM loading"
                      : "No DEM in this package — flat"
                  }
                  checked={showTerrain}
                  onChange={(v) => set({ showTerrain: v })}
                  disabled={!map.data?.terrain || mode !== "3d" || reduced}
                />
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </>
  );
}
