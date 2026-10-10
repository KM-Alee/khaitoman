/**
 * The headline insight (docs/WIN_PLAN.md W1): one sentence and three tiles from the seeded
 * session's stored runs. The story key and every figure (gains, point changes, budget used)
 * come from GET /demo/headline; this component only picks the sentence for the key and
 * formats server values.
 */
import type { ReactNode } from "react";
import { PlayCircle, Sparkles } from "lucide-react";
import { figureMetric, useHeadline, type DemoHeadline, type HeadlineFigure } from "@/lib/api/showcase";
import { formatDateTime, formatWithUnit, shortId } from "@/lib/formatting";
import { MetricTile } from "@/components/ui/MetricTile";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/status";
import { cn } from "@/lib/cn";

const fmt = (f: HeadlineFigure | null | undefined) => (f && typeof f.value === "number" ? formatWithUnit(f.value, f.unit) : "—");
/** "+18.8%" for a server % figure. */
const signedPct = (f: HeadlineFigure | null | undefined) => (f && typeof f.value === "number" ? `${f.value >= 0 ? "+" : "−"}${formatWithUnit(Math.abs(f.value), f.unit)}` : "—");

export function cropWord(seasonId: string): string {
  const c = seasonId.split("-")[0];
  return c && /^[a-z]+$/.test(c) ? c : "crop";
}

function B({ children }: { children: ReactNode }) {
  return <strong className="num font-semibold text-ink">{children}</strong>;
}

/** The one-sentence story for the server-chosen key. Exported for tests. */
export function HeadlineSentence({ h }: { h: DemoHeadline }) {
  const crop = cropWord(h.season_id);
  const b0 = h.plans.B0;
  const b1 = h.plans.B1;
  const p = h.plans.P;
  const gainB1 = h.production_gain_pct_vs_b0.B1;
  const gainP = h.production_gain_pct_vs_b0.P;
  if (h.story === "tail_tradeoff") {
    return (
      <p data-story="tail_tradeoff">
        Optimising only what exists grew <B>{fmt(gainB1)}</B> more {crop} but cut the worst-off tail field from <B>{fmt(b0.tail_min_service_ratio)}</B> to{" "}
        <B>{fmt(b1.tail_min_service_ratio)}</B> of its water. AabFlow's plan: <B>{signedPct(gainP)}</B> {crop}, tail at <B>{fmt(p.tail_min_service_ratio)}</B>, using{" "}
        <B>{fmt(h.budget_used_fraction)}</B> of the budget.
      </p>
    );
  }
  if (h.story === "budget_efficiency") {
    return (
      <p data-story="budget_efficiency">
        AabFlow's plan grows <B>{signedPct(gainP)}</B> more {crop} than today's routine while spending only <B>{fmt(h.budget_used_fraction)}</B> of the{" "}
        <B>{fmt(h.capital_budget_pkr)}</B> budget. The worst-off tail field gets <B>{fmt(p.tail_min_service_ratio)}</B> of its water.
      </p>
    );
  }
  return (
    <p data-story="plain_gain">
      AabFlow's plan grows <B>{signedPct(gainP)}</B> more {crop} than today's routine, using <B>{fmt(h.budget_used_fraction)}</B> of the budget. The worst-off tail field gets{" "}
      <B>{fmt(p.tail_min_service_ratio)}</B> of its water.
    </p>
  );
}

export function HeadlineTiles({ h, size = "lg" }: { h: DemoHeadline; size?: "md" | "lg" }) {
  const p = h.plans.P;
  const crop = cropWord(h.season_id);
  const gain = h.production_gain_pct_vs_b0.P;
  const tailPts = h.tail_service_change_pts.P;
  return (
    <div className="grid gap-5 sm:grid-cols-3" data-testid="headline-tiles">
      <MetricTile
        size={size}
        label={`${crop[0].toUpperCase()}${crop.slice(1)} grown, AabFlow plan`}
        metric={figureMetric("production_kg", p.production_kg)}
        delta={typeof gain.value === "number" ? { value: gain.value, unit: gain.unit, goodWhen: "up", against: "vs today" } : null}
        accent="wheat"
      />
      <MetricTile
        size={size}
        label="Worst-off tail field's water"
        metric={figureMetric("tail_min_service_ratio", p.tail_min_service_ratio)}
        delta={typeof tailPts.value === "number" ? { value: tailPts.value, unit: tailPts.unit, goodWhen: "up", against: "vs today" } : null}
        hint={<>Optimising only what exists: {fmt(h.plans.B1.tail_min_service_ratio)}</>}
        accent="water"
      />
      <MetricTile
        size={size}
        label="Budget used"
        metric={figureMetric("budget_used_fraction", h.budget_used_fraction)}
        hint={
          <>
            {fmt(p.capital_commitment_pkr)} of {fmt(h.capital_budget_pkr)}
          </>
        }
      />
    </div>
  );
}

export function RunBadges({ h }: { h: DemoHeadline }) {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-tertiary" data-testid="headline-runs">
      <span className="rounded-full bg-wheat-soft px-2 py-0.5 font-medium text-wheat-ink">Saved result</span>
      {(["B0", "B1", "P"] as const).map((k) => {
        const id = h.plans[k].run_id;
        return (
          <span key={k} className="font-mono" title={id}>
            {k} · {shortId(id)} · computed {formatDateTime(h.run_created_at[id])}
          </span>
        );
      })}
    </p>
  );
}

export function HeadlineInsight({ onSeeHow, className }: { onSeeHow?: () => void; className?: string }) {
  const q = useHeadline();
  if (q.isLoading) return <Skeleton className={cn("h-[260px] rounded-[24px]", className)} />;
  if (q.error || !q.data) return null; // no seeded session: the landing page still works without the story
  const h = q.data;
  return (
    <section
      className={cn("animate-rise rounded-[24px] border border-wheat/40 bg-surface p-6 shadow-glow md:p-8", className)}
      aria-labelledby="headline-h"
      data-testid="headline-insight"
      data-story={h.story}
    >
      <p id="headline-h" className="eyebrow flex items-center gap-2 text-wheat-ink">
        <Sparkles size={14} aria-hidden /> What the AI found on this watercourse
      </p>
      <div className="display mt-3 max-w-[62ch] text-[20px] leading-snug text-ink md:text-[24px]">
        <HeadlineSentence h={h} />
      </div>
      {h.groundwater_above_b0 ? (
        <p className="mt-2 text-[13px] text-ink-secondary" data-testid="headline-groundwater">
          Honest trade-off: the plan pumps {fmt(h.plans.P.groundwater_m3)} of groundwater, against {fmt(h.plans.B0.groundwater_m3)} under today's routine, within each well's cap.
        </p>
      ) : null}
      <div className="mt-6">
        <HeadlineTiles h={h} />
      </div>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <RunBadges h={h} />
        {onSeeHow ? (
          <Button variant="primary" size="md" icon={<PlayCircle size={16} />} onClick={onSeeHow} data-testid="headline-see-how">
            See how
          </Button>
        ) : null}
      </div>
    </section>
  );
}
