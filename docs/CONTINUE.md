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
3. **The next ready DAG substep** belonging to a `todo` or your active `building` PROGRESS row. Follow `docs/AGENT_WORKFLOW.md`, validate `docs/agent-dag.json`, and reconcile the private checkpoint before selecting. Use validated prerequisites with recorded SHA/evidence; single-parent work may stack on its open PR. A multi-parent base must contain every prerequisite SHA, otherwise wait for independent reviewer integration. Before claiming a new chunk, make sure nobody else has its PR/remote branch. Serial sessions take one ready substep; parallel sessions use the bounded dispatch workflow.

For a queue row: branch `feat/pNN-<slug>`, set the row to `building`, then build its DAG substeps the way `/feature` and `/milestone` describe (specs first, full scope, tests for every rule including rejections, real data). Complete the whole chunk before `/ship`, except an explicitly recorded coherent sub-PR needed for integration (such as P11-core); its parent stays incomplete. Full non-chat G-CORE precedes P10; full AT13/AT14 await P11-final. The PR title starts with `PNN`, and the PR sets the row to `review #n` only when its full scope lands. Then continue with the next ready substep when usage allows.

Never review or merge your own PR.

## 3b. Reviewer

1. **A PR waits for your review** (`gh pr list --search "review-requested:@me" --draft=false`; oldest first, stacked parent before child). Run `/review-pr <n>` using that PR's row in `docs/REVIEW_PLAN.md` §1 as the checklist. In your last `review(PNN): ...` commit, set the PROGRESS.md row to `done #n`. Merge only after the user confirms.
2. **A milestone just completed** (all its rows `done`) and its gate in REVIEW_PLAN.md §2 hasn't run. Run the gate on `main` and record it as that section says.
3. **Nothing waiting.** Audit the most recently merged PR against its spec sections and file `gap` issues for what's missing, or say there's nothing to review and what the builder is on.

Never build queue items as reviewer.

## 4. Report

Finish in under 10 lines: role, what you did (PR URL or issue numbers), checks run with result lines, what's next for this role, and anything waiting on the other person.
