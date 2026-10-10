---
description: Run every available check and refresh AT01–AT18 status with evidence
---
Run the AabFlow acceptance sweep.

1. Run `make doctor`, `make test`, `make science-smoke`, `make web-test`, `make web-build`. Also run any of `make water-tests domain-tests core-acceptance ui-checks` that are implemented (an unimplemented target exits 1 with "not implemented yet"; record that, don't treat it as a code failure).
2. For each AT01–AT18 in `docs/STATUS.md`, decide passed / failed / not_started / blocked strictly from executed evidence: a test that exercises it, its output, or a saved artifact. No evidence means not passed.
3. Save the combined output to `evidence/commands/acceptance-<UTC timestamp>.log`.
4. Update `docs/STATUS.md` on a branch `chore/acceptance-<UTC date>`, open a PR with the `/ship` steps, and report the PR URL, a table of AT IDs with status and the one-line reason, then the top three blockers.
