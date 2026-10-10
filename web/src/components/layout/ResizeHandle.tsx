/**
 * Drag handle that resizes a docked side panel (Plan settings, inspector, assistant).
 * Pointer drag, arrow keys (Shift = 48 px steps) and double-click to reset. Widths are UI
 * preferences only (persisted in the UI store); the map is told to resize as they change.
 */
import { useRef } from "react";
import { getEngine } from "@/components/map/runtime";
import { cn } from "@/lib/cn";

export const PANEL_LIMITS = {
  scenario: { min: 260, max: 560, initial: 312 },
  inspector: { min: 300, max: 680, initial: 372 },
  assistant: { min: 340, max: 900, initial: 420 },
} as const;
export type PanelKey = keyof typeof PANEL_LIMITS;

export const clampWidth = (k: PanelKey, w: number) => Math.round(Math.min(PANEL_LIMITS[k].max, Math.max(PANEL_LIMITS[k].min, w)));

let raf = 0;
const resizeMap = () => {
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(() => getEngine()?.resize());
};

export function ResizeHandle({
  panel,
  width,
  onChange,
  side,
  label,
}: {
  panel: PanelKey;
  width: number;
  onChange: (w: number) => void;
  /** Which edge of the panel the handle sits on. */
  side: "left" | "right";
  label: string;
}) {
  const start = useRef<{ x: number; w: number } | null>(null);
  const set = (w: number) => {
    onChange(clampWidth(panel, w));
    resizeMap();
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={PANEL_LIMITS[panel].min}
      aria-valuemax={PANEL_LIMITS[panel].max}
      aria-valuenow={width}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      data-testid={`resize-${panel}`}
      className={cn(
        "group absolute inset-y-0 z-30 w-2 cursor-col-resize touch-none select-none outline-none",
        side === "right" ? "-right-1" : "-left-1",
      )}
      onPointerDown={(e) => {
        e.preventDefault();
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, w: width };
        document.body.style.cursor = "col-resize";
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const dx = e.clientX - start.current.x;
        set(start.current.w + (side === "right" ? dx : -dx));
      }}
      onPointerUp={() => {
        start.current = null;
        document.body.style.cursor = "";
      }}
      onDoubleClick={() => set(PANEL_LIMITS[panel].initial)}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 48 : 16;
        const grow = side === "right" ? "ArrowRight" : "ArrowLeft";
        const shrink = side === "right" ? "ArrowLeft" : "ArrowRight";
        if (e.key === grow) set(width + step);
        else if (e.key === shrink) set(width - step);
        else return;
        e.preventDefault();
      }}
    >
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent transition-colors group-hover:bg-water group-focus-visible:bg-focus group-active:bg-water" aria-hidden />
    </div>
  );
}
