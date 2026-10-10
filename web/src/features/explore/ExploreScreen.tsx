import { useMemo, useState } from "react";
import { usePilotData } from "@/app/pilotData";
import { useRun } from "@/lib/api/queries";
import { MapSlot } from "@/components/map/MapSlot";
import { useShell } from "@/components/layout/AppShell";
import { SubTabs } from "@/features/compare/CompareTabs";
import { useScenario } from "@/features/workspace/useScenario";
import { Frontier } from "./Frontier";
import { Stress } from "./Stress";
import { WhyNot } from "./WhyNot";
import { Surrogate } from "./Surrogate";

const TABS = [
  { value: "frontier", label: "Frontier" },
  { value: "stress", label: "Stress matrix" },
  { value: "why-not", label: "Why not · synergy" },
  { value: "surrogate", label: "Surrogate preview" },
];

export function ExploreScreen() {
  const { sel } = usePilotData();
  const { mobile, tablet } = useShell();
  const tab = TABS.some((t) => t.value === sel.tab) ? sel.tab! : "frontier";
  const [highlightRun, setHighlightRun] = useState<string | null>(null);
  const hr = useRun(highlightRun);
  const s = useScenario();
  const catalog = s.catalog.interventions.data ?? [];
  // Portfolio fields of the selected frontier point (only after its run has loaded, §9.5)
  const highlight = useMemo(() => {
    if (!hr.data || hr.data.outcome !== "plan") return null;
    const ids = new Set<string>();
    for (const inst of hr.data.selected_intervention_instance_ids) {
      const it = catalog.find((c) => c.instance_id === inst);
      for (const t of it?.target_ids ?? []) ids.add(t);
    }
    for (const fid of Object.keys(hr.data.selection ?? {})) if (ids.size === 0) void fid;
    return [...ids];
  }, [hr.data, catalog]);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="explore">
      <SubTabs label="Explore analyses" tabs={TABS} value={tab} onChange={(v) => sel.setParams({ tab: v, analysis: null })} />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto p-3 md:p-4">
          {tab === "frontier" ? <Frontier onHighlight={setHighlightRun} /> : null}
          {tab === "stress" ? <Stress /> : null}
          {tab === "why-not" ? <WhyNot /> : null}
          {tab === "surrogate" ? <Surrogate /> : null}
        </div>
        {!mobile && !tablet && tab === "frontier" ? (
          <div className="relative hidden w-[38%] max-w-[560px] shrink-0 border-l border-border 2xl:block">
            <MapSlot runId={highlightRun ?? sel.runId} compactControls className="absolute inset-0" highlightFieldIds={highlight} label="Portfolio of the selected frontier point" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
