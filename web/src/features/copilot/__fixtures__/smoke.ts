/**
 * TEST FIXTURE (tests only): answers copied verbatim from the live gpt-6-luna smoke run on real
 * pilot-a data (evidence/copilot/smoke-20261010T131112Z.json). Labelled; never rendered in the app.
 */
import raw from "./smoke.json?raw";
import type { CopilotAnswer, CopilotEventEnvelope, CreatedRef, VisualBlock } from "../types";

export interface SmokeTurn {
  case: string;
  message: string;
  turn_id: string;
  status: string;
  language: string;
  latency_ms: number;
  rounds: number;
  error: { code: string; detail?: string } | null;
  created_refs: CreatedRef[];
  event_types: string[];
  answer: CopilotAnswer;
  tools: { tool: string; status: string; error: unknown }[];
}

export const SMOKE = JSON.parse(raw) as { _fixture: string; turns: Record<string, SmokeTurn> };

export function smokeVisuals(caseId: string): VisualBlock[] {
  return SMOKE.turns[caseId].answer.blocks.filter((b): b is VisualBlock => b.type === "visual");
}

/** A labelled synthetic event sequence for one smoke turn, built from its recorded answer. */
export function smokeEvents(caseId: string): CopilotEventEnvelope[] {
  const t = SMOKE.turns[caseId];
  const evs: Omit<CopilotEventEnvelope, "event_id" | "turn_id" | "created_at">[] = [
    { type: "turn_started", payload: { turn_id: t.turn_id, context: { pilot_id: "pilot-a", pilot_version: "reviewed-v1" }, language: t.answer.language } },
    { type: "thinking", payload: { round: 1, label: "Reading your question and planning" } },
    ...t.tools.flatMap((x, i) => [
      { type: "tool_started" as const, payload: { call_id: `c${i}`, tool: x.tool, activity: `Running ${x.tool}`, semantics: "read" } },
      { type: "tool_finished" as const, payload: { call_id: `c${i}`, tool: x.tool, ok: x.status === "succeeded", activity: `Running ${x.tool}`, duration_ms: 12 } },
    ]),
    { type: "thinking", payload: { round: 2, label: "Looking at the results" } },
    ...t.answer.blocks.map((block, index) => ({ type: "answer_block" as const, payload: { index, block } })),
    { type: "answer", payload: t.answer },
    { type: "turn_finished", payload: { status: t.status as "completed", rounds: t.rounds, latency_ms: t.latency_ms, pending_job_ids: [] } },
  ];
  return evs.map((e, i) => ({ ...e, event_id: i + 1, turn_id: t.turn_id, created_at: "2026-10-10T13:11:12Z" }) as CopilotEventEnvelope);
}
