/**
 * Answer block renderers (docs/COPILOT.md §3). `BlockView` switches exhaustively over the
 * server's block types; every value shown is a value from the block. Nothing is recomputed.
 */
import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  FileDown,
  FileText,
  GitBranch,
  GitCompareArrows,
  Hash,
  Info,
  MapPin,
  MessageCircleQuestion,
  PlayCircle,
  Telescope,
  Wrench,
} from "lucide-react";
import { Chip, MetricValueView, SolverBadge } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Popover, PopoverContent, PopoverTrigger, Segmented } from "@/components/ui/primitives";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { usePilotData } from "@/app/pilotData";
import type { MetricValue, SolverStatus } from "@/lib/api/types";
import { formatDelta, formatWithUnit, shortId } from "@/lib/formatting";
import { cn } from "@/lib/cn";
import { BASIS_TEXT, PLAN_PLAIN, PLAN_TOKEN, isUrdu, type Lang } from "./format";
import { actionRef, refKind, useCopilotNav, type RefKind } from "./nav";
import type { AnswerBlock, BlockOf, Citation } from "./types";
import { VisualCard } from "./visual";

export const KIND_ICON: Record<RefKind, ReactNode> = {
  run: <PlayCircle size={11} aria-hidden />,
  field: <MapPin size={11} aria-hidden />,
  evidence: <FileText size={11} aria-hidden />,
  comparison: <GitCompareArrows size={11} aria-hidden />,
  analysis: <Telescope size={11} aria-hidden />,
  report: <FileDown size={11} aria-hidden />,
  revision: <GitBranch size={11} aria-hidden />,
  job: <Wrench size={11} aria-hidden />,
  instance: <Hash size={11} aria-hidden />,
  other: <Hash size={11} aria-hidden />,
};

export function useRefLabel() {
  const { fieldIndex } = usePilotData();
  return (kind: RefKind, id: string) => {
    switch (kind) {
      case "run":
        return `run ${shortId(id)}`;
      case "field":
        return fieldIndex.get(id)?.label ?? id.replace(/^[^:]+:/, "");
      case "comparison":
        return "comparison";
      case "analysis":
        return `analysis ${shortId(id)}`;
      case "revision":
        return `scenario ${shortId(id)}`;
      default:
        return id;
    }
  };
}

const chipCls =
  "inline-flex h-6 max-w-full items-center gap-1 rounded-full border border-border bg-surface px-2 text-[11px] font-medium text-ink-secondary transition-colors hover:border-water/40 hover:bg-water-soft hover:text-water-deep";

export function CitationChip({ c }: { c: Pick<Citation, "ref_id" | "kind"> & { auto?: boolean } }) {
  const kind = refKind(c.kind, c.ref_id);
  const label = useRefLabel()(kind, c.ref_id);
  const nav = useCopilotNav();
  const title = `${c.ref_id}${c.auto ? " · cited automatically: the text quotes a number from this result" : ""}`;
  if (kind === "evidence") {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className={chipCls} title={title} data-testid="copilot-citation" data-kind={kind}>
            {KIND_ICON[kind]}
            <bdi className="truncate font-mono">{label}</bdi>
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
      className={cn(chipCls, !navigable && "cursor-default hover:border-border hover:bg-surface hover:text-ink-secondary")}
      title={title}
      onClick={() => navigable && nav.open(kind, c.ref_id)}
      aria-disabled={!navigable || undefined}
      aria-label={`Open ${label}`}
      data-testid="copilot-citation"
      data-kind={kind}
    >
      {KIND_ICON[kind]}
      <bdi className="truncate font-mono">{label}</bdi>
    </button>
  );
}

function Citations({ items }: { items: Citation[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1" aria-label="Sources">
      {items.slice(0, 6).map((c) => (
        <CitationChip key={c.ref_id} c={c} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ simple blocks */

function Headline({ b }: { b: BlockOf<"headline"> }) {
  return (
    <p className="display text-[19px] leading-[1.3] tracking-[-0.01em] text-ink" data-testid="copilot-headline">
      {b.text}
    </p>
  );
}

function Text({ b }: { b: BlockOf<"text"> }) {
  return (
    <div>
      <p className="whitespace-pre-line text-[13.5px] leading-relaxed text-ink">{b.text}</p>
      {b.withheld ? (
        <p className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-warning">
          <AlertTriangle size={11} aria-hidden /> A figure that no tool result supported was withheld.
        </p>
      ) : null}
      <Citations items={b.citations ?? []} />
    </div>
  );
}

function MetricCard({ b, lang }: { b: BlockOf<"metric">; lang: Lang }) {
  const nav = useCopilotNav();
  const metric: MetricValue = {
    metric_id: b.metric_id,
    definition_id: b.definition_id ?? b.metric_id,
    run_id: b.run_id,
    value: b.value ?? null,
    unit: b.unit ?? "",
    status: (b.status ?? "available") as MetricValue["status"],
    reason: b.reason ?? null,
    evidence_ids: [],
    crop: null,
    field_id: b.field_id ?? null,
  };
  const basis = BASIS_TEXT[b.basis];
  return (
    <button
      type="button"
      onClick={() => nav.open("run", b.run_id)}
      className="group flex min-w-0 flex-col gap-1 rounded-[14px] border border-border bg-surface px-3 py-2.5 text-left shadow-1 transition-colors hover:border-water/40"
      data-testid="copilot-metric"
      aria-label={`${b.label ?? b.metric_id}: open run ${b.run_id}`}
    >
      <span className={cn("truncate text-[11.5px] font-medium text-ink-secondary", isUrdu(lang) && "text-left")}>{b.label ?? b.metric_id.replace(/_/g, " ")}</span>
      <MetricValueView metric={metric} size="lg" />
      <span className="flex items-center gap-1 text-[10.5px] text-ink-tertiary">
        {basis ? basis.en : b.basis}
        <span aria-hidden>·</span>
        <bdi className="font-mono">{shortId(b.run_id)}</bdi>
      </span>
    </button>
  );
}

const KEY_DELTAS = ["production_kg", "capital_commitment_pkr", "operating_cost_pkr", "groundwater_m3", "canal_source_withdrawal_m3", "min_service_ratio", "tail_min_service_ratio"];
const GOOD_UP = new Set(["production_kg", "min_service_ratio", "tail_min_service_ratio", "withdrawal_productivity_kg_m3", "tail_mean_service_ratio"]);
const GOOD_DOWN = new Set(["capital_commitment_pkr", "operating_cost_pkr", "groundwater_m3", "pumping_cost_pkr", "conveyance_loss_m3"]);

type Delta = BlockOf<"comparison">["deltas"][number];

/** Group pairwise deltas (multi-run comparisons are pairwise) into labelled before/after pairs. */
export function comparisonPairs(b: BlockOf<"comparison">): { key: string; label: string; deltas: Delta[] }[] {
  const kind = new Map((b.plans ?? []).map((p) => [p.run_id, p.plan_kind ?? ""]));
  const name = (id?: string | null) => (id ? kind.get(id) || shortId(id) : "?");
  const groups = new Map<string, { key: string; label: string; deltas: Delta[] }>();
  const seen = new Map<string, number>();
  for (const d of b.deltas) {
    let key: string;
    let label: string;
    if (d.a_run_id && d.b_run_id) {
      key = `${d.a_run_id}>${d.b_run_id}`;
      label = `${name(d.a_run_id)} → ${name(d.b_run_id)}`;
    } else {
      const n = seen.get(d.metric_id) ?? 0; // older answers: pairs follow each other in order
      seen.set(d.metric_id, n + 1);
      key = `pair-${n}`;
      label = b.run_ids.length === 2 ? "Before → after" : `Pair ${n + 1}`;
    }
    if (!groups.has(key)) groups.set(key, { key, label, deltas: [] });
    groups.get(key)!.deltas.push(d);
  }
  return [...groups.values()];
}

function ComparisonCard({ b }: { b: BlockOf<"comparison"> }) {
  const [all, setAll] = useState(false);
  const nav = useCopilotNav();
  const pairs = comparisonPairs(b);
  const [pairKey, setPairKey] = useState(pairs[pairs.length - 1]?.key ?? "");
  const pair = pairs.find((p) => p.key === pairKey) ?? pairs[0];
  const deltas = pair?.deltas ?? [];
  const keyed = deltas.filter((d) => KEY_DELTAS.includes(d.metric_id));
  const shown = all ? deltas : keyed.length ? keyed : deltas.slice(0, 6);
  return (
    <section className="rounded-[16px] border border-border bg-surface p-3 shadow-1" aria-label="Comparison" data-testid="copilot-comparison">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink">
          <GitCompareArrows size={14} aria-hidden className="text-water" /> Before and after
        </span>
        <Chip size="sm" tone={b.compatible ? "vegetation" : "warning"} icon={b.compatible ? <Info size={11} aria-hidden /> : <AlertTriangle size={11} aria-hidden />}>
          {b.compatible ? "Same conditions" : "Different conditions"}
        </Chip>
      </div>
      {pairs.length > 1 ? (
        <Segmented size="sm" label="Which pair" value={pair?.key ?? ""} onChange={setPairKey} options={pairs.map((p) => ({ value: p.key, label: p.label }))} className="mb-2" />
      ) : null}
      {!b.compatible ? <p className="mb-2 text-[12px] text-warning">Conditions differ, so differences are not caused by the plan alone.</p> : null}
      <table className="w-full text-[12px]">
        <caption className="sr-only">Server-computed differences ({pair?.label})</caption>
        <thead>
          <tr className="text-ink-tertiary">
            <th scope="col" className="pb-1 text-left font-medium">Measure</th>
            <th scope="col" className="pb-1 text-right font-medium">Before</th>
            <th scope="col" className="pb-1 text-right font-medium">After</th>
            <th scope="col" className="pb-1 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((d) => {
            const good = d.delta && d.delta !== 0 ? (GOOD_UP.has(d.metric_id) ? d.delta > 0 : GOOD_DOWN.has(d.metric_id) ? d.delta < 0 : null) : null;
            return (
              <tr key={d.metric_id} className="border-t border-border/70">
                <th scope="row" className="py-1 pr-2 text-left font-normal text-ink-secondary">
                  {METRIC_WORDS[d.metric_id] ?? d.metric_id.replace(/_(kg|pkr|m3|ratio)$/, "").replace(/_/g, " ")}
                </th>
                <td className="num py-1 text-right text-ink">{typeof d.a === "number" && d.unit ? formatWithUnit(d.a, d.unit) : "—"}</td>
                <td className="num py-1 text-right text-ink">{typeof d.b === "number" && d.unit ? formatWithUnit(d.b, d.unit) : "—"}</td>
                <td className={cn("num py-1 text-right font-medium", good === true ? "text-vegetation" : good === false ? "text-danger" : "text-ink-secondary")}>
                  {typeof d.delta === "number" && d.unit ? formatDelta(d.delta, d.unit) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {deltas.length > shown.length || all ? (
          <button type="button" className="text-[12px] font-medium text-water-deep hover:underline" onClick={() => setAll((v) => !v)} aria-expanded={all}>
            {all ? "Show key measures" : `Show all ${deltas.length} measures`}
          </button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => nav.open("comparison", b.comparison_id, { runIds: b.run_ids })}>
          Open in Compare <ArrowRight size={13} aria-hidden />
        </Button>
      </div>
    </section>
  );
}

const METRIC_WORDS: Record<string, string> = {
  production_kg: "Crop production",
  capital_commitment_pkr: "Capital spent",
  operating_cost_pkr: "Seasonal running cost",
  groundwater_m3: "Groundwater pumped",
  canal_source_withdrawal_m3: "Canal water used",
  min_service_ratio: "Lowest field's fair share",
  tail_min_service_ratio: "Lowest tail field's share",
};

const CAVEAT_ICON = (text: string) =>
  /assum|right|cost/i.test(text) ? (
    <Info size={13} aria-hidden />
  ) : /model|uncalibrat|estimate/i.test(text) ? (
    <BarChart3 size={13} aria-hidden />
  ) : (
    <AlertTriangle size={13} aria-hidden />
  );

export function Caveats({ items }: { items: BlockOf<"uncertainty">[] }) {
  if (!items.length) return null;
  return (
    <aside className="rounded-[14px] border border-warning/25 bg-warning-soft/60 px-3 py-2.5" aria-label="Things to keep in mind" data-testid="copilot-caveats">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-warning">Keep in mind</p>
      <ul className="flex flex-col gap-1.5">
        {items.map((b, i) => (
          <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-ink">
            <span className="mt-0.5 shrink-0 text-warning">{CAVEAT_ICON(b.text)}</span>
            <span>
              {b.text}
              <Citations items={b.citations ?? []} />
            </span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

const ACTION_ICON: Record<BlockOf<"action">["action"], ReactNode> = {
  open_run: <PlayCircle size={14} aria-hidden />,
  open_branch: <GitBranch size={14} aria-hidden />,
  open_field: <MapPin size={14} aria-hidden />,
  open_report: <FileDown size={14} aria-hidden />,
  open_analysis: <Telescope size={14} aria-hidden />,
  open_comparison: <GitCompareArrows size={14} aria-hidden />,
};

export function Actions({ items, runIdsForCompare }: { items: BlockOf<"action">[]; runIdsForCompare?: string[] }) {
  const nav = useCopilotNav();
  const [note, setNote] = useState<string | null>(null);
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-2" data-testid="copilot-actions">
        {items.map((a) =>
          a.action === "open_branch" ? (
            <Chip key={a.ref_id} size="sm" tone="wheat" icon={<GitBranch size={11} aria-hidden />} title={a.ref_id}>
              New scenario saved · {shortId(a.ref_id)}
            </Chip>
          ) : (
            <Button
              key={a.ref_id}
              size="sm"
              variant="secondary"
              onClick={() => setNote(nav.open(actionRef(a.action), a.ref_id, a.action === "open_comparison" ? { runIds: runIdsForCompare } : undefined))}
              data-testid="copilot-action"
            >
              {ACTION_ICON[a.action]}
              <span className="max-w-[220px] truncate">{a.label}</span>
            </Button>
          ),
        )}
      </div>
      {note ? (
        <p className="text-[11.5px] text-ink-tertiary" role="status">
          {note}
        </p>
      ) : null}
    </div>
  );
}

export function FollowUps({ b, onAsk, disabled }: { b: BlockOf<"follow_ups">; onAsk?: (q: string) => void; disabled?: boolean }) {
  if (!b.questions.length) return null;
  return (
    <div className="flex flex-col gap-1.5" data-testid="copilot-followups">
      <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-ink-tertiary">
        <MessageCircleQuestion size={12} aria-hidden /> Ask next
      </span>
      <div className="flex flex-wrap gap-1.5">
        {b.questions.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled || !onAsk}
            onClick={() => onAsk?.(q)}
            dir="auto"
            className="rounded-full border border-water/25 bg-water-soft/60 px-3 py-1.5 text-left text-[12.5px] leading-snug text-water-deep transition-colors hover:border-water/50 hover:bg-water-soft disabled:opacity-60"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

export function RunBadge({ b }: { b: BlockOf<"run_badge"> }) {
  const nav = useCopilotNav();
  const kind = b.plan_kind ?? "";
  const token = PLAN_TOKEN[kind];
  return (
    <button
      type="button"
      onClick={() => nav.open("run", b.run_id)}
      className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-surface py-1 pl-1.5 pr-2.5 text-left text-[12px] shadow-1 transition-colors hover:border-water/40"
      data-testid="copilot-run-badge"
      data-run-id={b.run_id}
      data-role={b.role}
      aria-label={`${b.role === "created" ? "New run" : "About run"} ${b.run_id}: open it`}
    >
      <span className="grid h-5 min-w-5 place-items-center rounded-full px-1 text-[10.5px] font-bold text-white" style={{ background: token ? `var(${token})` : "var(--ink-tertiary)" }}>
        {kind || "?"}
      </span>
      {b.role === "created" ? (
        <span className="rounded-full bg-wheat-soft px-1.5 text-[10.5px] font-semibold text-wheat-ink">New</span>
      ) : null}
      <span className="truncate font-medium text-ink">{PLAN_PLAIN[kind] ?? b.label ?? "Run"}</span>
      {b.solver_status ? <SolverBadge status={b.solver_status as SolverStatus} size="sm" /> : null}
      <bdi className="font-mono text-[10.5px] text-ink-tertiary">{shortId(b.run_id)}</bdi>
    </button>
  );
}

/* ------------------------------------------------------------------ dispatch */

export interface BlockContext {
  lang: Lang;
  onAsk?: (q: string) => void;
  busy?: boolean;
}

/** Exhaustive renderer for one block. Caveats/actions/badges are grouped by `AnswerView`. */
export function BlockView({ b, ctx }: { b: AnswerBlock; ctx: BlockContext }): ReactNode {
  switch (b.type) {
    case "headline":
      return <Headline b={b} />;
    case "text":
      return <Text b={b} />;
    case "metric":
      return <MetricCard b={b} lang={ctx.lang} />;
    case "visual":
      return <VisualCard b={b} lang={ctx.lang} />;
    case "comparison":
      return <ComparisonCard b={b} />;
    case "uncertainty":
      return <Caveats items={[b]} />;
    case "action":
      return <Actions items={[b]} />;
    case "follow_ups":
      return <FollowUps b={b} onAsk={ctx.onAsk} disabled={ctx.busy} />;
    case "run_badge":
      return <RunBadge b={b} />;
    default: {
      const never: never = b;
      return never;
    }
  }
}

/** One validated answer: badges row, headline, text, a metric strip, visuals, caveats, actions, follow-ups. */
export function AnswerView({ blocks, ctx, testId = "copilot-answer" }: { blocks: AnswerBlock[]; ctx: BlockContext; testId?: string }) {
  const badges = blocks.filter((b): b is BlockOf<"run_badge"> => b.type === "run_badge");
  const metrics = blocks.filter((b): b is BlockOf<"metric"> => b.type === "metric");
  const caveats = blocks.filter((b): b is BlockOf<"uncertainty"> => b.type === "uncertainty");
  const actions = blocks.filter((b): b is BlockOf<"action"> => b.type === "action");
  const follow = blocks.find((b): b is BlockOf<"follow_ups"> => b.type === "follow_ups");
  const comparison = blocks.find((b): b is BlockOf<"comparison"> => b.type === "comparison");
  const flow = blocks.filter((b) => !["run_badge", "metric", "uncertainty", "action", "follow_ups"].includes(b.type));
  // Metric cards sit as one strip right after the first explanation.
  const firstText = flow.findIndex((b) => b.type === "text");
  const insertAt = firstText >= 0 ? firstText + 1 : flow.findIndex((b) => b.type === "headline") + 1;
  const ur = isUrdu(ctx.lang);
  return (
    <div className="flex flex-col gap-3" data-testid={testId} lang={ur ? "ur" : undefined} dir={ur ? "rtl" : undefined}>
      {badges.length ? (
        <div className="flex flex-wrap gap-1.5" dir="ltr">
          {badges.map((b) => (
            <RunBadge key={`${b.role}-${b.run_id}`} b={b} />
          ))}
        </div>
      ) : null}
      {flow.map((b, i) => (
        <div key={i} className="contents">
          {i === insertAt && metrics.length ? <MetricStrip items={metrics} lang={ctx.lang} /> : null}
          <div className="animate-rise min-w-0" dir={b.type === "visual" || b.type === "comparison" ? "ltr" : undefined}>
            <BlockView b={b} ctx={ctx} />
          </div>
        </div>
      ))}
      {insertAt >= flow.length && metrics.length ? <MetricStrip items={metrics} lang={ctx.lang} /> : null}
      <Caveats items={caveats} />
      <div dir="ltr">
        <Actions items={actions} runIdsForCompare={comparison?.run_ids} />
      </div>
      {follow ? <FollowUps b={follow} onAsk={ctx.onAsk} disabled={ctx.busy} /> : null}
    </div>
  );
}

function MetricStrip({ items, lang }: { items: BlockOf<"metric">[]; lang: Lang }) {
  return (
    <div className="grid grid-cols-2 gap-2 animate-rise" dir="ltr" data-testid="copilot-metrics">
      {items.map((m) => (
        <MetricCard key={`${m.run_id}-${m.metric_id}-${m.field_id ?? ""}`} b={m} lang={lang} />
      ))}
    </div>
  );
}

