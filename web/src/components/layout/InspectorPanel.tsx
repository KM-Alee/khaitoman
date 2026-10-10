/**
 * Right-hand inspector: the plan's answer (Plan screen), the selected field, and the pilot's
 * sources. Selecting a field anywhere switches to its details.
 */
import { useEffect } from "react";
import { PanelRightClose } from "lucide-react";
import { useUI, type InspectorTab } from "@/app/store";
import { usePilotData } from "@/app/pilotData";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { IconButton } from "@/components/ui/Button";
import { FieldInspector } from "@/features/workspace/FieldInspector";
import { ResultPanel } from "@/features/workspace/ResultPanel";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { StatePanel, TrustSummary } from "@/components/status";
import { cn } from "@/lib/cn";

export function InspectorPanel({ onClose, className }: { onClose?: () => void; className?: string }) {
  const stored = useUI((s) => s.inspectorTab);
  const set = useUI((s) => s.set);
  const { pilot, sel } = usePilotData();
  const onPlan = sel.screen === "workspace";
  const sources = pilot.data?.pilot?.source_refs ?? [];
  // Legacy tab names map onto the new ones; off the Plan screen there is no "result" tab.
  const tab: InspectorTab = stored === "actions" || stored === "copilot" ? "result" : stored;
  const shown = !onPlan && tab === "result" ? "field" : tab;

  useEffect(() => {
    if (sel.fieldId) set({ inspectorTab: "field" });
  }, [sel.fieldId, set]);

  return (
    <aside aria-label="Inspector" className={cn("flex h-full min-h-0 flex-col border-l border-border bg-surface", className)} data-testid="inspector">
      <Tabs value={shown} onValueChange={(v) => set({ inspectorTab: v as InspectorTab })} className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center justify-between pr-2">
          <TabsList className="flex-1 border-b-0 px-2">
            {onPlan ? <TabsTrigger value="result">Result</TabsTrigger> : null}
            <TabsTrigger value="field">{sel.fieldId ? "Field" : "Fields"}</TabsTrigger>
            <TabsTrigger value="evidence">Sources</TabsTrigger>
          </TabsList>
          {onClose ? (
            <IconButton label="Close panel" size="sm" onClick={onClose}>
              <PanelRightClose size={16} />
            </IconButton>
          ) : null}
        </div>
        <div className="h-px shrink-0 bg-border" />
        {onPlan ? (
          <TabsContent value="result" className="min-h-0 flex-1 overflow-y-auto outline-none">
            <ResultPanel />
          </TabsContent>
        ) : null}
        <TabsContent value="field" className="min-h-0 flex-1 overflow-y-auto outline-none">
          <FieldInspector />
        </TabsContent>
        <TabsContent value="evidence" className="min-h-0 flex-1 overflow-y-auto p-4 outline-none">
          <div className="flex flex-col gap-4">
            <section>
              <h3 className="eyebrow mb-2">What is checked and what is assumed</h3>
              <TrustSummary flags={pilot.data?.pilot?.review_flags} />
            </section>
            <section>
              <h3 className="eyebrow mb-2">Package sources</h3>
              {sources.length ? (
                <div className="flex flex-col gap-2">
                  {sources.slice(0, 12).map((id) => (
                    <EvidenceById key={id} id={id} compact />
                  ))}
                </div>
              ) : (
                <StatePanel compact state="empty" title="No package sources listed">
                  This pilot version lists no source evidence ids. Open Trust to search all records.
                </StatePanel>
              )}
            </section>
          </div>
        </TabsContent>
      </Tabs>
    </aside>
  );
}
