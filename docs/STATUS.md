# Build status

Single source of truth for progress. Update a row only with evidence (command + result, file, or screenshot path).
Status values: `not_started`, `in_progress`, `passed`, `failed`, `blocked`.

## Milestones (PRD §12, tech doc T13.1)

| ID | Outcome | Status | Evidence / notes |
|---|---|---|---|
| M0 | Feasibility and contracts: envs locked, science/solver sample timed, data/hardware/provider access, schemas frozen | in_progress | Docker images built; initial `make doctor` used CPU torch 2.14.1. P01 later executed LightGBM training on the RTX 5060 Laptop GPU (`evidence/commands/p01-complete-20261010T075535Z.log`). Provider `gpt-6-luna` available (`make provider-check`). AquaCrop wheat on real Open-Meteo weather: warm-up 0.35 s, median 0.166 s/run (`evidence/benchmarks/crop-bench-*.json`) so ~2,900 runs ≈ 8 min single-process. CP-SAT T12.2 fixture passes. Domain contract frozen in `api/aabflow/domain/schemas`. Remaining: Delineate sample run (data stream) |
| M1 | Real source packages: two AOIs, acquisition/import, inference/review, fields/graph/manifest, onboarding pipeline | in_progress | `pilot-a` and `pilot-b` `reviewed-v1` published in `data/pilots/index.json`. AT01 passed. `make pilot-a` reproduces `97e95984…` with the selected-area warabandi that package was published with. `make pilot-b` reproduces `f8c48181…` with the declared 120 ha rule. Neither command rewrites the package. |
| M2 | Exact domain engine: two crops, weather, ledger, crop adapter, candidates; science batch launched | in_progress | P01 backend complete: both pilots/four seasons, 17,480 pilot-b policies, 20 paired density comparisons with 40 OPTIMAL solves and retained larger libraries. `make domain-tests` → 85 passed; `make science-smoke` → 45 passed; `make test` → 397 passed; lint passed (2026-10-10). `evidence/commands/p01-complete-20261010T075535Z.log`, `docs/P01_DOMAIN.md`. Broader explorer/UI verification remains in the UI queue. |
| M3 | Decisions: baselines, all actions, live selection, constraints, economics/rights | in_progress | AT05–AT08 and AT12 passed once in `make core-acceptance` v1 (`evidence/commands/p03-core-acceptance-20261010T1106Z.log`). v1 is not G-CORE. |
| M4 | Polished decision loop: workspace/compare, replay, report, visual system, error/stale | in_progress | MapLibre workspace 3D, DEM decoding, optional Esri World Imagery with offline Sentinel-2 fallback (`web/src/components/map/engine.ts`, `tests/e2e/offline-imagery.spec.ts`). Vitest 49/49 passes. |
| M5 | Expanded intelligence: frontier, stress/robust, surrogate, why-not/synergy | in_progress | Frontier/stress routes mounted under `/api/v2/analyses/`. P01 `surrogate-v7-gpu`: both crops and all three sources pass release gates; 52 default preview requests cover both pilots/all published scenarios. `data/models/surrogate-v7-gpu/evaluation.json`; `evidence/commands/p01-complete-20261010T075535Z.log`. Full M5 acceptance remains P04. |
| M6 | Complete core: impact/SDG, onboarding UI, evidence, export, offline/restart | not_started | |
| M7 | Copilot (last): tool registry, provider loop, cards, bilingual, 30×3 eval | in_progress | User decision 2026-10-10: the 30×3 live eval will not be run. AT17 stays unpassed. Existing copilot unit tests remain the check. |
| M8 | Release: regression, cold launch, rehearsals, release report | not_started | |

## Features (PRD §3)

| ID | Feature | Milestone | Status | Evidence |
|---|---|---|---|---|
| F01 | Two-pilot geospatial workspace | M1/M2 | not_started | |
| F02 | Genuine field AI and review | M1 | not_started | |
| F03 | Guided regional onboarding | M1/M6 | in_progress | P07 wizard (`web/src/features/onboarding/`) wired to the onboarding API: server AOI check, raw-package select (listing now carries the bundle AOI), intake + process job with SSE stage log, review map/table with reject/replace-outline, network assumptions and rule overrides via `PATCH /review` (`expected_version`, 409 reload), view-reported publish blockers, publish with idempotency key. Vitest 75 passed (16 onboarding); `npm run build` passed; pytest `--ignore=tests/scientific` 536 passed, 3 need real `data/raw/bundles`+`data/pilots` (10/10 pass with them mounted read-only). `AAB_LIVE_SPECS=1 npx playwright test onboarding`: 4 passed, 2 skipped by design, against this branch's API on a copy of `data/` (real process job, cached Delineate `50ca220c256bbf74`, real 409); stops before publish. Publish through the UI is tested with mocked fetch only. Crop/soil/rights/asset parameters are not accepted by the onboarding API yet. |
| F04 | Crop/weather explorer | M2 | in_progress | P01: pilot-b own archived weather/scenarios and all four exact seasons; representative denser wheat/cotton libraries retained for both pilots. Domain 85 passed, science 45 passed. `evidence/commands/p01-complete-20261010T075535Z.log`. Explorer UI verification remains in the UI queue. |
| F05 | Entitlements, network, and storage | M2 | in_progress | P01: AT03/AT04 rejections, independent water properties, original-precision portfolio reconstruction for both pilots/all seasons, and all 40 density selections pass. Domain 85 passed. `evidence/commands/p01-complete-20261010T075535Z.log`. UI inspection is outside this backend chunk. |
| F06 | Five action categories | M3 | not_started | |
| F07 | Live portfolio selection | M3 | not_started | |
| F08 | Competent baseline ladder | M3 | not_started | |
| F09 | Season replay | M4 | not_started | |
| F10 | Resilience frontier | M5 | not_started | |
| F11 | Stress testing and robust plan | M5 | not_started | |
| F12 | Validated surrogate explorer | M5 | in_progress | P01: `surrogate-v7-gpu` trained on NVIDIA GeForce RTX 5060 Laptop GPU; wheat/cotton and each pilot pass every gate on the common unfitted year plus separately held-out schedule family. Pilot nMAE: wheat 7.77%/7.93%, cotton 8.07%/8.01%. Development-only architecture/bias selection, 2% component-domain margin, default previews and exact confirmation tested. Fast 397 / science 45 passed. `data/models/surrogate-v7-gpu/evaluation.json`; `evidence/commands/p01-complete-20261010T075535Z.log`. Prior weather years were inspected; new release schedules were never fitted (see `docs/P01_DOMAIN.md`). |
| F13 | Why-not, bottleneck, and synergy analysis | M5 | not_started | |
| F14 | Economics and action plan | M4/M6 | not_started | |
| F15 | Equity and water accounting | M3/M4 | not_started | |
| F16 | Impact and SDG analysis | M6 | not_started | |
| F17 | Evidence and reproducibility | M1–M6 | in_progress | P01: immutable publication/collision/restoration checks, all four pilot-b hashes reproduced, real raw crop artifacts, density reports with selections and bounds, GPU device/process and per-pilot evaluation records. Domain 85 passed. `docs/P01_DOMAIN.md`, `evidence/commands/p01-complete-20261010T075535Z.log`. Reports/export/import remain separate P05/P08 deliverables. |
| F18 | Complete visual/interaction system | M4/M6 | in_progress | Win path (feat/win-path): landing headline from `GET /demo/headline` (`tests/unit/test_demo_headline.py`), AI-inside strip from `GET /ai-stack`, Ask box, AI-reveal and instant-crop tour steps; `journey-tour.spec.ts` passed on dev (14 steps, `evidence/screenshots/tour-desktop-1920-*.png`); one-page brief `evidence/print/brief-20261010T153603Z.pdf`. AT14 not run. |
| F19 | Conversational copilot | M7 | in_progress | Plan mode ("Plan my season", schema v4, `tests/copilot/test_plan_mode.py`): live seeded turn completed in 93.7 s validated (`evidence/copilot/plan-season-live-20261010T1703Z.json`); `journey-plan.spec.ts` live goal passed (103.8 s); one plan turn on the demo image ended provider_unavailable (113 s). Landing Urdu question answered in Urdu in 54.3 s (`evidence/copilot/landing-urdu-20261010T1526Z.json`). AT17 not run. Backend done on `feat/copilot-luna`: 27 validated tools (incl. one-step `run_what_if`, plan ladder, equity, water, economics, SDG, action plan, timeline, saved analyses), server-materialized visual blocks, SSE progress events, schema v3 persistence; contract in `docs/COPILOT.md`. `tests/copilot` 104 passed (scripted fixture provider). Live `gpt-6-luna` smoke 6/7 completed, 1 honest timeout (`evidence/copilot/smoke-20261010T131112Z.json`). Chat UI on the redesigned system still to build. |
| F20 | Reliable full demo | M8 | in_progress | Cold start 3.05 s to healthy, 3.9 s to first tour step (`evidence/benchmarks/cold-demo-20261010T170800Z.json`); RECORDED fallback video `evidence/rehearsal/tour-20261010T174045Z.webm` (not committed, 54 MB). AT15 not run. |

## Acceptance tests (PRD §11.2)

| ID | Summary | Milestone | Status | Evidence |
|---|---|---|---|---|
| AT01 | Both pilots: real scene/source IDs, 30 reviewed fields, valid graph | M1 | passed | `tests/integration/test_pilot_packages.py` reads both published `reviewed-v1` packages. `make pilot-a` reproduced `97e95984…` and `make pilot-b` reproduced `f8c48181…` with no writes. A hash mismatch still leaves the published tree unchanged. |
| AT02 | Wheat and cotton runs with raw outputs, units, varying irrigation | M2 | passed | Domain 85 passed, including both named wheat/cotton treatment gates; raw kg/ha conversion and actual irrigation audited. Science 45 passed. `evidence/commands/p01-complete-20261010T075535Z.log`. |
| AT03 | Monday-before-Friday pond use and intra-period over-capacity rejected | M2 | passed | Domain 85 passed: Monday-before-Friday and intra-period capacity rejections, plus independent water property oracles. `evidence/commands/p01-complete-20261010T075535Z.log`. |
| AT04 | Closed route, shared-pump excess, missing costs, early commissioning rejected | M2 | passed | Domain 85 passed: closed route, shared-pump excess, missing costs and early commissioning rejection cases. `evidence/commands/p01-complete-20261010T075535Z.log`. |
| AT05 | Zero capital → no new assets; competent no-capital plan available | M3 | passed | `test_at05_zero_capital_no_new_assets`. core-acceptance v1: 1 passed. |
| AT06 | Live budget/deficit change re-solves and changes plan where designed | M3 | passed | `test_at06_binding_change_changes_plan_and_nonbinding_does_not`. core-acceptance v1: 1 passed. |
| AT07 | Coverage and finite-model optimality visible; no overstated impossibility | M3 | passed | `test_at07_coverage_and_finite_infeasibility`. core-acceptance v1: 1 passed. |
| AT08 | Matched comparisons share conditions; nonmatched labelled | M3 | passed | `test_at08_matched_share_conditions_nonmatched_labelled`. core-acceptance v1: 1 passed. |
| AT09 | Six-setting frontier and nine-cell stress map to run records | M5 | passed | Live API on real pilot-a wheat 2027-28: six frontier points (5 OPTIMAL nondominated, 1 INFEASIBLE tail-service point), nine stress cells; every point/cell `run_id` resolves via `GET /runs/{id}` with the analysis id. `make analyses-evidence` → `evidence/benchmarks/analyses-20261010T114936Z.json`. |
| AT10 | Robust run shares decisions; impossible stress cells have no yield | M5 | passed | Robust plan R: 9/9 cells deliverable with the same policy IDs; foregone typical output 27,360 kg vs P. Typical-only plan P: 6/9 cells undeliverable, each with `field_delivery` violations and no yield; worst-tested blocked. `make analyses-evidence` → `evidence/benchmarks/analyses-20261010T114936Z.json`. |
| AT11 | Surrogate held-out evaluation passes; previews exact-confirmed | M5 | not_started | |
| AT12 | Shared cost once; pond land removed; pumping on operating budget | M3 | passed | `test_at12_shared_cost_once_pond_land_pumping_budget` and `test_at12_pond_land_removed_once`. core-acceptance v1: 2 passed. |
| AT13 | Report, UI, chatbot use same metrics, units, run IDs | M4 | not_started | |
| AT14 | Six screens pass responsive/keyboard/contrast/state/reduced-motion | M4 | not_started | |
| AT15 | Core works with network denied, no hidden CDN requests | M6 | not_started | |
| AT16 | Onboarding publishes second pilot through real review/validation | M6 | not_started | |
| AT17 | Copilot completes evaluated tool workflows with real services | M7 | not_started | |
| AT18 | Clean restart restores runs, marks interrupted jobs honestly | M6 | not_started | |

## Decisions and defaults (overnight build, pablo away)

- Copilot model: `gpt-6-luna` from `.env` (`AABFLOW_OPENAI_MODEL`), verified available 2026-10-09.
- Default AquaCrop wheat profile: simulation window must run to the profile's `latest_harvest`; a window ending mid-May returned no harvest row (bench script).
- Default yields from uncalibrated AquaCrop parameters look high (wheat ~7.6 t/ha rainfed at 30.8N 72.5E); `crop_calibration=uncalibrated` stays visible until a plausibility check against Punjab district estimates.
- Copilot provider: strict function calling with `gpt-6-luna` verified through the Responses API (tool call + function_call_output follow-up; `evidence/environment/provider-tools-*.json`). Measured ~14 s per model call, so the 90 s turn budget (T11.4) allows ~5 rounds; M7 must stream tool-state feedback and keep rounds low.
- Overnight streams run in parallel per `docs/STREAMS.md`; the integrator commits.
- 2026-10-10, user: do not run the 30×3 copilot evaluation. AT17 stays unpassed. Every other required check runs once; reuse libraries, the surrogate, and cached inference.
