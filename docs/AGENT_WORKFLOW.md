# AabFlow agent DAG workflow

This is the execution workflow for the remaining P02–P13 queue. It preserves F01–F20 and AT01–AT18, the builder/reviewer split, real data and every rejection case. It prepares Cursor to do the development; installing these files does not mean the remaining product work has passed.

## Start in Cursor

Open this repository in a local Cursor Agent session. Select **Grok 4.7, High, 500k context, Fast off** for the parent. Run **`/aabflow-build`**. For an interrupted session use **`/aabflow-resume`**; **`/aabflow-status`** reports the current frontier without starting work. The parent is the integrator. It uses the named data, science, optimizer, frontend, verifier and spec-auditor agents in `.cursor/agents/`, with at most **six active children**. Verifiers/auditors count against that limit too. Science and GPU stay one at a time. Children do not recursively delegate.

All custom agents request `grok-4.7[effort=high,context=500k,fast=false]`. The parent picker must be set separately. Inspect each task card's actual model and record it in the handoff; if Cursor substitutes another model or rejects the options, resolve that concrete settings/access problem before further model-dependent dispatch. Do not silently use Auto or the built-in faster Explore agent. Use named custom agents for exploration and verification as well. These settings affect development agents, not AabFlow's product copilot/provider.

The configuration follows [Cursor subagent formats and model parameters](https://cursor.com/docs/subagents) and the [Grok 4.7 model reference](https://cursor.com/docs/models/grok-4-7), checked 2026-10-10. Actual Cursor execution remains a runtime check, not something a repository file can certify.

## The source of truth

- [`agent-dag.json`](agent-dag.json) contains 27 nodes: all P00–P13 chunks, their bounded substeps, ownership, prerequisites, resources, spec references, requirements and checks. It also maps every feature and AT to verification owners.
- [`AGENT_DAG.md`](AGENT_DAG.md) is generated from that manifest. Its edges must not be edited independently.
- [`PROGRESS.md`](PROGRESS.md) remains the PR queue; [`STATUS.md`](STATUS.md) remains the executed-evidence scoreboard. GitHub is authoritative for PR/merge state. The DAG refines the queue's sequencing; it does not replace its completion criteria.
- [`REVIEW_PLAN.md`](REVIEW_PLAN.md) supplies independent reviewer and milestone gates. Read the full cited spec sections before implementing a node; the manifest is an assignment index, not a substitute for the specs.

Run the planner in Docker:

```bash
docker compose run --rm --no-deps -T api python scripts/agent_dag.py validate
docker compose run --rm --no-deps -T api python scripts/agent_dag.py waves
docker compose run --rm --no-deps -T api python scripts/agent_dag.py brief P07-review
docker compose run --rm --no-deps -T api python scripts/agent_dag.py plan --state .agent-work/control/state.json
```

`waves` is a dependency forecast, **not a claim that tasks executed**. `plan` validates checkpoint records and offers resource-compatible candidates. It does not launch agents, verify GitHub, execute tests, provision data or prove that a chosen checkout contains the prerequisite commits. The parent performs those checks before dispatch. Never mark a candidate complete merely to unlock another task.

## Sequence and chunk size

1. Reconcile P00's merged snapshot and P01's current PR, then perform `G-CONTRACT`: inventory actual existing schemas, canonical metrics, pilot/run versions, routes/jobs and missing services. Assign shared-file ownership before workers write.
2. Build P02 provenance/reproduction and P03 decision verification. Start P05 reports API in parallel against frozen interfaces. P07 raw processing follows P02. P04 analysis/surrogate validation follows P01/P03. Provider connectivity alone may be checked early.
3. Finish P05 report artifacts against validated metrics. P06 SDG service follows validated decisions/stress, then its UI. P07 proceeds process → review/publish → UI. P08 performs completed-package ZIP validation → evidence-pack assembly. Substeps share their PNN branch and execute serially; one coherent chunk becomes one PR unless a separately reviewable split is explicitly recorded.
4. `P11-core` verifies the five non-chat screens, Evidence flows, report/UI consistency and unavailable chat shell. P09 then proves actual offline operation and restart/tamper recovery. `G-CORE` runs **complete** non-chat acceptance on one integrated snapshot.
5. On 2026-10-10 the builder's user waived the 30×3 copilot evaluation. P10 does not run it, and AT17 is not marked passed. `P11-final` still checks the copilot screen once. P12 runs the stage route once. Every other required check also runs once: reuse published libraries, the existing surrogate, and cached inference. Do not retrain or repeat a passing run.
6. P13 measures cold launch/performance and assembles the final release report/pack. `G-REVIEW` waits for independent prerequisite PR/milestone review and merge. P13 ships for review; `G-RELEASE` requires its merge and final reviewer M8 evidence before claiming release completion.

This corrects the old P10→P05-only shortcut. PRD §0.3/§12 and T11/T13.2/T13.4 require the full non-chat core before M7. P03's early `core-acceptance` v1 is a partial checkpoint. It must become a complete, missing-coverage-failing gate at `G-CORE`. P11-core evidence is partial AT13/AT14: Copilot is one of the six screens in PRD §9.6. Do not claim those ATs passed until P11-final.

Each substep is a checkpoint with a finite acceptance checklist, not a time box that permits leaving work unfinished. Break a large node into ordered local implementation tasks in its assignment, while retaining every requirement and its PNN completion barrier. Read existing code first; verify and fix it rather than rebuilding working subsystems. Do not expand three workers into dozens of overlapping agents merely because 500k context is available.

## Contracts and one writer per checkout

The parent owns `api/aabflow/domain/**`, main/router registration, job dispatcher/registration, SQLite schemas/version bumps, generated OpenAPI/TS, dependency manifests/lockfiles, Make/Compose/Dockerfiles, shared configuration, shared frontend routing/client/types and STATUS/PROGRESS. A worker that needs these files sends a precise contract change request. The parent obtains the `contracts` lease, makes the smallest coherent edit in that worker's checkout while its worker is paused, runs contract checks, and records the resulting SHA. Then the worker resumes against that SHA. Never regenerate shared contracts simultaneously in two workers.

Data owns intake/provenance/review modules and real source packages. Science owns crop/water/candidate/surrogate modules. API owns the specifically assigned service/router/test files. UI owns specifically assigned components/tests. A `web/src/**` or `tests/integration/**` manifest path is an upper boundary, not permission for several workers to edit every file in it: the assignment narrows it to concrete paths. Helpers may inspect broadly but cannot edit outside their assignment. Spec-auditor is read-only; verifier can run checks and write evidence but sends code failures back to the owning worker/parent.

Workers do not commit, push, open PRs, merge, stash or switch another checkout. The parent inspects and commits their work in their own worktree. Uncommitted changes from another contributor trigger the existing stop-and-clarify rule; do not stash/discard them. Parent-owned coordination is the reason workers never all update the same checkpoint or STATUS file.

## Branches and multi-parent joins

Before claiming a node, fetch and inspect open PRs, gap issues and remote `pNN` branches. Reuse the rightful builder's active chunk; never start a duplicate. Handle changes requested and merged-work gaps before new queue work. Detect builder/reviewer as in CONTINUE; reviewer sessions run REVIEW_PLAN, not this builder dispatch loop.

Create an isolated local Git worktree on the required base, for example:

```bash
git worktree add ../khaitoman-p05 -b feat/p05-reports <verified-base-ref>
```

Use actual refs, never the placeholder literally. Prefer reviewer-merged main for independent work. A dependent chunk may stack on one validated open PR branch. **Every required code SHA must be an ancestor of the selected base**, checked on the host with `git merge-base --is-ancestor <sha> <base>` for each parent. Asset versions/hashes must also be present. A join of multiple unmerged sibling PRs cannot be stacked on all of them: wait for reviewer integration or obtain the already-required human approval for a concrete integration merge. This is an external review dependency, not permission to cherry-pick conflicting code or pretend files exist. Continue other genuinely ready nodes meanwhile.

The separated P11-core and P11-final may be reviewed as explicit stacked sub-PRs if needed to unblock integration. The P11 parent remains incomplete until both are validated and its terminal PR is reviewer-merged. Record each sub-PR and its actual base; human review cannot be collapsed into a machine completion record.

No commit/push on main, no force-push, no rebase of pushed branches. Follow `/ship` for every coherent PR; request Sipra-Aoun review. The builder never approves or merges its own PR. `git merge`, `gh pr merge`, issue close, Docker image/volume deletion and spec edits retain their existing user-approval requirements. Worktree isolation and development do not require additional approvals.

## Docker, assets and resource leases

In each dedicated worker worktree:

```bash
./scripts/agent_runtime.sh init p05-run1 1
./scripts/agent_runtime.sh seed /absolute/path/to/prepared-checkout libraries
make test DC='./scripts/agent_runtime.sh compose'
make web-test DC='./scripts/agent_runtime.sh compose'
make train-surrogate GPU=1 DC='./scripts/agent_runtime.sh compose --gpu'
```

The helper uses existing images and verifies the seed API/web/Playwright images' embedded lock hashes; missing or incompatible images are a real setup dependency. The frozen demo must be explicitly built from this worker before use, because retagging cannot prove its source/bundle matches the worker. Compose must support `!override`/`!reset`; its own validation rejects incompatible versions. Slots 1–6 use API/demo 18001–18006 and web 15171–15176; the parent checks ports are free before assignment. Unique project names, image tags, private checkout `data/`, `data/agent.sqlite`, separate volumes and explicit port replacement prevent collision with the primary stack. API and demo still share their worker port, so stop that worker's API before starting its demo. Every worker Make command passes the wrapper through `DC`; otherwise Make silently uses the primary Compose configuration.

The helper disables Compose's `.env` loading and refuses initialization outside a linked worktree or with an existing `.env` in its checkout/ancestors (filename checks only). AabFlow itself calls `load_dotenv`, so keep that location free of secret files throughout the run; initialization is not a continuing sandbox. Provider credentials can be inherited from a properly configured host environment without displaying their values; missing credentials are a concrete connectivity blocker. Never inspect `.env`, `.env.*`, resolved Compose secrets, or write keys into source/logs/reports. Existing product provider defaults are preserved.

`seed` privately copies only ignored files from one explicitly chosen asset group, without overwriting existing files or tracked metadata. It never seeds databases, runs or reports. Copy-on-write is preferred; ordinary private copies are the fallback. Verify assets against **this branch's** manifests before use; stale same-named cache files do not become valid because they were copied. Seed only required groups, record source hashes, and use actual raw bundles/inference weights/library policy files. Do not install host dependencies, fabricate missing artifacts or mark fixtures as real. Do not share writable science caches or pilot indexes between worktrees. After a web image rebuild, renew that worker's anonymous node_modules volume with its normal `make deps` workflow before validating a persistent web container; ephemeral web/e2e test runs use fresh image volumes.

The parent owns leases for `contracts`, `gpu`, `science`, `demo` and `provider`; each has capacity one in the default manifest. Acquire them for the actual heavy operation, including expensive tests and servers, and release them only when its processes stop. A blocked worker must stop its processes before releasing its leases. Keep at most two host-global analytical jobs, ≤2 CP-SAT threads per job; the default science lease serializes expensive science/solve work more conservatively. Worker dispatchers use one job worker; do not leave three active analytical servers running. Bound LightGBM/BLAS and `AABFLOW_SCIENCE_WORKERS`, pause science for presentation timings, and record hardware/load conditions. Fast read-only/unit work can proceed while expensive resources are occupied if it truly does not consume those resources.

Prefer the available GPU for supported vision/LightGBM work and record the device observed in actual execution. A seeded CPU vision image does not become CUDA-enabled from `--gpu`: explicitly build the worker's vision image with `./scripts/agent_runtime.sh compose --gpu --profile vision build vision`, then execute its CUDA/device check before inference. AquaCrop and CP-SAT stay CPU. Preserve statistical holdout splits required by the specs. Dependency changes are parent-owned: edit manifest, `make lock` with the wrapper, rebuild the worker's private images, commit lockfiles and refresh runtime image/lock records. Explicit `compose build <services>` refreshes only those services' image IDs/lock fingerprints; a program argument named `build` does not. The helper refuses a service run when its lock hashes or recorded image ID changed. Retagging a shared image while another worker runs is prohibited.

## Assignment and handoff

Before dispatch, generate `brief <node>` and fill [`agent-assignment.md`](templates/agent-assignment.md) with **absolute worktree path**, branch/base SHA, prerequisite SHAs and asset hashes, exact allowed files, shared-file exclusions, model settings, allocated resources, complete spec checklist, commands and evidence destinations. A fresh subagent cannot infer the parent's history. Give it that self-contained assignment and point to AGENTS/CLAUDE/specs. Verify its checkout and model before edits. The parent alone launches/resumes named agents and records Cursor IDs.

Workers save [`agent-handoff.json`](templates/agent-handoff.json) in their own `.agent-work/handoffs/<node>.json`. It contains requirement→test→artifact mapping, exact commands/exit codes/logs, observed device, actual model, diff/files, assumptions and remaining failures. Never return only “done”. Every actionable finding, including should-fix, is fixed before validation; no deferred unfinished work or weakened assertions. A concrete external blocker must include the exact failed operation and necessary external change, while independent work continues.

The parent runs the required Docker checks for the whole chunk, generates contracts when needed, reads the full diff and invokes spec-auditor following `.claude/agents/spec-auditor.md`. An independent verifier re-executes relevant paths using real data; neither its output nor the auditor's review substitutes for human PR review. Fix all findings, then update STATUS with executed evidence and ship. Check logs are copied into versioned `evidence/commands/` before committing; private checkpoints/handoffs alone are not reproducible review evidence.

## Checkpoints, invalidation and resume

The parent creates `.agent-work/control/state.json` with `{"version":1,"nodes":{}}`; nothing is pre-marked complete. It alone updates this checkpoint, using a temporary file then atomic rename. `plan` rejects unknown nodes, malformed states, contradictory completed dependencies, missing SHA/evidence, duplicate checkout/chunk writers and resource overbooking. Its records remain claims the parent must validate against commands/GitHub.

Node states: `pending` → `active` → `validated` → `review` → `merged`; `blocked` means a concrete external blocker, never “hard” or “not finished”. Failed fixable checks stay active. Gate nodes without a PR stop at `validated`. External P00/P01 snapshots get their actual GitHub state and evidence. A validated record requires the 40-character commit SHA and nonempty evidence paths; review/merged also require the PR URL. Active records require `agent_id`, absolute `worktree` and `branch`. Add actual model, assigned files, lease operations, artifact hashes, requirement mapping, failed-command logs and timestamps as extra metadata. Preserve sub-PR details on the owning chunk record.

On resume: reconcile checkpoint against `git worktree list`, each checkout's status/HEAD, GitHub PR/gap state, running containers/processes, asset hashes and Cursor agent IDs. Never automatically reclaim an apparently stale active lease: inspect/stop or resume its actual worker first. Missing agents get a fresh self-contained assignment. Keep uncommitted work, report contradictory claims, and invalidate affected evidence rather than guessing.

Any upstream contract, reviewed code, pilot/library/model/hash or metric definition change invalidates **all affected descendants**. Before replanning, reset their evidence/state and record the reason; do this as one atomic checkpoint update so a completed child cannot outlive its changed parent. Retain prior PR/SHA/evidence history: invalidating verification does not undo a GitHub merge. Fix merged-work regressions through the existing gap/fix PR process, then record the new validating snapshot. Re-run full non-chat acceptance before further copilot evaluation when its interfaces or analytical behavior changed. Tie every test, screenshot, timing and evaluation to the exact code/data/model snapshot. Updating a base branch alone is not evidence that earlier results still pass.

Completion means every required node's scope has executed successfully and every required reviewer/release gate is satisfied. Open PRs are progress, not release completion. A truthful unfinished/blocker report is required when an external dependency prevents completion; scope never shrinks to fit the available time.

## Workflow verification on 2026-10-10

The workflow's own tests pass: **66 scheduler/runtime regression tests**, **463 total fast backend tests**, Ruff checks/format checks and shell syntax. The manifest validates all 27 nodes/14 chunks and complete F/AT ownership; the generated graph/configuration drift check passes. Evidence is in [`cursor-dag-tests-20261010.log`](../evidence/commands/cursor-dag-tests-20261010.log) and [`cursor-dag-workflow-20261010.log`](../evidence/commands/cursor-dag-workflow-20261010.log).

A real separate worktree was initialized with private image tags/data/database and API port 18003; its API booted with schema 2, a healthy database and one dispatcher worker. The final helper's embedded-image checks and isolated API mount were executed, and its GPU Compose configuration validated. Temporary containers/network/worktree were cleaned up. No new GPU training, vision inference, browser suite or Cursor agent launch is claimed by this tooling change. Cursor must confirm model selection/task execution when `/aabflow-build` first runs; remaining product acceptance remains the DAG's work.
