import { useCallback } from "react";
import { useSelection } from "@/app/selection";
import { useUI } from "@/app/store";
import { useAnalysis, useAnalysisList, useStartAnalysis } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { toast } from "@/components/ui/Toast";

export type AnalysisKind = "frontier" | "stress" | "why-not" | "synergy" | "sensitivity";

const LABEL: Record<AnalysisKind, string> = {
  frontier: "Resilience frontier",
  stress: "Stress matrix",
  "why-not": "Why-not solve",
  synergy: "Synergy (4 matched runs)",
  sensitivity: "Sensitivity sweep",
};

export function analysisKindOf(a: Record<string, unknown> | undefined): string {
  return String(a?.kind ?? a?.analysis_type ?? a?.type ?? "").replace("_", "-");
}

/** Start an analysis job and track it; result binding happens in JobWatchers. */
export function useAnalysisRunner(kind: AnalysisKind) {
  const sel = useSelection();
  const start = useStartAnalysis();
  const trackJob = useUI((s) => s.trackJob);
  const run = useCallback(
    async (body: Record<string, unknown>) => {
      try {
        const r = await start.mutateAsync({ kind, body });
        if (r.analysisId) sel.setParams({ analysis: r.analysisId, tab: kind });
        if (r.jobId)
          trackJob({
            jobId: r.jobId,
            label: LABEL[kind],
            operation: "analysis",
            analysisKind: kind,
            revisionId: null,
            pilotKey: sel.pilotKey,
          });
        return r;
      } catch (e) {
        const d = describeError(e);
        toast({ tone: "danger", title: `${LABEL[kind]}: ${d.title}`, description: d.detail });
        return null;
      }
    },
    [kind, start, trackJob, sel],
  );
  return { run, pending: start.isPending };
}

/** The analysis to show for a tab: URL selection if it matches the kind, else the newest of that kind. */
export function useCurrentAnalysis(kind: AnalysisKind) {
  const sel = useSelection();
  const list = useAnalysisList(sel.pilotId, sel.version);
  const fromUrl = useAnalysis(sel.analysisId, true);
  const urlMatches = fromUrl.data && analysisKindOf(fromUrl.data) === kind;
  const latest = (list.data ?? []).filter((a) => analysisKindOf(a) === kind).sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))[0];
  const latestId = !urlMatches ? ((latest?.analysis_id as string | undefined) ?? null) : null;
  const latestQ = useAnalysis(latestId, true);
  const data = urlMatches ? fromUrl.data : latestQ.data;
  return {
    data,
    loading: (sel.analysisId && fromUrl.isLoading) || latestQ.isLoading,
    error: urlMatches ? fromUrl.error : latestQ.error,
    history: (list.data ?? []).filter((a) => analysisKindOf(a) === kind),
  };
}

export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
export function pickNum(o: Record<string, unknown> | undefined | null, ...keys: string[]): number | null {
  if (!o) return null;
  for (const k of keys) {
    const v = o[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (v && typeof v === "object" && typeof (v as { value?: unknown }).value === "number") return (v as { value: number }).value;
  }
  return null;
}
