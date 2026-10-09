---
description: Debug a failing command, test, build, or container to its root cause
argument-hint: <command or error>
---
Something is failing: **$ARGUMENTS**

1. Reproduce it exactly (inside Docker via the Make target or `docker compose run --rm --no-deps <service> ...`). Capture the full error.
2. Find the root cause: read the failing code, the library source inside the container if needed (`/opt/venv/lib/python3.11/site-packages/...`), and recent `git log -p` for related changes. Don't guess.
3. Fix the cause, not the symptom. No skipped tests, broad excepts, version downgrades, or weakened assertions unless the cause truly is the dependency, in which case pin it in the manifest, run `make lock build`, and say why.
4. Re-run the original command plus `make test`. Add a regression test when the bug was in our code.
5. If the cause is non-obvious and will bite again, add one line about it to `CLAUDE.md`.
6. Commit locally and explain the cause and fix in two or three sentences.
