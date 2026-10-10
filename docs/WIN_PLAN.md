# AabFlow: the shortest path to winning (execution plan for one agent)

**Read first:** `CLAUDE.md`, `docs/PITCH.md` (story and numbers), `docs/UI_SYSTEM.md` (the "Furrow & Flow" design system, the assistant slot and the guided tour), and `docs/COPILOT.md` (the copilot contract).
**Goal:** make the AI visibly central and the demo unforgettable for non-expert judges, in **≈7 agent-hours**, by reusing what already exists. The order is chosen so that stopping at any phase boundary still leaves a better demo than before.

---

## 0. Ground rules (non-negotiable)

1. **Base branch.** Start from the integration branch once `feat/ui-rebuild` and `feat/copilot-ui` have both been merged into it. Check with `git log --oneline | grep -E "ui-rebuild|copilot-ui"`. If either is missing, **stop and ask the parent**; do not rebuild their work. Create the branch `feat/win-path`. Use merge commits only: no rebase, no force-push, never commit to `main`.
2. **Docker only.** Run everything through `docker compose run --rm --no-deps api|web …` or the Make targets. Never install on the host and never read `.env`.
3. **Real data only.** Every number on screen comes from the server (a stored metric, run, analysis or evidence record). **The browser never computes metrics.** If a sentence needs a derived number (a delta, a percentage), compute it **in Python on the server** from stored metrics and return it with its unit and source run IDs.
4. **Saved means labelled.** Saved demo results are ordinary stored runs, opened through the normal API and labelled "Saved result · run … · computed <time>". A failed live action shows its real error, never a canned success. Users can leave the tour at any time and use everything live.
5. **Never claim:** AT17 (the 30×3 copilot evaluation) as passed, or calibrated yields, measured water rights or measured costs.
6. **Keep these green:** `make test`, `docker compose run --rm --no-deps web npm run typecheck`, `… npm run test`, `… npm run build`, `… npm run typecheck:e2e`, and `make lint`. If you change an API: run `make contracts` and commit both generated files.
7. **Commits.** One per work item, each message ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Update a `docs/STATUS.md` row only with evidence.
8. **The dev API reloads on every `.py` edit.** Don't edit Python while a live Playwright run or a seed is in progress.

**Timebox discipline.** Every item has a timebox and a **cut line** (the minimum that still ships). When the timebox expires, ship the cut line, note it in the final report and move on.

---

## 1. Phase map

| Phase | Items | Time | What stopping here still gives you |
|---|---|---|---|
| **P0: base** | Preflight and seed | 20 min | A working demo session |
| **P1: AI visible** | W1 headline · W2 "AI inside" · W5 Ask box | ~2 h | Judges see within 10 seconds that AI is the core and why it matters |
| **P2: big one** | **BIG: "Plan my season"** | ~3 h | AI runs the whole planning investigation from one sentence |
| **P3: magic moments** | W3 AI reveal · W4 instant crop slider · W6 print · W7 USD | ~1.5 h | The wow beats in the tour |
| **P4: safety** | W8 seed/cold start/recording · rehearsal | ~45 min | A demo that can't fail on stage |

**Total ≈ 7–7.5 h.** If two agents are available, split it: Agent A takes W1–W8 (it owns `web/src/features/landing|tour|impact`, `web/src/components/**` and `api/aabflow/api/demo*`). Agent B takes BIG (it owns `api/aabflow/copilot/**`, `web/src/features/copilot/**` and the new `web/src/features/planner/**`). Agent A merges first. With two agents it's about 4 h.

---

## P0: preflight (20 min)

1. Bring the stack up: `make up`. Then check `curl -s localhost:8000/api/v2/health` (expect `schema_version` "3"). Check `/api/v2/capabilities`: the copilot should report `partial` when the key is configured.
2. Run `make demo-seed` (`scripts/seed_demo_session.py`). It writes `data/demo/session.json`. Then `curl -s localhost:8000/api/v2/demo/session` must report `complete: true`.
3. Fix the two known loose ends from the copilot agent:
   - Add `journey-copilot.spec.ts` and `a11y-copilot.spec.ts` to `web/tsconfig.e2e.json`.
   - Fix the impact empty-state vitest. The checkpoint renamed the text "Impact needs a run" to "Impact needs a plan", so update the test to the new copy.
4. Commit: "Preflight: e2e tsconfig and impact empty-state copy."

---

## P1: make the AI visible (~2 h)

### W1. The headline insight (45 min)

**Why.** The single strongest story line is in `docs/PITCH.md` §1: "just optimise what we have" can quietly hurt the tail farmer, while the integrated plan grows more *and* is fairer *and* is cheaper than the budget. It must be the first thing anyone sees, and its numbers must be real.

**Backend** (`api/aabflow/api/demo.py`, the route the UI agent added; read it first):
- Add `GET /api/v2/demo/headline`, or embed a `headline` object in `GET /demo/session`; pick one and keep it simple. Build it from the session's B0/B1/P run IDs using stored metrics only (`services.runs.load_run(...).metrics()`). Metrics: `production_kg`, `tail_min_service_ratio`, `capital_commitment_pkr`, `groundwater_m3`, plus the scenario's `capital_budget_pkr`.
- Compute in Python and return each value with `{value, unit, run_id}`:
  - `production_gain_pct_vs_b0` for B1 and P;
  - `tail_service_change_pts` for B1 and P vs B0;
  - `budget_used_fraction` = P capital ÷ budget.
- Return a `story` key chosen by rules, so the copy always matches the data:
  - `"tail_tradeoff"` if B1's tail service is lower than B0's and P's tail service is higher than B1's;
  - `"budget_efficiency"` if P uses ≤ 50% of the budget;
  - otherwise `"plain_gain"`.
- Test in `tests/unit/test_demo_headline.py` with labelled tmp fixtures, covering each story key and a missing-run 404. Then `make contracts`.

**Frontend:**
- Add `features/landing/HeadlineInsight.tsx`, a hero card on `Landing.tsx` above the watercourse cards. It has one sentence per `story` key and three `MetricTile`s (production, tail service, capital used) with server values and their run badges. Add a "See how" button that starts the tour.
- Reuse the same component in tour step `welcome` (`features/tour/steps.tsx`).
- Copy for `tail_tradeoff`: *"Optimising only what exists grew {B1 gain}% more wheat but cut the worst-off tail field from {B0 tail}% to {B1 tail}% of its water. AabFlow's plan: +{P gain}% wheat, tail at {P tail}%, using {budget used}% of the budget."*
- Mention groundwater honestly in a secondary line if P pumps more than B0.

**Accept when:** the landing page shows the card with real numbers and run IDs, vitest covers all three story keys, and nothing is hard-coded.
**Cut line:** a single story template (`plain_gain`) with the three tiles.

### W2. "AI inside": four engines, one strip (60 min)

**Why.** It answers the competition requirement ("AI is the core") in five seconds, with proof one click away.

**Backend:** add `GET /api/v2/ai-stack`, read-only, cached in memory at startup, file reads only. Return four entries, each `{id, label, plain, fact, fact_value, unit, evidence_ref, status}`:

| id | label | plain | fact source |
|---|---|---|---|
| `sees` | Sees | "AI finds every field from satellite images" | `data/pilots/<id>/<ver>/review_log.json` → `summary.raw_polygons`, `summary.selected` (summed over published pilots; pilot-a 931 → 30, pilot-b 303 → 30), model = Delineate Anything, checkpoint from the pilot manifest |
| `predicts` | Predicts | "A model we trained predicts crop yield in milliseconds" | `data/models/<latest>/evaluation.json` (nMAE per crop, training device), `evidence/benchmarks/p04-preview-timing.json` → `preview.elapsed_ms_after_load` (6.8 ms), experiment count = number of dirs in `data/experiments` |
| `plans` | Plans | "An AI planner searches thousands of combinations and proves the best one" | latest non-analysis P run: `solver_status`, `relative_gap`, candidate policy count from its library `library.json` |
| `explains` | Explains | "Ask in English or Urdu; it runs the real tools and shows its work" | registry `tools_for_role("planner")` count, `configured_model()`, copilot status |

Missing sources return `status: "unavailable"` with a reason; never a default number. Add a unit test with tmp fixtures, then `make contracts`.

**Frontend:** add `components/layout/AiStackStrip.tsx`, four compact cards with an icon, label, one plain sentence and a big fact. Place it:
- on the landing page under the headline;
- in the top-bar menu as "How the AI works" (a popover listing the same four).

Each card links to its proof:
- `sees` → the Plan map with raw AI fields on (`useUI().showRawFields = true`);
- `predicts` → What if › Surrogate preview;
- `plans` → the run's solver badge;
- `explains` → open the assistant.

**Accept when:** the strip renders live facts, every link lands on the right screen, and vitest passes.
**Cut line:** the landing strip only, without the top-bar popover.

### W5. Ask box as the front door (45 min)

**Why.** For laymen, the assistant *is* the AI. Put it on the first screen, with questions that answer fast.

- On `Landing.tsx`, add a large input "Ask AabFlow anything…" with three chips. One of them must be Urdu.
  - The chips use the demo session IDs, so the copilot's `read_analysis` reuses the saved frontier and stress results and answers in about 10–25 s.
  - Suggested chips: "Is the integrated plan fair to tail farmers?", "What happens in a dry year with a water cut?", "اگر نہر دو ہفتے بند رہے تو کیا ہوگا؟"
- Submitting navigates to `/p/pilot-a/<version>/workspace?run=<demo P run>` and calls `useAppActions().openAssistant()`. It hands the question to the copilot through a small store field (e.g. `useUI().assistantDraft = {text, autoSend: true}`) that `CopilotPanel` reads once.
  - That reader goes inside `features/copilot`, so if you are Agent A, coordinate with the copilot owner or add only a 5-line consumer.
- **Accept when:** a click on a chip produces a live answer with a chart (check once by hand or via `journey-copilot.spec.ts` extended with a "from landing" case).
- **Cut line:** chips that only open the assistant with the question prefilled, with no auto-send.

---

## P2: BIG, "Plan my season" (~3 h)

**What.** One sentence, e.g. *"We have ₨10 lakh. Don't hurt the tail farmers, and make sure it survives a dry year."* The copilot runs a full planning investigation with real tools, streams each step, moves the map, and ends with a one-page decision brief plus a printable report.

**Why this is the shortest path.** The copilot engine already does nearly everything:
- **The turn loop:** `api/aabflow/copilot/orchestrator.py` `Turn`, with `TurnLimits`.
- **27 tools that wait for their jobs on the server:** `ToolCtx.wait_job`, up to 45 s each. These include `run_what_if`, `build_frontier`, `run_stress_test`, `evaluate_alternative`, `read_analysis`, `get_plan_ladder`, `equity`, `create_report` and `action_plan`.
- **Server-built visuals and number tracing:** `visuals.py`, `datasets.py`, `answer_validation`.
- **SSE events with plain activity labels,** saved turns and an event-log replay.
- **A chat UI** that renders every block type.

So BIG = a **planner mode** on the same engine (bigger limits plus a recipe prompt plus a brief layout check), and **one new screen** that shows the run as a story. No new job system.

### B1. Backend (75 min)

1. **Mode flag.** In `copilot/router.py` `MessageIn`, add `mode: Literal["chat", "plan"] = "chat"`. Thread it through `_start_turn` → `Turn(...)` and store it on the turn row (`store.py`). If you change `schema.sql`, bump `schema_version` and add an in-place upgrade like the existing v2 → v3 one.
2. **Plan limits.** Use `PLAN_LIMITS = TurnLimits(max_rounds=6, max_tool_calls=20, max_jobs=10, wall_s=240.0, provider_call_s=40.0)` when `mode == "plan"`. Leave the chat limits unchanged.
3. **Recipe prompt.** Add `PLANNER_INSTRUCTIONS` to `copilot/prompts.py`, appended by `build_instructions` when the mode is `plan`, and bump `PROMPT_VERSION`. The recipe, with independent calls made in parallel within each round:
   - **Round 1. Understand and baseline (parallel):** `get_context`; `get_plan_ladder` for the pinned revision; `run_what_if` with the user's budget, service floor and shortage translated into revision changes, solving **P** (and **R** if the user asks for robustness or a dry year); `read_analysis` for any saved frontier or stress on this revision.
   - **Round 2. Test it (parallel):**
     - `build_frontier` around the user's budget: 6 settings at 0, 25%, 50%, 100%, 150% and 300% of the budget; if the user mentions fairness, make one of them carry a tail service floor.
     - `run_stress_test` (fixed plan) on the what-if P run, plus the R run if it exists.
     - `evaluate_alternative` (why-not) for any intervention the user names.
     - `equity` for the what-if P run vs B0.
   - **Round 3. Decide and write up:** choose the recommendation **by rule**:
     - prefer R if every stress cell is deliverable and the user asked for robustness;
     - otherwise prefer the P run that meets the service floor;
     - say explicitly if nothing meets it (an infeasible point is an honest answer).
     Then call `create_report` for the recommended run and `final_answer`.
   - **The final answer must have this layout,** in order:
     1. headline recommendation (one sentence);
     2. `kpi` blocks for production, tail service, capital and groundwater;
     3. the `frontier` chart;
     4. the stress `heatmap`;
     5. the equity `table`;
     6. dated action `steps`;
     7. caveats (assumed rights and costs, uncalibrated crop model, finite candidate set, worst case only within the tested states);
     8. buttons: open the recommended run, open the report, compare with B0;
     9. 3 follow-up suggestions.
4. **Layout guard.** Add a function in `answer_validation` that checks the plan-mode answer for the required block kinds. For each missing one, add a caveat ("Stress test not completed within the time budget") rather than inventing content.
5. **Step events for the map.** After each `tool_finished` in plan mode, emit `view_intents` immediately (today they are sent after the turn) with `highlight_fields` for affected fields (equity losers, a forced intervention's targets) and `open_run`/`open_analysis` for new IDs. If immediate intents are hard, emit a new `plan_step` event `{step, label, run_id?, analysis_id?, field_ids?}`, document it in `docs/COPILOT.md` and add it to the OpenAPI export.
6. **Warm path.** Extend `scripts/seed_demo_session.py` with `--plan-goal "<sentence>"`. It posts one plan-mode turn and waits for it to finish. It stores `plan_turn_id` and `plan_goal` in `data/demo/session.json`. `GET /demo/session` exposes them.
7. **Tests** (`tests/copilot/test_plan_mode.py`) with the labelled scripted provider:
   - the limits are applied;
   - the recipe prompt is included;
   - the layout guard adds caveats for missing blocks;
   - `plan_step`/intent events are emitted;
   - chat mode is unchanged;
   - a 240 s budget exhaustion produces an honest partial brief.

### B2. Frontend (75 min): `web/src/features/planner/`

1. **Entry points.**
   - A big "Plan my season" card on the landing page, next to the Ask box. It has a goal textarea and three example goals as chips (budget / fairness / dry year).
   - A "Plan my season" button in the Plan screen's top-bar menu.
   - The route `/p/:pilot/:version/plan-season?turn=<id>`. Add it to `App.tsx`. Keep it out of the 5-step journey nav, or add it as a top-bar action.
2. **Screen** (`PlanSeasonScreen.tsx`), three columns on wide screens and stacked on mobile:
   - **Left: the investigation timeline.** One row per `tool_started`/`tool_finished` with its plain `activity` label, a spinner then a tick or failure, and its duration. Group the rows under the three phase headings "Understanding your goal", "Testing it", "Deciding". Animate entries (reduced-motion aware).
   - **Centre: the map** (`MapSlot`), reacting to `plan_step` events/intents: highlight fields, fly to the affected area, show the new run's yield colours when `open_run` arrives.
   - **Right / below: the brief,** rendered with the copilot's existing block renderer (import it from `features/copilot`; don't fork it). Below it: "Open the action plan" (report), "Print brief" (W6) and "Ask a follow-up" (opens the assistant with the same session).
3. **Saved replay.** If `?turn=` points to the seeded `plan_turn_id`, replay `GET /copilot/turns/{id}/event-log` at 3× speed, with the label "Saved investigation · computed <time>" and a **"Run it live"** button that posts a new plan-mode message with the same goal.
4. **Tour step.** Insert step `plan-season` after `stress` in `features/tour/steps.tsx`. It opens the saved replay and has a "Try your own goal" action.
5. **Tests.** Vitest for the timeline reducer (events → rows, phases, failures) and for saved vs live labelling. Add `tests/e2e/journey-plan.spec.ts`: replay the saved investigation (fast, deterministic), then run **one live** goal and assert a brief with at least a kpi block, a run badge that resolves via `/api/v2/runs/{id}`, and no console errors. Run it live **once** at desktop-1920.

**Accept when:**
- one live goal finishes inside 240 s with a recommendation;
- the frontier and stress visuals and a report link appear;
- every number passes validation;
- the saved replay runs offline from the stored event log.

**Cut lines, in order:**
1. drop the live map reaction (map shows the final run only);
2. drop the 3-column layout and render the plan inside the assistant panel with a timeline header;
3. drop the report step (brief only).

**Never cut:** honest partial-completion caveats.

---

## P3: magic moments (~1.5 h)

### W3. The AI reveal: 931 → 30 fields (30 min)
- In tour step `fields`:
  1. Turn on `showRawFields` (the `MapSlot` toggle already exists, so wire the step to it).
  2. Show a counter with the `sees` numbers from `/ai-stack`.
  3. After 2.5 s, fade the raw outlines to the 30 reviewed fields (CSS opacity transition on the raw layer via the map's paint property; reduced motion means instant).
  4. Show the text: *"AI found {raw} possible fields in this satellite image. Our review rules kept the {selected} clearest, and a person checked them. Rights and costs are still assumptions, and they're labelled."*
- **Cut line:** a static toggle with the counter.

### W4. Instant crop slider (40 min)
- In What if › Surrogate (`features/explore/Surrogate.tsx`), add a single **irrigation amount** slider (or "number of irrigations"). It fires `POST /api/v2/surrogate/previews`, debounced to 150 ms, and shows the preview yield with its domain status and the measured `elapsed_ms`.
  - Then add a **"Confirm with exact science"** button that calls `POST /api/v2/surrogate/previews/{preview_id}/verify` (a job; poll it) and shows both side by side, labelled *preview (AI estimate)* vs *exact (crop model)*.
- Add tour step `instant-crop` after `replay`.
- **Cut line:** the slider without the tour step.

### W6. Print-ready brief (20 min)
- Make sure the report screen's "Print / PDF" produces one clean page for the hero run (print CSS: hide the nav, fit the tables).
- Add `scripts/print_brief.mjs`, run in the e2e image: Playwright `page.pdf` of `/p/.../report?run=<demo P>` → `evidence/print/brief-<UTC>.pdf`. Add `make print-brief`.
- **Cut line:** print CSS only.

### W7. USD for judges (20 min)
- Add server settings `AABFLOW_USD_PER_PKR` and `AABFLOW_USD_RATE_DATE` (env with no default). When set, `/capabilities` exposes `{usd_per_pkr, rate_date, source}`; otherwise nothing.
- The money formatter appends "≈ US$ X" only when the rate is present, with a tooltip "display conversion at {rate} on {date}". This is display-only unit conversion of a server value, and it's labelled.
- **Cut line:** skip it if the rate's source isn't confirmed by the team.

---

## P4: safety nets (45 min)

### W8. Make the demo un-failable
1. **Cold start:** `make down && time make demo`. Record the time to first healthy response and the time to first tour step in `evidence/benchmarks/cold-demo-<UTC>.json`.
2. **Recording:** run the tour through Playwright with `video: "on"` (a separate config `web/playwright.record.config.ts`) and save it to `evidence/rehearsal/tour-<UTC>.webm`. Burn in or overlay the label **"RECORDED"**; it is the fallback only.
3. **Offline beat (optional, 10 min):** with the demo image, block the network (`docker network disconnect`) and show a re-solve still works. Say "the copilot needs the internet; planning doesn't." Don't claim AT15 passed from this; it's a rehearsal check.
4. **Final run:** the full `journey-stage`, `journey-tour`, `journey-plan` and `journey-copilot` specs **once each** at desktop-1920 against `make demo`. Then rebuild the pack with `make evidence-pack`.
5. **Rehearsal sheet:** update `docs/PITCH.md` §8 with the final click path, the seeded goal sentence and the exact numbers the seeded session produced (copy them from the API, not from memory).

---

## 2. Definition of done (checklist for the final report)

- [ ] The landing page shows the headline insight (real numbers and run IDs), the AI-inside strip, the Ask box and the Plan-my-season card.
- [ ] The tour covers: welcome → AI reveal → plans → budget → replay → instant crop → frontier → stress → **plan my season (saved replay)** → impact → report → trust → finish. Every step is labelled "saved", and "Try it" works.
- [ ] One live "Plan my season" goal completes in ≤ 240 s, with the frontier, stress, equity, steps and report link, and all numbers validated.
- [ ] One live Urdu question answers in Urdu with a chart.
- [ ] Print brief PDF, cold-start timing and the RECORDED fallback video are saved under `evidence/`.
- [ ] `make test`, `make lint`, and web typecheck / vitest / build / e2e typecheck all pass. Each live spec has been run once.
- [ ] The `docs/STATUS.md` rows touched are updated with evidence paths. AT17 is untouched.
- [ ] Final report: the branch, commits, what was cut (by cut line), and the measured latencies.

## 3. Risks and quick mitigations

| Risk | Mitigation |
|---|---|
| GPT-6 Luna latency (3–32 s per call) makes "Plan my season" slow | Parallel tools per round; at most 3 planned rounds; `read_analysis` reuse; seeded saved replay for the stage, with "Run it live" as the encore |
| Provider outage on stage | The saved replay and the tour work offline from stored records; say so plainly, never fake a live answer |
| A seeded run gives a weaker story than expected | W1 picks the story key from the data; rehearse with whatever the data says (PITCH.md §1 has alternatives) |
| The dev API reloads mid-test | Don't edit `.py` during live runs; use `make demo` for final runs |
| Running out of time | Follow the phase order; ship each item's cut line; P1 + BIG alone already changes the outcome |
