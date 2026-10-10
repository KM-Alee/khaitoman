/** Small labelled form and message parts for the onboarding wizard (tokens only, no raw colors). */
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { AlertTriangle, Ban, CheckCircle2, Info, XCircle } from "lucide-react";
import { describeError } from "@/lib/api/client";
import { cn } from "@/lib/cn";

const fieldCls =
  "w-full rounded-[10px] border border-border-strong/70 bg-surface px-3 text-[13px] text-ink shadow-1 placeholder:text-ink-tertiary hover:border-border-strong disabled:opacity-60 read-only:bg-surface-muted";

export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode; error?: string | null }>(
  function TextField({ label, hint, error, className, id, ...p }, ref) {
    const auto = useId();
    const fid = id ?? auto;
    return (
      <div className={cn("flex flex-col gap-1", className)}>
        <label htmlFor={fid} className="text-[12px] font-medium text-ink-secondary">
          {label}
        </label>
        <input
          ref={ref}
          id={fid}
          aria-invalid={error ? true : undefined}
          aria-describedby={hint || error ? `${fid}-hint` : undefined}
          className={cn(fieldCls, "h-9", error && "border-danger")}
          {...p}
        />
        {hint || error ? (
          <p id={`${fid}-hint`} className={cn("text-[12px]", error ? "text-danger" : "text-ink-secondary")}>
            {error ?? hint}
          </p>
        ) : null}
      </div>
    );
  },
);

export function TextArea({ label, hint, className, id, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: ReactNode; hint?: ReactNode }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={fid} className="text-[12px] font-medium text-ink-secondary">
        {label}
      </label>
      <textarea id={fid} aria-describedby={hint ? `${fid}-hint` : undefined} className={cn(fieldCls, "py-2")} {...p} />
      {hint ? (
        <p id={`${fid}-hint`} className="text-[12px] text-ink-secondary">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type AlertTone = "danger" | "warning" | "info" | "success";
const alertCls: Record<AlertTone, string> = {
  danger: "border-danger/40 bg-danger-soft text-ink",
  warning: "border-warning/40 bg-warning-soft text-ink",
  info: "border-border-strong/60 bg-surface-muted text-ink",
  success: "border-vegetation/40 bg-vegetation-soft text-ink",
};
const alertIcon: Record<AlertTone, ReactNode> = {
  danger: <XCircle size={16} aria-hidden className="mt-0.5 shrink-0 text-danger" />,
  warning: <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0 text-warning" />,
  info: <Info size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-secondary" />,
  success: <CheckCircle2 size={16} aria-hidden className="mt-0.5 shrink-0 text-vegetation" />,
};

export function Alert({
  tone,
  title,
  children,
  action,
  className,
  testId,
}: {
  tone: AlertTone;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      data-testid={testId}
      className={cn("flex gap-2.5 rounded-[12px] border px-3.5 py-3 text-[13px]", alertCls[tone], className)}
    >
      {alertIcon[tone]}
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{title}</div>
        {children ? <div className="mt-0.5 break-words text-ink-secondary">{children}</div> : null}
        {action ? <div className="mt-2 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}

/** API failure as an alert; field-level details from T9.3 errors are listed. */
export function ErrorAlert({ error, title, action, testId }: { error: unknown; title?: ReactNode; action?: ReactNode; testId?: string }) {
  const d = describeError(error);
  return (
    <Alert tone="danger" title={title ?? d.title} action={action} testId={testId}>
      {d.detail}
    </Alert>
  );
}

export function IssueList({ items, kind, empty }: { items: string[]; kind: "blocker" | "warning"; empty?: ReactNode }) {
  if (!items.length) return empty ? <p className="text-[13px] text-ink-secondary">{empty}</p> : null;
  return (
    <ul className="flex flex-col gap-1.5" aria-label={kind === "blocker" ? "Blockers" : "Warnings"}>
      {items.map((t, i) => (
        <li key={`${kind}-${i}`} className="flex gap-2 text-[13px] text-ink" data-kind={kind}>
          {kind === "blocker" ? (
            <Ban size={14} aria-hidden className="mt-0.5 shrink-0 text-danger" />
          ) : (
            <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
          )}
          <span>
            <span className="font-semibold">{kind === "blocker" ? "Blocker: " : "Warning: "}</span>
            {t}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Card({ id, title, aside, description, children, className, testId }: { id?: string; title: ReactNode; aside?: ReactNode; description?: ReactNode; children: ReactNode; className?: string; testId?: string }) {
  return (
    <section id={id} data-testid={testId} aria-labelledby={id ? `${id}-h` : undefined} className={cn("scroll-mt-4 rounded-[18px] border border-border bg-surface shadow-1", className)}>
      <header className="flex flex-wrap items-start justify-between gap-2 px-4 pb-2 pt-3.5">
        <div className="min-w-0">
          <h2 id={id ? `${id}-h` : undefined} className="text-[14px] font-semibold text-ink">
            {title}
          </h2>
          {description ? <p className="mt-0.5 text-[12px] text-ink-secondary">{description}</p> : null}
        </div>
        {aside ? <div className="flex flex-wrap items-center gap-1.5">{aside}</div> : null}
      </header>
      <div className="px-4 pb-4">{children}</div>
    </section>
  );
}
