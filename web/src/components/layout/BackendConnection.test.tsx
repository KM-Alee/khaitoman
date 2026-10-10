import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

// Labelled network fixture: exercise the actual health hook through a blocked edge request.
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); });

test("failed remote request offers top-level login preserving the current page, then retry recovers", async () => {
  vi.stubEnv("VITE_BACKEND_ORIGIN", "https://api.example.com");
  vi.resetModules();
  const { BackendConnection } = await import("./BackendConnection");
  const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><BackendConnection /></QueryClientProvider>);
  const link = await screen.findByRole("link", { name: "Sign in to backend" });
  const url = new URL(link.getAttribute("href")!);
  expect(url.origin + url.pathname).toBe("https://api.example.com/api/v2/access/ready");
  expect(url.searchParams.get("return_to")).toBe(window.location.href);
  expect(link).not.toHaveAttribute("target");
  expect(fetcher).toHaveBeenCalledWith("https://api.example.com/api/v2/health", expect.objectContaining({ credentials: "include" }));
  fetcher.mockResolvedValue(new Response('{"status":"ok"}'));
  fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  client.clear();
});

test("same-origin local mode does not offer an edge login", async () => {
  vi.stubEnv("VITE_BACKEND_ORIGIN", "");
  vi.resetModules();
  const { BackendConnection } = await import("./BackendConnection");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><BackendConnection /></QueryClientProvider>);
  await waitFor(() => expect(client.getQueryState(["health"])?.status).toBe("error"));
  expect(screen.queryByRole("link", { name: "Sign in to backend" })).not.toBeInTheDocument();
  client.clear();
});

test("public remote mode offers retry without suggesting authentication", async () => {
  vi.stubEnv("VITE_BACKEND_ORIGIN", "https://api.example.com");
  vi.stubEnv("VITE_BACKEND_ACCESS_REQUIRED", "false");
  vi.resetModules();
  const { BackendConnection } = await import("./BackendConnection");
  const { ApiError, describeError } = await import("@/lib/api/client");
  const fetcher = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><BackendConnection /></QueryClientProvider>);
  const retry = await screen.findByRole("button", { name: "Retry connection" });
  expect(screen.queryByRole("link", { name: "Sign in to backend" })).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).not.toHaveTextContent(/sign in|approved email/i);
  expect(describeError(new ApiError(0, null, "offline")).detail).not.toMatch(/sign.in/i);
  fetcher.mockResolvedValue(new Response('{"status":"ok"}'));
  fireEvent.click(retry);
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  client.clear();
});
