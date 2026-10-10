# P01 self-review

Reviewed the P01 diff against `origin/feat/p00-integrate-m1-m5`, including the
reviewer's P00 fixes, following `.claude/agents/spec-auditor.md`.

No blockers found for the P01 deliverable. AT02–AT04 explicitly pass in the
75-test domain gate. Both real pilots/all four seasons have complete field/configuration
coverage and exact output references; original-precision reconstructed portfolios
pass. Undeliverable states retain violations and null yields/production. The crop
gates audit gross irrigation and the single tonne/ha → kg/ha conversion for both
crops. No fixture data entered production libraries, no API/schema changes, no
solver rounding changes, and no manifest/lockfile changes.

The publication fix preserves immutable metadata and refuses same-hash changes,
with tests for collisions and restoration of ignored policy dumps. All four
pilot-b hashes reproduce on the second build. The new surrogate model has a new
version and retains original weather-year split labels for mapped experiments;
domain tolerance and evaluation thresholds are unchanged.

Remaining findings (included in the PR's Known gaps):

- **Should-fix:** `api/aabflow/optimizer/candidates/__init__.py:992`, T5.7.
  Coverage counts and families do not establish objective/action stability under
  a denser library. That comparison has not run. M2 remains `in_progress`, and
  these finite-library results do not claim comprehensive search.
- **Should-fix:** `api/aabflow/surrogate/training/__init__.py:365`, T8.3.
  The newest wheat test season is 2025–26, outside the pilot archives ending in
  2025. Its final holdout therefore has discovery samples only. Cotton's 2025
  holdout has all three sources. Wheat pilot holdouts and per-pilot error metrics
  remain for P04; F12 remains `in_progress`.
- **Note:** `docs/P01_DOMAIN.md:48`, T5.4. These are exact simulated outcomes
  with uncalibrated crop profiles, not observed field predictive accuracy.
