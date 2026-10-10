# G-CONTRACT inventory (2026-10-10)

Executed on `chore/cursor-dag-workflow` at `ad11be3c8698e759f4a3d6d76cc53844faba3478` (product tree). This commit adds the record only.

Parent model requested: `grok-4.7[effort=high,context=500k,fast=false]`. Session identity: Grok 4.7. Child task cards are inspected at dispatch.

## Checks

- `make test`: 463 passed, 3 warnings, 28.98s. Log: `evidence/commands/g-contract-test-20261010T091932Z.log`.
- `make contracts`: exit 0. `git diff` on `contracts/openapi.json` and `web/src/generated/api.ts` was empty. Log: `evidence/commands/g-contract-contracts-20261010T092023Z.log`.
- DAG validate: 27 nodes, 14 chunks. Plan after P00 merged and P01 in review: only `G-CONTRACT` was ready. Log: `evidence/commands/g-contract-dag-20261010T091932Z.log`.
- Waves output is a forecast, not execution evidence.

## Ancestor SHAs

| Snapshot | SHA | State |
|---|---|---|
| P00 merge (PR #2) | `6c7d7218d2566b6720434f8c6c834b91e662c92c` | merged 2026-10-10T06:55:11Z; ancestor of this branch after `ad11be3` |
| P00 feature tip | `37ecb1aa3d834ee00e9d11a97711109c93a8aa65` | ancestor |
| P01 (PR #3) | `b2fb680539a8d0a683e8e9542407afad975706c4` | open, review pending Sipra-Aoun; ancestor; do not duplicate |
| Worker-runtime base | `ad11be3c8698e759f4a3d6d76cc53844faba3478` | this branch before the evidence commit |

## Images and locks (parent tags)

- `aabflow-dev:local` `sha256:eeed98a6495ffe82e5d022801c3af9507f935f358f73fcb4acebd8075ab904f6`
- `aabflow-web-dev:local` `sha256:a2edb2249aca51693cb9092f6b8efcdf57ab9277400185ce9d87bbe87c998324`
- `aabflow:local` `sha256:da949d774f3f56143546c459547b78ea4e15ac60e5c28b11b47ee5cf5fbdaaa3`
- `aabflow-e2e:local` `sha256:ee83158eea607b75fb4419e571a7592505e2b7932a0b9e7d03cb6c7725fa0422`
- `uv.lock` `a416c2776d54164afec312cdcb11d2518ec288637532f6bec81370338644456e`
- `web/package-lock.json` `dee1dade833b811737ec69ae830e77505b87acab9d3a7b237b536c3a3fd5f244`

Worker slots: 1 API/demo 18001 web 15171; 2 API/demo 18002 web 15172; 3 API/demo 18003 web 15173. Host 8000 and 5173 are the primary stack. 18001–18003 and 15171–15173 were free at assignment.

## Frozen shapes (source of truth)

- `MetricValue` and `MetricStatus`: `api/aabflow/domain/schemas/evidence.py`. Status is `available`, `not_estimated`, `not_applicable`, or `blocked`.
- Metric formulas: `api/aabflow/services/metrics/__init__.py`, `METRICS_VERSION=metrics-1.0.0`. Reports, UI, and copilot read these values. They do not recompute them.
- Runs: `PlanRun` / `NoPlanRun` / `InvalidPlanRun` in `api/aabflow/domain/schemas/run.py`. Outcomes stay distinct. Proof scope is `finite_candidate_library`.
- Jobs: `Job` / `JobState` in the same module. States include `interrupted`. Dispatcher: `api/aabflow/jobs/worker/__init__.py`.
- Pilots: `Pilot`, `ReviewFlags`, `ImageryRef` in `api/aabflow/domain/schemas/pilot.py`. Published index: `data/pilots/index.json` (`pilot-a` and `pilot-b`, `reviewed-v1`).
- SQLite `schema_version` 2 in `api/aabflow/repositories/sqlite/schema.sql`. Tables already include `reports` and `onboarding`. No migration in this gate.

## Routes present

Registered in `api/aabflow/main.py`: system, pilots, jobs, scenarios, runs, analyses, surrogate, copilot. Unknown `/api/v2/*` returns JSON 404.

## Stubs (not complete)

- No `api/aabflow/services/reports`, `services/onboarding`, or `services/impact` package.
- No `api/aabflow/api/reports.py` or onboarding router.
- Job map already names missing handlers: `report` → `aabflow.services.reports:report_job`, `onboarding.process` → `aabflow.services.onboarding:process_job`.
- `POST /api/v2/reports` is absent. Copilot `create_report` already posts `{run_ids, analysis_ids, report_type}` with `Idempotency-Key` and expects `report_id`, `job_id`, then `job`, and GET fields `status`, `report_type`, `run_ids`, `download_url`, `created_at`. Live copilot evaluation stays after G-CORE.
- `make core-acceptance`, `make copilot-evals`, and `make release-check` still exit 1 with "not implemented yet".

## Owners

- Lead: domain schemas, `main.py` router list, job-handler map, schema version, OpenAPI/TS, Make/Compose/Docker, STATUS/PROGRESS, leases.
- P02 data-engineer: ingestion, `scripts/publish_pilot.py`, `tests/integration/test_pilot_packages.py`, published pilot bytes only when a reproduction command writes them.
- P05-api optimizer-engineer: `services/reports/**`, `api/reports.py`, report tests. Router registration is a lead edit after the module exists.
- One writer per checkout. Contract edits are serial and recorded with the resulting SHA.

## Invalidation

A change to domain metrics, run/pilot/report schemas, job states, published package hashes, or generated contracts invalidates descendant evidence. Reset those nodes in one checkpoint write and keep prior PR/SHA history.
