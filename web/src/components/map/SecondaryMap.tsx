/**
 * Second synchronized map for paired comparison (T10.3). Shares selection through the URL
 * and camera through a re-entrancy-guarded sync with the persistent map.
 */
import { useEffect, useRef, useState } from "react";
import { usePilotData } from "@/app/pilotData";
import { useUI, type MapMetric } from "@/app/store";
import { useReducedMotion, useResolvedTheme } from "@/app/environment";
import { MapEngine } from "./engine";
import { getEngine, useMapRuntime } from "./runtime";
import { useFieldVisuals } from "./useFieldVisuals";
import { cn } from "@/lib/cn";

export function SecondaryMap({
  runId,
  baselineRunId,
  metric,
  sharedDomain,
  className,
  label,
  style,
}: {
  runId: string | null;
  baselineRunId?: string | null;
  metric: MapMetric;
  sharedDomain?: [number, number] | null;
  className?: string;
  label: string;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [engine, setEngine] = useState<MapEngine | null>(null);
  const [ready, setReady] = useState(false);
  const primaryReady = useMapRuntime((s) => s.ready);
  const { sel, map, fieldsFC, canalsFC, aoiFC, rawFC, fieldIndex } = usePilotData();
  const mode = useUI((s) => s.mapMode);
  const showImagery = useUI((s) => s.showImagery);
  const reduced = useReducedMotion();
  const theme = useResolvedTheme();
  const visuals = useFieldVisuals({ runId, baselineRunId, metric, fields: fieldIndex, sharedDomain });
  const selRef = useRef(sel);
  selRef.current = sel;

  useEffect(() => {
    if (!ref.current) return;
    const e = new MapEngine(ref.current, { mode, reducedMotion: reduced, secondary: true });
    setEngine(e);
    (window as unknown as { __aabMap2?: MapEngine }).__aabMap2 = e;
    e.whenReady().then(() => setReady(true));
    const ro = new ResizeObserver(() => e.resize());
    ro.observe(ref.current);
    const off = e.on((ev) => {
      if (ev.type === "field-click") selRef.current.setParams({ field: ev.fieldId }, false);
    });
    return () => {
      off();
      ro.disconnect();
      e.destroy();
      setEngine(null);
      setReady(false);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!engine || !map.data || !fieldsFC) return;
    void engine.setData({ bundle: map.data, fields: fieldsFC, canals: canalsFC, aoi: aoiFC, raw: rawFC }).then(() => {
      const p = getEngine();
      if (p) engine.syncFrom(p);
    });
  }, [engine, map.data, fieldsFC, canalsFC, aoiFC, rawFC]);

  // Two-way camera sync with guard
  useEffect(() => {
    const p = getEngine();
    if (!engine || !ready || !p || !primaryReady) return;
    engine.syncFrom(p);
    let lock = false;
    const offA = p.on((ev) => {
      if (ev.type !== "camera" || lock) return;
      lock = true;
      engine.syncFrom(p);
      lock = false;
    });
    const offB = engine.on((ev) => {
      if (ev.type !== "camera" || lock) return;
      lock = true;
      p.syncFrom(engine);
      lock = false;
    });
    return () => {
      offA();
      offB();
    };
  }, [engine, ready, primaryReady]);

  useEffect(() => {
    if (engine && ready) engine.setFieldVisuals(visuals.visuals);
  }, [engine, ready, visuals.visuals]);
  useEffect(() => {
    if (engine && ready) engine.setSelected(sel.fieldId, { fly: false });
  }, [engine, ready, sel.fieldId, fieldsFC]);
  useEffect(() => {
    if (engine && ready) engine.setMode(mode, reduced);
  }, [engine, ready, mode, reduced]);
  useEffect(() => {
    if (engine && ready) engine.refreshTheme();
  }, [engine, ready, theme]);
  useEffect(() => {
    if (engine && ready) engine.setImageryVisible(showImagery);
  }, [engine, ready, showImagery]);

  // MapLibre sets `position: relative` on its container, so the engine gets an inner
  // full-size element and the absolute positioning stays on the wrapper.
  return (
    <div className={cn("absolute inset-0", className)} style={style} role="region" aria-label={label} data-testid="secondary-map">
      <div ref={ref} className="h-full w-full" />
    </div>
  );
}
