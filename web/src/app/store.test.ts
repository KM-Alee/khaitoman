import { draftChanges, draftsEqual, needsNewScenario, type ScenarioDraft } from "./store";

const base: ScenarioDraft = {
  season_id: "wheat-rabi-2026-27",
  planning_mode: "season_response",
  decision_at: "2026-11-01T00:00:00+05:00",
  weather_scenario_ids: ["typical"],
  supply_profile_id: "nominal",
  uniform_reduction_fraction: 0,
  capital_budget_pkr: 1_500_000,
  operating_budget_pkr: 250_000,
  objective: "production_kg",
  optimization_mode: "typical",
  uncertainty_set_id: null,
  minimum_service_ratio: null,
  service_group: null,
  permit_groundwater: true,
  forced_instance_ids: [],
  excluded_instance_ids: [],
};

test("draft equality ignores list order but sees every changed input", () => {
  expect(draftsEqual(base, { ...base })).toBe(true);
  expect(draftsEqual({ ...base, forced_instance_ids: ["a", "b"] }, { ...base, forced_instance_ids: ["b", "a"] })).toBe(true);
  expect(draftsEqual(base, { ...base, capital_budget_pkr: 1_550_000 })).toBe(false);
  expect(draftsEqual(base, { ...base, uniform_reduction_fraction: 0.22 })).toBe(false);
});

test("derived revisions carry only the typed changes", () => {
  const d = { ...base, capital_budget_pkr: 0, uniform_reduction_fraction: 0.22 };
  expect(draftChanges(base, d)).toEqual({ capital_budget_pkr: 0, uniform_reduction_fraction: 0.22 });
  expect(draftChanges(base, base)).toEqual({});
});

test("season, mode, decision date or objective changes require a new scenario", () => {
  expect(needsNewScenario(base, { ...base, capital_budget_pkr: 0 })).toBe(false);
  expect(needsNewScenario(base, { ...base, season_id: "cotton-kharif-2027" })).toBe(true);
  expect(needsNewScenario(base, { ...base, objective: "irrigation_contribution_pkr" })).toBe(true);
});
