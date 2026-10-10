/**
 * The B0/B1/P/R ladder for the run on screen.
 *  1. explicit `?runs=` in the URL wins (shared comparison links);
 *  2. a run from the visitor's active settings version uses the runs recorded this session;
 *  3. any other run (a shared `?run=` link, the tour's saved result, a reload) rebuilds the
 *     ladder from the server: the newest ordinary run of each kind on that run's revision.
 */
import { useMemo } from "react";
import { useSelection } from "@/app/selection";
import { useUI } from "@/app/store";
import { useRevisionSiblings, useRun, useRuns } from "@/lib/api/queries";
import type { PlanKind, RunResult } from "@/lib/api/types";

export const LADDER_ORDER: PlanKind[] = ["B0", "B1", "P", "R"];

export function useLadderRuns() {
  const sel = useSelection();
  const active = useUI((s) => s.active[sel.pilotKey]);
  const runsByRevision = useUI((s) => s.runsByRevision);
  const anchor = useRun(sel.compareRunIds.length ? null : sel.runId);
  const activeRuns = useMemo(() => (active ? runsByRevision[active.revisionId] ?? {} : {}), [active, runsByRevision]);
  const anchorIsActive =
    !sel.runId || Object.values(activeRuns).includes(sel.runId) || (!!anchor.data && !!active && anchor.data.scenario_revision_id === active.revisionId);

  const local = useMemo(() => {
    if (sel.compareRunIds.length) return sel.compareRunIds;
    if (!anchorIsActive) return [];
    return LADDER_ORDER.map((k) => activeRuns[k]).filter(Boolean) as string[];
  }, [sel.compareRunIds, anchorIsActive, activeRuns]);

  const siblings = useRevisionSiblings(local.length || !sel.runId ? null : sel.runId);
  const ids = useMemo(() => {
    if (local.length) return local;
    const latest = new Map<string, string>();
    for (const r of siblings.list.data ?? []) {
      if (r.analysis_id || !r.plan_kind || r.outcome === undefined) continue;
      if (!latest.has(r.plan_kind)) latest.set(r.plan_kind, r.run_id);
    }
    return LADDER_ORDER.map((k) => latest.get(k)).filter(Boolean) as string[];
  }, [local, siblings.list.data]);
  const runs = useRuns(ids);
  const byKind = useMemo(() => {
    const m = new Map<PlanKind, RunResult>();
    for (const r of runs.data ?? []) if (!m.has(r.plan_kind)) m.set(r.plan_kind, r);
    return m;
  }, [runs.data]);
  return { ids, runs, byKind, siblingsLoading: !!sel.runId && !local.length && (anchor.isLoading || siblings.isLoading) };
}
