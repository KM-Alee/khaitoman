import { useEffect, useMemo, useRef, useState } from "react";
import * as DialogP from "@radix-ui/react-dialog";
import { Search } from "lucide-react";
import { useUI } from "@/app/store";
import { useSelection } from "@/app/selection";
import { usePilotData } from "@/app/pilotData";
import { JOURNEY } from "@/app/journey";
import { useTour } from "@/features/tour/store";
import { cn } from "@/lib/cn";

interface Cmd {
  id: string;
  group: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandMenu() {
  const open = useUI((s) => s.commandOpen);
  const set = useUI((s) => s.set);
  const sel = useSelection();
  const { sortedFields } = usePilotData();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  const cmds = useMemo<Cmd[]>(() => {
    const st = useUI.getState();
    const out: Cmd[] = [
      ...JOURNEY.map((n) => ({ id: `go-${n.screen}`, group: "Go to", label: `${n.label}: ${n.question}`, hint: n.shortcut, run: () => sel.go(n.screen) })),
      { id: "go-replay", group: "Go to", label: "Season replay", run: () => sel.go("replay") },
      { id: "go-report", group: "Go to", label: "Action plan and report", run: () => sel.go("report") },
      { id: "onboard", group: "Go to", label: "Add a new region (onboarding)", run: () => (window.location.href = "/onboarding") },
      { id: "tour", group: "Help", label: "Take the guided tour", run: () => useTour.getState().start(0) },
      { id: "present", group: "View", label: st.presentation ? "Exit presentation mode" : "Enter presentation mode", hint: "⇧P", run: () => set({ presentation: !st.presentation }) },
      { id: "mode", group: "View", label: st.mapMode === "3d" ? "Flat 2D map" : "3D map", run: () => set({ mapMode: st.mapMode === "3d" ? "2d" : "3d" }) },
      { id: "theme-l", group: "View", label: "Light theme", run: () => set({ theme: "light" }) },
      { id: "theme-d", group: "View", label: "Dark theme", run: () => set({ theme: "dark" }) },
      { id: "units", group: "View", label: st.areaUnit === "ha" ? "Show areas in acres" : "Show areas in hectares", run: () => set({ areaUnit: st.areaUnit === "ha" ? "acre" : "ha" }) },
      { id: "copilot", group: "Help", label: "Ask AabFlow (assistant)", run: () => set({ assistantOpen: true }) },
      ...sortedFields.map((f) => ({ id: `field-${f.id}`, group: "Fields", label: f.label, hint: f.group ?? undefined, run: () => sel.setParams({ field: f.id }, false) })),
    ];
    return out;
  }, [sel, set, sortedFields, open]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = t ? cmds.filter((c) => c.label.toLowerCase().includes(t) || c.group.toLowerCase().includes(t)) : cmds.filter((c) => c.group !== "Fields").concat(cmds.filter((c) => c.group === "Fields").slice(0, 6));
    return list.slice(0, 40);
  }, [cmds, q]);

  useEffect(() => {
    setIdx(0);
  }, [q, open]);
  useEffect(() => {
    if (!open) setQ("");
  }, [open]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${idx}"]`)?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const exec = (c: Cmd | undefined) => {
    if (!c) return;
    set({ commandOpen: false });
    c.run();
  };

  let lastGroup = "";
  return (
    <DialogP.Root open={open} onOpenChange={(o) => set({ commandOpen: o })}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-[80] bg-[var(--scrim)]" />
        <DialogP.Content className="fixed left-1/2 top-[12vh] z-[81] w-[min(600px,94vw)] -translate-x-1/2 overflow-hidden rounded-[20px] border border-border bg-surface-raised shadow-3 outline-none animate-pop" aria-describedby={undefined}>
          <DialogP.Title className="sr-only">Command menu</DialogP.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search size={16} className="text-ink-tertiary" aria-hidden />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Jump to a screen, field or setting…"
              aria-label="Command"
              role="combobox"
              aria-expanded
              aria-controls="cmd-list"
              aria-activedescendant={filtered[idx] ? `cmd-${filtered[idx].id}` : undefined}
              className="h-12 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-tertiary"
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setIdx((i) => Math.min(filtered.length - 1, i + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setIdx((i) => Math.max(0, i - 1));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  exec(filtered[idx]);
                }
              }}
            />
          </div>
          <ul id="cmd-list" role="listbox" ref={listRef} className="max-h-[52vh] overflow-y-auto p-1.5">
            {filtered.map((c, i) => {
              const header = c.group !== lastGroup ? c.group : null;
              lastGroup = c.group;
              return (
                <li key={c.id} role="presentation">
                  {header ? <div className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">{header}</div> : null}
                  <div
                    id={`cmd-${c.id}`}
                    role="option"
                    aria-selected={i === idx}
                    data-idx={i}
                    onMouseEnter={() => setIdx(i)}
                    onClick={() => exec(c)}
                    className={cn("flex cursor-pointer items-center justify-between rounded-[8px] px-2.5 py-2 text-[13px] text-ink", i === idx && "bg-surface-muted")}
                  >
                    <span>{c.label}</span>
                    {c.hint ? <span className="text-[11px] capitalize text-ink-tertiary">{c.hint}</span> : null}
                  </div>
                </li>
              );
            })}
            {!filtered.length ? <li className="px-3 py-6 text-center text-[13px] text-ink-secondary">No match.</li> : null}
          </ul>
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}
