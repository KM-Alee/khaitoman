/**
 * "Ask AabFlow" (F19). Fills the assistant slot (docs/UI_SYSTEM.md §7). Each question is sent
 * with what the visitor is looking at (pilot, scenario, run, field, date, screen); the server
 * pins that context, streams plain-language progress and returns a validated answer built
 * from tool results. Without a configured key the panel says so honestly and keeps the
 * deterministic "Why this plan" view. Nothing here computes or invents a number.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ArrowUp, History, MessageSquarePlus, Square, WifiOff } from "lucide-react";
import { useSelection } from "@/app/selection";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useRun } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { IconButton } from "@/components/ui/Button";
import { Popover, PopoverContent, PopoverTrigger, Segmented } from "@/components/ui/primitives";
import { formatDateTime, shortId } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { PLAN_PLAIN } from "./format";
import { useCopilotSessions, useCopilotStatus } from "./api";
import { cancel, isBusy, markIntentsApplied, openSession, reset, restore, retry, send, useConversation } from "./conversation";
import { useCopilotNav } from "./nav";
import { suggestQuestions } from "./suggestions";
import { TurnCard } from "./TurnCard";
import { WhyThisPlan } from "./WhyThisPlan";
import type { CopilotLanguage, UIContext } from "./types";

const MAX_CHARS = 4000;
const LANGS: { value: CopilotLanguage; label: string; title: string }[] = [
  { value: "en", label: "EN", title: "Answer in English" },
  { value: "ur", label: "اردو", title: "Answer in Urdu" },
  { value: "roman_ur", label: "Roman", title: "Answer in Roman Urdu" },
];

function readLang(): CopilotLanguage {
  try {
    const v = localStorage.getItem("aabflow-copilot-lang");
    return v === "ur" || v === "roman_ur" ? v : "en";
  } catch {
    return "en";
  }
}

type Gate = { kind: "loading" } | { kind: "ready"; model: string } | { kind: "unavailable"; title: string; detail: string; note?: string };

export function CopilotPanel() {
  const sel = useSelection();
  const { fieldIndex, pilot } = usePilotData();
  const status = useCopilotStatus();
  const run = useRun(sel.runId);
  const active = useUI((s) => s.active[sel.pilotKey]);
  const conv = useConversation(sel.pilotKey);
  const nav = useCopilotNav();
  const [draft, setDraft] = useState("");
  const [lang, setLang] = useState<CopilotLanguage>(readLang);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const sessions = useCopilotSessions(status.data?.mounted === true && status.data.status.configured);

  const gate: Gate = useMemo(() => {
    if (status.isLoading) return { kind: "loading" };
    if (status.error) {
      const e = describeError(status.error);
      return { kind: "unavailable", title: e.title, detail: e.detail };
    }
    const d = status.data!;
    if (!d.mounted) return { kind: "unavailable", title: "The assistant is not part of this build", detail: "This API does not expose the copilot routes." };
    if (!d.status.configured)
      return {
        kind: "unavailable",
        title: "The assistant is offline",
        detail: d.status.reason ?? "No hosted-model key is configured on this server.",
        note: d.status.offline_note,
      };
    return { kind: "ready", model: d.status.model };
  }, [status.isLoading, status.error, status.data]);

  const ready = gate.kind === "ready";
  const busy = conv.turns.some(isBusy);
  const runData = run.data;
  const fieldLabel = sel.fieldId ? (fieldIndex.get(sel.fieldId)?.label ?? sel.fieldId.replace(/^[^:]+:/, "")) : null;
  const pilotName = pilot.data?.pilot?.name ?? sel.pilotId ?? "";

  const context: UIContext = useMemo(
    () => ({
      pilot_id: sel.pilotId ?? null,
      pilot_version: sel.version ?? null,
      scenario_revision_id: runData?.scenario_revision_id ?? active?.revisionId ?? null,
      selected_run_id: sel.runId,
      selected_field_id: sel.fieldId,
      timeline_date: sel.date && /^\d{4}-\d{2}-\d{2}$/.test(sel.date) ? sel.date : null,
      view: sel.screen,
      language: lang,
      units: "metric",
    }),
    [sel.pilotId, sel.version, sel.runId, sel.fieldId, sel.date, sel.screen, runData?.scenario_revision_id, active?.revisionId, lang],
  );

  useEffect(() => {
    if (ready) void restore(sel.pilotKey);
  }, [ready, sel.pilotKey]);

  // Server view intents apply once, after a live turn finishes (navigate_view, T11.2).
  useEffect(() => {
    for (const t of conv.turns) {
      if (t.live && !t.intentsApplied && t.viewIntents.length && (t.status === "completed" || t.status === "clarification")) {
        for (const i of t.viewIntents) nav.applyIntent(i);
        markIntentsApplied(sel.pilotKey, t.key);
      }
    }
  }, [conv.turns, nav, sel.pilotKey]);

  // Follow the newest content while the reader is near the bottom.
  const last = conv.turns[conv.turns.length - 1];
  const sig = last ? `${conv.turns.length}:${last.status}:${last.steps.length}:${last.partial.length}:${!!last.answer}` : "";
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 260 || last?.status === "sending") el.scrollTop = el.scrollHeight;
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (ready) input.current?.focus({ preventScroll: true });
  }, [ready]);

  const ask = (text: string) => {
    const m = text.trim();
    if (!m || busy || !ready) return;
    setDraft("");
    void send(sel.pilotKey, m.slice(0, MAX_CHARS), context);
  };
  const setLanguage = (l: CopilotLanguage) => {
    setLang(l);
    try {
      localStorage.setItem("aabflow-copilot-lang", l);
    } catch {
      /* not persisted */
    }
  };

  const suggestions = suggestQuestions({
    screen: sel.screen,
    hasRun: !!sel.runId,
    planKind: runData?.plan_kind,
    runHasPlan: runData ? runData.outcome === "plan" : undefined,
    fieldLabel,
    hasAnalysis: !!sel.analysisId,
    tab: sel.tab,
  });

  if (gate.kind === "loading") {
    return (
      <div className="flex h-full flex-col gap-3 p-4" aria-busy="true">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-24" />
        <Skeleton className="h-10" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="copilot-panel">
      {/* context strip */}
      <div className="flex shrink-0 items-center gap-1.5 border-b border-border px-3 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1" aria-label="What the assistant will look at" data-testid="copilot-context">
          <Chip size="sm" tone="neutral">
            {pilotName || "No watercourse"}
          </Chip>
          {runData ? (
            <Chip size="sm" tone="water" title={runData.run_id}>
              {PLAN_PLAIN[runData.plan_kind] ?? runData.plan_kind} · {shortId(runData.run_id)}
            </Chip>
          ) : null}
          {fieldLabel ? (
            <Chip size="sm" tone="wheat">
              Field {fieldLabel}
            </Chip>
          ) : null}
        </div>
        {ready ? (
          <>
            <HistoryMenu
              sessions={sessions.data?.sessions ?? []}
              loading={sessions.isFetching}
              current={conv.sessionId}
              onOpen={(id) => void openSession(sel.pilotKey, id)}
              onRefresh={() => void sessions.refetch()}
            />
            <IconButton label="New conversation" size="sm" onClick={() => reset(sel.pilotKey)} disabled={busy || !conv.turns.length}>
              <MessageSquarePlus size={15} />
            </IconButton>
          </>
        ) : null}
      </div>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3.5 py-4" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" tabIndex={0}>
        {gate.kind === "unavailable" ? (
          <div className="flex flex-col gap-3">
            <StatePanel state="blocked" compact title={gate.title} art="trust">
              <span data-testid="copilot-unavailable">
                {gate.detail} {gate.note ?? "Saved results, the map, the plan settings and the deterministic explanation below keep working."}
              </span>
            </StatePanel>
            <WhyThisPlan key={sel.runId ?? "none"} runId={sel.runId} defaultOpen />
          </div>
        ) : conv.restoring ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-10 w-3/4 self-end" />
            <Skeleton className="h-32" />
          </div>
        ) : conv.turns.length ? (
          <div className="flex flex-col gap-6">
            {conv.turns.map((t, i) => (
              <TurnCard
                key={t.key}
                t={t}
                latest={i === conv.turns.length - 1}
                ctx={{ lang, onAsk: ask, busy }}
                onRetry={() => void retry(sel.pilotKey, t, context)}
                onStop={() => void cancel(sel.pilotKey, t)}
              />
            ))}
          </div>
        ) : (
          <Welcome suggestions={suggestions} onAsk={ask} note={conv.restoreNote} />
        )}
      </div>

      {ready ? (
        <form
          className="shrink-0 border-t border-border bg-surface px-3 pb-3 pt-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            ask(draft);
          }}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <Segmented size="sm" label="Answer language" value={lang} onChange={setLanguage} options={LANGS.map((l) => ({ value: l.value, label: l.value === "ur" ? <span lang="ur" className="urdu leading-none">{l.label}</span> : l.label, title: l.title }))} />
            <span className="truncate text-[11px] text-ink-tertiary">Hosted model · {gate.model}</span>
          </div>
          <div className="flex items-end gap-2 rounded-[14px] border border-border bg-surface-raised px-2.5 py-2 shadow-1 focus-within:border-water focus-within:ring-2 focus-within:ring-focus/40">
            <textarea
              ref={input}
              value={draft}
              onChange={(e) => setDraft(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  ask(draft);
                }
              }}
              rows={1}
              dir="auto"
              placeholder={lang === "ur" ? "اپنا سوال لکھیں…" : "Ask about this plan, a field, money or water…"}
              aria-label="Your question"
              className="max-h-40 min-h-[24px] flex-1 resize-none bg-transparent text-[13.5px] leading-relaxed text-ink outline-none placeholder:text-ink-tertiary focus-visible:outline-none"
              style={{ fieldSizing: "content" } as CSSProperties}
              data-testid="copilot-input"
            />
            {busy ? (
              <IconButton
                label="Stop"
                size="sm"
                type="button"
                onClick={() => {
                  const t = conv.turns.find(isBusy);
                  if (t) void cancel(sel.pilotKey, t);
                }}
              >
                <Square size={14} />
              </IconButton>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                aria-label="Send"
                className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-water text-on-water shadow-1 transition-colors hover:bg-water-deep disabled:opacity-40"
                data-testid="copilot-send"
              >
                <ArrowUp size={16} aria-hidden />
              </button>
            )}
          </div>
          <p className="mt-1.5 text-[10.5px] leading-snug text-ink-tertiary">Enter to send · Shift+Enter for a new line · answers can be wrong; numbers are checked against the app's results.</p>
        </form>
      ) : (
        <div className="shrink-0 border-t border-border px-3.5 py-2.5 text-[11.5px] text-ink-tertiary">
          <WifiOff size={11} aria-hidden className="mr-1 inline" /> Conversation needs the hosted model; everything else works offline.
        </div>
      )}
    </div>
  );
}

function Welcome({ suggestions, onAsk, note }: { suggestions: ReturnType<typeof suggestQuestions>; onAsk: (q: string) => void; note: string | null }) {
  return (
    <div className="flex flex-col gap-4 animate-rise" data-testid="copilot-welcome">
      <div className="rounded-[18px] bg-dawn p-4">
        <p className="display text-[20px] leading-tight text-ink">Ask anything about this watercourse.</p>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-secondary">
          I read the same plans, maps and water books you see, run what-ifs when you ask, and answer with charts. Every number comes from the app's own results.
        </p>
      </div>
      {note ? <p className="text-[12px] text-ink-secondary">{note}</p> : null}
      <div className="flex flex-col gap-1.5" aria-label="Suggested questions">
        {suggestions.map((s) => (
          <button
            key={s.text}
            type="button"
            onClick={() => onAsk(s.text)}
            lang={s.lang}
            dir="auto"
            className={cn(
              "group flex items-center gap-2.5 rounded-[12px] border border-border bg-surface px-3 py-2 text-left text-[13px] leading-snug text-ink shadow-1 transition-colors hover:border-water/40 hover:bg-water-soft/50",
              s.lang === "ur" && "urdu",
            )}
            data-testid="copilot-suggestion"
          >
            <span className="shrink-0 rounded-full bg-surface-muted px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary group-hover:bg-water-soft group-hover:text-water-deep">
              {s.tag}
            </span>
            <span className="min-w-0">{s.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function HistoryMenu({
  sessions,
  loading,
  current,
  onOpen,
  onRefresh,
}: {
  sessions: { session_id: string; title?: string | null; turns: number; last_turn_at?: string | null; created_at: string }[];
  loading: boolean;
  current: string | null;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) onRefresh();
      }}
    >
      <PopoverTrigger asChild>
        <IconButton label="Earlier conversations" size="sm">
          <History size={15} />
        </IconButton>
      </PopoverTrigger>
      <PopoverContent className="w-[300px] max-w-[90vw] p-1.5" align="end">
        <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-tertiary">Earlier conversations</p>
        {loading && !sessions.length ? <Skeleton className="m-2 h-10" /> : null}
        {!loading && !sessions.filter((s) => s.turns > 0).length ? <p className="px-2 py-2 text-[12.5px] text-ink-secondary">No saved conversations yet.</p> : null}
        <ul className="max-h-[320px] overflow-y-auto">
          {sessions
            .filter((s) => s.turns > 0)
            .map((s) => (
              <li key={s.session_id}>
                <button
                  type="button"
                  onClick={() => {
                    onOpen(s.session_id);
                    setOpen(false);
                  }}
                  className={cn("flex w-full flex-col rounded-[10px] px-2 py-1.5 text-left hover:bg-surface-muted", s.session_id === current && "bg-water-soft/60")}
                >
                  <span className="line-clamp-1 text-[12.5px] text-ink" dir="auto">
                    {s.title ?? "Conversation"}
                  </span>
                  <span className="text-[11px] text-ink-tertiary">
                    {s.turns} {s.turns === 1 ? "question" : "questions"} · {formatDateTime(s.last_turn_at ?? s.created_at)}
                  </span>
                </button>
              </li>
            ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

