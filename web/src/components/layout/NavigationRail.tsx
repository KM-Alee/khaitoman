/**
 * Primary navigation: the five journey steps (app/journey.tsx). Desktop shows them as a
 * numbered path in the top bar; mobile uses a bottom bar. Labels are plain; the PRD names
 * stay in tooltips and the command menu.
 */
import { NavLink } from "react-router";
import { useSelection, type Screen } from "@/app/selection";
import { JOURNEY } from "@/app/journey";
import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui/primitives";

export { BrandMark } from "@/components/ui/Art";

export interface NavItem {
  screen: Screen;
  also?: Screen[];
  label: string;
  icon: React.ReactNode;
  shortcut: string;
}

export const NAV: NavItem[] = JOURNEY.map((j) => ({ screen: j.screen, also: j.also, label: j.label, icon: j.icon, shortcut: j.shortcut }));

export function JourneyNav({ compact, className }: { compact?: boolean; className?: string }) {
  const sel = useSelection();
  const cur = JOURNEY.findIndex((j) => j.screen === sel.screen || j.also?.includes(sel.screen));
  return (
    <nav aria-label="Primary" className={cn("no-print", className)} data-tour="journey-nav">
      <ol className="flex items-center gap-0.5 rounded-[14px] border border-border/80 bg-surface-muted/70 p-1">
        {JOURNEY.map((j, i) => {
          const active = i === cur;
          return (
            <li key={j.screen} className="flex items-center">
              <Tooltip content={`${j.question} · ${j.precise} · ${j.shortcut}`} side="bottom">
                <NavLink
                  to={sel.hrefFor(j.screen)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex h-9 items-center gap-2 rounded-[10px] text-[13.5px] font-medium text-ink-secondary transition-[background-color,color,box-shadow] duration-150 hover:bg-surface hover:text-ink",
                    compact ? "px-2.5" : "px-3",
                    active && "bg-surface text-ink shadow-2 hover:bg-surface",
                  )}
                  data-testid={`nav-${j.screen}`}
                >
                  <span
                    className={cn(
                      "num grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold transition-colors",
                      active ? "bg-water text-on-water" : i < cur ? "bg-water-soft text-water-deep" : "bg-surface-sunken text-ink-tertiary",
                    )}
                    aria-hidden
                  >
                    {j.step}
                  </span>
                  <span className={cn(active && "font-semibold")}>{j.label}</span>
                </NavLink>
              </Tooltip>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Mobile bottom navigation. */
export function BottomNav() {
  const sel = useSelection();
  return (
    <nav aria-label="Primary" className="no-print grid h-16 shrink-0 grid-cols-5 border-t border-border bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
      {JOURNEY.map((j) => {
        const active = sel.screen === j.screen || j.also?.includes(sel.screen);
        return (
          <NavLink
            key={j.screen}
            to={sel.hrefFor(j.screen)}
            aria-current={active ? "page" : undefined}
            className={cn("relative flex flex-col items-center justify-center gap-1 text-ink-secondary transition-colors", active && "text-water-deep")}
          >
            {active ? <span className="absolute top-0 h-[3px] w-8 rounded-b-full bg-water" aria-hidden /> : null}
            {j.icon}
            <span className={cn("text-[11.5px] leading-none", active ? "font-semibold" : "font-medium")}>{j.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
