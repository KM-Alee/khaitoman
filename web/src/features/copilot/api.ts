/**
 * Copilot API (T9.1 / T11): typed client for /api/v2/copilot and the deterministic
 * /runs/{id}/explanations view. Shapes mirror aabflow/copilot/{router,orchestrator,
 * answer_validation,store}.py exactly; nothing here computes analytical values.
 */
import { useQuery } from "@tanstack/react-query";
import { API_BASE, ApiError, api } from "@/lib/api/client";
import type { JobState, PlanKind, SolverStatus } from "@/lib/api/types";

const enc = encodeURIComponent;

/* ------------------------------------------------------------------ status */

/** GET /copilot/status */
export interface CopilotStatus {
  configured: boolean;
  model: string;
  prompt_version: string;
  tool_schema_version: string;
  offline_note: string;
}

export type CopilotStatusResult =
  | { mounted: true; status: CopilotStatus }
  /** The API build does not expose /copilot routes (404 from the JSON catch-all). */
  | { mounted: false; detail: string };

export const copilotKeys = {
  status: ["copilot", "status"] as const,
  explanations: (runId: string) => ["run-explanations", runId] as const,
};

export function useCopilotStatus() {
  return useQuery<CopilotStatusResult>({
    queryKey: copilotKeys.status,
    queryFn: async ({ signal }) => {
      try {
        return { mounted: true, status: await api.get<CopilotStatus>("/copilot/status", signal) };
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return { mounted: false, detail: e.message };
        throw e;
      }
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
  });
}

/* ------------------------------------------------------------------ context + sessions */

export type CopilotLanguage = "en" | "ur" | "roman_ur";

/** copilot/context UIContext (extra="forbid"): only these keys may be sent. */
export interface UIContext {
  pilot_id?: string | null;
  pilot_version?: string | null;
  season_id?: string | null;
  scenario_revision_id?: string | null;
  selected_run_id?: string | null;
  selected_field_id?: string | null;
  /** ISO date (YYYY-MM-DD) */
  timeline_date?: string | null;
  view?: string | null;
  language?: CopilotLanguage;
  units?: "metric";
  ui_revision?: number | null;
}

/** PinnedContext.prompt_view(): the server-resolved, membership-checked context of a turn. */
export interface PinnedContextView {
  pilot_id: string;
  pilot_version: string;
  pilot_name?: string;
  season_id?: string;
  crop?: string;
  scenario_id?: string;
  scenario_revision_id?: string;
  selected_run_id?: string;
  selected_run_plan_kind?: PlanKind | string;
  selected_run_outcome?: SolverStatus | string;
  selected_field_id?: string;
  timeline_date?: string;
  view?: string;
  language?: CopilotLanguage;
  role?: "planner" | "viewer";
  notes?: string[];
  permitted_pilot_ids?: string[];
  unavailable_features?: string[];
}

export interface SessionOut {
  session_id: string;
  role: string;
  status: CopilotStatus;
}

export interface TurnAccepted {
  turn_id: string;
  session_id: string;
  context: PinnedContextView;
  events_url: string;
}

export const TERMINAL_TURN = ["completed", "clarification", "failed", "cancelled", "provider_unavailable", "budget_exhausted"] as const;
export type TerminalTurnStatus = (typeof TERMINAL_TURN)[number];
export type TurnStatus = "running" | TerminalTurnStatus;
export const isTerminalTurn = (s: string): s is TerminalTurnStatus => (TERMINAL_TURN as readonly string[]).includes(s);

/* ------------------------------------------------------------------ answers (answer_validation.py) */

export interface Citation {
  ref_id: string;
  /** Derived from the tool-result key the ID came from: run, evidence, field, comparison, analysis, job, ... */
  kind: string;
  /** Auto-attached because the prose quotes a number from this run/comparison. */
  auto?: boolean;
}

export interface TextBlock {
  type: "text" | "uncertainty";
  text: string;
  citations: Citation[];
  /** A sentence was replaced with a "withheld" notice after failing numeric validation. */
  withheld?: boolean;
}

export interface MetricBlock {
  type: "metric";
  metric_id: string;
  definition_id: string;
  run_id: string;
  field_id: string | null;
  value: number | null;
  unit: string;
  status: "available" | "not_estimated" | "not_applicable" | "blocked" | string;
  reason: string | null;
  basis: string | null;
  plan_kind: PlanKind | string;
  solver_status: SolverStatus | string;
}

export interface ComparisonDelta {
  metric_id: string;
  unit: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  status: string;
}

export interface ComparisonBlock {
  type: "comparison";
  comparison_id: string;
  run_ids: string[];
  compatible: boolean;
  label: string;
  deltas: ComparisonDelta[];
  fields_worse_off: unknown[];
}

export type ActionKind = "open_run" | "open_branch" | "open_field" | "open_report" | "open_analysis" | "open_comparison";

export interface ActionBlock {
  type: "action";
  action: ActionKind;
  ref_id: string;
  label: string;
  /** Attached by the server for an object this turn created. */
  auto?: boolean;
}

export type AnswerBlock = TextBlock | MetricBlock | ComparisonBlock | ActionBlock;

export interface CopilotAnswer {
  language: CopilotLanguage;
  blocks: AnswerBlock[];
  needs_clarification: boolean;
  clarification_question: string | null;
  /** True when every reference and prose number was supported by this turn's tool results. */
  validated: boolean;
  issues: string[];
  /** Server-written fallback (provider unavailable / budget exhausted), not model output. */
  deterministic?: boolean;
}

export interface ViewIntent {
  target: "pilot" | "field" | "run" | "branch" | "tab" | "date" | "report" | "analysis" | "comparison";
  pilot_id?: string;
  field_id?: string;
  run_id?: string;
  scenario_revision_id?: string;
  tab?: string;
  date?: string;
  report_id?: string;
  analysis_id?: string;
  comparison_id?: string;
}

export interface CreatedRef {
  kind: "branch" | "run" | "report" | "analysis" | string;
  ref_id: string;
  label: string;
}

export interface TurnError {
  code: string;
  detail?: string;
  retryable?: boolean;
}

/** GET /copilot/turns/{id}?include_tools=true → copilot_tool_calls rows */
export interface ToolCallRow {
  pk: number;
  call_id: string;
  round: number;
  tool: string;
  arguments: Record<string, unknown> | string | null;
  idempotency_key: string | null;
  status: "running" | "succeeded" | "failed" | "rejected" | string;
  result: Record<string, unknown> | null;
  started_at: string;
  finished_at: string | null;
}

/* ------------------------------------------------------------------ events (orchestrator.emit) */

export interface JobUpdatePayload {
  job_id: string;
  operation?: string;
  state: JobState;
  stage?: string | null;
  progress?: number | null;
  result_ref?: string | null;
  error?: Record<string, unknown> | null;
  state_meaning?: string | null;
  run?: { run_id: string; plan_kind?: string; solver_status?: string; outcome?: string; label?: string | null };
  analysis?: { analysis_id?: string; kind?: string } & Record<string, unknown>;
  analysis_id?: string;
  report?: { report_id?: string; download_url?: string } & Record<string, unknown>;
  report_id?: string;
}

export type CopilotEvent =
  | { type: "turn_started"; payload: { turn_id: string; context: PinnedContextView; badge: { pilot_id: string; pilot_version: string; run_id: string | null; season_id: string | null } } }
  | { type: "tool_started"; payload: { call_id: string; tool: string; activity: string; semantics: string } }
  | {
      type: "tool_finished";
      payload: { call_id: string; tool: string; ok: boolean; activity: string; error?: TurnError | null; reused?: boolean; job_ids?: string[]; created?: CreatedRef[] };
    }
  | { type: "answer"; payload: CopilotAnswer }
  | { type: "view_intents"; payload: { intents: ViewIntent[] } }
  | { type: "turn_finished"; payload: { status: TerminalTurnStatus; rounds?: number; tool_calls?: number; latency_ms?: number; pending_job_ids: string[]; error?: TurnError | null } }
  | { type: "job_update"; payload: JobUpdatePayload }
  | { type: "jobs_settled"; payload: { pending_job_ids: string[] } }
  | { type: "jobs_cancelled"; payload: { job_ids: string[] } }
  | { type: "error"; payload: TurnError };

export type CopilotEventEnvelope = CopilotEvent & { event_id: number; turn_id: string; created_at: string };

export const COPILOT_EVENT_TYPES = [
  "turn_started",
  "tool_started",
  "tool_finished",
  "answer",
  "view_intents",
  "turn_finished",
  "job_update",
  "jobs_settled",
  "jobs_cancelled",
  "error",
] as const;

/** Row of a session's turn list (GET /copilot/sessions/{id}). */
export interface SessionTurnRow {
  turn_id: string;
  seq: number;
  status: TurnStatus;
  user_message: string;
  answer: CopilotAnswer | null;
  view_intents: ViewIntent[];
  created_refs: CreatedRef[];
  job_ids: string[];
  error: TurnError | null;
  created_at: string;
  finished_at: string | null;
}

export interface SessionDetail {
  session_id: string;
  role: string;
  turns: SessionTurnRow[];
}

/** GET /copilot/turns/{id} (full audit row). `context` is the full PinnedContext. */
export interface TurnDetail extends SessionTurnRow {
  session_id: string;
  context: PinnedContextView & { selected_run_id?: string | null };
  model: string | null;
  prompt_version: string | null;
  tool_schema_version: string | null;
  request_ids: string[];
  rounds: number;
  latency_ms: number | null;
  tool_calls?: ToolCallRow[];
  events?: CopilotEventEnvelope[] | null;
}

/* ------------------------------------------------------------------ calls */

export const copilotApi = {
  createSession: (context: UIContext, role: "planner" | "viewer" = "planner") =>
    api.post<SessionOut>("/copilot/sessions", { contract_version: "2.0.0", context, role }),
  getSession: (sessionId: string, signal?: AbortSignal) => api.get<SessionDetail>(`/copilot/sessions/${enc(sessionId)}`, signal),
  postMessage: (sessionId: string, message: string, context: UIContext) =>
    api.post<TurnAccepted>(`/copilot/sessions/${enc(sessionId)}/messages`, { contract_version: "2.0.0", message, context }),
  retryTurn: (turnId: string) => api.post<TurnAccepted>(`/copilot/turns/${enc(turnId)}/retry`, {}),
  cancelTurn: (turnId: string) =>
    api.post<{ turn_id: string; cancel_requested: boolean; status: string }>(`/copilot/turns/${enc(turnId)}/cancel`, {}),
  getTurn: (turnId: string, includeTools = false, signal?: AbortSignal) =>
    api.get<TurnDetail>(`/copilot/turns/${enc(turnId)}${includeTools ? "?include_tools=true" : ""}`, signal),
  /** Absolute events URL; the server returns `/api/v2/...` already. */
  eventsUrl: (accepted: Pick<TurnAccepted, "events_url" | "turn_id">, after = 0) => {
    const base = accepted.events_url?.startsWith("/") ? accepted.events_url : `${API_BASE}/copilot/turns/${enc(accepted.turn_id)}/events`;
    return after > 0 ? `${base}?after=${after}` : base;
  },
};

/* ------------------------------------------------------------------ explanations (services/explanations.py) */

export interface ExplanationSelected {
  instance_id: string;
  category: string;
  capex_pkr: number;
  seasonal_opex_pkr: number;
  commissioned_on: string | null;
  evidence_ids: string[];
  why: string[];
  affected_field_ids: string[];
  marginal_role: { status: string; how: string };
}

export interface ExplanationRejected {
  instance_id: string;
  category: string;
  capex_pkr: number;
  seasonal_opex_pkr: number;
  commissioned_on: string | null;
  evidence_ids: string[];
  kind: "not_selected" | "ineligible" | "excluded_by_scenario" | "not_allowed" | "no_new_capital" | "over_budget" | string;
  why: string[];
  opportunity_cost: { status: string; how: string };
}

export interface ExplanationBudget {
  constraint: "capital_budget" | "operating_budget" | string;
  used_pkr: number | null;
  limit_pkr: number;
  utilization: number | null;
  binding: boolean;
}

export interface SaturatedResource {
  state_id: string;
  resource_id: string;
  interval_id: string;
  period: [string, string] | null;
  used_m3: number;
  capacity_m3: number;
  utilization: number;
  field_ids: string[];
}

export interface WhyNoSolution {
  solver_status: SolverStatus | string;
  infeasibility_kind: string | null;
  constraint_groups: unknown[];
  configurations: unknown[];
  empty_fields: Record<string, unknown>;
  coverage_note: string | null;
  statement: string;
  relaxation_branches: { change: Record<string, unknown>; label: string }[];
  relaxation_note: string;
}

export interface RunExplanations {
  run_id: string;
  outcome: "plan" | "no_plan" | "invalid_plan" | string;
  plan_kind: PlanKind | string;
  proof_scope: string;
  selected?: ExplanationSelected[];
  rejected?: ExplanationRejected[];
  bottlenecks?: {
    saturated_resources: SaturatedResource[];
    saturated_count: number;
    budgets: ExplanationBudget[];
    threshold: number;
    note: string;
  };
  why_no_solution?: WhyNoSolution;
}

export function useRunExplanations(runId?: string | null) {
  return useQuery({
    queryKey: copilotKeys.explanations(runId ?? ""),
    enabled: !!runId,
    queryFn: ({ signal }) => api.get<RunExplanations>(`/runs/${enc(runId!)}/explanations`, signal),
    staleTime: Number.POSITIVE_INFINITY, // runs are immutable
    retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 1,
  });
}
