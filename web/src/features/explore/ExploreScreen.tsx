/**
 * What if (Explore): five lenses on the same settings version: spend more or less
 * (frontier), bad years and water cuts (stress), why not this option (why-not, synergy),
 * which assumptions matter (sensitivity) and quick estimates (surrogate preview).
 */
import { useMemo, useState } from "react";
import { Activity, CloudRain, GitBranch, HelpCircle, Info, LineChart, Zap } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useInterventions, useRun } from "@/lib/api/queries";
import { MapSlot } from "@/components/map/MapSlot";
import { useShell } from "@/components/layout/AppShell";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { NextStep, PageHeader } from "@/components/ui/PageHeader";
import { GLOSSARY, planName, type TermId } from "@/lib/glossary";
import { shortId } from "@/lib/formatting";
import { SubTabs } from "@/features/compare/CompareTabs";
import { Frontier } from "./Frontier";
import { Stress } from "./Stress";
import { WhyNot } from "./WhyNot";
import { Sensitivity } from "./Sensitivity";
import { Surrogate } from "./Surrogate";
import { useExploreBase, type ExploreBase } from "./api";

const TABS: { value: string; label: string; hint: string; icon: React.ReactNode; term: TermId; question: string }[] = [
  { value: "frontier", label: "Spend more or less?", hint: "Resilience frontier", icon: <LineChart size={15} />, term: "frontier", question: "How much extra harvest does each extra rupee buy?" },
  { value: "stress", label: "Bad years & water cuts", hint: "Stress matrix", icon: <CloudRain size={15} />, term: "stress", question: "Does the plan still work in a dry year or when the canal is cut?" },
  { value: "why-not", label: "Why not this option?", hint: "Why not · synergy", icon: <HelpCircle size={15} />, term: "whyNot", question: "What would happen if we forced in the option the plan left out?" },
  { value: "sensitivity", label: "Which assumptions matter?", hint: "Sensitivity", icon: <Activity size={15} />, term: "sensitivity", question: "Which uncertain number could change the decision?" },
  { value: "surrogate", label: "Quick estimate", hint: "Surrogate preview", icon: <Zap size={15} />, term: "surrogate", question: "Can we preview a new schedule instantly before running the full crop model?" },
];

export function ExploreScreen() {
  const { sel } = usePilotData();
  const { mobile, tablet } = useShell();
  const tab = TABS.some((t) => t.value === sel.tab) ? sel.tab! : "frontier";
  const meta = TABS.find((t) => t.value === tab)!;
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
      <SubTabs label="What-if analyses" tabs={TABS} value={tab} onChange={(v) => sel.setParams({ tab: v, analysis: null })} />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-4 md:p-8">
            <PageHeader compact title={meta.question} lead={GLOSSARY[meta.term].explain} meta={<BaseStrip base={base} />} />
            {needsBase && base.resolving ? (
              <Skeleton className="h-72" />
            ) : needsBase && base.run.error && !base.revisionId ? (
              <StatePanel state="error" error={base.run.error} title="The linked run could not be loaded" />
            ) : needsBase && !base.revisionId ? (
              <div className="max-w-[620px] pt-2">
                <StatePanel state="empty" art="chart" title="First find a plan to test" action={{ label: "Go to Plan", onClick: () => sel.go("workspace") }}>
                  These what-if tests start from a solved plan and its settings. Run a plan on the Plan step, or open a link that carries a run
                  <span className="whitespace-nowrap font-mono"> (?run=…)</span>.
                </StatePanel>
              </div>
            ) : (
              <div className="animate-rise" key={tab}>
                {tab === "frontier" ? <Frontier base={base} onHighlight={setHighlightRun} /> : null}
                {tab === "stress" ? <Stress base={base} /> : null}
                {tab === "why-not" ? <WhyNot base={base} /> : null}
                {tab === "sensitivity" ? <Sensitivity base={base} /> : null}
                {tab === "surrogate" ? <Surrogate base={base} /> : null}
              </div>
            )}
            <NextStep />
          </div>
        </div>
        {!mobile && !tablet && tab === "frontier" && base.revisionId ? (
          <div className="relative hidden w-[34%] max-w-[560px] shrink-0 border-l border-border 2xl:block">
            <MapSlot
              runId={highlightRun ?? base.runId}
              compactControls
              className="absolute inset-0"
              highlightFieldIds={highlight}
              label={highlightRun ? "Works chosen at the selected budget" : "Base run"}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Which plan the tests start from, and where that came from. */
function BaseStrip({ base }: { base: ExploreBase }) {
  const r = base.run.data;
  if (!base.revisionId && !base.runId) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-secondary" data-testid="explore-base">
      <GitBranch size={14} className="text-ink-tertiary" aria-hidden />
      <span>Tests start from</span>
      {r ? (
        <Chip size="sm" tone="ink" title={r.run_id}>
          {planName(r.plan_kind)} · run {shortId(r.run_id)}
        </Chip>
      ) : null}
      {base.revisionId ? (
        <Chip size="sm" title={base.revisionId}>
          settings {shortId(base.revisionId)}
        </Chip>
      ) : base.run.error ? (
        <Chip size="sm" tone="danger">
          settings unknown
        </Chip>
      ) : (
        <Skeleton className="h-5 w-28" />
      )}
      <span className="text-ink-tertiary">{base.source === "url-run" ? "(the run on screen)" : base.source === "workspace" ? "(your current settings)" : ""}</span>
      {base.workspaceRevisionId ? (
        <span className="inline-flex items-center gap-1 text-ink-tertiary" title={base.workspaceRevisionId}>
          <Info size={12} aria-hidden /> Your Plan settings ({shortId(base.workspaceRevisionId)}) differ; the run on screen is used.
        </span>
      ) : null}
    </div>
  );
}
