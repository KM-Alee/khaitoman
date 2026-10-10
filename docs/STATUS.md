# Build status

Single source of truth for progress. Update a row only with evidence (command + result, file, or screenshot path).
Status values: `not_started`, `in_progress`, `passed`, `failed`, `blocked`.

## Milestones (PRD §12, tech doc T13.1)

| ID | Outcome | Status | Evidence / notes |
|---|---|---|---|
| M0 | Feasibility and contracts: envs locked, science/solver sample timed, data/hardware/provider access, schemas frozen | in_progress | Docker images built; `make doctor` all present (no GPU; CPU torch 2.14.1). Provider `gpt-6-luna` available (`make provider-check`). AquaCrop wheat on real Open-Meteo weather: warm-up 0.35 s, median 0.166 s/run (`evidence/benchmarks/crop-bench-*.json`) so ~2,900 runs ≈ 8 min single-process. CP-SAT T12.2 fixture passes. Domain contract frozen in `api/aabflow/domain/schemas`. Remaining: Delineate sample run (data stream) |
| M1 | Real source packages: two AOIs, acquisition/import, inference/review, fields/graph/manifest, onboarding pipeline | in_progress | `pilot-a` and `pilot-b` `reviewed-v1` published in `data/pilots/index.json`. Missing AT01 test. |
| M2 | Exact domain engine: two crops, weather, ledger, crop adapter, candidates; science batch launched | in_progress | P01: both pilots have four-season exact libraries; pilot-b has 9,736 policies. `make domain-tests` → 75 passed; `make science-smoke` → 41 passed; `make test` → 386 passed (2026-10-10). Evidence: `evidence/commands/p01-20261010T065119Z.log`, `evidence/benchmarks/science-library-pilot-b-20261010T065119Z.json`. T5.7 denser-library stability comparison still unverified; see `docs/P01_DOMAIN.md`. |
| M3 | Decisions: baselines, all actions, live selection, constraints, economics/rights | in_progress | Baseline ladder (B0, B1, P, R), constraints, solver routes implemented (`d9518bd`, `api/aabflow/services/runs`). Tests in `tests/scientific/test_real_pilot_decisions.py`. |
| M4 | Polished decision loop: workspace/compare, replay, report, visual system, error/stale | in_progress | MapLibre workspace 3D, DEM decoding, optional Esri World Imagery with offline Sentinel-2 fallback (`web/src/components/map/engine.ts`, `tests/e2e/offline-imagery.spec.ts`). Vitest 49/49 passes. |
| M5 | Expanded intelligence: frontier, stress/robust, surrogate, why-not/synergy | in_progress | Frontier and stress routes mounted under `/api/v2/analyses/`. `surrogate-v1` retrained for cotton & wheat with domain coverage verified across all 53 pilot scenarios. |
| M6 | Complete core: impact/SDG, onboarding UI, evidence, export, offline/restart | not_started | |
| M7 | Copilot (last): tool registry, provider loop, cards, bilingual, 30×3 eval | not_started | |
| M8 | Release: regression, cold launch, rehearsals, release report | not_started | |

## Features (PRD §3)

| ID | Feature | Milestone | Status | Evidence |
|---|---|---|---|---|
| F01 | Two-pilot geospatial workspace | M1/M2 | not_started | |
| F02 | Genuine field AI and review | M1 | not_started | |
| F03 | Guided regional onboarding | M1/M6 | not_started | |
| F04 | Crop/weather explorer | M2 | in_progress | P01: pilot-b weather/scenarios published from its own archived grid; all four seasons have exact wheat/cotton policies and raw outcomes. `make domain-tests` → 75 passed, `make science-smoke` → 41 passed; `evidence/commands/p01-20261010T065119Z.log`. Explorer UI not exercised in this PR. |
| F05 | Entitlements, network, and storage | M2 | in_progress | P01: AT03/AT04 rejections, water properties, and original-precision portfolio reconstruction for both pilots/all seasons pass in `make domain-tests` (75 passed); `evidence/commands/p01-20261010T065119Z.log`. UI inspection remains unverified here. |
| F06 | Five action categories | M3 | not_started | |
| F07 | Live portfolio selection | M3 | not_started | |
| F08 | Competent baseline ladder | M3 | not_started | |
| F09 | Season replay | M4 | not_started | |
| F10 | Resilience frontier | M5 | not_started | |
| F11 | Stress testing and robust plan | M5 | not_started | |
| F12 | Validated surrogate explorer | M5 | in_progress | P01 regression fix: `surrogate-v2` adds published calendar experiments with original weather-year splits, preserving v1. `make train-surrogate` → passed true (both crops); default previews, domain refusal and exact confirmation covered by `make test` (386 passed) / `make science-smoke` (41 passed). `data/models/surrogate-v2/evaluation.json`; source-specific pilot holdout evidence remains for P04. |
| F13 | Why-not, bottleneck, and synergy analysis | M5 | not_started | |
| F14 | Economics and action plan | M4/M6 | not_started | |
| F15 | Equity and water accounting | M3/M4 | not_started | |
| F16 | Impact and SDG analysis | M6 | not_started | |
| F17 | Evidence and reproducibility | M1–M6 | in_progress | P01: versioned pilot-b library metadata, exact raw crop outputs, build benchmarks, immutable publication/collision/restoration tests (`make domain-tests` → 75 passed). `docs/P01_DOMAIN.md`, `evidence/commands/p01-20261010T065119Z.log`. Reports/export/import and broader evidence interface remain P05/P08. |
| F18 | Complete visual/interaction system | M4/M6 | not_started | |
| F19 | Conversational copilot | M7 | not_started | |
| F20 | Reliable full demo | M8 | not_started | |

## Acceptance tests (PRD §11.2)

| ID | Summary | Milestone | Status | Evidence |
|---|---|---|---|---|
| AT01 | Both pilots: real scene/source IDs, 30 reviewed fields, valid graph | M1 | not_started | |
| AT02 | Wheat and cotton runs with raw outputs, units, varying irrigation | M2 | passed | `make domain-tests` → 75 passed, including `test_at02_gate2_wheat_three_treatments` and `test_at02_gate3_cotton_three_treatments`; raw kg/ha conversion and actual irrigation audited. `make science-smoke` → 41 passed. `evidence/commands/p01-20261010T065119Z.log`. |
| AT03 | Monday-before-Friday pond use and intra-period over-capacity rejected | M2 | passed | `make domain-tests` → 75 passed; `test_at03_monday_before_friday_rejected` and `test_at03_intra_period_over_capacity_rejected` explicitly passed, plus independent water property oracles. `evidence/commands/p01-20261010T065119Z.log`. |
| AT04 | Closed route, shared-pump excess, missing costs, early commissioning rejected | M2 | passed | `make domain-tests` → 75 passed; all four named `test_at04_*` rejection cases explicitly passed. `evidence/commands/p01-20261010T065119Z.log`. |
| AT05 | Zero capital → no new assets; competent no-capital plan available | M3 | not_started | |
| AT06 | Live budget/deficit change re-solves and changes plan where designed | M3 | not_started | |
| AT07 | Coverage and finite-model optimality visible; no overstated impossibility | M3 | not_started | |
| AT08 | Matched comparisons share conditions; nonmatched labelled | M3 | not_started | |
| AT09 | Six-setting frontier and nine-cell stress map to run records | M5 | not_started | |
| AT10 | Robust run shares decisions; impossible stress cells have no yield | M5 | not_started | |
| AT11 | Surrogate held-out evaluation passes; previews exact-confirmed | M5 | not_started | |
| AT12 | Shared cost once; pond land removed; pumping on operating budget | M3 | not_started | |
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
