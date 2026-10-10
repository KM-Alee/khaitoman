# Review plan

The reviewer (Aounuman, `Sipra-Aoun`) half of [`docs/PROGRESS.md`](PROGRESS.md). Process and merge rules are in [`docs/WORKFLOW.md`](WORKFLOW.md); the mechanics of one review are `/review-pr <n>` (`.claude/commands/review-pr.md`). This file says **what to check** for each planned PR and **when a milestone counts as done**.

"ai continue" as reviewer does, in order:

1. Review the oldest open, non-draft PR requesting your review (`gh pr list --search "review-requested:@me" --draft=false`). Review a stacked parent before its child.
2. Before merging, set the PR's row in `docs/PROGRESS.md` to `done #n` in your last `review(PNN): ...` commit.
3. After a merge that completes a milestone, run that milestone's **gate** (section 2).
4. With no PR waiting: run the next un-run gate, or audit merged work against the spec and file `gap` issues. Never idle, never build queue items yourself.

## 1. Per-PR checklist

Every PR: `git status` clean, branch current with its base (merge, never rebase), checks for every touched area re-run by you, `spec-auditor` on the diff, body's **Known gaps** and **Unverified** worked through first, STATUS rows match evidence, `make contracts` leaves no diff.

| PR | Read first | Must verify | Red flags |
|---|---|---|---|
| P00 (review first) | WORKFLOW.md, IMAGERY.md, T13.1, this file and PROGRESS.md | `make test`, `make web-test`, `make web-build`, `make contracts` clean. `tests/unit/test_surrogate_domain_coverage.py` passes. App works with no `VITE_ARCGIS_KEY` (Sentinel-2 fallback). `git grep -n "VITE_ARCGIS_KEY="` finds no value; no key in compose, Dockerfile, docs or `web/dist`. STATUS rows M0–M5 cite commands that you can re-run. | A key or `.env` in the diff. STATUS marking `passed` without a command. Large binaries outside the `.gitignore` rules. |
| P01 | PRD §5, T5–T6 (crop, ledger, candidates) | `make candidates PILOT=pilot-b` reproduces the libraries (hash in `latest.json` matches). `make domain-tests` exists and runs AT02, AT03, AT04 by name. Cotton **and** wheat runs with varying irrigation. | Libraries built from fixtures. AT03/AT04 tests that check only the happy path, not the rejections. |
| P02 | PRD §5.1–5.2, AT01, T9.1 | Test reads the published package, not a fixture. ≥30 reviewed fields per pilot, real Sentinel-2 scene IDs, directed tree with ≥2 reaches per watercourse, manifest sha256 match. | Thresholds lowered to pass. |
| P03 | PRD §6–7, §11.2 AT05–AT08, AT12 | Each AT has a test whose name carries the ID and which asserts the spec sentence (zero capital → no new assets; live change re-solves; optimality/coverage shown; matched vs nonmatched labels; shared cost once, pond land removed, pumping on operating budget). `make core-acceptance` runs them all. | "Impossible" claimed where only the finite model is infeasible (AT07). |
| P04 | PRD §8.1–8.4, §11.1, AT09–AT11 | Six-setting frontier + nine-cell stress each link to run records. Robust plan shares decisions across states; impossible cells show no yield. Surrogate preview ≤300 ms after load, `in_domain`, exact-confirmed. | Loosened timing target. Surrogate preview shown without exact confirmation. |
| P05 | PRD §8.6, §13.3, T7.x reports, copilot `tools/` report calls | `POST /api/v2/reports` → 202 `{report_id, job_id, job}` with Idempotency-Key; `GET` gives `download_url`; files route rejects `../`. `report.html` has no external URL (`grep -E "https?://"`). Values come from stored run metrics. Copilot report tool test passes against the real route. | Numbers recomputed in the report instead of read from runs (breaks AT13). |
| P06 | PRD §8.5, T7.5 | Three cards with official target text and URL, `official_indicator=false`, formula/numerator/denominator with units, run + baseline IDs, limitations. 13.1 blocked if any tested state is undeliverable. No 0–100 score. CO₂ `not_estimated`. UI shows the cards. | Any aggregate "SDG score". Proxy shown as an official indicator. |
| P07 | PRD §5.3, T9.1, AT16 | Runs the **real** pilot-b raw bundle through process → review → publish as a new immutable version. Stale review PATCH returns 409. Publish blocked on structural errors. Libraries from older versions flagged. UI wizard drives it end to end. | Publish that overwrites `reviewed-v1`. Inference "done" without a vision run. |
| P08 | T9.3–T9.5, §13.3 | Import rejects: wrong manifest version, path traversal, duplicate names, oversize/expanded size, bad formats, hash mismatch, existing version. Never executes archive content. Evidence pack written to `evidence/pack/<ts>/`. | Missing rejection tests. |
| P09 | AT15, AT18, T12.4 | Offline test really blocks non-loopback sockets. `scripts/offline_check.py` passes on a fresh `make web-build`. Restart: completed runs re-verify hashes, running job → interrupted with reason, tampered artifact refused, new draft shows no stale result. | Offline test that only mocks the network client. |
| P10 | PRD §10, T11, AT17 | Read `evidence/copilot/eval-*.json` yourself: 30 cases × 3, real services, pass rate per spec. Bilingual (en/ur) answers. Turns under 90 s. `make copilot-evals` reproduces. Re-run 3–5 cases live. | Eval run against the scripted fake model. Cases removed or weakened. |
| P11 | PRD §9, AT13, AT14 | Same metric value, unit and run ID in report, UI and copilot for one run (check by hand too). Six screens pass Playwright + axe at 3 viewports, keyboard, contrast, loading/error/stale, reduced motion. Screenshots committed in `evidence/screenshots/`. Esri imagery toggled in a real browser. | Snapshot tests with no a11y assertions. |
| P12 | PRD §13.2 | Playwright drives the full stage route through the UI against the real API (no mocked `fetch`). Run it yourself with `make ui-checks` or the e2e target. | Route steps skipped or stubbed. |
| P13 | PRD §11.1, §13.3, F20 | Cold `make demo` from a clean clone. Timings recorded against §11.1 (UI ≤5 s, solve p50 ≤5 s / p95 ≤15 s, frontier ≤60 s, stress ≤60 s, preview ≤300 ms, report ≤5 s). Capability report marks every F and AT with artifact paths; STATUS matches it. | Any F or AT marked passed without an artifact. |

## 2. Milestone gates

Run a gate on `main` after the last PR of that milestone merges. Record the result as a short comment on the last PR of the milestone (commands and result lines) and correct STATUS rows through a `review(Mx): gate` commit on the next open PR, or file a `gap` issue if the gate fails.

| Gate | After | Run | Passes when |
|---|---|---|---|
| G1 | P02 | `make pilot-a pilot-b`, AT01 test | Both packages reproduce, AT01 green. |
| G2 | P01 | `make domain-tests`, `make science-smoke`, `make water-tests` | AT02–AT04 green. |
| G3 | P03 | `make core-acceptance`, `make up` and run a live plan in the UI | AT05–AT08, AT12 green; plan changes when budget changes. |
| G5 | P04 | Explore screen: frontier, stress, why-not, surrogate in the UI | AT09–AT11 green and visible in the UI. |
| G6 | P09 | AT15, AT16, AT18 tests; report download from the UI | All green, report opens offline. |
| G7 | P10 | 3–5 live copilot turns in the UI, en and ur | AT17 green, cards render. |
| G4 | P11 | AT13, AT14 | Green with screenshots. |
| G8 | P13 | `make release-check` from a clean clone | Every F01–F20 and AT01–AT18 has a status backed by an artifact. |

## 3. Reviewer don'ts

- Don't build queue items; fix only what fits in the PR under review, and file `gap` issues for the rest.
- Don't loosen a spec threshold, skip a test, or merge a PR whose checks you didn't run.
- Don't merge without confirming with the user (`gh pr merge` asks), and always `--merge --delete-branch`.
