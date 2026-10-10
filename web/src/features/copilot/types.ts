/**
 * Copilot contract types, taken from the generated OpenAPI schema (docs/COPILOT.md).
 * The server owns every value in these shapes; the UI renders them and never recomputes.
 */
import type { components } from "@/generated/api";

type S = components["schemas"];

export type CopilotAnswer = S["CopilotAnswer"];
export type AnswerBlock = CopilotAnswer["blocks"][number];
export type BlockType = AnswerBlock["type"];
export type BlockOf<T extends BlockType> = Extract<AnswerBlock, { type: T }>;

export type VisualBlock = S["VisualBlock"];
export type VisualColumn = S["Column"];
export type VisualEncoding = S["Encoding"];
export type ChartKind = VisualBlock["chart"];
export type Basis = NonNullable<VisualBlock["basis"]>[number];
export type Citation = S["Citation"];
export type ActionKind = BlockOf<"action">["action"];
export type Row = Record<string, unknown>;

export type TurnStatus = S["TurnView"]["status"];
export type TerminalTurnStatus = Exclude<TurnStatus, "running">;
export type CopilotLanguage = CopilotAnswer["language"];
export type CreatedRef = S["CreatedRef"];
export type SessionSummary = S["SessionSummary"];
export type TurnViewRow = S["TurnView"];

export const TERMINAL_TURN: readonly TerminalTurnStatus[] = [
  "completed",
  "clarification",
  "failed",
  "cancelled",
  "provider_unavailable",
  "budget_exhausted",
];
export const isTerminalTurn = (s: string): s is TerminalTurnStatus => (TERMINAL_TURN as readonly string[]).includes(s);

/** Every chart kind in the server contract; the renderer switch must cover all of them. */
export const CHART_KINDS: readonly ChartKind[] = [
  "kpi",
  "table",
  "bar",
  "grouped_bar",
  "stacked_bar",
  "delta_bar",
  "line",
  "area",
  "scatter",
  "frontier",
  "heatmap",
  "sankey",
  "map",
  "steps",
];

/* ------------------------------------------------------------------ context */

/** copilot/context UIContext (extra="forbid"): only these keys may be sent. */
export interface UIContext {
  pilot_id?: string | null;
  pilot_version?: string | null;
  season_id?: string | null;
  scenario_revision_id?: string | null;
  selected_run_id?: string | null;
  selected_field_id?: string | null;
  timeline_date?: string | null;
  view?: string | null;
  language?: CopilotLanguage;
  units?: "metric";
  ui_revision?: number | null;
}

/** PinnedContext.prompt_view(): the server-resolved context of a turn. */
export interface PinnedContextView {
  pilot_id: string;
  pilot_version: string;
  pilot_name?: string;
  season_id?: string;
  crop?: string;
  scenario_revision_id?: string;
  selected_run_id?: string;
  selected_run_plan_kind?: string;
  selected_run_outcome?: string;
  selected_field_id?: string;
  language?: CopilotLanguage;
  notes?: string[];
}

export interface TurnError {
  code: string;
  detail?: string;
  retryable?: boolean;
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

/* ------------------------------------------------------------------ SSE events (contract.EventType) */

export interface DatasetDescriptor {
  dataset_id: string;
  kind: string;
  title: string;
  rows: number;
  charts: string[];
  call_id?: string | null;
  tool?: string;
}

export interface JobUpdatePayload {
  job_id: string;
  state: string;
  operation?: string;
  state_meaning?: string | null;
  error?: Record<string, unknown> | null;
  run?: { run_id: string; plan_kind?: string; solver_status?: string };
  analysis?: { analysis_id?: string; kind?: string };
  visuals?: VisualBlock[];
}

export type CopilotEvent =
  | {
      type: "turn_started";
      payload: {
        turn_id: string;
        context: PinnedContextView;
        language?: CopilotLanguage;
        badge?: { pilot_id: string; pilot_version: string; run_id: string | null; plan_kind?: string | null; season_id: string | null };
      };
    }
  | { type: "thinking"; payload: { round: number; label: string; elapsed_ms?: number; remaining_s?: number; problems?: number } }
  | { type: "tool_started"; payload: { call_id: string; tool: string; activity: string; semantics?: string; round?: number } }
  | { type: "dataset_ready"; payload: DatasetDescriptor }
  | {
      type: "tool_finished";
      payload: {
        call_id: string;
        tool: string;
        ok: boolean;
        activity: string;
        error?: TurnError | null;
        duration_ms?: number;
        datasets?: string[];
        reused?: boolean;
        job_ids?: string[];
        created?: CreatedRef[];
      };
    }
  | { type: "answer_block"; payload: { index: number; block: AnswerBlock } }
  | { type: "answer"; payload: CopilotAnswer }
  | { type: "view_intents"; payload: { intents: ViewIntent[] } }
  | { type: "error"; payload: TurnError }
  | {
      type: "turn_finished";
      payload: {
        status: TerminalTurnStatus;
        rounds?: number;
        tool_calls?: number;
        latency_ms?: number;
        provider_ms?: number;
        pending_job_ids?: string[];
        error?: TurnError | null;
      };
    }
  | { type: "job_update"; payload: JobUpdatePayload }
  | { type: "jobs_settled"; payload: { pending_job_ids: string[] } }
  | { type: "jobs_cancelled"; payload: { job_ids: string[] } };

export type CopilotEventType = CopilotEvent["type"];
export type CopilotEventEnvelope = CopilotEvent & { event_id: number; turn_id: string; created_at: string };

export const COPILOT_EVENT_TYPES: readonly CopilotEventType[] = [
  "turn_started",
  "thinking",
  "tool_started",
  "dataset_ready",
  "tool_finished",
  "answer_block",
  "answer",
  "view_intents",
  "error",
  "turn_finished",
  "job_update",
  "jobs_settled",
  "jobs_cancelled",
];

/** The stream is over once the turn finished with no pending jobs, or its jobs settled/cancelled. */
export function endsStream(ev: CopilotEventEnvelope): boolean {
  if (ev.type === "turn_finished") return !(ev.payload.pending_job_ids ?? []).length;
  return ev.type === "jobs_settled" || ev.type === "jobs_cancelled";
}
