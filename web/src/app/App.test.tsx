import { render, screen } from "@testing-library/react";
import { App } from "./App";

function mockFetch(routes: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(routes).find((k) => url.startsWith(k));
    if (!key) return new Response(JSON.stringify({ code: "NOT_FOUND", detail: url }), { status: 404 });
    return new Response(JSON.stringify(routes[key]), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
}

test("landing explains that no pilot is published instead of inventing one", async () => {
  mockFetch({
    "/api/v2/pilots": { pilots: [] },
    "/api/v2/health": { status: "ok", contract_version: "2.0.0" },
    "/api/v2/capabilities": { pilots: [], exact_science: true, surrogate_gate: "not_run", chat: {}, features: {} },
  });
  render(<App />);
  expect(screen.getByRole("heading", { name: /test the season before you spend/i })).toBeInTheDocument();
  expect(await screen.findByText(/no pilot package is published yet/i)).toBeInTheDocument();
});

test("landing names an unreachable API", { timeout: 10000 }, async () => {
  globalThis.fetch = vi.fn(async () => {
    throw new TypeError("Failed to fetch");
  }) as typeof fetch;
  render(<App />);
  expect(await screen.findAllByText(/local api not reachable/i, {}, { timeout: 6000 })).not.toHaveLength(0);
});
