# AabFlow v2 doc review: what changed

Full scope is kept. Every F01–F20 feature and AT01–AT18 test is unchanged. Only flaws were fixed. The originals are saved in `originals/` next to this file.

## Logic flaws fixed

1. **The downstream story didn't match the model.** Roster turns are exclusive in time, so one field taking its full turn never takes water from a tail field. Tail effects only come through reach losses, shared repairs, shared pumps, shared upstream edges and the budgets. Both docs now say this (PRD §6.1, handbook T4.3). They also require at least two reaches with different losses, so a repair actually changes what the tail receives. The demo story should frame it this way: protecting the tail needs the repair, and the repair uses budget that would otherwise pay for leveling at the head.
2. **B1 (no new capital) could equal B0.** B1 can only beat B0 by running existing assets better. If the pilot has no existing pond or pump, the "value of investment" comparison shows nothing. Each pilot now needs one existing pond and one existing shared pump, and B0 has to be a plausible but non-optimal habit. A warning fires if B1 equals B0 (PRD §6.4, T6.5).
3. **Service floors could fail silently.** With a 22% shortage and tail losses, tail service is capped around 0.5 unless the repair is built. The UI now shows the highest service each group can reach and warns while the floor is being set, not after a failed solve (PRD §8.3).
4. **Cotton season_response looked inconsistent.** Cotton is planted around April–May 2027, which leaves time to build ponds and repairs. So in season_response mode, cotton runs can legitimately include them and wheat runs can't. The docs now say this outright so it doesn't look like a bug (PRD §2.2).
5. **The schedule was already broken.** It used fixed clock times starting at 02:00 on 10 Oct and assumed about 30 hours with no sleep. It is now written as offsets from your real start time, with the same milestone order, an example run from 08:00 Oct 10 to 09:35 Oct 11, and a rest block while the copilot evaluation runs (T13.1).

## Technical flaws fixed

6. **AquaCrop would clip almost every irrigation.** Its default daily cap is far below a 50–100 mm flood turn. MaxIrr and MaxIrrSeason must now be set explicitly (T5.2).
7. **The science batch size was unbounded.** Crop runs don't depend on field area, so each schedule template now runs once per soil, weather and efficiency setting and is reused across fields. The estimate is about 2,900 runs before deduplication. The batch has to start at the end of M2 (T5.6).
8. **No guaranteed feasible option.** Every field now always has a zero-water option, so the portfolio and robust models are never infeasible just because one field has no deliverable plan (T5.6).
9. **numba warm-up.** The first AquaCrop run in each worker process compiles code and is slow. Workers now warm up once, and the benchmark leaves that run out (T5.2).
10. **Sentinel-2 resolution vs Punjab fields.** A one-acre field is about 6×6 pixels, so expect many merged and split fields. Pick AOIs with bigger fields, take the reviewed 30 from the cleanest area and report the correction rate (PRD §5.2, T2.4).
11. **The surrogate test was one year.** With 6 seasons, a single held-out year is noise. Development now uses leave-one-year-out cross-validation, and the untouched year stays as the final check. The doc also explains how to build 10 decision fixtures from one year (T8.3).
12. **Shared weather cells.** Both pilots may fall in the same weather grid cell. If they do, share the weather files and crop runs, and don't claim climate diversity (PRD §5.4, T2.5).
13. **Pond sizing.** A 250 m³ pond holds about a third of one irrigation on 1 ha. Pond sizes are now defined by how many irrigations they hold (T4.4).
14. **Canal data fast path.** A bounded Overpass query takes seconds, compared with a full Pakistan extract. OSM coverage of minor watercourses is patchy, so expect dashed assumed links (T2.1).
15. **Lighter persistence.** SQLAlchemy and Alembic are replaced by stdlib sqlite3 with a schema.sql. There are no feature changes (T1.2).
16. **Copilot evaluation runtime and model check.** The 90-run suite now runs concurrently and starts early in M7. `gpt-6.1-sol` must be confirmed on your account in M0, and the model stays configurable (T11.8).

## Open questions for pablo

- **Presentation time:** is it 09:35 on 11 Oct, or the end of 10 Oct? If it's the end of 10 Oct, the window is about half as long.
- **Copilot last:** the docs build the copilot last, at M7, which is apparently your earlier call. It's an AI hackathon, so if M7 slips, judges see no AI. Keep it last, or wire a thin version right after M3?
- **Copilot provider:** does AICON require or sponsor a specific model provider?

## Packaging change (pablo, 10 Oct)

17. **Docker for everything.** A second contributor joined, so the whole build now runs in Docker Compose: `api` (Python 3.11 + uv), `web` (Node 24 + Vite), `vision` (Delineate Anything + torch + GDAL), `demo` (frozen app image) and `e2e` (Playwright). Only Docker is needed on the host. The demo starts from prebuilt images with no network. Python resolution is pinned with `exclude-newer` for reproducibility. No feature or acceptance test changed (T0.1, T1.1–T1.4, T12.4, T13.2, T13.4; PRD §0.2 runtime row).
