/**
 * Copilot API client (docs/COPILOT.md): /api/v2/copilot routes plus the deterministic
 * /runs/{id}/explanations view used when the hosted assistant is unavailable.
 * Nothing here computes an analytical value.
 */
import { useQuery } from "@tanstack/react-query";
import { API_BASE, ApiError, api } from "@/lib/api/client";
import type { PlanKind, SolverStatus } from "@/lib/api/types";
import type { CopilotEventEnvelope, PinnedContextView, SessionSummary, TurnViewRow, UIContext } from "./types";

const enc = encodeURIComponent;

/** GET /copilot/status */
export interface CopilotStatus {
  configured: boolean;
  state?: "ready" | "unavailable";
  reason?: string | null;
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
  sessions: ["copilot", "sessions"] as const,
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

/** Recent conversations for the history menu (restorable after a restart). */
export function useCopilotSessions(enabled: boolean) {
  return useQuery({
    queryKey: copilotKeys.sessions,
    enabled,
    queryFn: ({ signal }) => api.get<{ sessions: SessionSummary[] }>("/copilot/sessions?limit=30", signal),
    staleTime: 10_000,
  });
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

/** GET /copilot/sessions/{id} (turn rows are a subset of TurnView). */
export interface SessionDetail {
  session_id: string;
  role: string;
  created_at?: string;
  turns: Pick<
    TurnViewRow,
    "turn_id" | "seq" | "status" | "user_message" | "language" | "answer" | "view_intents" | "created_refs" | "job_ids" | "error" | "rounds" | "latency_ms" | "created_at" | "finished_at"
  >[];
}

export const copilotApi = {
  createSession: (context: UIContext, role: "planner" | "viewer" = "planner") =>
    api.post<SessionOut>("/copilot/sessions", { contract_version: "2.0.0", context, role }),
  getSession: (sessionId: string, signal?: AbortSignal) => api.get<SessionDetail>(`/copilot/sessions/${enc(sessionId)}`, signal),
  postMessage: (sessionId: string, message: string, context: UIContext) =>
    api.post<TurnAccepted>(`/copilot/sessions/${enc(sessionId)}/messages`, { contract_version: "2.0.0", message, context }),
  retryTurn: (turnId: string) => api.post<TurnAccepted>(`/copilot/turns/${enc(turnId)}/retry`, {}),
  cancelTurn: (turnId: string) =>
    api.post<{ turn_id: string; cancel_requested: boolean; status: string }>(`/copilot/turns/${enc(turnId)}/cancel`, {}),
  getTurn: (turnId: string, signal?: AbortSignal) => api.get<TurnViewRow>(`/copilot/turns/${enc(turnId)}`, signal),
  /** The SSE events as JSON (resume after a dropped stream). */
  eventLog: (turnId: string, after = 0, signal?: AbortSignal) =>
    api.get<CopilotEventEnvelope[]>(`/copilot/turns/${enc(turnId)}/event-log?after=${after}`, signal),
  eventsUrl: (turnId: string, after = 0) => `${API_BASE}/copilot/turns/${enc(turnId)}/events${after > 0 ? `?after=${after}` : ""}`,
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
