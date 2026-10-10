import { useMemo } from "react";
import { FileDown, Info } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useRun } from "@/lib/api/queries";
import { fieldMetricMap, findMetric, runMetrics } from "@/lib/api/adapters";
import type { MetricValue, RunResult } from "@/lib/api/types";
import { formatPercent, formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, MetricValueView, Skeleton, StatePanel, metricText } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogContent, DialogTrigger, Eyebrow } from "@/components/ui/primitives";
import { SubTabs } from "@/features/compare/CompareTabs";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { useLadderRuns } from "@/features/compare/CompareScreen";
import { cn } from "@/lib/cn";

const TABS = [
  { value: "water", label: "Water accounting" },
  { value: "economics", label: "Economics" },
  { value: "equity", label: "Equity" },
  { value: "sdg", label: "SDG proxies" },
];

export function ImpactNav() {
  const { sel } = usePilotData();
  return (
    <nav aria-label="Impact views" className="no-print flex h-11 shrink-0 items-center gap-1 border-b border-border bg-surface px-3">
      {[
        { s: "impact" as const, l: "Impact" },
        { s: "report" as const, l: "Action plan & report" },
      ].map((t) => (
        <a
          key={t.s}
          href={sel.hrefFor(t.s)}
          onClick={(e) => {
            e.preventDefault();
            sel.go(t.s);
          }}
          aria-current={sel.screen === t.s ? "page" : undefined}
          className={cn(
            "relative inline-flex h-11 items-center px-3 text-[13px] font-medium text-ink-secondary hover:text-ink",
            sel.screen === t.s && "text-ink after:absolute after:inset-x-2 after:bottom-0 after:h-[2px] after:rounded-full after:bg-water",
          )}
        >
          {t.l}
        </a>
      ))}
    </nav>
  );
}

export function ImpactScreen() {
  const { sel } = usePilotData();
  const run = useRun(sel.runId);
  const tab = TABS.some((t) => t.value === sel.tab) ? sel.tab! : "water";
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="impact">
      <ImpactNav />
      <SubTabs label="Impact sections" tabs={TABS} value={tab} onChange={(v) => sel.setParams({ tab: v })} />
      <div className="min-h-0 flex-1 overflow-y-auto p-3 md:p-4">
        {!sel.runId ? (
          <div className="mx-auto max-w-[560px] pt-10">
            <StatePanel state="empty" title="Impact needs a run" action={{ label: "Go to Workspace", onClick: () => sel.go("workspace") }}>
              Water accounting, economics, equity and SDG proxies are computed by the server for a completed run.
            </StatePanel>
          </div>
        ) : run.isLoading ? (
          <div className="grid gap-3 md:grid-cols-2">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
        ) : run.error || !run.data ? (
          <StatePanel state="error" error={run.error} title="Run unavailable" />
        ) : run.data.outcome !== "plan" ? (
          <StatePanel state={run.data.solver_status === "INFEASIBLE" ? "infeasible" : "unknown"} title={`No plan (${run.data.solver_status})`}>
            Impact metrics exist only for runs with a validated plan.
          </StatePanel>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[12px] text-ink-secondary">
              <Chip size="sm" tone="ink">{run.data.plan_kind} · run {shortId(run.data.run_id)}</Chip>
              Metric values come from the server registry shared with the report and copilot.
              <Button size="sm" variant="secondary" className="ml-auto" icon={<FileDown size={14} />} onClick={() => sel.go("report")}>
                Export report
              </Button>
            </div>
            {tab === "water" ? <WaterLedger run={run.data} /> : null}
            {tab === "economics" ? <Economics run={run.data} /> : null}
            {tab === "equity" ? <Equity run={run.data} /> : null}
            {tab === "sdg" ? <SDG run={run.data} /> : null}
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- water */
const LEDGER: { id: string[]; label: string; from: string; to: string }[] = [
  { id: ["source_withdrawal_m3", "canal_source_m3"], label: "Source withdrawal", from: "Source", to: "Network" },
  { id: ["conveyance_loss_m3", "edge_loss_m3"], label: "Conveyance loss", from: "Network", to: "Conveyance loss" },
  { id: ["outlet_receipt_m3", "canal_receipt_m3"], label: "Delivered at outlets", from: "Network", to: "Outlets" },
  { id: ["direct_application_m3", "direct_irrigation_m3"], label: "Direct irrigation", from: "Outlets", to: "Field application" },
  { id: ["pond_fill_m3"], label: "To pond storage", from: "Outlets", to: "Ponds" },
  { id: ["pond_rain_m3"], label: "Pond rainfall", from: "Rainfall", to: "Ponds" },
  { id: ["pond_release_m3"], label: "Pond release", from: "Ponds", to: "Field application" },
  { id: ["pond_loss_m3", "pond_evaporation_seepage_m3"], label: "Pond evaporation + seepage", from: "Ponds", to: "Pond losses" },
  { id: ["pond_residual_m3", "pond_end_inventory_m3"], label: "Pond inventory at season end", from: "Ponds", to: "Carried inventory" },
  { id: ["groundwater_m3", "pump_abstraction_m3"], label: "Groundwater pumped", from: "Groundwater", to: "Field application" },
  { id: ["unused_window_m3"], label: "Unused window allowance", from: "Outlets", to: "Unused" },
];

function WaterLedger({ run }: { run: RunResult }) {
  const ms = runMetrics(run);
  const t = chartTokens();
  const flows = LEDGER.map((l) => ({ ...l, m: findMetric(ms, ...l.id) })).filter((x) => x.m);
  const avail = flows.filter((f) => f.m!.status === "available" && (f.m!.value ?? 0) > 0);
  const app = findMetric(ms, "field_application_m3", "gross_application_m3");
  const nodes = [...new Set(avail.flatMap((f) => [f.from, f.to]))];
  const option = {
    ...baseOption(),
    tooltip: { trigger: "item", backgroundColor: t.surface, borderColor: t.border, textStyle: { color: t.ink }, valueFormatter: (v: number) => formatWithUnit(v, "m3") },
    series: [
      {
        type: "sankey",
        left: 8,
        right: 120,
        top: 12,
        bottom: 12,
        nodeGap: 14,
        nodeWidth: 12,
        draggable: false,
        emphasis: { focus: "adjacency" },
        label: { color: t.ink, fontSize: 12, fontFamily: t.font },
        lineStyle: { color: "gradient", opacity: 0.35, curveness: 0.5 },
        data: nodes.map((n) => ({
          name: n,
          itemStyle: { color: /loss|Unused/i.test(n) ? t.danger : /Ground/i.test(n) ? t.warning : /Rain/i.test(n) ? t.series[3] : /Pond|Carried/i.test(n) ? t.waterDeep : /Field/i.test(n) ? t.veg : t.water },
        })),
        links: avail.map((f) => ({ source: f.from, target: f.to, value: f.m!.value })),
      },
    ],
  };
  if (!flows.length)
    return (
      <StatePanel state="empty" title="No water-accounting metrics in this run">
        The run reports none of the ledger boundary totals (source withdrawal, conveyance, outlet receipts, storage, groundwater).
      </StatePanel>
    );
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <ChartPanel
        id="water-sankey"
        title="Water ledger by accounting boundary"
        summary="Source → conveyance → outlets → direct irrigation or storage → field application; groundwater and rainfall enter explicitly. ET is not added as a separate loss."
        chart={nodes.length ? <EChart option={option} height={360} ariaLabel="Sankey of seasonal water flows; table view lists every amount" /> : <p className="p-4 text-[13px] text-ink-secondary">All ledger totals are zero or unavailable.</p>}
        table={
          <DataTable
            caption="Water ledger"
            columns={[
              { key: "l", label: "Flow" },
              { key: "b", label: "Boundary" },
              { key: "v", label: "Seasonal volume", align: "right" },
            ]}
            rows={flows.map((f) => ({ l: f.label, b: `${f.from} → ${f.to}`, v: metricText(f.m) }))}
          />
        }
      />
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <Eyebrow className="mb-2">Boundary totals</Eyebrow>
        <dl className="flex flex-col divide-y divide-border">
          {[...flows, ...(app ? [{ label: "Gross field application", m: app }] : [])].map((f) => (
            <div key={f.label} className="flex items-baseline justify-between gap-3 py-2">
              <dt className="text-[13px] text-ink-secondary">{f.label}</dt>
              <dd>
                <MetricValueView metric={f.m} size="sm" />
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 flex gap-1.5 text-[12px] text-ink-secondary">
          <Info size={13} className="mt-0.5 shrink-0" aria-hidden />
          Withdrawals reduced are not consumptive water savings. Basin-wide savings stay <em>not estimated</em> unless return flows are accounted for.
        </p>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- economics */
const ECON: { ids: string[]; label: string }[] = [
  { ids: ["gross_project_cost_pkr", "capex_pkr", "capital_commitment_pkr"], label: "Gross project cost" },
  { ids: ["public_grant_pkr", "verified_grant_pkr"], label: "Public grant (verified only)" },
  { ids: ["participant_cash_pkr"], label: "Participant cash requirement" },
  { ids: ["seasonal_pumping_cost_pkr", "pumping_cost_pkr"], label: "Seasonal pumping" },
  { ids: ["seasonal_upkeep_pkr", "upkeep_pkr"], label: "Seasonal upkeep" },
  { ids: ["seasonal_opex_pkr", "operating_cost_pkr"], label: "Total seasonal operating" },
  { ids: ["crop_value_pkr"], label: "Crop value (assumed price)" },
  { ids: ["incremental_irrigation_contribution_pkr", "irrigation_contribution_pkr"], label: "Irrigation contribution" },
  { ids: ["payback_years", "payback"], label: "Payback" },
];

function Economics({ run }: { run: RunResult }) {
  const ms = runMetrics(run);
  const rows = ECON.map((e) => ({ ...e, m: findMetric(ms, ...e.ids) }));
  const shown = rows.filter((r) => r.m);
  const t = chartTokens();
  const capex = shown.filter((r) => /cost|grant|cash/i.test(r.label) && r.m?.status === "available");
  const option = {
    ...baseOption(),
    grid: { left: 180, right: 24, top: 8, bottom: 24 },
    tooltip: { ...(baseOption().tooltip as object), trigger: "item", valueFormatter: (v: number) => formatWithUnit(v, "PKR") },
    xAxis: { ...(baseOption().xAxis as object), type: "value", axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatWithUnit(v, "PKR").replace("PKR ", "") } },
    yAxis: { ...(baseOption().yAxis as object), type: "category", data: capex.map((r) => r.label), axisLabel: { color: t.ink2, fontSize: 12 } },
    series: [{ type: "bar", data: capex.map((r) => r.m!.value), itemStyle: { color: t.water, borderRadius: [0, 4, 4, 0] }, barMaxWidth: 18 }],
  };
  if (!shown.length)
    return <StatePanel state="empty" title="No financial metrics">This run reports no economics. Null prices or costs disable the corresponding calculation rather than defaulting to zero.</StatePanel>;
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <ChartPanel
        id="econ-chart"
        title="Capital and cash breakdown"
        summary="The capital budget constrains gross project commitment; a verified grant changes participant cash only."
        chart={capex.length ? <EChart option={option} height={Math.max(160, capex.length * 44)} ariaLabel="Bar chart of capital breakdown" /> : <p className="p-4 text-[13px] text-ink-secondary">No capital amounts available.</p>}
        table={<DataTable caption="Financial breakdown" columns={[{ key: "l", label: "Item" }, { key: "v", label: "Value", align: "right" }]} rows={shown.map((r) => ({ l: r.label, v: metricText(r.m) }))} />}
      />
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <Eyebrow className="mb-2">Financial panel</Eyebrow>
        <dl className="flex flex-col divide-y divide-border">
          {shown.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3 py-2">
              <dt className="text-[13px] text-ink-secondary">{r.label}</dt>
              <dd className="text-right">
                <MetricValueView metric={r.m} size="sm" />
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- equity */
function Equity({ run }: { run: RunResult }) {
  const { fieldIndex, sel } = usePilotData();
  const ms = runMetrics(run);
  const svc = fieldMetricMap(ms, "field_service_ratio", "service_ratio");
  const gw = fieldMetricMap(ms, "groundwater_m3", "field_groundwater_m3");
  const t = chartTokens();
  const groups = ["head", "middle", "tail"] as const;
  const pts = [...svc.entries()].map(([fid, m]) => ({ fid, m, g: fieldIndex.get(fid)?.group ?? null, label: fieldIndex.get(fid)?.label ?? fid }));
  const zeroEnt = pts.filter((p) => p.m.status === "not_applicable");
  const valid = pts.filter((p) => p.m.status === "available" && typeof p.m.value === "number");
  const minM = findMetric(ms, "min_eligible_fulfillment", "min_service_ratio", "minimum_eligible_service");
  const aggBasis = findMetric(ms, "service_aggregation_basis");
  const option = {
    ...baseOption(),
    grid: { left: 70, right: 24, top: 16, bottom: 36 },
    tooltip: { trigger: "item", backgroundColor: t.surface, borderColor: t.border, textStyle: { color: t.ink }, formatter: (p: { data: { label: string; value: [number, number] } }) => `${p.data.label}<br/>${formatPercent(p.data.value[0])}` },
    xAxis: { ...(baseOption().xAxis as object), type: "value", min: 0, max: (v: { max: number }) => Math.max(1, Math.ceil(v.max * 10) / 10), name: "Receipt / reference allowance", nameLocation: "middle", nameGap: 24, axisLabel: { color: t.ink3, formatter: (v: number) => formatPercent(v) }, splitLine: { show: true, lineStyle: { color: t.border, opacity: 0.6 } } },
    yAxis: { ...(baseOption().yAxis as object), type: "category", data: groups.map(titleCase), axisLabel: { color: t.ink2, fontSize: 12 } },
    series: [
      {
        type: "scatter",
        symbolSize: 12,
        data: valid.map((p, i) => ({ value: [p.m.value, groups.indexOf((p.g ?? "middle") as (typeof groups)[number]) + ((i % 5) - 2) * 0.06], label: p.label, fid: p.fid, itemStyle: { color: p.g === "tail" ? t.warning : p.g === "head" ? t.water : t.veg, borderColor: t.surface, borderWidth: 1 } })),
        markLine: { silent: true, symbol: "none", lineStyle: { color: t.ink3, type: "dashed" }, data: [{ xAxis: 1 }], label: { formatter: "full reference", color: t.ink3 } },
      },
    ],
  };
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <ChartPanel
        id="equity-chart"
        title="Service by head / middle / tail"
        summary={
          <>
            Field canal receipts ÷ the fixed reference allowance at the same boundary (receipt / reference allowance, not a legal quota). {zeroEnt.length ? `${zeroEnt.length} zero-entitlement field(s) are excluded and listed below.` : ""}
          </>
        }
        chart={valid.length ? <EChart option={option} height={260} ariaLabel="Strip plot of field service ratios by group" onEvents={{ click: (p) => { const f = (p as { data?: { fid?: string } }).data?.fid; if (f) sel.setParams({ field: f }, false); } }} /> : <p className="p-4 text-[13px] text-ink-secondary">No per-field service ratios in this run.</p>}
        table={
          <DataTable
            caption="Field service and pumping"
            columns={[
              { key: "f", label: "Field" },
              { key: "g", label: "Group" },
              { key: "s", label: "Service", align: "right" },
              { key: "gw", label: "Groundwater", align: "right" },
            ]}
            rows={pts
              .sort((a, b) => (a.m.value ?? 9) - (b.m.value ?? 9))
              .map((p) => ({ f: p.label, g: p.g ? titleCase(p.g) : "—", s: metricText(p.m), gw: metricText(gw.get(p.fid)) }))}
          />
        }
      />
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <Eyebrow className="mb-2">Equity summary</Eyebrow>
        <dl className="flex flex-col divide-y divide-border">
          {[
            ["Minimum eligible fulfillment", minM],
            ["Tail minimum service", findMetric(ms, "tail_min_service", "tail_min_service_ratio")],
            ["Fields worse off vs baseline", findMetric(ms, "fields_worse_off", "fields_worse_off_count")],
            ["Pumping burden (groundwater)", findMetric(ms, "groundwater_m3", "total_groundwater_m3")],
          ].map(([l, m]) => (
            <div key={l as string} className="flex items-baseline justify-between gap-3 py-2">
              <dt className="text-[13px] text-ink-secondary">{l as string}</dt>
              <dd>
                <MetricValueView metric={m as MetricValue | null} size="sm" />
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-[12px] text-ink-secondary">
          Aggregation: {aggBasis?.reason ?? "field-weighted unless the metric definition states entitlement-volume weighting"}. No aggregate score hides fields with reduced service.
        </p>
        {zeroEnt.length ? <p className="mt-2 text-[12px] text-ink-secondary">Zero-entitlement: {zeroEnt.map((z) => z.label).join(", ")}</p> : null}
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- SDG */
const SDG_CARDS = [
  {
    id: "2.4",
    title: "SDG 2.4 · Sustainable food production",
    ids: ["sdg_2_4_production_retained", "production_retained_fraction", "worst_tested_production_kg", "production_kg"],
    interp: "Model-based planning resilience, not measured food security.",
  },
  {
    id: "6.4",
    title: "SDG 6.4 / 6.5 · Water-use efficiency and management",
    ids: ["withdrawal_productivity_kg_m3", "sdg_6_4_water_productivity"],
    interp: "Water productivity / accounting / participation proxies, not official UN indicator scores.",
  },
  {
    id: "13.1",
    title: "SDG 13.1 · Resilience to climate hazards",
    ids: ["worst_tested_production_kg", "sdg_13_1_worst_case_gap", "typical_vs_worst_gap_kg"],
    interp: "Scenario robustness within nine tested states, not quantified disaster-risk reduction.",
  },
];

function SDG({ run }: { run: RunResult }) {
  const ms = runMetrics(run);
  return (
    <div className="grid gap-3 lg:grid-cols-3" data-testid="sdg">
      {SDG_CARDS.map((c) => {
        const m = findMetric(ms, ...c.ids);
        const extra = c.id === "6.4" ? [findMetric(ms, "groundwater_m3"), findMetric(ms, "mean_entitlement_fulfillment", "field_service_ratio_mean")].filter(Boolean) : [];
        return (
          <article key={c.id} className="flex flex-col rounded-[14px] border border-border bg-surface p-4 shadow-1" data-testid="sdg-card">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-[13px] font-semibold leading-snug text-ink">{c.title}</h3>
              <Chip size="sm" tone="warning" title="official_indicator=false">Project proxy</Chip>
            </div>
            <div className="mt-3">
              <MetricValueView metric={m} size="lg" />
            </div>
            {extra.map((e) => (
              <div key={e!.metric_id} className="mt-1 text-[12px] text-ink-secondary">
                {titleCase(e!.definition_id)}: <MetricValueView metric={e} size="sm" showReason={false} />
              </div>
            ))}
            <p className="mt-3 text-[12px] text-ink-secondary">{c.interp}</p>
            <p className="mt-1 text-[11px] text-ink-tertiary">official_indicator = false · No 0–100 score · No CO₂ figure without cited energy factors.</p>
            <div className="mt-auto pt-3">
              <Dialog>
                <DialogTrigger asChild>
                  <Button size="sm" variant="secondary" disabled={!m}>
                    How was this calculated?
                  </Button>
                </DialogTrigger>
                {m ? (
                  <DialogContent title={c.title} description="Formula, run reference and sources">
                    <div className="flex flex-col gap-3 p-5 text-[13px]">
                      <div>
                        <Eyebrow>Definition</Eyebrow>
                        <p className="mt-1 font-mono text-[12px] text-ink">{m.formula ?? m.definition_id}</p>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-[12px]">
                        <span className="text-ink-secondary">Metric id</span>
                        <span className="font-mono text-ink">{m.metric_id}</span>
                        <span className="text-ink-secondary">Run</span>
                        <span className="font-mono text-ink">{m.run_id}</span>
                        <span className="text-ink-secondary">Unit</span>
                        <span className="text-ink">{m.unit}</span>
                        <span className="text-ink-secondary">Status</span>
                        <span className="text-ink">{m.status.replace(/_/g, " ")}</span>
                      </div>
                      {m.reason ? <p className="text-ink-secondary">{m.reason}</p> : null}
                      <p className="text-ink-secondary">{c.interp}</p>
                      {m.evidence_ids.map((id) => (
                        <EvidenceById key={id} id={id} compact />
                      ))}
                    </div>
                  </DialogContent>
                ) : null}
              </Dialog>
            </div>
          </article>
        );
      })}
    </div>
  );
}

export function useImpactRuns() {
  return useLadderRuns();
}
export { useMemo };
