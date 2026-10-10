import { afterEach, expect, test, vi } from "vitest";
import { parseBackendOrigin } from "./urls";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

test("local default and validated remote origin", () => {
  expect(parseBackendOrigin(undefined)).toBe("");
  expect(parseBackendOrigin(" https://api.example.com/ ")).toBe("https://api.example.com");
  expect(parseBackendOrigin("http://127.0.0.1:8010")).toBe("http://127.0.0.1:8010");
  for (const invalid of ["http://remote.example", "https://api.example.com/api/v2", "https://user:secret@example.com", "https://api.example.com?token=x"]) {
    expect(() => parseBackendOrigin(invalid)).toThrow();
  }
});

test("split origin resolves API, assets, report links and SSE bases", async () => {
  vi.stubEnv("VITE_BACKEND_ORIGIN", "https://api.example.com");
  vi.resetModules();
  const u = await import("./urls");
  const { assetUrl } = await import("./adapters");
  expect(u.API_BASE).toBe("https://api.example.com/api/v2");
  expect(u.apiRequestUrl("/health")).toBe("https://api.example.com/api/v2/health");
  expect(u.apiRequestUrl("/api/v2/health")).toBe("https://api.example.com/api/v2/health");
  expect(u.apiRequestUrl("/assets/pilots/x/y/z.png")).toBe("https://api.example.com/assets/pilots/x/y/z.png");
  expect(u.backendUrl("/api/v2/reports/r/files/report.html")).toBe("https://api.example.com/api/v2/reports/r/files/report.html");
  expect(assetUrl("x", "y", "imagery/z.png")).toBe("https://api.example.com/assets/pilots/x/y/imagery/z.png");
  expect(u.backendUrl("https://external.example/tiles")).toBe("https://external.example/tiles");
  expect(u.backendMapRequest("/assets/dem.png")).toEqual({ url: "https://api.example.com/assets/dem.png", credentials: "include" });
  expect(u.backendCredentials("https://api.example.com.evil/tiles")).toBe("same-origin");
  const fetcher = vi.fn().mockResolvedValue(new Response('{"status":"ok"}'));
  vi.stubGlobal("fetch", fetcher);
  const { request } = await import("./client");
  await request("/health");
  expect(fetcher).toHaveBeenCalledWith("https://api.example.com/api/v2/health", expect.objectContaining({ credentials: "include" }));
  vi.unstubAllGlobals();
});
