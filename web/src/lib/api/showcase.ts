/**
 * Landing showcase data: GET /demo/headline (the seeded session's story, every figure read or
 * derived on the server with its unit and run IDs) and GET /ai-stack (one fact per AI engine,
 * read from stored evidence). The browser only formats these values.
 */
import { useQuery } from "@tanstack/react-query";
import type { components } from "@/generated/api";
import type { MetricValue } from "./types";
import { ApiError, api } from "./client";

export type DemoHeadline = components["schemas"]["DemoHeadline"];
export type HeadlineFigure = components["schemas"]["Figure"];
export type AiStack = components["schemas"]["AiStack"];
export type AiEngine = components["schemas"]["AiEngine"];

const noRetry404 = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 1;

export function useHeadline() {
  return useQuery({
    queryKey: ["demo-headline"],
    queryFn: ({ signal }) => api.get<DemoHeadline>("/demo/headline", signal),
    staleTime: 60_000,
    retry: noRetry404,
  });
}

export function useAiStack() {
  return useQuery({
    queryKey: ["ai-stack"],
    queryFn: ({ signal }) => api.get<AiStack>("/ai-stack", signal),
    staleTime: 60_000,
    retry: noRetry404,
  });
}

/** Present a server figure through the shared MetricValue views (no arithmetic). */
export function figureMetric(metricId: string, f: HeadlineFigure | null | undefined): MetricValue | null {
  if (!f) return null;
  return {
    metric_id: metricId,
    definition_id: `${metricId}@server`,
    run_id: f.run_ids[f.run_ids.length - 1] ?? "",
    value: f.value ?? null,
    unit: f.unit,
    status: f.value === null || f.value === undefined ? "not_estimated" : "available",
    reason: f.reason ?? null,
    evidence_ids: [],
    crop: null,
    field_id: null,
  } as MetricValue;
}
