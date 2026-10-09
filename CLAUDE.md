# AabFlow (khaitoman)

AICON hackathon build: irrigation and canal water-allocation planner. Full scope: F01–F20 and AT01–AT18. Never cut scope.

- Specs: `prd-flow-v2.md` (product), `aab-flow-tech-doc-v2.md` (implementation contract). `review/CHANGES.md` lists doc fixes. Do not edit or move these.
- Repo layout follows tech doc T1.4. Backend package: `api/aabflow`. Frontend: `web/`.
- Python: uv only, Python 3.11, main env `.venv` from `pyproject.toml`/`uv.lock`. Vision (Delineate Anything) has its own `.venv-vision`; never mix them. Never install into the system Python.
- Node 24, npm with `web/package-lock.json`.
- Persistence: stdlib `sqlite3` + `api/aabflow/repositories/sqlite/schema.sql` (bump `schema_version` in `meta` on change).
- All API routes under `/api/v2`. Unknown API paths return JSON 404.

## Commands

- `./scripts/setup.sh` installs everything (pablo runs it). `make doctor` checks the toolchain.
- `make test` (fast), `make science-smoke` (real AquaCrop), `make web-test`, `make web-build`.
- `make dev-api` (:8000) + `make dev-web` (:5173 proxy). `make demo` serves the frozen build.
- `make contracts` regenerates `contracts/openapi.json` and `web/src/generated/api.ts`.
- Unbuilt Make targets exit 1 with "not implemented yet"; replace them as features land. No target may print success without doing the work.

## Working rules

- Local git commits only; no remote push.
- Real data and executed pipelines only; fixtures are for tests and must be labelled.
