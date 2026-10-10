import {
  forwardRef,
  useEffect,
  useId,
  useState,
  type HTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import * as TabsP from "@radix-ui/react-tabs";
import * as DialogP from "@radix-ui/react-dialog";
import * as TooltipP from "@radix-ui/react-tooltip";
import * as SliderP from "@radix-ui/react-slider";
import * as SwitchP from "@radix-ui/react-switch";
import * as ToggleGroupP from "@radix-ui/react-toggle-group";
import * as PopoverP from "@radix-ui/react-popover";
import { ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { IconButton } from "./Button";

/* ---------------------------------------------------------------- Tabs */
export const Tabs = TabsP.Root;
export function TabsList({ className, ...p }: TabsP.TabsListProps) {
  return (
    <TabsP.List
      className={cn("flex items-center gap-1 border-b border-border px-1", className)}
      {...p}
    />
  );
}
export function TabsTrigger({ className, ...p }: TabsP.TabsTriggerProps) {
  return (
    <TabsP.Trigger
      className={cn(
        "relative -mb-px inline-flex h-10 items-center gap-1.5 px-3 text-[13px] font-medium text-ink-secondary transition-colors hover:text-ink",
        "data-[state=active]:text-ink after:absolute after:inset-x-2 after:-bottom-px after:h-[2px] after:rounded-full after:bg-transparent data-[state=active]:after:bg-water",
        className,
      )}
      {...p}
    />
  );
}
export const TabsContent = TabsP.Content;

/* ---------------------------------------------------------------- Segmented control (ToggleGroup) */
export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegmentOption<T>[];
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <ToggleGroupP.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as T)}
      aria-label={label}
      className={cn("inline-flex rounded-[10px] bg-surface-muted p-0.5", className)}
    >
      {options.map((o) => (
        <ToggleGroupP.Item
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          title={o.title}
          className={cn(
            "inline-flex items-center justify-center gap-1.5 rounded-[8px] font-medium text-ink-secondary transition-colors",
            size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[13px]",
            "hover:text-ink data-[state=on]:bg-surface data-[state=on]:text-ink data-[state=on]:shadow-1 disabled:opacity-50",
          )}
        >
          {o.label}
        </ToggleGroupP.Item>
      ))}
    </ToggleGroupP.Root>
  );
}

/* ---------------------------------------------------------------- Tooltip */
export const TooltipProvider = TooltipP.Provider;
export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <TooltipP.Root delayDuration={250}>
      <TooltipP.Trigger asChild>{children}</TooltipP.Trigger>
      <TooltipP.Portal>
        <TooltipP.Content
          side={side}
          sideOffset={6}
          className="z-[80] max-w-[280px] rounded-[8px] bg-ink px-2.5 py-1.5 text-[12px] leading-snug text-canvas shadow-3"
        >
          {content}
          <TooltipP.Arrow className="fill-ink" />
        </TooltipP.Content>
      </TooltipP.Portal>
    </TooltipP.Root>
  );
}

/* ---------------------------------------------------------------- Popover */
export const Popover = PopoverP.Root;
export const PopoverTrigger = PopoverP.Trigger;
export function PopoverContent({ className, children, ...p }: PopoverP.PopoverContentProps) {
  return (
    <PopoverP.Portal>
      <PopoverP.Content
        sideOffset={8}
        className={cn("z-[70] rounded-[14px] border border-border bg-surface p-3 shadow-3 outline-none", className)}
        {...p}
      >
        {children}
      </PopoverP.Content>
    </PopoverP.Portal>
  );
}

/* ---------------------------------------------------------------- Dialog / Sheet */
export const Dialog = DialogP.Root;
export const DialogTrigger = DialogP.Trigger;
export const DialogClose = DialogP.Close;
export function DialogContent({
  title,
  description,
  children,
  className,
  side,
  wide,
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /** `side` renders a full-height sheet (mobile/drawers). */
  side?: "right" | "bottom" | "left";
  wide?: boolean;
}) {
  return (
    <DialogP.Portal>
      <DialogP.Overlay className="fixed inset-0 z-[60] bg-[var(--scrim)] backdrop-blur-[2px] data-[state=open]:animate-[fadein_200ms_ease-out]" />
      <DialogP.Content
        className={cn(
          "fixed z-[61] flex flex-col bg-surface shadow-3 outline-none",
          side === "right" && "inset-y-0 right-0 w-[min(440px,100vw)] border-l border-border",
          side === "left" && "inset-y-0 left-0 w-[min(360px,100vw)] border-r border-border",
          side === "bottom" && "inset-x-0 bottom-0 max-h-[92vh] rounded-t-[16px] border-t border-border",
          !side &&
            cn(
              "left-1/2 top-1/2 max-h-[88vh] -translate-x-1/2 -translate-y-1/2 rounded-[16px] border border-border",
              wide ? "w-[min(960px,94vw)]" : "w-[min(560px,94vw)]",
            ),
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <DialogP.Title className="text-[15px] font-semibold text-ink">{title}</DialogP.Title>
            {description ? (
              <DialogP.Description className="mt-0.5 text-[13px] text-ink-secondary">{description}</DialogP.Description>
            ) : (
              <DialogP.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</DialogP.Description>
            )}
          </div>
          <DialogP.Close asChild>
            <IconButton label="Close" size="sm">
              <X size={16} />
            </IconButton>
          </DialogP.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </DialogP.Content>
    </DialogP.Portal>
  );
}

/* ---------------------------------------------------------------- Switch */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  id?: string;
}) {
  const auto = useId();
  const sid = id ?? auto;
  return (
    <div className="flex items-start justify-between gap-3">
      <label htmlFor={sid} className="min-w-0 cursor-pointer">
        <span className="block text-[13px] font-medium text-ink">{label}</span>
        {description ? <span className="block text-[12px] text-ink-secondary">{description}</span> : null}
      </label>
      <SwitchP.Root
        id={sid}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onChange}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-border-strong bg-surface-sunken transition-colors data-[state=checked]:border-water data-[state=checked]:bg-water disabled:opacity-50"
      >
        <SwitchP.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-surface shadow-1 transition-transform data-[state=checked]:translate-x-[17px]" />
      </SwitchP.Root>
    </div>
  );
}

/* ---------------------------------------------------------------- Select (native for a11y + mobile) */
export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> & { label?: ReactNode; hint?: ReactNode; compact?: boolean }
>(function Select({ label, hint, className, children, id, compact, ...p }, ref) {
  const auto = useId();
  const sid = id ?? auto;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {label ? (
        <label htmlFor={sid} className="text-[12px] font-medium text-ink-secondary">
          {label}
        </label>
      ) : null}
      <div className="relative">
        <select
          ref={ref}
          id={sid}
          className={cn(
            "w-full appearance-none rounded-[10px] border border-border-strong/70 bg-surface pl-3 pr-8 text-[13px] text-ink shadow-1 transition-colors hover:border-border-strong disabled:opacity-60",
            compact ? "h-8" : "h-9",
          )}
          {...p}
        >
          {children}
        </select>
        <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-secondary" />
      </div>
      {hint ? <p className="text-[12px] text-ink-secondary">{hint}</p> : null}
    </div>
  );
});

/* ---------------------------------------------------------------- Slider + numeric entry (T10.5) */
export function SliderField({
  label,
  value,
  onChange,
  onCommit,
  min,
  max,
  step,
  format,
  parse,
  unit,
  hint,
  warning,
  disabled,
  inputWidth = "w-[118px]",
}: {
  label: ReactNode;
  value: number;
  onChange: (v: number) => void;
  /** Called on release / blur — validation, never a solve per pixel. */
  onCommit?: (v: number) => void;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  parse: (s: string) => number | null;
  unit?: string;
  hint?: ReactNode;
  warning?: ReactNode;
  disabled?: boolean;
  inputWidth?: string;
}) {
  const id = useId();
  const [text, setText] = useState(format(value));
  const [focused, setFocused] = useState(false);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    if (!focused) setText(format(value));
  }, [value, focused, format]);
  const commitText = () => {
    const v = parse(text);
    if (v === null || v < min || v > max) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onChange(v);
    onCommit?.(v);
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-[12px] font-medium text-ink-secondary">
          {label}
        </label>
        <div className="relative">
          <input
            id={id}
            inputMode="decimal"
            disabled={disabled}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? `${id}-err` : undefined}
            className={cn(
              "num h-8 rounded-[8px] border bg-surface px-2 text-right text-[13px] font-medium text-ink",
              invalid ? "border-danger" : "border-border-strong/70",
              unit ? "pr-9" : "",
              inputWidth,
            )}
            value={text}
            onFocus={() => setFocused(true)}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => {
              setFocused(false);
              commitText();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                commitText();
                (e.target as HTMLInputElement).blur();
              }
              if (e.key === "Escape") {
                setText(format(value));
                setInvalid(false);
              }
            }}
          />
          {unit ? (
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-ink-tertiary">{unit}</span>
          ) : null}
        </div>
      </div>
      <SliderP.Root
        className="relative flex h-5 touch-none select-none items-center"
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={([v]) => onChange(v)}
        onValueCommit={([v]) => onCommit?.(v)}
        aria-label={typeof label === "string" ? label : undefined}
      >
        <SliderP.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-surface-sunken">
          <SliderP.Range className="absolute h-full rounded-full bg-water" />
        </SliderP.Track>
        <SliderP.Thumb
          aria-label={typeof label === "string" ? label : "Value"}
          className="block h-[18px] w-[18px] rounded-full border-2 border-water bg-surface shadow-2 transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        />
      </SliderP.Root>
      {invalid ? (
        <p id={`${id}-err`} className="text-[12px] text-danger">
          Enter a value between {format(min)} and {format(max)}{unit ? ` ${unit}` : ""}.
        </p>
      ) : warning ? (
        <div className="text-[12px] text-warning">{warning}</div>
      ) : hint ? (
        <p className="text-[12px] text-ink-secondary">{hint}</p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- Layout bits */
export function Section({
  title,
  aside,
  children,
  className,
  id,
  description,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
  description?: ReactNode;
}) {
  return (
    <section id={id} className={cn("rounded-[14px] border border-border bg-surface shadow-1", className)} aria-labelledby={title && id ? `${id}-h` : undefined}>
      {title ? (
        <header className="flex items-start justify-between gap-3 px-4 pb-2 pt-3.5">
          <div className="min-w-0">
            <h2 id={id ? `${id}-h` : undefined} className="text-[13px] font-semibold tracking-[-0.005em] text-ink">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-[12px] text-ink-secondary">{description}</p> : null}
          </div>
          {aside ? <div className="flex shrink-0 items-center gap-1.5">{aside}</div> : null}
        </header>
      ) : null}
      <div className={cn(title ? "px-4 pb-4" : "p-4")}>{children}</div>
    </section>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-tertiary", className)}>{children}</div>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border border-border-strong/60 bg-surface-muted px-1 font-sans text-[11px] font-medium text-ink-secondary">
      {children}
    </kbd>
  );
}

export function Divider({ className }: { className?: string }) {
  return <hr className={cn("border-0 border-t border-border", className)} />;
}

export function DL({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-ink-secondary">{k}</dt>
          <dd className="num min-w-0 truncate text-right text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export const VisuallyHidden = forwardRef<HTMLSpanElement, HTMLAttributes<HTMLSpanElement>>(function VH(p, ref) {
  return <span ref={ref} className="sr-only" {...p} />;
});
