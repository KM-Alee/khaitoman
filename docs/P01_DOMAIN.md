# P01 domain libraries

Pilot-b's `reviewed-v1` package now has exact libraries for all four published seasons.
The build uses its own archived weather grid (30.7000 N, 72.2000 E), reviewed
field geometry, declared roster/assets/costs, and the real AquaCrop adapter.
It retains 9,736 policies across 30 fields and all admissible repair configurations.
Planning seasons contain three weather analogs × three supply profiles; historical
replay additionally includes actual archived weather, for twelve states.

| Season | Retained policies | Configurations | Options per field/configuration |
|---|---:|---:|---:|
| Wheat 2026–27 | 854 | 1 | 24–39 |
| Wheat 2027–28 | 3,913 | 4 | 24–46 |
| Cotton 2027 | 4,096 | 4 | 28–46 |
| Wheat replay 2024–25 | 873 | 1 | 24–40 |

## Reproduce

On a fresh checkout with the Docker images and pilot packages available:

```sh
make candidates PILOT=pilot-a
make candidates PILOT=pilot-b
make domain-tests
make science-smoke
make test
```

The ignored `policies.jsonl` and crop experiment files must be regenerated; missing
artifacts fail the domain gate. A repeated build checks immutable metadata and
policies before publishing, preserves the original creation timestamp, and can
restore a missing policy dump without rewriting the publication metadata.
Runtime/cache statistics from each invocation are saved separately under
`evidence/benchmarks/science-library-pilot-b-*.json`.

## Calendar coverage regression

Publishing pilot-b's weather exposed two default surrogate previews outside the
old training range: the final weather window of wheat 2027–28 contains an extra
day when a non-leap analog is mapped onto a leap-year calendar. `surrogate-v2`
adds exact experiments on published calendars. Mapped experiments retain their
original weather-year labels for splitting; held-out weather cannot leak into
training through a new calendar label. `surrogate-v1` remains available.

The new models keep the existing feature definition, domain tolerance, evaluation
thresholds, and out-of-domain refusal. `make train-surrogate` regenerates v2;
the regression and preview tests check the current published version.

## Limits of this evidence

The crop yields are simulated and uncalibrated. The library option counts describe
a finite candidate model; a denser-library objective/action stability comparison
has not been executed here (T5.7). Wheat's final test season (2025–26) has
discovery-source samples only because the pilot archives end in 2025; cotton's
2025 test contains all three sources. Additional wheat pilot holdouts and
per-pilot error reporting remain a review gap for P04/T8.3. This work does not
mark the entire M2 milestone or F12 complete.
