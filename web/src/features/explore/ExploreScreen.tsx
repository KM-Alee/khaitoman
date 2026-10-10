import { useMemo, useState } from "react";
import { GitBranch, Info } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useInterventions, useRun } from "@/lib/api/queries";
import { MapSlot } from "@/components/map/MapSlot";
import { useShell } from "@/components/layout/AppShell";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { shortId } from "@/lib/formatting";
import { SubTabs } from "@/features/compare/CompareTabs";
import { Frontier } from "./Frontier";
import { Stress } from "./Stress";
import { WhyNot } from "./WhyNot";
import { Sensitivity } from "./Sensitivity";
import { Surrogate } from "./Surrogate";
import { useExploreBase, type ExploreBase } from "./api";

const TABS = [
  { value: "frontier", label: "Frontier" },
  { value: "stress", label: "Stress matrix" },
  { value: "why-not", label: "Why not · synergy" },
  { value: "sensitivity", label: "Sensitivity" },
  { value: "surrogate", label: "Surrogate preview" },
];

export function ExploreScreen() {
  const { sel } = usePilotData();
  const { mobile, tablet } = useShell();
  const tab = TABS.some((t) => t.value === sel.tab) ? sel.tab! : "frontier";
  const base = useExploreBase();
  const [highlightRun, setHighlightRun] = useState<string | null>(null);
  const hr = useRun(highlightRun);
  const req = base.revision.data?.revision.request;
  const catalog = useInterventions(sel.pilotId, req?.season_id, req?.decision_at).data ?? [];
  // Fields touched by the selected frontier point's portfolio (only after its run has loaded).
  const highlight = useMemo(() => {
    if (!hr.data || hr.data.outcome !== "plan") return null;
    const ids = new Set<string>();
    for (const inst of hr.data.selected_intervention_instance_ids) {
      for (const t of catalog.find((c) => c.instance_id === inst)?.target_ids ?? []) ids.add(t);
    }
    return [...ids];
  }, [hr.data, catalog]);

  const needsBase = tab !== "surrogate";
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="explore">
      <SubTabs label="Explore analyses" tabs={TABS} value={tab} onChange={(v) => sel.setParams({ tab: v, analysis: null })} />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto p-3 md:p-4">
          <div className="mx-auto flex max-w-[1400px] flex-col gap-3">
            <BaseStrip base={base} />
            {needsBase && base.resolving ? (
              <Skeleton className="h-72" />
            ) : needsBase && base.run.error && !base.revisionId ? (
              <StatePanel state="error" error={base.run.error} title="The linked run could not be loaded" />
            ) : needsBase && !base.revisionId ? (
              <div className="mx-auto w-full max-w-[560px] pt-6">
                <StatePanel state="empty" title="Explore needs a scenario revision" action={{ label: "Go to Workspace", onClick: () => sel.go("workspace") }}>
                  Frontier, stress, why-not, synergy and sensitivity analyses branch from a solved scenario revision. Run a plan in Workspace, or open a link that carries a run
                  <span className="whitespace-nowrap font-mono">(?run=…)</span>.
                </StatePanel>
              </div>
            ) : (
              <>
                {tab === "frontier" ? <Frontier base={base} onHighlight={setHighlightRun} /> : null}
                {tab === "stress" ? <Stress base={base} /> : null}
                {tab === "why-not" ? <WhyNot base={base} /> : null}
                {tab === "sensitivity" ? <Sensitivity base={base} /> : null}
                {tab === "surrogate" ? <Surrogate base={base} /> : null}
              </>
            )}
          </div>
        </div>
        {!mobile && !tablet && tab === "frontier" && base.revisionId ? (
          <div className="relative hidden w-[34%] max-w-[560px] shrink-0 border-l border-border 2xl:block">
            <MapSlot
              runId={highlightRun ?? base.runId}
              compactControls
              className="absolute inset-0"
              highlightFieldIds={highlight}
              label={highlightRun ? "Portfolio of the selected frontier point" : "Base run"}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Which revision / run the analyses are about, and where that came from. */
function BaseStrip({ base }: { base: ExploreBase }) {
  const r = base.run.data;
  if (!base.revisionId && !base.runId) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-secondary" data-testid="explore-base">
      <GitBranch size={14} className="text-ink-tertiary" aria-hidden />
      <span>Analyses branch from</span>
      {base.revisionId ? (
        <Chip size="sm" tone="ink" title={base.revisionId}>
          revision {shortId(base.revisionId)}
        </Chip>
      ) : base.run.error ? (
        <Chip size="sm" tone="danger">
          revision unknown
        </Chip>
      ) : (
        <Skeleton className="h-5 w-28" />
      )}
      {r ? (
        <Chip size="sm" title={r.run_id}>
          {r.plan_kind} run {shortId(r.run_id)} · {r.outcome === "plan" ? r.solver_status : "no plan"}
        </Chip>
      ) : null}
      <span className="text-ink-tertiary">{base.source === "url-run" ? "from the linked run" : base.source === "workspace" ? "from the Workspace's active revision" : ""}</span>
      {base.workspaceRevisionId ? (
        <span className="inline-flex items-center gap-1 text-ink-tertiary" title={base.workspaceRevisionId}>
          <Info size={12} aria-hidden /> Workspace's active revision ({shortId(base.workspaceRevisionId)}) differs; the linked run takes precedence.
        </span>
      ) : null}
    </div>
  );
}
