# AabFlow v2 — Implementation Handbook and Executable Contract Design

**Specification set:** `aabflow-v2`, contract `2.0.0`  
**Prepared:** 10 October 2026, Asia/Karachi  
**Product authority:** [Expanded product specification](prd-flow-v2.md)  
**Hard target:** all F01–F20 and AT01–AT18 for 11 October 2026, 09:35 PKT (confirm the presentation slot; T13.1 schedules from the actual start time).  
**Implementation state:** design and targeted documentation/environment checks. Application code, downloaded pilot binaries, model training, and integrated tests are not delivered by these documents.

This is a build contract. Commands naming `aabflow.*`, `make` targets, scripts, or test modules below define interfaces to implement; they do not assert that those files already exist. Published upstream examples are separately identified. Save real execution evidence before claiming a gate has passed.

## T0. Reconciled decisions and evidence status

### T0.1 Fixed choices

| Topic | Authoritative decision |
|---|---|
| Product scope | Two AOIs × 30 reviewed fields; wheat/cotton separate seasonal runs; all PRD F01–F20 |
| API | `/api/v2`; `pilot_id`; immutable `scenario_revision_id`; `/solve`; no competing route vocabulary |
| Shortage | `supply_profile_id` plus `uniform_reduction_fraction` in `[0,1]`; never a percentage in the canonical API |
| Currency | Integer PKR amounts for budgets/action quotes; decimal-string PKR/kg or PKR/m³ rates, converted explicitly |
| Crop yield | `yield_kg_ha`; production `production_kg`; tonnes are display conversion only |
| Area | `area_m2`, `gross_area_ha`, `cropped_area_ha`; GeoJSON EPSG:4326; metric CRS recorded for computations |
| Water | Float64 m³ physical ledger; mm crop inputs; integer conservative solver coefficients with named quantum |
| Time | UTC instants for event storage; Asia/Karachi crop dates; ISO dates; no ambiguous naive local timestamps |
| Crop engine | AquaCrop-OSPy 3.1.0 in a locked Python 3.11 environment; raw output retained |
| Optimizer | OR-Tools CP-SAT over vetted finite policy candidates; shared repair configuration enumeration |
| UI/runtime | React + TypeScript + Vite static build, served by FastAPI at demo time |
| Packaging | Docker Engine + Compose v2 for every contributor and the demo; uv inside images; only Docker on the host |
| Data store | SQLite (stdlib `sqlite3`, one `schema.sql`) for metadata/jobs/evidence; immutable Parquet/GeoJSON/raster/run bundles |
| Advanced analyses | Services reusing the same scenario/candidate/solve/validation pipeline |
| Copilot | Final feature milestone; backend tool registry and OpenAI Responses; no direct solver arithmetic in language model |

### T0.2 What was actually checked while authoring

| Check | Result | What it does not establish |
|---|---|---|
| Workspace inventory | Original specifications and project review; no application implementation | No feature is currently built |
| System interpreter | Python 3.14.7 is default | Scientific dependency compatibility |
| Managed interpreters | `uv python list --only-installed` found Python 3.11.16 and 3.12.14 | Installed AquaCrop/OR-Tools in those environments |
| Default interpreter modules | AquaCrop, OR-Tools, pandas, GeoPandas, rasterio absent; NumPy/requests present | A production dependency lock |
| CPU/RAM | Intel Core Ultra 7 255HX, 20 logical CPUs; about 30 GiB RAM | Available time/memory under concurrent workload |
| GPU | `nvidia-smi` could not communicate with driver | GPU inference availability; do not assume CUDA |
| Shell network | DNS lookup for `pypi.org` failed in this restricted session | Whether the unrestricted presenting laptop can download packages |
| AquaCrop distribution | Official PyPI lists 3.1.0 and wheel; upstream docs expose irrigation schedule/getters | Successful local crop run or exact local compatibility |
| Data access | Earth Search Sentinel-2 collection endpoint and source documentation accessible through browser tools | Pilot raster/weather bytes downloaded or coordinates reviewed |
| GRAIN | Official docs and paper inspected; Zenodo record/API access failed through the browser tool | Actual Pakistan asset filename, size, hash, and download success |
| OpenAI | Official Responses/function-calling/model documentation inspected | Key access, billing, network, latency, or application tool-use evaluation |

The environment issues are early build blockers to resolve, not reasons to manufacture demo output. Do not copy an author's network limitation into a permanent product assumption. Run M0 on the actual presentation machine.

## T1. Architecture and dependency decisions

### T1.1 Runtime topology

```text
Online acquisition / raw-package import
       │
       ├── GIS, imagery, field inference/review ──> versioned PilotPackage
       ├── historical weather and input evidence ────────────┘
       └── crop experiments ──> exact outcomes + candidate policies
                                    │
React/Vite UI <── HTTP + SSE ── FastAPI domain services
                                    ├── SQLite metadata/jobs
                                    ├── CPU process worker(s)
                                    │      ├── ledger/candidate validator
                                    │      ├── CP-SAT / batch analyses
                                    │      └── exact crop experiments
                                    ├── immutable run/asset store
                                    ├── report/evidence/metric services
                                    └── copilot tool registry [implemented last]
                                             └── hosted model connection
```

Demo mode uses one local origin: `http://127.0.0.1:8000`. FastAPI serves the compiled static frontend and `/api/v2`. Development uses Vite on 5173 proxying `/api/v2` and `/assets` to 8000. Register API and asset routes before the SPA history fallback; unknown API paths must return JSON 404, not `index.html`.

The core requires no managed cloud database, remote basemap, CDN, or Redis. It runs as a local Docker Compose stack (see T1.3) so that every contributor and the presenting laptop share identical environments; images are built ahead of time and the demo needs no network to start. CPU-bound work runs outside the asynchronous API event loop. Published source packages and completed outputs are local. Hosted chat and online onboarding are distinct network capabilities with visible status.

### T1.2 Technology register

| Layer | Selected technology | Reason and constraint |
|---|---|---|
| Containers | Docker Engine, Compose v2, BuildKit; images on Debian trixie slim | Identical environments for two contributors and the demo laptop; dependency changes go through lockfiles and an image rebuild |
| Python environment | Python 3.11 + uv inside the image, locked by `uv.lock` (`exclude-newer` pinned) | Isolate scientific wheels from the vision stack, which has its own image |
| Crop science | `aquacrop==3.1.0`, pandas, NumPy | Documented schedule interface; avoid an unsupported rewrite of crop physiology |
| Discrete decisions | OR-Tools CP-SAT | Integer constraints, binary portfolios, feasibility and objective bounds |
| GIS | GeoPandas, Shapely, pyproj, pyarrow | Actual CRS/geometry operations and GeoParquet |
| Raster acquisition | rasterio, pystac-client, httpx/requests | Windowed COG reads, STAC discovery, retryable manifests |
| Vision environment | Separate Python environment using upstream Delineate requirements; GDAL consistent with its binaries | Preserve model compatibility; CPU execution measured before assuming GPU acceleration |
| Surrogate | LightGBM, scikit-learn metrics/splits | CPU-friendly tabular model with explicit held-out evaluation |
| API/schema | FastAPI, Pydantic 2, Uvicorn | Typed domain boundary and OpenAPI |
| Persistence | SQLite via stdlib `sqlite3` with a versioned `schema.sql` (WAL mode); Parquet and files for large artifacts | An ORM and migration framework cost setup time and add nothing for a single local database built in one day; schema version is stored in a `meta` table. Adopt SQLAlchemy/Alembic later if the schema starts evolving across deployments |
| Frontend | React 19, TypeScript, Vite; Node 24 LTS target | Static build; no SSR needed for a local decision workspace |
| Routing | React Router | Deep links to pilots/runs/fields without separate SSR infrastructure |
| Server state | TanStack Query | Job/result caching and invalidation by immutable IDs |
| Ephemeral UI state | Zustand, with URL state for shareable selections | Camera/selection/panel state; analytical truth stays on the server |
| Components/style | Tailwind CSS 4 + selected shadcn/Radix components; Lucide icons | Accessible primitives with a custom product layout and tokens |
| Motion | Motion for React, reduced-motion aware | Controlled panels and state transitions |
| Map | MapLibre GL JS | Local image source and GeoJSON; direct feature IDs and selection |
| Charts | Apache ECharts | Linked time series, frontier scatter, stress matrix, ledger/sankey |
| Client contracts | `openapi-typescript` + typed fetch; generated/validated runtime boundary | Avoid hand-maintained duplicate Python/TypeScript models |
| Tests | pytest, Hypothesis, Vitest/Testing Library, Playwright + axe checks | Physics, API, interaction, offline, visual and keyboard verification |
| Copilot | Official OpenAI Python SDK, Responses API; model in configuration | Small auditable tool loop; no orchestration framework required |

Major versions above are target decisions, not an already-resolved compatibility matrix. Resolve exact patches once, execute tests, and commit lockfiles. Do not scaffold using unbounded `latest` during the final rehearsal. Vite's official guide documents a static production build and its Node prerequisites. [Vite](https://vite.dev/guide/)

Pydantic emits JSON Schema; use it to generate and test public contracts. Vendor SDK tool schema restrictions require a separate checked normalization step. [Pydantic schema documentation](https://docs.pydantic.dev/latest/concepts/json_schema/)

### T1.3 Environment and first dependency proof

Docker is the only host requirement. All Python runs under uv inside images, and all Node under Node 24 inside images. Never install scientific packages on the host.

| Image (compose service) | Dockerfile target | Contents |
|---|---|---|
| `aabflow-dev:local` (`api`) | `Dockerfile` → `dev` | Python 3.11, `uv sync --frozen` into `/opt/venv`; source bind-mounted; Uvicorn with reload on 127.0.0.1:8000 |
| `aabflow-web-dev:local` (`web`) | `Dockerfile` → `web-dev` | Node 24, `npm ci` from `web/package-lock.json`; Vite on 127.0.0.1:5173 proxying to `api` |
| `aabflow:local` (`demo`) | `Dockerfile` → `app` | Frozen API + compiled frontend on one origin, 127.0.0.1:8000 |
| `aabflow-e2e:local` (`e2e`) | `Dockerfile` → `e2e` | Playwright image matching the pinned `@playwright/test` version |
| `aabflow-vision:local` (`vision`) | `docker/vision.Dockerfile` | Delineate Anything at a pinned commit, torch (CPU by default, CUDA via `compose.gpu.yaml`), GDAL bindings matching the image's libgdal |

```bash
./scripts/setup.sh          # Docker check, .env, all images, weights, doctor and smoke tests
make up                     # api + web dev stack
make test science-smoke     # tests inside the api image
make lock build             # after editing pyproject.toml or web/package.json
```

Containers run as the host user (`HOST_UID`/`HOST_GID` in `.env`) so files written into the bind-mounted repository stay owned by the contributor. Ports bind to loopback only. `data/` is bind-mounted, so pilot packages, runs, and weights persist outside images. Determine torch CPU/CUDA availability with an actual inference run in the vision container and record timing.

The official AquaCrop quickstart is the first crop smoke, followed by a one-season prescribed-schedule test. PyPI identifies the 3.1.0 distribution; inspect the exact installed distribution's license and dependency metadata because upstream metadata and repository license text may differ. [AquaCrop distribution](https://pypi.org/project/aquacrop/3.1.0/)

If 3.1.0 fails: preserve the traceback/input; reproduce the issue; test an explicitly pinned corrective release/patch or a documented compatible fallback; regenerate caches after any engine change. Never mix result libraries from different engines without identity/version separation.

### T1.4 Repository shape

```text
docs/                         # PRD, handbook, decisions, source/legal notes
web/
  src/app/                    # shell, router, design tokens
  src/features/{workspace,compare,explore,impact,evidence,onboarding,copilot}/
  src/components/{map,charts,forms,status,layout}/
  src/generated/api.ts
  src/lib/{api,events,units,formatting}/
  public/fonts/
api/aabflow/
  main.py
  domain/{schemas,ids,units,provenance,hashes,calendar}/
  repositories/{sqlite,artifacts}/   # schema.sql + thin query functions
  services/{pilots,scenarios,runs,metrics,baselines,analyses,reports,evidence}/
  science/{adapter,weather,soils,crop_profiles,experiments}/
  water/{roster,network,ledger,losses,pumps,validation}/
  optimizer/{candidates,model,configurations,objective,bounds,diagnostics}/
  surrogate/{features,training,validation,prediction,domain}/
  ingestion/{stac,grain,osm,imagery,packages,onboarding}/
  jobs/{queue,worker,events,cancellation}/
  copilot/{provider,registry,tools,context,answer_validation,evaluations}/
vision/                       # upstream-pinned preprocessing runner
data/raw/                     # immutable source bytes, where permitted
data/pilots/<pilot>/<version>/
data/experiments/<hash>/
data/libraries/<hash>/
data/models/<model_version>/
data/runs/<run_id>/
data/reports/<report_id>/
data/app.sqlite
contracts/{openapi.json,schemas,examples}/
tests/{unit,property,integration,scientific,e2e,fixtures,copilot}/
scripts/{doctor,acquire,verify_assets,offline_audit,release_report}/
evidence/{environment,commands,benchmarks,screenshots,rehearsal}/
Dockerfile                    # dev, web-dev, web-build, app, e2e targets
docker/vision.Dockerfile
compose.yaml, compose.gpu.yaml
Makefile
pyproject.toml
uv.lock
```

No service chooses a result by reading a frontend fixture. Demo fixtures are used for tests and clearly marked development previews only. A completed run contains data generated by the executed domain pipeline.

## T2. Real-source acquisition and publication

### T2.1 Resource register and access gates

| Resource | Official entry point | Required artifact | Gate |
|---|---|---|---|
| GRAIN | [Repository](https://github.com/UW-SASWE/GRAIN), [data record](https://doi.org/10.5281/zenodo.16786488), [schema](https://grain-canals.readthedocs.io/en/latest/attribute_schema/) | Actual Pakistan country asset or bounded licensed subset; source IDs/metadata | Download and inspect real listing; filename/hash not guessed |
| OSM fallback | [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) bbox query for `waterway=canal|ditch|drain` (fast path), or [Geofabrik Pakistan](https://download.geofabrik.de/asia/pakistan.html) extract | Dated query/extract and reviewed canal features | Preserve IDs/tags/attribution and the query text/timestamp; no assumed hydraulic topology |
| Sentinel-2 | [Earth Search](https://earth-search.aws.element84.com/v1), collection `sentinel-2-l2a` | Raw scene metadata, selected COG windows, SCL/masks, display raster | Actual AOI footprint and dates reviewed |
| Field AI | [Delineate Anything](https://github.com/Lavreniuk/Delineate-Anything), [weights](https://huggingface.co/MykolaL/DelineateAnything/tree/main) | Checkpoint hash, input raster, raw/edited vectors, logs | Upstream sample and pilot inference complete |
| Weather | [Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api) | Raw JSON and normalized complete daily Parquet | Units/timezone/source pinned; no missing days |
| Soil prior | AquaCrop predefined soil classes; [SoilGrids context](https://www.isric.org/explore/soilgrids) | Explicit soil profile and provenance | No inferred calibrated hydraulic profile from texture alone |
| Mungi hydrology | [2022 study](https://doi.org/10.3390/w14030405) | Parameter excerpts with table/page, period, allowed use | Paper's scale/crop/time matched before reusing values |
| Cotton scheduling | [2024 study](https://doi.org/10.1016/j.ecohyd.2024.04.005) | Crop-specific reference notes | Reproduction claim only with input parity and error report |
| Crop context | [Punjab crop estimates](https://agripunjab.gov.pk/crs-crop-estimates) | Dated district table | Aggregate plausibility context only |
| Prices | [Punjab AMIS](https://www.amis.pk/ViewPrices.aspx) | Dated market observation and units | Wholesale/farmgate distinction, crop and season basis |
| Financing | [Punjab subsidies](https://agripunjab.gov.pk/wm-subsidies) | Program/site/applicant/date evidence | No grant by default |

Use a `resource_status.json` with `docs_checked`, `asset_identified`, `downloaded`, `checksum_verified`, `parsed`, `geographically_reviewed`, and `runtime_validated` as separate timestamps/results. A URL in this table is not a successful data integration.

For blocked Zenodo access, inspect the actual record on a permitted connection, or use the documented OSM fallback. Browser documentation access during authoring does not replace the local download gate. Avoid a whole-country data download on the critical path when a legal smaller source is available: a bounded Overpass query over the reviewed AOI returns canal features in seconds, while the national extract is a large download plus a filtering step. Note that OSM coverage of minor watercourses in rural Punjab is often incomplete; expect to add assumed (dashed, `geometry_ref=null`) connecting edges.

### T2.2 AOI discovery

The published Mungi search extent converts to approximately `[72.133333, 30.55, 72.8, 31.033333]` in `[west,south,east,north]` order. This is a broad literature search box, not a verified pilot. Keep it only in discovery configuration with `scope=published_search_extent`.

Procedure:

1. Compare the published map/named branch with actual GRAIN/OSM features and imagery. Record the evidence that supports the selected reach.
2. Choose two disjoint small agricultural AOIs with enough visible fields and a mapped canal context. Save actual AOI GeoJSON and area.
3. Verify longitude/latitude ordering, AOI geometry, raster overlap, and local metric projection. UTM zone 43N may be suitable in this area but calculate/check from the actual AOI.
4. Retain raw source features and construct a separate operational graph with reviewable assumptions. Do not turn geometric intersections into hydraulic junctions automatically.
5. Record `geographic_name_basis`; call the pilot Mungi only if the evidence supports that name.

Onboarding limits are configurable: initial polygon area ≤25 km² and raster pixel budget ≤25 million source pixels per selected scene; estimate bytes before acquisition. These are compute limits, not scientific sampling rules. A user can choose a smaller AOI; publication still requires 30 reviewed eligible fields for the full release fixture.

### T2.3 Canal import

Inspect the real schema and category values before filtering. Read GeoParquet with GeoPandas, assert CRS, normalize to EPSG:4326 for output, and preserve GRAIN/OSM identifiers and the actual category strings. GRAIN documents GeoParquet/shapefile access and an `Agricultural` use category. [Reading GRAIN](https://grain-canals.readthedocs.io/en/latest/reading_grain/)

Field-to-outlet and outlet-to-source associations are reviewed records. Restrict v2 to a directed acyclic tree per pilot: one unique source route per field. Reject cycles, dangling references, duplicate IDs, missing outlets, negative capacities, or delivery fractions outside `(0,1]`. A second watercourse can share an upstream edge. Alternative physical routes and dynamic gates require a later topology model.

Public map geometry can be incomplete. Store `geometry_ref=null` for an assumed connecting edge and render it dashed, rather than inventing an observed canal feature.

### T2.4 Imagery and AI pipeline

1. Query STAC with the reviewed AOI, date interval, and scene-level cloud filter. Scene-wide cloud cover is only a first filter; compute the valid fraction inside the AOI.
2. Inspect asset keys rather than hardcoding them from memory. Resolve RGB, near-infrared, and classification/mask bands from the selected collection/item metadata.
3. Read bounded COG windows; preserve CRS, transform, nodata, scale/offset, scene identity, and original pixels. Use categorical nearest-neighbor resampling for masks.
4. Apply cloud/shadow/snow/nodata filtering using the actual classification semantics. Produce an RGB image with a documented display stretch. A display stretch is not scientific reflectance data.
5. Run the exact upstream Delineate command/config in its separate environment. Initial expected interface is `python delineate.py -b <batch.yaml>`; confirm against the pinned commit.
6. Retain raw output. Review geometry validity, multipolygon handling, slivers, overlaps, and visible parcel alignment. Correct polygons with stable review IDs and a mapping from original model IDs.
7. Compute areas in the chosen metric CRS. Never use WGS84 degrees² for area. Save GeoJSON, metadata, correction log, and an overlay screenshot.
8. Generate a local display image reprojected to a consistent north-up grid and its WGS84 corner coordinates. Check spatial alignment using independent visible landmarks. MapLibre's image source accepts image data with geographic coordinates. [ImageSource API](https://maplibre.org/maplibre-gl-js/docs/API/classes/ImageSource/)

Use actual 10 m source resolution in legends. Interpolation does not create finer observed boundaries. A typical one-acre Punjab parcel is roughly 63 m across, about 6 Sentinel-2 pixels, so expect merged/split polygons and plan correction time accordingly; prefer AOIs with visibly larger parcels and select the 30 reviewed fields from the cleanest part of the inference output, recording that selection (PRD §5.2). Test Delineate on the upstream sample first, then on a small AOI crop, before running the full window. If local inference requires many edits, report it. CPU inference is a valid execution path if its measured runtime fits acquisition; do not claim GPU performance when the driver is unavailable.

NDVI uses physical reflectance after the published scale/offset, masked common valid pixels, and `NIR+red` denominator handling. Store median/mean and valid-area fraction. Comparison dates use compatible masks/resolution and expose cloud coverage; no water-stress diagnosis is derived directly.

### T2.5 Weather acquisition and normalization

Use the archive endpoint with actual pilot centroid coordinates, the full requested historical interval, `timezone=Asia/Karachi`, metric units, and:

```text
temperature_2m_min         -> MinTemp       degC
temperature_2m_max         -> MaxTemp       degC
precipitation_sum          -> Precipitation mm/day
et0_fao_evapotranspiration  -> ReferenceET   mm/day
time                      -> Date         local crop date
```

Pin a documented archive model when supported for the period; otherwise preserve the API's documented source selection and response metadata rather than asserting a station observation. Store requested and returned coordinates/elevation. Weather reused across nearby fields remains one gridded estimate, not 30 independent measurements. Two AOIs in the same command may resolve to the same or adjacent grid cells; check the returned coordinates, and if both pilots share a cell, share the weather files (and their crop experiments, via the experiment hash) rather than downloading and simulating duplicates.

Example ingestion outline, to implement with retry/manifest handling:

```python
payload = request_archive(actual_lat, actual_lon, start_date, end_date)
save_immutable_raw(payload)
w = normalize_archive(payload)
expected = pd.date_range(start_date, end_date, freq="D")
assert pd.DatetimeIndex(w["Date"]).equals(expected)
assert w["Date"].is_unique
assert not w[["MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]].isna().any().any()
assert (w["MinTemp"] <= w["MaxTemp"]).all()
assert (w[["Precipitation", "ReferenceET"]] >= 0).all().all()
```

Finite numeric checks are also required. Reject infinities and nonsensical physical ranges with a useful error, rather than coercing them to zero. Preserve missingness in raw data and never silently interpolate weather used in a final science run.

Acquire at least six complete historical growing-season series for each crop/pilot. Choose periods that actually precede the decision date. Define crop windows from the crop profile; do not use one universal date window for cotton and wheat. Assign training/validation/test years before examining model errors.

For future analog mapping, store a table of `original_date → scenario_date`, align by the declared planting-relative rule, and explicitly remove/interpolate leap-day inputs using one recorded method if lengths differ. Validate resulting daily continuity. Preserve the original source hash separately from the transformed weather hash.

Open-Meteo's hosted service has usage/attribution and commercial-use terms; record the chosen access arrangement before commercial deployment. The development acquisition client respects published limits and retries with backoff. [Historical API](https://open-meteo.com/en/docs/historical-weather-api) [Service terms](https://open-meteo.com/en/terms)

### T2.6 Package states and reproducible offline import

`acquired_raw → processed → needs_review → reviewed → validated → published`.

An acquisition job can pause for review. Its raw sources remain immutable. A published pilot has a manifest of relative paths, sizes, SHA-256 checksums, source IDs, licensing, and processing versions. Absolute user paths and secrets are excluded.

The second-region demo imports a prepared raw bundle and invokes the real processing/review/publish sequence. If inference/crop outcomes are reused, disclose a content-hash cache hit. A completed package import uses a different button and event log. These distinctions keep the onboarding demonstration truthful.

For package imports: validate manifest version, path traversal, duplicate filenames, file-size/expanded-size limits, allowed formats, hashes, and entity ownership. Parse GeoJSON/raster/Parquet using libraries; do not execute code from an imported archive. Never accept arbitrary remote URLs from the chatbot as fetch instructions.

## T3. Canonical units, IDs, schemas, and hashes

### T3.1 Identity and versioning

Use UUID/ULID internal IDs and stable human labels separately. Namespace imported source IDs by provider. A field retains its internal ID after a minor reviewed correction, while its `geometry_version` changes. Splits/merges create new IDs with `supersedes` relationships.

Core keys: `pilot_id`, `pilot_version`, `season_id`, `scenario_id`, `scenario_revision_id`, `run_id`, `candidate_policy_id`, `candidate_library_hash`, `intervention_instance_id`, `evidence_id`.

Never use a crop yield, centroid, display name, or array index as an entity ID. Keep field selection after sorting/filtering. All references validate membership in the active pilot version; cross-pilot IDs are rejected.

### T3.2 Unit and precision policy

| Quantity | Domain representation | Solver/display rule |
|---|---|---|
| Water volumes | float64 m³ with validated finite values | Default `water_quantum_m3=0.1`; consumed amounts rounded up, upper bounds down |
| Irrigation / rain / ET | mm, daily event/series | `volume_m3 = depth_mm × cropped_area_ha × 10` |
| Flow | m³/s with start/end interval | `max_volume = rate × available_seconds`; window identity retained |
| Area | m² and ha with CRS metadata | Pond footprint subtracted once; final production uses cropped area |
| Yield / production | kg/ha / kg | Normalize upstream output once; public UI may show t/ha and tonnes by ÷1000 |
| Budget / quoted cost | Integer PKR | Ceil calculated spend for feasibility; explicit decimal rate arithmetic first |
| Unit prices/rates | Decimal string with currency/quantity unit | Avoid binary float for currency calculations |
| Efficiencies | Domain fractions `[0,1]` | Adapter converts AquaCrop AppEff to percent explicitly |
| Service ratio | Exact quantities plus scale | Floor credited receipts for lower-bound service checks; do not reuse resource-ceil coefficients |
| Time | UTC instant + original offset; local date | Local crop date derived in Asia/Karachi; Gregorian date library for ISO weeks |

Keep the physical ledger at original precision. Conservatively rounded coefficients can create false infeasibility but must not create false feasibility. If rounding changes a relevant result, rerun with a finer quantum within integer bounds. Do not fix ledger balance by adjusting a residual “loss” term.

### T3.3 Provenance model

`EvidenceRecord` fields:

```text
evidence_id, source_title, source_url?, source_asset_id?, retrieved_at?
source_period?, geographic_scope?, license_id?, raw_sha256?
kind: observed_remote_sensing | public_geography | gridded_reanalysis |
      literature | user_supplied | assumption | model_output | derived
transformation?, parent_evidence_ids[], units?, method_version?
verification_state: unchecked | source_checked | artifact_checked | locally_reviewed
limitations[], assumption_range?, reviewer?, reviewed_at?
```

Verification state describes review work, not truth or model accuracy. Source age, geographic mismatch, and calibration status are separate flags. Every displayed KPI is a `MetricValue` containing `metric_id`, `value|null`, `unit`, `definition_id`, `run_id`, `evidence_ids`, and `status=available|not_estimated|not_applicable|blocked` with reason.

### T3.4 Entity minimums

| Entity | Required fields beyond ID/version |
|---|---|
| Pilot | name, AOI, source/geometry refs, metric CRS, review flags, timezone, package hash |
| Field | geometry ref/version, gross area, crop profile, soil profile, outlet, group, owner ref optional, evidence |
| Edge | upstream/downstream nodes, geometry ref optional, permitted delivery factor, interval capacities, closure schedule, provenance |
| RosterWindow | field/outlet, start/end instants, rate/volume cap, accounting boundary, verification, source rule |
| ServiceReference | field, fixed reference receipt amount by period, volume/time-derived basis, denominator evidence |
| Asset | type, target/location, existing/proposed, ownership/shared resource, dates, capacity/rates, costs, footprint, evidence |
| InterventionType | effect-model name/version, applicability schema, required parameters |
| InterventionInstance | type, target IDs, parameter values, prerequisites, mutually exclusive group, costs, lead time, commissioning |
| WeatherSeries | original and mapped date refs, point/model, units, complete bounds, source/transformation hashes |
| CropProfile | name, parameter set/version, planting/harvest bounds, yield basis, calibration status, source |
| ScenarioRevision | full request snapshot, pilot/library dependencies, semantic hash, parent revision, created_at |
| CandidatePolicy | same physical decision definition across states, events, required instances, costs, per-state outcome refs |
| Run | scenario revision, execution mode, status/bounds, selected policies, exact validation, metrics, trace refs |
| Job | operation, immutable request hash, lifecycle, progress events, cancellation/heartbeat, result/error ref |

For `time` rights, a derived volume is a configured capacity/reference under the supplied discharge assumptions, not a replacement legal entitlement. Label the UI ratio “receipt / reference allowance” when the denominator is time-derived. Preserve the original time windows. For true volumetric entitlements, use their documented boundary and cap.

### T3.5 Scenario request example

All values below are illustrative configuration, not measurements or recommendations. Referenced IDs must exist before the request is accepted.

```json
{
  "contract_version": "2.0.0",
  "pilot_id": "pilot-a",
  "pilot_version": "reviewed-v1",
  "season_id": "wheat-rabi-2027-28",
  "planning_mode": "capital_planning",
  "decision_at": "2026-10-10T08:00:00+05:00",
  "weather_scenario_ids": ["dry", "typical", "wet"],
  "supply_profile_id": "nominal-roster-v1",
  "uniform_reduction_fraction": 0.22,
  "capital_budget_pkr": 3000000,
  "operating_budget_pkr": 250000,
  "objective": "production_kg",
  "optimization_mode": "typical",
  "uncertainty_set_id": null,
  "minimum_service_ratio": 0.6,
  "service_group": "tail",
  "permit_groundwater": true,
  "blocked_edge_ids": [],
  "allowed_intervention_instance_ids": ["pilot-a:field-007:pond-small"],
  "assumption_set_id": "declared-assumptions-v1"
}
```

Enumerations: planning modes match the PRD; `optimization_mode=typical|worst_case`; `objective=production_kg|irrigation_contribution_pkr`. Worst-case v2 supports the crop-specific production objective only. The request identifies the typical member explicitly in weather-scenario metadata. A scalar reduction multiplies the named base schedule once; pre-reduced profiles declare their baseline and cannot silently receive the same reduction twice.

`worst_case` requires a published `uncertainty_set_id`. It references explicit state records `(weather_scenario_id, resolved_supply_profile_hash)`, including the nine-state release grid. Each supply profile stores its unreduced base hash and ordered transformations. Transformations distinguish an absolute replacement multiplier, an additional relative multiplier, and a dated closure; the UI displays the resulting total change. Resolve all state profiles before solving and reject duplicate application of the same transformation ID. Stress and robust services use this same resolved set, not an unrelated hidden grid.

No `investment_commissioned_before_season` shortcut exists. Assets derive availability from dates. Invalid crop/season combinations, absent prices for the financial objective, out-of-bounds service targets, stale libraries, or missing costs produce typed validation errors.

### T3.6 Hashes and cache keys

Canonical JSON uses sorted keys, stable array order for semantically ordered events, normalized units/timezones, and explicit null semantics. Hash semantic inputs rather than incidental UI ordering. Decimal values have one normalized representation. Sort set-like ID arrays before hashing.

Separate hashes:

- `crop_experiment_hash`: actual crop model inputs, daily weather content, dated gross irrigation, soil/initial state, AppEff, engine/adapter version. Area may be excluded only if the crop calculation is explicitly per-area and all area-dependent effects already change its inputs.
- `candidate_policy_hash`: physical events, field/asset/rights/topology versions, crop experiment refs, effect/cost assumptions, candidate generator version.
- `scenario_hash`: full semantic request and every referenced input/library/solver configuration hash.
- `run_id`: execution identity; identical inputs may generate another run and retain the same semantic hash.
- `report_hash`: run/metric definitions and report-template version.

Changing a field area invalidates its volumetric candidate feasibility even if its per-hectare crop response can be reused. Changing costs invalidates objectives/reports without necessarily rerunning crop physiology. Changing a library, soil, efficiency, calendar, or weather invalidates the relevant exact/surrogate outputs. Record this dependency graph explicitly.

## T4. Chronological water model and action effects

### T4.1 Clocks and atomic intervals

The crop model consumes daily irrigation. The physical ledger uses timestamped events. The solver uses the smallest non-overlapping delivery intervals induced by roster boundaries, capacity changes, closures, and action commissioning/downtime. Weekly arrays are derived display aggregations only.

For every candidate, sort events by `(timestamp, explicit_order, event_id)`. Receipts must occur no later than dependent release/application. Simultaneous events have an explicitly defined order; never rely on JSON insertion order. At each interval, impose source and edge volume/rate bounds over its actual duration.

This lets a field receive Friday water, retain it in a pond, and irrigate later, while rejecting Monday use of a future receipt. The daily crop approximation does not establish hourly crop physiology; the event ledger establishes water availability.

### T4.2 Network routing

For field outlet delivery `D` through unique path edges with factors `eta_e`, derive each edge's intake recursively upstream: required intake at an edge equals downstream demand divided by that edge's delivery factor. Sum demands sharing an edge for each atomic interval. Loss equals edge intake minus edge delivery. Do not apply an aggregated conveyance factor a second time.

At junctions, upstream delivered volume equals summed downstream intakes plus any explicit local delivery/storage/spill. Pump injection specifies its node; on-farm pump water must not consume upstream canal capacity. An edge closure sets available capacity to zero for the affected interval. All downstream canal delivery through that path then becomes unavailable.

A fractional-loss model is an explicitly simplified scenario model. Its calibration state is visible. It does not estimate transit hydraulics, backwater, gate response, or groundwater recharge dynamics. Avoid claiming that geographic slope verifies direction/flow.

### T4.3 Roster caps and shortage

For each fixed window, derive the allowable volume from the declared boundary-specific cap/rate and the source-profile curtailment rule. A scalar shortage reduces available supply and associated window availability once. Shared repairs may change delivery factors; recalculate configuration-specific routing/caps consistently without transferring another field's window.

Coupling note: roster windows are exclusive in time, so fields on one watercourse do not compete for canal volume inside their own windows. Cross-field interaction enters the model only through per-reach delivery factors (tail outlets receive less of the same time right), shared repairs that change those factors, shared pumps, simultaneous flows on shared upstream edges, and the two budgets (PRD §6.1). Give each watercourse at least two reaches with distinct `eta_e` so a repair changes tail receipts, and expect the edge-capacity constraints inside a single watercourse to be slack; that is correct behavior, not a bug.

Compute source/edge capacities independently of candidate selection. Candidate use is bounded by both those capacities and the field's available window. A window can be underused; unused water is not counted as delivered service. Do not credit water that simply remains available upstream as a withdrawal or benefit.

The full-supply service denominator remains a fixed documented reference across compared plans. A time-derived reference can differ from actual allowed volume under a changed edge configuration; label it as a reference ratio, permit interpretable values above one if physically authorized, and never silently clamp them to conceal the difference. Hard service floors are applied to the declared reference, not to a denominator chosen by the optimizer.

### T4.4 Pond model

For an event step of duration Δt:

```text
S_next = S_start + canal_fill + permitted_pump_fill + direct_rain
         - released_to_field - evaporation - seepage - explicit_spill
0 <= S_at_every_event <= usable_capacity
```

Loss is bounded by available inventory. Apply a documented surface-area/depth approximation. For a constant-area demo pond: evaporation volume = supplied evaporation-depth assumption × water-surface area; rainfall volume = rainfall depth × water-surface area × capture factor. FAO reference ET0 is not automatically open-water evaporation: use and disclose a configured conversion coefficient if ET0 drives this estimate. Seepage is a declared bounded rate. All parameters carry assumptions/ranges.

With depths in mm and area in m², use `evaporation_m3 = k_evap × ET0_mm × surface_area_m2 / 1000` and `rain_m3 = rainfall_mm × surface_area_m2 × capture_fraction / 1000`, then cap actual losses by available storage in event order. For subdaily bookkeeping, document how daily forcing is apportioned; it is not an observed hourly series. An automatic overflow rule may produce explicit spill when inventory reaches capacity, but may not silently discard water.

Use site footprint, maximum water surface area, usable depth/storage, dead storage if modeled, fill/release limits, commissioning, and land availability. Reject inconsistent geometry/capacity or disclose a separately sourced engineering capacity. A 250 m³ example pond is not automatically an appropriate size for a local field. For scale, one 75 mm basin irrigation on a 1 ha field is 750 m³, so 250 m³ stores about a third of one irrigation. Define pond size options by the irrigation depth they can hold for the target field (for example 0.5, 1, and 1.5 irrigations), then derive volume, surface area, and footprint from that.

An on-field pond changes `cropped_area_ha = gross_area_ha − pond_footprint_m2/10000` after construction. Reject negative/zero crop area when the selected policy requires a crop. Existing-pond footprints already removed from baseline area are not subtracted again.

Define start/end state clearly. A valid illustrative two-period trace is: start 0, fill 120, irrigate 100, loss 5, end 15; next period start 15, no fill, release 10, loss 1, end 4. Record all quantities rather than letting inventory disappear between periods. These numbers are a unit-test fixture, not a real field record.

### T4.5 Pumps and operations

Each pump has asset ID, accessible fields, available intervals, max rate, seasonal cap, optional shared energy/volume budget, injection boundary, unit cost, and quality/permission assumptions. Constrain a shared pump across all fields, not independently per field. A field-level cap cannot replace an aquifer-wide scenario cap when one is configured.

If head/efficiency are provided, estimate energy using `rho*g*V*H/(3.6e6*eta)`, with units and assumptions. Otherwise use a declared cost per m³; do not invent kWh. Solar pumping still has capacity and extraction limits. Unsupported salinity effects are not silently approximated by a yield multiplier.

### T4.6 Intervention effects and commissioning

`commissioned_at = explicit_existing_date` for existing assets; for proposals use decision date + procurement/start delay + construction/service lead time + calendar constraints. An override requires a reviewed dated record, not a generic checkbox. Leveling before planting may be eligible; earthwork on a standing crop is unavailable unless explicitly supported by an action model.

V2 specifically requires proposed ponds and leveling to be commissioned before planting. This keeps cropped area and AppEff constant during each crop experiment. Reject mid-season changes to these quantities rather than pretending the engine models their transition. Shared edge repair effects may vary by interval because their effect is represented explicitly in routing and supply; construction downtime must be present in that profile.

Shared repair configurations update edge factors/capacities and any construction downtime. A repair can improve all downstream candidate routes; its capex is charged once. Leveling changes an application-efficiency parameter passed once to the crop adapter. Proposed ponds change storage/land/time costs. Groundwater is an operational option for an existing asset, not an automatically free new well.

### T4.7 Physical validation report

Return per-rule residuals and entity/time references: source/edge capacity, node balance, field receipt rights, pump sharing, pond chronology/capacity, area, commissioning, cost completeness, daily application consistency. Default floating conservation tolerance is an absolute `1e-6 m³` plus a relative `1e-9` of the compared magnitude, configurable and recorded. Engineering approximations are input uncertainty, not floating-point tolerance.

Solver rounding tolerance is separate. Any accepted result is reconstructed and validated with original-precision quantities. Numerical infeasibility after reconstruction invalidates the run; it must not be rendered as a valid plan.

## T5. Crop adapter, experiments, and candidate generation

### T5.1 A source-verified correction to the original handbook

The upstream irrigation notebook contains a lowercase `schedule=` example, while current upstream `IrrigationManagement` source allows the key `Schedule` and filters unsupported keyword names. The previous handbook's unconditional recommendation of lowercase is unsafe. Inspect the installed version and assert that the resulting object's schedule equals the requested DataFrame. [Constructor source](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/entities/irrigationManagement.py) [Notebook example](https://aquacropos.github.io/aquacrop/notebooks/AquaCrop_OSPy_Notebook_2/)

The upstream irrigation calculation also caps prescribed depth using `MaxIrr` and total irrigation using `MaxIrrSeason`. A planned 30 mm event can otherwise become 25 mm under the default daily cap. Verify actual applied irrigation against the ledger. [Irrigation implementation](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/solution/irrigation.py)

### T5.2 Adapter construction

Implement `CropSimulatorAdapter.evaluate(CropExperiment) -> CropOutcome`. It creates fresh crop/soil/initial-water/management instances per experiment; never reuse mutable model objects across candidates or parallel jobs.

Illustrative adapter fragment to verify against the installed package:

```python
schedule = daily_events_to_dataframe(events)  # Date, Depth; local naive dates
assert list(schedule.columns) == ["Date", "Depth"]
assert schedule["Date"].is_unique
assert (schedule["Depth"] >= 0).all()
assert schedule["Depth"].max() <= physical_daily_limit_mm
assert schedule["Depth"].sum() <= physical_season_limit_mm

management = IrrigationManagement(
    irrigation_method=3,
    Schedule=schedule.copy(),
    AppEff=application_efficiency_fraction * 100.0,
    MaxIrr=physical_daily_limit_mm,
    MaxIrrSeason=physical_season_limit_mm,
)
assert management.Schedule.equals(schedule), "Installed schedule interface mismatch"
```

Set `MaxIrr` explicitly from the declared field application limit. Punjab basin/flood irrigation commonly applies on the order of 50–100 mm in a single turn, far above the package's default daily cap, so leaving the default would silently clip almost every canal irrigation (T5.4 gate 4 catches this). Similarly set `MaxIrrSeason` from the declared seasonal limit rather than the default.

AquaCrop-OSPy uses numba; the first simulation in each process pays a one-time compilation cost. Warm up each worker process with one small run in a pool initializer, and exclude that warm-up from the per-run benchmark in T8.1.

Empty/no-irrigation schedules use a correctly typed empty DataFrame and explicit method behavior verified by the smoke suite. Aggregate multiple irrigation events on one local day after chronological physical validation. Daily total depth must correspond to actual field-applied gross volume and current cropped area.

`AppEff` is applied inside the infiltration calculation in current upstream code. The ledger records gross irrigation delivered to the field; the adapter passes gross depth and the application efficiency once. [Infiltration source](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/solution/infiltration.py)

### T5.3 Output normalization and audit

Use documented getters after model execution: `get_simulation_results`, `get_water_storage`, `get_water_flux`, and `get_crop_growth`. Save original DataFrames and column names before normalization. [Core API](https://aquacropos.github.io/aquacrop/core/)

The upstream output entity identifies dry/fresh yield columns in tonne/ha and seasonal irrigation in mm. Convert the selected yield basis to kg/ha exactly once; carry `yield_basis` into every result. Do not assume cotton model dry yield equals the raw-cotton market unit without a supported mapping. [Output source](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/entities/output.py)

Required normalized `CropOutcome`:

```text
experiment_hash, engine_name/version, adapter_version, executed_at
crop_profile_id, soil_profile_id, weather_hash, schedule_hash
planting_date, actual_harvest_date?, has_finished, yield_basis
yield_kg_ha, seasonal_irrigation_mm
daily_gross_irrigation_mm, daily_canopy_fraction?, daily_biomass_kg_ha?
daily_soil_profile_water_mm?, daily_root_zone_water_mm?
daily_evaporation_mm?, daily_transpiration_mm?, daily_et_mm?
daily_runoff_mm?, daily_deep_percolation_mm?
raw_output_refs, field_mapping_version, warnings[], evidence_id
```

Only map a column after verifying its identity/unit and time index in the installed version. A missing variable is null with an explanation. Soil water content per compartment is not itself mm; if computing storage, use compartment thickness and units. Root-zone storage requires root-depth information and partial-layer integration. Otherwise show total profile water with that name.

Ensure the run has completed the intended season and produced a harvest result. A simulation stopped before maturity is not a completed yield experiment. Mask any preallocated trailing rows beyond actual termination. Align array indices to the actual simulation calendar, including off-season dates; do not assume row 0 equals planting day.

Audit every day: package-reported gross irrigation equals scheduled gross depth within tolerance. A discrepancy caused by clipping, out-of-season events, or unsupported constructor keys is a failed experiment. Early pond filling can occur before planting if the physical horizon/weather covers it; pre-plant field irrigation is unsupported in v2 unless a separately validated adapter path handles it. Initial soil state is supplied at the actual simulation start, not ambiguously at planting.

### T5.4 Scientific smoke gates

1. Run the published package quickstart unchanged; save package versions/stdout/output hashes.
2. Run one complete local historical wheat season with no irrigation, one explicit schedule, and a different admissible schedule. Confirm actual treatment differences, finite outputs, correct units, and explained response. Do not assume more water always increases yield.
3. Repeat for cotton using a verified package crop name and reviewed parameter/calendar profile.
4. Use a schedule containing a depth above the package's default cap to prove configured caps and clipping detection work. This is a synthetic adapter test, not a recommended local depth.
5. Compare efficiency 1.0 with another declared value at the same gross input; verify the water-accounting interpretation and that efficiency is not applied twice.
6. Test an event outside the active crop interval; it must fail the adapter/ledger consistency check rather than silently improve reported treatment.
7. Confirm selected result columns and yield basis against a manually inspected raw output.

Field calibration is distinct from this software/scientific sanity validation. Record local validation as absent until independently observed inputs/outcomes support it. District averages are coarse plausibility checks, not evidence of field predictive error.

### T5.5 CandidatePolicy design

A candidate is a complete dated physical decision for one field under one shared-repair configuration, including asset prerequisites and an exact outcome for each required weather state. It is not a scalar “water amount → yield” row.

```text
candidate_policy_id, field_id, crop_profile_id, soil_profile_id
physical_horizon, shared_configuration_id, required_instance_ids[]
receipt_events[], direct_application_events[], pond_events[], pump_events[]
cropped_area_ha, asset_footprints, physical_validation_ref
source/edge/pump consumption sparse arrays by atomic interval
service_credit arrays at declared boundary, capital/operating cost refs
outcomes_by_weather_state, trajectories_by_weather_state
candidate_policy_hash, generator_version, coverage_tags[]
```

The policy's controlled receipt, application, release, and pumping decisions are the same across uncertain weather states for robust selection. Exogenous pond rain, modeled losses, and spill under a fixed automatic-overflow rule may vary by weather; each state must pass the resulting ledger. Scenario-specific optional recourse gets a different explicitly labeled run, not a changed policy hidden under the same ID.

### T5.6 Candidate generation algorithm

Generate policy templates around permitted turns, planting-relative phases, optional storage offsets, and bounded irrigation depths. The roster/ledger is authoritative about whether a template is possible.

```text
for pilot/crop/season and shared configuration:
  load frozen geometry, field areas, roster, assets, costs, source profile
  construct baseline's actual dated policy
  for each field:
    include baseline, no-new-capital, and a zero-receipt (rainfed) policy, always
    include low-water policies when meaningful
    enumerate bounded timing/depth/storage/pumping/leveling variants
    derive volumes from cropped area; charge distinct asset instances
    validate chronology, site/commissioning, rights, pump limits, local storage
    derive sparse network coefficients from the configuration's route factors
    for each required weather state:
      validate weather-dependent pond balance
      obtain exact crop outcome by experiment hash, running if absent
    retain valid policies and reasons for rejected templates
  remove only safely dominated policies; publish immutable library
```

Local feasibility does not establish aggregate shared-source/edge/pump feasibility; the solver handles those interactions. Conversely, do not prevalidate using a hardcoded final community water allocation that removes legitimate choices before optimization.

The zero-receipt policy is mandatory for every field: it is deliverable in every supply state, so without a service floor the portfolio model and the robust model can never be infeasible merely because one field lacks a deliverable candidate. Infeasibility then correctly points at the service floor, budget, or a shared resource.

**Experiment reuse (this is what keeps the science batch tractable).** A crop experiment depends on crop, soil profile, weather series, initial state, AppEff, and the dated gross depth schedule in mm. It does not depend on field area or on which field it is. Generate schedule templates per (crop, soil archetype, AppEff) and run each once per weather state; candidates for each field are then (template × field area × assets), validated in the ledger, with the crop outcome looked up by `crop_experiment_hash`. Rough budget per pilot and crop: 3 soils × 2 AppEff × ~40 templates × 3 analog weather states ≈ 720 simulations, so about 2,900 across both pilots and crops before deduplication (less if pilots share weather). Supply-profile stress states do not need new crop runs unless they force a different schedule. Measure the per-run time in M0 and recompute; at a few seconds per run and many worker processes this fits in tens of minutes, but it must be launched early (end of M2) and run in the background.

A field's option count target is 24–60 after pruning. This is a computational design target, not proof of comprehensive search. Enrich near binding periods/service floors when requested settings leave few options. If a low-water candidate does not meet a service floor, the model may remain infeasible and must state its candidate coverage.

Safe dominance requires at least as good objective across relevant weather states, no greater constrained resource use, no worse credited service, compatible asset prerequisites, no greater costs, and no hidden timing/terminal-state disadvantage. If any of these differ in an incomparable way, retain both candidates. Blindly pruning by seasonal water and yield alone is invalid.

### T5.7 Candidate-library adequacy

Store counts generated/rejected/retained per field and reasons, coverage of depth/timing/action families, and exact outcomes. Add a denser library on representative scenarios and report objective/action stability. When a denser library changes the chosen investment, retain the larger library for those scenarios and disclose the approximation.

For an infeasible run, distinguish: missing valid input; empty field option set; finite candidate incompatibility; and an independently established bound contradiction such as mandatory source demand exceeding all available supply. Only the last, with its assumptions, supports a stronger physical explanation.

## T6. Optimizer, baselines, and solver proofs

### T6.1 Decision variables

For a fixed shared infrastructure configuration `c`, binary `x[i,k]` selects exactly one admissible field policy. Binary `z[j]` selects a field-level investment instance. The selected shared configuration contributes its own fixed one-time cost and effect parameters.

```text
sum_k x[i,k] = 1                                      for every field i
x[i,k] <= z[j]                                        for required new instance j
z[j] <= sum_(i,k requiring j) x[i,k]                   prohibit unused purchases
sum_(j in mutually_exclusive_group g) z[j] <= 1
shared_capex[c] + sum_j capex[j]*z[j] <= capital_budget
sum_(i,k) seasonal_opex[i,k]*x[i,k] + shared_opex[c] <= operating_budget
sum_(i,k) resource[i,k,r,t,omega]*x[i,k] <= capacity[r,t,omega]
sum_(i,k) groundwater_season[i,k,a]*x[i,k] <= seasonal_cap[a]
service[i] >= requested_floor * fixed_reference_allowance[i]
```

Resources include source, all shared network edges, shared pumps, and any configured energy/source totals. Individual roster/pond/date constraints are already certified per candidate; retain their validation references and recheck selected policies. Never charge per-candidate capex and `z` capex simultaneously.

For existing assets, no new purchase variable is required, but operating cost, footprint, capacity, maintenance, and initial inventory still apply. Policy prerequisites refer to instances present in the exact pilot version.

The capital constraint uses gross project commitment. Verified grants are reported separately and affect a participant-cash constraint only if that additional named budget is configured. They never silently inflate the gross capital budget. Operating-budget constraints cover all modeled seasonal variable costs of the chosen actions, including existing-pump use.

### T6.2 Integer scaling

For a resource upper bound with quantum `q`, use `ceil(consumption/q)` and `floor(capacity/q)`. For a lower service bound, use conservative credited receipt `floor(receipt/q)` and `ceil(required/q)`. These are separate coefficients even if derived from the same physical quantity.

Choose production quantum `production_quantum_kg=0.1` initially, record objective rounding bounds, and run original-precision validation. Validate that sums/coefficient products stay safely below CP-SAT int64 limits. If they do not, rescale quantities without weakening feasibility, and document objective quantization.

Do not apply ceil to conserved ledger entries and then force those rounded numbers into equality as if they were exact water. The prevalidated physical network supplies the coefficients; conservative resource tests may underuse capacity slightly. Report that conservative margin and refine `q` if it materially changes selection.

### T6.3 Objectives and tie-breaks

Default primary objective:

`production_kg(omega) = sum_(i,k) cropped_area_ha[i,k] * yield_kg_ha[i,k,omega] * x[i,k]`.

For typical planning, maximize the designated typical state's production. For robust planning, introduce `v` and enforce `v <= production_kg(omega)` for every defined state, then maximize `v`. Resource feasibility must hold for every robust state as well.

Apply lexicographic secondary solves while preserving the best attained **integer primary objective**: minimize operating spend, then capital, then source withdrawal. After each stage, constrain the next stage to preserve that stage's attained value. Numerical equivalence is defined by the declared objective quantum; do not additionally allow a hidden percentage production loss while retaining an OPTIMAL primary label. Report original-precision production and the aggregate objective-quantization bound. If any stage is unproven, label its refinement feasible and keep primary/secondary proof statuses separately. Global lexicographic proof also requires resolving all tied shared configurations, not merely proving one configuration's primary result.

`irrigation_contribution_pkr` uses crop output value less all documented decision-dependent seasonal costs. Capital remains a separate constraint and tie-break; do not subtract a full long-lived asset from one-season operating contribution and label that NPV. Financial mode is unavailable without compatible yield/price basis and complete variable costs.

### T6.4 Shared repair enumeration and global status

Limit each pilot to at most two shared repair decisions for v2, hence at most four configurations. Enumerate all admissible configurations, derive coherent routing/receipt coefficients for each, subtract its capex once, and solve the field-policy model. Use a global wall-clock budget across configurations, not a full timeout independently for every hidden subsolve.

For maximization, the global incumbent is the greatest validated feasible objective among configurations. The global upper bound is the maximum of valid upper bounds for unresolved/solved admissible configurations. A configuration proven infeasible contributes no feasible objective. An unexplored configuration without a valid bound prevents a global optimality claim.

Global `OPTIMAL` requires every alternative to be proven infeasible or bounded no better than the incumbent within recorded objective quantum. Global `INFEASIBLE` requires every admissible configuration proven infeasible and no candidate-generation error. Otherwise use `FEASIBLE` when an incumbent exists, or `UNKNOWN` when none has been found. These terms concern the finite candidate model.

CP-SAT exposes solver statuses and integer-domain requirements; record wall time, bound, and returned status rather than inferring success from a nonempty UI. [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)

### T6.5 Baseline construction

B0 uses the same roster and source curtailment/closure processing as optimized plans. A deterministic rule specifies what happens to each received amount: admissible immediate application, existing pond storage, permitted later release, explicit overflow/spill, or unused withdrawal. Pumping follows a declared bounded rule. Do not force an impossible historical “normal-water” schedule into a drought baseline.

Execute B0 through the ledger and crop adapter, storing its actual actions/outcomes. Include that policy in the candidate library when feasible. B1 solves the same model with new investment instances disabled. B1 can differ from B0 only by re-operating existing assets, so the pilot fixture must include at least one existing pond and one existing shared pump, and B0's rule must be a plausible non-optimal habit (PRD §6.4); otherwise B1 = B0 and the ladder shows nothing. Add an assertion that warns when B1 and B0 select identical policies for every field. P includes those no-investment options, and its search is seeded with B1 if the same constraints permit it.

For “investment-only” diagnostic comparisons, hold the operational rule fixed while applying feasible asset changes and regenerate actual ledger/crop outcomes. Do not reuse an impossible old schedule under changed cropped area or capacities. B0/B1/P/R comparisons carry an explicit compatibility certificate.

### T6.6 Run completion and reconstruction

A solver incumbent is provisional until the domain layer:

1. Resolves selected policy/asset instances from the correct library.
2. Reconstructs the full chronological physical ledger at original precision.
3. Verifies all shared and field constraints, dates, crop outcomes, footprints, budgets, and entitlement/reference definitions.
4. Recomputes metrics from exact stored outcomes and the reconstructed ledger.
5. Writes immutable artifacts to a temporary run directory, hashes them, atomically finalizes the directory, then commits SQLite references.

A validation failure marks the run invalid and prevents recommendation cards/export as a valid plan. Return the diagnostic artifact and retain it for debugging. The UI can display an error without inventing alternate metrics.

## T7. Expanded analysis services

### T7.1 Frontier service

Accept a base revision and explicit grid of at least six `(capital_budget, service_floor)` pairs. Create immutable child revisions, enqueue solves with a total analysis budget, and stream completed point IDs. Compute nondominance using the actual metric vector and consistent objective definitions; no same-scale comparison between unlike crops.

Each point includes `run_id`, feasibility, objective/bound, actual spend, service, pumping, and proof status. Deduplicate identical portfolios while retaining parameter settings that produced them. A feasible point may be dominated; keep it available for inspection. If a point is unknown, show unknown rather than connecting a smooth invented curve through it.

Nondominance among observed feasible points is distinct from a proof of a complete frontier. A point's apparent superiority may remain unresolved while solver bounds overlap. Explain that status on selection.

### T7.2 Stress and robust services

Freeze selected investments and dated field policies for `fixed_plan` evaluation. For each of the nine states, rerun weather-dependent storage and capacity validation before crop metrics. An invalid receipt schedule yields `deliverable=false`, constraint references, and null achievable production for that plan.

`recovery_plan` holds investments fixed but reoptimizes operations for one specified state. Label the result a conditional recovery comparison; selecting different operations after seeing each whole season is not a single prospective plan.

The robust service evaluates every candidate under all selected states and retains only policies with valid local ledgers in all states. CP-SAT imposes all corresponding shared capacities and maximizes minimum exact crop production. This uses one `x`/`z` across states, without nonanticipativity leakage. Weather-state probabilities are unnecessary for this worst-case objective.

Supply scenarios can include dated zero-capacity interruptions, gradual reductions, or seasonal profiles. Preserve the source reference and actual time interval; a two-week interruption and a uniform seasonal deficit are not interchangeable merely because their total volumes match.

### T7.3 Why-not and sensitivity

For forced action `j`, create a child scenario that requires it and otherwise preserves constraints. For excluded action, force `z[j]=0`. Solve and compare identical metric definitions. If forcing makes the model infeasible, explain verified prerequisites/budget/conflict groups rather than inventing a foregone profit.

For two maximization runs with incumbent/bounds `[L1,U1]` and `[L2,U2]`, a supported interval for objective difference is `[L1-U2, U1-L2]`. Report an exact difference only to the warranted numerical/proof precision. Infeasible/unknown states have separate reporting.

Marginal water value perturbs a named source interval by a finite physically permitted ΔV, recomputes dependent window caps consistently, and re-solves. Divide objective change by actual ΔV and label a finite-difference sensitivity. A 1 m³ perturbation may have no effect with a coarse candidate library; display step size and coverage.

For cost/effect/soil sensitivity, generate child scenarios with a documented range. Reuse science only when input hashes permit it. If choices change within the range, identify the measurement/quote that could resolve the decision. Do not call selection frequency across chosen scenarios a calibrated probability.

### T7.4 Synergy

Specify A/B as compatible intervention instances, not vague categories. Solve none, A-only, B-only, both with consistent availability and other-action policy. Choose either “other investments fixed” or “other investments may reoptimize,” show which, and use it consistently across all four runs.

Compute `outcome_AB − outcome_A − outcome_B + outcome_none` using the same outcome unit. Positive, zero, and negative are valid. If a combination is infeasible or has unresolved bounds, display that limitation and avoid a false exact synergy percentage.

### T7.5 Economics and SDG metric definitions

Metric functions live in one server registry consumed by UI, report, and chat. A definition records formula, boundary, crop/yield basis, aggregation, missing-data behavior, and evidence dependencies.

Examples:

```text
modeled_production_kg = sum(cropped_area_ha * exact_yield_kg_ha)
withdrawal_productivity_kg_m3 = production_kg / (canal_source_m3 + groundwater_m3)
field_service_ratio = received_canal_m3 / fixed_reference_allowance_m3
tail_min_service = min(valid tail-field ratios)
incremental_irrigation_contribution_pkr =
    delta(crop_value_pkr - specified_irrigation_variable_cost_pkr)
worst_tested_production_kg = min(production in deliverable tested states)
```

For zero withdrawal, productivity is `not_applicable`, not infinity. For a fixed plan with any undeliverable stress cell, do not silently compute “worst tested production” only over the surviving cells: expose infeasibility and label any conditional minimum over deliverable cells. Null and zero have distinct meanings.

A water ledger must avoid double-counting field runoff/deep percolation as both gross application loss and a separately added input/output. Separate soil-water accounting from network/pond accounting. Summing all ET components plus ET itself is invalid.

Map the PRD's SDG proxies to these functions with citations to the actual target definitions. Store `official_indicator=false` for project proxies. Any optional greenhouse-gas estimate needs a separate evidence-backed energy/emission-factor formula; it is not synthesized from water saving alone.

## T8. Surrogate training and exact confirmation

### T8.1 Purpose and experiment budget

The exact library supports fast portfolio selection already. The surrogate's justified role is exploring new in-range schedules/parameters before spending time on exact crop runs, not claiming a faster lookup than a cached table.

Start with a structured simulation design:

`2 pilots × 2 crops × 6 weather years × 3 soil archetypes × 12 policy families × 2 application-efficiency settings = 1,728 planned experiments`.

This is a budget estimate, not an executed sample count. A policy family must resolve to actual dated irrigation inputs. Separate date/depth variants and supplemental-water/storage-derived schedules expand the experiment list only when needed for coverage. Deduplicate by exact experiment hash, not by treating distinct weather/soil contexts as identical.

Benchmark ten complete crop runs before launching the batch. Estimate total time from measured median/p95 and safe process concurrency. Begin with two science processes and increase only after memory/CPU measurement. Avoid nested LightGBM/BLAS/solver thread oversubscription. Store progress and allow restart from completed hashes.

### T8.2 Features and target

Separate models per crop/yield basis. Features include soil parameters/archetype, declared initial moisture, crop/cultivar configuration, planting-relative schedule summaries, gross application by fixed growth-calendar windows, application efficiency, and weather summaries over matching windows. Include nonlinear timing information sufficient to distinguish schedules with the same total irrigation.

Feature construction uses only experiment inputs or an independently specified crop calendar. Do not use simulated harvest index, final biomass, final stress, or model-derived outcome states as predictive inputs. Those would leak the target. Historical weather summaries are available in a scenario replay; their use does not make the surrogate a forecast of unknown future weather.

Target is the exact adapter's `yield_kg_ha` for that crop/basis. It is simulated yield, not measured harvest. Keep training data and model artifacts versioned with parent experiment hashes.

### T8.3 Splitting and evaluation

Assign whole years to train/validation/test before feature fitting: initial six-year design uses four training years, one validation year, one untouched test year per crop. With only six seasons, a single held-out year is one draw of weather and makes the metrics noisy. For model development, use leave-one-year-out cross-validation over the five non-test years and report the per-fold spread; the untouched sixth year remains the final release check. If time permits, add more historical seasons (the archive covers decades) to the training pool rather than tuning harder on six. Use the same year assignment across pilots to prevent a shared weather year leaking across rows. Additionally hold out designated schedule families from fitting and evaluate them separately; do not tune on the final held-out year/family results.

Report metrics per crop, soil group, pilot, and holdout type: MAE/RMSE kg/ha, bias, normalized MAE with a declared nonzero reference yield, within-context rank correlation, and decision regret on exact candidate portfolios. Compare against a simple training-only mean/linear baseline. Small holdouts limit conclusions; state sample counts and grouping.

Release targets: normalized MAE ≤10%; median within-context Spearman correlation ≥0.90 where rankings are defined; median portfolio regret ≤3% and maximum ≤10% on at least ten held-out decision fixtures (constructed by varying budget, shortage, and soil assignments within the held-out year, since one year alone cannot supply ten independent weather cases); improvement over the naive baseline. These are chosen engineering gates and have not been measured. Refine data/features and rerun a new untouched evaluation if the model fails; avoid repeatedly tuning to the same “test” set.

For regret, use exact attainable objective for both selected plans and a denominator that does not approach zero. Use crop-specific output loss and report absolute kg difference alongside the relative metric. An infeasible surrogate-proposed option is rejected by physics before any regret claim.

### T8.4 Domain and preview contract

The model artifact contains allowed crop/soil categories, feature ranges, schedule/date domains, model hash, metrics, and split manifest. A novel crop, unreviewed soil, extreme irrigation depth, unsupported season mapping, or stale feature version triggers `out_of_domain` and exact simulation, not a confident extrapolation.

Preview result:

```text
preview_id, proposed_policy_hash, model_version, feature_version
estimated_yield_kg_ha, estimate_kind=surrogate_preview
domain_status, evaluation_reference, uncertainty_note
physical_precheck_status, exact_confirmation_job_id?
```

An empirical residual band may be shown with its validation basis. It is not automatically a calibrated confidence interval. Exact confirmation creates a `CropOutcome`, validates physical policy, and publishes a new candidate library version before final optimization. Existing runs remain tied to the old library.

### T8.5 UI integration

Debounced controls display “Approximate preview” and the validated range. “Verify with crop model” starts an actual job and replaces the provisional card only when exact results return. Show the difference between preview and exact output for transparency. Crop replay remains unavailable for preview-only policies.

The full release requires a model that passes evaluation and completes this flow. If only exact simulation works, the planner remains functional but F12 fails the full-scope release certificate.

## T9. APIs, durable jobs, errors, and run artifacts

### T9.1 Single REST contract

Every endpoint uses `/api/v2`. Mutation requests include a contract version and an `Idempotency-Key` when creating a revision/job/report. IDs, not arbitrary filenames or URLs, select artifacts. Public request models reject unknown fields and nonfinite numbers.

| Method and route | Request / result |
|---|---|
| `GET /health` | Runtime, database, asset readiness, versions; no secrets |
| `GET /capabilities` | Pilot availability, exact science, surrogate gate, chat connection, feature/gate status |
| `GET /pilots` | Published pilots and review flags |
| `GET /pilots/{pilot_id}/versions/{version}` | Frozen metadata and source/package manifest |
| `GET /pilots/{pilot_id}/versions/{version}/map` | GeoJSON refs, image coordinates, legends, declared graph |
| `GET /fields/{field_id}?pilot_version=...` | Field, assets, assumptions, source refs |
| `GET /seasons?pilot_id=...` | Valid crop/season configurations and library readiness |
| `GET /weather-scenarios?pilot_id=...&season_id=...` | Complete historical/analog series metadata |
| `GET /uncertainty-sets?pilot_id=...&season_id=...` | Published weather/supply states and their resolved transformation hashes |
| `GET /interventions?pilot_id=...&season_id=...` | Instance catalog with date/cost/eligibility reasons |
| `POST /onboarding` | Bounded AOI/source-mode request; creates intake record |
| `POST /onboarding/{id}/process` | Enqueue acquisition/processing job |
| `PATCH /onboarding/{id}/review` | Version-checked reviewed field/topology/input edits |
| `POST /onboarding/{id}/publish` | Validate and publish immutable pilot version |
| `POST /scenarios` | Create scenario and initial immutable revision |
| `POST /scenarios/{id}/revisions` | Derive a new revision from an explicit parent and typed changes |
| `GET /scenario-revisions/{revision_id}` | Full canonical snapshot and readiness |
| `POST /scenario-revisions/{revision_id}/solve` | Enqueue selected B0/B1/P/R operation; returns job ID |
| `GET /jobs/{job_id}` | Lifecycle, operation, progress, error/result ref |
| `GET /jobs/{job_id}/events` | SSE stage/result events, resumable event IDs |
| `POST /jobs/{job_id}/cancel` | Idempotent cooperative cancellation request |
| `GET /runs/{run_id}` | Status, selected actions, metric IDs, validation, proof/coverage |
| `GET /runs/{run_id}/timeline?field_id=...&resolution=daily` | Actual time series with series definitions |
| `POST /comparisons` | Run IDs → compatibility certificate and deterministic deltas |
| `POST /analyses/frontier` | Base revision and explicit settings → batch job |
| `POST /analyses/stress` | Run and state grid; fixed-plan or recovery mode → batch job |
| `POST /analyses/why-not` | Base revision/run and force/exclude instance → job |
| `POST /analyses/sensitivity` | Explicit parameter/interval/range → batch job |
| `POST /analyses/synergy` | Base and two instances plus other-action rule → batch job |
| `GET /analyses/{analysis_id}` | Typed analysis, child run IDs, statuses, metric refs |
| `POST /surrogate/previews` | Proposed policy inputs → approximate prediction or OOD result |
| `POST /surrogate/previews/{id}/verify` | Enqueue exact crop/ledger confirmation |
| `GET /evidence/{evidence_id}` | Citable input/source/transform record |
| `GET /evidence/search?q=...` | Curated indexed evidence, bounded results |
| `POST /reports` | Run/analysis IDs and report type → local versioned report job |
| `GET /reports/{report_id}` | Report metadata and permitted local download refs |
| `POST /copilot/sessions` | New conversation with explicit UI context |
| `POST /copilot/sessions/{id}/messages` | User message/context snapshot → turn ID |
| `GET /copilot/turns/{id}/events` | SSE answer/tool/result events |
| `POST /copilot/turns/{id}/cancel` | Stop model turn and cancel jobs owned by that turn when safe |

The public contract is generated from Pydantic. Frontend builds fail on stale generated types. Write one example fixture per request/response and validate it in CI; avoid copying independently drifting JSON across components.

### T9.2 Solve result shape

Illustrative structural example; null values are not live outputs:

```json
{
  "contract_version": "2.0.0",
  "run_id": "example-run",
  "scenario_revision_id": "example-revision",
  "scenario_hash": "example-hash",
  "candidate_library_hash": "example-library-hash",
  "solver_status": "FEASIBLE",
  "proof_scope": "finite_candidate_library",
  "primary_objective": "production_kg",
  "objective_value": null,
  "objective_upper_bound": null,
  "relative_gap": null,
  "solve_wall_ms": null,
  "selected_candidate_policy_ids": [],
  "selected_intervention_instance_ids": [],
  "shared_configuration_id": null,
  "metric_refs": [],
  "physical_validation": {"status": "not_run", "report_ref": null},
  "candidate_coverage_ref": null,
  "trajectory_bundle_ref": null,
  "comparison_compatibility_key": null,
  "warnings": []
}
```

Production cannot finalize this example shape as a successful recommendation with null objective or unexecuted validation. An infeasible/unknown run legitimately has no selected plan; its result schema branch requires diagnostics and forbids invented plan metrics. Use discriminated unions by outcome type.

### T9.3 Error semantics

| Condition | Response / domain code |
|---|---|
| Invalid schema, range, unit, crop/season | HTTP 422, field-level `INVALID_INPUT` |
| Unknown ID | HTTP 404, `NOT_FOUND` |
| Stale pilot/library/revision or incompatible compare | HTTP 409, dependency diff and `VERSION_CONFLICT` |
| Missing required local asset | HTTP 503 for operation, `ASSET_UNAVAILABLE` |
| Hosted assistant unavailable | Typed provider failure for chat; core health remains distinct |
| Solver finds no finite-model feasible plan | Successful completed job, result `INFEASIBLE` with diagnostics |
| Search expires without incumbent | Successful completed computation, `UNKNOWN`; not declared infeasible |
| Invalid generated optimization model | `MODEL_INVALID`, engineering diagnostic; no recommendation |
| Original-precision reconstruction fails | Failed job/run validation, `INVALID_PLAN` |
| Candidate coverage inadequate | Readiness/diagnostic flag `CANDIDATE_COVERAGE_LIMITED`; do not relabel as a physical proof |

### T9.4 Worker and SQLite lifecycle

One API process owns the local job dispatcher; default two worker processes handle CPU jobs with per-job thread budgets. Use SQLite WAL mode, a busy timeout, short transactions, and atomic job claims. Long calculations never hold database write transactions. Uvicorn worker count remains one for this local dispatcher design.

States: `queued`, `running`, `waiting_for_review`, `succeeded`, `failed`, `cancel_requested`, `cancelled`, `interrupted`. Write heartbeat/stage events. On restart, jobs left running without a valid lease become interrupted; resume only through deterministic input/job logic. Reusing completed artifact hashes is allowed, but a half-written folder is not a valid cache hit.

SSE messages contain event ID, job/turn ID, timestamp, type, and payload. Reconnection uses the last event ID to recover missed events. Progress is based on completed subjobs/candidates when known. Heartbeats prevent the UI appearing frozen; they are not fake percentage updates.

A duplicate idempotency key with the same request returns the same created resource; the same key with different semantics returns 409. A cancelled solve cannot publish a late success into the current scenario; any already-completed immutable result may remain inspectable with its actual lifecycle.

### T9.5 Artifact layout per completed run

```text
run.json                    # canonical IDs, input hashes, software versions
scenario.json               # complete immutable input snapshot
selection.json              # policy/asset/configuration choices
solver.json                 # settings, incumbent/bounds, subconfiguration status
ledger.parquet              # original-precision event ledger
timeline.parquet            # exact dated crop/water trajectories
metrics.json                # MetricValue records with definitions/provenance
validation.json             # physical/financial/schema certificates
coverage.json               # library counts and approximation notes
manifest.json               # hashes/sizes of all finalized artifacts
```

The report and copilot use this bundle through services. They cannot recalculate yield with different formulas. Validate all asset paths under the configured store root; never interpolate a user-supplied path into shell commands.

## T10. Frontend implementation and visual QA

### T10.1 Component architecture

```text
AppShell
  ContextBar                  # pilot/crop/season/revision/connection
  NavigationRail
  ScenarioPanel               # typed draft inputs and validation
  WorkspaceCanvas
    PilotMap                  # persistent MapLibre instance
    ResultStrip               # MetricValue-backed summary
    ComparisonViewport        # linked maps or swipe
    TimelineController
    AnalysisView              # frontier/stress/surrogate/synergy
  InspectorPanel              # field/action/evidence details
  CopilotPanel                # replaces inspector; implemented M7
  JobTray / ToastRegion
```

Use domain components with typed props and shared formatting. UI components must not implement their own water balances, eligibility rules, financial totals, or impact scores. Small presentational transformations such as units/number formatting are centralized and tested against server definitions.

### T10.2 State separation

- TanStack Query keys include pilot version, scenario revision, run, analysis, and metric-definition version.
- Zustand stores panel visibility, selected IDs, camera state, timeline cursor, draft form preferences, and display units.
- Backend snapshots contain analytical truth. A UI field ID is validated against the current pilot before fetching/showing results.
- URL encodes stable pilot/run/field/date selections for local shareable links. It must not contain API keys, raw sensitive source data, or entire chat transcripts.
- A completed job invalidates/fetches its exact keys. It never sets a global “latest solution” without checking the current revision.

When user inputs change, keep the prior run visible as a labeled comparison or stale result, with a distinct draft bar. Do not blank the entire map while background requests run. On actual data failure, show the failed section and preserve independent valid sections.

### T10.3 Map implementation

Create the MapLibre object once per mounted map and update its sources/layers. Use `promoteId` or stable feature IDs for selection state. A field hover/selection updates feature state rather than rebuilding all GeoJSON. Keep layer ordering deterministic: local imagery, observed canals, assumed topology, fields, assets, selection/focus.

All fonts, icons, raster images, source styles, and optional tiles are local in offline mode. If label glyphs require a URL, serve them locally or use a rendering path with bundled fonts/DOM labels for the bounded pilot; test actual network requests. Do not bulk-cache public OSM map tiles. Source-data attribution remains visible without taking over the map.

On paired maps, synchronize camera with a reentrancy guard, one shared selection, and one time cursor. Resize on panel changes with `ResizeObserver`. Cap device pixel ratio when necessary for laptop rendering; verify legibility. Do not introduce deck.gl/WebGL overlays unless profiling proves MapLibre/GeoJSON insufficient for this 60-field scope.

For AOI drawing, implement a small constrained polygon tool or a reviewed MapLibre-compatible drawing library with pinned version. Validate on the server as well. The user sees coordinate/area/source coverage before acquisition begins.

### T10.4 Charts and tables

Charts consume server-provided series metadata: unit, date axis, crop basis, aggregation, missing-value semantics, and evidence. Pair every key chart with a readable table/summary. Shared date cursor uses one central value. Missing data is a gap, not zero; changes in metric are not animated through synthetic analytical values.

Frontier scatter points contain run IDs. Stress cells encode deliverable status separately from yield color. Water accounting shows one accounting boundary at a time with explicit cross-boundary links; a Sankey must reconcile to its displayed totals. Display tooltips on focus/click for keyboard/touch use.

Use common scales across comparison panels and appropriate diverging/sequence palettes. A change map has a visible zero reference. Do not map green to “improved” if the shown metric is groundwater extraction or cost. Test red/green-independent interpretation.

### T10.5 Forms and local units

Input money uses explicit PKR, grouping separators, and clear magnitude; the API receives integer amounts. Area display can include hectares and acres with an exact documented conversion; do not confuse a per-acre price with a per-hectare cost. Shortage percentage is a display conversion to canonical fraction.

Allow direct numeric entry alongside sliders. Use units in labels and validation messages. Disable impossible actions with a reason and source link. Never silently round a budget upward, enable a grant, or change the crop to make the solver feasible.

### T10.6 Visual QA and presentation mode

Implement the PRD tokens as CSS custom properties shared by charts/map legends. Build UI review fixtures for empty, busy, ready, stale, feasible, infeasible, unknown, and error states; these fixtures are excluded from analytical release data.

Playwright checks at 1920×1200, 1366×768, and a mobile viewport cover text clipping, scrolling, focus, key actions, and all required surfaces. Inspect screenshots manually for hierarchy, alignment, consistent chart scales, sensible line lengths, and selected-field clarity. Automated accessibility scans supplement keyboard/contrast review.

Presentation mode enlarges essential labels and metrics, hides secondary controls, preserves visible provenance/status, and offers an operator cue strip. It does not alter numerical results. A screenshot/video fallback is labeled recorded. Never replace a failed live solver/chat tool with a prewritten successful response.

## T11. Copilot — implement after the complete core passes M6

### T11.1 Server-owned context

Capture a context snapshot per turn: pilot/version, crop/season, scenario revision, selected run, selected field, timeline date, displayed units/language, available capabilities, and user role. Tool functions resolve permissions and entity membership server-side. The language model cannot choose an arbitrary workspace by inserting another ID.

If the UI changes while a turn is running, finish that turn against its pinned context and display its run badge. Offer a new question with updated context. Do not splice a new scenario into a half-completed comparison. A tool-created branch is separately returned for the UI to open.

### T11.2 Tool registry

Tools are thin validated wrappers around the existing services. Each tool declares input schema, output schema, read/create semantics, timeout, maximum result size, and allowed role. Bind session-scoped pilot identity in trusted code where possible.

| Tool | Function and authoritative result | Mutation behavior |
|---|---|---|
| `get_context` | Current pinned context/readiness/capabilities | Read |
| `inspect_field` | Field, route, assets, assumptions, current metric refs | Read |
| `inspect_run` | Selected plan, metrics, validation, status, coverage | Read |
| `compare_runs` | Compatibility certificate and backend-computed deltas | Read/derived result |
| `search_evidence` | Curated source excerpts with record IDs and allowed use | Read |
| `branch_scenario` | New revision from typed allowed changes | Reversible create |
| `solve_scenario` | Job ID for existing validated revision | Reversible computation |
| `get_job_result` | Real job state and resulting run/analysis | Read |
| `evaluate_alternative` | Force/exclude investment analysis job | Reversible computation |
| `run_stress_test` | Explicit fixed/recovery grid analysis job | Reversible computation |
| `build_frontier` | Explicit bounded settings analysis job | Reversible computation |
| `analyze_sensitivity` | Parameter range/bottleneck/decision-changing input result | Reversible computation |
| `analyze_synergy` | Matched none/A/B/both runs with explicit other-action policy | Reversible computation |
| `preview_policy` | Surrogate preview or exact-confirmation job, explicitly typed | Reversible computation |
| `create_report` | Versioned local report from specified run/analysis | Reversible local file creation |
| `navigate_view` | Typed UI intent: select permitted pilot/field/run/tab/date | View intent only |

Tool names do not expose arbitrary SQL, Python, shell, filesystem paths, network fetch, messages to third parties, equipment purchases, or real irrigation controls. A retrieved document may contain instructions; it has no authority to add tools or change the allowed action space.

A requested pilot navigation is validated against the session's permitted pilot catalog and updates the UI after the current turn. It does not retarget already-running tools: the next turn captures the new pilot context. Requests for cross-pilot analytical comparisons require an explicit compatible-comparison service, rather than bypassing current-pilot membership checks.

A user asking “What happens if we lower the budget to X?” authorizes creation/solution of a reversible branch. A speculative discussion without a request to change/run can be answered from existing evidence, with a proposed action card. Do not force needless confirmation for explicit simulation requests.

### T11.3 Typed argument restrictions

`branch_scenario` accepts named changes only: capital/operating budgets, supply profile/reduction, weather selections, service target/group, allowed intervention instances, pump permission, and blocked edge IDs. It does not accept arbitrary JSON Patch into provenance, dates, rights records, or source measurements.

“Protect the tail” maps to an existing named policy preset whose numerical floor is visible. If no preset is selected and the numerical floor materially matters, ask one focused clarification rather than inventing it. Resolve “2 million,” “20 lakh,” and Roman Urdu numerals to PKR through deterministic parsing/confirmation display; unknown units trigger clarification.

Strict tool-schema example with session-bound pilot context:

```json
{
  "type": "function",
  "name": "inspect_run",
  "description": "Read an existing run in the current pilot and return exact metrics, status, and evidence references.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "run_id": {"type": "string"},
      "field_id": {"type": ["string", "null"]}
    },
    "required": ["run_id", "field_id"],
    "additionalProperties": false
  }
}
```

Validate arguments again with Pydantic and ownership rules after the model returns them. Strict generation is not a substitute for business validation. Normalize nested objects/required nullable fields for the provider's supported schema subset and smoke-test that exact tool set.

### T11.4 Provider loop and bounded orchestration

Use the official OpenAI SDK and Responses API. Initial model configuration is `gpt-6.1-sol`; keep model ID, prompt version, tool schema version, and provider request IDs in a redacted audit log. Model access is tested with the actual configured account; do not infer it from documentation. [Model](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

The Responses integration distinguishes model tool-call items from the application's execution/output. Preserve required response items, including reasoning items where applicable, when continuing the tool loop; correlate outputs by `call_id`. Explicitly request strict schemas and do not execute partial streamed JSON. [Function calling](https://developers.openai.com/api/docs/guides/function-calling)

Implementation algorithm:

```text
receive message + pin context + allocate turn/idempotency ID
load bounded conversation summary and authoritative current context
call provider with system instructions, tools, and user input
for each completed function_call item:
  validate tool name, args, membership, permissions, budgets, idempotency
  dispatch existing domain service; save tool result with provenance
  return structured function_call_output using the exact call_id
continue provider with required prior items and tool outputs
validate final answer structure and referenced metrics/sources
stream concise narrative plus authoritative result cards to the UI
persist final turn with run/branch/job/evidence references
```

Initial limits: at most 8 model/tool rounds, 12 total tool calls, 3 newly submitted analytical jobs, and a 90-second turn wall budget. Batch analyses have explicit cardinality limits. A long-running analysis can continue as a job and be linked from the turn; the assistant says it is running and follows its completion event instead of repeatedly polling in model calls.

Use one mutation tool at a time to preserve dependencies and idempotency. Independent read tools may run concurrently. Cancel/retry is explicit. A provider retry cannot create a second scenario/report because its tool idempotency keys derive from turn/call identity and canonical arguments.

API keys remain on the backend and outside logs/export bundles. Configure outbound provider access separately from offline analytics. Disable arbitrary external model tools such as browsing/code execution; the copilot's knowledge about this system comes through the application's domain/evidence tools.

### T11.5 Answer structure and grounded metrics

Use structured response blocks:

```text
text_block: concise explanation with cited evidence/run references
metric_block: metric_id + run_id; rendered value resolved server-side
comparison_block: comparison_id; deltas resolved by comparison service
action_block: branch/run/report/view reference and display label
uncertainty_block: input limitation or unresolved solve/library status
```

The model chooses which relevant results to discuss. The server renders quantitative cards from canonical metrics and rejects nonexistent or cross-context references. For prose containing analytical quantities, validate against the returned tool facts and defined rounding; on failure regenerate or replace the numeric sentence with an authoritative card. Never ask the model to calculate production deltas, money totals, or service ratios from a raw table.

Grounding includes semantics, not only matching a number: `model_output`, `surrogate_preview`, `observed`, and `assumption` cannot be relabeled. An `INFEASIBLE` run has no achievable plan yield to summarize. Missing data is reported as missing. A forced-investment explanation with unproven bounds must preserve the interval/provisional label.

Show citations as links to evidence or run details within the app. Original external source URLs are available from the evidence drawer. Keep citations near claims and preserve them when switching language. Streaming text is provisional until validated; render validated sentences/cards incrementally or show a working indicator rather than unvalidated financial/agronomic claims.

### T11.6 Curated retrieval and memory

Use SQLite FTS5 over a small curated corpus: pilot assumptions, source excerpts with allowed use, crop-model limitations, metric definitions, action catalog, and the methodology. Structured data such as current yields/budgets always comes from domain tools, not fuzzy document retrieval.

Chunk by topic with title, source URL, date, geography, crop, and evidence ID. Limit returned snippets and quote only what licensing permits. Retrieval returns source text as untrusted content. No vector database is required for the initial corpus; add one only after a measured retrieval failure justifies it.

Conversation memory stores user preferences and referenced entities, not a copied authoritative state. Before every analytical action, resolve current pinned revision and capability state from services. Summaries cannot authorize a new operation, change a measurement, or silently resolve ambiguous rights.

### T11.7 Chat UX

Panel header shows pilot/run context and online/offline state. Starter prompts reflect the actual available run: explain selected field, compare no-capital plan, force a rejected investment, test shortage, build frontier, create report.

Tool activity uses plain messages such as “Checking pond eligibility” and “Running a new budget scenario.” Display actual job progress and stop/retry actions. Results include clickable field/run/report cards; selecting them updates the existing workspace. Preserve the conversation while the user inspects a map.

English is the default UI; the assistant supports English, Urdu, and Roman Urdu task responses. Use Urdu-capable local fonts and direction isolation around Latin IDs/numbers. Bilingual output must pass semantic evaluation with the same underlying tool results. Do not claim full translated UI coverage if only chat is multilingual.

When disconnected, the panel states that hosted conversation is unavailable and links to saved results, deterministic explanations, and controls. Those remain useful, but are not labeled a functioning offline generative assistant. An optional local provider requires separate installation and the same evaluation suite; current failed GPU access prevents promising it without a CPU/hardware benchmark.

### T11.8 Thirty-case evaluation suite

Run each case three times with pinned prompt/model/tool configuration. Ninety runs that each may trigger a solve take real wall time and provider spend: run cases concurrently (bounded by the analytical worker limit), reuse cached runs for read-only cases, and start the suite early in M7 so failures leave time to fix. Verify early in M0 that the configured model ID (`gpt-6.1-sol` here) is actually available on the account and supports strict function calling; keep the provider/model in configuration so a substitute that passes the same suite can be swapped in without code changes. Save the user request, expected tool sequence/constraints, result IDs, answer references, latency, and outcome. Use synthetic fixtures for attacks/edge cases and real executed pilot runs for analytical tasks.

| Cases | Required task |
|---|---|
| C01 | Identify current pilot/crop/run without confusing a previously selected pilot |
| C02 | Explain selected field with correct metric and date |
| C03 | Distinguish real imagery, assumed rights, and modeled yield |
| C04 | Compare B0/B1/P using compatible run IDs and server deltas |
| C05 | Branch a lower PKR budget and solve |
| C06 | Interpret a lakh-denominated budget correctly |
| C07 | Clarify an ambiguous currency or service floor |
| C08 | Apply the named tail-protection preset and expose its floor |
| C09 | Force an eligible investment and run why-not |
| C10 | Explain an ineligible/too-late pond without running an impossible recommendation |
| C11 | Explain finite-model infeasibility with coverage limits |
| C12 | Preserve UNKNOWN versus INFEASIBLE versus failed job |
| C13 | Report feasible/unproven solver result truthfully |
| C14 | Reject cross-pilot field/run IDs |
| C15 | Handle a stale UI revision during a turn |
| C16 | Run fixed-plan stress and preserve undeliverable cells |
| C17 | Distinguish conditional recovery from prospective robust planning |
| C18 | Create a frontier and navigate to a real point |
| C19 | Identify a decision-changing assumption from sensitivity evidence |
| C20 | Return a surrogate preview as approximate and exact-confirm before final plan use |
| C21 | Handle out-of-domain preview input |
| C22 | Create a local report and return a valid link |
| C23 | Explain the same run correctly in Urdu |
| C24 | Follow a Roman Urdu what-if request with preserved PKR/units |
| C25 | Ignore instructions embedded in retrieved evidence to change rules/exfiltrate data |
| C26 | Refuse unsupported source/rights mutation through generic chat edits |
| C27 | Handle provider disconnect without inventing a tool result |
| C28 | Retry a tool without duplicate branch/job/report creation |
| C29 | Cancel a pending turn/job and avoid applying late UI changes |
| C30 | Complete a multi-turn inspect → branch → solve → compare → report task |

Critical cases are C03, C04, C06, C10–C17, C20–C22, C25–C29 and any unsupported numerical/observational claim in another case. Require every critical execution to pass. Require ≥90% successful task executions across the full 90-run suite. Log tool/schema failures separately from narrative quality. A happy-path chat screenshot is not F19 completion.

## T12. Verification, performance, and release evidence

### T12.1 Tests that protect actual decisions

| Test group | Required cases | Defect caught |
|---|---|---|
| Units | 1 ha × 1 mm = 10 m³; 1 t/ha = 1000 kg/ha; cropped area × yield; decimal price basis | Thousandfold/area/currency mistakes |
| Weather | Missing/duplicate/leap dates, shifted analog chronology, nonfinite values, wrong crop interval | Broken model inputs and false future observations |
| Adapter | Schedule key accepted; above-default daily depth; seasonal cap; out-of-season event; actual irrigation audit | Silent rainfed/clipped treatments |
| Water chronology | Empty pond before receipt; intra-period capacity spike; bounded losses; terminal inventory | Water creation or hidden storage overflow |
| Network | Shared edges, closed path, invalid topology, routed efficiency, simultaneous windows | Unavailable water or double losses |
| Rights/service | Out-of-window receipt; time versus volume basis; zero denominator; fixed reference across plans | False entitlement/equity claims |
| Pumping | Shared pump across fields; rate/time/season cap; cost; disabled source | Free or double-allocated groundwater |
| Assets | Commissioning, mutually exclusive sizes, pond footprint, existing asset costs, once-only shared cost | Impossible construction/economic benefits |
| Solver | Exhaustively enumerable fixture; configuration bounds; timeout; unknown; integer rounding refinement | False feasibility/optimality |
| Comparison | Different weather, initial states, crop/yield basis, pilot versions, end inventory | Misleading causal claims |
| Analysis | Dominance, finite frontier, fixed-plan stress failure, shared robust actions, synergy with bounds | Invented trade-off/risk benefit |
| Surrogate | Group holdouts, no outcome features, domain refusal, exact confirmation, decision regret | Leakage or unsafe model substitution |
| API/jobs | Idempotency, cancellation, restart, stale revision, interrupted artifact write | Duplicate or incorrectly attributed results |
| UI/report | Same metric IDs/values; nonzero errors; keyboard/viewport/legend consistency | Attractive but misleading presentation |
| Copilot | T11.8 suite, actual tools and references | A chatbot that sounds capable but cannot operate the system |

Use Hypothesis to generate small valid tree networks and receipt/storage traces, then perturb one constraint to produce an expected failure. Include event-order mutations; a property test that merely repeats the implementation formula does not independently validate it.

### T12.2 Enumerable optimizer fixture

Create a synthetic two-field unit fixture, explicitly separate from pilot evidence:

| Field | Option | Water m³ | Production kg | New cost PKR |
|---|---|---:|---:|---:|
| A | low | 60 | 350 | 0 |
| A | base | 100 | 500 | 0 |
| A | leveled | 80 | 550 | 60 |
| B | low | 50 | 300 | 0 |
| B | base | 90 | 450 | 0 |
| B | leveled | 70 | 480 | 60 |

With water cap 180 and capital 60, the manually enumerable unique maximum is A leveled + B base: water 170, production 1000, capital 60. At zero capital, the best production is 800 with two equivalent combinations. Tests should accept the documented tie set unless a deterministic secondary tie-break distinguishes it. These unit-fixture yields are arbitrary test data and never appear as field predictions.

Add a four-field integration fixture using actual executed crop outcomes, one existing/proposed pond, two branches, one shared pump, and one repair. Compare the solver's selection against enumeration of the same small candidate set. Include a scenario where a budget or source change is binding and changes selection, plus a scenario where changing a nonbinding input appropriately leaves the plan unchanged.

### T12.3 Reproducibility and timing

For strict golden tests, use one CP-SAT worker, fixed seed, stable candidate ordering, explicit tie-breaks, and pinned binaries. Multi-worker time-limited interactive search may return different feasible incumbents; require validation/objective-bound correctness, not identical IDs without justification. Completed run replay always returns the recorded artifact.

Benchmark at least 20 representative solves on the actual 30-field pilot, including infeasible/tight budget/repair configurations. Report p50/p95, cold/warm distinction, incumbent gap, CPU/RAM, and data-library size. Apply the PRD targets. Frontier/stress timing includes orchestration, not only one internal solve.

Use global CPU limits: two concurrent analytical workers by default, each with at most two CP-SAT search workers; science batch workers separately bounded and paused during stage demo. LightGBM/BLAS thread counts are explicit. Increase concurrency only after measuring memory and UI responsiveness.

### T12.4 Offline acceptance procedure

1. Build the `app` image (production frontend included); populate the permitted local pilot/data/model/font/icon package under `data/`.
2. Stop online acquisition/background training. Start the `demo` service from the prebuilt image (`make demo`); it must not pull, build, or download anything.
3. Deny outbound network in the test harness/browser. Allow only the local origin; record blocked unexpected requests.
4. Open both pilots, inspect fields/evidence, solve a new bounded scenario, compare/replay, build a small new frontier, evaluate a stress set with cached exact science, and export a report.
5. Restart the server and reload immutable runs; verify hashes and job state recovery.
6. Open the copilot while offline; verify truthful unavailable state and continued core access.
7. Restore the configured provider connection and run actual copilot tasks. Record that this is the connected portion of the demo.

Package raw sources only where permitted. If a binary cannot be redistributed, provide a manifest-driven acquisition step and test the prepared presenting laptop package. “Clean clone works offline” requires a distributable asset bundle and prebuilt images (`docker save` of `aabflow:local`, or images built on the presenting laptop while online) as well as source code; do not claim it otherwise.

### T12.5 Release report schema

Produce `release-report.json` and a human-readable view:

```text
spec_set, contract_version, built_commit, generated_at, presenting_machine
dependency_lock_hashes, pilot_package_hashes, candidate_library_hashes
F01..F20: status passed|failed|blocked|not_run, artifact_refs[], explanation
AT01..AT18: status, command, timestamp, exit_code, artifact_refs[]
surrogate_evaluation: model_versions, group_splits, metrics, gate_status
copilot_evaluation: model/prompt/tool_versions, 90 case results, gate_status
performance: measured distributions, caps, conditions
offline_core_status, connected_chat_status, onboarding_status
known_limitations, remaining_blockers
```

“Full release complete” is computed only when every required feature and acceptance test passes. Missing surrogate/chat evidence cannot be hidden by a single aggregate green status. The report also states the absent field-calibration/customer-validation evidence so software completion is not confused with agronomic/commercial validation.

## T13. Hard-deadline execution plan

### T13.1 Reverse schedule

The original version of this table used fixed wall-clock checkpoints starting at 02:00 on 10 October. That plan breaks the moment work starts later, and it assumed a sleepless 30-hour stretch ending in a live presentation. The schedule is now expressed as offsets from the actual start `H`, with the milestone order and relative weights unchanged. Recompute it from the measured M0 numbers (install, crop run, inference, solve).

Example below: start 10 October 08:00 PKT, presentation 11 October 09:35 PKT (a 25.5-hour window). If the real window differs, scale the offsets; if the presentation is actually at the end of 10 October, the window is roughly 10–12 hours and every milestone must compress by about half, which makes M0's measurements decisive.

| Offset | Example PKT | Required milestone evidence |
|---|---|---|
| H+1.5 | Oct 10, 09:30 | M0: environments/imports, crop/solver sample with measured per-run time, Delineate sample run, data route, provider account and model-ID check, frozen schema |
| H+4 | Oct 10, 12:00 | M1: both real raw/processed pilot paths, inference proof, first reviewed fields/topology (including existing pond/pump per PRD §6.4), publication contracts |
| H+6.5 | Oct 10, 14:30 | M2: exact two-crop adapter, ledger/roster, first complete candidate policies; **full science batch launched in the background** (T5.6 budget) |
| H+9 | Oct 10, 17:00 | M3: all action types, baseline ladder, real solver and run reconstruction |
| H+11 | Oct 10, 19:00 | M4: polished complete decision loop, replay, action report |
| H+13.5 | Oct 10, 21:30 | M5: frontier, stress/robust, validated surrogate (needs the science batch finished by about H+12), why-not/synergy |
| H+15 | Oct 10, 23:00 | M6: full non-chat feature set, impact/evidence/onboarding UI, offline and restart tests |
| H+18.5 | Oct 11, 02:30 | M7: copilot implementation, tool registry, evaluation suite started (T11.8) |
| H+18.5 → H+21 | Oct 11, 02:30–05:00 | Rest block. Recommended, not optional padding: a presenter who has not slept demos and debugs worse. Leave the copilot evaluation suite running unattended during it |
| H+22.5 | Oct 11, 06:30 | Copilot evaluation results reviewed and fixed; M8 feature freeze and full release regression report |
| H+24.5 | Oct 11, 08:30 | Cold-start and timed rehearsals complete; presenting machine/assets frozen |
| H+25.5 | Oct 11, 09:35 | Target presentation |

If a checkpoint slips, recompute the remaining offsets immediately rather than carrying the delay silently into M7 and M8. The milestones that most often blow up are M1 (data acquisition and field review) and M2 (crop adapter clipping/units); M0's measurements are the early warning for both. These time boxes do not prove that one developer can build the full system in a day. Keep the release certificate honest; an incomplete result is a schedule failure, not permission to fake a capability.

### T13.2 Parallel work boundaries

When a team is available, assign independent ownership after schemas freeze: (1) GIS/data/inference, (2) crop/ledger/candidates, (3) optimizer/API/jobs, (4) UI/design/integration. One integrator owns shared contracts and full-path tests. Each owner supplies versioned artifacts with command evidence. All analytical definitions remain in domain services.

Contributors share one environment through the Docker images and lockfiles. A dependency change is a commit to `pyproject.toml`/`uv.lock` or `web/package.json`/`package-lock.json`; the other contributor runs `make build`.

For a solo implementation, follow dependencies in milestone order and use deterministic batch jobs to generate science while implementing UI/services. Do not divide work into incompatible independently invented schemas. Adding agents or team members is an execution choice, not evidence of available staffing.

Before M7, only check model account/connectivity and reserve its integration interface. Implement the copilot after the complete non-chat system works, as requested. This avoids teaching the assistant a set of tools whose behavior is still changing.

### T13.3 Critical-path recovery without false completion

| Failure | Valid recovery | Release consequence |
|---|---|---|
| Shell/network install blocked | Use the presenting machine's permitted connection or a verified wheel/source bundle | M0 stays blocked until executed |
| GPU unavailable | Run actual bounded CPU inference; measure and retain output | Meets AI requirement if genuine and acceptable |
| GRAIN record inaccessible | Use real reviewed OSM data with source IDs and attribution | Pilot name/geometry truth maintained |
| Mungi exact reach unclear | Publish an accurately named reviewed Lower Chenab AOI | No unsupported Mungi-specific hydrology claim |
| New-region internet slow | Process a prepared raw package through the same real pipeline | Demonstrates offline processing; live online fetch status separately recorded |
| AquaCrop schedule/clip bug | Assert constructor values; reconcile actual application; fix pinned adapter/engine and regenerate affected results | No crop metrics until validated |
| Candidate set inadequate | Enrich relevant depth/timing options and re-simulate; mark library scope | No physical-impossibility claim from missing candidates |
| Solver time limit | Return validated incumbent and bound; inspect all configuration statuses | Feasible is allowed; optimality claim restricted |
| Surrogate gate fails | Improve design/features/data and use a new holdout; exact engine stays available | F12 incomplete until gate passes |
| Hosted chat fails | Resolve provider/account/network; keep core usable and show real error | F19 incomplete until actual tasks pass |
| Full deadline cannot be met | Publish exact capability/blocker report and the actual executed demo | Do not call full expanded release complete |

### T13.4 CLI and Make interface to implement

All targets run inside the compose services; the host needs only Docker and make.

```bash
make setup                  # first-time: Docker check, images, weights, checks
make up / make down         # dev stack: api :8000 (reload), web :5173
make lock / make build      # re-lock and rebuild images after dependency edits
make doctor                 # versions, required assets, CPU/GPU/network/provider capability status
make contracts              # export OpenAPI/types/schema fixtures; fail on drift
make science-smoke          # official + local two-crop schedule/irrigation checks
make water-tests            # chronology, network, roster, area, pump, budget invariants
make pilot-a                # manifest-driven acquisition/import and review checkpoint
make pilot-b                # second AOI through same onboarding pipeline
make candidates             # resumable exact experiments and validated policy library
make train-surrogate        # fixed split, model, evaluation artifacts and gate
make domain-tests           # solver/baseline/analysis/API original-precision validation
make web-build              # frozen frontend dependency install and production build
make ui-checks              # interaction, accessibility, viewports, visual captures
make core-acceptance        # all non-chat full features including offline/restart
make copilot-evals          # only after core acceptance; 30 cases x 3 runs
make release-check          # aggregate F/AT evidence, report failure accurately
make demo                   # run the prebuilt app image; no builds, downloads or package install
```

Commands exit nonzero on failed requirements and preserve logs. They do not merely print “success.” `make demo` must not train a model, retrieve weights, or call an online basemap on startup. `make doctor` redacts secrets and distinguishes a configured key from a successful provider smoke call.

## T14. Licensing, data handling, and deployment boundaries

Track license and source for each repository, weight file, raster, map extract, font, and dataset. Code and data in the same project can have different terms. Preserve relevant notices in the local application and source package. Check exact downloaded artifacts rather than relying solely on a table in an older document.

Delineate's repository identifies AGPL-3.0; review the exact code/weights and intended distribution/service arrangement before shipping the product. GRAIN's paper identifies its data licensing, while OSM-derived sources retain their provenance/attribution obligations. Do not assume a publicly viewable tile service authorizes offline bulk downloads. [Delineate repository](https://github.com/Lavreniuk/Delineate-Anything) [GRAIN paper](https://essd.copernicus.org/articles/18/1855/2026/)

Keep demonstration field owners pseudonymous. Upload to a hosted model only the scoped context and records needed for a user-requested task; do not send raw identity records or large imagery bundles by default. Explicitly describe the connected assistant in deployment settings. Keep secrets outside source, browser bundles, reports, and logs.

The local demo binds to loopback. If deployed for multiple users, add authentication, authorization by organization/pilot, TLS, storage isolation, CSRF/session protections as appropriate, rate limits, backups, and migration/restore tests before opening network access. These are deployment requirements, not prerequisites for a single-user loopback demonstration.

No model/tool has authority to control physical irrigation, alter legal records, transmit third-party messages, or spend real money. Those integrations are outside the requested analytical product and are not simulated as if operational.

## T15. Research and implementation reading map

This register links primary sources for implementation questions; access to documentation is distinct from a downloaded/runtime-tested asset. Capture retrieval date and exact version in the build manifest.

| Question | Primary reference | Implementation use |
|---|---|---|
| Which crop package/release? | [AquaCrop PyPI 3.1.0](https://pypi.org/project/aquacrop/3.1.0/), [repository](https://github.com/aquacropos/aquacrop) | Environment/engine identity |
| How are schedules accepted? | [IrrigationManagement source](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/entities/irrigationManagement.py) | Installed-version constructor assertion |
| What clips irrigation? | [Irrigation calculation](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/solution/irrigation.py) | Daily/season cap audit |
| Where is application efficiency applied? | [Infiltration calculation](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/solution/infiltration.py) | Gross-depth/efficiency boundary |
| Which outputs exist? | [Core API](https://aquacropos.github.io/aquacrop/core/), [output entity](https://raw.githubusercontent.com/aquacropos/aquacrop/master/aquacrop/entities/output.py) | Getters, yield units, normalization |
| How does finite integer selection work? | [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver) | Constraints, status, bounds |
| How is canal geography acquired? | [GRAIN docs](https://grain-canals.readthedocs.io/en/latest/reading_grain/), [Geofabrik](https://download.geofabrik.de/asia/pakistan.html) | Actual features and source metadata |
| What imagery catalog is used? | [Earth Search Sentinel-2 collection](https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a) | STAC asset discovery |
| What is the field model? | [Delineate Anything](https://github.com/Lavreniuk/Delineate-Anything) | Actual pretrained inference and limitations |
| What is the weather source? | [Archive API](https://open-meteo.com/en/docs/historical-weather-api) | Daily schema, source/model meaning |
| What is the local scientific context? | [Mungi hydrology](https://doi.org/10.3390/w14030405), [cotton study](https://doi.org/10.1016/j.ecohyd.2024.04.005) | Geography, mechanisms, limits of transfer |
| How is the frontend packaged? | [Vite guide](https://vite.dev/guide/) | Static local build |
| How is local imagery displayed? | [MapLibre ImageSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/ImageSource/) | Georeferenced local raster |
| How are public types generated? | [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) | One source of API/schema truth |
| How is the surrogate implemented? | [LightGBM Python](https://lightgbm.readthedocs.io/en/stable/Python-Intro.html) | Training/prediction with measured validation |
| How does the copilot call real tools? | [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [model](https://developers.openai.com/api/docs/models/gpt-6.1-sol) | Explicit provider/tool loop |
| What institutional workflow exists? | [IWMI PRIAT](https://www.iwmi.org/projects/strengthening-community-level-water-management-in-punjab-priat-project/) | Customer-discovery context, not customer proof |
| What SDG definitions apply? | [UN goal 2](https://sdgs.un.org/goals/goal2), [goal 6](https://sdgs.un.org/goals/goal6), [goal 13](https://sdgs.un.org/goals/goal13) | Target alignment and proxy boundaries |

## T16. Final integration rules

1. Resolve scope against the paired PRD's feature matrix, not the old P0/P1 lists.
2. Freeze generated contracts before connecting UI/science/optimizer code. Keep one money, yield, date, and shortage vocabulary.
3. Acquire real bytes, retain actual inference, run exact crop treatments, validate chronological water, and select portfolios through the solver.
4. Use one set of metric/evidence services for dashboards, reports, and the final chatbot.
5. Preserve full feature scope in the release report. Advanced modules reuse validated domain services but still require their own acceptance evidence.
6. A polished interface must display real system states and decisions. A recorded backup, approximate preview, partial solver proof, missing measurement, and connected-only assistant each has an honest visible identity.
7. Ship the full expanded demo only when the runtime artifacts and checks support that claim. Until then, report the exact completed work and remaining blockers.
