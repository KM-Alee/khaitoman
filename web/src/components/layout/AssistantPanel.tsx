/**
 * Assistant slot (docs/UI_SYSTEM.md › Assistant slot). The "Ask AabFlow" button in the top
 * bar opens this region. On wide screens it docks on the right (420 px) in place of the
 * inspector and never covers the plan settings or the run button (PRD §9.3); on smaller
 * screens it is a full-height sheet. It renders the copilot feature's `CopilotPanel`,
 * which reads its context (pilot, run, field, date, screen) from the URL selection.
 */
import { Sparkles, X } from "lucide-react";
import { CopilotPanel } from "@/features/copilot/CopilotPanel";
import { IconButton } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export function AssistantHeader({ onClose }: { onClose?: () => void }) {
  return (
    <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-water-grad text-on-water shadow-1" aria-hidden>
          <Sparkles size={16} />
        </span>
        <div className="min-w-0">
          <h2 className="text-[14px] font-semibold leading-tight text-ink">Ask AabFlow</h2>
          <p className="truncate text-[11.5px] leading-tight text-ink-tertiary">Answers cite the saved runs they come from</p>
        </div>
      </div>
      {onClose ? (
        <IconButton label="Close assistant" size="sm" onClick={onClose}>
          <X size={16} />
        </IconButton>
      ) : null}
    </div>
  );
}

export function AssistantPanel({ className, onClose, header = true }: { className?: string; onClose?: () => void; header?: boolean }) {
  return (
    <aside aria-label="Ask AabFlow" className={cn("flex h-full min-h-0 flex-col border-l border-border bg-surface", className)} data-testid="assistant-slot">
      {header ? <AssistantHeader onClose={onClose} /> : null}
      <div className="min-h-0 flex-1">
        <CopilotPanel />
      </div>
    </aside>
  );
}
