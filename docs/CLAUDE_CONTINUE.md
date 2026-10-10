# Continue from here

This branch is the integrated tip of the product work done through 2026-10-10. Ignore `docs/AGENT_WORKFLOW.md`, `docs/agent-dag.json`, and the Cursor DAG commands. This list is the work.

Docker only. Do not read `.env`. Do not commit or push `main`. Do not run the 30×3 copilot evaluation. Do not mark AT17 passed. Run each required check once. Reuse published libraries, the existing surrogate, and the Delineate cache. Do not retrain or start a new vision job unless a cache miss blocks a real publish.

## Already on this branch

- P02 AT01 and reproduction of both `reviewed-v1` packages without rewriting them. PR #4.
- P03 AT05–AT08 and AT12, plus `make core-acceptance` v1. That v1 is not the full release gate. PR #5.
- P05 reports API and local `report.html`, CSV, GeoJSON, and sha256 manifest from stored metrics. PR #9.
- P06 SDG cards from stored metrics on `GET /runs/{id}/impact`. No 0–100 score. CO₂ is `not_estimated`. PR #7.
- P07 raw onboarding routes and one cached pilot-b process. `reviewed-v1` was not overwritten. PR #6.
- P08 finished-package ZIP export/import and hostile-archive rejections. PR #8.
- P01 is still PR #3 and is not merged. Leave it for Sipra-Aoun.

Routers mounted, in order: system, pilots, onboarding, packages, jobs, scenarios, impact, runs, analyses, surrogate, reports, copilot.

## Implement next, in this order

1. Frontier and stress on one real request. Undeliverable cells already drop yield when the frozen plan is not shared (`api/aabflow/services/analyses/jobs.py`). One in-domain preview after load was 6.822 ms, with a separate AquaCrop confirmation (`evidence/benchmarks/p04-preview-timing.json`). Do not retrain. Still run one six-setting frontier and one nine-cell stress if those saved results are not already linked to run records.
2. Impact screen is implemented. Vitest passed (59 tests) and typecheck passed. The live Playwright file `tests/e2e/impact.spec.ts` is written and was not executed. Run that one spec once when the demo is up. Do not recompute metrics in the browser.
3. Onboarding review and publish. Stale review returns 409. Publish pilot-b `reviewed-v2` from the real raw bundle. Do not overwrite `reviewed-v1`. Reuse the Delineate cache.
4. Onboarding wizard screen wired to those routes.
5. Evidence pack from `scripts/build_evidence_pack.py`.
6. Offline check (AT15) and restart/tamper check (AT18), one pass each.
7. Non-chat screens: one pass for loading, empty, error, keyboard, and contrast. Copilot screen can show the existing panel. Do not run 90 copilot cases.
8. One Playwright pass of the stage route against the real API.
9. One cold `make demo` timing pass and a release note that lists every feature and acceptance test as passed, failed, or not run, with the command or file that supports it.

## Do not claim

- AT17 passed.
- Full release, until Sipra-Aoun has merged the open PRs and the list above is done.
- A new GPU training run or a new vision inference unless you actually executed it.
