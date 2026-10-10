import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { PanelLeftOpen, PanelRightOpen, SlidersHorizontal } from "lucide-react";
import { useUI } from "@/app/store";
import { BREAKPOINTS, useMediaQuery } from "@/app/environment";
import { useSelection } from "@/app/selection";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { Button, IconButton } from "@/components/ui/Button";
import { MapBinder } from "@/components/map/MapBinder";
import { ContextBar } from "./ContextBar";
import { BottomNav, NavigationRail, NAV } from "./NavigationRail";
import { InspectorPanel } from "./InspectorPanel";
import { JobTray, JobWatchers } from "./JobTray";
import { CommandMenu } from "./CommandMenu";
import { PresentationCues } from "./PresentationCues";
import { ScenarioPanel } from "@/features/workspace/ScenarioPanel";

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
  const inspectorTab = useUI((s) => s.inspectorTab);
  const presentation = useUI((s) => s.presentation);
  const set = useUI((s) => s.set);
  const [scenarioSheet, setScenarioSheet] = useState(false);
  const [inspectorSheet, setInspectorSheet] = useState(false);
  const showScenario = sel.screen === "workspace";
  const docked = !tablet;

  // Opening the copilot on small screens uses the inspector sheet.
  useEffect(() => {
    if (!docked && inspectorTab === "copilot") setInspectorSheet(true);
  }, [docked, inspectorTab]);
  // A field selected on a small screen opens its details sheet.
  useEffect(() => {
    if (!docked && sel.fieldId && sel.screen === "workspace") setInspectorSheet(true);
  }, [docked, sel.fieldId, sel.screen]);

  useGlobalShortcuts();

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
      <div className="flex h-dvh w-full overflow-hidden bg-canvas text-ink" data-testid="app-shell" data-screen={sel.screen}>
        {!mobile ? <NavigationRail /> : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <ContextBar compact={mobile} onOpenScenario={ctx.openScenario} />
          <div className="relative flex min-h-0 flex-1">
            {showScenario && docked && scenarioOpen && !presentation ? (
              <ScenarioPanel className="w-[var(--scenario-w)] shrink-0" onCollapse={() => set({ scenarioOpen: false })} />
            ) : null}
            <main id="main" tabIndex={-1} className="relative flex min-w-0 flex-1 flex-col outline-none" aria-label={NAV.find((n) => n.screen === sel.screen || n.also?.includes(sel.screen))?.label}>
              {showScenario && (!docked || !scenarioOpen || presentation) ? (
                <div className="pointer-events-none absolute left-3 top-14 z-20">
                  {docked ? (
                    <IconButton label="Open scenario panel" variant="secondary" className="pointer-events-auto shadow-2" onClick={() => set({ scenarioOpen: true, presentation: false })}>
                      <PanelLeftOpen size={16} />
                    </IconButton>
                  ) : null}
                </div>
              ) : null}
              {children}
              <div className="pointer-events-none absolute bottom-3 right-3 z-30 flex flex-col items-end gap-2">
                <JobTray />
              </div>
              {!docked ? (
                <div className="no-print pointer-events-none absolute right-3 top-3 z-30 flex gap-2 md:top-auto md:bottom-3 md:right-auto md:left-3">
                  {showScenario ? (
                    <Button variant="secondary" size="sm" className="pointer-events-auto shadow-2" icon={<SlidersHorizontal size={14} />} onClick={() => setScenarioSheet(true)} data-testid="open-scenario-sheet">
                      Inputs
                    </Button>
                  ) : null}
                  <Button variant="secondary" size="sm" className="pointer-events-auto shadow-2" icon={<PanelRightOpen size={14} />} onClick={() => setInspectorSheet(true)} data-testid="open-inspector-sheet">
                    Details
                  </Button>
                </div>
              ) : null}
            </main>
            {docked && inspectorOpen ? (
              <InspectorPanel
                className={inspectorTab === "copilot" ? "w-[var(--copilot-w)] shrink-0" : "w-[var(--inspector-w)] shrink-0"}
                onClose={() => set({ inspectorOpen: false })}
              />
            ) : docked ? (
              <div className="absolute right-3 top-14 z-20">
                <IconButton label="Open inspector" variant="secondary" className="shadow-2" onClick={() => set({ inspectorOpen: true })}>
                  <PanelRightOpen size={16} />
                </IconButton>
              </div>
            ) : null}
          </div>
          {presentation ? <PresentationCues /> : null}
          {mobile ? <BottomNav /> : null}
        </div>
      </div>

      <Dialog open={scenarioSheet && !docked} onOpenChange={setScenarioSheet}>
        <DialogContent title="Scenario inputs" side={mobile ? "bottom" : "left"} className={mobile ? "h-[88vh]" : ""}>
          <ScenarioPanel className="border-0" />
        </DialogContent>
      </Dialog>
      <Dialog open={inspectorSheet && !docked} onOpenChange={(o) => { setInspectorSheet(o); if (!o && inspectorTab === "copilot") set({ inspectorTab: "field" }); }}>
        <DialogContent title={inspectorTab === "copilot" ? "Copilot" : "Details"} side={mobile ? "bottom" : "right"} className={mobile ? "h-[88vh]" : ""}>
          <InspectorPanel className="border-0" />
        </DialogContent>
      </Dialog>
      <CommandMenu />
    </Ctx.Provider>
  );
}

function useGlobalShortcuts() {
  const sel = useSelection();
  const set = useUI((s) => s.set);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t?.closest("input,textarea,select,[contenteditable=true],[role=combobox]");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        set({ commandOpen: true });
        return;
      }
      if (typing || e.altKey || e.ctrlKey || e.metaKey) return;
      if (document.querySelector("[role=dialog]")) return;
      const nav = NAV.find((n) => n.shortcut === e.key);
      if (nav) {
        e.preventDefault();
        sel.go(nav.screen);
      } else if (e.key === "/") {
        e.preventDefault();
        set({ inspectorOpen: true, inspectorTab: "field" });
        if (sel.fieldId) sel.setParams({ field: null });
        setTimeout(() => document.getElementById("field-search")?.focus(), 30);
      } else if (e.key === "p" && e.shiftKey) {
        set({ presentation: !useUI.getState().presentation });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sel, set]);
}
