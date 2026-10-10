/**
 * Explore data layer (T9.1, T7.1–T7.4, T8.4): typed request bodies that mirror the server's
 * pydantic models exactly, typed result shapes from `services/analyses/jobs.py`, and hooks
 * that start an analysis, poll it until its job is terminal, and resolve which scenario
 * revision / run the screen is about (from the URL first, so deep links work).
 *
 * Nothing here computes an outcome: every number shown in Explore comes from these payloads.
 */
import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSelection } from "@/app/selection";
import { useUI } from "@/app/store";
import { api, ApiError, describeError, qs } from "@/lib/api/client";
import { qk, useRevision, useRun } from "@/lib/api/queries";
import type { Job, MetricValue } from "@/lib/api/types";
import { toast } from "@/components/ui/Toast";

/* ================================================================ kinds */

/** URL / tab spelling of an analysis kind. */
export type AnalysisKind = "frontier" | "stress" | "why-not" | "sensitivity" | "synergy";
/** Server `analyses.kind` spelling. */
export type ServerKind = "frontier" | "stress" | "why_not" | "sensitivity" | "synergy";

export const toServerKind = (k: AnalysisKind): ServerKind => (k === "why-not" ? "why_not" : k);
export const fromServerKind = (k: string): AnalysisKind | null =>
  k === "why_not" ? "why-not" : (["frontier", "stress", "sensitivity", "synergy"] as string[]).includes(k) ? (k as AnalysisKind) : null;

export const KIND_LABEL: Record<AnalysisKind, string> = {
  frontier: "Resilience frontier",
  stress: "Stress matrix",
  "why-not": "Why-not solve",
  synergy: "Synergy (4 matched runs)",
  sensitivity: "Sensitivity sweep",
};

/* ================================================================ request bodies (pydantic mirrors) */

export type ServiceGroup = "all" | "head" | "middle" | "tail";

/** `FrontierSetting`: a floor without a group defaults to "all" server-side. */
export interface FrontierSetting {
  capital_budget_pkr: number;
  minimum_service_ratio?: number | null;
  service_group?: ServiceGroup | null;
}
/** `FrontierRequest`: 6–24 distinct settings. */
export interface FrontierRequest {
  contract_version: "2.0.0";
  base_revision_id: string;
  settings: FrontierSetting[];
  plan_kind?: "P" | "R";
  time_limit_per_point_s?: number; // (0, 60]
  total_budget_s?: number; // (0, 900]
}
export const FRONTIER_MIN = 6;
export const FRONTIER_MAX = 24;

/** `StressRequest`. `state_ids` null → the revision's uncertainty set (≤ 9 states). */
export interface StressRequest {
  contract_version: "2.0.0";
  run_id: string;
  mode?: "fixed_plan" | "recovery_plan";
  state_ids?: string[] | null;
  uncertainty_set_id?: string | null;
  reference_run_id?: string | null;
  time_limit_per_cell_s?: number; // (0, 60]
}

/** `WhyNotRequest`. */
export interface WhyNotRequest {
  contract_version: "2.0.0";
  base_revision_id: string;
  instance_id: string;
  action?: "force" | "exclude";
  base_run_id?: string | null;
  time_limit_s?: number;
}

export type SensitivityParameter = "capital_budget_pkr" | "operating_budget_pkr" | "uniform_reduction_fraction" | "minimum_service_ratio";
/** `SensitivityRequest`: 2–12 distinct non-negative values; fractions in [0, 1] (reduction < 1). */
export interface SensitivityRequest {
  contract_version: "2.0.0";
  base_revision_id: string;
  parameter: SensitivityParameter;
  values: number[];
  service_group?: ServiceGroup | null;
  time_limit_per_point_s?: number;
}

/** `SynergyRequest`. */
export interface SynergyRequest {
  contract_version: "2.0.0";
  base_revision_id: string;
  instance_a: string;
  instance_b: string;
  other_actions?: "fixed" | "reoptimize";
  base_run_id?: string | null;
  time_limit_per_arm_s?: number;
}

export interface RequestByKind {
  frontier: FrontierRequest;
  stress: StressRequest;
  "why-not": WhyNotRequest;
  sensitivity: SensitivityRequest;
  synergy: SynergyRequest;
}

/* ================================================================ result shapes */

/** `point()` summary of one child run (outcome plan / no_plan / other). */
export interface ChildPoint {
  run_id?: string;
  outcome?: "plan" | "no_plan" | "not_run" | "rejected" | string;
  solver_status?: string | null;
  plan_kind?: string;
  scenario_revision_id?: string;
  warnings?: string[];
  objective_value?: number | null;
  objective_upper_bound?: number | null;
  relative_gap?: number | null;
  production_kg?: number | null;
  capital_commitment_pkr?: number | null;
  operating_cost_pkr?: number | null;
  pumping_cost_pkr?: number | null;
  groundwater_m3?: number | null;
  canal_source_withdrawal_m3?: number | null;
  min_service_ratio?: number | null;
  tail_min_service_ratio?: number | null;
  worst_tested_production_kg?: number | null;
  quantization_bound?: number | null;
  selected_intervention_instance_ids?: string[];
  shared_configuration_id?: string | null;
  physical_validation?: string | null;
  infeasibility_kind?: string | null;
  diagnostics?: { configurations?: { shared_configuration_id?: string; reason?: string }[] } & Record<string, unknown>;
  reason?: string | null;
  fields?: Record<string, unknown>;
}

export type Dominance = "nondominated" | "dominated" | "dominance_unresolved" | "not_applicable";
export interface FrontierPoint extends ChildPoint {
  point_id: string;
  setting: FrontierSetting;
  dominance?: Dominance;
  dominated_by?: string[];
  portfolio_key?: string | null;
  same_portfolio_as?: string[];
}
export interface FrontierResult {
  kind: "frontier";
  status: string;
  base_revision_id?: string;
  objective?: string;
  axes?: { x: { metric_id: string; unit: string }; y: { metric_id: string; unit: string }; channel: { metric_id: string; unit: string } };
  points: FrontierPoint[];
  label?: string;
  note?: string;
  distinct_portfolios?: number;
  counts?: Record<"evaluated" | "feasible" | "nondominated" | "dominated" | "dominance_unresolved" | "infeasible" | "unknown_or_other", number>;
  proof_status?: "all_points_optimal" | "some_points_unproven";
  wall_ms?: number;
}

export interface StressViolation {
  rule: string;
  detail?: string;
  field_id?: string;
  candidate_policy_id?: string;
  resource_id?: string;
  interval_id?: string;
  period?: [string, string] | null;
  used_m3?: number;
  capacity_m3?: number;
  violations?: string[];
}
export interface StressCell {
  state_id: string;
  weather_scenario_id: string;
  supply_profile_id: string;
  supply_label?: string;
  run_id?: string;
  solver_status?: string | null;
  deliverable: boolean;
  production_kg: number | null;
  objective_upper_bound?: number | null;
  violations?: StressViolation[];
  selected_intervention_instance_ids?: string[] | null;
  unused_fixed_investments?: string[] | null;
}
export interface StressResult {
  kind: "stress";
  status: string;
  run_id?: string;
  mode?: "fixed_plan" | "recovery_plan";
  source_plan_kind?: string;
  source_states?: string[];
  typical_state?: string | null;
  cells: StressCell[];
  label?: string;
  note?: string;
  worst_case_scope?: string;
  metrics_by_id?: Record<string, MetricValue>;
  recovery_metrics?: Record<string, MetricValue>;
  summary?: {
    tested: number;
    deliverable: number;
    undeliverable_state_ids: string[];
    worst_tested_production_kg: number | null;
    conditional_min_over_deliverable_kg: number | null;
    conditional_label: string | null;
    best_tested_production_kg: number | null;
    typical_production_kg: number | null;
  };
  matrix?: { rows: string[]; columns: string[]; cells: (string | null)[][] };
  foregone_typical_output?: {
    reference_run_id: string;
    typical_state: string | null;
    reference_typical_production_kg: number | null;
    this_plan_typical_production_kg: number | null;
    foregone_kg: number | null;
    note: string;
  };
  wall_ms?: number;
}

/** `difference_interval` / no-change answer. */
export interface ObjectiveDifference {
  status: "exact" | "interval" | "not_comparable" | "no_change";
  lower: number | null;
  upper: number | null;
  point: number | null;
  reason?: string | null;
  definition?: string;
}
export interface InstanceFacts {
  instance_id: string;
  exists: boolean;
  category?: string;
  capex_pkr?: number;
  seasonal_opex_pkr?: number;
  commissioned_on?: string | null;
  eligibility_reasons?: string[];
  library_excluded_reason?: string | null;
  candidate_policies_or_configurations_using_it?: number;
  mutually_exclusive_with?: string[];
  capital_budget_pkr?: number;
  over_capital_budget?: boolean;
  prerequisites?: string[];
}
export interface MetricDelta {
  metric_id: string;
  definition_id?: string;
  field_id: string | null;
  unit: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  status: "available" | "not_comparable";
  causal: boolean;
}
export interface Certificate {
  compatible: boolean;
  label: string;
  shared?: { condition: string; value: unknown }[];
  differences?: { condition: string; values: unknown[]; kind: string; note: string }[];
}
export interface WhyNotResult {
  kind: "why_not";
  status: string;
  base_revision_id?: string;
  instance_id?: string;
  action?: "force" | "exclude";
  objective?: string;
  instance?: InstanceFacts;
  base?: ChildPoint;
  alternative?: (ChildPoint & { outcome?: string }) | null;
  alternative_revision_id?: string;
  difference?: ObjectiveDifference;
  explanation?: string[];
  certificate?: Certificate;
  deltas?: MetricDelta[];
}

export interface SensitivityStep {
  from_value: number;
  to_value: number;
  objective_difference: ObjectiveDifference;
  delta_available_m3?: number;
  marginal_value_per_m3?: { lower: number; upper: number; unit: string; label: string };
  marginal_value_per_pkr?: { lower: number; upper: number };
  decision_changes?: boolean;
  instances_added?: string[];
  instances_removed?: string[];
}
export interface SensitivityResult {
  kind: "sensitivity";
  status: string;
  base_revision_id?: string;
  parameter?: SensitivityParameter;
  base_value?: number | null;
  values?: number[];
  points: (ChildPoint & { value: number; portfolio_key?: string | null })[];
  steps?: SensitivityStep[];
  label?: string;
  nominal_roster_volume_m3?: number | null;
  objective_unit?: string;
  decision_stable?: boolean;
  resolving_measurement?: string | null;
  note?: string;
}

export type ArmKey = "none" | "a" | "b" | "ab";
export interface SynergyArm extends ChildPoint {
  arm: ArmKey;
  includes: string[];
  excludes: string[];
}
export interface SynergyValue {
  status: "exact" | "interval" | "not_available" | "not_matched";
  value: number | null;
  incumbent_value?: number | null;
  lower: number | null;
  upper: number | null;
  sign?: "positive" | "negative" | "zero" | null;
  reason?: string | null;
  explanations?: Record<string, string[]>;
}
export interface SynergyResult {
  kind: "synergy";
  status: string;
  base_revision_id?: string;
  instance_a?: string;
  instance_b?: string;
  other_actions?: "fixed" | "reoptimize";
  arms: Partial<Record<ArmKey, SynergyArm>>;
  formula?: string;
  objective?: string;
  instances?: Record<string, InstanceFacts>;
  base_run_id?: string;
  held_fixed_instance_ids?: string[];
  synergy?: SynergyValue;
  certificate?: Certificate;
}

export interface ResultByKind {
  frontier: FrontierResult;
  stress: StressResult;
  "why-not": WhyNotResult;
  sensitivity: SensitivityResult;
  synergy: SynergyResult;
}

/** `AnalysisView` (GET /analyses/{id}); the list rows are the same without `result`. */
export interface AnalysisView<R = Record<string, unknown>> {
  analysis_id: string;
  kind: ServerKind;
  pilot_id: string | null;
  base_revision_id: string | null;
  base_run_id: string | null;
  job_id: string | null;
  job_state: Job["state"] | null;
  job_error: { code?: string; detail?: string; fields?: Record<string, unknown> } | null;
  /** queued | running | completed | cancelled | failed | interrupted */
  status: string;
  request: Record<string, unknown>;
  result: R | null;
  child_run_ids: string[];
  created_at: string;
  updated_at: string;
}
export type AnalysisRow = Omit<AnalysisView, "result">;

export interface AnalysisAccepted {
  analysis_id: string;
  job_id: string;
  job: Job;
}

const LIVE = new Set(["queued", "running"]);
const LIVE_JOB = new Set(["queued", "running", "cancel_requested", "waiting_for_review"]);
/** Still producing results: neither the analysis nor its job is terminal. */
export function isLive(a: Pick<AnalysisView, "status" | "job_state"> | null | undefined): boolean {
  if (!a) return false;
  if (a.job_state && !LIVE_JOB.has(a.job_state)) return false;
  return LIVE.has(a.status);
}

/* ================================================================ queries */

const retry = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;
const enc = encodeURIComponent;

/** One analysis, polled every 1.5 s while it is live (partial results are saved per child run). */
export function useAnalysisView<K extends AnalysisKind>(analysisId: string | null | undefined) {
  return useQuery({
    queryKey: qk.analysis(analysisId ?? ""),
    enabled: !!analysisId,
    queryFn: ({ signal }) => api.get<AnalysisView<ResultByKind[K]>>(`/analyses/${enc(analysisId!)}`, signal),
    refetchInterval: (q) => (isLive(q.state.data as AnalysisView | undefined) ? 1500 : false),
    retry,
  });
}

/** GET /analyses?kind&base_revision_id&base_run_id (newest first). */
export function useAnalysisHistory(kind: AnalysisKind, filter: { revisionId?: string | null; runId?: string | null }) {
  const sk = toServerKind(kind);
  const enabled = !!(filter.revisionId || filter.runId);
  return useQuery({
    queryKey: ["analyses", "explore", sk, filter.revisionId ?? "", filter.runId ?? ""],
    enabled,
    queryFn: async ({ signal }) =>
      (
        await api.get<{ analyses: AnalysisRow[] }>(
          `/analyses${qs({ kind: sk, base_revision_id: filter.revisionId ?? undefined, base_run_id: filter.runId ?? undefined, limit: 25 })}`,
          signal,
        )
      ).analyses ?? [],
    refetchInterval: (q) => ((q.state.data ?? []).some((a) => isLive(a)) ? 4000 : false),
    staleTime: 5_000,
    retry,
  });
}

/** The job behind an analysis, for measured progress and the current stage while it runs. */
export function useAnalysisJob(jobId: string | null | undefined, live: boolean) {
  return useQuery({
    queryKey: qk.job(jobId ?? ""),
    enabled: !!jobId,
    queryFn: ({ signal }) => api.get<Job>(`/jobs/${enc(jobId!)}`, signal),
    refetchInterval: live ? 1200 : false,
    retry,
  });
}

/* ================================================================ which revision / run */

export interface ExploreBase {
  /** Run in the URL (`?run=`), else the workspace's P/R/B1 run of the active revision. */
  runId: string | null;
  run: ReturnType<typeof useRun>;
  /** Scenario revision the analyses branch from. */
  revisionId: string | null;
  revision: ReturnType<typeof useRevision>;
  source: "url-run" | "workspace" | null;
  /** True while the URL run is loading and the revision is not yet known. */
  resolving: boolean;
  /** Workspace's active revision when it differs from the URL run's revision. */
  workspaceRevisionId: string | null;
}

/**
 * Resolve the analysed revision: the URL `?run=` run's `scenario_revision_id` comes first so a
 * shared link always means the same thing; the workspace store's active revision is the
 * fallback when no run is linked.
 */
export function useExploreBase(): ExploreBase {
  const sel = useSelection();
  const active = useUI((s) => s.active[sel.pilotKey]);
  const runsByRevision = useUI((s) => s.runsByRevision);
  const storeRuns = active ? runsByRevision[active.revisionId] ?? {} : {};
  const storeRun = storeRuns.P ?? storeRuns.R ?? storeRuns.B1 ?? storeRuns.B0 ?? null;
  const runId = sel.runId ?? storeRun ?? null;
  const run = useRun(runId);
  const fromRun = run.data?.scenario_revision_id ?? null;
  const revisionId = sel.runId ? fromRun : (fromRun ?? active?.revisionId ?? null);
  const revision = useRevision(revisionId);
  return {
    runId,
    run,
    revisionId,
    revision,
    source: sel.runId ? "url-run" : active ? "workspace" : null,
    resolving: !!runId && run.isLoading,
    workspaceRevisionId: active && active.revisionId !== revisionId ? active.revisionId : null,
  };
}

/**
 * The analysis a panel shows: the URL `?analysis=` when it is of this kind, else the newest
 * analysis of this kind for the base (revision, or run for stress).
 */
export function useCurrentAnalysis<K extends AnalysisKind>(kind: K, filter: { revisionId?: string | null; runId?: string | null }) {
  const sel = useSelection();
  const history = useAnalysisHistory(kind, filter);
  const fromUrl = useAnalysisView<K>(sel.analysisId);
  const urlMatches = !!fromUrl.data && fromServerKind(fromUrl.data.kind) === kind;
  const urlPending = !!sel.analysisId && fromUrl.isLoading;
  const latestId = !urlMatches && !urlPending ? history.data?.[0]?.analysis_id ?? null : null;
  const latest = useAnalysisView<K>(latestId);
  const q = urlMatches ? fromUrl : latest;
  return {
    data: q.data ?? null,
    loading: urlPending || history.isLoading || q.isLoading,
    error: (urlMatches ? fromUrl.error : null) ?? q.error ?? history.error ?? null,
    history: history.data ?? [],
    currentId: q.data?.analysis_id ?? null,
  };
}

/* ================================================================ mutations */

/** POST /analyses/{kind} → 202; selects the new analysis in the URL and lists its job in the tray. */
export function useLaunchAnalysis<K extends AnalysisKind>(kind: K) {
  const sel = useSelection();
  const qc = useQueryClient();
  const trackJob = useUI((s) => s.trackJob);
  const m = useMutation({
    mutationFn: (body: RequestByKind[K]) => api.post<AnalysisAccepted>(`/analyses/${kind}`, body, { idempotent: true }),
  });
  const launch = useCallback(
    async (body: RequestByKind[K]) => {
      try {
        const r = await m.mutateAsync(body);
        sel.setParams({ analysis: r.analysis_id });
        // Operation "analysis" without analysisKind: the tray shows progress / cancel / failure
        // toasts; result binding is by analysis ID here (the job's result_ref is a JSON summary).
        trackJob({ jobId: r.job_id, label: KIND_LABEL[kind], operation: "analysis", revisionId: null, pilotKey: sel.pilotKey });
        void qc.invalidateQueries({ queryKey: ["analyses", "explore", toServerKind(kind)] });
        return r;
      } catch (e) {
        const d = describeError(e);
        toast({ tone: "danger", title: `${KIND_LABEL[kind]}: ${d.title}`, description: d.detail });
        return null;
      }
    },
    [m, sel, trackJob, qc, kind],
  );
  return { launch, pending: m.isPending, error: m.error };
}

/* ================================================================ surrogate */

export interface PreviewRequest {
  crop_profile_id: string;
  soil_profile_id: string;
  application_efficiency: number;
  schedule: { date: string; gross_depth_mm: number }[];
  season_id: string;
  weather_scenario_id: string;
  pilot_id?: string | null;
  candidate_policy_id?: string | null;
}
export interface SurrogateVerification {
  estimate_kind: "exact_crop_model";
  exact_yield_kg_ha: number | null;
  preview_yield_kg_ha: number | null;
  preview_minus_exact_kg_ha: number | null;
  preview_domain_status: string;
  seasonal_irrigation_mm: number | null;
  has_finished: boolean | null;
  outcome?: Record<string, unknown> & { experiment_hash?: string; engine_name?: string; engine_version?: string; actual_harvest_date?: string; yield_basis?: string };
  note?: string;
  verified_at?: string;
}
export interface PreviewView {
  preview_id: string;
  proposed_policy_hash: string;
  model_version: string;
  feature_version: string;
  crop_profile_id: string;
  estimated_yield_kg_ha: number | null;
  estimate_kind: "surrogate_preview";
  domain_status: "in_domain" | "out_of_domain";
  domain_reasons: string[];
  evaluation_reference: string;
  uncertainty_note: string;
  residual_band_kg_ha: [number, number] | null;
  physical_precheck_status: "passed" | "failed" | "not_run";
  physical_precheck_reasons: string[];
  exact_confirmation_job_id: string | null;
  message: string | null;
  request: Record<string, unknown>;
  verification: SurrogateVerification | null;
  verify_job_id: string | null;
  created_at: string;
  /** Server-measured compute time; present on create only. */
  elapsed_ms?: number | null;
}

export function useCreatePreview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PreviewRequest) => api.post<PreviewView>("/surrogate/previews", body),
    onSuccess: (p) => qc.setQueryData(["surrogate-preview", p.preview_id], p),
  });
}

/** GET /surrogate/previews/{id}; polls while an exact confirmation job is attached but unrecorded. */
export function usePreviewView(previewId: string | null | undefined, verifyJobLive: boolean) {
  return useQuery({
    queryKey: ["surrogate-preview", previewId ?? ""],
    enabled: !!previewId,
    queryFn: ({ signal }) => api.get<PreviewView>(`/surrogate/previews/${enc(previewId!)}`, signal),
    refetchInterval: (q) => (verifyJobLive || (q.state.data?.verify_job_id && !q.state.data?.verification) ? 1500 : false),
    retry,
  });
}

export function useVerifyPreview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (previewId: string) =>
      api.post<{ preview_id: string; job_id: string; job: Job }>(`/surrogate/previews/${enc(previewId)}/verify`, {}, { idempotent: true }),
    onSuccess: (r) => void qc.invalidateQueries({ queryKey: ["surrogate-preview", r.preview_id] }),
  });
}

/* ================================================================ small helpers */

export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Unit of a revision objective id ("production_kg" → kg, "net_value_pkr" → PKR). */
export function objectiveUnit(objective: string | null | undefined): string {
  const o = String(objective ?? "");
  if (/_pkr$/.test(o)) return "PKR";
  if (/_kg$/.test(o)) return "kg";
  if (/_m3$/.test(o)) return "m3";
  return "";
}

export function objectiveLabel(objective: string | null | undefined): string {
  const o = String(objective ?? "").replace(/^worst_case_/, "worst-case ");
  const t = o ? o.replace(/_(kg|pkr|m3)$/, "").replace(/_/g, " ") : "objective";
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Short display of an intervention instance id: "pilot-a:field-003:pond-large" → "field-003 · pond-large". */
export function instanceShort(id: string): string {
  const parts = id.split(":");
  return (parts.length > 1 ? parts.slice(1) : parts).join(" · ");
}

export function useIsPlanRun(base: ExploreBase) {
  return useMemo(() => base.run.data?.outcome === "plan", [base.run.data]);
}

/** Axis bounds that keep a nearly flat series readable without implying a trend (adds ≥1% padding). */
export function paddedRange(values: (number | null | undefined)[]): { min: number; max: number } | null {
  const v = values.filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (!v.length) return null;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const pad = Math.max((hi - lo) * 0.15, Math.abs(hi) * 0.01, 1);
  return { min: lo - pad, max: hi + pad };
}
