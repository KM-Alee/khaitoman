import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Buttons (docs/UI_SYSTEM.md › Components). One primary action per region; `hero` is the
 * single most important action on a page (landing, "Find the best plan", tour finish).
 */
export type ButtonVariant = "primary" | "hero" | "secondary" | "ghost" | "subtle" | "danger" | "inverse";
export type ButtonSize = "sm" | "md" | "lg" | "xl";

const base =
  "relative inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap select-none transition-[background-color,color,border-color,box-shadow,transform,opacity] duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-55 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-water text-on-water shadow-1 hover:bg-water-deep disabled:hover:bg-water [&_svg]:opacity-95",
  hero: "bg-water-grad text-on-water shadow-glow hover:brightness-[1.06] hover:shadow-3 disabled:hover:brightness-100",
  secondary: "bg-surface text-ink border border-border-strong/55 shadow-1 hover:bg-surface-muted hover:border-border-strong",
  ghost: "text-ink-secondary hover:text-ink hover:bg-surface-muted",
  subtle: "bg-surface-muted text-ink hover:bg-surface-sunken",
  danger: "bg-surface text-danger border border-danger/40 hover:bg-danger-soft",
  inverse: "bg-ink text-canvas hover:opacity-90",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px] rounded-[9px]",
  md: "h-9 px-3.5 text-sm rounded-[10px]",
  lg: "h-11 px-5 text-[15px] rounded-[12px]",
  xl: "h-13 px-6 text-[16px] font-semibold rounded-[14px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  trailing?: ReactNode;
  busy?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, trailing, busy, className, children, disabled, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonClass(variant, size, className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner /> : icon}
      {children}
      {trailing}
    </button>
  );
});

/** Class string for link elements styled as buttons. */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string) {
  return cn(base, variants[variant], sizes[size], className);
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  pressed?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = "ghost", size = "md", pressed, className, children, ...rest },
  ref,
) {
  const dim = size === "sm" ? "h-8 w-8 rounded-[9px]" : size === "lg" || size === "xl" ? "h-11 w-11 rounded-[12px]" : "h-9 w-9 rounded-[10px]";
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={cn(base, variants[variant], dim, "p-0", pressed && "bg-water-soft text-water-deep hover:bg-water-soft", className)}
      {...rest}
    >
      {children}
    </button>
  );
});

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      className={cn("inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-current border-r-transparent [animation:spin_0.8s_linear_infinite]", className)}
    />
  );
}
