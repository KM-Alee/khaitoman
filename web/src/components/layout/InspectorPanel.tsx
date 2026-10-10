import { PanelRightClose } from "lucide-react";
import { useUI, type InspectorTab } from "@/app/store";
import { usePilotData } from "@/app/pilotData";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { IconButton } from "@/components/ui/Button";
import { FieldInspector } from "@/features/workspace/FieldInspector";
import { ActionsInspector } from "@/features/workspace/ActionsInspector";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { CopilotPanel } from "@/features/copilot/CopilotPanel";
import { StatePanel } from "@/components/status";
import { cn } from "@/lib/cn";

export function InspectorPanel({ onClose, className }: { onClose?: () => void; className?: string }) {
  const tab = useUI((s) => s.inspectorTab);
  const set = useUI((s) => s.set);
  const { pilot } = usePilotData();
  const sources = pilot.data?.pilot?.source_refs ?? [];
  return (
    <aside
      aria-label={tab === "copilot" ? "Copilot" : "Inspector"}
      className={cn("flex h-full min-h-0 flex-col border-l border-border bg-surface", className)}
      data-testid="inspector"
    >
      <Tabs value={tab} onValueChange={(v) => set({ inspectorTab: v as InspectorTab })} className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center justify-between pr-2">
          <TabsList className="flex-1 border-b-0">
            <TabsTrigger value="field">Field</TabsTrigger>
            <TabsTrigger value="actions">Actions</TabsTrigger>
            <TabsTrigger value="evidence">Sources</TabsTrigger>
            <TabsTrigger value="copilot">Copilot</TabsTrigger>
          </TabsList>
          {onClose ? (
            <IconButton label="Close inspector" size="sm" onClick={onClose}>
              <PanelRightClose size={16} />
            </IconButton>
          ) : null}
        </div>
        <div className="h-px shrink-0 bg-border" />
        <TabsContent value="field" className="min-h-0 flex-1 overflow-y-auto outline-none">
          <FieldInspector />
        </TabsContent>
        <TabsContent value="actions" className="min-h-0 flex-1 overflow-y-auto outline-none">
          <ActionsInspector />
        </TabsContent>
        <TabsContent value="evidence" className="min-h-0 flex-1 overflow-y-auto p-4 outline-none">
          {sources.length ? (
            <div className="flex flex-col gap-2">
              {sources.slice(0, 12).map((id) => (
                <EvidenceById key={id} id={id} compact />
              ))}
            </div>
          ) : (
            <StatePanel state="empty" title="No package sources listed">
              This pilot version lists no source evidence ids. Open Evidence to search all records.
            </StatePanel>
          )}
        </TabsContent>
        <TabsContent value="copilot" className="min-h-0 flex-1 outline-none">
          <CopilotPanel />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
