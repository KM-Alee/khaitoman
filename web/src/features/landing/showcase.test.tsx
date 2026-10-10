/**
 * Landing showcase (W1 headline, W2 AI strip, W5 Ask box). Every headline/AI-stack object here
 * is a labelled TEST FIXTURE; the numbers are invented and the components only format them.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import type { ReactNode } from "react";
import type { AiStack, DemoHeadline } from "@/lib/api/showcase";
import { useUI } from "@/app/store";
import { AiStackStrip } from "@/components/layout/AiStackStrip";
import { HeadlineInsight, HeadlineSentence } from "./HeadlineInsight";
import { AskBox } from "./AskBox";

const fig = (value: number | null, unit: string, run_ids = ["run_fx_p"]) => ({ value, unit, run_ids, reason: value === null ? "fixture missing" : null });
const plan = (id: string, prod: number, tail: number, cap: number, gw: number) => ({
  run_id: id,
  production_kg: fig(prod, "kg", [id]),
  tail_min_service_ratio: fig(tail, "ratio", [id]),
  capital_commitment_pkr: fig(cap, "PKR", [id]),
  groundwater_m3: fig(gw, "m3", [id]),
});

/** TEST FIXTURE headline. */
function headline(story: DemoHeadline["story"]): DemoHeadline {
  return {
    story,
    pilot_id: "pilot-fx",
    pilot_version: "v1",
    season_id: "wheat-rabi-fx",
    scenario_revision_id: "rev_fx",
    plans: { B0: plan("run_fx_b0", 100000, 0.6, 0, 0), B1: plan("run_fx_b1", 108300, 0.44, 0, 10), P: plan("run_fx_p", 118800, 0.61, 650, 20) },
    capital_budget_pkr: fig(1000, "PKR"),
    production_gain_pct_vs_b0: { B1: fig(8.3, "%"), P: fig(18.8, "%") },
    tail_service_change_pts: { B1: fig(-16.0, "pct_points"), P: fig(1.0, "pct_points") },
    budget_used_fraction: fig(0.65, "fraction"),
    groundwater_above_b0: true,
    run_created_at: { run_fx_b0: "2026-10-10T08:00:00Z", run_fx_b1: "2026-10-10T08:00:00Z", run_fx_p: "2026-10-10T08:00:00Z" },
  } as DemoHeadline;
}

function wrap(children: ReactNode, data: { headline?: DemoHeadline; stack?: AiStack } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (data.headline) qc.setQueryData(["demo-headline"], data.headline);
  if (data.stack) qc.setQueryData(["ai-stack"], data.stack);
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={children} />
          <Route path="/p/:pilot/:version/:screen" element={<div data-testid="pilot-route" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("headline story", () => {
  it.each([
    ["tail_tradeoff", "Optimising only what exists grew 8.3% more wheat but cut the worst-off tail field from 60% to 44% of its water."],
    ["budget_efficiency", "while spending only 65% of the"],
    ["plain_gain", "AabFlow's plan grows +18.8% more wheat than today's routine, using 65% of the budget."],
  ] as const)("%s uses the server figures", (story, text) => {
    wrap(<HeadlineSentence h={headline(story)} />);
    expect(document.querySelector(`[data-story="${story}"]`)?.textContent).toContain(text);
  });

  it("renders tiles, run badges and the honest groundwater line", () => {
    wrap(<HeadlineInsight onSeeHow={() => undefined} />, { headline: headline("tail_tradeoff") });
    expect(screen.getByTestId("headline-tiles").textContent).toContain("118.8 t");
    expect(screen.getByTestId("headline-runs").textContent).toContain("Saved result");
    expect(screen.getByTestId("headline-groundwater")).toBeInTheDocument();
  });
});

describe("AI stack strip", () => {
  it("shows facts and the server's reason for an unavailable engine, never a number", () => {
    const stack = {
      engines: [
        { id: "sees", label: "Sees", plain: "p", fact: "931 possible fields found; 30 kept after review", fact_value: 931, unit: "count", facts: [], by_pilot: {}, evidence_ref: "x", status: "available", reason: null },
        { id: "predicts", label: "Predicts", plain: "p", fact: null, fact_value: null, unit: null, facts: [], by_pilot: {}, evidence_ref: null, status: "unavailable", reason: "no trained surrogate evaluation on disk" },
      ],
    } as unknown as AiStack;
    wrap(<AiStackStrip />, { stack, headline: headline("plain_gain") });
    expect(screen.getByTestId("ai-fact-sees").textContent).toBe("931");
    expect(screen.queryByTestId("ai-fact-predicts")).toBeNull();
    expect(screen.getByText("no trained surrogate evaluation on disk")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ai-link-sees"));
    expect(useUI.getState().showRawFields).toBe(true);
    expect(screen.getByTestId("pilot-route")).toBeInTheDocument();
  });
});

describe("Ask box", () => {
  it("hands a chip question to the assistant and opens the saved plan", () => {
    useUI.getState().set({ assistantOpen: false, assistantDraft: null });
    wrap(<AskBox />, { headline: headline("plain_gain") });
    fireEvent.click(screen.getAllByTestId("ask-chip")[2]);
    const st = useUI.getState();
    expect(st.assistantOpen).toBe(true);
    expect(st.assistantDraft).toEqual({ text: "اگر نہر دو ہفتے بند رہے تو کیا ہوگا؟", autoSend: true });
    expect(screen.getByTestId("pilot-route")).toBeInTheDocument();
  });
});
