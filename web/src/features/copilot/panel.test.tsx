import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { useUI } from "@/app/store";
import { AnswerView } from "./blocks";
import { CopilotPanel } from "./CopilotPanel";
import { __resetConversations } from "./conversation";
import { SMOKE, smokeEvents } from "./__fixtures__/smoke";
import { suggestQuestions } from "./suggestions";

vi.mock("@/components/charts/EChart", async () => {
  const actual = await vi.importActual<typeof import("@/components/charts/EChart")>("@/components/charts/EChart");
  return { ...actual, EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} data-testid="echart" /> };
});

const RUN = "run_c1251d888e0045fc88e80f05b20158f0";

function Probe() {
  const l = useLocation();
  return <output data-testid="location">{l.pathname + l.search}</output>;
}

function wrap(ui: React.ReactNode, url = `/p/pilot-a/reviewed-v1/workspace?run=${RUN}`) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/p/:pilotId/:version/:screen"
            element={
              <>
                {ui}
                <Probe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Handler = (url: string, init?: RequestInit) => unknown;
function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [k, h] of Object.entries(routes)) {
      if (url.includes(k)) {
        const body = h(url, init);
        if (body instanceof Response) return body;
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }
    }
    return new Response(JSON.stringify({ code: "NOT_FOUND", detail: url }), { status: 404 });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  __resetConversations();
  sessionStorage.clear();
  useUI.setState({ assistantHighlight: null });
  vi.stubGlobal("EventSource", undefined);
});
afterEach(() => vi.unstubAllGlobals());

test("a real answer renders its headline, run badge, metric cards, charts, caveats and follow-ups", () => {
  mockFetch({});
  const onAsk = vi.fn();
  wrap(<AnswerView blocks={SMOKE.turns.S1.answer.blocks} ctx={{ lang: "en", onAsk }} />);
  expect(screen.getByTestId("copilot-headline")).toHaveTextContent(/integrated plan/i);
  const badge = screen.getByTestId("copilot-run-badge");
  expect(badge).toHaveAttribute("data-run-id", RUN);
  expect(screen.getAllByTestId("copilot-metric")).toHaveLength(2);
  expect(screen.getAllByTestId("copilot-visual").map((v) => v.dataset.chart)).toEqual(["bar", "steps"]);
  expect(screen.getByTestId("copilot-caveats")).toHaveTextContent(/uncalibrated/i);
  const chips = within(screen.getByTestId("copilot-followups")).getAllByRole("button");
  fireEvent.click(chips[0]);
  expect(onAsk).toHaveBeenCalledWith(SMOKE.turns.S1.answer.blocks.find((b) => b.type === "follow_ups")!.questions[0]);
  fireEvent.click(badge);
  expect(screen.getByTestId("location")).toHaveTextContent(`run=${RUN}`);
});

test("every visual has a data twin with the served rows", () => {
  mockFetch({});
  wrap(<AnswerView blocks={SMOKE.turns.S7.answer.blocks} ctx={{ lang: "en" }} />);
  const sankey = screen.getAllByTestId("copilot-visual").find((v) => v.dataset.chart === "sankey")!;
  fireEvent.click(within(sankey).getByRole("radio", { name: /data/i }));
  const rows = within(sankey).getByTestId("copilot-visual-table").querySelectorAll("tbody tr");
  const served = SMOKE.turns.S7.answer.blocks.find((b) => b.type === "visual" && b.chart === "sankey");
  expect(rows).toHaveLength(served && served.type === "visual" ? served.rows.length : -1);
});

test("Show on map highlights the answer's fields and opens the Plan map", () => {
  mockFetch({});
  wrap(<AnswerView blocks={SMOKE.turns.S4.answer.blocks} ctx={{ lang: "en" }} />, `/p/pilot-a/reviewed-v1/compare?run=${RUN}`);
  const map = screen.getAllByTestId("copilot-visual").find((v) => v.dataset.chart === "map")!;
  fireEvent.click(within(map).getByTestId("copilot-show-on-map"));
  const v = SMOKE.turns.S4.answer.blocks.find((b) => b.type === "visual" && b.chart === "map");
  expect(useUI.getState().assistantHighlight).toEqual(v && v.type === "visual" ? v.highlight_ids : null);
  expect(screen.getByTestId("location")).toHaveTextContent("/workspace");
});

test("an Urdu answer renders right-to-left with Urdu fonts", () => {
  mockFetch({});
  wrap(<AnswerView blocks={SMOKE.turns.S5.answer.blocks} ctx={{ lang: "ur" }} />);
  const answer = screen.getByTestId("copilot-answer");
  expect(answer).toHaveAttribute("lang", "ur");
  expect(answer).toHaveAttribute("dir", "rtl");
});

test("without a key the panel says the assistant is offline and keeps the deterministic view", async () => {
  mockFetch({
    "/copilot/status": () => ({ configured: false, state: "unavailable", reason: "No hosted-model key is configured.", model: "gpt-6-luna", prompt_version: "p", tool_schema_version: "t", offline_note: "Saved results work offline." }),
  });
  wrap(<CopilotPanel />);
  expect(await screen.findByText("The assistant is offline")).toBeInTheDocument();
  expect(screen.getByTestId("copilot-unavailable")).toHaveTextContent("No hosted-model key is configured.");
  expect(screen.queryByTestId("copilot-input")).toBeNull();
});

test("asking a suggested question streams progress and renders the answer", async () => {
  const evs = smokeEvents("S7");
  let polled = 0;
  const calls: string[] = [];
  mockFetch({
    "/copilot/status": () => ({ configured: true, state: "ready", model: "gpt-6-luna", prompt_version: "p", tool_schema_version: "t", offline_note: "" }),
    "/copilot/sessions?limit": () => ({ sessions: [] }),
    "/messages": (_u, init) => {
      calls.push(String(init?.body));
      return { turn_id: "turn_s7", session_id: "cps_1", context: { pilot_id: "pilot-a", pilot_version: "reviewed-v1" }, events_url: "/api/v2/copilot/turns/turn_s7/events" };
    },
    "/copilot/sessions": () => ({ session_id: "cps_1", role: "planner", status: {} }),
    "/event-log": (u) => {
      const after = Number(new URL(u, "http://x").searchParams.get("after"));
      polled += 1;
      return evs.filter((e) => e.event_id > after).slice(0, polled === 1 ? 3 : 100);
    },
    "/copilot/turns/turn_s7": () => ({ ...SMOKE.turns.S7, turn_id: "turn_s7", session_id: "cps_1", seq: 1, user_message: SMOKE.turns.S7.message, context: {}, created_at: "", view_intents: [], job_ids: [], request_ids: [] }),
  });
  wrap(<CopilotPanel />);
  const suggestion = await screen.findAllByTestId("copilot-suggestion");
  expect(suggestion.length).toBeGreaterThanOrEqual(4);
  fireEvent.change(screen.getByTestId("copilot-input"), { target: { value: SMOKE.turns.S7.message } });
  fireEvent.click(screen.getByTestId("copilot-send"));
  expect(await screen.findByTestId("copilot-question")).toHaveTextContent(SMOKE.turns.S7.message);
  await waitFor(() => expect(screen.getAllByTestId("copilot-visual").length).toBe(2), { timeout: 6000 });
  const sent = JSON.parse(calls[0]);
  expect(sent.context).toMatchObject({ pilot_id: "pilot-a", pilot_version: "reviewed-v1", selected_run_id: RUN, view: "workspace" });
  expect(screen.getByTestId("copilot-turn")).toHaveAttribute("data-status", "completed");
});

test("suggestions follow the screen and keep an Urdu example", () => {
  const s = suggestQuestions({ screen: "explore", hasRun: true, fieldLabel: "A-010" });
  expect(s).toHaveLength(6);
  expect(s[0].text).toContain("A-010");
  expect(s.some((x) => /robust/i.test(x.text))).toBe(true);
  expect(s[s.length - 1].lang).toBe("ur");
  expect(s.every((x) => !/\d{3,}/.test(x.text.replace("A-010", "")))).toBe(true);
});
