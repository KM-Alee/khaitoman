---
description: Build a whole milestone (M0–M8) end to end against the specs
argument-hint: <M0..M8>
---
Build milestone **$ARGUMENTS** for AabFlow.

1. Read `docs/STATUS.md`, the milestone's row in PRD §12 (`prd-flow-v2.md`) and its row in tech doc T13.1 (`aab-flow-tech-doc-v2.md`). List every feature (Fxx) and acceptance test (ATxx) it owns, plus any earlier milestone still open that it depends on.
2. For each owned item, read the PRD section and tech-doc sections that define it. Quote nothing back; extract the concrete requirements, invariants, and listed tests.
3. Write a short ordered plan (as a todo list) that covers every requirement. Do not drop or shrink scope. Where the specs leave a detail open, pick the default closest to existing code and note it.
4. Implement in dependency order. Independent workstreams (data / science / optimizer+API / UI, per T13.2) can go to the matching subagents in parallel once shared schemas exist; you own integration and shared contracts.
5. Every requirement gets a test (pytest under `tests/`, vitest beside the component, Playwright in `tests/e2e`). Use real data and executed pipelines; fixtures only in tests and labelled as such.
6. Run `make test`, `make science-smoke` (if science changed), `make web-test` and `make web-build` (if web changed). Fix failures from the root cause.
7. Update `docs/STATUS.md` rows with status and evidence (command and result, artifact path). Replace any `not implemented yet` Make target you made real.
8. Commit locally with a clear message. Never push.
9. Finish with: what passed (with evidence), what is still open in this milestone and why, and the next milestone's first step.
