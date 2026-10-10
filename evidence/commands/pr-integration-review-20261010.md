# PR integration review, 2026-10-10

The user authorized conflict resolution, a small review of all open PRs, merging, and rebuilding.

## Integrated work and fixes

PRs #5–#9 were independently reviewed and merged with merge commits into their existing stacked bases. The builder's PR #10 is the final integration into main; reviewer-created draft #11 is superseded, avoiding self-approval of that draft.

- Preserved all decision, onboarding, impact, ZIP, report, demo and copilot routes and the reviewed P02 provenance safeguards.
- Regenerated OpenAPI/TypeScript contracts; restored missing ReportAccepted, ReportCreate and ReportView definitions.
- Fixed malformed AOI parsing to return typed INVALID_INPUT errors, catching specific geometry/structure exceptions.
- Real onboarding tests may select a validated local acquisition of the same pilot AOI. Each acquisition retains its original timestamp and manifest; inference input/output hashes and the recorded CPU cache must still match.
- Preserved existing reviewed-v1 and reviewed-v2 manifests during raw reprocessing.
- Restored the vision config's committed LF bytes locally. Windows CRLF bytes had changed its hash and prevented reuse of the existing inference cache. No new inference or GPU execution was required.

## Executed validation

All commands ran in Docker; project dependencies were not installed on the host.

| Check | Executed result |
| --- | --- |
| Fast Python suite, final run | 623 passed, 1 skipped, 8 warnings in 114.81s |
| Science smoke | 45 passed in 1139.19s |
| Core acceptance v1 | 19 passed, 1 skipped in 14.96s; exit 0; g_core=false |
| Onboarding PR branch | 13 targeted cache, route, rejection and job checks passed |
| Reports/packages/impact PR branch | 38 checks passed |
| Frontend | 105 tests passed in 16 files |
| Frontend production build | Passed: TypeScript and Vite |
| E2E TypeScript | Passed |
| API contract generation | Runtime OpenAPI and TypeScript regenerated; combined source matches the validated integration |
| Ruff | Passed; only EXE002 excluded because Windows bind mounts report ordinary tracked files as executable |
| Browser smoke | Real pilot-a workspace: 30 fields, imagery, terrain, JSON API 404, healthy API; no page errors |
| Docker builds | api, web, e2e and frozen demo images built successfully |

Fast-suite stdout: pr-integration-python-20261010.log.
Browser screenshot: ../screenshots/pr-integration-windows-20261010.png.

## Limits

The existing exact-original-raw-bundle test skips because pilot-b bundle 20261010T003841Z-798d10d2 is absent. Real local bundle 20261010T123300Z-798d10d2 was validated and exercised through the cache/review/publish pipeline without fabricating historical provenance. The v1 runner reports AT01 partial; full original-bundle reproducibility and full acceptance are not claimed.

P06-service, P07-process and P08-zip are partial chunks; merging them and the later integration snapshot does not complete their parent gates. Core v1 leaves AT09–AT11 and AT13–AT18 unmarked, and does not unlock M7. No 30×3 copilot evaluation, public Vercel/Tunnel activation, machine reboot or full rollback was executed in this review.

npm ci reported six dependency audit advisories (two moderate, one high, three critical). This integration review does not establish that the locked dependency tree is free of advisories; no forced lockfile upgrade was performed.

Existing untracked evidence, real runtime data, Docker images and volumes were preserved.
