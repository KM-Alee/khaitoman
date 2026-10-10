/**
 * The five-minute story (PRD §13.2) as tour steps over the REAL application.
 *
 * Every step opens an ordinary route with the saved run/analysis IDs from the demo-session
 * manifest, spotlights a real element, and explains it with numbers read from the server
 * through the normal hooks (never from the manifest's notes, never invented). Each step has
 * a "Try it yourself" action that leaves the tour and focuses the matching live control.
 */
import { useMemo, type ReactNode } from "react";
import { useAnalysis, useComparison, useGeoJSON, useMapBundle, usePilot, useRun, useRuns } from "@/lib/api/queries";
import type { RunResult } from "@/lib/api/types";
import { findMetric, runMetrics } from "@/lib/api/adapters";
import { formatDate, formatDelta, formatPKRCompact, formatWithUnit } from "@/lib/formatting";
import { planName } from "@/lib/glossary";
import { comparisonDeltas } from "@/features/workspace/ResultStrip";
import { FLAG_PLAIN } from "@/components/status";
import type { DemoSession } from "./api";

export type Placement = "auto" | "center";

export interface TourCtx {
  session: DemoSession;
  /** Leave the tour (keeps the current page and selections). */
  exit: () => void;
  navigate: (to: string) => void;
  /** Copy a stored revision's settings into the editable Plan draft. */
  adoptRevision: (revisionId: string, then?: "run" | "focus-budget" | "focus-run") => void;
  focus: (selector: string) => void;
  highlight: (fieldIds: string[] | null) => void;
  setMapMetric: (m: "yield" | "service" | "change" | "group") => void;
  overview: () => void;
  openAssistant: () => void;
}

export interface TourStep {
  id: string;
  chapter: string;
  title: string;
  /** Rendered inside the coach card; may use hooks (it is a component). */
  Body: (p: { s: DemoSession }) => ReactNode;
  /** Route to open, built from the manifest's IDs. */
  route: (s: DemoSession) => string;
  /** CSS selector of the real element to spotlight; none = centred card. */
  target?: string;
  placement?: Placement;
  /** The stored run or analysis this step shows (for the "Saved result" label). */
  saved?: (s: DemoSession) => { runId?: string | null; analysisId?: string | null };
  onEnter?: (c: TourCtx) => void;
  tryIt?: { label: string; run: (c: TourCtx) => void };
  /** Offer "Re-run live" (solves these saved settings again, as a new scenario). */
  rerun?: (s: DemoSession) => string;
  /** Seconds before auto-advance (autoplay). */
  seconds?: number;
}

const base = (s: DemoSession) => `/p/${encodeURIComponent(s.pilot_id)}/${encodeURIComponent(s.pilot_version)}`;
const q = (o: Record<string, string | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v) u.set(k, v);
  const t = u.toString();
  return t ? `?${t}` : "";
};

function metricValue(run: RunResult | undefined, id: string) {
  const m = findMetric(runMetrics(run), id);
  return m && m.status === "available" && typeof m.value === "number" ? m : null;
}

function Num({ children }: { children: ReactNode }) {
  return <strong className="num font-semibold text-ink">{children}</strong>;
}

/** A field's reviewed label, read from the session's own pilot package (the tour runs outside pilot routes too). */
function useSessionFieldLabel(s: DemoSession, fieldId: string | null | undefined) {
  const map = useMapBundle(s.pilot_id, s.pilot_version);
  const geo = useGeoJSON(map.data?.fields?.data ? null : map.data?.fields?.url ?? null);
  const fc = (map.data?.fields?.data as GeoJSON.FeatureCollection | undefined) ?? geo.data ?? null;
  if (!fieldId) return null;
  const f = fc?.features.find((x) => String((x.properties as Record<string, unknown> | null)?.field_id ?? x.id) === fieldId);
  return (f?.properties as Record<string, unknown> | null)?.label ? String((f!.properties as Record<string, unknown>).label) : fieldId.replace(/^[^:]+:/, "");
}

/* ------------------------------------------------------------------ step bodies */
function WelcomeBody({ s }: { s: DemoSession }) {
  const pilot = usePilot(s.pilot_id, s.pilot_version);
  const field = useSessionFieldLabel(s, s.focus_field_id);
  return (
    <>
      <p>
        This is <Num>{pilot.data?.pilot?.name ?? s.pilot_id}</Num>: real fields and mapped canals in Punjab's Lower Chenab irrigation area. Its committee can fund only some of the
        improvements farmers ask for: land levelling, a farm pond, a canal repair, extra pumping.
      </p>
      <p>
        We will follow one tail-end field, <Num>{field ?? "the focus field"}</Num>, and ask: which works deserve the money, and who would still go short of water?
      </p>
    </>
  );
}

function FieldsBody({ s }: { s: DemoSession }) {
  const pilot = usePilot(s.pilot_id, s.pilot_version);
  const field = useSessionFieldLabel(s, s.focus_field_id);
  const p = pilot.data?.pilot;
  const im = p?.imagery?.[0];
  const f = p?.review_flags;
  const assumed = f
    ? (
        [
          f.rights_verification !== "verified" ? "water turns" : null,
          f.cost_evidence !== "quoted" ? "costs" : null,
          f.crop_calibration !== "calibrated" ? "crop-model calibration" : null,
        ] as (string | null)[]
      ).filter(Boolean)
    : [];
  return (
    <>
      <p>
        The background is a real Sentinel-2 satellite image{im ? <> from <Num>{formatDate(im.acquired_at)}</Num></> : null}. Each field outline was drawn by an AI model and then checked by a
        person. Field <Num>{field}</Num> sits at the tail end, where water arrives last.
      </p>
      {assumed.length ? (
        <p>
          Still assumed until checked locally: <Num>{assumed.join(", ")}</Num>. {f && f.rights_verification !== "verified" ? FLAG_PLAIN.rights_verification.not : ""}
        </p>
      ) : null}
    </>
  );
}

function PlansBody({ s }: { s: DemoSession }) {
  const ids = (["B0", "B1", "P"] as const).map((k) => s.base.runs[k]).filter(Boolean) as string[];
  const runs = useRuns(ids);
  const byKind = new Map((runs.data ?? []).map((r) => [r.plan_kind, r]));
  const prod = (k: "B0" | "B1" | "P") => metricValue(byKind.get(k), "production_kg");
  const capex = metricValue(byKind.get("P"), "capital_commitment_pkr");
  return (
    <>
      <p>The same season, solved three ways under identical weather, canal water and prices:</p>
      <ul className="flex flex-col gap-1.5">
        {(["B0", "B1", "P"] as const).map((k) => (
          <li key={k} className="flex items-baseline justify-between gap-3 rounded-[10px] bg-surface-muted/70 px-3 py-1.5">
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: `var(--plan-${k.toLowerCase()})` }} aria-hidden />
              {planName(k)}
            </span>
            <Num>{prod(k) ? formatWithUnit(prod(k)!.value as number, prod(k)!.unit) : "…"}</Num>
          </li>
        ))}
      </ul>
      {capex ? (
        <p>
          The recommended plan commits <Num>{formatPKRCompact(capex.value as number)}</Num> to new works.
        </p>
      ) : null}
    </>
  );
}

function StepsBody({ s }: { s: DemoSession }) {
  const ids = (["B0", "B1", "P"] as const).map((k) => s.base.runs[k]).filter(Boolean) as string[];
  const cmp = useComparison(ids);
  const inc = (cmp.data?.incremental as { step: string; production_kg?: number | null; groundwater_m3?: number | null }[] | undefined) ?? [];
  const st = (k: string) => inc.find((x) => x.step === k);
  return (
    <>
      <p>Where does the extra harvest come from? The comparison service splits it into steps:</p>
      <p>
        Timing water better with existing ponds and pumps adds <Num>{typeof st("B0->B1")?.production_kg === "number" ? formatDelta(st("B0->B1")!.production_kg!, "kg") : "…"}</Num>, at no capital
        cost. The new works then add <Num>{typeof st("B1->P")?.production_kg === "number" ? formatDelta(st("B1->P")!.production_kg!, "kg") : "…"}</Num>.
      </p>
      <p className="text-ink-tertiary">Where more harvest also means more pumping, the card says so instead of hiding it.</p>
    </>
  );
}

function BudgetBody({ s }: { s: DemoSession }) {
  const a = useRun(s.base.runs.P);
  const b = useRun(s.budget_change.runs.P);
  const cmp = useComparison(s.base.runs.P && s.budget_change.runs.P ? [s.base.runs.P, s.budget_change.runs.P] : []);
  const d = useMemo(() => comparisonDeltas(cmp.data, null), [cmp.data]);
  const before = (s.scenario_request as { capital_budget_pkr?: number }).capital_budget_pkr;
  const after = (s.budget_change.changes as { capital_budget_pkr?: number }).capital_budget_pkr;
  const prodB = metricValue(b.data, "production_kg");
  const capB = metricValue(b.data, "capital_commitment_pkr");
  const dropped = useMemo(() => {
    if (a.data?.outcome !== "plan" || b.data?.outcome !== "plan") return null;
    const kept = new Set(b.data.selected_intervention_instance_ids);
    return a.data.selected_intervention_instance_ids.filter((x) => !kept.has(x));
  }, [a.data, b.data]);
  const dProd = d.get("production_kg");
  return (
    <>
      <p>
        What if the committee has only <Num>{typeof after === "number" ? formatPKRCompact(after) : "less"}</Num> for works instead of{" "}
        <Num>{typeof before === "number" ? formatPKRCompact(before) : "the full budget"}</Num>? We changed that one number and solved again.
      </p>
      <p>
        The new plan spends <Num>{capB ? formatPKRCompact(capB.value as number) : "…"}</Num>, drops <Num>{dropped ? dropped.length : "…"}</Num> of the costlier works, and still grows{" "}
        <Num>{prodB ? formatWithUnit(prodB.value as number, prodB.unit) : "…"}</Num>
        {dProd ? <> ({formatDelta(dProd.value, dProd.unit)} vs the full budget)</> : null}.
      </p>
    </>
  );
}

function ReplayBody({ s }: { s: DemoSession }) {
  const field = useSessionFieldLabel(s, s.focus_field_id);
  return (
    <>
      <p>
        Now the season, day by day, for field <Num>{field}</Num>: when its canal turn arrives, when water is applied, pond levels and how the crop canopy grows.
      </p>
      {s.decisive_date ? (
        <p>
          We jumped to <Num>{formatDate(String(s.decisive_date))}</Num>, the day this field draws the most stored pond and pumped water of the season, between canal turns.
        </p>
      ) : null}
      <p className="text-ink-tertiary">These are the crop model's own daily outputs; nothing is interpolated.</p>
    </>
  );
}

function FrontierBody() {
  return (
    <>
      <p>
        <Num>Spend more or less?</Num> The same question was solved independently at several budgets. Each dot is a complete saved plan you can open.
      </p>
      <p>Where the curve flattens, extra money buys little extra harvest. That is often where a committee should stop.</p>
    </>
  );
}

function StressBody({ s }: { s: DemoSession }) {
  const a = useAnalysis(s.analyses.stress);
  const cells = ((a.data?.result as { cells?: { weather_scenario_id?: string; supply_label?: string; deliverable?: boolean }[] } | undefined)?.cells ?? []);
  const weathers = [...new Set(cells.map((c) => c.weather_scenario_id).filter(Boolean))];
  const supplies = [...new Set(cells.map((c) => c.supply_label).filter(Boolean))];
  const ok = cells.filter((c) => c.deliverable).length;
  return (
    <>
      <p>
        The bad-year-proof plan, checked under <Num>{cells.length || "9"} conditions</Num>
        {weathers.length && supplies.length ? (
          <>
            : {weathers.join(", ")} weather, each with {supplies.join(", ")} canal supply
          </>
        ) : null}
        .
      </p>
      <p>
        Each cell first answers <Num>can this plan still be carried out?</Num>
        {cells.length ? (
          <>
            {" "}
            Here: <Num>{ok} of {cells.length}</Num> yes.
          </>
        ) : null}{" "}
        Only then does it show a harvest. These are tested scenarios, not probabilities.
      </p>
    </>
  );
}

function ImpactBody() {
  return (
    <>
      <p>
        Beyond the harvest: for the bad-year-proof plan, three indicators linked to UN goals for <Num>food</Num> (harvest kept in the worst tested year), <Num>water</Num> (crop per cubic
        metre) and <Num>climate resilience</Num>. Water accounts, money and fairness between head-end and tail-end fields are one tab away.
      </p>
      <p className="text-ink-tertiary">Each card opens its formula and sources. There is no made-up 0–100 score.</p>
    </>
  );
}

function ReportBody() {
  return <p>A printable action plan for the committee: each work, its dates, cost, who approves it and which fields it affects, with every number tied to its saved run.</p>;
}

function TrustBody() {
  return (
    <>
      <p>
        <Num>Can I trust it?</Num> Here is what is real (imagery, AI boundaries, historical weather, executed models), what is still assumed, and exactly how this result was made.
      </p>
      <p className="text-ink-tertiary">Saved results never change. A correction creates a new version you can compare.</p>
    </>
  );
}

function FinishBody() {
  return (
    <p>
      That was a saved, real result. Everything you saw is live: change any setting, pick the other watercourse or season, run new plans and tests, or ask AabFlow in plain words.
    </p>
  );
}

/* ------------------------------------------------------------------ the route */
export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    chapter: "The decision",
    title: "One watercourse, limited money",
    Body: WelcomeBody,
    route: (s) => `${base(s)}/workspace${q({ run: s.base.runs.P })}`,
    target: '[data-tour="map-intro"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    onEnter: (c) => {
      c.setMapMetric("yield");
      c.overview();
    },
    tryIt: { label: "Explore the map", run: (c) => c.focus('[data-testid="map-slot"] canvas, [data-testid="map-slot"]') },
    seconds: 11,
  },
  {
    id: "fields",
    chapter: "Real geography",
    title: "Real imagery, AI-drawn fields",
    Body: FieldsBody,
    route: (s) => `${base(s)}/workspace${q({ run: s.base.runs.P, field: s.focus_field_id })}`,
    target: '[data-testid="map-slot"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    onEnter: (c) => {
      c.setMapMetric("group");
    },
    tryIt: { label: "Pick any field", run: (c) => c.focus("#field-search") },
    seconds: 12,
  },
  {
    id: "plans",
    chapter: "Three plans",
    title: "Today, smarter timing, recommended",
    Body: PlansBody,
    route: (s) => `${base(s)}/compare${q({ run: s.base.runs.P })}`,
    target: '[data-tour="plan-cards"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    onEnter: (c) => c.setMapMetric("yield"),
    tryIt: { label: "Solve with my own settings", run: (c) => c.adoptRevision(c.session.base.revision_id, "focus-run") },
    rerun: (s) => s.base.revision_id,
    seconds: 12,
  },
  {
    id: "steps",
    chapter: "Three plans",
    title: "Where the gain comes from",
    Body: StepsBody,
    route: (s) => `${base(s)}/compare${q({ run: s.base.runs.P })}`,
    target: '[data-tour="step-story"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    tryIt: { label: "See all the numbers", run: (c) => c.focus('[data-testid="ladder"] button, [data-testid="ladder"]') },
    seconds: 12,
  },
  {
    id: "budget",
    chapter: "A budget change",
    title: "Less money: what changes?",
    Body: BudgetBody,
    route: (s) => `${base(s)}/workspace${q({ run: s.budget_change.runs.P })}`,
    target: '[data-tour="result"]',
    saved: (s) => ({ runId: s.budget_change.runs.P }),
    onEnter: (c) => c.setMapMetric("yield"),
    tryIt: { label: "Change the budget myself", run: (c) => c.adoptRevision(c.session.budget_change.revision_id, "focus-budget") },
    rerun: (s) => s.budget_change.revision_id,
    seconds: 13,
  },
  {
    id: "replay",
    chapter: "The season",
    title: "Replay the decisive days",
    Body: ReplayBody,
    route: (s) => `${base(s)}/replay${q({ run: s.base.runs.P, field: s.focus_field_id, date: s.decisive_date ? String(s.decisive_date) : null })}`,
    target: '[data-tour="timeline"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    tryIt: { label: "Scrub through the season", run: (c) => c.focus('[data-testid="date-slider"]') },
    seconds: 12,
  },
  {
    id: "frontier",
    chapter: "What if",
    title: "Spend more or less?",
    Body: FrontierBody,
    route: (s) => `${base(s)}/explore${q({ tab: "frontier", analysis: s.analyses.frontier, run: s.base.runs.P })}`,
    target: '[data-testid="frontier-chart"]',
    saved: (s) => ({ analysisId: s.analyses.frontier }),
    tryIt: { label: "Try other budgets", run: (c) => c.focus('[data-testid="run-frontier"]') },
    seconds: 11,
  },
  {
    id: "stress",
    chapter: "What if",
    title: "Bad years and canal cuts",
    Body: StressBody,
    route: (s) => `${base(s)}/explore${q({ tab: "stress", analysis: s.analyses.stress, run: s.base.runs.R })}`,
    target: '[data-testid="stress-matrix"]',
    saved: (s) => ({ analysisId: s.analyses.stress }),
    tryIt: { label: "Test another plan", run: (c) => c.focus('[data-testid="run-stress"]') },
    seconds: 12,
  },
  {
    id: "impact",
    chapter: "Impact",
    title: "Who benefits, beyond the harvest",
    Body: ImpactBody,
    route: (s) => `${base(s)}/impact${q({ tab: "sdg", run: s.base.runs.R })}`,
    target: '[aria-label="SDG proxy cards"]',
    saved: (s) => ({ runId: s.base.runs.R }),
    tryIt: { label: "Open the fairness view", run: (c) => c.focus('[data-tab="equity"]') },
    seconds: 11,
  },
  {
    id: "report",
    chapter: "Impact",
    title: "The committee's action plan",
    Body: ReportBody,
    route: (s) => `${base(s)}/report${q({ run: s.base.runs.P })}`,
    target: '[data-tour="report"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    tryIt: { label: "Export the package", run: (c) => c.focus('[data-testid="export-report"]') },
    seconds: 10,
  },
  {
    id: "trust",
    chapter: "Trust",
    title: "Can I trust these numbers?",
    Body: TrustBody,
    route: (s) => `${base(s)}/evidence${q({ run: s.base.runs.P })}`,
    target: '[data-tour="trust"]',
    saved: (s) => ({ runId: s.base.runs.P }),
    tryIt: { label: "Look up a source", run: (c) => c.focus('[data-testid="evidence-search"]') },
    seconds: 11,
  },
  {
    id: "finish",
    chapter: "Your turn",
    title: "Now try it yourself",
    Body: FinishBody,
    route: (s) => `${base(s)}/workspace${q({ run: s.base.runs.P })}`,
    placement: "center",
  },
];
