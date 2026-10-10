/**
 * UI-only state (T10.2): panel visibility, hover, camera, display preferences, job tray
 * and the scenario draft. Analytical truth never lives here — only IDs pointing at it.
 * Stable selections (pilot/run/field/date) live in the URL; see `useSelection`.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { JobState, ScenarioRequest } from "@/lib/api/types";

export type ThemePref = "system" | "light" | "dark";
export type MapMetric = "yield" | "service" | "change" | "group" | "none";
export type InspectorTab = "field" | "actions" | "evidence" | "copilot";

export interface TrackedJob {
  jobId: string;
  label: string;
  operation: string;
  /** Revision the job was launched for; results only bind to the matching active revision. */
  revisionId: string | null;
  planKind?: string;
  analysisKind?: string;
  pilotKey: string;
  startedAt: number;
  state: JobState;
  stage: string | null;
  progress: number | null;
  resultRef: string | null;
  error: string | null;
  lastUpdate: number;
  dismissed?: boolean;
}

/** Draft inputs edited in the Scenario panel before a revision exists. */
export type ScenarioDraft = Pick<
  ScenarioRequest,
  | "season_id"
  | "planning_mode"
  | "decision_at"
  | "weather_scenario_ids"
  | "supply_profile_id"
  | "uniform_reduction_fraction"
  | "capital_budget_pkr"
  | "operating_budget_pkr"
  | "objective"
  | "optimization_mode"
  | "uncertainty_set_id"
  | "minimum_service_ratio"
  | "service_group"
  | "permit_groundwater"
  | "forced_instance_ids"
  | "excluded_instance_ids"
>;

export interface ActiveScenario {
  scenarioId: string;
  revisionId: string;
  /** Draft snapshot the active revision was created from (for dirty detection). */
  basis: ScenarioDraft;
}

interface UIState {
  theme: ThemePref;
  presentation: boolean;
  motion: "system" | "reduced" | "full";
  mapMode: "3d" | "2d";
  mapMetric: MapMetric;
  showImagery: boolean;
  showRawFields: boolean;
  showTerrain: boolean;
  areaUnit: "ha" | "acre";
  scenarioOpen: boolean;
  inspectorOpen: boolean;
  inspectorTab: InspectorTab;
  commandOpen: boolean;
  hoveredFieldId: string | null;
  hoveredEdgeId: string | null;
  selectedEdgeId: string | null;
  orbiting: boolean;
  jobs: TrackedJob[];
  /** per pilot key `${pilot}@${version}` */
  drafts: Record<string, ScenarioDraft>;
  active: Record<string, ActiveScenario>;
  /** Runs produced per revision and plan kind (IDs only; immutable results live in the API). */
  runsByRevision: Record<string, Partial<Record<"B0" | "B1" | "P" | "R", string>>>;
  recordRun: (revisionId: string, planKind: string, runId: string) => void;
  set: (p: Partial<UIState>) => void;
  toggle: (k: "presentation" | "scenarioOpen" | "inspectorOpen" | "showImagery" | "showRawFields" | "showTerrain" | "orbiting" | "commandOpen") => void;
  setDraft: (pilotKey: string, d: ScenarioDraft) => void;
  patchDraft: (pilotKey: string, d: Partial<ScenarioDraft>) => void;
  setActive: (pilotKey: string, a: ActiveScenario | null) => void;
  trackJob: (j: Omit<TrackedJob, "state" | "stage" | "progress" | "resultRef" | "error" | "lastUpdate" | "startedAt">) => void;
  updateJob: (jobId: string, p: Partial<TrackedJob>) => void;
  dismissJob: (jobId: string) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: "system",
      presentation: false,
      motion: "system",
      mapMode: "3d",
      mapMetric: "yield",
      showImagery: true,
      showRawFields: false,
      showTerrain: true,
      areaUnit: "ha",
      scenarioOpen: true,
      inspectorOpen: true,
      inspectorTab: "field",
      commandOpen: false,
      hoveredFieldId: null,
      hoveredEdgeId: null,
      selectedEdgeId: null,
      orbiting: false,
      jobs: [],
      drafts: {},
      active: {},
      runsByRevision: {},
      recordRun: (revisionId, planKind, runId) =>
        set((s) => ({
          runsByRevision: { ...s.runsByRevision, [revisionId]: { ...(s.runsByRevision[revisionId] ?? {}), [planKind]: runId } },
        })),
      set: (p) => set(p),
      toggle: (k) => set((s) => ({ [k]: !s[k] }) as Partial<UIState>),
      setDraft: (pilotKey, d) => set((s) => ({ drafts: { ...s.drafts, [pilotKey]: d } })),
      patchDraft: (pilotKey, d) =>
        set((s) => (s.drafts[pilotKey] ? { drafts: { ...s.drafts, [pilotKey]: { ...s.drafts[pilotKey], ...d } } } : {})),
      setActive: (pilotKey, a) =>
        set((s) => {
          const next = { ...s.active };
          if (a) next[pilotKey] = a;
          else delete next[pilotKey];
          return { active: next };
        }),
      trackJob: (j) =>
        set((s) => ({
          jobs: [
            { ...j, startedAt: Date.now(), lastUpdate: Date.now(), state: "queued" as JobState, stage: null, progress: null, resultRef: null, error: null },
            ...s.jobs.filter((x) => x.jobId !== j.jobId),
          ].slice(0, 20),
        })),
      updateJob: (jobId, p) =>
        set((s) => ({ jobs: s.jobs.map((j) => (j.jobId === jobId ? { ...j, ...p, lastUpdate: Date.now() } : j)) })),
      dismissJob: (jobId) => set((s) => ({ jobs: s.jobs.map((j) => (j.jobId === jobId ? { ...j, dismissed: true } : j)) })),
    }),
    {
      name: "aabflow-ui",
      version: 1,
      partialize: (s) => ({
        theme: s.theme,
        motion: s.motion,
        mapMode: s.mapMode,
        mapMetric: s.mapMetric,
        showImagery: s.showImagery,
        showTerrain: s.showTerrain,
        areaUnit: s.areaUnit,
        scenarioOpen: s.scenarioOpen,
        drafts: s.drafts,
        active: s.active,
        runsByRevision: s.runsByRevision,
        jobs: s.jobs.filter((j) => !j.dismissed).slice(0, 10),
      }),
    },
  ),
);

export const TERMINAL_JOB_STATES: JobState[] = ["succeeded", "failed", "cancelled", "interrupted"];
export const isTerminal = (s: JobState) => TERMINAL_JOB_STATES.includes(s);

/** Shallow, order-insensitive draft equality used to detect "Inputs changed — run again". */
export function draftsEqual(a: ScenarioDraft | undefined, b: ScenarioDraft | undefined): boolean {
  if (!a || !b) return a === b;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof ScenarioDraft>;
  for (const k of keys) {
    const x = a[k];
    const y = b[k];
    if (Array.isArray(x) || Array.isArray(y)) {
      const xs = [...((x as string[]) ?? [])].sort().join("|");
      const ys = [...((y as string[]) ?? [])].sort().join("|");
      if (xs !== ys) return false;
    } else if ((x ?? null) !== (y ?? null)) return false;
  }
  return true;
}

/** The typed change set between a revision's basis and the current draft. */
export function draftChanges(basis: ScenarioDraft, draft: ScenarioDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const keys: (keyof ScenarioDraft)[] = [
    "capital_budget_pkr",
    "operating_budget_pkr",
    "supply_profile_id",
    "uniform_reduction_fraction",
    "weather_scenario_ids",
    "minimum_service_ratio",
    "service_group",
    "permit_groundwater",
    "forced_instance_ids",
    "excluded_instance_ids",
    "optimization_mode",
    "uncertainty_set_id",
  ];
  for (const k of keys) {
    const single: Partial<ScenarioDraft> = { [k]: basis[k] } as Partial<ScenarioDraft>;
    const other: Partial<ScenarioDraft> = { [k]: draft[k] } as Partial<ScenarioDraft>;
    if (!draftsEqual(single as ScenarioDraft, other as ScenarioDraft)) out[k] = draft[k];
  }
  return out;
}

/** Fields that cannot be changed through a derived revision; a new scenario is needed. */
export function needsNewScenario(basis: ScenarioDraft, draft: ScenarioDraft): boolean {
  return (
    basis.season_id !== draft.season_id ||
    basis.planning_mode !== draft.planning_mode ||
    basis.decision_at !== draft.decision_at ||
    basis.objective !== draft.objective
  );
}
