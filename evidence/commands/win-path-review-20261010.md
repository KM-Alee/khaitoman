# Independent integration review (Windows, 2026-10-10)

Base: origin/main 3cc65e3, including merged PRs #5–#10, #12 and #13.

Fixed two review findings: the Timeline.tsx/timeline.ts import collision on a Windows bind mount, and demo manifests advertising a missing, unfinished or chat-mode turn as a saved plan. Saved-plan availability now gates the replay link. Five rejection/success cases exercise availability. Repaired the F18–F20 status table columns while preserving the reported limitations.

Executed in Docker:

- Ruff check: passed (EXE002 excluded because Windows bind mounts report all files executable); Ruff fix/format on edited Python files passed.
- Fast pytest, excluding tests/scientific: 638 passed, 1 skipped, 8 warnings in 126.02 s. See pr12-python-final-20261010.log. The skipped historical pilot-b raw bundle is absent; no data was fabricated or renamed.
- Frontend: 114 tests passed in 17 files; TypeScript and Vite production build passed on the combined #12/#13 source.
- E2E TypeScript check passed.
- OpenAPI and generated TypeScript regenerated with no contract changes.
- Earlier integration scientific sweep: 45 passed in 1139.19 s; core acceptance v1: 19 passed, 1 skipped. No science engine code changed in #12/#13 or these fixes, so the sweep was reused.

This is a review/build check, not full AT13–AT18 acceptance. No hosted-model turn, complete guided tour, recording replay, pitch rendering or offline acceptance was executed here. Existing author-reported tour timeout/resource 404s, absent dated USD rate and unfinished evidence-pack remain recorded limitations. AT17 evaluation remains explicitly deferred by the user.

The PR was already merged by another session during review, so fixes ship separately for independent review. No main commit/push, force-push or rebase was used.
