/**
 * TanStack Query hooks. Keys contain immutable IDs only (pilot version, revision, run,
 * analysis), so a completed job can invalidate exactly what it produced (T10.2).
 */
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { api, qs, ApiError } from "./client";
import { readMapBundle, readTimeline, type MapBundle, type Timeline } from "./adapters";
import type {
  Capabilities,
  EvidenceRecord,
  FieldRecord,
  Health,
  InterventionInstance,
  Job,
  MetricValue,
  Pilot,
  PilotSummary,
  RevisionChange,
  RunResult,
  ScenarioRequest,
  ScenarioRevision,
  Season,
  SupplyProfile,
  UncertaintySet,
  WeatherScenario,
} from "./types";

export const qk = {
  health: ["health"] as const,
  capabilities: ["capabilities"] as const,
  pilots: ["pilots"] as const,
  pilot: (id: string, v: string) => ["pilot", id, v] as const,
  map: (id: string, v: string) => ["map", id, v] as const,
  geo: (url: string) => ["geo", url] as const,
  field: (v: string, fieldId: string) => ["field", v, fieldId] as const,
  seasons: (pilot: string) => ["seasons", pilot] as const,
  weather: (pilot: string, season: string) => ["weather-scenarios", pilot, season] as const,
  uncertainty: (pilot: string, season: string) => ["uncertainty-sets", pilot, season] as const,
  interventions: (pilot: string, season: string) => ["interventions", pilot, season] as const,
  revision: (id: string) => ["revision", id] as const,
  run: (id: string) => ["run", id] as const,
  timeline: (run: string, field: string | null) => ["timeline", run, field ?? "_network"] as const,
  comparison: (runIds: string[]) => ["comparison", ...[...runIds].sort()] as const,
  analysis: (id: string) => ["analysis", id] as const,
  job: (id: string) => ["job", id] as const,
  evidence: (id: string) => ["evidence", id] as const,
  evidenceSearch: (q: string, pilot?: string) => ["evidence-search", pilot ?? "", q] as const,
  report: (id: string) => ["report", id] as const,
  runs: (pilot: string, v: string) => ["runs", pilot, v] as const,
  analyses: (pilot: string, v: string) => ["analyses", pilot, v] as const,
  onboarding: (id: string) => ["onboarding", id] as const,
};

const retry = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;
type Opts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: ({ signal }) => api.get<Health>("/health", signal),
    refetchInterval: 15_000,
    retry: 0,
  });
}

export function useCapabilities() {
  return useQuery({
    queryKey: qk.capabilities,
    queryFn: ({ signal }) => api.get<Capabilities>("/capabilities", signal),
    staleTime: 30_000,
    retry,
  });
}

/** GET /pilots tolerates `[...]` or `{pilots: [...]}`. */
export function usePilots() {
  return useQuery({
    queryKey: qk.pilots,
    queryFn: async ({ signal }) => {
      const r = await api.get<unknown>("/pilots", signal);
      const list = Array.isArray(r) ? r : ((r as { pilots?: unknown[] })?.pilots ?? []);
      return list as PilotSummary[];
    },
    staleTime: 60_000,
    retry,
  });
}

export function usePilot(pilotId?: string, version?: string) {
  return useQuery({
    queryKey: qk.pilot(pilotId ?? "", version ?? ""),
    enabled: !!pilotId && !!version,
    queryFn: async ({ signal }) => {
      const r = await api.get<unknown>(`/pilots/${enc(pilotId!)}/versions/${enc(version!)}`, signal);
      const o = r as { pilot?: Pilot; manifest?: unknown };
      return { pilot: (o?.pilot ?? r) as Pilot, manifest: (o?.manifest ?? null) as unknown, raw: r };
    },
    staleTime: Number.POSITIVE_INFINITY, // immutable version
    retry,
  });
}

export function useMapBundle(pilotId?: string, version?: string) {
  return useQuery<MapBundle>({
    queryKey: qk.map(pilotId ?? "", version ?? ""),
    enabled: !!pilotId && !!version,
    queryFn: async ({ signal }) =>
      readMapBundle(
        await api.get<unknown>(`/pilots/${enc(pilotId!)}/versions/${enc(version!)}/map`, signal),
        pilotId!,
        version!,
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

/** Fetch a GeoJSON referenced by the map bundle (local /assets URL). */
export function useGeoJSON(url?: string | null, opts: Opts<GeoJSON.FeatureCollection> = {}) {
  return useQuery<GeoJSON.FeatureCollection, Error, GeoJSON.FeatureCollection, readonly unknown[]>({
    queryKey: qk.geo(url ?? ""),
    enabled: !!url,
    queryFn: async ({ signal }) => {
      const r = await api.get<GeoJSON.FeatureCollection | GeoJSON.Feature>(url!, signal);
      if (r && (r as GeoJSON.Feature).type === "Feature")
        return { type: "FeatureCollection", features: [r as GeoJSON.Feature] };
      return r as GeoJSON.FeatureCollection;
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry,
    ...opts,
  });
}

export interface FieldDetail {
  field: FieldRecord;
  raw: Record<string, unknown>;
}
export function useField(pilotVersion?: string, fieldId?: string | null, pilotId?: string) {
  return useQuery({
    queryKey: qk.field(`${pilotId ?? ""}@${pilotVersion ?? ""}`, fieldId ?? ""),
    enabled: !!pilotVersion && !!fieldId,
    queryFn: async ({ signal }) => {
      const r = await api.get<Record<string, unknown>>(
        `/fields/${enc(fieldId!)}${qs({ pilot_version: pilotVersion, pilot_id: pilotId })}`,
        signal,
      );
      const field = ((r as { field?: FieldRecord }).field ?? r) as FieldRecord;
      return { field, raw: r } as FieldDetail;
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

function listOf<T>(r: unknown, key: string): T[] {
  if (Array.isArray(r)) return r as T[];
  const v = (r as Record<string, unknown>)?.[key];
  return Array.isArray(v) ? (v as T[]) : [];
}

export function useSeasons(pilotId?: string) {
  return useQuery({
    queryKey: qk.seasons(pilotId ?? ""),
    enabled: !!pilotId,
    queryFn: async ({ signal }) =>
      listOf<Record<string, unknown>>(await api.get(`/seasons${qs({ pilot_id: pilotId })}`, signal), "seasons").map((e) => {
        // SeasonEntry {season, library, roster_configured} or a bare Season
        const season = (e.season ?? e) as Season;
        const lib = (e.library ?? null) as Record<string, unknown> | null;
        return {
          ...season,
          library: lib,
          roster_configured: (e.roster_configured as boolean | undefined) ?? null,
          library_ready: lib ? Boolean(lib.ready ?? lib.available ?? lib.library_hash ?? lib.candidate_library_hash) : season.library_ready,
        } as Season;
      }),
    staleTime: 60_000,
    retry,
  });
}

export function useWeatherScenarios(pilotId?: string, seasonId?: string) {
  return useQuery({
    queryKey: qk.weather(pilotId ?? "", seasonId ?? ""),
    enabled: !!pilotId && !!seasonId,
    queryFn: async ({ signal }) =>
      listOf<WeatherScenario>(
        await api.get(`/weather-scenarios${qs({ pilot_id: pilotId, season_id: seasonId })}`, signal),
        "weather_scenarios",
      ),
    staleTime: 60_000,
    retry,
  });
}

export interface UncertaintyCatalog {
  sets: UncertaintySet[];
  supplyProfiles: SupplyProfile[];
}
export function useUncertaintySets(pilotId?: string, seasonId?: string) {
  return useQuery<UncertaintyCatalog>({
    queryKey: qk.uncertainty(pilotId ?? "", seasonId ?? ""),
    enabled: !!pilotId && !!seasonId,
    queryFn: async ({ signal }) => {
      const r = await api.get<unknown>(`/uncertainty-sets${qs({ pilot_id: pilotId, season_id: seasonId })}`, signal);
      const o = (r ?? {}) as Record<string, unknown>;
      return {
        sets: listOf<UncertaintySet>(Array.isArray(r) ? r : o.uncertainty_sets ?? o.sets ?? [], "sets"),
        supplyProfiles: listOf<SupplyProfile>(o.supply_profiles ?? [], "supply_profiles"),
      };
    },
    staleTime: 60_000,
    retry,
  });
}

export function useInterventions(pilotId?: string, seasonId?: string, decisionAt?: string | null) {
  return useQuery({
    queryKey: [...qk.interventions(pilotId ?? "", seasonId ?? ""), decisionAt ?? ""],
    enabled: !!pilotId && !!seasonId,
    queryFn: async ({ signal }) => {
      const r = await api.get<unknown>(`/interventions${qs({ pilot_id: pilotId, season_id: seasonId, decision_at: decisionAt })}`, signal);
      const raw = listOf<Record<string, unknown>>(
        Array.isArray(r) ? r : (r as Record<string, unknown>)?.interventions ?? (r as Record<string, unknown>)?.instances,
        "interventions",
      );
      // InterventionEligibility {instance, eligible, reasons, commissioned_on, type_label} → flat instance
      return raw.map((e) => {
        if (!e.instance) return e as unknown as InterventionInstance;
        const inst = e.instance as InterventionInstance;
        return {
          ...inst,
          category: (e.category as InterventionInstance["category"]) ?? inst.category,
          eligible: e.eligible as boolean,
          eligibility_reasons: (e.reasons as string[]) ?? [],
          earliest_commissioning: (e.commissioned_on as string | null) ?? null,
          label: (e.type_label as string | undefined) ? `${e.type_label} · ${inst.target_ids.join(", ")}` : undefined,
          in_library: (e.in_library as boolean | null) ?? null,
        } as InterventionInstance;
      });
    },
    staleTime: 60_000,
    retry,
  });
}

/** Server revision view: immutable snapshot plus readiness and its runs (T9.1). */
export interface RevisionIssue {
  code: string;
  detail: string;
  field?: string | null;
}
export interface RevisionReadiness {
  ready: boolean;
  blockers: RevisionIssue[];
  warnings: RevisionIssue[];
  max_attainable_service: Record<string, number | null>;
  coverage?: Record<string, unknown> | null;
}
export interface RevisionView {
  revision: ScenarioRevision;
  readiness: RevisionReadiness | null;
  runs: { run_id: string; plan_kind: string; outcome: string; solver_status: string; created_at: string; job_id?: string | null }[];
  is_head: boolean;
  origin: string | null;
}

/** Accepts the composed `{revision, readiness, runs}` view or a bare revision. */
export function readRevisionView(raw: unknown): RevisionView {
  const o = (raw ?? {}) as Record<string, unknown>;
  const inner = o.revision as Record<string, unknown> | undefined;
  const isView = !!inner && typeof inner === "object" && "scenario_revision_id" in inner;
  const revision = (isView ? inner : o) as unknown as ScenarioRevision;
  const rd = (isView ? o.readiness : null) as Record<string, unknown> | null;
  const issues = (v: unknown): RevisionIssue[] =>
    Array.isArray(v) ? v.map((x) => (typeof x === "string" ? { code: "NOTE", detail: x } : (x as RevisionIssue))) : [];
  return {
    revision,
    readiness: rd
      ? {
          ready: !!rd.ready,
          blockers: issues(rd.blockers),
          warnings: issues(rd.warnings),
          max_attainable_service: (rd.max_attainable_service ?? {}) as Record<string, number | null>,
          coverage: (rd.coverage ?? null) as Record<string, unknown> | null,
        }
      : null,
    runs: (isView && Array.isArray(o.runs) ? o.runs : []) as RevisionView["runs"],
    is_head: isView ? o.is_head !== false : true,
    origin: (isView ? (o.origin as string | null) : null) ?? null,
  };
}

export function useRevision(revisionId?: string | null) {
  return useQuery({
    queryKey: qk.revision(revisionId ?? ""),
    enabled: !!revisionId,
    queryFn: async ({ signal }) => readRevisionView(await api.get<unknown>(`/scenario-revisions/${enc(revisionId!)}`, signal)),
    staleTime: 30_000,
    retry,
  });
}

/** GET /runs/{id} → RunResult with inline `metrics` (accepts `{run, metrics}` or a bare run). */
export async function fetchRun(id: string, signal?: AbortSignal): Promise<RunResult> {
  const r = await api.get<unknown>(`/runs/${enc(id)}`, signal);
  const o = r as { run?: RunResult; metrics?: unknown; selection?: unknown };
  if (o?.run)
    return {
      ...o.run,
      metrics: (o.metrics ?? (o.run as { metrics?: unknown }).metrics) as never,
      selection: o.selection ?? null,
    } as RunResult;
  return r as RunResult;
}

export function useRun(runId?: string | null) {
  return useQuery({
    queryKey: qk.run(runId ?? ""),
    enabled: !!runId,
    queryFn: ({ signal }) => fetchRun(runId!, signal),
    staleTime: Number.POSITIVE_INFINITY, // immutable run
    retry,
  });
}

/** Multiple runs at once (Compare ladder, frontier points). */
export function useRuns(runIds: string[]) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["runs-bundle", ...runIds],
    enabled: runIds.length > 0,
    queryFn: async ({ signal }) =>
      Promise.all(
        runIds.map((id) =>
          qc.fetchQuery({
            queryKey: qk.run(id),
            queryFn: () => fetchRun(id, signal),
            staleTime: Number.POSITIVE_INFINITY,
          }),
        ),
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

export function useTimeline(runId?: string | null, fieldId?: string | null) {
  return useQuery<Timeline>({
    queryKey: qk.timeline(runId ?? "", fieldId ?? null),
    enabled: !!runId,
    queryFn: async ({ signal }) =>
      readTimeline(
        await api.get(`/runs/${enc(runId!)}/timeline${qs({ field_id: fieldId, resolution: "daily" })}`, signal),
        runId!,
        fieldId ?? null,
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

/* ---------------------------------------------------------------- dedicated run views (PRD §8.1–8.5) */
/** Every run-view endpoint may answer `{available:false, reason}`; never substitute numbers for it. */
export interface RunViewUnavailable {
  available: false;
  reason: string;
  run_id?: string;
}
export type RunView<T> = (T & { available: true }) | RunViewUnavailable;
/** A status/reason pair the server uses for quantities it declines to compute. */
export interface StatusReason {
  status: MetricValue["status"];
  reason: string | null;
}

export interface AccountingFlow {
  from: string;
  to: string;
  m3: number;
}
export interface RunAccounting {
  run_id: string;
  state_id: string | null;
  boundaries: Record<string, number | null>;
  flows: AccountingFlow[];
  reconciliation: { source_minus_loss_minus_receipt_m3?: number | null; note?: string | null } & Record<string, unknown>;
  per_field: Record<string, Record<string, number>>;
  basin_savings: StatusReason | null;
}

export interface EquityField {
  field_id: string;
  group: "head" | "middle" | "tail" | string | null;
  owner_ref: string | null;
  service_ratio: number | null;
  service_status: MetricValue["status"] | string;
  production_kg: number | null;
  groundwater_m3: number | null;
  production_delta_kg: number | null;
}
export interface EquityGroupStats {
  fields: number;
  eligible: number;
  mean_service_ratio: number | null;
  min_service_ratio: number | null;
}
export interface EquityComparison {
  compatible: boolean;
  compatibility_key?: string;
  shared?: { condition: string; value: unknown }[];
  differences?: { condition: string; values: unknown[]; kind?: string; note?: string }[];
  label?: string;
}
export interface RunEquity {
  run_id: string;
  baseline_run_id: string | null;
  measure_label: string;
  aggregation: string;
  fields: EquityField[];
  groups: Record<string, EquityGroupStats>;
  min_service_ratio: number | null;
  zero_reference_fields: string[];
  fields_worse_off: (string | { field_id: string; [k: string]: unknown })[];
  fields_worse_off_count: number | null;
  pumping_burden_share: Record<string, number>;
  owner_aggregation: unknown;
  owner_note: string | null;
  comparison: EquityComparison | null;
}

export interface EconomicsInstance {
  instance_id: string;
  category: string;
  capex_pkr: number;
  seasonal_opex_pkr: number;
  shared: boolean;
  charged: string;
  evidence_ids: string[];
}
export interface EconomicsSensitivity {
  case: string;
  gross_capital_pkr?: number;
  operating_pkr?: number;
  within_budget: boolean;
}
export interface RunEconomics {
  run_id: string;
  gross_project_cost_pkr: number | null;
  capital_budget_pkr: number | null;
  public_grant_pkr: number | StatusReason | null;
  participant_cash_pkr: number | null;
  seasonal_operating_pkr: number | null;
  operating_budget_pkr: number | null;
  pumping: { field_id: string; seasonal_opex_pkr: number; pump_volume_m3: number }[];
  instances: EconomicsInstance[];
  crop_value: MetricValue | null;
  irrigation_contribution: MetricValue | null;
  sensitivity: EconomicsSensitivity[];
  sensitivity_note: string | null;
  cashflow: StatusReason | Record<string, unknown> | null;
}

export interface PlanAction {
  action_id: string;
  category: string;
  target_ids: string[];
  description: string;
  crop_season: string | null;
  decision_date: string | null;
  start_date: string | null;
  commissioning_date: string | null;
  quantity: Record<string, number | string | null>;
  capex_pkr: number | null;
  seasonal_opex_pkr: number | null;
  payer: string | null;
  responsible_role: string | null;
  required_approval: string | null;
  prerequisites: string[];
  affected_fields: string[];
  modeled_change: Record<string, number | null>;
  uncertainty: string | null;
  source_refs: string[];
  run_id: string;
  status: string;
}
export interface ScheduleRow {
  field_id: string;
  date: string;
  gross_depth_mm: number;
  policy_family: string;
}
export interface RunActionPlan {
  run_id: string;
  plan_kind: string;
  actions: PlanAction[];
  schedules: ScheduleRow[];
  status_note: string | null;
}

export interface SdgCard {
  card: string;
  metrics: string[];
  interpretation: string;
  target_url: string | null;
  official_indicator: boolean;
  values: MetricValue[];
  formulas: Record<string, string>;
  run_ids: string[];
  limitations: string[];
}
export interface RunImpact {
  run_id: string;
  cards: SdgCard[];
  distribution: { field_id: string; production_kg: number | null }[];
  co2: StatusReason | null;
}

function runViewQuery<T>(key: readonly unknown[], runId: string | null | undefined, path: string, params?: Record<string, string | null | undefined>) {
  return {
    queryKey: key,
    enabled: !!runId,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.get<RunView<T>>(`/runs/${enc(runId!)}/${path}${params ? qs(params) : ""}`, signal),
    staleTime: Number.POSITIVE_INFINITY, // derived from an immutable run
    retry,
  };
}

export function useRunAccounting(runId?: string | null) {
  return useQuery(runViewQuery<RunAccounting>(["run-accounting", runId ?? ""], runId, "accounting"));
}
export function useRunEquity(runId?: string | null, baselineRunId?: string | null) {
  const b = baselineRunId && baselineRunId !== runId ? baselineRunId : null;
  return useQuery(runViewQuery<RunEquity>(["run-equity", runId ?? "", b ?? ""], runId, "equity", { baseline_run_id: b }));
}
export function useRunEconomics(runId?: string | null) {
  return useQuery(runViewQuery<RunEconomics>(["run-economics", runId ?? ""], runId, "economics"));
}
export function useRunActionPlan(runId?: string | null) {
  return useQuery(runViewQuery<RunActionPlan>(["run-action-plan", runId ?? ""], runId, "action-plan"));
}
export function useRunImpact(runId?: string | null, baselineRunId?: string | null) {
  const b = baselineRunId && baselineRunId !== runId ? baselineRunId : null;
  return useQuery(runViewQuery<RunImpact>(["run-impact", runId ?? "", b ?? ""], runId, "impact", { baseline_run_id: b }));
}

export interface RunListItem {
  run_id: string;
  plan_kind?: string;
  solver_status?: string;
  outcome?: string;
  scenario_revision_id?: string;
  created_at?: string;
  label?: string;
  season_id?: string;
}
/** Optional listing of stored runs for a pilot version (published example sessions). */
export function useRunList(pilotId?: string, version?: string) {
  return useQuery({
    queryKey: qk.runs(pilotId ?? "", version ?? ""),
    enabled: !!pilotId && !!version,
    queryFn: async ({ signal }) =>
      listOf<RunListItem>(await api.get(`/runs${qs({ pilot_id: pilotId, pilot_version: version })}`, signal), "runs"),
    staleTime: 10_000,
    retry: 0,
  });
}

export function useComparison(runIds: string[]) {
  return useQuery({
    queryKey: qk.comparison(runIds),
    enabled: runIds.length >= 2,
    queryFn: () => api.post<Record<string, unknown>>("/comparisons", { run_ids: runIds }),
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

export function useAnalysis(analysisId?: string | null, poll = false) {
  return useQuery({
    queryKey: qk.analysis(analysisId ?? ""),
    enabled: !!analysisId,
    queryFn: ({ signal }) => api.get<Record<string, unknown>>(`/analyses/${enc(analysisId!)}`, signal),
    refetchInterval: (q) => {
      const s = (q.state.data as { status?: string } | undefined)?.status;
      return poll && (!s || s === "running" || s === "queued") ? 1500 : false;
    },
    retry,
  });
}

export function useAnalysisList(pilotId?: string, version?: string) {
  return useQuery({
    queryKey: qk.analyses(pilotId ?? "", version ?? ""),
    enabled: !!pilotId && !!version,
    queryFn: async ({ signal }) =>
      listOf<Record<string, unknown>>(
        await api.get(`/analyses${qs({ pilot_id: pilotId, pilot_version: version })}`, signal),
        "analyses",
      ),
    staleTime: 10_000,
    retry: 0,
  });
}

export function useJob(jobId?: string | null) {
  return useQuery({
    queryKey: qk.job(jobId ?? ""),
    enabled: !!jobId,
    queryFn: ({ signal }) => api.get<Job>(`/jobs/${enc(jobId!)}`, signal),
    refetchInterval: (q) => {
      const s = q.state.data?.state;
      return !s || s === "queued" || s === "running" || s === "cancel_requested" ? 1000 : false;
    },
    retry,
  });
}

export function useEvidence(id?: string | null) {
  return useQuery({
    queryKey: qk.evidence(id ?? ""),
    enabled: !!id,
    queryFn: async ({ signal }) => {
      const r = await api.get<Record<string, unknown>>(`/evidence/${enc(id!)}`, signal);
      // EvidenceDetail {record, document, pilot_ids} or a bare record
      if (r && "record" in r) {
        if (!r.record) {
          const doc = (r.document ?? {}) as Record<string, unknown>;
          return {
            evidence_id: id!,
            source_title: String(doc.title ?? id),
            kind: (doc.kind as EvidenceRecord["kind"]) ?? "literature",
            verification_state: "unchecked",
            source_url: (doc.source_url as string | null) ?? null,
            limitations: [],
            parent_evidence_ids: [],
            document: doc,
          } as unknown as EvidenceRecord;
        }
        return { ...(r.record as EvidenceRecord), document: r.document ?? null, pilot_ids: r.pilot_ids ?? [] } as EvidenceRecord;
      }
      return r as unknown as EvidenceRecord;
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry,
  });
}

export interface EvidenceHit {
  doc_id: string;
  kind: string;
  pilot_id: string | null;
  score: number;
  snippet: string;
  source_url: string | null;
  title: string;
}
export function useEvidenceSearch(q: string, pilotId?: string) {
  return useQuery({
    queryKey: qk.evidenceSearch(q, pilotId),
    enabled: q.trim().length > 0, // the curated index requires a term (min length 1)
    queryFn: async ({ signal }) =>
      listOf<EvidenceHit>(await api.get(`/evidence/search${qs({ q, pilot_id: pilotId })}`, signal), "results"),
    staleTime: 30_000,
    retry,
  });
}

/* ---------------------------------------------------------------- mutations */

export interface CreatedScenario {
  scenario_id: string;
  revision: ScenarioRevision;
  view: RevisionView;
}
export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: ScenarioRequest) => {
      // POST /scenarios takes {contract_version, label?, request} (T9.1, ScenarioCreate).
      const r = await api.post<Record<string, unknown>>(
        "/scenarios",
        { contract_version: "2.0.0", request: req },
        { idempotent: true },
      );
      const view = readRevisionView(r.revision ?? r.initial_revision ?? r);
      const scenario_id = String(r.scenario_id ?? view.revision.scenario_id);
      return { scenario_id, revision: view.revision, view } as CreatedScenario;
    },
    onSuccess: (d) => qc.setQueryData(qk.revision(d.revision.scenario_revision_id), d.view),
  });
}

export function useDeriveRevision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: { scenarioId: string; parentRevisionId: string; changes: RevisionChange }) => {
      const r = await api.post<Record<string, unknown>>(
        `/scenarios/${enc(a.scenarioId)}/revisions`,
        { contract_version: "2.0.0", parent_revision_id: a.parentRevisionId, changes: a.changes },
        { idempotent: true },
      );
      return readRevisionView(r);
    },
    onSuccess: (v) => qc.setQueryData(qk.revision(v.revision.scenario_revision_id), v),
  });
}

export function useSolve() {
  return useMutation({
    mutationFn: async (a: { revisionId: string; planKind: string; timeLimitS?: number }) => {
      const r = await api.post<Record<string, unknown>>(
        `/scenario-revisions/${enc(a.revisionId)}/solve`,
        { plan_kind: a.planKind, time_limit_s: a.timeLimitS ?? 10 },
        { idempotent: true },
      );
      return { jobId: String(r.job_id ?? (r.job as Job | undefined)?.job_id ?? ""), raw: r };
    },
  });
}

export function useCancelJob() {
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/jobs/${enc(jobId)}/cancel`, {}, { idempotent: true }),
  });
}

export function useStartAnalysis() {
  return useMutation({
    mutationFn: async (a: { kind: "frontier" | "stress" | "why-not" | "sensitivity" | "synergy"; body: unknown }) => {
      const r = await api.post<Record<string, unknown>>(`/analyses/${a.kind}`, a.body, { idempotent: true });
      return {
        jobId: (r.job_id as string | undefined) ?? null,
        analysisId: (r.analysis_id as string | undefined) ?? null,
        raw: r,
      };
    },
  });
}

export function useCreateReport() {
  return useMutation({
    mutationFn: async (body: { run_ids: string[]; analysis_ids?: string[]; report_type: string }) =>
      api.post<Record<string, unknown>>("/reports", body, { idempotent: true }),
  });
}

export function useSurrogatePreview() {
  return useMutation({
    mutationFn: (body: unknown) => api.post<Record<string, unknown>>("/surrogate/previews", body),
  });
}
export function useVerifyPreview() {
  return useMutation({
    mutationFn: (previewId: string) =>
      api.post<Record<string, unknown>>(`/surrogate/previews/${enc(previewId)}/verify`, {}, { idempotent: true }),
  });
}

function enc(s: string) {
  return encodeURIComponent(s);
}
