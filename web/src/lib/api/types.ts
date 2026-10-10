/**
 * Client view of the v2 contract.
 *
 * Domain entities mirror `api/aabflow/domain/schemas` (the frozen executable contract).
 * When `make contracts` publishes `src/generated/api.ts`, `schema-check.ts` asserts these
 * stay assignable to the generated OpenAPI types so drift breaks the build (T9.1).
 * Response envelopes that the API stream composes (map bundle, timeline, comparison,
 * analyses) are read through tolerant adapters in `adapters.ts`.
 */

export type Crop = "wheat" | "cotton";
export type PlanningMode = "historical_replay" | "season_response" | "capital_planning";
export type OptimizationMode = "typical" | "worst_case";
export type Objective = "production_kg" | "irrigation_contribution_pkr";
export type PlanKind = "B0" | "B1" | "P" | "R";
export type ActionCategory = "timing" | "leveling" | "pond" | "shared_repair" | "pump_supplement";
export type SolverStatus = "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN" | "MODEL_INVALID";
export type ErrorCode =
  | "INVALID_INPUT"
  | "NOT_FOUND"
  | "VERSION_CONFLICT"
  | "ASSET_UNAVAILABLE"
  | "PROVIDER_UNAVAILABLE"
  | "MODEL_INVALID"
  | "INVALID_PLAN"
  | "CANDIDATE_COVERAGE_LIMITED"
  | "IDEMPOTENCY_CONFLICT";

export interface ApiErrorBody {
  code: ErrorCode | string;
  detail: string;
  fields?: Record<string, string>;
}

export type PackageState = "acquired_raw" | "processed" | "needs_review" | "reviewed" | "validated" | "published";

export interface ReviewFlags {
  geography_reviewed: boolean;
  topology_structurally_valid: boolean;
  rights_verification: "assumed" | "configured" | "verified";
  cost_evidence: "assumed" | "referenced" | "quoted";
  crop_calibration: "uncalibrated" | "plausibility_checked" | "calibrated";
}

export interface ImageryRef {
  scene_id: string;
  collection: string;
  acquired_at: string;
  aoi_valid_fraction: number;
  display_image_ref: string;
  display_corners_wgs84: [number, number][];
  resolution_m: number;
  evidence_id: string;
}

export interface Pilot {
  pilot_id: string;
  pilot_version: string;
  name: string;
  geographic_name_basis: string;
  aoi_geojson_ref: string;
  aoi_bbox: [number, number, number, number];
  aoi_area_m2: number;
  metric_crs: string;
  timezone: string;
  state: PackageState;
  review_flags: ReviewFlags;
  source_refs: string[];
  imagery: ImageryRef[];
  package_sha256: string | null;
  created_at: string;
}

export interface PilotSummary {
  pilot_id: string;
  pilot_version: string;
  name: string;
  state?: PackageState;
  review_flags?: ReviewFlags;
  aoi_bbox?: [number, number, number, number];
  versions?: string[];
}

export interface FieldRecord {
  field_id: string;
  label: string;
  geometry_ref: string;
  geometry_version: number;
  gross_area_m2: number;
  gross_area_ha: number;
  soil_profile_id: string;
  outlet_node_id: string;
  group: "head" | "middle" | "tail";
  owner_ref: string | null;
  source_model_ids: string[];
  supersedes: string[];
  evidence_ids: string[];
  existing_application_efficiency: number;
}

export type NodeKind = "source" | "junction" | "outlet" | "pump";
export interface NetNode {
  node_id: string;
  kind: NodeKind;
  lon: number;
  lat: number;
  label: string | null;
}
export interface CapacityInterval {
  start: string;
  end: string;
  max_rate_m3_s: number;
}
export interface Edge {
  edge_id: string;
  upstream_node_id: string;
  downstream_node_id: string;
  geometry_ref: string | null;
  source_feature_ids: string[];
  delivery_factor: number;
  capacities: CapacityInterval[];
  closures: [string, string][];
  reach_label: string | null;
  evidence_ids: string[];
}
export interface RosterWindow {
  window_id: string;
  field_id: string;
  outlet_node_id: string;
  start: string;
  end: string;
  basis: "time" | "volume";
  rate_m3_s: number | null;
  volume_cap_m3: number | null;
  accounting_boundary: "outlet" | "field_inlet";
  verification: "assumed" | "configured" | "verified";
  source_rule: string;
}
export interface ServiceReference {
  field_id: string;
  season_id: string;
  reference_receipt_m3: number;
  basis: "time" | "volume";
  evidence_ids: string[];
}
export interface Asset {
  asset_id: string;
  kind: "pond" | "pump";
  existing: boolean;
  field_ids: string[];
  node_id: string | null;
  commissioned_at: string | null;
  usable_capacity_m3: number | null;
  surface_area_m2: number | null;
  footprint_m2: number | null;
  initial_inventory_m3: number;
  max_fill_m3_day: number | null;
  max_release_m3_day: number | null;
  seepage_m3_day: number;
  k_evap: number;
  rain_capture_fraction: number;
  max_rate_m3_h: number | null;
  seasonal_cap_m3: number | null;
  cost_per_m3_pkr: string | null;
  head_m: number | null;
  efficiency: number | null;
  quality_status: "unknown" | "acceptable" | "marginal" | "poor";
  annual_upkeep_pkr: number;
  evidence_ids: string[];
  /** Optional display position when the API supplies it. */
  lon?: number;
  lat?: number;
}
export interface InterventionInstance {
  instance_id: string;
  type_id: string;
  category: ActionCategory;
  target_ids: string[];
  parameters: Record<string, unknown>;
  prerequisites: string[];
  mutually_exclusive_group: string | null;
  capex_pkr: number;
  seasonal_opex_pkr: number;
  procurement_delay_days: number;
  lead_time_days: number;
  shared: boolean;
  evidence_ids: string[];
  /** Catalog annotations from GET /interventions (eligibility reasons, dates). */
  eligible?: boolean;
  eligibility_reasons?: string[];
  earliest_commissioning?: string | null;
  label?: string;
}

export interface SoilProfile {
  soil_profile_id: string;
  engine_soil_type: string;
  archetype: string;
  initial_water: string;
  evidence_ids: string[];
  limitations: string[];
}

export interface Season {
  season_id: string;
  crop: Crop;
  crop_profile_id: string;
  start: string;
  end: string;
  planning_modes: string[];
  library_ready?: boolean;
  label?: string;
}

export interface WeatherScenario {
  weather_scenario_id: string;
  season_id: string;
  label: string;
  analog_season_start: string;
  weather_series_id: string;
  date_mapping_ref: string | null;
  transformed_sha256: string;
  is_typical: boolean;
  selection_basis: string;
}

export interface SupplyProfile {
  supply_profile_id: string;
  label: string;
  base_profile_hash?: string;
  resolved_hash?: string;
  transformations?: unknown[];
}
export interface UncertaintyState {
  state_id: string;
  weather_scenario_id: string;
  supply_profile_id: string;
  resolved_supply_profile_hash: string;
}
export interface UncertaintySet {
  uncertainty_set_id: string;
  pilot_id: string;
  season_id: string;
  states: UncertaintyState[];
}

export type EvidenceKind =
  | "observed_remote_sensing"
  | "public_geography"
  | "gridded_reanalysis"
  | "literature"
  | "user_supplied"
  | "assumption"
  | "model_output"
  | "derived";
export type VerificationState = "unchecked" | "source_checked" | "artifact_checked" | "locally_reviewed";
export interface EvidenceRecord {
  evidence_id: string;
  source_title: string;
  kind: EvidenceKind;
  verification_state: VerificationState;
  source_url: string | null;
  source_asset_id: string | null;
  retrieved_at: string | null;
  source_period: string | null;
  geographic_scope: string | null;
  license_id: string | null;
  raw_sha256: string | null;
  transformation: string | null;
  parent_evidence_ids: string[];
  units: string | null;
  method_version: string | null;
  limitations: string[];
  assumption_range: { low: number; high: number; unit: string } | null;
  allowed_use: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
}

export type MetricStatus = "available" | "not_estimated" | "not_applicable" | "blocked";
export interface MetricValue {
  metric_id: string;
  definition_id: string;
  run_id: string;
  value: number | null;
  unit: string;
  status: MetricStatus;
  reason: string | null;
  evidence_ids: string[];
  crop: string | null;
  field_id: string | null;
  /** Optional registry annotations when the API embeds them. */
  label?: string;
  formula?: string;
}

export interface RuleResidual {
  rule: string;
  passed: boolean;
  max_violation: number;
  unit: string;
  entity_ids: string[];
  at: string | null;
  detail: string | null;
}
export interface PhysicalValidationReport {
  status: "passed" | "failed" | "not_run";
  abs_tolerance_m3: number;
  rel_tolerance: number;
  residuals: RuleResidual[];
}
export interface ConfigurationStatus {
  shared_configuration_id: string;
  status: SolverStatus;
  objective_value: number | null;
  upper_bound: number | null;
  wall_ms: number;
}

interface RunBase {
  contract_version: "2.0.0";
  run_id: string;
  scenario_revision_id: string;
  scenario_hash: string;
  candidate_library_hash: string;
  plan_kind: PlanKind;
  proof_scope: "finite_candidate_library";
  primary_objective: string;
  solve_wall_ms: number;
  configurations: ConfigurationStatus[];
  candidate_coverage_ref: string | null;
  warnings: string[];
  created_at: string;
  /** Inline metric values when the API embeds them alongside `metric_refs`. */
  metrics?: MetricValue[];
  /** Per-field policy summaries for plan runs (`{field_id: summary}`) when supplied. */
  selection?: Record<string, Record<string, unknown>> | null;
}
export interface PlanRun extends RunBase {
  outcome: "plan";
  solver_status: "OPTIMAL" | "FEASIBLE";
  objective_value: number;
  objective_upper_bound: number | null;
  relative_gap: number | null;
  selected_candidate_policy_ids: string[];
  selected_intervention_instance_ids: string[];
  shared_configuration_id: string;
  metric_refs: string[];
  physical_validation: PhysicalValidationReport;
  trajectory_bundle_ref: string;
  comparison_compatibility_key: string;
}
export type InfeasibilityKind =
  | "missing_input"
  | "empty_option_set"
  | "finite_candidate_incompatibility"
  | "bound_contradiction";
export interface NoPlanRun extends RunBase {
  outcome: "no_plan";
  solver_status: "INFEASIBLE" | "UNKNOWN" | "MODEL_INVALID";
  infeasibility_kind: InfeasibilityKind | null;
  diagnostics: Record<string, unknown>;
}
export interface InvalidPlanRun extends RunBase {
  outcome: "invalid_plan";
  solver_status: SolverStatus;
  physical_validation: PhysicalValidationReport;
  diagnostic_ref: string;
}
export type RunResult = PlanRun | NoPlanRun | InvalidPlanRun;

export type JobState =
  | "queued"
  | "running"
  | "waiting_for_review"
  | "succeeded"
  | "failed"
  | "cancel_requested"
  | "cancelled"
  | "interrupted";
export interface Job {
  job_id: string;
  operation: string;
  request_hash: string;
  state: JobState;
  progress: number | null;
  stage: string | null;
  result_ref: string | null;
  error: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
export interface JobEvent {
  event_id: number;
  job_id: string;
  created_at: string;
  type: "stage" | "progress" | "heartbeat" | "result" | "error" | "cancelled";
  payload: Record<string, unknown>;
}

export interface ScenarioRequest {
  contract_version: "2.0.0";
  pilot_id: string;
  pilot_version: string;
  season_id: string;
  planning_mode: PlanningMode;
  decision_at: string;
  weather_scenario_ids: string[];
  supply_profile_id: string;
  uniform_reduction_fraction: number;
  capital_budget_pkr: number;
  operating_budget_pkr: number;
  objective: Objective;
  optimization_mode: OptimizationMode;
  uncertainty_set_id: string | null;
  minimum_service_ratio: number | null;
  service_group: "all" | "head" | "middle" | "tail" | null;
  permit_groundwater: boolean;
  blocked_edge_ids: string[];
  allowed_intervention_instance_ids: string[] | null;
  forced_instance_ids: string[];
  excluded_instance_ids: string[];
  assumption_set_id: string;
}
export type RevisionChange = Partial<
  Pick<
    ScenarioRequest,
    | "capital_budget_pkr"
    | "operating_budget_pkr"
    | "supply_profile_id"
    | "uniform_reduction_fraction"
    | "weather_scenario_ids"
    | "minimum_service_ratio"
    | "service_group"
    | "allowed_intervention_instance_ids"
    | "forced_instance_ids"
    | "excluded_instance_ids"
    | "permit_groundwater"
    | "blocked_edge_ids"
    | "optimization_mode"
    | "uncertainty_set_id"
  >
>;
export interface ScenarioRevision {
  scenario_revision_id: string;
  scenario_id: string;
  parent_revision_id: string | null;
  request: ScenarioRequest;
  semantic_hash: string;
  candidate_library_hash: string | null;
  created_at: string;
  readiness?: { ready: boolean; blockers?: string[]; warnings?: string[] };
}

export interface Capabilities {
  pilots: unknown[];
  exact_science: boolean;
  surrogate_gate: string;
  chat: { key_configured: boolean; model?: string | null; available?: boolean; status?: string; reason?: string };
  features?: Record<string, string>;
  [k: string]: unknown;
}
export interface Health {
  status: string;
  contract_version: string;
  schema_version?: number | null;
  versions?: Record<string, string | null>;
  assets?: Record<string, unknown>;
}
