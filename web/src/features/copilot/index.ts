/**
 * Public surface of the copilot feature (docs/UI_SYSTEM.md §7): the assistant slot mounts
 * `CopilotPanel`; `CopilotLauncher` is an optional "Ask AabFlow" button for other surfaces.
 */
export { CopilotPanel } from "./CopilotPanel";
export { CopilotLauncher } from "./CopilotLauncher";
// The validated-answer renderer, shared with the "Plan my season" brief (features/planner).
export { AnswerView, type BlockContext } from "./blocks";
