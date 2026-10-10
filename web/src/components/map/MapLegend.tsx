import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { MapMetric } from "@/app/store";
import { formatWithUnit } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { GROUP_COLORS } from "./palette";
import { METRIC_DEFS, type FieldVisualResult } from "./useFieldVisuals";

export function MapLegend({ metric, visuals, className }: { metric: MapMetric; visuals: FieldVisualResult; className?: string }) {
  // Open by default only where it leaves the scene visible; one tap expands it on short screens.
  const [open, setOpen] = useState(() => typeof window === "undefined" || (window.innerHeight >= 880 && window.innerWidth >= 768));
  const def = metric !== "none" ? METRIC_DEFS[metric] : null;
  return (
    <div
      className={cn(
        "pointer-events-auto w-[248px] max-w-full rounded-[12px] border border-border bg-surface/95 text-[12px] shadow-2 backdrop-blur",
        className,
      )}
      data-testid="map-legend"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="min-w-0 truncate font-semibold text-ink">{def?.label ?? "Fields"}</span>
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}
      </button>
      {open ? (
        <div className="flex flex-col gap-2.5 border-t border-border px-3 pb-3 pt-2.5">
          {metric === "group" ? (
            <ul className="flex flex-col gap-1">
              {(["head", "middle", "tail"] as const).map((g) => (
                <li key={g} className="flex items-center gap-2 capitalize text-ink">
                  <span className="h-3 w-3 rounded-[3px]" style={{ background: GROUP_COLORS()[g] }} />
                  {g}
                  <span className="text-ink-tertiary">· height orders head → tail</span>
                </li>
              ))}
            </ul>
          ) : visuals.scale ? (
            <div>
              <div
                className="h-2.5 rounded-full"
                style={{ background: `linear-gradient(90deg, ${visuals.scale.stops.map((s) => `${s.color} ${s.t * 100}%`).join(", ")})` }}
                role="img"
                aria-label={`Colour scale from ${formatWithUnit(visuals.scale.domain[0], visuals.unit)} to ${formatWithUnit(visuals.scale.domain[1], visuals.unit)}`}
              />
              <div className="num mt-1 flex justify-between text-[11px] text-ink-secondary">
                <span>{formatWithUnit(visuals.scale.domain[0], visuals.unit)}</span>
                {visuals.scale.kind === "diverging" ? <span className="font-semibold text-ink">0</span> : null}
                <span>{formatWithUnit(visuals.scale.domain[1], visuals.unit)}</span>
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-[11px] text-ink-secondary">
                <span className="h-2.5 w-2.5 rounded-[3px] border border-border-strong" style={{ background: visuals.scale.noData }} />
                No value (shown low and flat)
              </div>
              <p className="mt-1 text-[11px] text-ink-tertiary">Block height and colour encode the same server value.</p>
            </div>
          ) : (
            <p className="text-[12px] text-ink-secondary" data-testid="legend-reason">
              {visuals.status === "loading" ? "Loading run results…" : visuals.reason ?? "No field values."}
            </p>
          )}
          <ul className="flex flex-col gap-1 border-t border-border pt-2 text-[11px] text-ink-secondary">
            <li className="flex items-center gap-2">
              <svg width="28" height="8" aria-hidden>
                <line x1="1" y1="4" x2="27" y2="4" stroke="var(--water)" strokeWidth="3" strokeLinecap="round" />
              </svg>
              Observed canal (declared edge)
            </li>
            <li className="flex items-center gap-2">
              <svg width="28" height="8" aria-hidden>
                <line x1="1" y1="4" x2="27" y2="4" stroke="var(--water)" strokeWidth="3" strokeDasharray="5 4" />
              </svg>
              Assumed connection
            </li>
            <li className="flex items-center gap-2">
              <svg width="28" height="8" aria-hidden>
                <circle cx="6" cy="4" r="2.5" fill="var(--water)" />
                <circle cx="16" cy="4" r="2.5" fill="var(--water)" opacity="0.7" />
                <circle cx="26" cy="4" r="2.5" fill="var(--water)" opacity="0.4" />
              </svg>
              Flow direction/activity only
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#5fbcc4] ring-2 ring-[#9a8466]" aria-hidden />
              Pond (fill level schematic)
              <span className="ml-auto inline-block h-2.5 w-2.5 rotate-45 bg-warning" aria-hidden />
              Pump
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}
