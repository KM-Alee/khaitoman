# AabFlow v2 — Product, Experience, Scientific Acceptance, and Demo Specification

**Specification set:** `aabflow-v2`, contract `2.0.0`  
**Prepared:** 10 October 2026, Asia/Karachi  
**Companion:** [Technical implementation handbook](aab-flow-tech-doc-v2.md)  
**Release target:** the entire expanded demonstration by **11 October 2026, 09:35 PKT**, using the presentation time in the original brief.  
**Current implementation status:** specifications only. This document does not certify a built application, downloaded pilot dataset, trained model, calibrated crop model, or successful API integration.

> **AabFlow helps watercourse planners test irrigation investments before committing scarce money—showing modeled production, cost, water use, and consequences for downstream fields.**

> **Test the season before you spend.**

This paired rewrite supersedes the implementation decisions in `prd-flow.md` and `aab-flow-tech-doc.md`. The earlier PRD already used an internal “2.0” label; the filenames above identify this expanded, reconciled specification set unambiguously. The earlier documents remain historical reference material.

## 0. Authority, full scope, and release truth

### 0.1 One contract across both documents

This document owns product behavior, user experience, scope, and release acceptance. The companion owns algorithms, schemas, APIs, file formats, tooling, and execution procedures. Both use the same feature IDs, units, scenario modes, milestones, and release targets. Once implemented, Pydantic models and generated OpenAPI are the executable contract; changes must update both documents and the contract version.

The full v2 release includes every feature in §3. Milestones describe implementation order, not permission to quietly remove advanced features. A working core with an unfinished surrogate or chatbot is a partial build. Record that status accurately even if the deadline arrives.

**Required expansion over the earlier review recommendation:** two geographically distinct pilot AOIs; 30 reviewed fields per pilot; wheat and cotton season configurations; immediate-response, future-investment, and historical-replay modes; five action categories; multiple weather/supply scenarios; robust portfolio selection; a resilience frontier; a validated surrogate with a real preview use; guided regional onboarding; substantive impact/equity/SDG views; a polished interface; and a working assistant built last.

The target is deliberately ambitious for the remaining time. A written plan is not evidence that its critical path fits the deadline. Gate M0 must measure installation, acquisition, inference, and crop-run time; the release report must expose missing features rather than substitute fabricated results.

### 0.2 Canonical release dimensions

| Dimension | Full v2 requirement |
|---|---|
| Geography | 2 non-overlapping, reviewed Punjab AOIs, each with real imagery and mapped canals; 30 reviewed field polygons each |
| Operational topology | 1 declared source and 1–3 modeled watercourses per pilot; connected directed tree; each field has a reviewed route and configured roster |
| Crops | Wheat and cotton, each with a separate suitable seasonal configuration; one crop per optimization run |
| Planning modes | `historical_replay`, `season_response`, `capital_planning` |
| Scientific clock | Daily crop model; chronological within-day delivery/storage events; weekly display summaries |
| Weather | 6 complete historical crop-season series per pilot/crop for surrogate development; 3 selected analogs for scenario exploration |
| Supply | Nominal, uniform deficit, and concentrated interruption profiles, independently editable |
| Actions | Operational timing using available assets; leveling; proposed pond; shared watercourse repair; constrained existing-pump supplementation |
| Alternatives | Fixed-roster baseline; optimized no-new-capital plan; integrated investment plan; robust plan |
| Frontier | At least 6 evaluated budget/service settings, with status and nondominance determined from computed results |
| Stress test | 3 weather analogs × 3 supply profiles; feasibility and production reported separately |
| Surrogate | Crop-specific validated LightGBM previews, followed by exact crop simulation before a new option becomes actionable |
| Onboarding | Draw/import AOI, acquire or import a source package, run/reuse genuine inference, review fields/topology/assumptions, publish a pilot |
| Copilot | Grounded reading, scenario branching, solving, comparisons, explanations, stress/frontier requests, navigation, and local report creation |
| Runtime | Core analytical application and published pilot packages run offline; hosted conversational generation and new online acquisition require connectivity |
| Presentation | Rehearsed 5-minute story plus a deeper interactive route covering every full-release feature |

These are acceptance targets, not current measurements. Field count can be configurable above/below 30 for development, but the full release certificate requires the target fixture in each pilot. Extra arbitrary regions, mixed-crop economic optimization, real gate actuation, aquifer forecasting, and voice are outside this release.

### 0.3 Non-negotiable product invariants

1. All analytical metrics come from executed science, validated accounting, or deterministic calculations with evidence references.
2. Real imagery and historical weather do not imply measured local water rights, crop identity, soil, capacity, or harvest.
3. Every supplied water volume has a source, route, date, and permitted receipt window; storage cannot release water before it exists.
4. A proposed asset becomes available only after a calculated commissioning date. An editable boolean cannot bypass lead time.
5. Each selectable action has a configured cost, target instance, prerequisites, date, and effect mechanism. Missing cost is unavailable, not zero.
6. Exact crop outputs, surrogate previews, retrospective comparisons, and field observations have visibly different labels.
7. A solver proof concerns its finite candidate model. It is not a proof of the best possible real-world farming practice.
8. Requested what-if operations create reversible scenario branches. A recommendation does not operate a canal, transfer a right, order equipment, or contact a farmer.
9. An infeasible finite model, unknown search result, failed job, missing dataset, and uncalibrated input are distinct states.
10. The chatbot is implemented after M0–M6 pass. It calls the same domain services as the interface and receives no alternate path for inventing outcomes.

## 1. User, purchase, and decision

### 1.1 Decision being served

A Water User Association coordinator or extension officer prepares a seasonal watercourse meeting. The committee must decide which feasible improvements to fund, how to operate existing assets, what each action costs, and which fields remain poorly served. AabFlow produces a comparative decision package that can be inspected, challenged, revised, and printed.

The first useful outcome is a defensible planning decision. Model calibration and an observed field benefit are separate achievements that require a supervised pilot.

The original crisis motivation is supported by APP's report of a 22% system-level Rabi 2026–27 shortage for Punjab and Sindh. This is context; no selected pilot receives a measured 22% shortage merely because the headline exists. A local 22% preset is explicitly a scenario. [APP](https://www.app.com.pk/national/22pc-water-shortage-projected-for-rabi-season-2026-27/)

### 1.2 Roles

| Role | Need | Product responsibility |
|---|---|---|
| WUA coordinator | Compare choices and explain distribution | Scenario workspace, farmer/field breakdown, action sheet |
| Extension/agronomy reviewer | Check assumptions and crop response | Input inspector, scientific runs, evidence and validation |
| Program implementer | Allocate limited improvement funding | Portfolio, financial assumptions, frontier, exportable rationale |
| Farmer participant | Understand an action affecting their land/turn | Plain action card, local units, dates, consequences, correction path |
| Judge | Verify that AI and computation genuinely work | Inference evidence, live solve, traceable comparison, transparent limits |

`field_id` identifies a parcel, not a household. Household counts, smallholder protection, and distribution by owner require an explicitly supplied ownership mapping. Until then, say “fields.”

### 1.3 Commercial hypothesis

Start with a supported program pilot: local data review, investment comparisons, planning sessions, and an auditable report. The operator is the WUA/extension coordinator; the initial buyer hypothesis is an organization delivering funded irrigation improvement or resilience work. Seasonal multi-watercourse support is the recurring offer to validate.

IWMI's PRIAT assignment describes water budgeting and participatory planning with 72 WUAs. This provides a concrete institutional workflow to investigate, including existing alternatives AabFlow must complement or outperform. It is not a partnership, customer commitment, or willingness-to-pay finding. [IWMI project](https://www.iwmi.org/projects/strengthening-community-level-water-management-in-punjab-priat-project/)

Record discovery evidence before asserting demand: operator interviews; recent decisions; existing spreadsheet/manual process; data collection time; approval authority; procurement budget; report usefulness. Measure onboarding and agronomic support cost in the business model. Do not price only the computation.

## 2. Geography, seasons, and meaning of real data

### 2.1 Pilot selection

Pilot A is a reviewed Lower Chenab/Mungi research-area AOI. Pilot B is a second non-overlapping agricultural AOI selected through the onboarding workflow, initially within the same broader irrigation region to reuse climate/engineering knowledge while demonstrating real geographic portability. They may be distinct watercourses within a broader command; do not describe that as nationwide coverage.

The published Mungi literature gives a broad search extent, approximately latitude 30°33′–31°2′ N and longitude 72°08′–72°48′ E. This supports discovery only. It does not identify the pilot boundary, individual canal reach, or legal field connections. Record source-feature IDs and imagery footprints before publishing either pilot. [Mungi hydrology study](https://doi.org/10.3390/w14030405)

If the exact Mungi reach cannot be independently identified, use the actual verified location name, such as “Lower Chenab representative pilot A.” This still meets real-geography acceptance if all observed features and assumed operational links are separated and reviewed. Thirty fabricated rectangles over a real background do not meet acceptance.

### 2.2 Three planning modes

| Mode | Meaning | Availability rules | Permitted interpretation |
|---|---|---|---|
| `historical_replay` | Replay an already completed crop season with actual archived gridded weather | Historic or explicitly counterfactual assets with dates preceding their use | Retrospective comparison under known weather; no forecast claim |
| `season_response` | Plan the next/current season from the decision date using analog scenarios | Existing assets; new actions only if their lead time fits before use | Advisory what-if response; weather is uncertain |
| `capital_planning` | Evaluate investments for a future season far enough away to construct them | Explicit decision date, lead time, start date, commissioning, footprint, and life | Future investment comparison under stated assumptions |

The initial response case may use Rabi wheat 2026–27. Proposed 90-day ponds and 120-day repairs cannot be treated as ready for an assumed mid-November 2026 planting. The initial capital case uses a documented future season such as Rabi 2027–28, leaving construction time. These are scenario calendars until locally reviewed.

Wheat and cotton use separate runs, calendars, crop parameters, candidate libraries, and yield metrics. Never add wheat grain kilograms to raw cotton kilograms as an economic or food-security objective. Compare crop-specific production and resource intensity side by side. Mixed-crop profit optimization requires additional validated prices and budgets and is outside v2.

The 2019/2020 cotton study supports the investigation of crop-aware timing under rotational delivery. A separate reproduction track may compare published conditions when enough inputs are available. Its performance is not automatically transferred to wheat. [Cotton scheduling study](https://doi.org/10.1016/j.ecohyd.2024.04.005)

### 2.3 Input reality matrix

| Input | Required v2 acquisition | Meaning and limitation | Publication gate |
|---|---|---|---|
| Satellite raster | Actual Sentinel-2 L2A scene/window for both AOIs | Remote observation on an acquisition date; clouds and 10 m sampling limit usable detail | Valid georeferencing, scene ID, cloud mask, local raster |
| Field polygons | Genuine Delineate inference with retained original output; review/edit as needed | Estimated boundaries, not ownership or automatic crop classification | 30 distinct reviewed geometries and stable IDs per pilot |
| Canals | GRAIN or reviewed OSM subset | Mapped geometry/classification; operational capacity is separate | Source IDs, CRS, source date, overlay inspection |
| Weather | Daily historical gridded temperature, precipitation, reference ET | Reanalysis/grid estimates, not a station in each field | Full continuous crop-season series and provenance |
| Soil | Configured AquaCrop archetypes; literature/raster context if available | Priors until local soil measurements exist | Parameter bounds, soil identity, sensitivity range |
| Crops/planting | User or documented scenario configuration | Not inferred from a single RGB image | Plausible seasonal profile, parameter/source record |
| Water turns | Imported local roster or explicitly configured roster | Time rights and volume caps must be distinguished | Chronological validation and verification label |
| Network capacities | Local record if available; otherwise documented assumptions | Geography does not establish hydraulics | Structural validation and input visibility |
| Costs/effects | Dated quote/reference or editable assumption with range | No guaranteed farm profit or subsidy | All selected action instances have cost/effect/lead time |
| Groundwater | Configured pump availability, volume, cost, quality status | No implied sustainability or salinity tolerance | Finite limits; unknown quality stated |
| Crop output | Executed AquaCrop result | Model output, calibration state visible | Raw outputs, adapter version, run hash, unit checks |

Every published pilot has independent flags for `geography_reviewed`, `topology_structurally_valid`, `rights_verification`, `cost_evidence`, and `crop_calibration`. A single green “verified pilot” badge must not imply all five.

## 3. Full release feature contract

All rows are required for the expanded release. Implementation depth is specified to keep the scope concrete.

| ID | Feature | Completion evidence | Build gate |
|---|---|---|---|
| F01 | Two-pilot geospatial workspace | Real AOIs, canals, imagery, 30 selectable reviewed fields each | M1/M2 |
| F02 | Genuine field AI and review | Raw inference, reviewed polygons, correction record, local overlay | M1 |
| F03 | Guided regional onboarding | A second AOI is processed/imported, reviewed, and published through the real pipeline | M1/M6 |
| F04 | Crop/weather explorer | Wheat/cotton configurations, complete series, analog selection, crop-specific units | M2 |
| F05 | Entitlements, network, and storage | Chronological ledger, routes, source/edge/window bounds, finite groundwater | M2 |
| F06 | Five action categories | Eligible instances, dates, cost/effect parameters, at least one rejected alternative | M3 |
| F07 | Live portfolio selection | New scenario input produces a solver execution and validated run bundle | M3 |
| F08 | Competent baseline ladder | Fixed policy, optimized no-capital, integrated comparison under common conditions | M3 |
| F09 | Season replay | Linked actual crop/flow/storage traces, one selected field and common legend | M4 |
| F10 | Resilience frontier | At least 6 evaluated settings with selectable computed points and clear proof status | M5 |
| F11 | Stress testing and robust plan | 9-cell feasibility/outcome matrix; one shared plan selected across defined uncertainties | M5 |
| F12 | Validated surrogate explorer | Held-out evaluation, bounded preview, exact verification path, OOD refusal | M5 |
| F13 | Why-not, bottleneck, and synergy analysis | Forced/excluded alternatives and matched four-run synergy with valid bounds | M5 |
| F14 | Economics and action plan | Capital/operating breakdown, dates, cropped-area effects, printable report | M4/M6 |
| F15 | Equity and water accounting | Entitlement fulfillment, harmed fields, pumping, storage, withdrawals, losses | M3/M4 |
| F16 | Impact and SDG analysis | Computed project proxies, assumptions, distribution, explicit indicator boundaries | M6 |
| F17 | Evidence and reproducibility | Source/run drill-downs, immutable versions, export/import of permitted assets | M1–M6 |
| F18 | Complete visual/interaction system | Responsive layouts, accessible comparison, loading/error/stale states, local assets | M4/M6 |
| F19 | Conversational copilot | Actual tools for reading, branching, solving, comparing, explaining, and exporting | M7, last feature implementation |
| F20 | Reliable full demo | Offline core test, connected chat test, cold start, restart, rehearsal, release report | M8 |

## 4. Primary journey and workspace

### 4.1 A complete session

1. Open a published pilot and inspect its readiness flags, selected season, crop, and data dates.
2. Review the map and a field's source route, roster, crop/soil assumptions, and existing assets.
3. Choose the dated planning mode, weather/supply assumptions, capital and operating budgets, and equity target.
4. Execute or load a matching baseline, then solve a new portfolio.
5. Compare the fixed baseline, competent no-capital plan, and selected portfolio. Inspect a field that benefits and one that is unchanged or worse off.
6. Challenge a rejected investment or a binding constraint, then create a branch if desired.
7. Explore frontier and stress results. Verify that additional pumping or changed assumptions explain any change in outcome.
8. Review the action plan and provenance. Print/export a versioned decision package.
9. Once the system is complete, use the copilot to conduct the same workflow conversationally.

### 4.2 One coherent application

Primary navigation: **Workspace · Compare · Explore · Impact · Evidence**. “Add region” opens onboarding. The assistant is a persistent side panel, not a separate disconnected application.

Persistent top context: pilot, crop/season, planning mode, scenario revision, baseline/run, and connection state. Changes to weather, money, topology, crop, area, or assumptions visibly invalidate dependent results.

Primary call to action changes with state: **Review inputs → Run plan → Compare results → Export action plan**. Advanced controls are grouped under “Planning assumptions”; the default view offers shortage, capital budget, operating budget, and service target without a wall of configuration.

A first-time user receives a published example session and a short guided route. Example sessions are stored executed runs when available. During development, empty analytical states remain empty; design fixtures are visibly marked and excluded from release mode.

### 4.3 Scenario state machine

`draft → validating → ready → queued → running → succeeded / failed / cancelled`.

Solver outcome is a separate field inside a successful computation: `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, or `MODEL_INVALID`. An `INFEASIBLE` calculation can complete successfully. A network timeout is a failed job, not infeasibility.

Editing a scenario creates a draft derived from an immutable revision. Existing results remain inspectable with their original run ID. The current draft shows “Inputs changed—run again.” A late result never overwrites a newer active scenario. Comparing results is allowed only after a compatibility check or with explicitly labeled non-causal differences.

## 5. F01–F04: real geography, AI, onboarding, and climate

### 5.1 Geospatial inspection

Layers: imagery; observed canal geometry; declared operational connections; field boundaries; head/middle/tail groups; selected asset sites; stress/production/service choropleth; selected water route. Observed geometry and assumed connections differ by line style and legend, not color alone.

Click a field to select its stable ID across map, charts, action cards, evidence, and chat. Click a canal to show its source feature and the separate modeled edge parameters. A geometry line crossing another line does not automatically create a junction.

NDVI context uses two actual cloud-screened observations per pilot if suitable scenes exist in the acquisition window. The required behavior is an honest observation view with valid-data coverage; an unavailable date shows unavailable. It never substitutes NDVI for measured water stress, crop identity, disease, or simulated yield. Crop-state replay uses crop-model outputs.

### 5.2 AI quality review

Retain checkpoint identity, source image, inference configuration, original polygons, reviewed polygons, and edit log. Review validity, overlaps, visibly merged/split fields, boundary displacement, and area. Report number reviewed, number corrected, and review duration; only report accuracy metrics against an independent reference with an explained matching method.

A manually corrected genuine inference can satisfy F02. A fully manual set with no actual inference cannot satisfy full v2 AI completion. Difficult small fields can be replaced by other suitable fields within the legitimate pilot AOI, with the selection recorded; avoid presenting only easy examples as population accuracy.

### 5.3 Onboarding stages

**AOI → sources → imagery/fields → operational graph → crop/soil/rights/assets → validation → publish.**

- AOI: draw a bounded polygon or import GeoJSON. Show area and source availability before starting a job.
- Sources: choose an online acquisition run or a previously downloaded raw source package. Offline imports re-enter the same processing and validation code.
- Imagery: show candidate dates, local cloud coverage, source resolution, and selected bands. Retrieve windows, not whole-country rasters.
- Fields: run/reuse a matching inference by hash, review original/corrected overlays, and stabilize IDs.
- Graph: propose spatial associations for review; require explicit direction, source/outlet, capacity, and roster assumptions before publication. “Automatic” never means guessed rights or hydraulic truth.
- Parameters: choose crop/season/soil, enter or import asset and cost records, and identify input provenance.
- Validation: list blockers and warnings with affected items. Structural blockers prevent publishing. Explicit assumptions may publish as scenario inputs.
- Publish: create an immutable pilot version and invalidate incompatible libraries. Build baseline and crop candidates as jobs.

For the stage demo, a prepared **raw** second-AOI package may eliminate network download time while still exercising real transformation/review/publication. Importing a finished pilot is a separate capability and must not be described as fresh automatic onboarding. A free-form new AOI may take minutes and needs online access; show its actual job progress.

### 5.4 Weather and seasons

Store temperatures, precipitation, and reference ET daily with units and complete dates. The interface shows the grid point, archive model/source, time zone, original dates, and any calendar remapping. Reanalysis is labeled “historical gridded weather.”

Choose dry/typical/wet analogs by a documented crop-season water-balance statistic such as precipitation minus ET0, then retain original daily sequences. These labels describe those selected years, not probability forecasts. Include a heat/timing inspection so seasonal totals do not hide different rainfall distributions.

Future planning may align analogs by days after the scenario's planting date. Store original and shifted dates, use a deterministic leap-day rule, and keep thermal development coherent. A date shift is a scenario transformation, not observed future weather. A current growing crop additionally needs an initial crop/soil state at the decision date; otherwise the release uses pre-season planning and does not claim mid-season assimilation.

## 6. F05–F08: physical actions and valid comparisons

### 6.1 Delivery rights and authority

Each field has permitted receipt windows, a declared outlet/path, and quantity or rate limits at a named accounting boundary. Configured rights remain explicit assumptions unless verified records support them. A time right is not silently converted into a fixed seasonal volume.

The release uses fixed roster windows and a declared proportional supply-curtailment rule to derive each window's available cap. Optimization can choose admissible use within those caps, storage release, allowed pumping, and investments. It cannot move one field into another field's window. Extra cooperative reallocation is outside v2.

Record who would review an operational recommendation. Watercourse-level investment priorities may have distributional consequences even when receipt windows are preserved. Present those consequences instead of implying the software authorizes implementation.

### 6.2 Five action categories

| Category | Physical mechanism | Date/cost requirements | Decision shown |
|---|---|---|---|
| Timing with available assets | Vary field application after permitted receipt using actual storage and pump capacity | Existing asset availability, release/application limits, operating costs | Which admissible schedule uses available water well |
| Leveling service | Change a documented application-efficiency assumption; crop model reruns | Eligible parcel, service cost, lead time, pre-plant or explicitly eligible work date | Where service adds modeled value |
| New pond | Shift receipts through explicit inventory, loss, rainfall, capacity, and release limits | Site footprint, construction cost, commissioning, upkeep, pumping | Whether storage timing value justifies commitment under the selected objective |
| Shared repair | Change a specific edge's conveyance/capacity parameters | Shared project charged once; completion and downtime; eligibility | Which branch improvement supports the strongest admissible portfolio |
| Existing-pump supplementation | Add finite groundwater at a declared point, with energy/cost limits | Existing well, shared ownership if any, quality status, seasonal and time caps | Whether additional irrigation warrants its operating expenditure |

The optimizer sees **instances**, such as `pilot-a:field-007:pond-small` or `pilot-a:edge-02:repair`, and separately references their types. Costs and constraints attach to instances. Multiple mutually exclusive pond sizes at one site cannot be selected together.

A new pond reduces the field's cropped area by its in-field footprint. An off-field site needs its own verified/assumed land availability. All metrics compare the same pre-project landholding boundary while allowing treatment-related cropped-area change.

For v2, new ponds and leveling must be commissioned before planting, so cropped area and application efficiency remain well-defined for the full crop run. Mid-season construction with changing crop area/efficiency requires a different validated model and is outside this release. Shared repairs may use explicitly dated capacity/downtime profiles, provided the physical ledger and routing coefficients include them.

### 6.3 Water and crop invariants visible to the user

Display source withdrawal, water delivered at the outlet, gross field irrigation, groundwater abstraction, pond state/loss, and crop ET separately. Pond rainfall is an explicit inflow when modeled. Existing pond initial inventory is shared between comparison plans; new ponds start empty. Initial soil moisture also matches across treatments.

Model crop output from dated irrigation schedules and crop/soil/weather inputs. Leveling changes an input parameter; it does not add a fixed yield percentage. Ponds change feasible timing; they do not generate water. Groundwater has a finite cost and limit. Unsupported salinity, disease, or fertility effects remain outside the crop engine's scope.

The UI labels withdrawals reduced separately from consumptive water savings. Basin-wide savings remain `not_estimated` unless the analysis actually accounts for recoverable return flows and a suitable basin boundary. A modeled pumping reduction may be reported directly when both runs include the same pumping accounting.

### 6.4 Baseline ladder

| Plan | Specification | Purpose |
|---|---|---|
| B0 Fixed-roster policy | Declared receipt rule, finite sources, existing assets, dated application rule; curtailment and closures processed before crop simulation | Transparent operational reference |
| B1 No new capital | Same physical/information conditions; optimize feasible operations using existing assets, with new capex fixed to zero | Competent benchmark for the value of investment |
| P Integrated | Choose eligible investment instances and feasible operations under budgets | Main recommendation |
| R Robust | Same portfolio and operation policy evaluated across specified uncertain states | Protection against the chosen scenario set |

The candidate library includes the baseline's exact action policy when physically feasible. B1's candidate set is a subset of P's admissible no-investment options. This supports a meaningful optimality comparison. A timed-out P run may underperform a known B1 incumbent; retain and seed the feasible incumbent rather than show a worse result as an improvement.

All plans share the same source availability profile, weather realization for each comparison cell, crop parameters, initial soil/pond state, and cost assumptions unless the difference is the defined treatment. An assets-for-next-year plan is not directly credited with rescuing this year's crop.

Retrospective optimization using known daily rain is labeled retrospective. Future analog planning commits to the selected dated actions across weather states; it receives no hidden perfect forecast. Stress recovery plans are separate scenario-specific recommendations and are not presented as a single plan known in advance.

### 6.5 Default objective

For each single-crop run, maximize modeled harvested production subject to source/edge/window constraints, a capital budget, a seasonal operating budget, and a service target. Break equivalent production ties by lower operating expenditure, then lower capital commitment and source withdrawal, using the companion's explicit tolerances.

An optional `irrigation_contribution_pkr` objective is enabled only when a dated crop value and all decision-dependent variable costs are supplied. It measures crop value less the specified irrigation-related costs; it is not automatically full farm profit. Lifecycle projections disclose crop price, asset life, maintenance, discount, terminal value, and all annual scenarios. These projections do not silently alter the single-season objective.

## 7. F09–F13: replay, frontier, risk, surrogate, explanations

### 7.1 Season replay

Use two synchronized map views with one shared date control and one selected field. The camera, legend, color domain, dates, metric definitions, and scenario IDs stay aligned. A vertical swipe comparison is available on narrow screens.

Timeline tracks show permitted receipts, actual receipts, field application, rain, pumping, pond fill/release, and crop-stage markers where the installed model exposes or reproducibly derives them. At each step, the selected field panel plots actual canopy/soil/crop output series. Do not interpolate harvest yield into an invented daily yield curve. Before harvest, show canopy or biomass with correct labels.

Source flow animations show direction/activity only. Their speed does not claim simulated hydraulic velocity. Pausing and scrubbing must leave all charts at the same run/date. Reduced-motion mode preserves the data and removes decorative movement.

### 7.2 Resilience frontier

Explore six or more independently solved settings spanning capital budget and/or minimum service floor. Axes are explicit: for example, capital commitment versus modeled crop production, with minimum service encoded in a labeled channel.

Each point opens its immutable run and actual action portfolio. Show dominated feasible points lightly, nondominated points prominently, and infeasible/unknown settings separately. “Nondominated among evaluated plans” is the default label. Time-limited points do not establish a mathematically complete Pareto frontier.

Budget/service sweeps reuse candidate science, not fabricated interpolated outcomes. Connecting lines are visual guides; clicking between points initiates a new solve. Warm starts and caching are allowed with matching hashes and visible execution timestamps.

### 7.3 Stress matrix and robust choice

Evaluate the chosen plan on three historical weather analogs and three configured source profiles. A weather change may alter crop response and pond losses. A supply interruption can make the original planned receipts impossible.

Every cell first answers “Can this plan actually be delivered?” If no, show the violating receipt/route/period; do not attach its original schedule's crop yield as an achievable outcome. The user may request a separate recovery solve with investments held fixed, clearly labeled scenario-specific replanning.

The robust optimizer selects one portfolio and one dated operation policy that is physically valid in every selected state; it maximizes worst-case crop-specific production, with explicit tie-breaks. This conservative model is implementable before a full stochastic recourse framework. Display the scenario set, outcome range, and foregone typical-scenario output relative to the typical-only plan.

Three analogs and three supply profiles are scenario tests. “Worst case” means worst within those nine tested states. Do not display a probability of success without a calibrated probabilistic model.

### 7.4 Surrogate explorer

The surrogate has a real job: provide a fast, explicitly approximate yield preview for a newly proposed admissible irrigation schedule or in-range parameter change before executing a new crop simulation. A preview may guide which candidate to simulate next. It does not create a final plan's canopy trace or replace water/rights validation.

Train crop-specific LightGBM models on executed simulation records. Split entire weather years and schedule families, not neighboring rows. Show held-out error, ranking, decision-regret tests, training domain, and model version. All thresholds in the companion are development targets.

Out-of-domain input produces “Outside validated preview range—run crop model.” A final recommendation using a new schedule waits for exact crop outputs and full physical validation. Accepted plans show exact metrics; the preview remains separately inspectable for fidelity evaluation.

A failed surrogate evaluation means F12 is incomplete. The exact planning engine remains usable; it does not make the full expanded release complete.

### 7.5 Decision explanations

- **Why selected:** prerequisites met, marginal role in a matched comparison, cost, water timing, and affected fields.
- **Why rejected:** ineligible/too late/over budget can be explained from validations. A quantitative opportunity cost needs a forced-inclusion solve.
- **Why no solution:** identify validated constraint groups and candidate-library coverage. Offer an explicit branch with a relaxed setting; never relax it silently.
- **Bottleneck:** explain a saturated or conflicting resource. A binding constraint alone does not prove that relaxing it improves production; quantify improvement only by a new solve.
- **Synergy:** evaluate none, A, B, A+B under matched conditions. Report the four outcomes and `both − A − B + none`, including negative synergy. Skip an infeasible comparison and explain why.

If alternative solves have gaps, use candidate objective intervals or label the difference provisional. Do not claim a precise rejection penalty when the alternative's best achievable objective is unresolved.

## 8. F14–F17: actionable output, economics, equity, impact, evidence

### 8.1 Action sheet

For each action: target and map link; crop/season; action description; decision/start/commissioning dates; quantity; cost breakdown; payer/assumed financing; responsible role; required approval; prerequisites; affected fields; modeled change; uncertainty; source/run references; status `proposed / reviewed / accepted / rejected`.

“Accepted” records the local software user's decision only. It is not a government authorization or work order. Export HTML printable to PDF, CSV schedules, GeoJSON selected locations where permitted, and JSON run metadata. PDF must include the same dates, assumptions, units, and status as the screen.

Provide an incremental view: B0→B1 operational gain; B1→P investment gain; P→R risk trade-off. The report clearly states where greater output also uses greater pumping or expenditure.

### 8.2 Financial panel

Separate gross project cost, public grant if verified, participant cash requirement, seasonal pumping and upkeep, crop value assumption, and the specifically defined contribution metric. No subsidy is enabled without the relevant program/site/applicant eligibility record. Null price/cost disables the corresponding financial calculation.

The default capital budget constrains **gross project commitment**. A verified grant changes the participant-cash breakdown; it does not increase that gross budget automatically. A separately configured participant-cash constraint can apply alongside it. Both budgets and their payer/boundary are visible when used.

Include a sensitivity table for uncertain capital cost, operating cost, and crop price. A multi-year illustrative cashflow view supports documented useful life and recurring benefits/costs. Payback is “not reached within modeled horizon” if cumulative discounted or undiscounted cashflow, as labeled, never crosses zero. A constant annual benefit extrapolation is identified as an assumption, not a multiseason agronomic simulation.

### 8.3 Equity panel

Primary measures: field canal receipts divided by configured full-supply entitlement at the same boundary; minimum eligible field fulfillment; head/middle/tail distributions; each field's production delta; fields worse off; pumping burden distribution. Exclude zero-entitlement fields from entitlement ratios and list them separately. State whether aggregation is field-weighted or entitlement-volume-weighted.

For a time-based right whose volume denominator is derived from assumed discharge, label this measure **receipt / reference allowance**. Preserve the actual receipt window and do not portray the derived volume as a verified legal quota. The denominator remains fixed across compared plans.

Tail minimum can be a hard floor. If physically or finitely infeasible, show the conflict. No green aggregate score may conceal fields with reduced service. When ownership is known, provide owner-level aggregation without double-counting multiple parcels.

### 8.4 Water accounting

Use a ledger/sankey with boundary-specific amounts: source withdrawals → conveyance delivery/loss → direct irrigation or storage → field application, with groundwater and rainfall explicit. Root-zone storage, runoff, deep percolation, soil evaporation, transpiration, and ET are displayed only if defined and available from the adapter. Do not sum ET and its components as separate losses.

Store pond residual storage and soil state at season end. The comparison should expose remaining stored water rather than make a plan look inefficient because it carries useful inventory beyond harvest. The single-season objective does not assign that inventory an invented financial salvage value.

### 8.5 SDG and impact explorer

Three substantive cards with drill-downs:

| Alignment | Computed project proxy | Required interpretation |
|---|---|---|
| SDG 2.4 | Crop-specific production retained across tested scenarios; distribution of field changes | Model-based planning resilience, not measured food security |
| SDG 6.4/6.5 | kg of the selected crop per m³ of clearly defined withdrawal; groundwater change; entitlement fulfillment | Water productivity/accounting/participation proxies, not official UN indicator scores |
| SDG 13.1 | Worst tested scenario outcome and difference from the typical-case plan | Scenario robustness, not a quantified disaster-risk reduction |

Each card opens the formula, numerator/denominator, baseline/run IDs, source records, and limitations. No arbitrary 0–100 SDG score. No CO₂ number unless energy, fuel/grid factor, and system boundary are supplied and cited. Impact badges are not substitutes for the action report.

### 8.6 Evidence interface

Every metric supports “How was this calculated?” with metric formula, raw unit, source lineage, scenario assumptions, software/library versions, crop calibration state, solver status and bound, and reproducible run ID. Use progressive disclosure: the main screen remains legible, while decisive assumptions are always close to the result.

Pilot inputs, candidate libraries, trained models, and completed runs are immutable/versioned. Correction creates a new version and an explicit invalidation path. Restore a saved run without silently recomputing it using newer inputs.

## 9. F18: visual design and interaction specification

### 9.1 Visual direction

Create an elegant agricultural planning instrument: warm mineral surfaces, deep ink text, restrained teal water cues, precise typography, aerial imagery, and generous spacing around the important decision. Use dense information only where it supports inspection. A large map and a clear comparative result should carry the visual identity.

Use original product composition. Avoid making each metric a large interchangeable card. Let the selected field and season narrative organize the page: a quiet context header, useful map, compact result strip, aligned timeline, and an inspector with a clear reading order.

### 9.2 Design tokens

| Token | Starting value | Role |
|---|---|---|
| `canvas` | `#F4F2EB` | Warm application background |
| `surface` | `#FFFFFF` | Inspectors and primary controls |
| `surface-muted` | `#EBEFE9` | Secondary groups and quiet selections |
| `ink` | `#172B2A` | Primary text |
| `ink-secondary` | `#4B6260` | Secondary text; verify contrast on each surface |
| `water` | `#087F8C` | Primary action and water identity |
| `water-deep` | `#075E68` | Hover/pressed; white text contrast checked |
| `vegetation` | `#386A4B` | Crop identity, not universal “success” |
| `warning` | `#A35B08` | Assumption/partial state with icon/text |
| `danger` | `#A63E32` | Errors, explicit negative changes |
| `border` | `#CFDAD5` | Group separation |
| `focus` | `#245FBD` | Visible keyboard focus |

Tokens are design starting points. Measure WCAG AA text contrast, non-text control contrast, and selected-state clarity before acceptance; do not declare accessibility from hex values alone.

Typography: locally bundled Inter for interface/data, Fraunces for a restrained landing/presentation headline, and a locally bundled Urdu-capable font such as Noto Naskh Arabic for Urdu content. Verify redistribution licenses. Body 14–16 px; labels at least 12 px in the interactive app; presentation mode at least 16 px for essential labels. Use tabular numerals for metrics. Spacing follows 4/8/12/16/24/32 px; corner radius 10–16 px; subtle shadows only where depth explains layering.

### 9.3 Desktop composition

At wide desktop sizes: 64 px navigation rail, 64 px context header, 280 px scenario panel, flexible map/results canvas, and a 360 px inspector. Opening chat replaces the inspector with a roughly 400 px conversation panel; it does not cover the primary solve controls. Tabs allow switching back to field details without losing selection.

At 1366×768: collapse optional details and make the scenario panel collapsible. At 1024 px: use a drawer for inspection/chat. On mobile: stack summary and map, use full-height sheets, and maintain a table alternative for map-only information. There must be no horizontal overflow hiding the solve or export action.

### 9.4 Screen behavior

| Surface | Main content | Primary action | Critical state |
|---|---|---|---|
| Workspace | Map, assumptions, selected field, compact input controls | Run plan | Changed inputs and data readiness |
| Compare | B0/B1/P/R metrics, synchronized replay, distribution | Inspect difference | Comparison compatibility |
| Explore | Frontier, stress matrix, surrogate preview, why-not | Evaluate selection | Exact versus preview/provisional results |
| Impact | Water ledger, economics, equity, SDG cards | Export report | Metric definitions and missing inputs |
| Evidence | Sources, runs, model evaluation, lineage | Open source/run | Verification and calibration state |
| Onboarding | Stepper, sources, review map, blockers | Continue/publish | Real job stage and review requirements |
| Copilot | Context badge, messages, tool activity, result cards | Ask/run requested what-if | Run references and connection state |

### 9.5 Interaction details

- Selecting a frontier point highlights its portfolio on the map and updates the inspector only after the correct run is loaded.
- Dragging a budget slider edits a draft; release/debounce validates it. “Run plan” executes. Optional auto-run is explicit and bounded, never a request on every pixel of dragging.
- A baseline/plan toggle has persistent labels. Stress and yield maps use separate legends and cannot share an ambiguous color meaning.
- Hover is supplementary; every hover detail is accessible by click/focus.
- Loading skeletons indicate layout only. No fake numbers count upward while waiting for results.
- For long jobs show real stages, completed subruns, elapsed time, cancellation, and last update. Use an indeterminate indicator if percent completion cannot be measured.
- Friendly status copy accompanies solver terminology: “Valid plan found; search ended before optimality was proven.”
- Empty states name what is missing and link to the relevant input. Avoid generic “Something went wrong.”
- Keyboard shortcuts: command menu, field search, play/pause when timeline focused, and escape to close panels. Never intercept typing in inputs/chat.
- Animations: 120–180 ms control feedback, 180–240 ms panels, deliberate 300–450 ms camera moves; honor reduced motion. Data transitions must not imply uncomputed intermediate outcomes.

### 9.6 Visual acceptance

Capture and inspect Workspace, Compare, Explore, Impact, Onboarding, and Copilot at 1920×1200, 1366×768, and a mobile viewport. Test keyboard navigation, focus return, screen-reader labels for controls, table alternatives for charts, and color-independent status. Verify local fonts/icons/raster/JS with the network disabled. Beautiful means coherent typography, hierarchy, alignment, meaningful motion, and readable real results—not a screenshot-only shell.

## 10. F19: conversational copilot — final feature implementation

### 10.1 User-visible capability

The assistant understands the currently selected pilot, scenario, run, crop, date, and field. It can answer questions about those entities, retrieve evidence, and operate the analytical workflow through validated tools.

Required examples:

1. “Why is this tail field worse off?” Read field deltas and matched inputs, explain supported mechanisms, link to the relevant interval.
2. “Reduce the budget to PKR 2 million and protect the tail fields.” Create a branch, validate settings, run the solver, compare with the parent.
3. “What if we build the pond anyway?” Check eligibility, run a forced-inclusion alternative, explain costs and differences.
4. “Which assumption should we check before spending?” Use sensitivity results and identify a decision-changing uncertain input.
5. “Show the plan under dry weather and a two-week interruption.” Run a stress test; distinguish infeasible commitments from modeled yield.
6. “Show me the trade-off between spending and protecting tail fields.” Start/load a matching frontier and present selectable run cards.
7. “Can you explain that in Urdu?” Explain the same tool-backed result in Urdu or Roman Urdu while preserving units, IDs, and meaning.
8. “Prepare a one-page plan for the committee.” Generate a local report from a specified run; return the download link.

### 10.2 Tool-backed behavior

The assistant reads structured domain results and a curated evidence index. Numerical comparisons are calculated by backend services. Each result card cites run/metric/source IDs and opens the corresponding view. An answer can say “unknown” and point to missing input.

Read queries execute immediately. An explicit request to run a reversible what-if authorizes scenario branching and computation within configured job limits. The assistant summarizes the resulting changes; it need not ask for an extra confirmation before every local simulation. Ambiguous units, pilot, crop, or intended service target trigger a focused clarification when they materially change the action.

It never silently overwrites the active scenario. “Use this plan” selects a created branch in the UI; prior versions remain available. It cannot change verified source records, legal entitlements, or provenance through a generic text edit. Such changes use the dedicated input-review workflow.

### 10.3 Grounding and product boundaries

- A statement about a result must identify the run it describes. A stale run may be discussed as historical, with its identity visible.
- Tool evidence and retrieved documents are data, not instructions capable of changing permissions or the assistant's role.
- Facts missing from the pilot are not filled in with general agronomic knowledge and presented as measurements.
- A draft schedule must pass physical validation and exact simulation before being described as a computed recommendation.
- Report generation stays local. Sending email, purchasing, grant submission, and physical irrigation control are unavailable tools.
- Show source-backed result cards and concise tool activity, not private reasoning traces.
- Model/provider failures leave a clear retry/error state. Core controls, evidence, deterministic explanations, and saved results continue to work offline.

### 10.4 Provider and connectivity

Default integration: a server-side OpenAI Responses tool-calling loop with `gpt-6.1-sol` as the initial evaluated model, configurable by deployment. Official model/API documentation was checked; account access, latency, and actual application success require runtime tests. [Model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol) [Function calling](https://developers.openai.com/api/docs/guides/function-calling)

Hosted chat requires internet and a configured API key. The release explicitly distinguishes **offline analytics** from **connected copilot**. An evaluated local-model adapter can be added if the target hardware supports it; it is not a claimed fallback until it passes the same tool-use tests. Do not rename deterministic help text as an offline generative chatbot.

### 10.5 Copilot acceptance

Run the companion's 30-case evaluation suite with saved transcripts and tool logs. Require all critical cases to pass: correct scenario identity, no unsupported analytical number, no unrequested source/rights mutation, truthful infeasibility, no duplicate branch/job on retries, and correct report links. At least 90% of the full task suite must complete successfully across three runs per case; critical safety/data-integrity cases must pass every run. These are release targets, not present metrics.

## 11. Performance, reliability, and release acceptance

### 11.1 Targets on the presentation laptop

| Operation | Target after measured setup | Conditions |
|---|---|---|
| Cold core UI load | ≤5 s | Services started; local pilot assets |
| Field selection / panel update | ≤200 ms perceived feedback | Cached geometry and summary; full series may load subsequently |
| Single portfolio solve | p50 ≤5 s; p95 ≤15 s | 30 fields, bounded vetted candidates, total configuration budget |
| Six-setting frontier | ≤60 s total | Progressive results; no hidden per-point timeout multiplication |
| Nine-cell stress matrix | ≤60 s with available exact outcomes | New science jobs display separate progress if needed |
| Surrogate preview | ≤300 ms backend after model load | In-domain input; excludes exact confirmation |
| Local report | ≤5 s HTML export | Charts/metrics already available |
| Chat | Immediate sending/tool-state feedback; latency recorded | Provider and analysis jobs vary; no fabricated fixed response guarantee |
| New AOI acquisition | Measured and reported | Depends on network, raster size, inference, and review; not a 3-second promise |

### 11.2 Cross-feature acceptance tests

- **AT01:** Both pilot packages contain actual scene/source IDs, 30 valid reviewed fields, and a structurally valid declared graph.
- **AT02:** At least one wheat and one cotton run finish with raw model outputs, known units, and actual varying irrigation treatments.
- **AT03:** A Monday-before-Friday pond-use fixture and an intra-period over-capacity fixture are rejected.
- **AT04:** Closed-route receipts, excessive shared-pump use, missing costs, and premature commissioning are rejected.
- **AT05:** Zero capital produces no new assets. A competent no-capital plan is available for comparison.
- **AT06:** A live budget/deficit change executes the optimizer, returns a different feasible set or plan where the fixture is designed to make the constraint relevant, and preserves the run ledger.
- **AT07:** Candidate coverage and finite-model optimality are visible. No-feasible-option is not overstated as physical impossibility.
- **AT08:** Matched comparisons share weather, crop/input state, and budget semantics. Nonmatched comparisons are labeled.
- **AT09:** A six-setting frontier and nine-cell stress matrix are inspectable and map back to run records.
- **AT10:** The robust run uses shared decisions across states, and impossible fixed-plan stress cells have no fabricated achievable yield.
- **AT11:** Surrogate evaluation uses held-out groups and passes its thresholds; previews are visibly distinct and exact-confirmed before final use.
- **AT12:** Shared project cost is charged once; pond land is removed from crop production; pumping has an operating budget.
- **AT13:** Report, UI, and chatbot reference the same metric values, units, and run IDs.
- **AT14:** Six key screens pass responsive, keyboard, contrast, loading/error/stale, and reduced-motion review.
- **AT15:** Core boot, solve, replay, frontier, stress, evidence, and export work with network denied and no hidden CDN requests.
- **AT16:** Onboarding processes the second raw package through actual review/validation and publishes a new pilot version.
- **AT17:** The copilot completes the evaluated tool workflows using real application services, including failures and follow-up questions.
- **AT18:** A clean restart restores completed runs, marks interrupted jobs honestly, and does not substitute stale results for current drafts.

## 12. Hard-deadline build sequence

M0–M8 all precede full release. Preparatory data generation can run while UI shells are implemented, but chatbot feature implementation starts only after M6. Checking provider account access during M0 is a dependency check, not early chatbot construction.

| Milestone | Required outcome | Acceptance IDs / features |
|---|---|---|
| M0: feasibility and contracts | Lock environments; run science/solver sample; verify data access, hardware, provider access; freeze schemas; estimate critical path | Dependencies for all |
| M1: real source packages | Two AOIs; source acquisition/import; actual inference/review; fields/graph/manifest; onboarding pipeline | F01–F03/F17, AT01 |
| M2: exact domain engine | Two crop configurations; complete weather; chronological ledger; crop adapter; reusable candidate generation | F04/F05, AT02–AT04 |
| M3: decisions | Baselines; all action categories; live selection; constraints; economics/rights bounds | F06–F08/F15, AT05–AT08/AT12 |
| M4: polished decision loop | Workspace/Compare; real replay; report; visual system; error/stale flows | F09/F14/F18, AT13/AT14 |
| M5: expanded intelligence | Frontier, 9-state stress/robust selection, surrogate training/evaluation, explanations and synergy | F10–F13, AT09–AT11 |
| M6: complete core | Impact/SDGs, onboarding UI, evidence, export, offline/restart verification | F03/F16–F18, AT15/AT16/AT18 |
| M7: copilot, implemented last | Tool registry, provider loop, context, rich chat cards, bilingual output, evaluation | F19, AT17 |
| M8: release | Full regression, cold launch, rehearsals, recorded backup, capability report | F20, all AT IDs |

The companion supplies the deadline schedule, parallelizable work boundaries, measured runtime budgeting, and stop conditions. Missing a gate is recorded as an incomplete feature. It must not be converted into a prerecorded “live” response, silent feature removal, or an invented measurement.

## 13. Demonstration and pitch

### 13.1 Narrative

Use an explicitly illustrative committee and farmer situation mapped onto the actual pilot geometry. A coordinator must explain which improvements deserve limited money and which downstream fields remain exposed. The audience follows one field and one disputed investment through the decision.

Suggested opening:

> “A watercourse committee can fund only some of the improvements its farmers need. One farmer wants a pond; another wants leveling. They need to know what each choice changes, what it costs, and who will still be short of water. AabFlow lets them test those decisions before spending.”

Use the actual executed outcome as the payoff. Preserving production with less pumping, rejecting an expensive low-value project, or protecting a tail field at an explicit trade-off can each make a strong story. Do not tune assumptions solely to manufacture a dramatic improvement percentage.

### 13.2 Five-minute stage route

| Time | Action and claim |
|---|---|
| 0:00–0:35 | Introduce the decision and one downstream field; one sourced fact establishes urgency |
| 0:35–1:00 | Show real pilot imagery and genuine reviewed AI boundaries; state what local inputs remain assumed |
| 1:00–1:50 | Compare fixed and no-capital baselines; run the integrated portfolio with the chosen dated horizon |
| 1:50–2:35 | Change budget or force an eligible investment; show live recomputation and field distribution |
| 2:35–3:15 | Replay the decisive interval; show actual storage/irrigation/crop traces |
| 3:15–3:45 | Open frontier and stress matrix; distinguish tested robustness from prediction certainty |
| 3:45–4:25 | Ask the copilot a fresh, bounded what-if or explanation; show tools, result reference, and action card |
| 4:25–5:00 | Show report, operator/buyer hypothesis, validation status, and ask for a supervised pilot partner |

The deeper inspection route demonstrates the second pilot's onboarding, cotton run, surrogate preview→exact confirmation, synergy, SDG formulas, and offline mode. These must work even if the five-minute narration cannot inspect every screen.

### 13.3 Proof package

Bundle versioned pilot sources permitted for redistribution, raw inference evidence, scientific outputs, candidate manifests, model evaluation, completed run IDs, original-precision ledgers, solver logs/bounds, frontend checks, chat evaluation transcripts with secrets removed, and the rehearsal recording. A capability report lists each F/AT ID as passed, failed, or blocked with artifact paths.

## 14. Success beyond the competition

Track whether a coordinator can produce an understood action plan, how long local onboarding takes, which inputs change recommendations, whether experts accept the assumptions, and whether decision-makers request another seasonal session. In a supervised pilot, record implemented actions, actual deliveries/pumping, costs, crop conditions, and harvest outcomes with a suitable comparison design.

The project's next commercial claim should follow that evidence. The full v2 demo establishes an executable, inspectable planning workflow; real agronomic effectiveness and willingness to pay remain empirical questions.
