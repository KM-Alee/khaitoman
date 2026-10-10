import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { formatDelta, formatWithUnit } from "@/lib/formatting";
import { ImpactScreen } from "./ImpactScreen";
import { SdgCards } from "./SdgCards";
import { plottedNumber, readCanonicalImpact } from "./sdgView";

vi.mock("@/components/charts/EChart", async () => {
  const actual = await vi.importActual<typeof import("@/components/charts/EChart")>("@/components/charts/EChart");
  return {
    ...actual,
    EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
  };
});

const TARGET_24 = "By 2030, ensure sustainable food production systems and implement resilient agricultural practices.";
const TARGET_64 = "6.4 By 2030, substantially increase water-use efficiency. 6.5 By 2030, implement integrated water resources management.";
const TARGET_131 = "Strengthen resilience and adaptive capacity to climate-related hazards and natural disasters in all countries.";
const NO_SCORE = "No arbitrary 0–100 SDG score is computed for this proxy.";
const BLOCKED = "at least one tested state is undeliverable for this plan";
const CO2_REASON = "CO₂ is not_estimated: the metric registry has no evidence-backed energy use, fuel/grid emission factor and system boundary.";

function metric(id: string, value: number | null, unit: string, status = "available", reason: string | null = null) {
  return {
    metric_id: id,
    definition_id: id,
    run_id: "run_plan",
    value,
    unit,
    status,
    reason,
    evidence_ids: ["ev_prod"],
    crop: "wheat",
    field_id: null,
  };
}

function term(role: string, label: string, value: number | null, unit: string, status = "available") {
  return {
    role,
    label,
    metric_id: label,
    definition_id: label,
    value,
    unit,
    status,
    run_id: "run_plan",
    reason: status === "available" ? null : "missing input",
    formula: `${label} formula`,
    evidence_ids: ["ev_prod"],
  };
}

function impactFixture() {
  return {
    available: true,
    run_id: "run_plan",
    baseline_run_id: "run_base",
    compatible: true,
    score: 42,
    cards: [
      {
        card: "SDG 2.4",
        official_target_text: TARGET_24,
        target_url: "https://sdgs.un.org/goals/goal2",
        official_indicator: false,
        interpretation: "Model-based planning resilience, not measured food security",
        status: "available",
        reason: null,
        formula: "worst_tested_production_kg / typical_production_kg",
        formulas: { sdg_2_4_production_retained_fraction: "worst / typical" },
        numerator: term("numerator", "Worst tested production", 900, "kg"),
        denominator: term("denominator", "Typical-state production", 1000, "kg"),
        difference_from_typical: null,
        metrics: ["sdg_2_4_production_retained_fraction"],
        values: [metric("sdg_2_4_production_retained_fraction", 0.5, "fraction")],
        limitations: [NO_SCORE, "Model-based planning resilience, not measured food security."],
        run_id: "run_plan",
        baseline_run_id: "run_base",
        run_ids: ["run_plan", "run_base"],
        source_records: ["ev_prod"],
        crop: "wheat",
        score: 77,
      },
      {
        card: "SDG 6.4/6.5",
        official_target_text: TARGET_64,
        target_url: "https://sdgs.un.org/goals/goal6",
        official_indicator: false,
        interpretation: "Water productivity/accounting/participation proxies, not official UN indicator scores",
        status: "available",
        reason: null,
        formula: "production_kg / (canal_source_withdrawal_m3 + groundwater_m3)",
        formulas: {},
        numerator: term("numerator", "Modeled crop production", 1000, "kg"),
        denominator: term("denominator", "Defined withdrawal", 123, "m3"),
        difference_from_typical: null,
        metrics: ["sdg_6_4_water_productivity_kg_m3"],
        values: [
          metric("sdg_6_4_water_productivity_kg_m3", 1.5, "kg/m3"),
          metric("canal_source_withdrawal_m3", 400, "m3"),
          metric("groundwater_m3", 100, "m3"),
          metric("sdg_6_4_groundwater_change_m3", 7, "m3"),
        ],
        limitations: [NO_SCORE],
        run_id: "run_plan",
        baseline_run_id: "run_base",
        run_ids: ["run_plan", "run_base"],
        source_records: ["ev_gw"],
        crop: "wheat",
      },
      {
        card: "SDG 13.1",
        official_target_text: TARGET_131,
        target_url: "https://sdgs.un.org/goals/goal13",
        official_indicator: false,
        interpretation: "Scenario robustness, not a quantified disaster-risk reduction",
        status: "blocked",
        reason: BLOCKED,
        formula: "min production in deliverable tested states",
        formulas: {},
        numerator: term("numerator", "Worst tested scenario outcome", 999, "kg", "blocked"),
        denominator: null,
        difference_from_typical: term("difference", "Difference from typical", null, "kg", "blocked"),
        metrics: ["sdg_13_1_worst_tested_production_kg"],
        values: [metric("sdg_13_1_worst_tested_production_kg", 999, "kg", "blocked", BLOCKED)],
        limitations: [NO_SCORE, "When a tested state is undeliverable the card is blocked."],
        run_id: "run_plan",
        baseline_run_id: null,
        run_ids: ["run_plan"],
        source_records: [],
        crop: "wheat",
      },
    ],
    distribution: [
      {
        field_id: "pilot:field-1",
        production_kg: 1000,
        baseline_production_kg: 800,
        delta_kg: 50,
        unit: "kg",
        status: "available",
        reason: null,
        run_id: "run_plan",
        baseline_run_id: "run_base",
        definition_id: "production_kg",
        crop: "wheat",
        causal: false,
      },
      {
        field_id: "pilot:field-2",
        production_kg: null,
        baseline_production_kg: null,
        delta_kg: null,
        unit: "kg",
        status: "not_estimated",
        reason: "stored field production is absent",
        run_id: "run_plan",
        definition_id: "production_kg",
        crop: "wheat",
        causal: false,
      },
    ],
    field_change_summary: {
      unit: "kg",
      quantum_kg: 0.1,
      fields_worse_off: 3,
      fields_better_off: 1,
      fields_unchanged: 0,
      fields_not_comparable: 2,
    },
    co2: {
      status: "not_estimated",
      value: 12,
      unit: "kg",
      reason: CO2_REASON,
      official_indicator: false,
    },
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderCards(impact: object) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SdgCards impact={impact} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderScreen(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/p/:pilotId/:version/:screen" element={<ImpactScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn(async () => json({ code: "NOT_FOUND", detail: "missing" }, 404)) as typeof fetch;
});

describe("canonical impact reading", () => {
  it("copies server terms and drops scores, blocked numbers and CO₂ values", () => {
    const view = readCanonicalImpact(impactFixture());
    expect(view.cards.map((card) => card.card)).toEqual(["SDG 2.4", "SDG 6.4/6.5", "SDG 13.1"]);
    expect(view.cards[1].denominator?.value).toBe(123);
    expect(view.cards[1].denominator?.unit).toBe("m3");
    expect(view.distribution[0].delta_kg).toBe(50);
    expect(view.field_change_summary.fields_worse_off).toBe(3);
    expect(view.cards[2].status).toBe("blocked");
    expect(view.cards[2].values[0].value).toBeNull();
    expect(view.co2.status).toBe("not_estimated");
    expect(view.co2.value).toBeNull();
    expect(view.co2.official_indicator).toBe(false);
    expect("score" in view).toBe(false);
    expect(plottedNumber("blocked", 999)).toBeNull();
    expect(plottedNumber("available", 50)).toBe(50);
  });

  it("keeps a missing expected card as missing instead of inventing target text", () => {
    const raw = impactFixture();
    raw.cards = raw.cards.filter((card) => card.card !== "SDG 2.4");
    const view = readCanonicalImpact(raw);
    expect(view.cards[0].missing).toBe(true);
    expect(view.cards[0].official_target_text).toBeNull();
    expect(view.cards[0].official_indicator).toBeNull();
  });
});

describe("SDG cards", () => {
  it("shows official target text, official_indicator false, units, limitations and blocked or missing rows", () => {
    renderCards(impactFixture());
    expect(screen.getAllByTestId("sdg-card")).toHaveLength(3);
    expect(screen.getByText(TARGET_24)).toBeInTheDocument();
    expect(screen.getByText(TARGET_64)).toBeInTheDocument();
    expect(screen.getByText(TARGET_131)).toBeInTheDocument();
    expect(screen.getAllByText("official_indicator = false").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByText(NO_SCORE)).toHaveLength(3);
    expect(screen.getByText("Unit fraction")).toBeInTheDocument();
    expect(screen.getAllByText("Unit kg").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unit m³").length).toBeGreaterThan(0);
    expect(screen.getByText("Unit kg/m³")).toBeInTheDocument();
    expect(screen.getByText(formatWithUnit(123, "m3"))).toBeInTheDocument();
    expect(screen.queryByText(formatWithUnit(500, "m3"))).not.toBeInTheDocument();
    expect(screen.getByText(formatWithUnit(7, "m3"))).toBeInTheDocument();
    const blocked = screen.getAllByTestId("sdg-card").find((card) => card.getAttribute("data-card") === "SDG 13.1")!;
    expect(blocked).toHaveAttribute("data-status", "blocked");
    expect(within(blocked).getAllByText(BLOCKED).length).toBeGreaterThan(0);
    expect(within(blocked).queryByText("999")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /UN target for SDG 2.4/ })).toHaveAttribute("href", "https://sdgs.un.org/goals/goal2");
    expect(screen.getByTestId("co2")).toHaveAttribute("data-status", "not_estimated");
    expect(screen.getByTestId("co2-status")).toHaveTextContent("Not estimated");
    expect(screen.getByText(CO2_REASON)).toBeInTheDocument();
    expect(screen.getByTestId("co2-value")).toHaveTextContent("No CO₂ value is shown.");
    expect(screen.queryByText("42")).not.toBeInTheDocument();
    expect(screen.queryByText("77")).not.toBeInTheDocument();
    expect(screen.queryByText("12")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sdg-score")).not.toBeInTheDocument();
    const summary = screen.getByTestId("field-change-summary");
    expect(within(summary).getByText("Worse off").nextElementSibling).toHaveTextContent("3");
    expect(within(summary).getByText("Not comparable").nextElementSibling).toHaveTextContent("2");
    expect(summary).toHaveTextContent("0.1 kg");
    const gaps = screen.getByTestId("distribution-gaps");
    expect(gaps).toHaveTextContent("field-2");
    expect(gaps).toHaveTextContent("Not estimated");
    expect(gaps).toHaveTextContent("stored field production is absent");
    expect(gaps).not.toHaveTextContent("0 kg");
    fireEvent.click(screen.getByRole("button", { name: "Show as table" }));
    expect(screen.getByText(formatDelta(50, "kg"))).toBeInTheDocument();
    expect(screen.queryByText(formatDelta(200, "kg"))).not.toBeInTheDocument();
  });

  it("states when a canonical card or its official target text is absent", () => {
    const raw = impactFixture();
    raw.cards = raw.cards.filter((card) => card.card !== "SDG 2.4");
    raw.cards[0].official_target_text = "";
    renderCards(raw);
    expect(screen.getByText("SDG 2.4 was not returned")).toBeInTheDocument();
    expect(screen.getByText("Official target text was not returned.")).toBeInTheDocument();
    expect(screen.getByText(/No proxy was estimated in the browser/)).toBeInTheDocument();
  });
});

describe("impact screen states", () => {
  it("shows an accessible empty state when no run is selected", () => {
    renderScreen("/p/pilot-a/v1/impact?tab=sdg");
    const empty = screen.getByTestId("impact-empty");
    expect(empty).toHaveTextContent("Impact needs a plan");
    expect(screen.getByRole("button", { name: "Go to Plan" })).toBeInTheDocument();
    expect(screen.queryByTestId("sdg-card")).not.toBeInTheDocument();
  });

  it("shows a loading status without metric numbers", async () => {
    let release: (response: Response) => void = () => {};
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/runs/run_plan")) return new Promise<Response>((resolve) => {
        release = resolve;
      });
      return json({ code: "NOT_FOUND", detail: url }, 404);
    }) as typeof fetch;
    renderScreen("/p/pilot-a/v1/impact?run=run_plan&tab=sdg");
    const loading = await screen.findByTestId("impact-loading");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading).toHaveAttribute("aria-label", "Impact loading");
    expect(loading).not.toHaveTextContent(/\d/);
    release(json({ run: { outcome: "plan", run_id: "run_plan", plan_kind: "P", solver_status: "OPTIMAL" }, metrics: [] }));
  });

  it("shows an error when the run request fails", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/runs/missing-run")) return json({ code: "NOT_FOUND", detail: "run missing-run is not stored" }, 404);
      return json({ code: "NOT_FOUND", detail: url }, 404);
    }) as typeof fetch;
    renderScreen("/p/pilot-a/v1/impact?run=missing-run&tab=sdg");
    expect(await screen.findByTestId("impact-error")).toHaveTextContent("Run unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("run missing-run is not stored");
  });

  it("shows infeasible runs without SDG numbers", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/runs/run_bad")) {
        return json({ run: { outcome: "no_plan", run_id: "run_bad", plan_kind: "P", solver_status: "INFEASIBLE" }, metrics: [] });
      }
      return json({ code: "NOT_FOUND", detail: url }, 404);
    }) as typeof fetch;
    renderScreen("/p/pilot-a/v1/impact?run=run_bad&tab=sdg");
    expect(await screen.findByTestId("impact-infeasible")).toHaveTextContent("No plan (INFEASIBLE)");
    expect(screen.queryByTestId("sdg-card")).not.toBeInTheDocument();
  });

  it("shows a missing impact payload and a blocked proxy from the impact response", async () => {
    const body = impactFixture();
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/impact")) return json({ available: false, reason: "stored metrics are missing", run_id: "run_plan" });
      if (url.includes("/runs/run_plan")) {
        return json({ run: { outcome: "plan", run_id: "run_plan", plan_kind: "P", solver_status: "OPTIMAL" }, metrics: [] });
      }
      return json({ code: "NOT_FOUND", detail: url }, 404);
    }) as typeof fetch;
    renderScreen("/p/pilot-a/v1/impact?run=run_plan&tab=sdg");
    expect(await screen.findByTestId("sdg-unavailable")).toHaveTextContent("stored metrics are missing");
    expect(screen.queryByText(body.cards[0].official_target_text)).not.toBeInTheDocument();
  });

  it("renders the impact response on the SDG tab", async () => {
    const body = impactFixture();
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/impact")) return json(body);
      if (url.includes("/runs/run_plan")) {
        return json({ run: { outcome: "plan", run_id: "run_plan", plan_kind: "P", solver_status: "OPTIMAL" }, metrics: [] });
      }
      return json({ code: "NOT_FOUND", detail: url }, 404);
    }) as typeof fetch;
    renderScreen("/p/pilot-a/v1/impact?run=run_plan&tab=sdg");
    expect(await screen.findByText(TARGET_24)).toBeInTheDocument();
    expect(screen.getByText(TARGET_131)).toBeInTheDocument();
    expect(screen.getAllByTestId("sdg-card")).toHaveLength(3);
    expect(screen.getByTestId("co2-status")).toHaveTextContent("Not estimated");
  });
});
