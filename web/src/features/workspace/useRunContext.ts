/**
 * Everything the UI needs to *describe* a stored run: the run, the immutable settings
 * version it was solved with, and the intervention catalog for that run's own season and
 * decision date (not the current draft's). Pure reads; no metric is derived here.
 */
import { useMemo } from "react";
import { useInterventions, useRevision, useRun } from "@/lib/api/queries";
import { useSelection } from "@/app/selection";
import { useUI } from "@/app/store";

export function useRunContext(runId: string | null | undefined) {
  const sel = useSelection();
  const run = useRun(runId);
  const revision = useRevision(run.data?.scenario_revision_id ?? null);
  const request = revision.data?.revision.request ?? null;
  const interventions = useInterventions(sel.pilotId, request?.season_id, request?.decision_at);
  const byId = useMemo(() => new Map((interventions.data ?? []).map((c) => [c.instance_id, c])), [interventions.data]);
  const active = useUI((s) => s.active[sel.pilotKey]);
  /** The run was solved from settings other than the visitor's active revision (a link, the tour, an older run). */
  const saved = !!run.data && (!active || active.revisionId !== run.data.scenario_revision_id);
  return { run, revision, request, interventions, byId, saved };
}
