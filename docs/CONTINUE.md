# "ai continue"

When someone says **"ai continue"** (optionally followed by `builder` or `reviewer` and notes), do the next step of the AabFlow build for their role, using these steps. `CLAUDE.md` points here. A copy can also live at `.claude/commands/continue.md` as the `/continue` slash command, with `$ARGUMENTS` as the role and notes.

## 1. Role

Decide the role, first match wins, and say which one you picked and why in one line:

1. A role word after "ai continue" (or the `/continue` argument): `builder` or `reviewer`.
2. `git config --get aabflow.role` (each person can set it once: `git config aabflow.role reviewer`).
3. `gh api user --jq .login`: `Sipra-Aoun` → reviewer, `KM-Alee` → builder.
4. Otherwise ask once which role, and tell them to set `git config aabflow.role <role>`.

## 2. Sync

`git status`. If there are uncommitted changes you didn't make, stop and ask what they are; never stash or discard them. Then `git fetch origin`, `gh pr list --json number,title,headRefName,baseRefName,isDraft,reviewDecision,author`, and `gh issue list --label gap`. Read `docs/PROGRESS.md` (queue), `docs/STATUS.md` (evidence) and, as reviewer, `docs/REVIEW_PLAN.md`.

The PR list is the truth for the queue. If a row in PROGRESS.md disagrees with GitHub (a merged PR still marked `review`, a pushed branch still marked `todo`), trust GitHub and correct the row in your next commit.

## 3a. Builder

Pick the first of these that applies, then do it end to end:

1. **Your PR has changes requested.** Check out its branch, address every review comment, push, re-request review.
2. **An open `gap` issue** on merged work. Fix it on a `fix/` branch, PR says `Closes #n`.
3. **The next `todo` row** in the PROGRESS.md queue whose **Needs** are `done`. If a Need is only `review #n`, stack on that PR's branch (`--base` it). Before starting, make sure nobody else has it: no open PR and no `origin/*pNN*` branch for that ID. If someone does, take the next row.

For a queue row: branch `feat/pNN-<slug>`, set the row to `building`, then build it the way `/feature` and `/milestone` describe (specs first, full scope, tests for every rule including rejections, real data). Finish with `/ship`; the PR title starts with `PNN`, and the PR sets the row to `review #n`. Then, if your usage allows, continue with the next row (stacked if it needs this one) instead of stopping.

Never review or merge your own PR.

## 3b. Reviewer

1. **A PR waits for your review** (`gh pr list --search "review-requested:@me" --draft=false`; oldest first, stacked parent before child). Run `/review-pr <n>` using that PR's row in `docs/REVIEW_PLAN.md` §1 as the checklist. In your last `review(PNN): ...` commit, set the PROGRESS.md row to `done #n`. Merge only after the user confirms.
2. **A milestone just completed** (all its rows `done`) and its gate in REVIEW_PLAN.md §2 hasn't run. Run the gate on `main` and record it as that section says.
3. **Nothing waiting.** Audit the most recently merged PR against its spec sections and file `gap` issues for what's missing, or say there's nothing to review and what the builder is on.

Never build queue items as reviewer.

## 4. Report

Finish in under 10 lines: role, what you did (PR URL or issue numbers), checks run with result lines, what's next for this role, and anything waiting on the other person.
