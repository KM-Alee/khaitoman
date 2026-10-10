import { NavLink } from "react-router";
import { useSelection } from "@/app/selection";
import { cn } from "@/lib/cn";

export function CompareTabs() {
  const sel = useSelection();
  const tabs = [
    { screen: "compare" as const, label: "Baseline ladder" },
    { screen: "replay" as const, label: "Season replay" },
  ];
  return (
    <nav aria-label="Compare views" className="no-print flex h-11 shrink-0 items-center gap-1 border-b border-border bg-surface px-3">
      {tabs.map((t) => (
        <NavLink
          key={t.screen}
          to={sel.hrefFor(t.screen)}
          aria-current={sel.screen === t.screen ? "page" : undefined}
          className={cn(
            "relative inline-flex h-11 items-center px-3 text-[13px] font-medium text-ink-secondary hover:text-ink",
            sel.screen === t.screen && "text-ink after:absolute after:inset-x-2 after:bottom-0 after:h-[2px] after:rounded-full after:bg-water",
          )}
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function SubTabs({ tabs, value, onChange, label }: { tabs: { value: string; label: string; badge?: React.ReactNode }[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="no-print flex h-11 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "relative inline-flex h-11 shrink-0 items-center gap-1.5 px-3 text-[13px] font-medium text-ink-secondary hover:text-ink",
            value === t.value && "text-ink after:absolute after:inset-x-2 after:bottom-0 after:h-[2px] after:rounded-full after:bg-water",
          )}
        >
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}
