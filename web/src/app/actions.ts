/**
 * App actions: the small, stable verbs other parts of the UI (the assistant slot, the
 * guided tour, command menu) use to move the app. Everything here changes navigation or
 * UI state only; no action computes or caches an analytical number.
 * Documented in docs/UI_SYSTEM.md › Assistant slot.
 */
import { useMemo } from "react";
import { useSelection, type Screen } from "./selection";
import { useUI } from "./store";
import { getEngine } from "@/components/map/runtime";

export interface AppActions {
  /** Go to one of the screens, optionally with URL selections (run, field, date, runs, analysis, tab, ev). */
  openScreen: (screen: Screen, params?: Partial<Record<string, string | null>>) => void;
  /** Show a stored run (any screen, default: stay on the current one). */
  openRun: (runId: string, screen?: Screen) => void;
  /** Open a stored analysis (frontier, stress, why-not, synergy, sensitivity) in "What if". */
  openAnalysis: (analysisId: string, tab?: string) => void;
  /** Select a field everywhere (map flies to it, inspector opens it). */
  selectField: (fieldId: string | null) => void;
  /** Move the shared timeline cursor (YYYY-MM-DD). */
  setDate: (isoDate: string | null) => void;
  /** Ask the map to emphasise fields (assistant answers, tour). `null` clears it. */
  highlightFields: (fieldIds: string[] | null) => void;
  /** Frame the whole pilot on the map. */
  overview: () => void;
  openAssistant: () => void;
  closeAssistant: () => void;
}

export function useAppActions(): AppActions {
  const sel = useSelection();
  const set = useUI((s) => s.set);
  return useMemo<AppActions>(
    () => ({
      openScreen: (screen, params) => sel.go(screen, params),
      openRun: (runId, screen) => (screen ? sel.go(screen, { run: runId }) : sel.setParams({ run: runId }, false)),
      openAnalysis: (analysisId, tab) => sel.go("explore", { analysis: analysisId, ...(tab ? { tab } : {}) }),
      selectField: (fieldId) => sel.setParams({ field: fieldId }, false),
      setDate: (isoDate) => sel.setParams({ date: isoDate }, false),
      highlightFields: (ids) => set({ assistantHighlight: ids && ids.length ? ids : null }),
      overview: () => getEngine()?.fitAOI(true),
      openAssistant: () => set({ assistantOpen: true }),
      closeAssistant: () => set({ assistantOpen: false }),
    }),
    [sel, set],
  );
}
