# AabFlow copilot (F19): backend-to-UI contract

The copilot answers lay questions about the pinned workspace by calling the same `/api/v2`
services as the UI, then returns a validated, visual answer. This document is the contract
the chat UI builds against. The executable contract is the Pydantic models in
`api/aabflow/copilot/contract.py` and `api/aabflow/copilot/visuals.py`, exported in
`contracts/openapi.json` and `web/src/generated/api.ts` (`CopilotAnswer`, `VisualBlock`,
`TurnView`, `CopilotEvent`, `SessionList`).

Status: implemented and unit/route tested with a labelled scripted provider; live smoke runs
with `gpt-6-luna` are in `evidence/copilot/smoke-*.json`. The T11.8 30x3 evaluation has not
been run, so AT17 is **not** passed and `/capabilities` reports the copilot as `partial`
(or `not_available` without a key).

## 1. Routes (all under `/api/v2/copilot`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | `{configured, state: "ready"\|"unavailable", reason, model, prompt_version, tool_schema_version, offline_note}` |
| GET | `/sessions?limit=` | `SessionList`: recent conversations (title = first question) for restore after restart |
| POST | `/sessions` | `{context: UIContext, role}` -> `{session_id, role, status}` |
| GET | `/sessions/{id}` | session with every turn (answer, language, created refs, status, latency) |
| POST | `/sessions/{id}/messages` | `{message, context: UIContext, mode?: "chat"\|"plan"}` -> 202 `{turn_id, events_url, context}` (`mode` defaults to `chat`; see §12) |
| GET | `/turns/{id}` | `TurnView` (`?include_tools=true` adds tool calls and the event log) |
| GET | `/turns/{id}/events` | SSE stream (resume with `Last-Event-ID` or `?after=`) |
| GET | `/turns/{id}/event-log?after=` | the same events as JSON (`CopilotEvent[]`) |
| GET | `/turns/{id}/plan-steps` | the `plan_step` payloads of a plan-mode turn (`PlanStep[]`; empty for chat) |
| POST | `/turns/{id}/cancel` | stop a running turn; jobs it started are cancelled, its view intents dropped |
| POST | `/turns/{id}/retry` | re-run with the original message/context; idempotency keys reuse created objects |

`UIContext` (what the UI is showing when the user sends): `pilot_id, pilot_version,
season_id, scenario_revision_id, selected_run_id, selected_field_id, timeline_date, view,
language ("en"|"ur"|"roman_ur"), units, ui_revision`. The server resolves and **pins** it for the
whole turn (T11.1): IDs that do not belong to the selected pilot are dropped with a visible
note, every tool re-checks membership, and the model cannot switch workspace by inventing IDs.
A message written in Urdu script (or recognisably Roman Urdu) switches the turn language.

Error states on `POST .../messages`: `503 PROVIDER_UNAVAILABLE` (no key / provider cannot be
created), `409 VERSION_CONFLICT` (a turn is still running in the session; payload has
`running_turn_id`), `404` unknown session. Model/provider failures *during* a turn finish the
turn with status `provider_unavailable` and an honest deterministic answer (see 4).

## 2. Turn lifecycle and SSE events

Each event: `{event_id, turn_id, created_at, type, payload}`; SSE `id:` is `event_id`,
`event:` is `type`. The stream ends after `turn_finished` (or after `jobs_settled` when a job
the turn started is still running).

| type | payload | UI use |
|---|---|---|
| `turn_started` | `context` (pinned), `language`, `badge {pilot_id, pilot_version, run_id, plan_kind, season_id}` | show the context badge immediately |
| `thinking` | `round`, `label` ("Reading your question and planning", "Looking at the results", "Writing the answer", "Double-checking the numbers"), `elapsed_ms`, `remaining_s` | working indicator; never show model reasoning |
| `tool_started` | `call_id`, `tool`, `activity` (plain label, e.g. "Running your what-if as a new scenario"), `semantics` (read/create/compute/view), `round` | activity row (spinner) |
| `dataset_ready` | `dataset_id`, `kind`, `title`, `rows`, `charts`, `call_id`, `tool` | optional "data ready" chip under the activity row |
| `tool_finished` | `call_id`, `tool`, `ok`, `activity`, `error {code, detail}`, `duration_ms`, `datasets[]`, `job_ids`, `created[]`, `reused?` | tick or failure state with the error text |
| `answer_block` | `index`, `block` (validated) | render blocks progressively |
| `answer` | full `CopilotAnswer` | final render (replace progressive blocks) |
| `view_intents` | `intents[]` | apply after the turn (see 5) |
| `error` | `{code, detail, retryable}` | provider failure banner with retry |
| `turn_finished` | `status`, `rounds`, `tool_calls`, `latency_ms`, `provider_ms`, `pending_job_ids`, `error` | stop spinner; show latency |
| `job_update` | job state plus the finished run/analysis summary and its `datasets` | a long job finished after the turn |
| `jobs_settled` / `jobs_cancelled` | `pending_job_ids` / `job_ids` | close the stream |
| `plan_step` | plan mode only, right after each `tool_finished`: `PlanStep {step, phase (understand\|test\|decide), label, tool, call_id, ok, run_id?, analysis_id?, report_id?, field_ids[]}` | group the investigation timeline; highlight `field_ids`, show a new `run_id` on the map |

Turn `status`: `running`, `completed`, `clarification` (one focused question is asked),
`failed` (internal error, or `error.code = INTERRUPTED` after a server restart),
`cancelled`, `provider_unavailable`, `budget_exhausted` (90 s / 8 rounds / 12 tool calls /
3 jobs reached; plan mode 240 s / 6 / 20 / 10). `turn_started` and `TurnView` carry the turn `mode`. Prose is never streamed unvalidated; only validated `answer_block`s are sent.

Budget: one model round measured 3-32 s live (median ~10 s), so the prompt asks the model to call
all independent read tools in the first round and answer in the second (typical turn 10-35 s;
a what-if with a regeneration took 63 s). Each hosted call is capped at 40 s; a stalled call is
retried once with a forced `final_answer`. With less than 28 s left the server forces
`final_answer`; at the 90 s limit it writes the honest fallback.

## 3. Answer: `CopilotAnswer`

```json
{
  "language": "en",
  "blocks": [ ...ordered blocks... ],
  "needs_clarification": false,
  "clarification_question": null,
  "validated": true,
  "issues": [],
  "deterministic": false
}
```

Render `blocks` top to bottom. The server orders them: run badges, headline, first
explanation, metric cards, visuals, further text, comparison, caveats, actions, follow-ups.
`validated=false` means something was withheld or dropped (the `issues` list says what; show a
small "some figures were withheld" note). `deterministic=true` means the server wrote the answer
because the model could not finish: show it as a system message, not as the assistant's voice.

| `type` | fields | rendering |
|---|---|---|
| `run_badge` | `role` (`context`\|`created`), `run_id`, `plan_kind`, `solver_status`, `outcome`, `scenario_revision_id`, `pilot_id`, `pilot_version`, `season_id`, `label` | chip: "Plan P · OPTIMAL · run_…"; `created` = new run from this turn. Click opens the run |
| `headline` | `text`, `citations[]`, `withheld` | large first line |
| `text` | `text`, `citations[{ref_id, kind, auto}]`, `withheld` | paragraph; citation chips open run/evidence/analysis |
| `metric` | `metric_id`, `label`, `run_id`, `field_id`, `value`, `unit`, `status`, `reason`, `basis`, `plan_kind`, `solver_status` | metric card; value is server-resolved; show `basis` label (model output / computed from inputs) and `reason` when `status != available` |
| `visual` | see 3.1 | chart/table/map with a table toggle |
| `comparison` | `comparison_id`, `run_ids`, `compatible`, `label`, `deltas[{metric_id, unit, a, b, delta, status}]`, `fields_worse_off` | before/after delta table; "non-matched" warning when `compatible=false` |
| `uncertainty` | `text`, `citations`, `withheld` | caveat callout (warning token + icon; never hidden) |
| `action` | `action` (`open_run`, `open_branch`, `open_field`, `open_report`, `open_analysis`, `open_comparison`), `ref_id`, `label`, `auto` | button that updates the existing workspace; `auto` = created this turn |
| `follow_ups` | `questions[]` | suggestion chips that send the question |

Language: `ur` answers are Urdu script (render RTL with an Urdu-capable font and `dir="auto"`
isolation around Latin IDs, PKR amounts and units); `roman_ur` is Latin script.

### 3.1 Visual blocks

The model never types chart values. Tools register **datasets** (typed columns + rows copied
from service results, with units, basis and source IDs). In `final_answer` the model chooses
`{dataset_id, chart, title, caption, x, y, series, sort, limit, highlight_ids}`; the server
validates the choice against the dataset and builds the block from the stored rows. Datasets
live for one turn only.

```json
{
  "type": "visual",
  "visual_id": "v1",
  "chart": "bar",
  "title": "Production per plan",
  "caption": "The integrated plan grows the most wheat.",
  "dataset_id": "ds1",
  "dataset_kind": "plans_side_by_side",
  "columns": [
    {"key": "plan", "label": "Plan", "label_ur": "منصوبہ", "kind": "category", "unit": null, "unit_column": null, "basis": null, "ref": null},
    {"key": "production_kg", "label": "Crop production", "label_ur": "فصل کی پیداوار", "kind": "number", "unit": "kg", "basis": "model_output", "ref": null, "unit_column": null},
    {"key": "run_id", "label": "Run", "kind": "id", "ref": "run", "unit": null, "label_ur": "رن", "unit_column": null, "basis": null}
  ],
  "rows": [{"plan": "B0 fixed roster", "production_kg": 129701.0, "run_id": "run_…"}],
  "row_count": 4,
  "truncated": false,
  "encoding": {"x": "plan", "y": ["production_kg"], "series": null, "value": null, "label": null,
               "color": null, "source": null, "target": null, "id": "run_id", "status": "solver_status"},
  "highlight_ids": [],
  "source": {"tool": "get_plan_ladder", "call_id": "call_…", "run_ids": ["run_…"], "analysis_ids": [],
             "comparison_ids": ["cmp_…"], "revision_ids": [], "endpoint": "/comparisons"},
  "basis": ["computed_from_inputs", "model_output"],
  "notes": ["matched comparison"],
  "interactions": [{"on": "select_row", "column": "run_id", "intent": "open_run"}],
  "table_fallback": true,
  "auto": false
}
```

Rules for the renderer:

- `null` values are gaps (missing / undeliverable / infeasible), never zero. Draw them as a
  hatched or empty mark with the row's `status`.
- Units come from `columns[].unit`, or per row from `unit_column` (metric cards).
- Always offer the rows as an accessible table (`table_fallback`), and show `notes`, `basis`
  and the source run/analysis IDs in a footer ("Source: run_… · model output").
- `highlight_ids` match an ID column (`ref = field` or `run`): emphasise those marks; for map
  visuals also highlight those fields on the workspace map.
- `interactions` say which column opens which entity when a mark/row/cell is selected.
- `auto: true` = the server added the chart without explanation (fallback answers only).

| chart | encoding used | typical dataset kinds |
|---|---|---|
| `kpi` | `label`, `value`, `status` (`unit_column`) | `run_metrics`, `money_cards`, `sdg_cards` |
| `table` | all columns (or `y` subset + ID columns) | any |
| `bar` / `grouped_bar` / `stacked_bar` | `x`, `y[]`, `series?`, `color?`, `id?` | `plans_side_by_side`, `field_outcomes`, `equity_fields`, `water_by_field`, `cost_by_category`, `irrigation_schedule` |
| `delta_bar` | `x`, `y=[delta]`, `color?` (diverging around 0) | `field_deltas`, `ladder_steps`, `equity_fields` |
| `line` / `area` | `x=date`, `y[]` | `timeline`, sensitivity points |
| `scatter` | `x`, `y[1]`, `color`, `id` | `field_outcomes`, `frontier` |
| `frontier` | `x`, `y[1]`, `color=dominance`, `label`, `id=run_id`, `status` | `frontier` (join nondominated points; infeasible settings shown as status markers) |
| `heatmap` | `x` (column category), `y[1]` (row category), `value`, `status`, `id` | `stress_matrix` (undeliverable cells have `value=null`, status `undeliverable`) |
| `sankey` | `source`, `target`, `value` | `water_flows` (m3) |
| `map` | `id` (field ID), `value` or `color`, `label` | `field_outcomes`, `equity_fields`, `field_deltas`, `water_by_field` |
| `steps` | `label`, `x=start_date`, `value`, `id` | `action_steps` (dated cards: what, when, cost, who, approval) |

## 4. Honest failure behaviour

- No key: `/status.state = unavailable` with `reason`; posting a message returns `503
  PROVIDER_UNAVAILABLE`. The panel must say hosted chat is unavailable and link to saved results
  and controls; it is not an offline assistant.
- Provider fails mid-turn: status `provider_unavailable`, an `error` event, and a
  `deterministic` answer: one caveat saying the answer is incomplete, plus (when tools already
  ran) up to two `auto` visuals of the tool-returned datasets and action buttons for created
  objects. No prose or number is invented.
- A tool fails: the model receives `{ok:false, error:{code, detail}}`; `tool_finished.ok=false`
  carries the code (e.g. `NOT_FOUND`, `CROSS_PILOT_REFERENCE`, `NO_PLAN`, `TURN_JOB_LIMIT`,
  `CAPABILITY_UNAVAILABLE`). The answer must say what could not be done.
- Unsupported figures: prose numbers are checked against this turn's tool results (with
  lakh/crore/million/t/% scaling and written rounding). The model gets one regeneration; then
  offending sentences become a "[figure withheld]" notice, invalid visuals are dropped and a
  caveat is added (`validated=false`).
- Restart: turns left `running` by a dead process are reported `failed` with
  `error.code = INTERRUPTED`; completed turns, answers and visuals are restored from SQLite.

## 5. Navigation and action intents

`navigate_view` produces typed `view_intents` applied after the turn (never mid-turn):
`{target: "pilot"|"field"|"run"|"branch"|"tab"|"date"|"report"|"analysis"|"comparison", pilot_id?,
field_id?, run_id?, scenario_revision_id?, tab?, date?, report_id?, analysis_id?, comparison_id?}`.
A pilot switch applies to the **next** question. Action blocks and visual interactions use the
same targets. Creating a branch never changes the active scenario: "use this plan" selects the
created branch in the UI; the parent stays available.

## 6. Tools (`api/aabflow/copilot/tools/*`)

Every tool declares an argument model (strict JSON schema), semantics, timeout, maximum result
size, allowed roles and a plain activity label (`registry/__init__.py`). Read tools run in
parallel; create/compute tools one at a time with idempotency keys from turn + arguments.

| Tool | Wraps | Semantics | Datasets |
|---|---|---|---|
| `get_context` | pinned context, revision runs, presets, capabilities | read | - |
| `inspect_field` | `/fields/{id}`, run field metrics, daily timeline | read | - |
| `inspect_run` | `/runs/{id}`, `/coverage` | read | `run_metrics`, `field_outcomes` |
| `compare_runs` | `POST /comparisons` | read (derived) | `plans_side_by_side`, `field_deltas` (+`ladder_steps`) |
| `get_plan_ladder` | revision runs + `POST /comparisons` (B0/B1/P/R) | read (derived) | `plans_side_by_side`, `field_deltas` (B0 -> P), `ladder_steps` |
| `read_analysis` | `/analyses`, `/analyses/{id}` (latest frontier/stress/... of the scenario) | read | `frontier`, `stress_matrix`, `*_points` |
| `water_accounting` | `/runs/{id}/accounting` | read | `water_flows`, `water_by_field` |
| `economics` | `/runs/{id}/economics` | read | `money_cards`, `cost_by_category` |
| `equity` | `/runs/{id}/equity?baseline_run_id` (default B0) | read | `equity_fields`, `equity_groups` |
| `impact_sdg` | `/runs/{id}/impact` (+ latest stress) | read | `sdg_cards` |
| `action_plan` | `/runs/{id}/action-plan` | read | `action_steps`, `irrigation_schedule` |
| `field_timeline` | `/runs/{id}/timeline` | read | `timeline` |
| `explain_decisions` | `/runs/{id}/explanations` | read | `decisions` |
| `methodology` | `/metrics/definitions`, `/evidence/search`, pilot review flags | read | - |
| `search_evidence` | `/evidence/search` | read | - |
| `get_job_result` | `/jobs/{id}` (+ result) | read | per result |
| `run_what_if` | branch -> solve -> compare (one call) | create | `plans_side_by_side`, `field_deltas` |
| `branch_scenario` | `POST /scenarios/{id}/revisions` (+ optional solve) | create | - |
| `solve_scenario` | `POST /scenario-revisions/{id}/solve` | compute | - |
| `evaluate_alternative` | `POST /analyses/why-not` (eligibility first) | compute | `why_not_points` |
| `run_stress_test` | `POST /analyses/stress` | compute | `stress_matrix` |
| `build_frontier` | `POST /analyses/frontier` | compute | `frontier` |
| `analyze_sensitivity` | `POST /analyses/sensitivity` | compute | `sensitivity_points` |
| `analyze_synergy` | `POST /analyses/synergy` | compute | `synergy_points` |
| `preview_policy` | `/surrogate/previews` (+ exact confirmation) | compute | - |
| `create_report` | `POST /reports` | create | - |
| `navigate_view` | typed UI intent | view | - |

Viewer role: read and view tools only. No tool exposes SQL, files, shell, network, messaging,
purchases, irrigation control or edits to rights/sources/provenance.

## 7. Persistence

Tables `copilot_sessions`, `copilot_turns` (pinned context, answer, language, timings, model,
prompt/tool-schema versions, provider request IDs), `copilot_events` and `copilot_tool_calls`
live in `schema.sql` (schema v4: v3 added the copilot tables, v4 the turn `mode` column; v2 and v3
databases are upgraded in place). Anything that looks like
an API key is redacted before it is written. `timings` = `{provider_calls[{round, latency_ms,
calls, usage, forced_final}], tools[{tool, call_id, round, ms, status}], total_ms, provider_ms,
tool_ms}`.

## 8. Example (abridged) turn

User (pinned to pilot-a, run P): "What if we only had 10 lakh rupees to spend instead?"

Events: `turn_started` -> `thinking("Reading your question and planning")` ->
`tool_started(run_what_if, "Running your what-if as a new scenario")` -> `dataset_ready(ds1
plans_side_by_side)` -> `dataset_ready(ds2 field_deltas)` -> `tool_finished(ok, 10 s)` ->
`thinking("Looking at the results")` -> `answer_block` x N -> `answer` -> `turn_finished`.

Answer blocks: `run_badge(context, P)`, `run_badge(created, P, OPTIMAL)`, `headline`, `text`,
`metric(production_kg, new run)`, `visual(bar, plans_side_by_side)`, `visual(delta_bar,
field_deltas, highlight tail fields)`, `comparison`, `uncertainty` (assumed costs, finite
library), `action(open_branch)`, `action(open_run)`, `action(open_comparison)`, `follow_ups`.

## 9. Live smoke (`evidence/copilot/smoke-20261010T131112Z.json`)

Seven `gpt-6-luna` turns on real pilot-a wheat 2027-28 runs (B0/B1/P/R, fixed-plan stress,
6-point frontier solved first in the same process):

| Case | Question | Status | Wall | Tools | Visuals |
|---|---|---|---|---|---|
| S1 | best plan, keep it simple | completed | 33.1 s | get_plan_ladder, action_plan | bar, steps |
| S2 | only 10 lakh to spend | completed (1 regeneration) | 62.8 s | run_what_if (new OPTIMAL run) | table |
| S3 | dry year / canal cut robustness | budget_exhausted | 90.1 s | get_context, read_analysis, inspect_run | heatmap, kpi (auto) |
| S4 | which farmers lose out | completed | 16.7 s | get_context, equity, read_analysis | grouped_bar, map |
| S5 | Urdu: canal closed two weeks | completed (Urdu) | 18.1 s | run_what_if (interruption-14d-v1) | grouped_bar |
| S6 | compare with a nonexistent run | completed (tool NOT_FOUND reported) | 13.6 s | get_context, compare_runs | - |
| S7 | where does the water go | completed | 9.6 s | water_accounting | sankey, stacked_bar |

S3's second hosted call stalled past the remaining budget; the turn ended with the honest
fallback (server-built heatmap of the saved stress test, no prose). The 40 s per-call cap with
one forced-final retry was added after this run (`test_stalled_provider_call_is_retried_once_for_the_answer`).
Re-measured live once (`evidence/copilot/smoke-20261010T141112Z.json`): S3 completed in 21.0 s,
3 rounds (4.2 s + 10.5 s + 5.3 s); the middle round was a regeneration because the model put
the measured value in `y` of a heatmap, which the server now accepts as the colour value.

## 10. Chat UI (`web/src/features/copilot`)

| File | Role |
|---|---|
| `index.ts` | Exports `CopilotPanel` (mounted by the assistant slot) and `CopilotLauncher` |
| `types.ts` | Contract types from `generated/api.ts`, typed SSE event union, `endsStream` |
| `api.ts` | Client for the routes in §1 (+ deterministic `/runs/{id}/explanations`) |
| `stream.ts` | SSE with event-log catch-up, resume from the last event id, backoff, polling fallback, buffered-proxy watchdog |
| `conversation.ts` | Zustand store per pilot; pure `applyEvent` reducer over every event type; send/retry/cancel/restore/openSession |
| `blocks.tsx` | Exhaustive `BlockView`; `AnswerView` layout (badges, headline, text, metric strip, visuals, caveats, actions, follow-ups); RTL for Urdu |
| `visual.tsx`, `charts.ts` | Visual card (chart/data twin, copy TSV, expand, show on map, source footer, error boundary); pure ECharts option builders; SVG field map with canals; dated steps; metric cards |
| `nav.ts` | Citations, actions, chart clicks and view intents → `useAppActions` (open run/analysis/compare, select/highlight fields) |
| `suggestions.ts` | Starter questions by screen, run and field (always one Urdu example) |
| `TurnCard.tsx`, `CopilotPanel.tsx` | Live progress steps, honest terminal states with retry, background-job visuals, composer, language switch, history, offline state |

Rules kept in the UI: values are only formatted (`lib/formatting`), never computed; `null` is a
gap; bar/line columns with different units become small multiples (no second axis); at most four
categorical colours in the validated order series-1, -2, -4, -3 (slots 5 and 6 of the design
palette fail colour-vision separation). Checks: `web/src/features/copilot/*.test.ts(x)` (labelled
fixtures copied from the live smoke transcript), `tests/e2e/journey-copilot.spec.ts` (one live
question through the UI) and `tests/e2e/a11y-copilot.spec.ts` (recorded answers, axe and
screenshots of every chart kind at desktop and mobile).

## 11. Verification

- `tests/copilot/*`: scripted-provider (labelled fixture) tests for the tool loop, schemas,
  number tracing, visual materialization, context pinning / ID injection, failures, events,
  language, persistence and the schema upgrade.
- `scripts/copilot_smoke.py`: a handful of live `gpt-6-luna` turns on the real pilot data;
  writes `evidence/copilot/smoke-<UTC>.json` with timings. Not the 30x3 evaluation.
- `scripts/copilot_eval.py`: the T11.8 30-case x 3 evaluation (required for AT17; not yet run).

## 12. Plan mode ("Plan my season", WIN_PLAN P2)

`POST /sessions/{id}/messages` with `mode: "plan"` runs one full planning investigation on the same
engine (no new job system). Differences from chat:

- **Limits** `PLAN_LIMITS`: 6 rounds, 20 tool calls, 10 new jobs, 240 s wall, 40 s per hosted call.
  Override in tests with `state.extras["copilot_plan_limits"]` (chat keeps `copilot_limits`).
- **Recipe** `prompts.PLANNER_INSTRUCTIONS` is appended to the instructions (prompt
  `copilot-prompt-2.2.0`): round 1 understand and baseline (context, ladder, what-if P [+ R for a dry
  year], saved analyses); round 2 test it (6-point frontier around the budget, fixed-plan stress
  test, why-not for named interventions, equity vs B0); round 3 decide by rule (R if every stress cell
  is deliverable and robustness was asked; else the P run meeting the service floor; say so when
  nothing meets it), `create_report` + `action_plan`, then `final_answer` in the brief layout
  (headline, kpi metrics, frontier, stress heatmap, equity table, dated steps, caveats, actions, 3
  follow-ups).
- **Concurrency**: a round's read and compute tools (frontier, stress, why-not) run concurrently;
  `create` tools (what-if, report) still run one at a time.
- **`plan_step` events** after each `tool_finished` (see §2). `run_id`/`analysis_id`/`report_id` are
  objects that call created (attributed by call, not by timing); `field_ids` are the fields its result
  names (`fields_worse_off`, `lowest_service_fields`, targets), at most 40.
- **Layout guard** `answer_validation.apply_plan_layout`: for each required part the validated
  answer lacks (kpi, frontier, stress, equity, steps, caveats, actions, follow-ups) one uncertainty
  block is inserted before the actions, e.g. "The stress test (weather x supply heatmap) was not
  completed within the time budget." (`budget_exhausted`), "... could not be completed in this
  investigation." (failed / provider unavailable) or "... is not part of this brief." (completed).
  With no caveat at all, the four standard method caveats are added verbatim. Nothing is invented: a
  missing chart stays missing. A budget-exhausted plan turn shows up to 4 server-built visuals of the
  results its tools already returned.
- **Saved investigation**: `scripts/seed_demo_session.py --plan-goal "<sentence>"` (or
  `--plan-only --plan-goal ...` on an existing manifest, nothing re-solved) runs one plan turn on the
  seeded base revision and P run and stores `plan_turn_id`, `plan_goal` and `plan_computed_at` in
  `data/demo/session.json`; `GET /demo/session` serves them. Only a `completed` turn is recorded.
- **UI** (`web/src/features/planner`): route `/p/:pilot/:version/plan-season?turn=<id>&goal=<text>`.
  A finished `?turn=` replays its event log at 3x (instant with reduced motion), labelled "Saved
  investigation · computed <server time>", with "Run it live" (new session, same goal, plan mode,
  live SSE). `?goal=` without a turn starts live at once. A live failure shows its real status and
  error, never the saved brief.
- **Tests**: `tests/copilot/test_plan_mode.py` (limits, recipe only in plan mode, layout-guard caveats,
  `plan_step` events and route, chat unchanged, retry keeps the mode, wall-budget exhaustion gives an
  honest partial brief), `web/src/features/planner/*.test.ts`, `tests/e2e/journey-plan.spec.ts`
  (saved replay + one live goal; run live by the integrator).

