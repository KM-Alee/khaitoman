# Parallel build streams (integration contract)

Four streams build concurrently in one checkout. The integrator (main session) owns shared contracts, commits, and `docs/STATUS.md`.

## Rules for every stream

- Specs are law: `prd-flow-v2.md`, `aab-flow-tech-doc-v2.md`, `review/CHANGES.md`. Full scope; no stubs that claim success; real data and executed pipelines; fixtures only in tests, labelled.
- Read `CLAUDE.md`. Everything runs in Docker: `docker compose run --rm --no-deps -T api <cmd>` (Python), `... web <cmd>` (Node), `docker compose --profile vision run --rm --no-deps -T vision <cmd>` (Delineate). Never install on the host.
- Shared types: `api/aabflow/domain/schemas/` (frozen). You may **add** fields/models in a backwards-compatible way; never rename/remove. Use `aabflow.domain.units`, `.hashes`, `.ids`, `.calendar`.
- Only edit the directories your stream owns (below). If you need something from another stream, code against the schema and the file contract here.
- Do **not** run `git commit`, `git stash`, `git checkout`, or anything that rewrites other streams' files. The integrator commits.
- New Python dependency: add to `pyproject.toml`, then `docker compose run --rm --no-deps -T api uv lock` and `docker compose build api`. New npm dependency: `docker compose run --rm --no-deps -T web npm install <pkg>@<exact-version>` then `docker compose build web`. Keep these rare and report them.
- Lint: `docker compose run --rm --no-deps -T api sh -c "ruff check --fix <paths> && ruff format <paths>"`. Tests: `make test`, `make science-smoke`, `make web-test`, `make web-build`.
- Write tests for every rule the specs list, including rejection cases.
- Finish with a report: what is done (with test/command evidence), file list, what is open, and any contract additions.

## Ownership

| Stream | Owns |
|---|---|
| data | `api/aabflow/ingestion/**`, `scripts/acquire_*.py`, `scripts/publish_*.py`, `data/raw/**`, `data/pilots/**`, `tests/unit/test_ingestion_*.py`, `tests/integration/test_pilot_*.py`, `vision/**` (configs) |
| science | `api/aabflow/science/**`, `api/aabflow/water/**`, `api/aabflow/optimizer/candidates/**`, `api/aabflow/surrogate/**`, `scripts/science_*.py`, `data/experiments/**`, `data/libraries/**`, `data/models/surrogate*/**`, `tests/scientific/**`, `tests/property/**`, `tests/unit/test_science_*.py`, `tests/unit/test_water_*.py`, `tests/unit/test_candidates_*.py`, `tests/unit/test_surrogate_*.py` |
| optimizer/API | `api/aabflow/main.py`, `api/aabflow/api/**` (routers), `api/aabflow/optimizer/**` except `candidates/`, `api/aabflow/services/**`, `api/aabflow/jobs/**`, `api/aabflow/repositories/**`, `api/aabflow/config.py`, `contracts/**`, `data/runs/**`, `data/reports/**`, `tests/unit/test_api_*.py`, `tests/unit/test_optimizer_*.py`, `tests/unit/test_services_*.py`, `tests/integration/test_api_*.py` |
| ui | `web/**`, `tests/e2e/**` |
| integrator | `api/aabflow/domain/**`, `api/aabflow/copilot/**` (M7), `docs/**`, `Makefile`, `compose.yaml`, `Dockerfile*`, `pyproject.toml` structure, `CLAUDE.md` |

## Pilot package file contract (data → everyone)

`data/pilots/<pilot_id>/<pilot_version>/` (pilot ids `pilot-a`, `pilot-b`; version e.g. `reviewed-v1`), plus `data/pilots/index.json` listing published `{pilot_id, pilot_version, name}`.

| File | Content (schema in `domain/schemas`) |
|---|---|
| `pilot.json` | `Pilot` (incl. `ImageryRef` list, `ReviewFlags`) |
| `aoi.geojson` | AOI polygon, EPSG:4326 |
| `fields.geojson` | FeatureCollection; `properties` = `FieldRecord` fields; feature `id` = `field_id` (30 reviewed fields) |
| `fields_raw.geojson` | Untouched Delineate output for the AOI window, with model ids |
| `review_log.json` | Correction log: original model ids → reviewed field ids, action, reason |
| `canals.geojson` | Observed canal features with provider ids/tags (OSM/GRAIN) |
| `network.json` | `{ "nodes": [Node], "edges": [Edge] }`; directed tree; ≥2 reaches per watercourse with distinct `delivery_factor`; assumed edges have `geometry_ref: null` |
| `roster.json` | `{ "seasons": { "<season_id>": [RosterWindow] } }` fixed exclusive windows |
| `service_reference.json` | `[ServiceReference]` |
| `assets.json` | `[Asset]`; ≥1 existing pond and ≥1 existing shared pump |
| `interventions.json` | `{ "types": [InterventionType], "instances": [InterventionInstance] }` across all five categories; ≤2 shared repairs; mutually exclusive pond sizes sized in irrigations (0.5/1/1.5 × 75 mm on the field's area) |
| `soils.json` | `[SoilProfile]` (AquaCrop predefined classes; ≥2 archetypes across fields) |
| `imagery/<scene_id>.webp` (+ `.json` corners) | North-up display image, documented stretch |
| `terrain/dem.png` + `terrain/dem.json` | Optional local Copernicus DEM (Terrarium-encoded) and bounds for 3D terrain |
| `weather/<series_id>.json` (raw) + `.parquet` (normalized) | `WeatherSeries` metadata in `weather/index.json`; ≥10 complete historical years for the pilot centroid |
| `evidence.json` | `[EvidenceRecord]` for every source, assumption and transformation |
| `resource_status.json` | T2.1 gates per resource |
| `manifest.json` | `PilotManifest` with sha256 of every file |

## Science outputs (science → optimizer/API, UI)

- Seasons: `wheat-rabi-2026-27` (season_response), `wheat-rabi-2027-28` (capital_planning), `cotton-kharif-2027` (season_response/capital_planning), `wheat-rabi-2024-25` (historical_replay). Published as `data/libraries/seasons.json` (`[Season]`), crop profiles `crop_profiles.json`, weather scenarios `weather_scenarios.json`, supply profiles + uncertainty sets `supply.json` (3 weather × 3 supply = 9 states).
- Crop outcomes: `data/experiments/<experiment_hash>/{outcome.json, raw_*.parquet, trajectory.parquet}`.
- Candidate libraries: `data/libraries/<pilot_id>/<season_id>/<library_hash>/{library.json (CandidateLibrary), policies.jsonl (CandidatePolicy)}` plus `latest.json` pointing at the current hash.
- Python entry points the optimizer/API stream imports (keep signatures stable):
  - `aabflow.science.experiments.run_experiment(exp: CropExperiment) -> CropOutcome` (cached by hash)
  - `aabflow.water.ledger.reconstruct(policy_ids, library, state_id, config_id) -> (list[LedgerEvent], PhysicalValidationReport)`
  - `aabflow.optimizer.candidates.load_library(pilot_id, season_id, library_hash=None) -> (CandidateLibrary, list[CandidatePolicy])`
  - `aabflow.optimizer.candidates.build_library(pilot_id, season_id, *, extra_templates=None) -> CandidateLibrary`
  - `aabflow.surrogate.prediction.preview(policy_inputs) -> SurrogatePreview` and `.domain.check(...)`

## API (optimizer/API → UI)

All routes in tech doc T9.1 under `/api/v2`, generated OpenAPI at `contracts/openapi.json` (`make contracts`), TS types at `web/src/generated/api.ts`. Read-only pilot routes (`/health`, `/capabilities`, `/pilots`, `/pilots/{id}/versions/{v}`, `/pilots/{id}/versions/{v}/map`, `/fields/{id}`, `/seasons`, `/weather-scenarios`, `/uncertainty-sets`, `/interventions`, `/evidence/{id}`) come first so the UI can integrate early. Static pilot assets (imagery, terrain, geojson) are served under `/assets/pilots/...` with path validation.
