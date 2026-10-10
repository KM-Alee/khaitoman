# Progress and build plan

What is done, what is left, and the ordered PR queue that "ai continue" works through. Written 2026-10-10 06:40 UTC from `git log`, `git status`, the repo tree and the project threads.

- **Row-level status with evidence** lives in [`docs/STATUS.md`](STATUS.md). This file is the plan; STATUS is the scoreboard. When they disagree, executed evidence wins.
- **Process** lives in [`docs/WORKFLOW.md`](WORKFLOW.md) (builder ships PRs, reviewer verifies, fixes and merges).
- **Reviewer side** of this plan: [`docs/REVIEW_PLAN.md`](REVIEW_PLAN.md).
- **"ai continue"**: [`docs/CONTINUE.md`](CONTINUE.md) reads this file and picks the next step for your role (builder or reviewer).
- **Parallel execution**: [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md) and the complete [`agent-dag.json`](agent-dag.json) refine this PR queue into bounded tasks, core-before-copilot gates and independent reviewer joins. The generated graph is [`AGENT_DAG.md`](AGENT_DAG.md).

Scope is fixed: F01–F20 and AT01–AT18, nothing cut.

## 1. Where things stand

| M | Outcome | State | Notes |
|---|---|---|---|
| M0 | Feasibility, contracts | **done** (committed) | Images build, `make doctor`, provider `gpt-6-luna` tool calling, AquaCrop bench 0.17 s/run, CP-SAT fixture, schemas frozen, Delineate sample. |
| M1 | Two real pilot packages + onboarding pipeline | **mostly done** (committed) | pilot-a and pilot-b `reviewed-v1` published (`data/pilots/index.json`), pilot-b through the onboarding pipeline (`05c844d`). Missing: AT01 test. |
| M2 | Exact domain engine | **mostly done** | P01 builds both pilots' four-season libraries and implements `make domain-tests` (85 passed, AT02–AT04). Pilot-b has 17,480 policies; retained density recipes and repeat-build hashes are verified. P01 also executes denser-library objective/action comparisons on both pilots and crops; evidence is in `docs/P01_DOMAIN.md`. |
| M3 | Decisions | **done in code** (committed `d9518bd`) | Baseline ladder, live solve, constraints, economics/rights. Named tests exist for AT05–AT08, AT12. Not yet marked passed in STATUS. |
| M4 | Polished decision loop (UI) | **in progress** | Workspace 3D, replay with canopy frames, compare, impact/report screens, Explore wired to analyses, copilot panel (`c9e01a2`, `574534f`, `e049bdc`). Esri imagery is committed in P00. Missing: AT13, AT14, screenshots. |
| M5 | Frontier, stress/robust, surrogate, why-not/synergy | **done in code** (committed) | Routes under `/api/v2/analyses/*`, surrogate domain coverage is checked across published scenarios (`tests/unit/test_surrogate_domain_coverage.py`). AT09–AT11 tests exist. |
| M6 | Impact/SDG, onboarding UI, evidence, export, offline/restart | **not started** | `services/reports/__init__.py` is empty, `services/onboarding` missing, but job handlers already point at both. No tests for AT15, AT16, AT18. |
| M7 | Copilot | **built, not evaluated** | 16 tools, provider loop, router registered in `main.py`, 76 copilot tests. Live eval (30 cases × 3) never ran. Report tool needs M6 reports API. |
| M8 | Release | **not started** | `make core-acceptance`, `copilot-evals`, `release-check` still print "not implemented yet". |

Acceptance tests with a named test in `tests/` today: AT02–AT12. **No test yet:** AT01, AT13, AT14, AT15, AT16, AT17, AT18.

### Integration awaiting review

P00 was merged as PR #2 on 2026-10-10. P01 now targets `main`; its domain and GPU evaluation evidence is recorded in `docs/P01_DOMAIN.md`.

### Known risks

- `docs/STATUS.md` records evidence by row. P01 moves AT02–AT04 to passed and keeps broader M2/F12 completion claims open where verification remains.
- P01 ran 397 fast tests, 85 domain tests, 45 science tests and lint green on its branch; P00 records 49 vitest passes. Release checks on a clean checkout remain P13.
- Default AquaCrop yields look high (wheat ~7.6 t/ha rainfed). Keep `crop_calibration=uncalibrated` visible until a plausibility check.
- The copilot turn budget is 90 s and the model takes ~14 s per call, so tool rounds must stay low.
- Esri imagery was only tested with mocked tiles. It must work with no key (Sentinel-2 fallback) and the key must never be committed.

## 2. PR queue

For serial work, use the first ready row; parallel work follows the DAG's substeps and validated SHA ancestry. Each row is one coherent PR, with explicit stacked sub-PRs where a split integration gate requires them. Parent chunks stay incomplete until all substeps pass. Branch `feat/pNN-<slug>` (or `fix/`, `chore/`), PR title `PNN <IDs>: <summary>`.

Status values: `todo`, `building` (branch pushed, no PR yet), `review #n`, `done #n`. The builder sets `review #n` in the PR itself; the reviewer sets `done #n` in its last review commit before merging.

| ID | Milestone | Delivers | Needs | Status |
|---|---|---|---|---|
| P00 | M1–M5 | One PR with the whole current working tree (`git add .`; `.env` and `.xfer/` stay ignored), opened by the lead thread, including these plan docs: workflow, Esri imagery, surrogate retrain + domain-coverage test, pilot weather, copilot tool shapes. Refresh `docs/STATUS.md` with evidence for M0–M5 rows. | — | done #2 |
| P01 | M2 | Pilot-b candidate libraries for all 4 seasons (`make candidates PILOT=pilot-b`). `make domain-tests` runs the AT02–AT04 tests and the water/property suites. | P00 | review #3 |
| P02 | M1 | AT01 test (`tests/integration/test_pilot_packages.py`): both pilots have real scene/source IDs, ≥30 reviewed fields, valid directed graph, manifest hashes match. `make pilot-a`/`pilot-b` reproduce the package. | P00 | todo |
| P03 | M3 | Mark AT05–AT08, AT12 with evidence; fill any rule in PRD §11.2 those tests miss. `make core-acceptance` v1 runs every AT test that exists; partial v1 cannot unlock M7. | P00, P01 | todo |
| P04 | M5 | AT09–AT11 evidence; surrogate preview ≤300 ms after load (PRD §11.1), in-domain on the default request. | P01, P03 | todo |
| P05 | M6 | Reports + evidence API (F14, F17): `POST /reports`, `GET /reports/{id}`, files route, report job, self-contained `report.html`, CSVs, GeoJSON, `manifest.json` with sha256. Match the contract the copilot already calls. | P00 | todo |
| P06 | M6 | Impact/SDG (F16, PRD §8.5, T7.5): `services/impact`, three cards (2.4, 6.4/6.5, 13.1), field-change distribution, no 0–100 score, CO₂ `not_estimated`. Impact screen SDG cards. | P03, P04 | todo |
| P07 | M6 | Onboarding API + job (F03, AT16, T9.1): aoi-check, raw-packages, intake, process, versioned review (409 on stale), publish with validation, layers. UI wizard wired. Integration test publishes pilot-b `reviewed-v2` from its real raw bundle. | P00 | todo |
| P08 | M6 | Package export/import zip (T9.3–T9.5) with all import checks; `scripts/build_evidence_pack.py` writes the §13.3 pack. | P05, P07; pack also P04/P06 | todo |
| P09 | M6 | AT15 offline (sockets blocked; boot, pilots, solve, replay, frontier, stress, export) + `scripts/offline_check.py` on `web/dist`. AT18 restart (runs restore and re-verify, interrupted jobs marked honestly, tampered artifact refused). | P08, P11-core | todo |
| P10 | M7 | Copilot code stays; no 30×3 live eval (user decision 2026-10-10). AT17 is not marked passed. Existing unit tests stay green. | Full G-CORE including P09 | todo |
| P11 | M4 | AT13 (report, UI and copilot show the same values, units, run IDs) and AT14 (six screens: responsive, keyboard, contrast, states, reduced motion; Playwright + axe). Screenshots at 3 viewports in `evidence/screenshots/`. Esri check in a real browser. | P06, P07, P10 | todo |
| P12 | M8 | Playwright E2E of the full PRD §13.2 stage route against the real API (`tests/e2e/stage-route.spec.ts`). | P11 | todo |
| P13 | M8 | Cold launch via `make demo`, §11.1 timings recorded, `make release-check`, release/capability report (each F and AT passed/failed/blocked with artifact paths), evidence pack, final STATUS. | P12 | todo |

Gap issues (`gh issue list --label gap`) jump the queue: the builder fixes open gaps for merged work before starting the next `todo` row, and that PR says `Closes #n`.

## 3. Next up

1. P00 (#2) is merged. P01 (#3) is ready for reviewer verification; the builder takes P02 next.
2. After shared-interface inventory, P02, P03 and P05 API preparation can proceed independently; the DAG caps workers and expensive resources. P05 artifacts require P03; P07 process needs P02 and review uses P01 version/library semantics. Final chunk validation uses all recorded dependencies.
3. P11-core runs before P09/G-CORE. Each required check runs once. Reuse libraries, the trained surrogate, and cached inference. Do not retrain or repeat a passing run.
4. The 30×3 copilot evaluation is waived. AT17 stays unpassed. P11-final, P12, and P13 still ship the product once each. Reviewer merges remain required for release.
