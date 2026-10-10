/**
 * Binds pilot data, URL selection and display preferences to the persistent engine.
 * Mounted once per pilot layout; screens only provide <MapSlot>s.
 */
import { useEffect, useRef } from "react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useReducedMotion, useResolvedTheme } from "@/app/environment";
import { useField } from "@/lib/api/queries";
import { ensureEngine, useMapRuntime } from "./runtime";

export function MapBinder() {
  const { sel, map, fieldsFC, canalsFC, aoiFC, rawFC } = usePilotData();
  const mode = useUI((s) => s.mapMode);
  const reduced = useReducedMotion();
  const theme = useResolvedTheme();
  const showImagery = useUI((s) => s.showImagery);
  const showRaw = useUI((s) => s.showRawFields);
  const showTerrain = useUI((s) => s.showTerrain);
  const orbiting = useUI((s) => s.orbiting);
  const ready = useMapRuntime((s) => s.ready);
  const engine = ensureEngine({ mode, reducedMotion: reduced });
  const selRef = useRef(sel);
  selRef.current = sel;

  // Data
  useEffect(() => {
    if (!map.data || !fieldsFC) return;
    void engine.setData({ bundle: map.data, fields: fieldsFC, canals: canalsFC, aoi: aoiFC, raw: rawFC }).then(() => {
      engine.setSelected(selRef.current.fieldId, { fly: false });
    });
  }, [engine, map.data, fieldsFC, canalsFC, aoiFC, rawFC]);

  // Selection from URL
  useEffect(() => {
    if (!ready) return;
    engine.setSelected(sel.fieldId);
  }, [engine, ready, sel.fieldId, fieldsFC]);

  // Route of the selected field (server-declared edge ids)
  const field = useField(sel.version, sel.fieldId);
  useEffect(() => {
    const ids = (field.data?.raw?.route_edge_ids as string[] | undefined) ?? [];
    engine.setRoute(sel.fieldId ? ids : []);
  }, [engine, field.data, sel.fieldId]);

  // Interaction → URL
  useEffect(
    () =>
      engine.on((e) => {
        if (e.type === "field-click") selRef.current.setParams({ field: e.fieldId }, false);
        if (e.type === "edge-click") useUI.getState().set({ selectedEdgeId: e.edgeId, inspectorTab: "field", inspectorOpen: true });
        if (e.type === "field-hover") {
          if (useUI.getState().hoveredFieldId !== e.fieldId) useUI.getState().set({ hoveredFieldId: e.fieldId });
        }
        if (e.type === "edge-hover") {
          if (useUI.getState().hoveredEdgeId !== e.edgeId) useUI.getState().set({ hoveredEdgeId: e.edgeId });
        }
      }),
    [engine],
  );

  useEffect(() => {
    if (ready) engine.setMode(mode, reduced);
  }, [engine, ready, mode, reduced]);
  useEffect(() => {
    if (ready) engine.refreshTheme();
  }, [engine, ready, theme]);
  useEffect(() => engine.setImageryVisible(showImagery), [engine, showImagery, ready]);
  useEffect(() => engine.setRawVisible(showRaw), [engine, showRaw, ready]);
  useEffect(() => engine.setTerrainEnabled(showTerrain), [engine, showTerrain, ready]);
  useEffect(() => {
    if (!ready) return;
    if (orbiting && !reduced) engine.startOrbit();
    else engine.stopOrbit();
    return () => engine.stopOrbit();
  }, [engine, ready, orbiting, reduced]);

  return null;
}
