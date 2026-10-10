/**
 * Sub-navigation inside a journey step. `CompareTabs` switches between routes (Compare,
 * Season replay); `SubTabs` switches a `?tab=` within one screen. Both are pill rails that
 * scroll horizontally on narrow screens instead of wrapping.
 */
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { useSelection } from "@/app/selection";
import { cn } from "@/lib/cn";

const rail = "no-print flex h-14 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3 md:px-6";
const pill = (on: boolean) =>
  cn(
    "relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[10px] px-3.5 text-[13.5px] font-medium transition-[background-color,color,box-shadow] duration-150",
    on ? "bg-surface text-ink shadow-2 ring-1 ring-border" : "text-ink-secondary hover:bg-surface-muted hover:text-ink",
  );

export function CompareTabs() {
  const sel = useSelection();
  const tabs = [
    { screen: "compare" as const, label: "Plans side by side" },
    { screen: "replay" as const, label: "Season replay" },
  ];
  return (
    <nav aria-label="Compare views" className={rail}>
      {tabs.map((t) => (
        <NavLink key={t.screen} to={sel.hrefFor(t.screen)} aria-current={sel.screen === t.screen ? "page" : undefined} className={pill(sel.screen === t.screen)}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function SubTabs({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { value: string; label: string; hint?: string; icon?: ReactNode; badge?: ReactNode }[];
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={rail}>
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={value === t.value}
          title={t.hint}
          onClick={() => onChange(t.value)}
          className={pill(value === t.value)}
          data-tab={t.value}
        >
          {t.icon ? <span className={cn("text-ink-tertiary", value === t.value && "text-water")}>{t.icon}</span> : null}
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}
