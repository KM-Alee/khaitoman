import { useState, type ReactNode } from "react";
import { ChevronRight, HelpCircle } from "lucide-react";
import { GLOSSARY, type GlossaryEntry, type TermId } from "@/lib/glossary";
import { cn } from "@/lib/cn";
import { Popover, PopoverContent, PopoverTrigger } from "./primitives";

function entry(id: TermId): GlossaryEntry {
  return GLOSSARY[id];
}

/**
 * A plain-language label whose precise term and meaning open on hover, focus or tap.
 * Keyboard: it is a button; Enter/Space opens it, Esc closes it.
 */
export function Term({ id, children, className, showPrecise }: { id: TermId; children?: ReactNode; className?: string; showPrecise?: boolean }) {
  const e = entry(id);
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn("term inline text-left align-baseline font-[inherit] text-inherit", className)}
          aria-label={`${typeof children === "string" ? children : e.plain}: what this means`}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          data-term={id}
        >
          {children ?? e.plain}
          {showPrecise ? <span className="ml-1 text-ink-tertiary">({e.precise})</span> : null}
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-[300px] p-0" onOpenAutoFocus={(ev) => ev.preventDefault()}>
        <TermCard e={e} />
      </PopoverContent>
    </Popover>
  );
}

export function TermCard({ e }: { e: GlossaryEntry }) {
  return (
    <div className="px-3.5 py-3">
      <div className="text-[13px] font-semibold text-ink">{e.plain}</div>
      <p className="mt-1 text-[12.5px] leading-relaxed text-ink-secondary">{e.explain}</p>
      <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-surface-muted px-2 py-0.5 font-mono text-[11px] text-ink-secondary">{e.precise}</div>
    </div>
  );
}

/** A small "?" button that opens a glossary entry; for use next to form labels. */
export function TermHint({ id, className }: { id: TermId; className?: string }) {
  const e = entry(id);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn("grid h-5 w-5 shrink-0 place-items-center rounded-full text-ink-tertiary transition-colors hover:bg-water-soft hover:text-water-deep", className)}
          aria-label={`What does “${e.plain}” mean?`}
          data-term={id}
        >
          <HelpCircle size={13} aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-[300px] p-0" onOpenAutoFocus={(ev) => ev.preventDefault()}>
        <TermCard e={e} />
      </PopoverContent>
    </Popover>
  );
}

/** "What this means" disclosure for a paragraph-level explanation under a heading. */
export function Explain({ children, label = "What this means", className, defaultOpen = false }: { children: ReactNode; label?: string; className?: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("text-[13px]", className)}>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 -ml-1.5 font-medium text-water-deep hover:bg-water-soft/70"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <HelpCircle size={13} aria-hidden />
        {label}
        <ChevronRight size={13} className={cn("transition-transform duration-150", open && "rotate-90")} aria-hidden />
      </button>
      {open ? <div className="mt-1.5 max-w-[68ch] animate-rise leading-relaxed text-ink-secondary">{children}</div> : null}
    </div>
  );
}
