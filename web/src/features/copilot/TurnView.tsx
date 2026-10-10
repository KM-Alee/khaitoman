/**
 * One copilot turn: the question, the server-pinned context badge, live tool activity,
 * the validated answer (server-rendered metric/comparison cards, cited prose), jobs the
 * turn started, applied view intents, validation status and the audited tool trace.
 * Values come only from the turn's answer payload; nothing is recomputed here.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Ban,
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock,
  Compass,
  FileDown,
  FileText,
  GitBranch,
  GitCompareArrows,
  Hash,
  Loader2,
  MapPin,
  PlayCircle,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Square,
  Telescope,
  Wrench,
  XCircle,
} from "lucide-react";
import { Chip, JobBadge, MetricValueView, SolverBadge, type Tone } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/primitives";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { useFieldLabel } from "@/features/impact/viewKit";
import { formatDelta, formatDuration, formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import type { MetricValue, SolverStatus } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import type { ActionBlock, AnswerBlock, Citation, ComparisonBlock, MetricBlock, TextBlock, ToolCallRow } from "./api";
import { isTerminalTurn } from "./api";
import type { LiveTurn, ToolActivity } from "./conversation";
import { actionKind, refKind, useCopilotNav, type RefKind } from "./nav";

/* ------------------------------------------------------------------ status copy */

const STATUS: Record<string, { label: string; tone: Tone; icon: ReactNode }> = {
  sending: { label: "Sending", tone: "neutral", icon: <Loader2 size={11} className="[animation:spin_1s_linear_infinite]" aria-hidden /> },
  running: { label: "Working", tone: "water", icon: <Loader2 size={11} className="[animation:spin_1s_linear_infinite]" aria-hidden /> },
  cancelling: { label: "Cancelling", tone: "warning", icon: <Loader2 size={11} className="[animation:spin_1s_linear_infinite]" aria-hidden /> },
  completed: { label: "Answered", tone: "vegetation", icon: <CheckCircle2 size={11} aria-hidden /> },
  clarification: { label: "Needs your input", tone: "water", icon: <CircleHelp size={11} aria-hidden /> },
  failed: { label: "Failed", tone: "danger", icon: <XCircle size={11} aria-hidden /> },
  cancelled: { label: "Cancelled", tone: "neutral", icon: <Ban size={11} aria-hidden /> },
  provider_unavailable: { label: "Assistant unavailable", tone: "warning", icon: <AlertTriangle size={11} aria-hidden /> },
  budget_exhausted: { label: "Turn limit reached", tone: "warning", icon: <Clock size={11} aria-hidden /> },
  rejected: { label: "Not sent", tone: "danger", icon: <XCircle size={11} aria-hidden /> },
};

const TOOL_ICON: Record<string, ReactNode> = {
  get_context: <Compass size={13} aria-hidden />,
  inspect_field: <MapPin size={13} aria-hidden />,
  inspect_run: <PlayCircle size={13} aria-hidden />,
  compare_runs: <GitCompareArrows size={13} aria-hidden />,
  search_evidence: <FileText size={13} aria-hidden />,
  branch_scenario: <GitBranch size={13} aria-hidden />,
  create_report: <FileDown size={13} aria-hidden />,
  navigate_view: <Compass size={13} aria-hidden />,
};

const KIND_ICON: Record<RefKind, ReactNode> = {
  run: <PlayCircle size={11} aria-hidden />,
  field: <MapPin size={11} aria-hidden />,
  evidence: <FileText size={11} aria-hidden />,
  comparison: <GitCompareArrows size={11} aria-hidden />,
  analysis: <Telescope size={11} aria-hidden />,
  report: <FileDown size={11} aria-hidden />,
  branch: <GitBranch size={11} aria-hidden />,
  revision: <GitBranch size={11} aria-hidden />,
  job: <Wrench size={11} aria-hidden />,
  other: <Hash size={11} aria-hidden />,
};

/* ------------------------------------------------------------------ helpers */

const METRIC_LABEL: Record<string, string> = {
  production_kg: "Modeled production",
  cropped_area_ha: "Cropped area",
  capital_cost_pkr: "Capital cost",
  operating_cost_pkr: "Operating cost",
  pumping_cost_pkr: "Pumping cost",
  groundwater_m3: "Groundwater abstraction",
  canal_delivered_m3: "Canal water delivered",
  net_margin_pkr: "Net margin",
};

export function metricLabel(id: string): string {
  if (METRIC_LABEL[id]) return METRIC_LABEL[id];
  const t = id.replace(/_(kg_ha|kg_m3|m3|kg|pkr|ha|fraction|ratio)$/, "").replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function useRefLabel() {
  const fieldLabel = useFieldLabel();
  return (kind: RefKind, id: string) => {
    switch (kind) {
      case "run":
        return `Run ${shortId(id.replace(/^run_/, ""))}`;
      case "field":
        return fieldLabel(id);
      case "comparison":
        return `Comparison ${shortId(id.replace(/^cmp_/, ""))}`;
      case "analysis":
        return `Analysis ${shortId(id.replace(/^ana_/, ""))}`;
      case "revision":
        return `Branch ${shortId(id.replace(/^rev_/, ""))}`;
      case "job":
        return `Job ${shortId(id.replace(/^job_/, ""))}`;
      default:
        return id;
    }
  };
}

/* ------------------------------------------------------------------ citations */

export function CitationChip({ c }: { c: Citation }) {
  const kind = refKind(c.kind, c.ref_id);
  const label = useRefLabel()(kind, c.ref_id);
  const nav = useCopilotNav();
  const cls =
    "inline-flex h-6 max-w-full items-center gap-1 rounded-full border border-border bg-surface px-2 text-[11px] font-medium text-ink-secondary transition-colors hover:border-water/40 hover:bg-water-soft hover:text-water-deep focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus";
  const title = `${titleCase(kind)} ${c.ref_id}${c.auto ? " · auto-cited: the text quotes a number from this result" : ""}`;
  if (kind === "evidence") {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className={cls} title={title} data-testid="copilot-citation" data-kind={kind}>
            {KIND_ICON[kind]}
            <span className="truncate font-mono">{label}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[340px] max-w-[92vw] p-2" align="start">
          <EvidenceById id={c.ref_id} compact />
        </PopoverContent>
      </Popover>
    );
  }
  const navigable = ["run", "field", "analysis", "comparison", "report"].includes(kind);
  return (
    <button
      type="button"
      className={cn(cls, !navigable && "cursor-default hover:border-border hover:bg-surface hover:text-ink-secondary")}
      title={title}
      onClick={() => navigable && nav.open(kind, c.ref_id)}
      aria-disabled={!navigable || undefined}
      data-testid="copilot-citation"
      data-kind={kind}
    >
      {KIND_ICON[kind]}
      <span className="truncate">{label}</span>
      {c.auto ? <span className="text-ink-tertiary">·auto</span> : null}
    </button>
  );
}

function Citations({ items }: { items: Citation[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-1" aria-label="Sources for this statement">
      {items.map((c) => (
        <li key={c.ref_id} className="max-w-full">
          <CitationChip c={c} />
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------ blocks */

function TextView({ b, lang }: { b: TextBlock; lang: string }) {
  const rtl = lang === "ur";
  if (b.type === "uncertainty")
    return (
      <div className="rounded-[10px] border border-warning/30 bg-warning-soft/60 px-3 py-2" data-block="uncertainty">
        <div className="flex gap-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden />
          <p dir={rtl ? "rtl" : "auto"} lang={rtl ? "ur" : undefined} className={cn("text-[13px] leading-relaxed text-ink", rtl && "font-urdu text-[15px] leading-loose")}>
            <span className="sr-only">Limitation: </span>
            {b.text}
          </p>
        </div>
        <Citations items={b.citations ?? []} />
      </div>
    );
  return (
    <div data-block="text">
      <p dir={rtl ? "rtl" : "auto"} lang={rtl ? "ur" : undefined} className={cn("whitespace-pre-line text-[13.5px] leading-relaxed text-ink", rtl && "font-urdu text-[15px] leading-loose")}>
        {b.text}
      </p>
      {b.withheld ? (
        <Chip size="sm" tone="warning" icon={<ShieldAlert size={11} aria-hidden />} className="mt-1.5" title="A sentence whose figure no tool result supported was replaced by the server">
          Unsupported figure withheld
        </Chip>
      ) : null}
      <Citations items={b.citations ?? []} />
    </div>
  );
}

function MetricCard({ b }: { b: MetricBlock }) {
  const nav = useCopilotNav();
  const fieldLabel = useFieldLabel();
  const m: MetricValue = {
    metric_id: b.metric_id,
    definition_id: b.definition_id,
    run_id: b.run_id,
    value: b.value,
    unit: b.unit,
    status: b.status as MetricValue["status"],
    reason: b.reason,
    evidence_ids: [],
    crop: null,
    field_id: b.field_id,
  };
  return (
    <div className="rounded-[12px] border border-border bg-surface-muted/50 p-3" data-block="metric" data-metric={b.metric_id}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] font-medium text-ink-secondary" title={`Definition ${b.definition_id} (server registry); value rendered by the server, not the model`}>
            {metricLabel(b.metric_id)}
            {b.field_id ? <span className="text-ink-tertiary"> · {fieldLabel(b.field_id)}</span> : null}
          </div>
          <MetricValueView metric={m} size="lg" className="mt-0.5" />
        </div>
        <SolverBadge status={b.solver_status as SolverStatus} size="sm" />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-tertiary">
        <button type="button" onClick={() => nav.open("run", b.run_id)} className="inline-flex items-center gap-1 font-medium text-water hover:underline" title={b.run_id}>
          <PlayCircle size={11} aria-hidden /> {b.plan_kind} · {shortId(b.run_id.replace(/^run_/, ""))}
        </button>
        {b.basis ? <span>· {b.basis.replace(/_/g, " ")}</span> : null}
      </div>
    </div>
  );
}

function ComparisonCard({ b }: { b: ComparisonBlock }) {
  const nav = useCopilotNav();
  return (
    <div className="rounded-[12px] border border-border bg-surface p-3" data-block="comparison">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-ink">{b.label}</div>
          <div className="mt-0.5 text-[11px] text-ink-tertiary">{b.run_ids.map((r) => shortId(r.replace(/^run_/, ""))).join(" → ")}</div>
        </div>
        <Chip size="sm" tone={b.compatible ? "vegetation" : "warning"} icon={b.compatible ? <CheckCircle2 size={11} aria-hidden /> : <AlertTriangle size={11} aria-hidden />}>
          {b.compatible ? "Compatible" : "Not comparable"}
        </Chip>
      </div>
      {b.deltas.length ? (
        <table className="mt-2 w-full text-[12px]">
          <caption className="sr-only">Backend-computed deltas</caption>
          <thead>
            <tr className="text-left text-[11px] text-ink-tertiary">
              <th className="py-1 font-medium">Metric</th>
              <th className="py-1 text-right font-medium">Base</th>
              <th className="py-1 text-right font-medium">Other</th>
              <th className="py-1 text-right font-medium">Δ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {b.deltas.slice(0, 8).map((d) => (
              <tr key={d.metric_id}>
                <td className="py-1.5 pr-2 text-ink-secondary">{metricLabel(d.metric_id)}</td>
                <td className="num py-1.5 text-right text-ink">{d.a === null ? "—" : formatWithUnit(d.a, d.unit)}</td>
                <td className="num py-1.5 text-right text-ink">{d.b === null ? "—" : formatWithUnit(d.b, d.unit)}</td>
                <td className="num py-1.5 text-right font-medium text-ink">{d.delta === null ? titleCase(d.status) : formatDelta(d.delta, d.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-ink-tertiary">
        <span>{b.fields_worse_off.length ? `${b.fields_worse_off.length} fields worse off` : "No field worse off reported"}</span>
        <button type="button" className="inline-flex items-center gap-1 font-medium text-water hover:underline" onClick={() => nav.open("comparison", b.comparison_id, { runIds: b.run_ids })}>
          Open in Compare <ArrowUpRight size={11} aria-hidden />
        </button>
      </div>
    </div>
  );
}

function ActionCard({ b }: { b: ActionBlock }) {
  const nav = useCopilotNav();
  const kind = actionKind(b.action);
  const navigable = kind !== "revision";
  const [note, setNote] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-1" data-block="action">
      <Button
        size="sm"
        variant={navigable ? "secondary" : "subtle"}
        icon={KIND_ICON[kind]}
        trailing={navigable ? <ArrowUpRight size={13} aria-hidden /> : undefined}
        className="w-full justify-between"
        onClick={() => {
          if (navigable) nav.open(kind, b.ref_id);
          else setNote(`Branch ${b.ref_id} was created through the API. Select it from the Scenario panel; nothing was overwritten.`);
        }}
        title={b.ref_id}
      >
        <span className="min-w-0 flex-1 truncate text-left">
          {b.label}
          {b.auto ? <span className="ml-1 text-[11px] font-normal text-ink-tertiary">· created in this turn</span> : null}
        </span>
      </Button>
      {note ? <p className="text-[12px] text-ink-secondary">{note}</p> : null}
    </div>
  );
}

function Block({ b, lang }: { b: AnswerBlock; lang: string }) {
  switch (b.type) {
    case "text":
    case "uncertainty":
      return <TextView b={b} lang={lang} />;
    case "metric":
      return <MetricCard b={b} />;
    case "comparison":
      return <ComparisonCard b={b} />;
    case "action":
      return <ActionCard b={b} />;
    default:
      return null;
  }
}

/* ------------------------------------------------------------------ activity + trace */

function ActivityRow({ a }: { a: ToolActivity }) {
  return (
    <li className="flex items-center gap-2 text-[12px]" data-tool={a.tool} data-state={a.state}>
      <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full", a.state === "failed" ? "bg-danger-soft text-danger" : a.state === "ok" ? "bg-vegetation-soft text-vegetation" : "bg-water-soft text-water")}>
        {a.state === "running" ? (
          <Loader2 size={11} className="[animation:spin_1s_linear_infinite]" aria-hidden />
        ) : a.state === "ok" ? (
          <CheckCircle2 size={11} aria-hidden />
        ) : (
          <XCircle size={11} aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1 truncate text-ink">{a.activity}</span>
      {a.reused ? <span className="text-[11px] text-ink-tertiary">reused</span> : null}
      <code className="shrink-0 font-mono text-[11px] text-ink-tertiary">{a.tool}</code>
      {a.state === "failed" && a.error?.detail ? <span className="sr-only">{a.error.detail}</span> : null}
    </li>
  );
}

function argsText(a: ToolCallRow["arguments"]): string {
  if (!a) return "{}";
  if (typeof a === "string") return a;
  const shown = Object.fromEntries(Object.entries(a).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && !v.length)));
  const s = JSON.stringify(shown);
  return s === "{}" ? "defaults (pinned context)" : s;
}

function duration(a: string, b: string | null): string | null {
  if (!b) return null;
  const ms = Date.parse(b) - Date.parse(a);
  return Number.isFinite(ms) && ms >= 0 ? (ms < 1000 ? `${ms} ms` : formatDuration(ms)) : null;
}

function Trace({ t }: { t: LiveTurn }) {
  const rows = t.toolCalls;
  return (
    <div className="mt-2 rounded-[10px] border border-border bg-surface-muted/40 p-2.5" data-testid="copilot-trace">
      {!rows ? (
        <div className="flex items-center gap-2 text-[12px] text-ink-secondary">
          <Loader2 size={12} className="[animation:spin_1s_linear_infinite]" aria-hidden /> Loading the audited tool log…
        </div>
      ) : rows.length === 0 ? (
        <p className="text-[12px] text-ink-secondary">No tools were called in this turn.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {rows.map((r) => {
            const err = (r.result as { error?: { code?: string; detail?: string } } | null)?.error;
            const ok = r.status === "succeeded";
            return (
              <li key={r.pk} className="text-[12px]">
                <div className="flex items-center gap-1.5">
                  <span className={cn(ok ? "text-vegetation" : r.status === "running" ? "text-water" : "text-danger")} aria-hidden>
                    {TOOL_ICON[r.tool] ?? <Wrench size={13} />}
                  </span>
                  <code className="font-mono font-medium text-ink">{r.tool}</code>
                  <span className="text-ink-tertiary">· round {r.round}</span>
                  <span className={cn("ml-auto text-[11px] font-medium", ok ? "text-vegetation" : r.status === "running" ? "text-water" : "text-danger")}>{titleCase(r.status)}</span>
                  {duration(r.started_at, r.finished_at) ? <span className="num text-[11px] text-ink-tertiary">{duration(r.started_at, r.finished_at)}</span> : null}
                </div>
                <div className="mt-0.5 break-all pl-5 font-mono text-[11px] leading-snug text-ink-secondary">{argsText(r.arguments)}</div>
                {r.idempotency_key ? <div className="pl-5 font-mono text-[10.5px] text-ink-tertiary">idempotency {r.idempotency_key.slice(0, 22)}…</div> : null}
                {err ? (
                  <div className="pl-5 text-[11px] text-danger">
                    {err.code}: {err.detail}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 border-t border-border pt-2 text-[11px] text-ink-tertiary">
        {t.model ? <span>model {t.model}</span> : null}
        {t.rounds !== null ? <span>{t.rounds} model rounds</span> : null}
        {t.latencyMs !== null ? <span>{formatDuration(t.latencyMs)}</span> : null}
        {t.turnId ? <span className="font-mono">{t.turnId}</span> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ turn */

export function TurnView({
  t,
  onRetry,
  onCancel,
  onLoadTrace,
  currentRunId,
}: {
  t: LiveTurn;
  onRetry: () => void;
  onCancel: () => void;
  onLoadTrace: () => void;
  currentRunId: string | null;
}) {
  const [traceOpen, setTraceOpen] = useState(false);
  const busy = t.status === "running" || t.status === "sending" || t.status === "cancelling";
  const s = STATUS[t.status] ?? STATUS.running;
  const ctx = t.context;
  const answer = t.answer;
  const lang = answer?.language ?? "en";
  const terminal = isTerminalTurn(t.status) || t.status === "rejected";
  const retryable = terminal && t.status !== "completed" && t.status !== "clarification";
  const toolCount = t.toolCallCount ?? t.activity.length;
  const runChanged = !!ctx?.selected_run_id && !!currentRunId && ctx.selected_run_id !== currentRunId;

  useEffect(() => {
    if (traceOpen) onLoadTrace();
  }, [traceOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <article className="flex flex-col gap-2" data-testid="copilot-turn" data-status={t.status} aria-busy={busy || undefined}>
      {/* the question */}
      <div className="flex justify-end">
        <div className="max-w-[88%] rounded-[14px] rounded-br-[4px] bg-water px-3 py-2 text-[13.5px] leading-relaxed text-on-water shadow-1" dir="auto">
          {t.message}
          {t.retryOf ? <div className="mt-0.5 text-[11px] opacity-80">Retry of an earlier turn · same pinned context</div> : null}
        </div>
      </div>

      {/* the answer */}
      <div className="rounded-[14px] border border-border bg-surface p-3 shadow-1">
        <header className="flex flex-wrap items-center gap-1.5">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-water-soft text-water-deep" aria-hidden>
            <Bot size={13} />
          </span>
          <Chip size="sm" tone={s.tone} icon={s.icon}>
            {s.label}
          </Chip>
          {ctx?.selected_run_id ? (
            <Chip size="sm" tone={runChanged ? "warning" : "neutral"} icon={<PlayCircle size={11} aria-hidden />} title={`Pinned to ${ctx.selected_run_id}${runChanged ? " — the UI has since selected another run" : ""}`}>
              {ctx.selected_run_plan_kind ? `${ctx.selected_run_plan_kind} · ` : ""}
              {shortId(ctx.selected_run_id.replace(/^run_/, ""))}
            </Chip>
          ) : ctx ? (
            <Chip size="sm" title="No run was pinned for this turn">
              No run pinned
            </Chip>
          ) : null}
          {ctx?.selected_field_id ? (
            <Chip size="sm" icon={<MapPin size={11} aria-hidden />}>
              {ctx.selected_field_id.replace(/^[^:]+:/, "")}
            </Chip>
          ) : null}
        </header>

        {runChanged ? (
          <p className="mt-1.5 text-[11.5px] text-ink-secondary">Answered for the run pinned when you asked; ask again to use the run selected now.</p>
        ) : null}
        {ctx?.notes?.length ? (
          <ul className="mt-2 flex flex-col gap-1">
            {ctx.notes.map((n, i) => (
              <li key={i} className="flex gap-1.5 text-[12px] text-warning">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        ) : null}

        {/* live activity */}
        {busy || (!answer && t.activity.length) ? (
          <div className="mt-2.5" aria-live="polite">
            {t.activity.length ? (
              <ul className="flex flex-col gap-1.5">
                {t.activity.map((a) => (
                  <ActivityRow key={a.callId} a={a} />
                ))}
              </ul>
            ) : null}
            {busy ? (
              <div className="mt-1.5 flex items-center gap-2 text-[12px] text-ink-secondary">
                <span className="flex gap-1" aria-hidden>
                  <span className="h-1.5 w-1.5 rounded-full bg-water [animation:pulse-dot_1.2s_ease-in-out_infinite]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-water [animation:pulse-dot_1.2s_ease-in-out_0.2s_infinite]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-water [animation:pulse-dot_1.2s_ease-in-out_0.4s_infinite]" />
                </span>
                {t.status === "sending" ? "Pinning your context…" : t.status === "cancelling" ? "Stopping the turn and any jobs it started…" : t.activity.length ? "Reading tool results…" : "Thinking with the current workspace…"}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* answer blocks */}
        {answer ? (
          <div className="mt-2.5 flex flex-col gap-2.5" data-testid="copilot-answer">
            {answer.needs_clarification && answer.clarification_question ? (
              <div className="rounded-[10px] border border-water/30 bg-water-soft/60 px-3 py-2 text-[13px] text-ink" dir="auto">
                <div className="mb-0.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-water-deep">
                  <CircleHelp size={12} aria-hidden /> One question first
                </div>
                {answer.clarification_question}
              </div>
            ) : null}
            {answer.blocks.map((b, i) => (
              <Block key={i} b={b} lang={lang} />
            ))}
          </div>
        ) : null}

        {/* errors */}
        {t.requestError ? (
          <div role="alert" className="mt-2.5 rounded-[10px] border border-danger/30 bg-danger-soft/60 px-3 py-2 text-[12.5px]">
            <div className="font-semibold text-danger">{t.requestError.title}</div>
            <div className="text-ink-secondary">{t.requestError.detail}</div>
          </div>
        ) : t.error && t.status !== "completed" ? (
          <div role="alert" className="mt-2.5 rounded-[10px] border border-warning/30 bg-warning-soft/60 px-3 py-2 text-[12.5px]">
            <div className="font-semibold text-warning">{t.error.code.replace(/_/g, " ")}</div>
            {t.error.detail ? <div className="text-ink-secondary">{t.error.detail}</div> : null}
          </div>
        ) : null}

        {t.status === "cancelled" ? (
          <p className="mt-2 text-[12px] text-ink-secondary">Stopped on request. No answer was kept and any job this turn started was cancelled; Retry re-asks with the same pinned context.</p>
        ) : null}

        {/* jobs started by the turn */}
        {t.jobIds.length ? <Jobs t={t} /> : null}

        {/* view intents */}
        {t.viewIntents.length && terminal ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-secondary">
            <Compass size={12} aria-hidden className="text-water" />
            {t.live ? "View updated:" : "Suggested view:"}
            {t.viewIntents.map((v, i) => (
              <Chip key={i} size="sm">
                {v.target}
                {v.run_id ? ` ${shortId(v.run_id.replace(/^run_/, ""))}` : v.field_id ? ` ${v.field_id.replace(/^[^:]+:/, "")}` : v.tab ? ` ${v.tab}` : v.date ? ` ${v.date}` : ""}
              </Chip>
            ))}
          </div>
        ) : null}

        {/* footer */}
        <footer className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-2.5">
          {answer ? (
            answer.deterministic ? (
              <Chip size="sm" tone="info" icon={<ShieldCheck size={11} aria-hidden />} title="Written by the server, not the model; no result was invented">
                Server notice
              </Chip>
            ) : answer.validated ? (
              <Chip size="sm" tone="vegetation" icon={<ShieldCheck size={11} aria-hidden />} title="Every cited ID and quoted number was matched against this turn's tool results">
                Grounded
              </Chip>
            ) : (
              <Chip size="sm" tone="warning" icon={<ShieldAlert size={11} aria-hidden />} title={answer.issues.join("\n")}>
                {answer.issues.length} check{answer.issues.length === 1 ? "" : "s"} failed
              </Chip>
            )
          ) : null}
          {t.turnId && (terminal || toolCount > 0) ? (
            <button
              type="button"
              onClick={() => setTraceOpen((o) => !o)}
              aria-expanded={traceOpen}
              className="inline-flex h-6 items-center gap-1 rounded-full px-1.5 text-[11.5px] font-medium text-ink-secondary hover:bg-surface-muted hover:text-ink"
              data-testid="copilot-trace-toggle"
            >
              <Wrench size={11} aria-hidden />
              {toolCount} tool{toolCount === 1 ? "" : "s"}
              {t.rounds !== null ? ` · ${t.rounds} round${t.rounds === 1 ? "" : "s"}` : ""}
              {t.latencyMs !== null ? ` · ${formatDuration(t.latencyMs)}` : ""}
              <ChevronDown size={12} aria-hidden className={cn("transition-transform", traceOpen && "rotate-180")} />
            </button>
          ) : null}
          <span className="ml-auto flex items-center gap-1">
            {t.status === "running" || t.status === "cancelling" ? (
              <Button size="sm" variant="ghost" icon={<Square size={12} aria-hidden />} onClick={onCancel} disabled={t.status === "cancelling"} className="h-7 px-2 text-[12px]">
                {t.status === "cancelling" ? "Stopping" : "Stop"}
              </Button>
            ) : null}
            {retryable ? (
              <Button size="sm" variant="secondary" icon={<RotateCcw size={12} aria-hidden />} onClick={onRetry} className="h-7 px-2 text-[12px]">
                Retry
              </Button>
            ) : null}
          </span>
        </footer>
        {answer && !answer.validated && answer.issues.length ? (
          <details className="mt-1.5 text-[11.5px] text-ink-secondary">
            <summary className="cursor-pointer select-none font-medium text-warning">Why some content was removed</summary>
            <ul className="mt-1 list-disc pl-4">
              {answer.issues.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </details>
        ) : null}
        {traceOpen ? <Trace t={t} /> : null}
      </div>
    </article>
  );
}

function Jobs({ t }: { t: LiveTurn }) {
  const nav = useCopilotNav();
  return (
    <ul className="mt-2.5 flex flex-col gap-1.5" aria-label="Jobs started in this turn">
      {t.jobIds.map((id) => {
        const u = t.jobUpdates.find((j) => j.job_id === id);
        const pending = t.pendingJobIds.includes(id);
        const runId = u?.run?.run_id;
        return (
          <li key={id} className="flex flex-wrap items-center gap-2 rounded-[10px] border border-border px-2.5 py-1.5 text-[12px]">
            <Wrench size={12} className="text-ink-tertiary" aria-hidden />
            <span className="font-medium text-ink">{u?.operation ? titleCase(u.operation.replace(/\./g, " ")) : "Job"}</span>
            <span className="font-mono text-[11px] text-ink-tertiary">{shortId(id.replace(/^job_/, ""))}</span>
            <span className="ml-auto">
              {u ? <JobBadge state={u.state} /> : pending ? <JobBadge state="running" /> : <Chip size="sm">Started</Chip>}
            </span>
            {runId ? (
              <button type="button" onClick={() => nav.open("run", runId)} className="inline-flex w-full items-center gap-1 text-[11.5px] font-medium text-water hover:underline">
                <PlayCircle size={11} aria-hidden /> Open run {u?.run?.plan_kind ?? ""} {shortId(runId.replace(/^run_/, ""))}
              </button>
            ) : null}
            {u?.state_meaning && u.state !== "succeeded" ? <span className="w-full text-[11px] text-ink-tertiary">{u.state_meaning}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}
