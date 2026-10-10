---
description: Review a PR (reviewer side of docs/WORKFLOW.md) by verifying it, fixing gaps on the branch, filing issues for the rest, then approving
argument-hint: <PR number> [focus notes]
---
Review pull request **$ARGUMENTS**. The reviewer's job is to fill gaps and fix errors, not just comment on them.

1. **Load.** `git status` must be clean (if it isn't, stop and ask). `git fetch origin`, `gh pr view <n> --comments`, `gh pr checkout <n>`. Read the body. **Known gaps** and **Unverified** are your starting list. Find each Fxx/Mx/ATxx in the title in the PRD and the tech doc (`/spec` style) so you review against the requirements, not just the diff.
2. **Bring it current.** If the branch is behind its base, `git merge origin/<base>`. Never rebase. For `docs/STATUS.md` conflicts, keep whichever row has executed evidence.
3. **Verify independently.** Re-run the checks the PR claims, plus the ones for every touched area (`make test`, `make science-smoke`, `make web-test`, `make web-build`, `make contracts` with a clean diff afterwards). Run the `spec-auditor` subagent on `git diff origin/<base>...HEAD`. Then read the diff yourself and look for: scope dropped or stubbed as success, fixtures in non-test code, spec rules without tests (including rejection cases), STATUS rows that claim more than the evidence, generated contracts out of date, and claims in the body that don't match what you ran.
4. **Triage every finding.**
   - **Fix now** anything that fits in this PR: errors, spec violations, missing tests, the PR's own known gaps. Use one commit per fix (`review(<ID>): <what>`) and re-run the affected checks.
   - **File an issue** for gaps too large for this PR: `gh issue create --label gap --title "<ID>: <gap>" --body "<spec section, file:line, concrete failure, Found in #<n>>"`. If the label is missing, create it first: `gh label create gap --color d93f0b --description "Spec gap found in review"`.
   - **Correct** STATUS rows that overclaim.
5. **Push** to the PR branch with `git push`. Never push to `main`.
6. **Decide.**
   - Everything fixed or filed and checks green: run `gh pr review <n> --approve --body-file <file>` with these sections: **Fixed** (short sha and one line each), **Issues filed** (#s), **Verified** (commands and their results), **Remaining risk**.
   - The approach itself is wrong (a rework, not a patch): run `gh pr review <n> --request-changes` saying what to redo and why, then stop. The branch goes back to the builder.
7. **Merge** an approved PR after confirming with the user: `gh pr merge <n> --merge --delete-branch`, then `git switch main && git pull --ff-only`. If another open PR was stacked on this branch, say so. It needs `origin/main` merged in next.
