# Build status

Single source of truth for progress. Update a row only with evidence (command + result, file, or screenshot path).
Status values: `not_started`, `in_progress`, `passed`, `failed`, `blocked`.

## Milestones (PRD §12, tech doc T13.1)

| ID | Outcome | Status | Evidence / notes |
|---|---|---|---|
| M0 | Feasibility and contracts: envs locked, science/solver sample timed, data/hardware/provider access, schemas frozen | in_progress | Docker images built; `make doctor` all present (no GPU; CPU torch 2.14.1). Provider `gpt-6-luna` available (`make provider-check`). AquaCrop wheat on real Open-Meteo weather: warm-up 0.35 s, median 0.166 s/run (`evidence/benchmarks/crop-bench-*.json`) so ~2,900 runs ≈ 8 min single-process. CP-SAT T12.2 fixture passes. Domain contract frozen in `api/aabflow/domain/schemas`. Remaining: Delineate sample run (data stream) |
| M1 | Real source packages: two AOIs, acquisition/import, inference/review, fields/graph/manifest, onboarding pipeline | not_started | |
| M2 | Exact domain engine: two crops, weather, ledger, crop adapter, candidates; science batch launched | not_started | |
| M3 | Decisions: baselines, all actions, live selection, constraints, economics/rights | not_started | |
| M4 | Polished decision loop: workspace/compare, replay, report, visual system, error/stale | not_started | |
| M5 | Expanded intelligence: frontier, stress/robust, surrogate, why-not/synergy | not_started | |
| M6 | Complete core: impact/SDG, onboarding UI, evidence, export, offline/restart | not_started | |
| M7 | Copilot (last): tool registry, provider loop, cards, bilingual, 30×3 eval | not_started | |
| M8 | Release: regression, cold launch, rehearsals, release report | not_started | |

## Features (PRD §3)

| ID | Feature | Milestone | Status | Evidence |
|---|---|---|---|---|
| F01 | Two-pilot geospatial workspace | M1/M2 | not_started | |
| F02 | Genuine field AI and review | M1 | not_started | |
| F03 | Guided regional onboarding | M1/M6 | not_started | |
| F04 | Crop/weather explorer | M2 | not_started | |
| F05 | Entitlements, network, and storage | M2 | not_started | |
| F06 | Five action categories | M3 | not_started | |
| F07 | Live portfolio selection | M3 | not_started | |
| F08 | Competent baseline ladder | M3 | not_started | |
| F09 | Season replay | M4 | not_started | |
| F10 | Resilience frontier | M5 | not_started | |
| F11 | Stress testing and robust plan | M5 | not_started | |
| F12 | Validated surrogate explorer | M5 | not_started | |
| F13 | Why-not, bottleneck, and synergy analysis | M5 | not_started | |
| F14 | Economics and action plan | M4/M6 | not_started | |
| F15 | Equity and water accounting | M3/M4 | not_started | |
| F16 | Impact and SDG analysis | M6 | not_started | |
| F17 | Evidence and reproducibility | M1–M6 | not_started | |
| F18 | Complete visual/interaction system | M4/M6 | not_started | |
| F19 | Conversational copilot | M7 | not_started | |
| F20 | Reliable full demo | M8 | not_started | |

## Acceptance tests (PRD §11.2)

| ID | Summary | Milestone | Status | Evidence |
|---|---|---|---|---|
| AT01 | Both pilots: real scene/source IDs, 30 reviewed fields, valid graph | M1 | not_started | |
| AT02 | Wheat and cotton runs with raw outputs, units, varying irrigation | M2 | not_started | |
| AT03 | Monday-before-Friday pond use and intra-period over-capacity rejected | M2 | not_started | |
| AT04 | Closed route, shared-pump excess, missing costs, early commissioning rejected | M2 | not_started | |
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
