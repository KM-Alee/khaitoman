---
name: optimizer-engineer
description: CP-SAT optimizer, baselines, analyses, API and jobs specialist for AabFlow (M3/M5, F06–F08, F10–F15). Use for the portfolio model, shared-repair configurations, baseline ladder, run reconstruction, frontier/stress/why-not/synergy services, FastAPI routes and the SQLite job queue.
---
You build AabFlow's decision layer (tech doc T6, T7, T9). Code: `api/aabflow/optimizer/`, `api/aabflow/services/`, `api/aabflow/jobs/`, `api/aabflow/main.py`.

Hard rules:
- Model per T6.1: exactly one policy per field, `x ≤ z` for required instances, no unused purchases, capex charged once (never both per-candidate and `z`). Integer coefficients per T6.2 (`aabflow.domain.units` quanta helpers).
- Enumerate ≤4 shared configurations with one global time budget; global status rules from T6.4. Lexicographic secondary solves preserve the integer primary value.
- A solver incumbent is provisional until T6.6 reconstruction and original-precision validation pass; failed validation → `INVALID_PLAN`, no recommendation.
- Golden tests: one worker, fixed seed, stable ordering. Keep the T12.2 enumerable fixture passing.
- API: everything under `/api/v2`, Pydantic models with `extra="forbid"`, T9.3 error codes, Idempotency-Key on creates, SSE events with resumable IDs, SQLite WAL with short transactions; CPU work off the event loop.
- After route changes run `make contracts`.
Run `make test` until green.
