/**
 * The guided tour's data: GET /api/v2/demo/session (written by `make demo-seed`). It names
 * real, previously executed runs and analyses; the tour opens them through the ordinary
 * run/analysis endpoints like any shared link. A 404 means no session has been seeded.
 */
import { useQuery } from "@tanstack/react-query";
import type { components } from "@/generated/api";
import { ApiError, api } from "@/lib/api/client";

export type DemoSession = components["schemas"]["DemoSession"];

export type DemoSessionState =
  | { kind: "loading" }
  | { kind: "missing"; detail: string }
  | { kind: "incomplete"; session: DemoSession }
  | { kind: "ready"; session: DemoSession }
  | { kind: "error"; error: unknown };

export function useDemoSession(enabled = true): DemoSessionState {
  const q = useQuery({
    queryKey: ["demo-session"],
    enabled,
    queryFn: ({ signal }) => api.get<DemoSession>("/demo/session", signal),
    staleTime: 60_000,
    retry: (n, e) => !(e instanceof ApiError && e.isNotFound) && n < 1,
  });
  if (q.isLoading) return { kind: "loading" };
  if (q.error) {
    if (q.error instanceof ApiError && q.error.isNotFound) return { kind: "missing", detail: q.error.message };
    return { kind: "error", error: q.error };
  }
  if (!q.data) return { kind: "loading" };
  return q.data.complete ? { kind: "ready", session: q.data } : { kind: "incomplete", session: q.data };
}

/** Server-recorded creation time of a run named in the manifest (for "computed <time>"). */
export function computedAt(s: DemoSession, runId: string | null | undefined): string | null {
  if (!runId) return null;
  return s.run_details?.[runId]?.created_at ?? null;
}
