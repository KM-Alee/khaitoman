/**
 * TEST FIXTURES — labelled synthetic data for component tests only.
 * Never imported by application code; not analytical release data.
 */
import type { MetricValue, ReviewFlags, RunResult } from "@/lib/api/types";

export const FIXTURE_LABEL = "test-fixture";

export const flags: ReviewFlags = {
  geography_reviewed: true,
  topology_structurally_valid: true,
  rights_verification: "assumed",
  cost_evidence: "referenced",
  crop_calibration: "uncalibrated",
};

export function metric(p: Partial<MetricValue> & Pick<MetricValue, "definition_id">): MetricValue {
  return {
    metric_id: `${FIXTURE_LABEL}:${p.definition_id}${p.field_id ? `:${p.field_id}` : ""}`,
    run_id: "fixture-run",
    value: 1,
    unit: "kg",
    status: "available",
    reason: null,
    evidence_ids: [],
    crop: "wheat",
    field_id: null,
    ...p,
  };
}

export function planRun(p: Partial<RunResult> = {}): RunResult {
  return {
    contract_version: "2.0.0",
    run_id: "fixture-run",
    scenario_revision_id: "fixture-rev",
    scenario_hash: "0".repeat(64),
    candidate_library_hash: "1".repeat(64),
    plan_kind: "P",
    proof_scope: "finite_candidate_library",
    primary_objective: "production_kg",
    solve_wall_ms: 1234,
    configurations: [],
    candidate_coverage_ref: null,
    warnings: [],
    created_at: "2026-10-10T00:00:00Z",
    outcome: "plan",
    solver_status: "OPTIMAL",
    objective_value: 100,
    objective_upper_bound: 100,
    relative_gap: 0,
    selected_candidate_policy_ids: [],
    selected_intervention_instance_ids: [],
    shared_configuration_id: "cfg",
    metric_refs: [],
    physical_validation: { status: "passed", abs_tolerance_m3: 1e-6, rel_tolerance: 1e-9, residuals: [] },
    trajectory_bundle_ref: "t",
    comparison_compatibility_key: "k",
    metrics: [],
    ...p,
  } as RunResult;
}
