# AabFlow (khaitoman)

AICON hackathon build: irrigation and canal water-allocation planner. Full scope: F01–F20 and AT01–AT18. Never cut scope.

- Specs: `prd-flow-v2.md` (product), `aab-flow-tech-doc-v2.md` (implementation contract). `review/CHANGES.md` lists doc fixes. Change them only when pablo asks, and log each change in `review/CHANGES.md`.
- Repo layout follows tech doc T1.4. Backend package: `api/aabflow`. Frontend: `web/`.
- Everything runs in Docker Compose (`compose.yaml`, `Dockerfile`, `docker/vision.Dockerfile`). Only Docker is on the host; never install project deps on the host.
- Python: uv inside the `api` image, Python 3.11, locked by `uv.lock` (`exclude-newer` in pyproject). Vision (Delineate Anything) is its own image; never mix them.
- Node 24 inside the `web` image, locked by `web/package-lock.json`. `@playwright/test` is pinned exactly to match the Playwright image tag in `Dockerfile`.
- Two contributors share the repo. Dependency changes: edit manifest, `make lock`, `make build`, commit both lockfiles.
- Persistence: stdlib `sqlite3` + `api/aabflow/repositories/sqlite/schema.sql` (bump `schema_version` in `meta` on change).
- All API routes under `/api/v2`. Unknown API paths return JSON 404.

## Commands

- `./scripts/setup.sh` builds all images, fetches weights and runs checks (pablo runs installs themselves). `make help` lists targets.
- `make up` / `make down`: api :8000 (reload) + web :5173. `make shell` for a bash in the api container.
- `make test` (fast), `make science-smoke` (real AquaCrop), `make web-test`, `make web-build`, `make doctor`.
- `make demo` runs the frozen `app` image. `make ui-checks` runs Playwright against it.
- `make contracts` regenerates `contracts/openapi.json` and `web/src/generated/api.ts`.
- Unbuilt Make targets exit 1 with "not implemented yet"; replace them as features land. No target may print success without doing the work.

## Working rules

- Local git commits only; no remote push.
- Real data and executed pipelines only; fixtures are for tests and must be labelled.
