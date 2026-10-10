# P01 self-review

Reviewed the full P01 diff against `origin/main`, including uncommitted work,
following `.claude/agents/spec-auditor.md`. P00 (#2) is merged; this PR targets main.

No actionable blockers or should-fix findings remain in the selected P01 chunk.

- T5.7: executed twenty paired density comparisons with forty proved OPTIMAL
  solves, on both real pilots and both representative crops. Original-precision
  physical reconstruction and spending/service checks pass. Six investment
  choices changed; the larger libraries are retained and normal rebuilds reproduce
  their recipes. Tests reject FEASIBLE, UNKNOWN, INFEASIBLE and invalid ledgers or
  budget/service selections. Finite-library approximation is disclosed.
- T8.2–T8.4: both pilots share the same unfitted release year; later source-only
  years and the irregular family are excluded from fitting. Source/soil metrics,
  rankings and decision-regret fixtures are reported separately. Architecture and
  bias correction use development-year LOYO only. Fortnight input features contain
  no crop outputs. Every crop/source passes the unchanged release gates. Failed
  exact experiments stop training; failed release gates cannot advance latest.
- T8.4: known, evaluated weather requires an exact input hash and complete matching
  weather-only vector. Derived balances must equal validated P + fitted net input
  − validated ET0. Soil/irrigation component ranges keep their 2% margin. Regression
  tests reject unknown outlying weather, mismatches, invalid balances, excessive
  irrigation and failed models. All default replay/planning previews pass; exact
  confirmation was executed after the domain fix.
- T3.2/T3.6/T5.2–T5.6: kg/ha conversion and irrigation audits pass for wheat/cotton;
  every retained deliverable state references a real exact outcome and raw files.
  Undeliverable states preserve violations and null production. Publication
  collision/restoration tests preserve original metadata bytes and timestamps.
  Cached dominance views keep the existing criteria; repeated published hashes
  verify unchanged content. No physics or solver-rounding rule was changed.
- T4/T6: chronological and capacity rejections, independent water properties,
  original-precision reconstruction and conservative finite-model bounds pass.
  No fixture was added to production libraries. API contracts, persistence schema,
  dependency manifests and lockfiles are unchanged.
- GPU execution: the final LightGBM training ran on an RTX 5060 Laptop GPU through
  OpenCL, with actual process/device evidence. AquaCrop and CP-SAT remain CPU.
  Final checks: 397 fast, 85 domain, 45 science tests; lint passed.

Notes, not completion claims:

- `docs/P01_DOMAIN.md`, T5.4/T8.3: outcomes are simulated and uncalibrated. New
  release schedules were never fitted, but their weather years were inspected in
  prior release checks. Evidence explicitly records that limitation and prior
  failed GPU evaluations; it does not claim independent new weather-year trials
  or observed field prediction accuracy.
- The wider UI, reports and release acceptance queue remains in PROGRESS.md;
  none of the selected P01 requirements is deferred to that queue.
