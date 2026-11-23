import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportScreen } from "./ReportScreen";

// Labelled API fixture: verify the real report hook and rendered canonical response.
const fixtureRun = {
  run_id: "run_fixture_report", plan_kind: "P", outcome: "diagnostic", solver_status: "INFEASIBLE",
  scenario_revision_id: "rev_fixture", scenario_hash: "fixture", candidate_library_hash: "fixture",
  created_at: "2026-10-10T00:00:00Z", warnings: [],
};
vi.mock("@/app/pilotData", () => ({ usePilotData: () => ({
  sel: { runId: "run_fixture_report", pilotId: "pilot-fixture", version: "fixture-v1", pilotKey: "fixture", hrefFor: () => "#", go: vi.fn() },
  pilot: { data: { pilot: { name: "Report test fixture" } } }, fieldIndex: new Map(),
}) }));
vi.mock("@/app/selection", () => ({ useSelection: () => ({ runId: "run_fixture_report" }) }));
vi.mock("@/features/workspace/useRunContext", () => ({ useRunContext: () => ({ request: {} }) }));
vi.mock("@/features/workspace/useScenario", () => ({
  useScenario: () => ({ catalog: { seasons: { data: [] } } }), PLAN_LABEL: { P: "Integrated plan" },
}));
vi.mock("@/features/compare/useLadder", () => ({ useLadderRuns: () => ({ ids: ["run_fixture_report"], byKind: new Map() }) }));
vi.mock("@/lib/api/queries", async () => ({
  ...await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries"),
  useRun: () => ({ data: fixtureRun }), useRunActionPlan: () => ({ data: { available: false, reason: "Diagnostic fixture" } }),
}));

it("exports a supported report type and renders the API download_url", async () => {
  let posted: Record<string, unknown> | undefined;
  globalThis.fetch = vi.fn(async (_url, options) => {
    if (options?.method === "POST") {
      posted = JSON.parse(String(options.body));
      if (!["one_page_plan", "full_report"].includes(String(posted?.report_type))) {
        return new Response(JSON.stringify({ detail: "unsupported report type" }), { status: 422 });
      }
      return new Response(JSON.stringify({ report_id: "rpt_fixture", job_id: "job_fixture" }), { status: 202 });
    }
    return new Response(JSON.stringify({
      report_id: "rpt_fixture", status: "succeeded", job_state: "succeeded",
      download_url: "/api/v2/reports/rpt_fixture/files/report.html", final_self_contained_report: true,
    }));
  }) as typeof fetch;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><ReportScreen /></MemoryRouter></QueryClientProvider>);
  fireEvent.click(screen.getByTestId("export-report"));
  const link = await screen.findByRole("link", { name: "Download report HTML" });
  expect(posted).toEqual({ contract_version: "2.0.0", run_ids: ["run_fixture_report"], report_type: "one_page_plan" });
  expect(link).toHaveAttribute("href", "/api/v2/reports/rpt_fixture/files/report.html");
  expect(link).toHaveAttribute("download");
});
