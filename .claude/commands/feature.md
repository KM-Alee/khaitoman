---
description: Implement one feature (F01–F20) fully, with tests and status update
argument-hint: <Fxx> [extra notes]
---
Implement feature **$ARGUMENTS** for AabFlow.

1. Find the feature in PRD §3 and its detailed PRD section, then every tech-doc section that implements it (grep the ID and its key nouns in `aab-flow-tech-doc-v2.md`). Note the acceptance tests it feeds.
2. Check `docs/STATUS.md` and existing code under `api/aabflow` and `web/src` so you extend rather than duplicate.
3. Implement backend domain logic first (typed Pydantic schemas, units from `aabflow.domain.units`, hashes from `aabflow.domain.hashes`), then API routes under `/api/v2`, then UI.
4. Add tests for each rule the specs list, including the rejection cases. Run the relevant make targets until green.
5. If the API changed, run `make contracts` so `web/src/generated/api.ts` matches.
6. Work on a branch (`feat/<id>-<slug>`, never `main`). Update the feature's row in `docs/STATUS.md` with evidence, then finish with the `/ship` steps (`.claude/commands/ship.md`) to open the PR for review. Report the PR URL, what was built, and what remains.
