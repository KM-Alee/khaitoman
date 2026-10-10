# AGENTS.md: AabFlow (khaitoman)

Instructions for any coding agent (Codex, Cursor, Gemini, Copilot, Claude Code and others). `CLAUDE.md` holds the same rules for Claude Code, and `.claude/commands/*.md` are the source of the commands below. If you change one, change the other in the same PR.

## Project rules

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

### Make targets

- `./scripts/setup.sh` builds all images, fetches weights and runs checks (pablo runs installs themselves). `make help` lists targets.
- `make up` / `make down`: api :8000 (reload) + web :5173. `make shell` for a bash in the api container.
- `make test` (fast), `make science-smoke` (real AquaCrop), `make web-test`, `make web-build`, `make doctor`.
- `make demo` runs the frozen `app` image. `make ui-checks` runs Playwright against it.
- `make contracts` regenerates `contracts/openapi.json` and `web/src/generated/api.ts`.
- Unbuilt Make targets exit 1 with "not implemented yet"; replace them as features land. No target may print success without doing the work.

### Working rules

- **"ai continue"**: when the user says it, follow `docs/CONTINUE.md`. It detects the role (builder or reviewer) and takes the next step from `docs/PROGRESS.md` (PR queue) and `docs/REVIEW_PLAN.md` (reviewer checklist and milestone gates).
- PR workflow (`docs/WORKFLOW.md`): KM-Alee builds, Aounuman (`Sipra-Aoun`) reviews. Never commit or push to `main`. Work on a branch and finish with `/ship`, which opens a PR. Reviews use `/review-pr <n>`: fix gaps on the PR branch, file `gap` issues for the rest, merge with a merge commit. No rebase or force-push of pushed branches.
- Real data and executed pipelines only; fixtures are for tests and must be labelled.
- Prefer the available GPU for supported workloads. Use `make train-surrogate GPU=1` for LightGBM training through `compose.gpu.yaml`; record the device and executed evaluation. AquaCrop and CP-SAT keep their current CPU backends. Do not claim GPU use from configuration alone.
- **No unfinished work held back.** Complete every requirement, rejection case, and validation in the selected chunk before shipping. Fix all actionable self-review findings, including should-fix items; do not defer them to the reviewer, a later PR, or a gap issue just to finish sooner. Keep working through root causes until the required checks pass. Only a concrete external blocker or an explicit user decision can leave requested work incomplete; report it honestly and never claim completion. Statistical held-out data and tests remain mandatory where the specs require them.

## Guardrails other agents must enforce themselves

Claude Code enforces these with hooks in `.claude/settings.json`. Without those hooks, follow them by hand:

- Never commit on `main`, push to `main`, force-push, or rebase a pushed branch (`scripts/hooks/git_guard.sh`).
- Never read `.env` or `.env.*`, and never write a key into a tracked file.
- After editing Python, run `docker compose run --rm --no-deps -T api sh -c "ruff check --fix <paths> && ruff format <paths>"` and fix what remains.
- Before finishing with uncommitted changes, run `make test`, plus `make web-test` when `web/` changed. Both must pass.
- Ask the user before `gh pr merge`, `git merge`, `gh issue close`, deleting Docker images or volumes, or editing `prd-flow-v2.md` / `aab-flow-tech-doc-v2.md`. Never edit `review/originals/**`.
- `spec-auditor` (`.claude/agents/spec-auditor.md`) is a read-only spec review. Where a command says to run it, do that review yourself by following that file.

## Commands

Say a command's name (for example "ship", "review-pr 12", "feature F05") and the agent runs its steps. `<args>` is whatever follows the name.

### ai continue [builder | reviewer] [notes]

_Detect the role and do the next step from `docs/PROGRESS.md`._ Source: `docs/CONTINUE.md`.

When someone says **"ai continue"** (optionally followed by `builder` or `reviewer` and notes), do the next step of the AabFlow build for their role, using these steps. `CLAUDE.md` points here. A copy can also live at `.claude/commands/continue.md` as the `/continue` slash command, with `$ARGUMENTS` as the role and notes.

#### 1. Role

Decide the role, first match wins, and say which one you picked and why in one line:

1. A role word after "ai continue" (or the `/continue` argument): `builder` or `reviewer`.
2. `git config --get aabflow.role` (each person can set it once: `git config aabflow.role reviewer`).
3. `gh api user --jq .login`: `Sipra-Aoun` → reviewer, `KM-Alee` → builder.
4. Otherwise ask once which role, and tell them to set `git config aabflow.role <role>`.

#### 2. Sync

`git status`. If there are uncommitted changes you didn't make, stop and ask what they are; never stash or discard them. Then `git fetch origin`, `gh pr list --json number,title,headRefName,baseRefName,isDraft,reviewDecision,author`, and `gh issue list --label gap`. Read `docs/PROGRESS.md` (queue), `docs/STATUS.md` (evidence) and, as reviewer, `docs/REVIEW_PLAN.md`.

The PR list is the truth for the queue. If a row in PROGRESS.md disagrees with GitHub (a merged PR still marked `review`, a pushed branch still marked `todo`), trust GitHub and correct the row in your next commit.

#### 3a. Builder

Pick the first of these that applies, then do it end to end:

1. **Your PR has changes requested.** Check out its branch, address every review comment, push, re-request review.
2. **An open `gap` issue** on merged work. Fix it on a `fix/` branch, PR says `Closes #n`.
3. **The next `todo` row** in the PROGRESS.md queue whose **Needs** are `done`. If a Need is only `review #n`, stack on that PR's branch (`--base` it). Before starting, make sure nobody else has it: no open PR and no `origin/*pNN*` branch for that ID. If someone does, take the next row.

For a queue row: branch `feat/pNN-<slug>`, set the row to `building`, then build it the way `/feature` and `/milestone` describe (specs first, full scope, tests for every rule including rejections, real data). Finish with `/ship`; the PR title starts with `PNN`, and the PR sets the row to `review #n`. Then, if your usage allows, continue with the next row (stacked if it needs this one) instead of stopping.

Never review or merge your own PR.

#### 3b. Reviewer

1. **A PR waits for your review** (`gh pr list --search "review-requested:@me" --draft=false`; oldest first, stacked parent before child). Run `/review-pr <n>` using that PR's row in `docs/REVIEW_PLAN.md` §1 as the checklist. In your last `review(PNN): ...` commit, set the PROGRESS.md row to `done #n`. Merge only after the user confirms.
2. **A milestone just completed** (all its rows `done`) and its gate in REVIEW_PLAN.md §2 hasn't run. Run the gate on `main` and record it as that section says.
3. **Nothing waiting.** Audit the most recently merged PR against its spec sections and file `gap` issues for what's missing, or say there's nothing to review and what the builder is on.

Never build queue items as reviewer.

#### 4. Report

Finish in under 10 lines: role, what you did (PR URL or issue numbers), checks run with result lines, what's next for this role, and anything waiting on the other person.

### status

_Where the build stands and what to do next._ Source: `.claude/commands/status.md`.

Summarize AabFlow progress.

Read `docs/STATUS.md`, `git log --oneline -15`, `git status`, `gh pr list` and `gh issue list --label gap`. Report in under 15 lines: current milestone and its open items, features/ATs passed so far (count and IDs), anything failing or blocked, uncommitted work, open PRs and their review state, open `gap` issues, and the single next step. Compare against the tech doc T13.1 schedule if the user gives a start time.

### feature <Fxx> [extra notes]

_Implement one feature (F01–F20) fully, with tests and status update._ Source: `.claude/commands/feature.md`.

Implement feature `<args>` for AabFlow.

1. Find the feature in PRD §3 and its detailed PRD section, then every tech-doc section that implements it (grep the ID and its key nouns in `aab-flow-tech-doc-v2.md`). Note the acceptance tests it feeds.
2. Check `docs/STATUS.md` and existing code under `api/aabflow` and `web/src` so you extend rather than duplicate.
3. Implement backend domain logic first (typed Pydantic schemas, units from `aabflow.domain.units`, hashes from `aabflow.domain.hashes`), then API routes under `/api/v2`, then UI.
4. Add tests for each rule the specs list, including the rejection cases. Run the relevant make targets until green.
5. If the API changed, run `make contracts` so `web/src/generated/api.ts` matches.
6. Work on a branch (`feat/<id>-<slug>`, never `main`). Update the feature's row in `docs/STATUS.md` with evidence, then finish with the `/ship` steps (the **ship** command below) to open the PR for review. Report the PR URL, what was built, and what remains.

### milestone <M0..M8>

_Build a whole milestone (M0–M8) end to end against the specs._ Source: `.claude/commands/milestone.md`.

Build milestone `<args>` for AabFlow.

1. Read `docs/STATUS.md`, the milestone's row in PRD §12 (`prd-flow-v2.md`) and its row in tech doc T13.1 (`aab-flow-tech-doc-v2.md`). List every feature (Fxx) and acceptance test (ATxx) it owns, plus any earlier milestone still open that it depends on.
2. For each owned item, read the PRD section and tech-doc sections that define it. Quote nothing back; extract the concrete requirements, invariants, and listed tests.
3. Write a short ordered plan (as a todo list) that covers every requirement. Do not drop or shrink scope. Where the specs leave a detail open, pick the default closest to existing code and note it.
4. Implement in dependency order. Independent workstreams (data / science / optimizer+API / UI, per T13.2) can go to the matching subagents in parallel once shared schemas exist; you own integration and shared contracts.
5. Every requirement gets a test (pytest under `tests/`, vitest beside the component, Playwright in `tests/e2e`). Use real data and executed pipelines; fixtures only in tests and labelled as such.
6. Run `make test`, `make science-smoke` (if science changed), `make web-test` and `make web-build` (if web changed). Fix failures from the root cause.
7. Update `docs/STATUS.md` rows with status and evidence (command and result, artifact path). Replace any `not implemented yet` Make target you made real.
8. Work on branches, never `main`. Open one PR per feature or coherent workstream as it lands (`/ship` steps in the **ship** command below), not one giant PR. Keep building while earlier PRs are in review. Stack dependent branches on the open PR branch as described in `docs/WORKFLOW.md`.
9. Finish with: the PRs opened (URLs), what passed (with evidence), what is still open in this milestone and why, and the next milestone's first step.

### acceptance

_Run every available check and refresh AT01–AT18 status with evidence._ Source: `.claude/commands/acceptance.md`.

Run the AabFlow acceptance sweep.

1. Run `make doctor`, `make test`, `make science-smoke`, `make web-test`, `make web-build`. Also run any of `make water-tests domain-tests core-acceptance ui-checks` that are implemented (an unimplemented target exits 1 with "not implemented yet"; record that, don't treat it as a code failure).
2. For each AT01–AT18 in `docs/STATUS.md`, decide passed / failed / not_started / blocked strictly from executed evidence: a test that exercises it, its output, or a saved artifact. No evidence means not passed.
3. Save the combined output to `evidence/commands/acceptance-<UTC timestamp>.log`.
4. Update `docs/STATUS.md` on a branch `chore/acceptance-<UTC date>`, open a PR with the `/ship` steps, and report the PR URL, a table of AT IDs with status and the one-line reason, then the top three blockers.

### fix <command or error>

_Debug a failing command, test, build, or container to its root cause._ Source: `.claude/commands/fix.md`.

Something is failing: `<args>`

1. Reproduce it exactly (inside Docker via the Make target or `docker compose run --rm --no-deps <service> ...`). Capture the full error.
2. Find the root cause: read the failing code, the library source inside the container if needed (`/opt/venv/lib/python3.11/site-packages/...`), and recent `git log -p` for related changes. Don't guess.
3. Fix the cause, not the symptom. No skipped tests, broad excepts, version downgrades, or weakened assertions unless the cause truly is the dependency, in which case pin it in the manifest, run `make lock build`, and say why.
4. Re-run the original command plus `make test`. Add a regression test when the bug was in our code.
5. If the cause is non-obvious and will bite again, add one line about it to `CLAUDE.md`.
6. Commit on the current branch (if on `main`, `git switch -c fix/<slug>` first). If that branch isn't already an open PR under review, open one with the `/ship` steps. Explain the cause and fix in two or three sentences.

### spec <question>

_Answer a question from the PRD and tech doc with section citations._ Source: `.claude/commands/spec.md`.

Answer from the specs only: `<args>`

Search `prd-flow-v2.md`, `aab-flow-tech-doc-v2.md` and `review/CHANGES.md`. Give the answer first, then cite the section numbers it comes from (e.g. "PRD §6.4, T6.5"). If the docs disagree or are silent, say so and state which document is authoritative (PRD for product scope, tech doc for implementation). Don't change any code.

### ship [Fxx | Mx | short title] [notes]

_Open a PR for the current work so Aounuman can review it (builder side of docs/WORKFLOW.md)._ Source: `.claude/commands/ship.md`.

Ship the current work as a pull request: `<args>`

This is the builder half of `docs/WORKFLOW.md`. Once the PR is open, the reviewer owns the branch.

1. **Branch.** On `main`: `git fetch origin`, then `git switch -c <type>/<id>-<slug>` (type is feat, fix, chore or docs, e.g. `feat/f05-pond-ledger`). Uncommitted work comes along. On a branch with no PR yet: use it. On a branch whose PR is already open (`gh pr view` succeeds): don't touch it; branch from it and stack. If the work depends on another unmerged PR, branch from that PR's branch and use it as `--base` in step 6.
2. **Checks.** Run the checks for every area the diff touches: Python → `make test`; science/water/candidates → `make science-smoke`; web → `make web-test` and `make web-build`; API routes or schemas → `make contracts` and commit the regenerated files. Keep each command's final result line for the PR body. Fix failures from the root cause and finish all required validation before shipping. A concrete external blocker may be recorded in a draft PR, but a fixable failure is not a reason to stop.
3. **Self-review.** Follow `.claude/agents/spec-auditor.md` on `git diff origin/<base>...HEAD` plus uncommitted changes. Fix every actionable blocker and should-fix finding before shipping. Do not hand fixable work to the reviewer.
4. **STATUS.** Update only the `docs/STATUS.md` rows this work moves, each with evidence.
5. **Commit.** Use small logical commits, with messages like `F05: <what>`. Never commit on `main` (the hook blocks it).
6. **Open the PR.** `git push -u origin HEAD`. Write the body in the scratchpad from `.github/pull_request_template.md`, then run `gh pr create --base <main or parent branch> --reviewer Sipra-Aoun --assignee @me --title "<ID>: <summary>" --body-file <file>` (add `--draft` if step 2 left a failure). Add `Closes #n` for every `gap` issue it resolves.
7. **Next.** Report the PR URL and a one-line summary. Then run `git switch main && git pull --ff-only` so the next work starts clean, unless the next task stacks on this branch.

The PR body must be honest. The reviewer works from **Known gaps** and **Unverified** first, so list every stub, TODO, skipped or missing test, default you picked where the specs are silent, and every path you never executed. Claim nothing as passing unless the command output backs it.

### review-pr <PR number> [focus notes]

_Review a PR (reviewer side of docs/WORKFLOW.md) by verifying it, fixing gaps on the branch, filing issues for the rest, then approving._ Source: `.claude/commands/review-pr.md`.

Review pull request `<args>`. The reviewer's job is to fill gaps and fix errors, not just comment on them.

1. **Load.** `git status` must be clean (if it isn't, stop and ask). `git fetch origin`, `gh pr view <n> --comments`, `gh pr checkout <n>`. Read the body. **Known gaps** and **Unverified** are your starting list. Find each Fxx/Mx/ATxx in the title in the PRD and the tech doc (`/spec` style) so you review against the requirements, not just the diff.
2. **Bring it current.** If the branch is behind its base, `git merge origin/<base>`. Never rebase. For `docs/STATUS.md` conflicts, keep whichever row has executed evidence.
3. **Verify independently.** Re-run the checks the PR claims, plus the ones for every touched area (`make test`, `make science-smoke`, `make web-test`, `make web-build`, `make contracts` with a clean diff afterwards). Run the `spec-auditor` subagent on `git diff origin/<base>...HEAD`. Then read the diff yourself and look for: scope dropped or stubbed as success, fixtures in non-test code, spec rules without tests (including rejection cases), STATUS rows that claim more than the evidence, generated contracts out of date, and claims in the body that don't match what you ran.
4. **Triage every finding.**
   - **Fix now** anything that fits in this PR: errors, spec violations, missing tests, the PR's own known gaps. Use one commit per fix (`review(<ID>): <what>`) and re-run the affected checks.
   - **File an issue** for gaps too large for this PR: `gh issue create --label gap --title "<ID>: <gap>" --body "<spec section, file:line, concrete failure, Found in #<n>>"`. If the label is missing, create it first: `gh label create gap --color d93f0b --description "Spec gap found in review"`.
   - **Correct** STATUS rows that overclaim.
5. **Push** to the PR branch with `git push`. Never push to `main`.
6. **Decide.**
   - Everything fixed or filed and checks green: run `gh pr review <n> --approve --body-file <file>` with these sections: **Fixed** (short sha and one line each), **Issues filed** (#s), **Verified** (commands and their results), **Remaining risk**.
   - The approach itself is wrong (a rework, not a patch): run `gh pr review <n> --request-changes` saying what to redo and why, then stop. The branch goes back to the builder.
7. **Merge** an approved PR after confirming with the user: `gh pr merge <n> --merge --delete-branch`, then `git switch main && git pull --ff-only`. If another open PR was stacked on this branch, say so. It needs `origin/main` merged in next.
