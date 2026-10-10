# P01 domain libraries

Both reviewed pilots now have exact libraries for all four published seasons.
Pilot-b uses its own archived grid (30.7000 N, 72.2000 E), reviewed geometry,
roster/assets/costs and the real AquaCrop adapter. It retains 17,480 policies
across 30 fields and every admissible repair configuration. Pilot-a retains
17,511. Planning seasons contain three weather analogs × three supply profiles;
historical replay adds actual archived weather, for twelve states.

| Pilot | Season | Retained policies | Options per field/configuration |
|---|---|---:|---:|
| pilot-a | cotton-kharif-2027 | 8,034 | 51–98 |
| pilot-a | wheat-rabi-2024-25 | 876 | 24–40 |
| pilot-a | wheat-rabi-2026-27 | 856 | 24–40 |
| pilot-a | wheat-rabi-2027-28 | 7,745 | 45–98 |
| pilot-b | cotton-kharif-2027 | 8,024 | 51–98 |
| pilot-b | wheat-rabi-2024-25 | 873 | 24–40 |
| pilot-b | wheat-rabi-2026-27 | 854 | 24–39 |
| pilot-b | wheat-rabi-2027-28 | 7,729 | 46–96 |

## Executed density comparison (T5.7)

`make library-adequacy` completed 20 paired comparisons (40 proved optimal
CP-SAT solves): both pilots, representative wheat/cotton seasons, no capital,
small budget, capital, shortage and a nine-state robust portfolio. Every selected
portfolio was reconstructed with original float precision and budget/service
checks. The larger library never reduced the integer finite-model objective.

| Pilot | Representative season | Coarse → retained policies | Investment changed |
|---|---|---:|---:|
| pilot-a | cotton-kharif-2027 | 4,096 → 8,034 | 2/5 |
| pilot-a | wheat-rabi-2027-28 | 3,909 → 7,745 | 0/5 |
| pilot-b | cotton-kharif-2027 | 4,096 → 8,024 | 2/5 |
| pilot-b | wheat-rabi-2027-28 | 3,913 → 7,729 | 2/5 |

Six comparisons changed investment decisions, and nineteen changed schedules.
The larger exact libraries are retained for all four representative cases.
`adequacy.json` records each request, before/after objective, configuration,
investment, policy selection, spending, validated states and optimal bound.
`density.json` pins the recipe and baseline hash. Normal candidate builds use
that retained recipe, including on a fresh checkout. The comparison establishes
observed sensitivity to a finite library; it does not prove a continuous-schedule
optimum.

## Reproduce

```sh
make candidates PILOT=pilot-a
make candidates PILOT=pilot-b
make library-adequacy
make train-surrogate GPU=1
make domain-tests
make science-smoke
make test
make lint
```

All commands run in Docker. Ignored policy dumps and crop experiments must be
regenerated; missing artifacts fail the domain gate. Publication preserves the
original metadata bytes/timestamp and refuses changed content under the same
hash. A build restores a missing policy dump and saves current cache/runtime
statistics separately. Dominance comparisons cache immutable resource views
without changing the criteria; repeated published hashes check this in real data.

## Surrogate calendar and pilot evaluation

Mapped analog experiments keep their original weather-year split assignment,
including leap-year target calendars. The final release year is shared by all
sources (wheat 2024–25, cotton 2025); earlier years alone are fitted. The irregular
schedule family is also excluded from fitting. Each pilot has separate soil,
ranking, baseline and decision-regret metrics so pooled results cannot hide a
pilot failure. Architecture selection and additive bias correction use development
year cross-validation only. Failed crop executions fail training, and failed
release gates cannot advance the model pointer.

The v7 feature definition uses fortnight input windows with rain/heat-day counts
to preserve weather and application timing. No crop output enters features.
Validated held-out weather input hashes and complete weather-only vectors can
pass the preview domain check; soil and irrigation component ranges remain
fitting-only with the existing 2% margin. Derived balance values use the validated
P/ET0 offset and still require fitted net-water components. Out-of-range unknown weather, mismatched vectors,
unsupported soil, extreme irrigation and failed models still refuse estimates.

`make train-surrogate GPU=1` uses the NVIDIA GeForce RTX 5060 Laptop GPU via
OpenCL. Actual running GPU process/device evidence accompanies the executed
evaluation. AquaCrop and CP-SAT execute on CPU. CPU training remains available
with `make train-surrogate` but is not claimed as executed for the final version.

Prior release weather years have been inspected during development; new release
schedule designs are never fitted, but are not independent weather-year draws.
Earlier GPU failures and their per-pilot gates are preserved in
`evidence/benchmarks/p01-gpu-development-attempts.json`. Final results and command
logs accompany the released model. Old committed model versions remain archived.

The yields remain simulated and uncalibrated. This P01 work completes its selected
backend library, rejection and validation requirements; the wider UI and release
queue remains tracked separately in `docs/PROGRESS.md`.

Final checks: 397 fast, 85 domain and 45 science tests passed; lint passed.
Command/device evidence: `evidence/commands/p01-complete-20261010T075535Z.log`.
