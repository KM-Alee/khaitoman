/**
 * Headline numbers (docs/UI_SYSTEM.md › MetricTile).
 *
 * A MetricTile renders one server MetricValue with a plain label, its precise term behind
 * a <Term>, an optional server-computed delta and a one-line meaning. It never computes a
 * metric. In story mode (the guided tour) a value that has ALREADY arrived from the server
 * eases up from zero as an entrance flourish; screen readers get the final value at once,
 * reduced-motion users see it immediately, and values are never animated while loading or
 * between two different computed results.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { create } from "zustand";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { MetricValue } from "@/lib/api/types";
import { formatDelta, formatWithUnit } from "@/lib/formatting";
import { MetricValueView } from "@/components/status";
import { useReducedMotion } from "@/app/environment";
import type { TermId } from "@/lib/glossary";
import { cn } from "@/lib/cn";
import { Term } from "./Term";

/** Story mode is switched on by the guided tour only. */
export const useStoryMode = create<{ story: boolean; set: (v: boolean) => void }>((set) => ({ story: false, set: (story) => set({ story }) }));

/** Eases from 0 to `target` once per distinct target, only in story mode. */
export function useCountUp(target: number | null, ms = 1100): number | null {
  const story = useStoryMode((s) => s.story);
  const reduced = useReducedMotion();
  const [v, setV] = useState<number | null>(target);
  const raf = useRef(0);
  useEffect(() => {
    cancelAnimationFrame(raf.current);
    if (target === null || !story || reduced || !Number.isFinite(target) || target === 0) {
      setV(target);
      return;
    }
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      setV(k >= 1 ? target : target * e);
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    setV(0);
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, story, reduced, ms]);
  return v;
}

export function CountUpValue({ value, unit, className }: { value: number; unit: string; className?: string }) {
  const v = useCountUp(value);
  const final = formatWithUnit(value, unit);
  const shown = v === null ? final : v === value ? final : formatWithUnit(v, unit);
  return (
    <span className={className} data-value={value} data-unit={unit}>
      <span aria-hidden>{shown}</span>
      <span className="sr-only">{final}</span>
    </span>
  );
}

export interface TileDelta {
  value: number;
  unit: string;
  /** Which direction is good for this metric; "neutral" keeps the chip uncoloured. */
  goodWhen?: "up" | "down" | "neutral";
  /** What the delta is measured against, e.g. "vs today's routine". */
  against?: string;
}

export function DeltaChip({ d, className }: { d: TileDelta; className?: string }) {
  const zero = d.value === 0;
  const good = !zero && d.goodWhen && d.goodWhen !== "neutral" ? (d.value > 0) === (d.goodWhen === "up") : null;
  const Icon = zero ? Minus : d.value > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-semibold",
        good === true && "bg-vegetation-soft text-vegetation",
        good === false && "bg-danger-soft text-danger",
        good === null && "bg-surface-muted text-ink-secondary",
        className,
      )}
    >
      <Icon size={13} aria-hidden />
      {formatDelta(d.value, d.unit)}
      {d.against ? <span className="font-medium opacity-80">{d.against}</span> : null}
    </span>
  );
}

export function MetricTile({
  label,
  term,
  metric,
  delta,
  hint,
  size = "md",
  className,
  testId,
  accent,
}: {
  label: ReactNode;
  term?: TermId;
  metric: MetricValue | null | undefined;
  delta?: TileDelta | null;
  hint?: ReactNode;
  size?: "sm" | "md" | "lg" | "hero";
  className?: string;
  testId?: string;
  accent?: "water" | "wheat" | "none";
}) {
  const available = metric && metric.status === "available" && typeof metric.value === "number";
  const numCls = {
    sm: "num text-[17px] font-semibold tracking-[-0.01em]",
    md: "num text-[22px] font-semibold tracking-[-0.015em]",
    lg: "display-num text-[32px]",
    hero: "display-num text-[44px] md:text-[52px]",
  }[size];
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)} data-testid={testId} data-metric-status={metric?.status ?? "missing"}>
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink-secondary">
        {accent && accent !== "none" ? <span className={cn("h-2 w-2 shrink-0 rounded-full", accent === "water" ? "bg-water" : "bg-wheat")} aria-hidden /> : null}
        {term ? <Term id={term}>{label}</Term> : <span className="truncate">{label}</span>}
      </div>
      {available ? (
        <CountUpValue value={metric.value as number} unit={metric.unit} className={cn("leading-none text-ink", numCls)} />
      ) : (
        <MetricValueView metric={metric} size="sm" />
      )}
      {delta && available ? <DeltaChip d={delta} className="mt-1 self-start" /> : null}
      {hint ? <div className="text-[12px] leading-snug text-ink-tertiary">{hint}</div> : null}
    </div>
  );
}
