import { NavLink } from "react-router";
import {
  BookOpenCheck,
  GitCompareArrows,
  Leaf,
  Map as MapIcon,
  MessageSquareText,
  PlusCircle,
  Telescope,
} from "lucide-react";
import type { ReactNode } from "react";
import { useSelection, type Screen } from "@/app/selection";
import { useUI } from "@/app/store";
import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui/primitives";

export interface NavItem {
  screen: Screen;
  also?: Screen[];
  label: string;
  icon: ReactNode;
  shortcut: string;
}

export const NAV: NavItem[] = [
  { screen: "workspace", label: "Workspace", icon: <MapIcon size={20} />, shortcut: "1" },
  { screen: "compare", also: ["replay"], label: "Compare", icon: <GitCompareArrows size={20} />, shortcut: "2" },
  { screen: "explore", label: "Explore", icon: <Telescope size={20} />, shortcut: "3" },
  { screen: "impact", also: ["report"], label: "Impact", icon: <Leaf size={20} />, shortcut: "4" },
  { screen: "evidence", label: "Evidence", icon: <BookOpenCheck size={20} />, shortcut: "5" },
];

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="aab-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0fa3b1" />
          <stop offset="1" stopColor="#075e68" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#aab-g)" />
      <path d="M6 20.5c3.2 0 3.2-2.4 6.4-2.4s3.2 2.4 6.4 2.4 3.2-2.4 6.4-2.4" fill="none" stroke="#e8fbfc" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M6 25c3.2 0 3.2-2.4 6.4-2.4s3.2 2.4 6.4 2.4 3.2-2.4 6.4-2.4" fill="none" stroke="#e8fbfc" strokeOpacity=".55" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M16 6.5c2.6 3.4 4 5.8 4 7.5a4 4 0 0 1-8 0c0-1.7 1.4-4.1 4-7.5Z" fill="#e8fbfc" />
    </svg>
  );
}

export function NavigationRail() {
  const sel = useSelection();
  const inspectorTab = useUI((s) => s.inspectorTab);
  const set = useUI((s) => s.set);
  return (
    <nav aria-label="Primary" className="no-print flex h-full w-[var(--rail-w)] shrink-0 flex-col items-center border-r border-border bg-surface py-3">
      <NavLink to="/" aria-label="AabFlow home" className="mb-4 rounded-[10px]">
        <BrandMark className="h-9 w-9" />
      </NavLink>
      <ul className="flex flex-col items-center gap-1">
        {NAV.map((n) => {
          const active = sel.screen === n.screen || n.also?.includes(sel.screen);
          return (
            <li key={n.screen}>
              <Tooltip content={`${n.label} · ${n.shortcut}`} side="right">
                <NavLink
                  to={sel.hrefFor(n.screen)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex h-11 w-11 flex-col items-center justify-center gap-0.5 rounded-[12px] text-ink-secondary transition-colors hover:bg-surface-muted hover:text-ink",
                    active && "bg-water-soft text-water-deep hover:bg-water-soft hover:text-water-deep",
                  )}
                >
                  {active ? <span className="absolute -left-2 top-2.5 h-7 w-[3px] rounded-r-full bg-water" aria-hidden /> : null}
                  {n.icon}
                  <span className="sr-only">{n.label}</span>
                </NavLink>
              </Tooltip>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto flex flex-col items-center gap-1">
        <Tooltip content="Add region (onboarding)" side="right">
          <NavLink
            to="/onboarding"
            className="flex h-12 w-12 flex-col items-center justify-center gap-0.5 rounded-[12px] text-ink-secondary hover:bg-surface-muted hover:text-ink"
          >
            <PlusCircle size={20} />
            <span className="sr-only">Add region</span>
          </NavLink>
        </Tooltip>
        <Tooltip content="Copilot" side="right">
          <button
            type="button"
            aria-pressed={inspectorTab === "copilot"}
            onClick={() => set({ inspectorTab: inspectorTab === "copilot" ? "field" : "copilot", inspectorOpen: true })}
            className={cn(
              "flex h-12 w-12 flex-col items-center justify-center gap-0.5 rounded-[12px] text-ink-secondary hover:bg-surface-muted hover:text-ink",
              inspectorTab === "copilot" && "bg-water-soft text-water-deep",
            )}
          >
            <MessageSquareText size={20} />
            <span className="sr-only">Copilot</span>
          </button>
        </Tooltip>
      </div>
    </nav>
  );
}

/** Mobile bottom navigation. */
export function BottomNav() {
  const sel = useSelection();
  return (
    <nav aria-label="Primary" className="no-print grid h-16 shrink-0 grid-cols-5 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)]">
      {NAV.map((n) => {
        const active = sel.screen === n.screen || n.also?.includes(sel.screen);
        return (
          <NavLink
            key={n.screen}
            to={sel.hrefFor(n.screen)}
            aria-current={active ? "page" : undefined}
            className={cn("flex flex-col items-center justify-center gap-1 text-ink-secondary", active && "text-water-deep")}
          >
            {n.icon}
            <span className="text-[12px] font-medium leading-none">{n.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
