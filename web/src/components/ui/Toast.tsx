import * as ToastP from "@radix-ui/react-toast";
import { create } from "zustand";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ToastTone = "info" | "success" | "warning" | "danger";
interface ToastItem {
  id: number;
  title: string;
  description?: ReactNode;
  tone: ToastTone;
  action?: { label: string; onClick: () => void };
}
interface ToastStore {
  items: ToastItem[];
  push: (t: Omit<ToastItem, "id">) => void;
  remove: (id: number) => void;
}
let seq = 1;
export const useToasts = create<ToastStore>((set) => ({
  items: [],
  push: (t) => set((s) => ({ items: [...s.items.slice(-3), { ...t, id: seq++ }] })),
  remove: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
}));
export const toast = (t: Omit<ToastItem, "id">) => useToasts.getState().push(t);

const icons = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle };
const tones = {
  info: "text-water",
  success: "text-vegetation",
  warning: "text-warning",
  danger: "text-danger",
};

export function ToastRegion() {
  const { items, remove } = useToasts();
  return (
    <ToastP.Provider swipeDirection="right" duration={6000} label="Notifications">
      {items.map((t) => {
        const Icon = icons[t.tone];
        return (
          <ToastP.Root
            key={t.id}
            onOpenChange={(o) => !o && remove(t.id)}
            className="pointer-events-auto flex w-[min(380px,calc(100vw-24px))] items-start gap-3 rounded-[18px] border border-border bg-surface p-3.5 shadow-3"
          >
            <Icon size={18} className={cn("mt-0.5 shrink-0", tones[t.tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <ToastP.Title className="text-[13px] font-semibold text-ink">{t.title}</ToastP.Title>
              {t.description ? (
                <ToastP.Description className="mt-0.5 text-[12px] text-ink-secondary">{t.description}</ToastP.Description>
              ) : null}
              {t.action ? (
                <ToastP.Action altText={t.action.label} asChild>
                  <button
                    className="mt-2 text-[12px] font-semibold text-water hover:underline"
                    onClick={t.action.onClick}
                  >
                    {t.action.label}
                  </button>
                </ToastP.Action>
              ) : null}
            </div>
            <ToastP.Close aria-label="Dismiss" className="rounded-md p-0.5 text-ink-tertiary hover:text-ink">
              <X size={14} />
            </ToastP.Close>
          </ToastP.Root>
        );
      })}
      <ToastP.Viewport className="fixed bottom-4 right-4 z-[90] flex flex-col gap-2 outline-none" />
    </ToastP.Provider>
  );
}
