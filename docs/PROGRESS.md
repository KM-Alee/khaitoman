# Progress and build plan

What is done, what is left, and the ordered PR queue that "ai continue" works through. Written 2026-10-10 06:40 UTC from `git log`, `git status`, the repo tree and the project threads.

- **Row-level status with evidence** lives in [`docs/STATUS.md`](STATUS.md). This file is the plan; STATUS is the scoreboard. When they disagree, executed evidence wins.
- **Process** lives in [`docs/WORKFLOW.md`](WORKFLOW.md) (builder ships PRs, reviewer verifies, fixes and merges).
- **Reviewer side** of this plan: [`docs/REVIEW_PLAN.md`](REVIEW_PLAN.md).
- **"ai continue"**: [`docs/CONTINUE.md`](CONTINUE.md) reads this file and picks the next step for your role (builder or reviewer).

Scope is fixed: F01–F20 and AT01–AT18, nothing cut.

## 1. Where things stand

| M | Outcome | State | Notes |
|---|---|---|---|
| M0 | Feasibility, contracts | **done** (committed) | Images build, `make doctor`, provider `gpt-6-luna` tool calling, AquaCrop bench 0.17 s/run, CP-SAT fixture, schemas frozen, Delineate sample. |
| M1 | Two real pilot packages + onboarding pipeline | **mostly done** (committed) | pilot-a and pilot-b `reviewed-v1` published (`data/pilots/index.json`), pilot-b through the onboarding pipeline (`05c844d`). Missing: AT01 test. |
| M2 | Exact domain engine | **mostly done** | P01 builds both pilots' four-season libraries and implements `make domain-tests` (75 passed, AT02–AT04). Pilot-b has 9,736 policies; repeat-build hashes verified separately. Denser-library objective/action stability (T5.7) remains unverified. |
| M3 | Decisions | **done in code** (committed `d9518bd`) | Baseline ladder, live solve, constraints, economics/rights. Named tests exist for AT05–AT08, AT12. Not yet marked passed in STATUS. |
| M4 | Polished decision loop (UI) | **in progress** | Workspace 3D, replay with canopy frames, compare, impact/report screens, Explore wired to analyses, copilot panel (`c9e01a2`, `574534f`, `e049bdc`). Esri imagery layer uncommitted. Missing: AT13, AT14, screenshots. |
| M5 | Frontier, stress/robust, surrogate, why-not/synergy | **done in code** (committed) | Routes under `/api/v2/analyses/*`, surrogate retrained to cover all 2026-27/2027-28 scenarios (`tests/unit/test_surrogate_domain_coverage.py`, uncommitted). AT09–AT11 tests exist. |
| M6 | Impact/SDG, onboarding UI, evidence, export, offline/restart | **not started** | `services/reports/__init__.py` is empty, `services/onboarding` missing, but job handlers already point at both. No tests for AT15, AT16, AT18. |
| M7 | Copilot | **built, not evaluated** | 16 tools, provider loop, router registered in `main.py`, 76 copilot tests. Live eval (30 cases × 3) never ran. Report tool needs M6 reports API. |
| M8 | Release | **not started** | `make core-acceptance`, `copilot-evals`, `release-check`, `domain-tests` still print "not implemented yet". |

Acceptance tests with a named test in `tests/` today: AT02–AT12. **No test yet:** AT01, AT13, AT14, AT15, AT16, AT17, AT18.

### Integration awaiting review

The integration work above is committed on `feat/p00-integrate-m1-m5` and open as PR #2. P01 stacks on that branch; the reviewer owns P00.

### Known risks

- `docs/STATUS.md` records evidence by row. P01 moves AT02–AT04 to passed and keeps broader M2/F12 completion claims open where verification remains.
- The full test suite has run green in sandboxes (381 fast tests, 49 vitest reported), not yet on a clean checkout of `main`.
- Default AquaCrop yields look high (wheat ~7.6 t/ha rainfed). Keep `crop_calibration=uncalibrated` visible until a plausibility check.
- The copilot turn budget is 90 s and the model takes ~14 s per call, so tool rounds must stay low.
- Esri imagery was only tested with mocked tiles. It must work with no key (Sentinel-2 fallback) and the key must never be committed.

## 2. PR queue

Work top to bottom. Each row is one PR (stack only where **Needs** names an unmerged PR). Branch `feat/pNN-<slug>` (or `fix/`, `chore/`), PR title `PNN <IDs>: <summary>`.

Status values: `todo`, `building` (branch pushed, no PR yet), `review #n`, `done #n`. The builder sets `review #n` in the PR itself; the reviewer sets `done #n` in its last review commit before merging.

| ID | Milestone | Delivers | Needs | Status |
|---|---|---|---|---|
| P00 | M1–M5 | One PR with the whole current working tree (`git add .`; `.env` and `.xfer/` stay ignored), opened by the lead thread, including these plan docs: workflow, Esri imagery, surrogate retrain + domain-coverage test, pilot weather, copilot tool shapes. Refresh `docs/STATUS.md` with evidence for M0–M5 rows. | — | review #2 |
| P01 | M2 | Pilot-b candidate libraries for all 4 seasons (`make candidates PILOT=pilot-b`). `make domain-tests` runs the AT02–AT04 tests and the water/property suites. | P00 | building |
| P02 | M1 | AT01 test (`tests/integration/test_pilot_packages.py`): both pilots have real scene/source IDs, ≥30 reviewed fields, valid directed graph, manifest hashes match. `make pilot-a`/`pilot-b` reproduce the package. | P00 | todo |
| P03 | M3 | Mark AT05–AT08, AT12 with evidence; fill any rule in PRD §11.2 those tests miss. `make core-acceptance` v1 runs every AT test that exists. | P00 | todo |
| P04 | M5 | AT09–AT11 evidence; surrogate preview ≤300 ms after load (PRD §11.1), in-domain on the default request. | P00 | todo |
| P05 | M6 | Reports + evidence API (F14, F17): `POST /reports`, `GET /reports/{id}`, files route, report job, self-contained `report.html`, CSVs, GeoJSON, `manifest.json` with sha256. Match the contract the copilot already calls. | P00 | todo |
| P06 | M6 | Impact/SDG (F16, PRD §8.5, T7.5): `services/impact`, three cards (2.4, 6.4/6.5, 13.1), field-change distribution, no 0–100 score, CO₂ `not_estimated`. Impact screen SDG cards. | P00 | todo |
| P07 | M6 | Onboarding API + job (F03, AT16, T9.1): aoi-check, raw-packages, intake, process, versioned review (409 on stale), publish with validation, layers. UI wizard wired. Integration test publishes pilot-b `reviewed-v2` from its real raw bundle. | P00 | todo |
| P08 | M6 | Package export/import zip (T9.3–T9.5) with all import checks; `scripts/build_evidence_pack.py` writes the §13.3 pack. | P05 | todo |
| P09 | M6 | AT15 offline (sockets blocked; boot, pilots, solve, replay, frontier, stress, export) + `scripts/offline_check.py` on `web/dist`. AT18 restart (runs restore and re-verify, interrupted jobs marked honestly, tampered artifact refused). | P05, P08 | todo |
| P10 | M7 | Copilot live smoke eval, then full 30×3; fix failures; bilingual (en/ur) answers and cards; `make copilot-evals`. AT17. | P05 | todo |
| P11 | M4 | AT13 (report, UI and copilot show the same values, units, run IDs) and AT14 (six screens: responsive, keyboard, contrast, states, reduced motion; Playwright + axe). Screenshots at 3 viewports in `evidence/screenshots/`. Esri check in a real browser. | P06, P07, P10 | todo |
| P12 | M8 | Playwright E2E of the full PRD §13.2 stage route against the real API (`tests/e2e/stage-route.spec.ts`). | P11 | todo |
| P13 | M8 | Cold launch via `make demo`, §11.1 timings recorded, `make release-check`, release/capability report (each F and AT passed/failed/blocked with artifact paths), evidence pack, final STATUS. | P12 | todo |

Gap issues (`gh issue list --label gap`) jump the queue: the builder fixes open gaps for merged work before starting the next `todo` row, and that PR says `Closes #n`.

## 3. Next up

1. Reviewer reviews P00 (#2) first. P01 is building on its branch.
2. P01, P02, P05, P06 and P07 only need P00, so they can be built in parallel (separate branches from `origin/main` once P00 merges, or stacked on the P00 branch until then).
3. P10 (copilot eval) starts as soon as P05 is merged; it costs model calls and time, so start it early.
4. P11–P13 are the release run and go last.
