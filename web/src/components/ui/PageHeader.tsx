import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { useSelection, type Screen } from "@/app/selection";
import { JOURNEY, journeyFor, nextJourney } from "@/app/journey";
import { cn } from "@/lib/cn";
import { buttonClass } from "./Button";

/**
 * Page header: the question this screen answers, in display type, with a one-line answer
 * or promise, page actions, and a quiet provenance row (docs/UI_SYSTEM.md › PageHeader).
 */
export function PageHeader({
  screen,
  title,
  lead,
  actions,
  meta,
  className,
  compact,
}: {
  screen?: Screen;
  title?: ReactNode;
  lead?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  const sel = useSelection();
  const j = journeyFor(screen ?? sel.screen);
  return (
    <header className={cn("flex flex-col gap-3 animate-rise", className)} data-tour="page-header">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-[880px]">
          <div className="eyebrow flex items-center gap-2">
            <span className="num grid h-5 w-5 place-items-center rounded-full bg-water text-[10.5px] font-bold tracking-normal text-on-water">{j.step}</span>
            <span>
              Step {j.step} of {JOURNEY.length} · {j.label}
            </span>
          </div>
          <h1 className={cn("display mt-2 text-ink", compact ? "text-[24px] leading-[1.15] md:text-[28px]" : "text-[28px] leading-[1.1] md:text-[34px]")}>{title ?? j.question}</h1>
          {lead !== null ? <div className="mt-2 max-w-[72ch] text-[14.5px] leading-relaxed text-ink-secondary">{lead ?? j.blurb}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {meta ? <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-ink-tertiary">{meta}</div> : null}
    </header>
  );
}

/** "Next question" link at the end of a screen: the guided path through the five steps. */
export function NextStep({ className, params }: { className?: string; params?: Partial<Record<string, string | null>> }) {
  const sel = useSelection();
  const n = nextJourney(sel.screen);
  if (!n) return null;
  return (
    <nav aria-label="Next step" className={cn("no-print", className)}>
      <a
        href={sel.hrefFor(n.screen, params)}
        onClick={(e) => {
          e.preventDefault();
          sel.go(n.screen, params);
        }}
        className="group flex items-center justify-between gap-4 rounded-[18px] border border-border bg-surface px-5 py-4 shadow-1 transition-[box-shadow,border-color] duration-150 hover:border-water/40 hover:shadow-2"
        data-testid="next-step"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] bg-water-soft text-water-deep" aria-hidden>
            {n.icon}
          </span>
          <span className="min-w-0">
            <span className="eyebrow block">Next · step {n.step}</span>
            <span className="block truncate text-[15px] font-semibold text-ink">{n.question}</span>
          </span>
        </span>
        <span className={buttonClass("primary", "md", "pointer-events-none shrink-0")}>
          {n.label}
          <ArrowRight size={15} className="transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
        </span>
      </a>
    </nav>
  );
}

/** A horizontal list of numbered steps (onboarding, tour progress). */
export function Stepper({
  steps,
  current,
  onSelect,
  className,
  label = "Progress",
  compact = false,
}: {
  steps: { id: string; label: ReactNode; state?: "done" | "current" | "todo" | "blocked" }[];
  current: number;
  onSelect?: (i: number) => void;
  className?: string;
  label?: string;
  /** Tighter dots for long sequences in narrow cards (the tour). */
  compact?: boolean;
}) {
  return (
    <ol className={cn("flex min-w-0 items-center", compact ? "gap-0.5" : "gap-1.5", className)} aria-label={label}>
      {steps.map((s, i) => {
        const state = s.state ?? (i < current ? "done" : i === current ? "current" : "todo");
        const dot = (
          <span
            className={cn(
              "block h-1.5 rounded-full transition-all duration-300",
              state === "current" ? (compact ? "w-4 bg-water" : "w-6 bg-water") : state === "done" ? "w-1.5 bg-water/55" : state === "blocked" ? "w-1.5 bg-warning" : "w-1.5 bg-border-strong/45",
            )}
          />
        );
        return (
          <li key={s.id} aria-current={state === "current" ? "step" : undefined}>
            {onSelect ? (
              <button type="button" className={cn("grid h-5 place-items-center", compact ? "px-[2px]" : "px-0.5")} onClick={() => onSelect(i)} aria-label={`Go to step ${i + 1}: ${typeof s.label === "string" ? s.label : ""}`}>
                {dot}
              </button>
            ) : (
              <span className="grid h-5 place-items-center px-0.5" title={typeof s.label === "string" ? s.label : undefined}>
                {dot}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
