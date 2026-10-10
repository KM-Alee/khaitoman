/**
 * Per-field crop-model canopy cover for every date of a run, used to grow the 3D fields
 * through the season replay. Values are the exact AquaCrop `canopy_fraction` series the API
 * returns per field (GET /runs/{id}/timeline?field_id=…); nothing is interpolated, and a
 * missing value stays missing (the field renders flat and grey for that date).
 */
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { api, qs } from "@/lib/api/client";
import { qk } from "@/lib/api/queries";
import { readTimeline, type Timeline } from "@/lib/api/adapters";

export const CANOPY_SERIES = "canopy_fraction";

export interface CanopyFrames {
  /** Dates shared by the run's daily series (YYYY-MM-DD…). */
  dates: string[];
  /** field_id → canopy fraction per date index (null = no model value that day). */
  byField: Map<string, (number | null)[]>;
  loaded: number;
  total: number;
  failed: number;
}

export function useCanopyFrames(runId: string | null | undefined, fieldIds: string[], enabled = true): CanopyFrames {
  const results = useQueries({
    queries: fieldIds.map((fid) => ({
      queryKey: qk.timeline(runId ?? "", fid),
      enabled: enabled && !!runId,
      staleTime: Number.POSITIVE_INFINITY,
      retry: 1,
      queryFn: async ({ signal }: { signal: AbortSignal }): Promise<Timeline> =>
        readTimeline(await api.get(`/runs/${encodeURIComponent(runId!)}/timeline${qs({ field_id: fid, resolution: "daily" })}`, signal), runId!, fid),
    })),
  });
  const stamp = results.map((r) => r.dataUpdatedAt).join(",");
  return useMemo(() => {
    const byField = new Map<string, (number | null)[]>();
    let dates: string[] = [];
    let loaded = 0;
    let failed = 0;
    results.forEach((r, i) => {
      if (r.error) failed++;
      const t = r.data;
      if (!t) return;
      loaded++;
      if (!dates.length) dates = t.dates;
      const s = t.series.find((x) => x.id === CANOPY_SERIES);
      if (s) byField.set(fieldIds[i], s.values);
    });
    return { dates, byField, loaded, total: fieldIds.length, failed };
  }, [stamp, fieldIds.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
}
