/**
 * Operator cue strip for presentation mode (T10.6): the five-minute stage route from
 * PRD §13.2 as navigable cues. It changes navigation only, never any numbers.
 */
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useUI } from "@/app/store";
import { useSelection, type Screen } from "@/app/selection";
import { IconButton } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

const CUES: { t: string; label: string; screen: Screen; note: string }[] = [
  { t: "0:00", label: "Decision & downstream field", screen: "workspace", note: "Select a tail field; one sourced fact." },
  { t: "0:35", label: "Real imagery & reviewed AI boundaries", screen: "workspace", note: "Toggle raw AI overlay; state what is assumed." },
  { t: "1:00", label: "B0 vs B1, then run portfolio", screen: "compare", note: "Matched conditions; run P." },
  { t: "1:50", label: "Change budget — live re-solve", screen: "workspace", note: "Drag capital budget, Run again." },
  { t: "2:35", label: "Replay the decisive interval", screen: "replay", note: "Scrub to the pond release; canopy trace." },
  { t: "3:15", label: "Frontier & stress matrix", screen: "explore", note: "Tested robustness ≠ prediction certainty." },
  { t: "3:45", label: "Copilot what-if", screen: "workspace", note: "Only if connected; otherwise say so." },
  { t: "4:25", label: "Report & ask", screen: "report", note: "Validation status; supervised pilot partner." },
];

export function PresentationCues() {
  const sel = useSelection();
  const set = useUI((s) => s.set);
  const i = Math.max(0, CUES.findIndex((c) => c.screen === sel.screen));
  const go = (n: number) => {
    const c = CUES[(n + CUES.length) % CUES.length];
    if (c.label.startsWith("Copilot")) set({ inspectorTab: "copilot", inspectorOpen: true });
    sel.go(c.screen);
  };
  return (
    <div className="no-print flex h-14 shrink-0 items-center gap-2 border-t border-border bg-ink px-3 text-canvas" role="navigation" aria-label="Presentation cues" data-testid="presentation-cues">
      <IconButton label="Previous cue" size="sm" variant="ghost" className="text-canvas hover:bg-white/10 hover:text-canvas" onClick={() => go(i - 1)}>
        <ChevronLeft size={18} />
      </IconButton>
      <ol className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {CUES.map((c, n) => (
          <li key={c.t}>
            <button
              type="button"
              onClick={() => go(n)}
              title={c.note}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-[10px] px-3 py-1.5 text-[14px] transition-colors",
                c.screen === sel.screen ? "bg-white/15 font-semibold" : "text-canvas/70 hover:bg-white/10 hover:text-canvas",
              )}
            >
              <span className="num text-[12px] opacity-70">{c.t}</span>
              {c.label}
            </button>
          </li>
        ))}
      </ol>
      <IconButton label="Next cue" size="sm" variant="ghost" className="text-canvas hover:bg-white/10 hover:text-canvas" onClick={() => go(i + 1)}>
        <ChevronRight size={18} />
      </IconButton>
      <IconButton label="Exit presentation mode" size="sm" variant="ghost" className="text-canvas hover:bg-white/10 hover:text-canvas" onClick={() => set({ presentation: false })}>
        <X size={16} />
      </IconButton>
    </div>
  );
}
