/**
 * Scenario lifecycle on the client (PRD §4.3, T10.2):
 * draft (Zustand) → immutable revision (API) → solve jobs (API) → runs (API, by ID).
 * The client never decides analytical outcomes; it only tracks which IDs belong to the
 * active revision so a late result never overwrites a newer draft.
 */
import { useCallback, useEffect, useMemo } from "react";
import { useSelection } from "@/app/selection";
import {
  draftChanges,
  draftsEqual,
  needsNewScenario,
  useUI,
  type ScenarioDraft,
} from "@/app/store";
import {
  useCreateScenario,
  useDeriveRevision,
  useInterventions,
  useSeasons,
  useSolve,
  useUncertaintySets,
  useWeatherScenarios,
} from "@/lib/api/queries";
import type { PlanKind, ScenarioRequest, Season } from "@/lib/api/types";
import { describeError } from "@/lib/api/client";
import { toast } from "@/components/ui/Toast";

export type ScenarioPhase = "loading" | "unavailable" | "draft" | "dirty" | "current" | "running";

export function defaultDecisionAt(season: Season): string {
  // Season's published decision date when present; otherwise pre-season planning at local
  // midnight on the season start date with an explicit +05:00 offset.
  if (season.decision_at) return season.decision_at.length <= 10 ? `${season.decision_at}T00:00:00+05:00` : season.decision_at;
  return `${season.start.slice(0, 10)}T00:00:00+05:00`;
}

export function useScenarioCatalog(pilotId?: string, seasonId?: string, decisionAt?: string | null) {
  const seasons = useSeasons(pilotId);
  const sid = seasonId ?? seasons.data?.[0]?.season_id;
  const weather = useWeatherScenarios(pilotId, sid);
  const uncertainty = useUncertaintySets(pilotId, sid);
  const interventions = useInterventions(pilotId, sid, decisionAt);
  return { seasons, weather, uncertainty, interventions, seasonId: sid };
}

export function useScenario() {
  const sel = useSelection();
  const key = sel.pilotKey;
  const draft = useUI((s) => s.drafts[key]);
  const active = useUI((s) => s.active[key]);
  const jobs = useUI((s) => s.jobs);
  const runsByRevision = useUI((s) => s.runsByRevision);
  const setDraft = useUI((s) => s.setDraft);
  const patchDraft = useUI((s) => s.patchDraft);
  const setActive = useUI((s) => s.setActive);
  const trackJob = useUI((s) => s.trackJob);
  const catalog = useScenarioCatalog(sel.pilotId, draft?.season_id, draft?.decision_at);

  // Initialise a draft from the published catalog (only inputs the user can see and edit).
  useEffect(() => {
    if (draft || !catalog.seasons.data?.length) return;
    const season = catalog.seasons.data[0];
    const w = catalog.weather.data ?? [];
    if (catalog.weather.isLoading || catalog.uncertainty.isLoading) return;
    const typical = w.find((x) => x.is_typical) ?? w[0];
    const supply = catalog.uncertainty.data?.supplyProfiles?.[0]?.supply_profile_id ?? catalog.uncertainty.data?.sets?.[0]?.states?.[0]?.supply_profile_id ?? "nominal";
    const sAny = season as unknown as Record<string, unknown>;
    setDraft(key, {
      season_id: season.season_id,
      planning_mode: (season.planning_modes?.[0] as ScenarioDraft["planning_mode"]) ?? "season_response",
      decision_at: defaultDecisionAt(season),
      weather_scenario_ids: typical ? [typical.weather_scenario_id] : [],
      supply_profile_id: supply,
      uniform_reduction_fraction: typeof sAny.default_uniform_reduction_fraction === "number" ? (sAny.default_uniform_reduction_fraction as number) : 0,
      capital_budget_pkr: typeof sAny.default_capital_budget_pkr === "number" ? (sAny.default_capital_budget_pkr as number) : 1_500_000,
      operating_budget_pkr: typeof sAny.default_operating_budget_pkr === "number" ? (sAny.default_operating_budget_pkr as number) : 250_000,
      objective: "production_kg",
      optimization_mode: "typical",
      uncertainty_set_id: catalog.uncertainty.data?.sets?.[0]?.uncertainty_set_id ?? null,
      minimum_service_ratio: null,
      service_group: null,
      permit_groundwater: true,
      forced_instance_ids: [],
      excluded_instance_ids: [],
    });
  }, [draft, catalog.seasons.data, catalog.weather.data, catalog.weather.isLoading, catalog.uncertainty.data, catalog.uncertainty.isLoading, key, setDraft]);

  const createScenario = useCreateScenario();
  const deriveRevision = useDeriveRevision();
  const solve = useSolve();

  const activeJobs = useMemo(
    () => jobs.filter((j) => j.pilotKey === key && j.revisionId && j.revisionId === active?.revisionId && !["succeeded", "failed", "cancelled", "interrupted"].includes(j.state)),
    [jobs, key, active?.revisionId],
  );
  const dirty = !!draft && !!active && !draftsEqual(draft, active.basis);
  const phase: ScenarioPhase = !catalog.seasons.data
    ? catalog.seasons.error
      ? "unavailable"
      : "loading"
    : !draft
      ? catalog.seasons.data.length
        ? "loading"
        : "unavailable"
      : activeJobs.length
        ? "running"
        : !active
          ? "draft"
          : dirty
            ? "dirty"
            : "current";

  const revisionRuns = active ? runsByRevision[active.revisionId] ?? {} : {};

  const toRequest = useCallback(
    (d: ScenarioDraft): ScenarioRequest => ({
      contract_version: "2.0.0",
      pilot_id: sel.pilotId!,
      pilot_version: sel.version!,
      season_id: d.season_id,
      planning_mode: d.planning_mode,
      decision_at: d.decision_at,
      weather_scenario_ids: d.weather_scenario_ids,
      supply_profile_id: d.supply_profile_id,
      uniform_reduction_fraction: d.uniform_reduction_fraction,
      capital_budget_pkr: Math.floor(d.capital_budget_pkr),
      operating_budget_pkr: Math.floor(d.operating_budget_pkr),
      objective: d.objective,
      optimization_mode: d.optimization_mode,
      uncertainty_set_id: d.optimization_mode === "worst_case" ? d.uncertainty_set_id : d.uncertainty_set_id ?? null,
      minimum_service_ratio: d.minimum_service_ratio,
      service_group: d.minimum_service_ratio === null ? null : d.service_group ?? "all",
      permit_groundwater: d.permit_groundwater,
      blocked_edge_ids: [],
      allowed_intervention_instance_ids: null,
      forced_instance_ids: d.forced_instance_ids,
      excluded_instance_ids: d.excluded_instance_ids,
      assumption_set_id: "declared-assumptions-v1",
    }),
    [sel.pilotId, sel.version],
  );

  /** Ensure an immutable revision exists for the current draft; returns its id. */
  const ensureRevision = useCallback(async (): Promise<string | null> => {
    if (!draft) return null;
    if (active && draftsEqual(draft, active.basis)) return active.revisionId;
    try {
      if (!active || needsNewScenario(active.basis, draft)) {
        const created = await createScenario.mutateAsync(toRequest(draft));
        setActive(key, { scenarioId: created.scenario_id, revisionId: created.revision.scenario_revision_id, basis: { ...draft } });
        return created.revision.scenario_revision_id;
      }
      const rev = await deriveRevision.mutateAsync({
        scenarioId: active.scenarioId,
        parentRevisionId: active.revisionId,
        changes: draftChanges(active.basis, draft),
      });
      setActive(key, { scenarioId: active.scenarioId, revisionId: rev.scenario_revision_id, basis: { ...draft } });
      return rev.scenario_revision_id;
    } catch (e) {
      const d = describeError(e);
      toast({ tone: "danger", title: d.title, description: d.detail });
      return null;
    }
  }, [draft, active, createScenario, deriveRevision, toRequest, setActive, key]);

  const run = useCallback(
    async (kinds: PlanKind[] = ["B0", "B1", "P"]) => {
      const revId = await ensureRevision();
      if (!revId) return;
      const existing = useUI.getState().runsByRevision[revId] ?? {};
      for (const kind of kinds) {
        if (existing[kind]) continue; // immutable result already exists for this exact revision
        try {
          const r = await solve.mutateAsync({ revisionId: revId, planKind: kind });
          if (!r.jobId) throw new Error("The API did not return a job id.");
          trackJob({
            jobId: r.jobId,
            label: `${PLAN_LABEL[kind]} solve`,
            operation: "solve",
            revisionId: revId,
            planKind: kind,
            pilotKey: key,
          });
        } catch (e) {
          const d = describeError(e);
          toast({ tone: "danger", title: `${PLAN_LABEL[kind]}: ${d.title}`, description: d.detail });
        }
      }
      const runs = useUI.getState().runsByRevision[revId] ?? {};
      if (runs.P) sel.setParams({ run: runs.P, runs: [runs.B0, runs.B1, runs.P].filter(Boolean).join(",") });
    },
    [ensureRevision, solve, trackJob, key, sel],
  );

  return {
    key,
    draft,
    active,
    phase,
    dirty,
    catalog,
    revisionRuns,
    activeJobs,
    patch: (p: Partial<ScenarioDraft>) => patchDraft(key, p),
    reset: () => active && setDraft(key, { ...active.basis }),
    run,
    busy: createScenario.isPending || deriveRevision.isPending || solve.isPending,
  };
}

export const PLAN_LABEL: Record<PlanKind, string> = {
  B0: "Fixed-roster baseline",
  B1: "No new capital",
  P: "Integrated plan",
  R: "Robust plan",
};
export const PLAN_SHORT: Record<PlanKind, string> = { B0: "B0", B1: "B1", P: "P", R: "R" };
