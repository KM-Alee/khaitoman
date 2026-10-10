import { useMemo } from "react";
import { usePilotData } from "@/app/pilotData";
import { useRun } from "@/lib/api/queries";
import { useScenario } from "./useScenario";
import { CATEGORY_META } from "./ScenarioPanel";
import { formatPKR, formatPKRCompact, shortId } from "@/lib/formatting";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { Eyebrow } from "@/components/ui/primitives";
import { Button } from "@/components/ui/Button";

/** Selected intervention instances in the displayed run, joined to the catalog for cost/dates. */
export function ActionsInspector() {
  const { sel } = usePilotData();
  const run = useRun(sel.runId);
  const s = useScenario();
  const catalog = s.catalog.interventions.data ?? [];
  const byId = useMemo(() => new Map(catalog.map((c) => [c.instance_id, c])), [catalog]);
  if (!sel.runId)
    return (
      <div className="p-4">
        <StatePanel state="empty" title="No run selected">
          Actions appear after a plan is solved. Use “Run plan” in the scenario panel.
        </StatePanel>
      </div>
    );
  if (run.isLoading) return <Skeleton className="m-4 h-40" />;
  if (run.error || !run.data) return <div className="p-4"><StatePanel state="error" error={run.error} title="Run unavailable" /></div>;
  const r = run.data;
  if (r.outcome !== "plan")
    return (
      <div className="p-4">
        <StatePanel state={r.solver_status === "INFEASIBLE" ? "infeasible" : "unknown"} title={`No plan · ${r.solver_status}`}>
          This run has no selected actions. Open Explore → Why not to inspect the binding constraints.
        </StatePanel>
      </div>
    );
  const ids = r.selected_intervention_instance_ids;
  return (
    <div className="flex flex-col gap-3 p-4" data-testid="actions-inspector">
      <div className="flex items-center justify-between">
        <Eyebrow>{ids.length ? `${ids.length} selected action${ids.length > 1 ? "s" : ""}` : "No new investment selected"}</Eyebrow>
        <Chip size="sm" tone="info">{r.plan_kind} · {shortId(r.run_id)}</Chip>
      </div>
      {!ids.length ? (
        <p className="text-[13px] text-ink-secondary">
          This plan uses operational timing with existing assets only. That is a valid outcome — no investment cleared the objective under these budgets.
        </p>
      ) : null}
      <ul className="flex flex-col gap-2">
        {ids.map((id) => {
          const it = byId.get(id);
          const cat = it ? CATEGORY_META[it.category] : null;
          return (
            <li key={id} className="rounded-[12px] border border-border p-3">
              <div className="flex items-center gap-2 text-[12px] text-ink-secondary">
                {cat?.icon}
                {cat?.label ?? "Intervention"}
                {it?.shared ? <Chip size="sm" tone="water">Shared · charged once</Chip> : null}
              </div>
              <div className="mt-1 text-[13px] font-semibold text-ink" title={id}>
                {it?.label ?? id}
              </div>
              {it ? (
                <div className="num mt-1 text-[12px] text-ink-secondary">
                  {formatPKR(it.capex_pkr)} capex{it.seasonal_opex_pkr ? ` · ${formatPKRCompact(it.seasonal_opex_pkr)}/season` : ""}
                  {it.lead_time_days ? ` · ${it.procurement_delay_days + it.lead_time_days} d to commission` : ""}
                </div>
              ) : null}
              <div className="mt-1 text-[12px] text-ink-tertiary">Targets {(it?.target_ids ?? []).join(", ") || "—"}</div>
            </li>
          );
        })}
      </ul>
      <Button variant="secondary" size="sm" onClick={() => sel.go("report")}>
        Open action plan
      </Button>
    </div>
  );
}
