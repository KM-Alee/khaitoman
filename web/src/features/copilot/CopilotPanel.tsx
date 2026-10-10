/**
 * Copilot region (F19, T11). Gated on GET /copilot/status: when the provider is not
 * configured (or the API build has no copilot routes) the panel says so with the server's
 * own words and keeps the deterministic "Why this plan" explanation and core tools usable.
 * When connected, each question is sent with the current pilot/revision/run/field context;
 * the server pins it per turn, streams tool activity over SSE and returns a validated,
 * cited answer. Nothing in this panel invents or recomputes a number.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Bot, Compass, FileText, GitCompareArrows, MessageSquarePlus, PlayCircle, RefreshCw, Sparkles, Telescope, WifiOff } from "lucide-react";
import { useSelection } from "@/app/selection";
import { usePilotData } from "@/app/pilotData";
import { useCapabilities, useRun } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { IconButton } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { shortId } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { useCopilotStatus, useRunExplanations, type CopilotLanguage, type UIContext } from "./api";
import { cancel, loadToolCalls, markIntentsApplied, reset, restore, retry, send, useConversation } from "./conversation";
import { useCopilotNav } from "./nav";
import { TurnView } from "./TurnView";
import { WhyThisPlan, suggestedQuestions } from "./WhyThisPlan";

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

type Gate =
  | { kind: "loading" }
  | { kind: "available"; model: string; note: string; versions: string }
  | { kind: "not_configured"; model: string; note: string; versions: string }
  | { kind: "not_mounted"; reason: string; detail: string }
  | { kind: "error"; title: string; detail: string };

export function CopilotPanel() {
  const sel = useSelection();
  const { fieldIndex, pilot } = usePilotData();
  const status = useCopilotStatus();
  const caps = useCapabilities();
  const run = useRun(sel.runId);
  const conv = useConversation(sel.pilotKey);
  const nav = useCopilotNav();
  const [draft, setDraft] = useState("");
  const [lang, setLang] = useState<CopilotLanguage>(readLang);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const expl = useRunExplanations(sel.runId);

  const gate: Gate = useMemo(() => {
    if (status.isLoading) return { kind: "loading" };
    if (status.error) {
      const e = describeError(status.error);
      return { kind: "error", title: e.title, detail: e.detail };
    }
    const d = status.data!;
    if (!d.mounted) {
      const f = (caps.data?.features as Record<string, { status?: string; reason?: string | null }> | undefined)?.copilot;
      return {
        kind: "not_mounted",
        reason: f?.reason ?? "This API build does not expose the copilot routes.",
        detail: "GET /api/v2/copilot/status returned 404",
      };
    }
    const versions = `${d.status.prompt_version} · ${d.status.tool_schema_version}`;
    return d.status.configured
      ? { kind: "available", model: d.status.model, note: d.status.offline_note, versions }
      : { kind: "not_configured", model: d.status.model, note: d.status.offline_note, versions };
  }, [status.isLoading, status.error, status.data, caps.data]);

  const available = gate.kind === "available";
  const running = conv.turns.some((t) => t.status === "running" || t.status === "sending" || t.status === "cancelling");
  const runData = run.data;
  const fieldLabel = sel.fieldId ? fieldIndex.get(sel.fieldId)?.label ?? sel.fieldId.replace(/^[^:]+:/, "") : null;

  const context: UIContext = useMemo(
    () => ({
      pilot_id: sel.pilotId ?? null,
      pilot_version: sel.version ?? null,
      scenario_revision_id: runData?.scenario_revision_id ?? null,
      selected_run_id: sel.runId,
      selected_field_id: sel.fieldId,
      timeline_date: sel.date && /^\d{4}-\d{2}-\d{2}$/.test(sel.date) ? sel.date : null,
      view: sel.screen,
      language: lang,
      units: "metric",
    }),
    [sel.pilotId, sel.version, sel.runId, sel.fieldId, sel.date, sel.screen, runData?.scenario_revision_id, lang],
  );

  // Restore this tab's conversation (session id only is remembered) once the copilot is reachable.
  useEffect(() => {
    if (available) void restore(sel.pilotKey);
  }, [available, sel.pilotKey]);

  // Apply server view intents once, after a live turn finishes (T11.2 navigate_view).
  useEffect(() => {
    for (const t of conv.turns) {
      if (t.live && !t.intentsApplied && t.viewIntents.length && (t.status === "completed" || t.status === "clarification")) {
        for (const i of t.viewIntents) nav.applyIntent(i);
        markIntentsApplied(sel.pilotKey, t.key);
      }
    }
  }, [conv.turns, nav, sel.pilotKey]);

  // Keep the newest activity in view while the user is near the bottom.
  const lastSig = conv.turns.length ? `${conv.turns.length}:${conv.turns[conv.turns.length - 1].status}:${conv.turns[conv.turns.length - 1].activity.length}:${!!conv.turns[conv.turns.length - 1].answer}` : "";
  // Follow the newest turn after the user asks: keep its question in view (top) while the answer
  // grows, and stop following as soon as the user scrolls up on their own.
  const follow = useRef(false);
  const lastAuto = useRef(0);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !follow.current) return;
    const turns = el.querySelectorAll<HTMLElement>("[data-testid=copilot-turn]");
    const last = turns[turns.length - 1];
    const bottom = el.scrollHeight - el.clientHeight;
    const target = last ? Math.min(bottom, last.offsetTop - 12) : bottom;
    if (target <= el.scrollTop + 2) return;
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    lastAuto.current = target;
    el.scrollTo({ top: target, behavior: target - el.scrollTop > 480 || reduce ? "auto" : "smooth" });
  }, [lastSig]); // eslint-disable-line react-hooks/exhaustive-deps
  const onScroll = () => {
    const el = scroller.current;
    if (el && follow.current && el.scrollTop < lastAuto.current - 60) follow.current = false;
  };

  const submit = (text?: string) => {
    const msg = (text ?? draft).trim();
    if (!msg || !available || running || msg.length > MAX_CHARS) return;
    follow.current = true;
    lastAuto.current = scroller.current?.scrollTop ?? 0;
    void send(sel.pilotKey, msg, context);
    if (!text) setDraft("");
    input.current?.focus();
  };

  const setLanguage = (v: CopilotLanguage) => {
    setLang(v);
    try {
      localStorage.setItem("aabflow-copilot-lang", v);
    } catch {
      /* per-viewer convenience only */
    }
  };

  const suggestions = suggestedQuestions(expl.data, fieldLabel);
  const runKind = runData?.plan_kind;

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas/40" data-testid="copilot-panel" data-gate={gate.kind}>
      {/* header */}
      <div className="flex items-center justify-between gap-2 border-b border-border bg-surface px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-[9px] bg-water-soft text-water-deep" aria-hidden>
            <Bot size={15} />
          </span>
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold leading-tight text-ink">Copilot</h2>
            <div className="truncate text-[11px] leading-tight text-ink-tertiary" title={gate.kind === "available" || gate.kind === "not_configured" ? gate.versions : undefined}>
              {gate.kind === "available" ? `Connected · ${gate.model}` : gate.kind === "not_configured" ? "Hosted model not configured" : gate.kind === "loading" ? "Checking connection…" : "Not available in this build"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Chip
            size="sm"
            tone={available ? "vegetation" : gate.kind === "loading" ? "neutral" : "warning"}
            icon={available ? <span className="h-1.5 w-1.5 rounded-full bg-vegetation" aria-hidden /> : gate.kind === "loading" ? undefined : <WifiOff size={11} aria-hidden />}
          >
            {available ? "Online" : gate.kind === "loading" ? "Checking" : gate.kind === "not_configured" ? "Not configured" : "Unavailable"}
          </Chip>
          {available && conv.turns.length ? (
            <IconButton label="New conversation" size="sm" onClick={() => reset(sel.pilotKey)} disabled={running}>
              <MessageSquarePlus size={15} />
            </IconButton>
          ) : null}
        </div>
      </div>

      {/* context the next question will carry */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border bg-surface px-4 py-2 text-[11px] text-ink-secondary" aria-label="Context sent with your next question">
        <span className="text-ink-tertiary">Asking about</span>
        <Chip size="sm" title={pilot.data?.pilot?.name}>
          {sel.pilotId ?? "no pilot"}
          {sel.version ? ` · ${sel.version}` : ""}
        </Chip>
        {sel.runId ? (
          <Chip size="sm" tone="water" icon={<PlayCircle size={11} aria-hidden />} title={sel.runId}>
            {runKind ? `${runKind} · ` : ""}
            {shortId(sel.runId.replace(/^run_/, ""))}
          </Chip>
        ) : (
          <Chip size="sm" title="No run selected; the copilot will read the pilot and its revisions">
            no run selected
          </Chip>
        )}
        {fieldLabel ? <Chip size="sm">{fieldLabel}</Chip> : null}
      </div>

      {/* body */}
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3" data-testid="copilot-scroll">
        {gate.kind === "loading" ? (
          <div className="flex flex-col gap-2" aria-busy>
            <Skeleton className="h-20" />
            <Skeleton className="h-12" />
          </div>
        ) : !available ? (
          <Unavailable gate={gate} onRecheck={() => void status.refetch()} rechecking={status.isFetching} />
        ) : null}

        {gate.kind !== "loading" ? (
          <div className={cn("flex flex-col gap-3", !available && "mt-4")}>
            <WhyThisPlan key={sel.runId ?? "none"} runId={sel.runId} defaultOpen={!conv.turns.length} />

            {available && conv.restoring ? <Skeleton className="h-24" /> : null}
            {available && conv.restoreNote ? <p className="text-[12px] text-ink-secondary">{conv.restoreNote}</p> : null}

            {available && !conv.turns.length && !conv.restoring ? (
              <div data-testid="copilot-suggestions">
                <Eyebrow className="mb-1.5 flex items-center gap-1">
                  <Sparkles size={11} aria-hidden /> Ask about this plan
                </Eyebrow>
                <ul className="flex flex-col gap-1.5">
                  {suggestions.map((s) => (
                    <li key={s}>
                      <button
                        type="button"
                        onClick={() => submit(s)}
                        className="w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-left text-[12.5px] text-ink shadow-1 transition-colors hover:border-water/40 hover:bg-water-soft/50"
                      >
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11.5px] leading-snug text-ink-tertiary">
                  Answers use the application's own tools on the context above. Explicit what-ifs create reversible branches and jobs; nothing overwrites your active scenario.
                </p>
              </div>
            ) : null}

            {conv.turns.map((t) => (
              <TurnView
                key={t.key}
                t={t}
                currentRunId={sel.runId}
                onRetry={() => {
                  follow.current = true;
                  void retry(sel.pilotKey, t, context);
                }}
                onCancel={() => void cancel(sel.pilotKey, t)}
                onLoadTrace={() => void loadToolCalls(sel.pilotKey, t)}
              />
            ))}
          </div>
        ) : null}

        {!available && gate.kind !== "loading" ? <CoreTools /> : null}
      </div>

      {/* composer */}
      <div className="border-t border-border bg-surface p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className={cn(
            "rounded-[12px] border bg-surface transition-colors focus-within:border-water focus-within:ring-2 focus-within:ring-water/15",
            available ? "border-border-strong/60" : "border-border bg-surface-muted",
          )}
        >
          <label htmlFor="copilot-input" className="sr-only">
            Message the copilot
          </label>
          <textarea
            id="copilot-input"
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={!available}
            rows={2}
            maxLength={MAX_CHARS}
            dir="auto"
            placeholder={
              !available
                ? gate.kind === "not_configured"
                  ? "Hosted copilot not configured on this server"
                  : "Copilot unavailable — see status above"
                : running
                  ? "Wait for the current answer, or stop it"
                  : "Ask about this plan, or request a what-if…"
            }
            className="block max-h-40 min-h-[44px] w-full resize-none bg-transparent px-3 pt-2.5 text-[13.5px] text-ink outline-none focus-visible:outline-none placeholder:text-ink-tertiary disabled:cursor-not-allowed disabled:text-ink-tertiary"
            style={{ outline: "none" }} /* the form's focus-within ring is the visible focus indicator */
            data-testid="copilot-input"
          />
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <Segmented size="sm" label="Answer language" value={lang} onChange={setLanguage} options={LANGS.map((l) => ({ ...l, disabled: !available }))} />
            <div className="flex items-center gap-2">
              {draft.length > MAX_CHARS * 0.8 ? <span className="num text-[11px] text-ink-tertiary">{draft.length}/{MAX_CHARS}</span> : null}
              <button
                type="submit"
                disabled={!available || running || !draft.trim()}
                aria-label="Send"
                title={running ? "A turn is still running" : "Send (Enter)"}
                className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-water text-on-water shadow-1 transition-colors enabled:hover:bg-water-deep disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-tertiary disabled:shadow-none"
                data-testid="copilot-send"
              >
                <ArrowUp size={16} aria-hidden />
              </button>
            </div>
          </div>
        </form>
        <p className="mt-1.5 px-0.5 text-[10.5px] text-ink-tertiary">
          {available ? "Enter to send · Shift+Enter for a new line · answers cite the runs and sources they use" : "Saved results, explanations and controls keep working without the copilot."}
        </p>
      </div>
    </div>
  );
}

function Unavailable({ gate, onRecheck, rechecking }: { gate: Gate; onRecheck: () => void; rechecking: boolean }) {
  if (gate.kind === "not_configured")
    return (
      <div className="rounded-[14px] border border-border bg-surface p-4 shadow-1" data-testid="copilot-unavailable" role="status">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-warning-soft text-warning" aria-hidden>
            <WifiOff size={17} />
          </span>
          <div className="min-w-0">
            <h3 className="text-[13.5px] font-semibold text-ink">Copilot not configured</h3>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-secondary">{gate.note}</p>
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-[10px] bg-surface-muted/70 px-3 py-2 text-[11.5px]">
          <dt className="text-ink-tertiary">Server reports</dt>
          <dd className="font-mono text-ink">configured: false</dd>
          <dt className="text-ink-tertiary">Model</dt>
          <dd className="font-mono text-ink">{gate.model}</dd>
          <dt className="text-ink-tertiary">Prompt · tools</dt>
          <dd className="truncate font-mono text-ink" title={gate.versions}>
            {gate.versions}
          </dd>
        </dl>
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={onRecheck}
            className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[8px] border border-border-strong/60 bg-surface px-2.5 text-[12px] font-medium text-ink shadow-1 hover:bg-surface-muted"
          >
            <RefreshCw size={12} aria-hidden className={cn(rechecking && "[animation:spin_1s_linear_infinite]")} /> Check again
          </button>
          <span className="text-[11.5px] text-ink-tertiary">There is no offline generative assistant.</span>
        </div>
      </div>
    );
  if (gate.kind === "not_mounted")
    return (
      <StatePanel state="blocked" title="Copilot is not part of this API build">
        <span className="block">{gate.reason}</span>
        <span className="mt-1 block font-mono text-[11px] text-ink-tertiary">{gate.detail}</span>
      </StatePanel>
    );
  if (gate.kind === "error")
    return (
      <StatePanel state="error" title={gate.title} action={{ label: "Check again", onClick: onRecheck }}>
        {gate.detail}
      </StatePanel>
    );
  return null;
}

function CoreTools() {
  const sel = useSelection();
  return (
    <div className="mt-4">
      <Eyebrow className="mb-2">Available without the copilot</Eyebrow>
      <ul className="flex flex-col gap-1.5 text-[13px]">
        {[
          { icon: <Compass size={14} />, label: "Explain the selected field", to: () => sel.go("workspace") },
          { icon: <GitCompareArrows size={14} />, label: "Compare B0 · B1 · P", to: () => sel.go("compare") },
          { icon: <Telescope size={14} />, label: "Why-not, frontier and stress tests", to: () => sel.go("explore") },
          { icon: <FileText size={14} />, label: "Action plan and report", to: () => sel.go("report") },
        ].map((x) => (
          <li key={x.label}>
            <button type="button" onClick={x.to} className="flex w-full items-center gap-2 rounded-[10px] border border-border bg-surface px-3 py-2 text-left text-ink hover:bg-surface-muted">
              <span className="text-water" aria-hidden>
                {x.icon}
              </span>
              {x.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
