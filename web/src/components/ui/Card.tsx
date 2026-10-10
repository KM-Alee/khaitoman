import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Card: the basic grouped surface (docs/UI_SYSTEM.md › Components).
 * `tone="hero"` is reserved for the one decisive answer on a screen; `quiet` for secondary
 * groups that sit on a surface already.
 */
export function Card({
  children,
  className,
  tone = "default",
  as: Tag = "section",
  ...rest
}: { children: ReactNode; className?: string; tone?: "default" | "quiet" | "hero" | "accent"; as?: "section" | "div" | "article" | "aside" } & HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={cn(
        "rounded-[18px] border",
        tone === "default" && "border-border bg-surface shadow-1",
        tone === "quiet" && "border-border/70 bg-surface-muted/60",
        tone === "hero" && "border-water/25 bg-surface shadow-2 bg-dawn",
        tone === "accent" && "border-wheat/35 bg-wheat-soft/45",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function CardHeader({
  icon,
  eyebrow,
  title,
  description,
  aside,
  id,
  className,
}: {
  icon?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-5 pt-4 pb-3", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-water-soft text-water-deep" aria-hidden>
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          {eyebrow ? <div className="eyebrow mb-0.5">{eyebrow}</div> : null}
          <h2 id={id} className="text-[16px] font-semibold leading-snug tracking-[-0.012em] text-ink">
            {title}
          </h2>
          {description ? <div className="mt-1 max-w-[72ch] text-[13px] leading-relaxed text-ink-secondary">{description}</div> : null}
        </div>
      </div>
      {aside ? <div className="flex shrink-0 flex-wrap items-center gap-2">{aside}</div> : null}
    </header>
  );
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("px-5 pb-5", className)}>{children}</div>;
}

export function CardFooter({ children, className }: { children: ReactNode; className?: string }) {
  return <footer className={cn("flex flex-wrap items-center gap-2 border-t border-border px-5 py-3 text-[12px] text-ink-secondary", className)}>{children}</footer>;
}
