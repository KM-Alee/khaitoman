/**
 * DESIGN FIXTURE — synthetic API responses for UI review only (T10.6).
 *
 * Purpose: render every screen and state (empty/busy/ready/stale/feasible/infeasible/
 * unknown/error) for screenshot-driven design QA before the real pipelines publish.
 * Imagery, DEM and canal geometry are the real processed pilot-A intake files when present;
 * fields, network, runs, metrics and analyses below are SYNTHETIC and labelled as such.
 * Never used by the application or the real-API journey spec; excluded from release data.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import type { Page, Route } from "@playwright/test";

export const FIXTURE = "design-fixture";
const PILOT = "fixture-a";
const VER = "design-v1";
const INTAKE = resolve(__dirname, "../../../data/pilots/.intake/pilot-a-reviewed-v1/processed");

/* -------------------------------------------------------------- deterministic RNG */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/* -------------------------------------------------------------- geography */
const AOI = [72.306, 30.776, 72.33, 30.798];
function realImagery() {
  const dir = join(INTAKE, "imagery");
  if (!existsSync(dir)) return null;
  const json = readdirSync(dir).filter((f) => f.endsWith(".json"));
  const prim = json.map((f) => JSON.parse(readFileSync(join(dir, f), "utf8"))).sort((a, b) => (a.label === "primary" ? -1 : 1))[0];
  return prim
    ? { scene_id: prim.scene_id, acquired_at: prim.acquired_at, url: `/assets/pilots/${PILOT}/${VER}/${prim.image_ref}`, corners: prim.corners_wgs84, evidence_id: "ev-fixture-s2", resolution_m: 10, aoi_valid_fraction: 1, file: join(INTAKE, prim.image_ref) }
    : null;
}
function realTerrain() {
  const j = join(INTAKE, "terrain/dem.json");
  if (!existsSync(j)) return null;
  const t = JSON.parse(readFileSync(j, "utf8"));
  return { url: `/assets/pilots/${PILOT}/${VER}/terrain/dem.png`, bounds: t.bounds, encoding: "terrarium", min_m: t.min_m, max_m: t.max_m, file: join(INTAKE, "terrain/dem.png") };
}
function realCanals(): GeoJSON.FeatureCollection {
  const p = join(INTAKE, "canals.geojson");
  if (existsSync(p)) return JSON.parse(readFileSync(p, "utf8"));
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", id: "fx-canal-1", properties: { name: "Fixture canal" }, geometry: { type: "LineString", coordinates: [[72.3214, 30.7828], [72.32435, 30.786], [72.3206, 30.792]] } }],
  };
}

/** 30 synthetic field rectangles in three bands (head/middle/tail) beside the watercourse. */
function fields(): GeoJSON.FeatureCollection {
  const feats: GeoJSON.Feature[] = [];
  const r = rng(7);
  let n = 0;
  const bands: { g: "head" | "middle" | "tail"; lat0: number }[] = [
    { g: "head", lat0: 30.7838 },
    { g: "middle", lat0: 30.7872 },
    { g: "tail", lat0: 30.7906 },
  ];
  for (const b of bands) {
    for (let row = 0; row < 2; row++) {
      for (let col = 0; col < 5; col++) {
        n++;
        const w = 0.00078 + r() * 0.00018;
        const h = 0.00118 + r() * 0.0002;
        const x0 = 72.3115 + col * 0.00102 + (row ? 0.0003 : 0);
        const y0 = b.lat0 + row * 0.00142;
        const skew = (r() - 0.5) * 0.00008;
        const id = `${PILOT}:field-${String(n).padStart(3, "0")}`;
        feats.push({
          type: "Feature",
          id,
          properties: { field_id: id, label: `Fixture field ${String(n).padStart(2, "0")}`, group: b.g, gross_area_m2: Math.round(w * 96000 * h * 111000), fixture: FIXTURE },
          geometry: { type: "Polygon", coordinates: [[[x0, y0], [x0 + w, y0 + skew], [x0 + w + skew, y0 + h], [x0, y0 + h], [x0, y0]]] },
        });
      }
    }
  }
  return { type: "FeatureCollection", features: feats };
}

const FIELDS = fields();
const FIELD_IDS = FIELDS.features.map((f) => String(f.id));
const groupOf = (id: string) => (FIELDS.features.find((f) => f.id === id)!.properties as { group: string }).group;
const centroidOf = (id: string) => {
  const c = (FIELDS.features.find((f) => f.id === id)!.geometry as GeoJSON.Polygon).coordinates[0];
  return [(c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2];
};

const NODES = [
  { node_id: "src", kind: "source", lon: 72.3214062, lat: 30.7828247, label: "Watercourse head" },
  { node_id: "j1", kind: "junction", lon: 72.32435, lat: 30.7860131, label: null },
  { node_id: "j2", kind: "junction", lon: 72.3205934, lat: 30.7920228, label: null },
  { node_id: "o-head", kind: "outlet", lon: 72.3162, lat: 30.7852, label: "Head outlet" },
  { node_id: "o-mid", kind: "outlet", lon: 72.3168, lat: 30.7887, label: "Middle outlet" },
  { node_id: "o-tail", kind: "outlet", lon: 72.3172, lat: 30.7921, label: "Tail outlet" },
  { node_id: "pump-1", kind: "pump", lon: 72.3155, lat: 30.7884, label: "Shared tubewell" },
];
const E = (edge_id: string, up: string, down: string, geom: string | null, df: number, reach: string) => ({
  edge_id,
  upstream_node_id: up,
  downstream_node_id: down,
  geometry_ref: geom,
  source_feature_ids: geom ? [geom] : [],
  delivery_factor: df,
  capacities: [],
  closures: [],
  reach_label: reach,
  evidence_ids: ["ev-fixture-net"],
});
const EDGES = [
  E("e-1", "src", "j1", "osm:way/1245856795", 0.92, "Reach 1 (head)"),
  E("e-2", "j1", "j2", "osm:way/1246259150", 0.78, "Reach 2 (tail)"),
  E("e-3", "src", "o-head", null, 0.95, "Head offtake (assumed)"),
  E("e-4", "j1", "o-mid", null, 0.9, "Middle offtake (assumed)"),
  E("e-5", "j2", "o-tail", null, 0.85, "Tail offtake (assumed)"),
];
const ASSETS = [
  { asset_id: "pond-existing-1", kind: "pond", existing: true, field_ids: [FIELD_IDS[12]], node_id: null, commissioned_at: "2023-01-01", usable_capacity_m3: 1800, surface_area_m2: 1200, footprint_m2: 1400, initial_inventory_m3: 600, max_fill_m3_day: 400, max_release_m3_day: 300, seepage_m3_day: 4, k_evap: 1, rain_capture_fraction: 1, max_rate_m3_h: null, seasonal_cap_m3: null, cost_per_m3_pkr: null, head_m: null, efficiency: null, quality_status: "unknown", annual_upkeep_pkr: 20000, evidence_ids: [], lon: 72.3142, lat: 30.7893 },
  { asset_id: "pump-shared-1", kind: "pump", existing: true, field_ids: FIELD_IDS.slice(10, 20), node_id: "pump-1", commissioned_at: "2019-01-01", usable_capacity_m3: null, surface_area_m2: null, footprint_m2: null, initial_inventory_m3: 0, max_fill_m3_day: null, max_release_m3_day: null, seepage_m3_day: 0, k_evap: 1, rain_capture_fraction: 1, max_rate_m3_h: 90, seasonal_cap_m3: 40000, cost_per_m3_pkr: "6.5", head_m: 18, efficiency: 0.55, quality_status: "marginal", annual_upkeep_pkr: 35000, evidence_ids: [] },
];

/* -------------------------------------------------------------- catalog */
const SEASON = { season_id: "wheat-rabi-2026-27", crop: "wheat", crop_profile_id: "wheat-punjab-v1", start: "2026-11-01", end: "2027-04-30", planning_modes: ["season_response", "capital_planning"], label: "Rabi 2026–27", decision_at: "2026-10-20T00:00:00+05:00", planting_date: "2026-11-15" };
const COTTON = { season_id: "cotton-kharif-2027", crop: "cotton", crop_profile_id: "cotton-v1", start: "2027-04-15", end: "2027-11-15", planning_modes: ["season_response", "capital_planning"], label: "Kharif 2027", planting_date: "2027-05-01" };
const WEATHER = [
  { weather_scenario_id: "dry", season_id: SEASON.season_id, label: "Dry analog", analog_season_start: "2018-11-01", weather_series_id: "ws", date_mapping_ref: null, transformed_sha256: "a".repeat(64), is_typical: false, selection_basis: "Lowest P − ET0 tercile, 2014–2024 (fixture)" },
  { weather_scenario_id: "typical", season_id: SEASON.season_id, label: "Typical analog", analog_season_start: "2021-11-01", weather_series_id: "ws", date_mapping_ref: null, transformed_sha256: "b".repeat(64), is_typical: true, selection_basis: "Median P − ET0 tercile, 2014–2024 (fixture)" },
  { weather_scenario_id: "wet", season_id: SEASON.season_id, label: "Wet analog", analog_season_start: "2019-11-01", weather_series_id: "ws", date_mapping_ref: null, transformed_sha256: "c".repeat(64), is_typical: false, selection_basis: "Highest P − ET0 tercile, 2014–2024 (fixture)" },
];
const SUPPLY = [
  { supply_profile_id: "nominal", label: "Nominal roster supply", base_profile_hash: "d".repeat(64), resolved_hash: "d".repeat(64), pre_reduced: false },
  { supply_profile_id: "deficit-22", label: "Uniform 22% deficit", base_profile_hash: "d".repeat(64), resolved_hash: "e".repeat(64), pre_reduced: false },
  { supply_profile_id: "interruption", label: "Concentrated interruption", base_profile_hash: "d".repeat(64), resolved_hash: "f".repeat(64), pre_reduced: false },
];
const STATES = WEATHER.flatMap((w) => SUPPLY.map((s) => ({ state_id: `${w.weather_scenario_id}|${s.supply_profile_id}`, weather_scenario_id: w.weather_scenario_id, supply_profile_id: s.supply_profile_id, resolved_supply_profile_hash: s.resolved_hash })));
const INST = (instance_id: string, category: string, targets: string[], capex: number, opex: number, extra: Record<string, unknown> = {}) => ({
  instance: { instance_id, type_id: `${category}-v1`, category, target_ids: targets, parameters: {}, prerequisites: [], mutually_exclusive_group: null, capex_pkr: capex, seasonal_opex_pkr: opex, procurement_delay_days: 7, lead_time_days: 14, shared: category === "shared_repair", evidence_ids: [] },
  category,
  eligible: true,
  reasons: [],
  commissioned_on: "2026-11-10",
  type_label: { leveling: "Laser leveling", pond: "Farm pond", shared_repair: "Lining repair", pump_supplement: "Pump top-up", timing: "Timing" }[category],
  in_library: true,
  ...extra,
});
const INTERVENTIONS = [
  INST(`${PILOT}:edge-02:repair`, "shared_repair", ["e-2"], 1_200_000, 15_000),
  INST(`${PILOT}:edge-01:repair`, "shared_repair", ["e-1"], 900_000, 10_000),
  ...FIELD_IDS.slice(0, 6).map((f) => INST(`${f}:leveling`, "leveling", [f], 85_000, 0)),
  ...FIELD_IDS.slice(20, 24).map((f) => INST(`${f}:pond-small`, "pond", [f], 420_000, 8_000)),
  INST(`${FIELD_IDS[25]}:pond-large`, "pond", [FIELD_IDS[25]], 780_000, 12_000, { eligible: false, reasons: ["Commissioning after planting date (2026-11-15)"] }),
  INST(`${PILOT}:pump-shared-1:topup`, "pump_supplement", ["pump-shared-1"], 0, 0),
];

/* -------------------------------------------------------------- runs */
type Kind = "B0" | "B1" | "P" | "R";
const BASE_YIELD = Object.fromEntries(FIELD_IDS.map((f, i) => [f, 3600 + ((i * 137) % 900) - (groupOf(f) === "tail" ? 650 : groupOf(f) === "middle" ? 250 : 0)]));
const GAIN: Record<Kind, number> = { B0: 0, B1: 160, P: 420, R: 300 };
function fieldYield(kind: Kind, f: string) {
  const g = groupOf(f);
  const r = rng(FIELD_IDS.indexOf(f) + 31)();
  let v = BASE_YIELD[f] + GAIN[kind] * (g === "tail" ? 1.4 : g === "middle" ? 1 : 0.6) * (0.6 + r * 0.8);
  if (kind === "P" && (f === FIELD_IDS[2] || f === FIELD_IDS[7])) v -= 140; // fixture: some fields worse off
  return Math.round(v);
}
const M = (run_id: string, definition_id: string, value: number | null, unit: string, field_id: string | null = null, status = "available", reason: string | null = null) => ({
  metric_id: `${run_id}:${definition_id}${field_id ? `:${field_id}` : ""}`,
  definition_id,
  run_id,
  value,
  unit,
  status,
  reason,
  evidence_ids: [],
  crop: "wheat",
  field_id,
});
function runFor(kind: Kind, revision: string) {
  const run_id = `run-${kind.toLowerCase()}-${revision.slice(-6)}`;
  const area = (f: string) => ((FIELDS.features.find((x) => x.id === f)!.properties as { gross_area_m2: number }).gross_area_m2) / 10000;
  const ys = FIELD_IDS.map((f) => fieldYield(kind, f));
  const prod = FIELD_IDS.reduce((a, f, i) => a + ys[i] * area(f), 0);
  const svc = (f: string) => {
    const g = groupOf(f);
    const base = g === "head" ? 0.86 : g === "middle" ? 0.68 : 0.47;
    return Math.min(1.05, base + (kind === "P" && g === "tail" ? 0.16 : kind === "R" && g === "tail" ? 0.12 : 0) + rng(FIELD_IDS.indexOf(f) + 5)() * 0.06);
  };
  const gw = { B0: 18200, B1: 14600, P: 11900, R: 13100 }[kind];
  const capex = { B0: 0, B1: 0, P: 1_455_000, R: 1_370_000 }[kind];
  const metrics = [
    M(run_id, "production_kg", Math.round(prod), "kg"),
    M(run_id, "tail_min_service", Math.min(...FIELD_IDS.filter((f) => groupOf(f) === "tail").map(svc)), "fraction"),
    M(run_id, "groundwater_m3", gw, "m3"),
    M(run_id, "withdrawal_productivity_kg_m3", Math.round((prod / (182000 + gw)) * 100) / 100, "kg/m3"),
    M(run_id, "capex_pkr", capex, "PKR"),
    M(run_id, "seasonal_opex_pkr", { B0: 118_300, B1: 94_900, P: 101_700, R: 108_400 }[kind], "PKR"),
    M(run_id, "fields_worse_off", kind === "P" ? 2 : 0, "count"),
    M(run_id, "source_withdrawal_m3", 182000, "m3"),
    M(run_id, "conveyance_loss_m3", kind === "P" ? 21000 : 31500, "m3"),
    M(run_id, "outlet_receipt_m3", kind === "P" ? 161000 : 150500, "m3"),
    M(run_id, "direct_application_m3", kind === "P" ? 139000 : 133000, "m3"),
    M(run_id, "pond_fill_m3", kind === "P" ? 22000 : 17500, "m3"),
    M(run_id, "pond_rain_m3", 900, "m3"),
    M(run_id, "pond_release_m3", kind === "P" ? 19800 : 15200, "m3"),
    M(run_id, "pond_loss_m3", 2400, "m3"),
    M(run_id, "pond_residual_m3", 700, "m3"),
    M(run_id, "gross_project_cost_pkr", capex, "PKR"),
    M(run_id, "public_grant_pkr", null, "PKR", null, "not_estimated", "No verified program eligibility record"),
    M(run_id, "participant_cash_pkr", capex, "PKR"),
    M(run_id, "crop_value_pkr", null, "PKR", null, "blocked", "No dated crop price supplied"),
    M(run_id, "basin_water_saving_m3", null, "m3", null, "not_estimated", "Return flows and basin boundary not modeled"),
    ...FIELD_IDS.flatMap((f, i) => [M(run_id, "yield_kg_ha", ys[i], "kg/ha", f), M(run_id, "production_kg", Math.round(ys[i] * area(f)), "kg", f), M(run_id, "field_service_ratio", Math.round(svc(f) * 1000) / 1000, "fraction", f), M(run_id, "groundwater_m3", Math.round(gw / 10), "m3", f)]),
  ];
  return {
    run: {
      contract_version: "2.0.0",
      run_id,
      scenario_revision_id: revision,
      scenario_hash: "9".repeat(64),
      candidate_library_hash: "8".repeat(64),
      plan_kind: kind,
      proof_scope: "finite_candidate_library",
      primary_objective: "production_kg",
      solve_wall_ms: { B0: 410, B1: 2380, P: 4120, R: 9800 }[kind],
      configurations: [],
      candidate_coverage_ref: null,
      warnings: kind === "P" ? ["DESIGN FIXTURE — synthetic results for UI review"] : [],
      created_at: "2026-10-10T03:00:00Z",
      outcome: "plan",
      solver_status: kind === "R" ? "FEASIBLE" : "OPTIMAL",
      objective_value: prod,
      objective_upper_bound: kind === "R" ? prod * 1.012 : prod,
      relative_gap: kind === "R" ? 0.012 : 0,
      selected_candidate_policy_ids: [],
      selected_intervention_instance_ids: kind === "P" ? [`${PILOT}:edge-02:repair`, `${FIELD_IDS[1]}:leveling`, `${FIELD_IDS[21]}:pond-small`] : kind === "R" ? [`${PILOT}:edge-02:repair`, `${FIELD_IDS[21]}:pond-small`] : [],
      shared_configuration_id: kind === "P" || kind === "R" ? "cfg-repair-e2" : "cfg-none",
      metric_refs: [],
      physical_validation: { status: "passed", abs_tolerance_m3: 1e-6, rel_tolerance: 1e-9, residuals: [] },
      trajectory_bundle_ref: "fixture",
      comparison_compatibility_key: "fixture-key",
    },
    metrics,
  };
}

function timeline(runId: string, fieldId: string | null) {
  const days = 170;
  const start = new Date("2026-11-15T12:00:00Z").getTime();
  const dates = Array.from({ length: days }, (_, i) => new Date(start + i * 864e5).toISOString().slice(0, 10));
  const r = rng(fieldId ? FIELD_IDS.indexOf(fieldId) + 99 : 1);
  const turns = new Set([4, 25, 46, 67, 88, 109, 130]);
  const rain = dates.map((_, i) => (r() < 0.07 ? Math.round(r() * 18 * 10) / 10 : 0));
  const permitted = dates.map((_, i) => (turns.has(i) ? 820 : 0));
  const actual = permitted.map((v, i) => (v ? Math.round(v * (runId.includes("-p-") ? 0.93 : 0.8)) : 0));
  const pondRelease = dates.map((_, i) => (runId.includes("-p-") && (i === 15 || i === 57 || i === 99) ? 310 : 0));
  const application = dates.map((_, i) => actual[i] * 0.85 + pondRelease[i]);
  const pumping = dates.map((_, i) => (i === 36 || i === 78 || i === 120 ? 260 : 0));
  const canopy = dates.map((_, i) => Math.round(Math.min(0.94, 0.02 + 0.92 / (1 + Math.exp(-(i - 55) / 11))) * (i > 140 ? 1 - (i - 140) / 60 : 1) * 1000) / 1000);
  const biomass = dates.map((_, i) => Math.round((12.5 / (1 + Math.exp(-(i - 95) / 16))) * 100) / 100);
  let sw = 160;
  const soil = dates.map((_, i) => {
    sw = Math.max(70, Math.min(190, sw - 1.9 - canopy[i] * 2.4 + rain[i] + application[i] / 60));
    return i === 61 || i === 62 ? null : Math.round(sw);
  });
  let inv = 600;
  const pond = dates.map((_, i) => {
    inv = Math.max(0, Math.min(1800, inv + (turns.has(i) ? 380 : 0) - pondRelease[i] - 3));
    return Math.round(inv);
  });
  const flows = (k: number) => dates.map((_, i) => (turns.has(i) || turns.has(i - 1) ? Math.round(9000 * k) : i % 3 === 0 ? Math.round(1200 * k) : 0));
  return {
    run_id: runId,
    field_id: fieldId,
    dates,
    series: [
      { series_id: "permitted_receipt_m3", label: "Permitted receipt", unit: "m3", kind: "water", values: permitted },
      { series_id: "canal_receipt_m3", label: "Actual canal receipt", unit: "m3", kind: "water", values: actual },
      { series_id: "field_application_m3", label: "Field application", unit: "m3", kind: "water", values: application },
      { series_id: "pumping_m3", label: "Pumping", unit: "m3", kind: "water", values: pumping },
      { series_id: "rain_mm", label: "Rain", unit: "mm", kind: "water", values: rain },
      { series_id: "pond_inventory_m3", label: "Pond inventory", unit: "m3", kind: "storage", values: pond },
      { series_id: "pond_release_m3", label: "Pond release", unit: "m3", kind: "storage", values: pondRelease },
      { series_id: "canopy_cover", label: "Canopy cover", unit: "fraction", kind: "crop", values: canopy },
      { series_id: "biomass_t_ha", label: "Biomass", unit: "t/ha", kind: "crop", values: biomass },
      { series_id: "soil_water_mm", label: "Root-zone soil water", unit: "mm", kind: "crop", values: soil },
    ],
    edges: [
      { edge_id: "e-1", values: flows(1) },
      { edge_id: "e-2", values: flows(0.55) },
      { edge_id: "e-3", values: flows(0.35) },
      { edge_id: "e-4", values: flows(0.3) },
      { edge_id: "e-5", values: flows(0.22) },
    ],
    ponds: [{ asset_id: "pond-existing-1", inventory_m3: pond, capacity_m3: 1800 }],
    markers: [
      { date: dates[0], label: "Planting", kind: "stage" },
      { date: dates[48], label: "Tillering", kind: "stage" },
      { date: dates[105], label: "Flowering", kind: "stage" },
    ],
    harvest: { date: dates[days - 1], yield_kg_ha: fieldId ? fieldYield(runId.includes("-p-") ? "P" : "B0", fieldId) : null },
  };
}

/* -------------------------------------------------------------- analyses */
function frontier(rev: string) {
  const budgets = [0, 500_000, 1_000_000, 2_000_000, 3_500_000, 5_000_000];
  const prods = [338000, 351500, 362800, 371900, 372400, 374100];
  return {
    analysis_id: "an-frontier-1",
    kind: "frontier",
    status: "succeeded",
    created_at: "2026-10-10T03:10:00Z",
    base_revision_id: rev,
    child_run_ids: budgets.map((_, i) => `run-fr-${i}`),
    points: [
      ...budgets.map((b, i) => ({ run_id: `run-fr-${i}`, setting: { capital_budget_pkr: b }, solver_status: i === 4 ? "FEASIBLE" : "OPTIMAL", capex_pkr: Math.min(b, [0, 420000, 990000, 1455000, 3100000, 2900000][i]), production_kg: prods[i], min_service_ratio: [0.47, 0.49, 0.6, 0.63, 0.63, 0.65][i], nondominated: i !== 4, relative_gap: i === 4 ? 0.02 : 0, executed_at: "2026-10-10T03:10:00Z" })),
      { run_id: "run-fr-x", setting: { capital_budget_pkr: 250_000, minimum_service_ratio: 0.7 }, solver_status: "INFEASIBLE", capex_pkr: null, production_kg: null, nondominated: false },
    ],
  };
}
function stress() {
  return {
    analysis_id: "an-stress-1",
    kind: "stress",
    mode: "fixed_plan",
    status: "succeeded",
    created_at: "2026-10-10T03:20:00Z",
    cells: STATES.map((s, i) => {
      const deliverable = !(s.supply_profile_id === "interruption" && s.weather_scenario_id !== "wet");
      return {
        ...s,
        deliverable,
        production_kg: deliverable ? [341000, 322500, 0, 368200, 349800, 0, 379000, 362100, 351700][i] : null,
        violations: deliverable ? [] : [{ rule: "receipt_right", entity_ids: ["window w-tail-06", "e-2"], at: "2027-01-12T05:00:00Z", detail: "Planned receipt exceeds curtailed window cap during interruption" }],
        run_id: `run-st-${i}`,
      };
    }),
    result: { worst_tested_production_kg: 322500 },
  };
}

/* -------------------------------------------------------------- router */
export interface FixtureOptions {
  pilots?: "two" | "none";
  failRuns?: boolean;
  solveOutcome?: "plan" | "infeasible";
  slowSolveMs?: number;
}

export async function installDesignFixture(page: Page, opts: FixtureOptions = {}) {
  const imagery = realImagery();
  const terrain = realTerrain();
  const canals = realCanals();
  let revSeq = 0;
  const revisions = new Map<string, Record<string, unknown>>();
  const jobs = new Map<string, { created: number; result: string; kind: string }>();
  const runs = new Map<string, ReturnType<typeof runFor>>();
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/assets/pilots/**", async (route) => {
    const url = new URL(route.request().url());
    const rel = url.pathname.replace(`/assets/pilots/${PILOT}/${VER}/`, "");
    if (rel === "fields.geojson") return json(route, FIELDS);
    if (rel === "canals.geojson") return json(route, canals);
    if (rel === "aoi.geojson") return json(route, { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[AOI[0], AOI[1]], [AOI[2], AOI[1]], [AOI[2], AOI[3]], [AOI[0], AOI[3]], [AOI[0], AOI[1]]]] } }] });
    if (imagery && rel.startsWith("imagery/")) return route.fulfill({ path: imagery.file, contentType: "image/webp" });
    if (terrain && rel === "terrain/dem.png") return route.fulfill({ path: terrain.file, contentType: "image/png" });
    return json(route, { code: "NOT_FOUND", detail: rel }, 404);
  });

  await page.route("**/api/v2/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname.replace("/api/v2", "");
    const method = req.method();
    const body = method === "POST" || method === "PATCH" ? (req.postDataJSON() as Record<string, unknown>) : null;

    if (p === "/health") return json(route, { status: "ok", contract_version: "2.0.0", schema_version: 3, versions: { fixture: FIXTURE } });
    if (p === "/capabilities")
      return json(route, {
        pilots: [],
        exact_science: true,
        surrogate_gate: "passed",
        chat: { key_configured: true, model: "fixture" },
        features: { copilot: { status: "not_available", reason: "Copilot is implemented last (M7); not in this build yet." } },
      });
    if (p === "/pilots")
      return json(route, {
        pilots:
          opts.pilots === "none"
            ? []
            : [
                { pilot_id: PILOT, pilot_version: VER, name: "Design fixture · Lower Chenab watercourse", state: "published", review_flags: { geography_reviewed: true, topology_structurally_valid: true, rights_verification: "assumed", cost_evidence: "referenced", crop_calibration: "uncalibrated" }, aoi_bbox: AOI, aoi_area_m2: 5607559, field_count: 30, imagery: [], versions: [VER] },
                { pilot_id: "fixture-b", pilot_version: VER, name: "Design fixture · second pilot", state: "published", review_flags: { geography_reviewed: false, topology_structurally_valid: true, rights_verification: "assumed", cost_evidence: "assumed", crop_calibration: "plausibility_checked" }, aoi_bbox: [72.2, 30.9, 72.22, 30.92], aoi_area_m2: 4.1e6, field_count: 30, imagery: [], versions: [VER] },
              ],
      });
    if (p === `/pilots/${PILOT}/versions/${VER}`)
      return json(route, {
        pilot_id: PILOT,
        pilot_version: VER,
        name: "Design fixture · Lower Chenab watercourse",
        geographic_name_basis: "DESIGN FIXTURE",
        aoi_bbox: AOI,
        aoi_area_m2: 5607559,
        metric_crs: "EPSG:32643",
        timezone: "Asia/Karachi",
        state: "published",
        review_flags: { geography_reviewed: true, topology_structurally_valid: true, rights_verification: "assumed", cost_evidence: "referenced", crop_calibration: "uncalibrated" },
        source_refs: ["ev-fixture-s2", "ev-fixture-net", "ev-fixture-cost"],
        imagery: [],
        package_sha256: "7".repeat(64),
        created_at: "2026-10-10T01:00:00Z",
        counts: { fields: 30 },
        seasons: [SEASON.season_id],
        manifest: null,
      });
    if (p === `/pilots/${PILOT}/versions/${VER}/map`)
      return json(route, {
        pilot_id: PILOT,
        pilot_version: VER,
        aoi_bbox: AOI,
        aoi_url: `/assets/pilots/${PILOT}/${VER}/aoi.geojson`,
        fields_url: `/assets/pilots/${PILOT}/${VER}/fields.geojson`,
        canals_url: `/assets/pilots/${PILOT}/${VER}/canals.geojson`,
        fields_raw_url: null,
        imagery: imagery ? [{ ...imagery, file: undefined }] : [],
        terrain: terrain ? { ...terrain, file: undefined } : null,
        network: { nodes: NODES, edges: EDGES },
        assets: ASSETS,
        field_groups: Object.fromEntries(FIELD_IDS.map((f) => [f, groupOf(f)])),
        legends: [],
      });
    if (p.startsWith("/fields/")) {
      const fid = decodeURIComponent(p.slice("/fields/".length));
      if (!FIELD_IDS.includes(fid)) return json(route, { code: "NOT_FOUND", detail: fid }, 404);
      const g = groupOf(fid);
      return json(route, {
        pilot_id: PILOT,
        pilot_version: VER,
        field: { field_id: fid, label: (FIELDS.features.find((f) => f.id === fid)!.properties as { label: string }).label, geometry_ref: fid, geometry_version: 2, gross_area_m2: (FIELDS.features.find((f) => f.id === fid)!.properties as { gross_area_m2: number }).gross_area_m2, gross_area_ha: 1, soil_profile_id: g === "tail" ? "sandy-loam" : "silt-loam", outlet_node_id: `o-${g === "middle" ? "mid" : g}`, group: g, source_model_ids: ["da-0012", "da-0013"], supersedes: [], evidence_ids: ["ev-fixture-s2"], existing_application_efficiency: 0.6 },
        soil: { soil_profile_id: "silt-loam", engine_soil_type: g === "tail" ? "SandyLoam" : "SiltLoam", archetype: g === "tail" ? "light" : "medium", initial_water: "FC", evidence_ids: [], limitations: [] },
        assets: ASSETS.filter((a) => a.field_ids.includes(fid)),
        roster_windows: { [SEASON.season_id]: [0, 1, 2].map((k) => ({ window_id: `w-${fid}-${k}`, field_id: fid, outlet_node_id: "o-head", start: `2026-11-${String(19 + k * 7).padStart(2, "0")}T05:00:00Z`, end: `2026-11-${String(19 + k * 7).padStart(2, "0")}T06:30:00Z`, basis: "time", rate_m3_s: 0.028, volume_cap_m3: null, accounting_boundary: "outlet", verification: "assumed", source_rule: "warabandi (fixture)" })) },
        route_edge_ids: g === "head" ? ["e-3"] : g === "middle" ? ["e-1", "e-4"] : ["e-1", "e-2", "e-5"],
        service_references: [{ field_id: fid, season_id: SEASON.season_id, reference_receipt_m3: 5200, basis: "time", evidence_ids: [] }],
        interventions: [],
        evidence_ids: ["ev-fixture-net"],
        geometry: null,
      });
    }
    if (p === "/seasons") return json(route, { seasons: [{ season: SEASON, library: { ready: true, library_hash: "8".repeat(64) }, roster_configured: true }, { season: COTTON, library: { ready: false }, roster_configured: true }] });
    if (p === "/weather-scenarios") return json(route, { weather_scenarios: WEATHER });
    if (p === "/uncertainty-sets") return json(route, { uncertainty_sets: [{ uncertainty_set_id: "release-9", pilot_id: PILOT, season_id: SEASON.season_id, states: STATES }], supply_profiles: SUPPLY });
    if (p === "/interventions") return json(route, { pilot_id: PILOT, pilot_version: VER, season_id: SEASON.season_id, decision_at: SEASON.decision_at, planting_date: SEASON.planting_date, interventions: INTERVENTIONS });
    if (p === "/scenarios" && method === "POST") {
      const id = `rev-${String(++revSeq).padStart(4, "0")}${FIXTURE.slice(0, 2)}`;
      const rev = { scenario_revision_id: id, scenario_id: "scn-1", parent_revision_id: null, request: body, semantic_hash: "6".repeat(64), candidate_library_hash: "8".repeat(64), created_at: new Date().toISOString(), readiness: { ready: true, blockers: [], warnings: ["Rights are assumed from a warabandi template (fixture)"], max_attainable_service: { head: 0.92, middle: 0.74, tail: 0.51 } } };
      revisions.set(id, rev);
      return json(route, { scenario_id: "scn-1", revision: rev }, 201);
    }
    if (/^\/scenarios\/[^/]+\/revisions$/.test(p) && method === "POST") {
      const id = `rev-${String(++revSeq).padStart(4, "0")}${FIXTURE.slice(0, 2)}`;
      const rev = { scenario_revision_id: id, scenario_id: "scn-1", parent_revision_id: body?.parent_revision_id, request: body?.changes, semantic_hash: "5".repeat(64), candidate_library_hash: "8".repeat(64), created_at: new Date().toISOString(), readiness: { ready: true, blockers: [], warnings: [], max_attainable_service: { head: 0.92, middle: 0.74, tail: 0.51 } } };
      revisions.set(id, rev);
      return json(route, { revision: rev }, 201);
    }
    const revM = p.match(/^\/scenario-revisions\/([^/]+)(\/solve)?$/);
    if (revM && !revM[2]) return revisions.has(revM[1]) ? json(route, revisions.get(revM[1])) : json(route, { code: "NOT_FOUND", detail: revM[1] }, 404);
    if (revM && revM[2] && method === "POST") {
      const kind = String(body?.plan_kind ?? "P") as Kind;
      const r = runFor(kind, revM[1]);
      if (opts.solveOutcome === "infeasible" && kind === "P") {
        (r as unknown as { run: Record<string, unknown> }).run = { ...r.run, outcome: "no_plan", solver_status: "INFEASIBLE", infeasibility_kind: "finite_candidate_incompatibility", diagnostics: { binding_group: "tail service floor 0.70 > attainable 0.51", candidate_coverage: "30/30 fields covered" } };
        r.metrics = [];
      }
      runs.set(r.run.run_id, r);
      const jid = `job-${kind}-${revM[1]}`;
      jobs.set(jid, { created: Date.now(), result: r.run.run_id, kind });
      return json(route, { job_id: jid }, 202);
    }
    const jobM = p.match(/^\/jobs\/([^/]+)(\/events|\/cancel)?$/);
    if (jobM) {
      if (jobM[2] === "/events") return route.fulfill({ status: 204, body: "" });
      const j = jobs.get(jobM[1]);
      if (!j) return json(route, { code: "NOT_FOUND", detail: jobM[1] }, 404);
      const dur = (opts.slowSolveMs ?? 1200) * ({ B0: 0.4, B1: 0.8, P: 1, R: 1.5 } as Record<string, number>)[j.kind];
      const done = Date.now() - j.created > dur;
      return json(route, { job_id: jobM[1], operation: "solve", request_hash: "x", state: done ? "succeeded" : "running", progress: done ? 1 : null, stage: done ? "Validated original-precision ledger" : "Solving finite candidate model (CP-SAT)", result_ref: done ? j.result : null, error: null, created_at: new Date(j.created).toISOString(), updated_at: new Date().toISOString() });
    }
    const runM = p.match(/^\/runs\/([^/]+)(\/timeline)?$/);
    if (runM) {
      if (opts.failRuns) return json(route, { code: "ASSET_UNAVAILABLE", detail: "Run bundle missing on disk" }, 503);
      const id = decodeURIComponent(runM[1]);
      if (runM[2]) return json(route, timeline(id, url.searchParams.get("field_id")));
      let r = runs.get(id);
      if (!r) {
        const k = (id.match(/^run-(b0|b1|p|r)-/)?.[1]?.toUpperCase() ?? "P") as Kind;
        r = runFor(k, `rev-${id.slice(-6)}`);
        r.run.run_id = id;
      }
      return json(route, r);
    }
    if (p === "/runs") return json(route, { runs: [] });
    if (p === "/comparisons" && method === "POST") {
      const ids = (body?.run_ids as string[]) ?? [];
      const [a, b] = ids.map((id) => runs.get(id) ?? runFor(((id.match(/^run-(b0|b1|p|r)-/)?.[1]?.toUpperCase() ?? "P") as Kind), "rev-x"));
      const deltas = [
        ...["production_kg", "tail_min_service", "groundwater_m3", "withdrawal_productivity_kg_m3", "capex_pkr", "seasonal_opex_pkr"].map((d) => {
          const x = a.metrics.find((m) => m.definition_id === d && !m.field_id)!;
          const y = b.metrics.find((m) => m.definition_id === d && !m.field_id)!;
          return { metric_id: d, definition_id: d, field_id: null, a: x.value, b: y.value, delta: (y.value ?? 0) - (x.value ?? 0), unit: x.unit, status: "available" };
        }),
        ...FIELD_IDS.map((f) => {
          const x = a.metrics.find((m) => m.definition_id === "yield_kg_ha" && m.field_id === f)!;
          const y = b.metrics.find((m) => m.definition_id === "yield_kg_ha" && m.field_id === f)!;
          return { metric_id: `yield_kg_ha:${f}`, definition_id: "yield_kg_ha", field_id: f, a: x.value, b: y.value, delta: (y.value ?? 0) - (x.value ?? 0), unit: "kg/ha", status: "available" };
        }),
      ];
      return json(route, { comparison_id: "cmp-1", compatible: true, compatibility_key: "fixture-key", certificate: { shared: ["weather_typical", "supply_nominal", "crop_profile", "initial_soil_and_pond_state", "cost_assumptions"], differences: ["plan_kind"] }, labels: {}, deltas });
    }
    if (p === "/analyses" && method === "GET") return json(route, { analyses: [frontier("rev-0001"), stress()] });
    if (p === "/analyses/an-frontier-1") return json(route, frontier("rev-0001"));
    if (p === "/analyses/an-stress-1") return json(route, stress());
    if (p.startsWith("/analyses/") && method === "POST") return json(route, { analysis_id: p.includes("frontier") ? "an-frontier-1" : p.includes("stress") ? "an-stress-1" : "an-other", job_id: null });
    if (p === "/surrogate/previews" && method === "POST") {
      const total = ((body?.schedule as { gross_depth_mm: number }[]) ?? []).reduce((s, e) => s + e.gross_depth_mm, 0);
      if (total > 600) return json(route, { preview_id: "pv-ood", estimated_yield_kg_ha: null, estimate_kind: "surrogate_preview", domain_status: "out_of_domain", domain_reasons: [`Seasonal gross irrigation ${total} mm exceeds the trained range (0–480 mm)`], model_version: "surrogate-wheat-fixture" });
      return json(route, { preview_id: "pv-1", estimated_yield_kg_ha: 3600 + total * 2.1, estimate_kind: "surrogate_preview", domain_status: "in_domain", domain_reasons: [], model_version: "surrogate-wheat-fixture", evaluation_reference: "eval-fixture", uncertainty_note: "Held-out normalized MAE 6.8% (design fixture value).", physical_precheck_status: "passed" });
    }
    if (p.startsWith("/evidence/search")) {
      return json(route, {
        query: url.searchParams.get("q") ?? "",
        results: [
          { doc_id: "ev-fixture-s2", kind: "observed_remote_sensing", pilot_id: PILOT, score: 1, snippet: "Sentinel-2 L2A scene used for the display image and field delineation (design fixture record).", source_url: null, title: "Sentinel-2 L2A scene (fixture)" },
          { doc_id: "ev-fixture-net", kind: "assumption", pilot_id: PILOT, score: 0.8, snippet: "Declared watercourse topology and delivery factors; assumed edges have no observed geometry.", source_url: null, title: "Declared operational network (fixture)" },
          { doc_id: "ev-fixture-cost", kind: "literature", pilot_id: PILOT, score: 0.6, snippet: "Reference costs for laser leveling, farm ponds and watercourse lining.", source_url: "https://example.org/fixture", title: "Intervention cost references (fixture)" },
        ],
      });
    }
    if (p.startsWith("/evidence/")) {
      const id = decodeURIComponent(p.slice("/evidence/".length));
      return json(route, {
        record: { evidence_id: id, source_title: `Fixture evidence record ${id}`, kind: id.includes("s2") ? "observed_remote_sensing" : id.includes("cost") ? "literature" : "assumption", verification_state: id.includes("s2") ? "artifact_checked" : "unchecked", source_url: null, source_asset_id: null, retrieved_at: "2026-10-09T10:00:00Z", source_period: "2024-12 – 2025-02", geographic_scope: "Fixture AOI", license_id: "CC-BY-4.0", raw_sha256: "4".repeat(64), transformation: "Reprojected to EPSG:3857; percentile stretch 2–98%", parent_evidence_ids: [], units: null, method_version: "fixture-1", limitations: ["DESIGN FIXTURE record for UI review", "Not a citable source"], assumption_range: null, allowed_use: "UI review only", reviewer: null, reviewed_at: null },
        document: null,
        pilot_ids: [PILOT],
      });
    }
    if (p === "/reports" && method === "POST") return json(route, { report_id: "rep-1", job_id: null }, 202);
    if (p === "/reports/rep-1") return json(route, { report_id: "rep-1", status: "succeeded", downloads: [{ kind: "html", url: "/api/v2/reports/rep-1/files/report.html", label: "HTML (print to PDF)" }, { kind: "csv", url: "/api/v2/reports/rep-1/files/schedule.csv", label: "CSV schedule" }, { kind: "json", url: "/api/v2/reports/rep-1/files/run.json", label: "Run metadata JSON" }] });
    return json(route, { code: "NOT_FOUND", detail: p }, 404);
  });
}

export const fixturePaths = { pilot: PILOT, version: VER, workspace: `/p/${PILOT}/${VER}/workspace`, fieldIds: FIELD_IDS, centroidOf };
