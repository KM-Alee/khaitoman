---
description: Open a PR for the current work so Aounuman can review it (builder side of docs/WORKFLOW.md)
argument-hint: [Fxx | Mx | short title] [notes]
---
Ship the current work as a pull request: **$ARGUMENTS**

This is the builder half of `docs/WORKFLOW.md`. Once the PR is open, the reviewer owns the branch.

1. **Branch.** On `main`: `git fetch origin`, then `git switch -c <type>/<id>-<slug>` (type is feat, fix, chore or docs, e.g. `feat/f05-pond-ledger`). Uncommitted work comes along. On a branch with no PR yet: use it. On a branch whose PR is already open (`gh pr view` succeeds): don't touch it; branch from it and stack. If the work depends on another unmerged PR, branch from that PR's branch and use it as `--base` in step 6.
2. **Checks.** Run the checks for every area the diff touches: Python → `make test`; science/water/candidates → `make science-smoke`; web → `make web-test` and `make web-build`; API routes or schemas → `make contracts` and commit the regenerated files. Keep each command's final result line for the PR body. Fix failures from the root cause and finish all required validation before shipping. A concrete external blocker may be recorded in a draft PR, but a fixable failure is not a reason to stop.
3. **Self-review.** Follow `.claude/agents/spec-auditor.md` on `git diff origin/<base>...HEAD` plus uncommitted changes. Fix every actionable blocker and should-fix finding before shipping. Do not hand fixable work to the reviewer.
4. **STATUS.** Update only the `docs/STATUS.md` rows this work moves, each with evidence.
5. **Commit.** Use small logical commits, with messages like `F05: <what>`. Never commit on `main` (the hook blocks it).
6. **Open the PR.** `git push -u origin HEAD`. Write the body in the scratchpad from `.github/pull_request_template.md`, then run `gh pr create --base <main or parent branch> --reviewer Sipra-Aoun --assignee @me --title "<ID>: <summary>" --body-file <file>` (add `--draft` if step 2 left a failure). Add `Closes #n` for every `gap` issue it resolves.
7. **Next.** Report the PR URL and a one-line summary. Then run `git switch main && git pull --ff-only` so the next work starts clean, unless the next task stacks on this branch.

The PR body must be honest. The reviewer works from **Known gaps** and **Unverified** first, so list every stub, TODO, skipped or missing test, default you picked where the specs are silent, and every path you never executed. Claim nothing as passing unless the command output backs it.
