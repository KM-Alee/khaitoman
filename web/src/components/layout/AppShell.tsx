/**
 * Pilot screens' shell (PRD §9.3, docs/UI_SYSTEM.md › Shell):
 *   top bar (brand · pilot · journey · tour · Ask AabFlow · next action)
 *   [plan settings 312px] [screen] [inspector 372px | assistant 420px]
 * The plan settings dock only on Plan; the inspector docks on Plan and opens elsewhere when
 * a field is selected. On tablets and phones both become sheets.
 */
import { cn } from "@/lib/cn";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PanelLeftOpen, PanelRightOpen, SlidersHorizontal } from "lucide-react";
import { useUI } from "@/app/store";
import { BREAKPOINTS, useMediaQuery } from "@/app/environment";
import { useSelection } from "@/app/selection";
import { journeyFor } from "@/app/journey";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { Button, IconButton } from "@/components/ui/Button";
import { MapBinder } from "@/components/map/MapBinder";
import { TopBar } from "./ContextBar";
import { BottomNav, NAV } from "./NavigationRail";
import { InspectorPanel } from "./InspectorPanel";
import { AssistantPanel } from "./AssistantPanel";
import { JobTray, JobWatchers } from "./JobTray";
import { CommandMenu } from "./CommandMenu";
import { PresentationCues } from "./PresentationCues";
import { ScenarioPanel } from "@/features/workspace/ScenarioPanel";
import { useScenario } from "@/features/workspace/useScenario";

interface ShellCtx {
  mobile: boolean;
  tablet: boolean;
  compact: boolean;
  openScenario: () => void;
  openInspector: () => void;
}
const Ctx = createContext<ShellCtx>({ mobile: false, tablet: false, compact: false, openScenario: () => {}, openInspector: () => {} });
export const useShell = () => useContext(Ctx);

export function AppShell({ children }: { children: ReactNode }) {
  const mobile = useMediaQuery(BREAKPOINTS.mobile);
  const tablet = useMediaQuery(BREAKPOINTS.tablet);
  const compact = useMediaQuery(BREAKPOINTS.compact);
  const sel = useSelection();
  const scenarioOpen = useUI((s) => s.scenarioOpen);
  const inspectorOpen = useUI((s) => s.inspectorOpen);
  const assistantOpen = useUI((s) => s.assistantOpen);
  const presentation = useUI((s) => s.presentation);
  const set = useUI((s) => s.set);
  const [scenarioSheet, setScenarioSheet] = useState(false);
  const [inspectorSheet, setInspectorSheet] = useState(false);
  const onPlan = sel.screen === "workspace";
  const docked = !tablet;
  // Off the Plan screen the inspector is shown for a selected field (or when asked for).
  const [detailsOff, setDetailsOff] = useState(false);
  useEffect(() => setDetailsOff(false), [sel.fieldId]);
  const showInspector = onPlan ? inspectorOpen : !!sel.fieldId && !detailsOff;

  // A field selected on a small screen opens its details sheet.
  useEffect(() => {
    if (!docked && sel.fieldId && sel.screen === "workspace") setInspectorSheet(true);
  }, [docked, sel.fieldId, sel.screen]);

  useGlobalShortcuts();

  // "Open Plan settings" requests from the tour or an assistant answer.
  const settingsRequest = useUI((s) => s.settingsRequest);
  const firstReq = useRef(settingsRequest);
  useEffect(() => {
    if (settingsRequest === firstReq.current) return;
    firstReq.current = settingsRequest;
    if (docked) set({ scenarioOpen: true, presentation: false });
    else setScenarioSheet(true);
  }, [settingsRequest, docked, set]);

  const ctx = useMemo<ShellCtx>(
    () => ({
      mobile,
      tablet,
      compact,
      openScenario: () => (docked ? set({ scenarioOpen: true }) : setScenarioSheet(true)),
      openInspector: () => (docked ? set({ inspectorOpen: true }) : setInspectorSheet(true)),
    }),
    [mobile, tablet, compact, docked, set],
  );

  return (
    <Ctx.Provider value={ctx}>
      <a href="#main" className="sr-only z-[100] rounded-md bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2">
        Skip to content
      </a>
      <MapBinder />
      <JobWatchers />
      <PendingRun />
      <div className="flex h-dvh w-full flex-col overflow-hidden bg-canvas text-ink print:block print:h-auto print:overflow-visible print:bg-white" data-testid="app-shell" data-screen={sel.screen}>
        <TopBar compact={mobile} onOpenScenario={ctx.openScenario} />
        <div className="relative flex min-h-0 flex-1 print:block">
          {onPlan && docked && scenarioOpen && !presentation ? (
            <ScenarioPanel className="w-[var(--scenario-w)] shrink-0" onCollapse={() => set({ scenarioOpen: false })} />
          ) : null}
          <main
            id="main"
            tabIndex={-1}
            className="relative flex min-w-0 flex-1 flex-col outline-none"
            aria-label={journeyFor(sel.screen).label ?? NAV[0].label}
          >
            {onPlan && docked && (!scenarioOpen || presentation) ? (
              <div className="pointer-events-none absolute left-3 top-3 z-20">
                <Button
                  variant="secondary"
                  size="sm"
                  className="pointer-events-auto shadow-2"
                  icon={<PanelLeftOpen size={15} />}
                  onClick={() => set({ scenarioOpen: true, presentation: false })}
                  data-testid="open-plan-settings"
                >
                  Plan settings
                </Button>
              </div>
            ) : null}
            {children}
            <div className={cn("pointer-events-none absolute right-3 z-30 flex flex-col items-end gap-2", !docked ? "bottom-16 md:bottom-3" : "bottom-3")}>
              <JobTray />
            </div>
            {!docked ? (
              <div className={cn("no-print pointer-events-none absolute z-30 flex gap-2", onPlan ? "left-3 top-3" : "bottom-3 left-3")}>
                {onPlan ? (
                  <Button variant="secondary" size="sm" className="pointer-events-auto shadow-2" icon={<SlidersHorizontal size={14} />} onClick={() => setScenarioSheet(true)} data-testid="open-scenario-sheet">
                    Plan settings
                  </Button>
                ) : null}
                {onPlan ? (
                  <Button variant="secondary" size="sm" className="pointer-events-auto shadow-2" icon={<PanelRightOpen size={14} />} onClick={() => setInspectorSheet(true)} data-testid="open-inspector-sheet">
                    Result & fields
                  </Button>
                ) : sel.fieldId ? (
                  <Button variant="secondary" size="sm" className="pointer-events-auto shadow-2" icon={<PanelRightOpen size={14} />} onClick={() => setInspectorSheet(true)} data-testid="open-inspector-sheet">
                    Field details
                  </Button>
                ) : null}
              </div>
            ) : null}
          </main>
          {docked && assistantOpen ? (
            <AssistantPanel className="w-[var(--copilot-w)] shrink-0 animate-[sheet-r_220ms_var(--ease-out)_both]" onClose={() => set({ assistantOpen: false })} />
          ) : docked && showInspector ? (
            <InspectorPanel
              className="w-[var(--inspector-w)] shrink-0"
              onClose={() => (onPlan ? set({ inspectorOpen: false }) : sel.fieldId ? sel.setParams({ field: null }) : setDetailsOff(true))}
            />
          ) : docked && onPlan ? (
            <div className="absolute right-3 top-3 z-20">
              <IconButton label="Open result and field details" variant="secondary" className="shadow-2" onClick={() => set({ inspectorOpen: true })}>
                <PanelRightOpen size={16} />
              </IconButton>
            </div>
          ) : null}
        </div>
        {presentation ? <PresentationCues /> : null}
        {mobile ? <BottomNav /> : null}
      </div>

      <Dialog open={scenarioSheet && !docked} onOpenChange={setScenarioSheet}>
        <DialogContent title="Plan settings" side={mobile ? "bottom" : "left"} className={mobile ? "h-[90vh]" : ""}>
          <ScenarioPanel className="border-0" />
        </DialogContent>
      </Dialog>
      <Dialog open={inspectorSheet && !docked} onOpenChange={setInspectorSheet}>
        <DialogContent title={sel.fieldId ? "Field details" : "Result"} side={mobile ? "bottom" : "right"} className={mobile ? "h-[90vh]" : ""}>
          <InspectorPanel className="border-0" />
        </DialogContent>
      </Dialog>
      <Dialog open={assistantOpen && !docked} onOpenChange={(o) => set({ assistantOpen: o })}>
        <DialogContent title="Ask AabFlow" description="Answers cite the saved runs they come from" side={mobile ? "bottom" : "right"} className={mobile ? "h-[90vh]" : "w-[min(440px,100vw)]"}>
          <AssistantPanel className="border-0" header={false} />
        </DialogContent>
      </Dialog>
      <CommandMenu />
    </Ctx.Provider>
  );
}

/** Solves the current draft once the Plan settings are loaded, when "Re-run live" asked for it. */
function PendingRun() {
  const s = useScenario();
  const pending = useUI((st) => st.pendingRun);
  const set = useUI((st) => st.set);
  const ready = !!s.draft && s.draft.weather_scenario_ids.length > 0 && (s.phase === "draft" || s.phase === "dirty") && !s.catalog.weather.isLoading && !s.catalog.uncertainty.isLoading;
  useEffect(() => {
    if (!pending || !ready) return;
    set({ pendingRun: false });
    void s.run();
  }, [pending, ready]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function useGlobalShortcuts() {
  const sel = useSelection();
  const set = useUI((s) => s.set);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      const typing = t instanceof Element && !!t.closest("input,textarea,select,[contenteditable=true],[role=combobox]");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        set({ commandOpen: true });
        return;
      }
      if (typing || e.altKey || e.ctrlKey || e.metaKey) return;
      if (document.querySelector("[role=dialog]") || document.querySelector("[data-tour-active]")) return;
      const nav = NAV.find((n) => n.shortcut === e.key);
      if (nav) {
        e.preventDefault();
        sel.go(nav.screen);
      } else if (e.key === "/") {
        e.preventDefault();
        set({ inspectorOpen: true, inspectorTab: "field" });
        if (sel.fieldId) sel.setParams({ field: null });
        setTimeout(() => document.getElementById("field-search")?.focus(), 30);
      } else if (e.key.toLowerCase() === "p" && e.shiftKey) {
        set({ presentation: !useUI.getState().presentation });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sel, set]);
}
