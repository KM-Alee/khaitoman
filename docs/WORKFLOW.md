# Build → review workflow

Two roles, working in parallel. Every change reaches `main` through a reviewed PR.

| Role | Who | Does | Command |
|---|---|---|---|
| Builder | KM-Alee | Builds features/milestones with Claude, opens a PR per reviewable chunk, moves on to the next | `/feature`, `/milestone`, `/fix`, then `/ship` |
| Reviewer | Aounuman (`Sipra-Aoun`) | Verifies each PR against the specs, fixes gaps and errors directly on the PR branch, files issues for anything bigger, merges | `/review-pr <n>` |

## Lifecycle

1. **Build** on a branch, never on `main`: `feat/f05-pond-ledger`, `fix/ledger-rounding`, `chore/...`, `docs/...`.
2. **Ship** with `/ship`: checks run, `spec-auditor` self-review, STATUS rows updated, branch pushed, PR opened with Sipra-Aoun as reviewer. The PR body's **Known gaps** and **Unverified** sections are the reviewer's starting list, so they must be honest and complete.
3. **Hand-off.** Once the PR is open the reviewer owns the branch. The builder doesn't push to it again unless the reviewer requests changes.
4. **Review** with `/review-pr <n>`. The reviewer re-runs checks, audits the diff against the PRD and tech doc, and then:
   - fixes what fits in the PR as `review(<ID>): ...` commits on the PR branch,
   - opens a `gap` issue for anything larger (with the spec section, file:line and "Found in #n"),
   - corrects STATUS rows that claim more than the evidence shows.
5. **Approve and merge.** The reviewer approves with a summary (fixed / issues filed / verified / remaining risk) and merges with a **merge commit** (`gh pr merge <n> --merge --delete-branch`). Merge commits keep the reviewer's fix commits visible and keep stacked PRs clean. If the design itself is wrong, the reviewer requests changes instead and the branch goes back to the builder.
6. **Gap issues** feed the builder's queue. `/status` lists them, and the PR that fixes one says `Closes #n`.

## Building while a PR is in review

- Work that doesn't depend on the open PR branches from `origin/main`.
- Work that does depend on it is **stacked**: branch from the open PR's branch and open the new PR with `--base <that branch>`. When the parent merges and its branch is deleted, GitHub retargets the child to `main`, and the reviewer merges `origin/main` into it.
- Rebasing a branch that's already pushed is not allowed (force-push is blocked). Use merges.

## STATUS.md

A PR updates only the rows its own work moves, with evidence. If both sides changed `docs/STATUS.md`, resolve the conflict row by row and keep the status that has executed evidence behind it.

## Guardrails (enforced in `.claude/`)

- `scripts/hooks/git_guard.sh` blocks `git commit` on `main`, pushes to `main`, and force-pushes (`--force-with-lease` to a non-main branch is allowed).
- `gh pr merge` needs confirmation. A builder never merges their own PR.
- The Stop hook still runs `make test` / web checks on uncommitted changes.

## Reviewer setup (once)

```bash
gh auth login
gh repo clone KM-Alee/khaitoman && cd khaitoman && ./scripts/setup.sh
```

Then open Claude Code in the repo and run `/review-pr <n>`. `gh pr list --search "review-requested:@me"` shows the queue (the session-start hook prints it too).
