# AabFlow (khaitoman)

AICON hackathon build: irrigation and canal water-allocation planner. Full scope: F01–F20 and AT01–AT18. Never cut scope.

- Specs: `prd-flow-v2.md` (product), `aab-flow-tech-doc-v2.md` (implementation contract). `review/CHANGES.md` lists doc fixes. Change them only when pablo asks, and log each change in `review/CHANGES.md`.
- Repo layout follows tech doc T1.4. Backend package: `api/aabflow`. Frontend: `web/`.
- Everything runs in Docker Compose (`compose.yaml`, `Dockerfile`, `docker/vision.Dockerfile`). Only Docker is on the host; never install project deps on the host.
- Python: uv inside the `api` image, Python 3.11, locked by `uv.lock` (`exclude-newer` in pyproject). Vision (Delineate Anything) is its own image; never mix them.
- Node 24 inside the `web` image, locked by `web/package-lock.json`. `@playwright/test` is pinned exactly to match the Playwright image tag in `Dockerfile`.
- Two contributors share the repo. Dependency changes: edit manifest, `make lock`, `make build`, commit both lockfiles.
- AquaCrop: import from submodules (`aquacrop.core`, `aquacrop.entities.*`, `aquacrop.utils.*`). Its `__init__` skips exports whenever `-m` is in `sys.argv` (e.g. `pytest -m`, `python -m`).
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

- Queue-wide parallel development uses `docs/AGENT_WORKFLOW.md` and the complete DAG in `docs/agent-dag.json`; Cursor commands are `/aabflow-build`, `/aabflow-resume`, `/aabflow-status`. Use isolated local worker worktrees, at most six direct subagents, explicit file ownership and global resource leases. Parent owns shared contracts/integration. Full non-chat acceptance precedes copilot implementation/evaluation; partial UI gates do not pass AT13/AT14. Preserve every chunk and independent human review.
- **"ai continue"**: when the user says it, follow `docs/CONTINUE.md`. It detects the role (builder or reviewer) and takes the next step from `docs/PROGRESS.md` (PR queue) and `docs/REVIEW_PLAN.md` (reviewer checklist and milestone gates).
- PR workflow (`docs/WORKFLOW.md`): KM-Alee builds, Aounuman (`Sipra-Aoun`) reviews. Never commit or push to `main`. Work on a branch and finish with `/ship`, which opens a PR. Reviews use `/review-pr <n>`: fix gaps on the PR branch, file `gap` issues for the rest, merge with a merge commit. No rebase or force-push of pushed branches.
- Real data and executed pipelines only; fixtures are for tests and must be labelled.
- Prefer the available GPU for supported workloads. Use `make train-surrogate GPU=1` for LightGBM training through `compose.gpu.yaml`; record the device and executed evaluation. AquaCrop and CP-SAT keep their current CPU backends. Do not claim GPU use from configuration alone.
- **No unfinished work held back.** Complete every requirement, rejection case, and validation in the selected chunk before shipping. Fix all actionable self-review findings, including should-fix items; do not defer them to the reviewer, a later PR, or a gap issue just to finish sooner. Keep working through root causes until the required checks pass. Only a concrete external blocker or an explicit user decision can leave requested work incomplete; report it honestly and never claim completion. Statistical held-out data and tests remain mandatory where the specs require them.

## Claude Code workflow (`.claude/`)

- Progress lives in `docs/STATUS.md` (M0–M8, F01–F20, AT01–AT18). Update rows only with evidence, in the same commit as the work.
- Slash commands: `/milestone M2`, `/feature F05`, `/acceptance`, `/fix <error>`, `/spec <question>`, `/status`, `/ship [ID]` (open a PR), `/review-pr <n>` (review, fix and merge).
- Subagents for parallel work after schemas freeze (T13.2): `data-engineer`, `science-engineer`, `optimizer-engineer`, `frontend-engineer`; `spec-auditor` reviews diffs read-only. The main session owns shared contracts and integration.
- Hooks: `git_guard.sh` blocks commits on `main`, pushes to `main` and force-pushes; edited `.py` files are ruff-formatted/fixed in the api container (remaining errors come back to fix); before stopping, `make test` and web typecheck/vitest run for uncommitted changes and must pass.
- `.env` is unreadable by Claude by design; `gh pr merge` asks first.
