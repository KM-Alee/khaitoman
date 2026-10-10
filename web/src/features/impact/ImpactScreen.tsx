import { useMemo, useState } from "react";
import { Coins, Droplets, FileDown, Globe2, Info, Scale } from "lucide-react";
import { NextStep, PageHeader } from "@/components/ui/PageHeader";
import { Provenance } from "@/components/status";
import { planName } from "@/lib/glossary";
import { usePilotData } from "@/app/pilotData";
import { useMediaQuery } from "@/app/environment";
import {
  useRun,
  useRunAccounting,
  useRunEconomics,
  useRunEquity,
  useRunImpact,
  type RunAccounting,
  type RunEconomics,
  type RunEquity,
} from "@/lib/api/queries";
import type { PlanKind } from "@/lib/api/types";
import { formatDelta, formatMass, formatNumber, formatPKR, formatPercent, formatVolume, shortId, titleCase } from "@/lib/formatting";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, MetricValueView, Skeleton, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/primitives";
import { SubTabs } from "@/features/compare/CompareTabs";
import { useLadderRuns } from "@/features/compare/useLadder";
import { cn } from "@/lib/cn";
import { SdgCards } from "./SdgCards";
import { BudgetMeter, Panel, Rows, StatusReasonView, ViewGate, isStatusReason, useFieldLabel } from "./viewKit";

const TABS = [
  { value: "water", label: "Water", hint: "Water accounting: where every cubic metre goes", icon: <Droplets size={15} /> },
  { value: "economics", label: "Money", hint: "Economics: costs, budgets and payback", icon: <Coins size={15} /> },
  { value: "equity", label: "Fairness", hint: "Equity: who receives their fair share, who is worse off", icon: <Scale size={15} /> },
  { value: "sdg", label: "Global goals", hint: "SDG proxies (2.4, 6.4/6.5, 13.1)", icon: <Globe2 size={15} /> },
];

const TAB_COPY: Record<string, { title: string; lead: string }> = {
  water: { title: "Where does the water go?", lead: "From the canal head to the crop: withdrawals, losses on the way, ponds, pumping and what reaches each field, on one accounting boundary at a time." },
  economics: { title: "What does it cost, and is it worth it?", lead: "One-time works and this season's running costs against the budgets you set. Missing prices stay missing; nothing is filled in." },
  equity: { title: "Who benefits, and is anyone left behind?", lead: "Each field's fair share of water and change in harvest, from head-end to tail-end, with every field that ends up worse off named." },
  sdg: { title: "How does this relate to the global goals?", lead: "Three planning indicators linked to UN goals for food (2.4), water (6.4/6.5) and climate resilience (13.1). They are project proxies, not official scores." },
};

export function ImpactNav() {
  const { sel } = usePilotData();
  return (
    <nav aria-label="Impact views" className="no-print flex h-14 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3 md:px-6">
      {[
        { s: "impact" as const, l: "Costs & benefits" },
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
            "relative inline-flex h-9 shrink-0 items-center rounded-[10px] px-3.5 text-[13.5px] font-medium transition-[background-color,color,box-shadow] duration-150",
            sel.screen === t.s ? "bg-surface text-ink shadow-2 ring-1 ring-border" : "text-ink-secondary hover:bg-surface-muted hover:text-ink",
          )}
        >
          {t.l}
        </a>
      ))}
    </nav>
  );
}

/** Baseline options for comparisons: B0/B1 runs of the ladder other than the current run. */
function useBaselines(runId: string | null) {
  const { byKind } = useLadderRuns();
  return useMemo(
    () =>
      (["B0", "B1"] as PlanKind[])
        .map((k) => ({ kind: k, id: byKind.get(k)?.run_id ?? null }))
        .filter((b): b is { kind: PlanKind; id: string } => !!b.id && b.id !== runId),
    [byKind, runId],
  );
}

export function ImpactScreen() {
  const { sel } = usePilotData();
  const run = useRun(sel.runId);
  const tab = TABS.some((t) => t.value === sel.tab) ? sel.tab! : "water";
  const baselines = useBaselines(sel.runId);
  const [baseKind, setBaseKind] = useState<PlanKind | "none">("B0");
  const baseline = baselines.find((b) => b.kind === baseKind) ?? (baseKind === "none" ? null : baselines[0] ?? null);
  const baselinePicker = baselines.length ? (
    <Segmented
      label="Baseline for comparison"
      size="sm"
      value={baseline ? baseline.kind : "none"}
      onChange={(v) => setBaseKind(v as PlanKind | "none")}
      options={[...baselines.map((b) => ({ value: b.kind as string, label: `vs ${b.kind}`, title: b.id })), { value: "none", label: "No baseline" }]}
    />
  ) : null;
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="impact">
      <ImpactNav />
      <SubTabs label="Impact sections" tabs={TABS} value={tab} onChange={(v) => sel.setParams({ tab: v })} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-5 p-4 md:p-8">
          <PageHeader
            compact
            title={TAB_COPY[tab].title}
            lead={TAB_COPY[tab].lead}
            meta={run.data ? <Provenance run={run.data} /> : null}
            actions={
              sel.runId ? (
                <>
                  {tab === "equity" || tab === "sdg" ? baselinePicker : null}
                  <Button variant="secondary" icon={<FileDown size={15} />} onClick={() => sel.go("report")}>
                    Action plan & report
                  </Button>
                </>
              ) : null
            }
          />
          {!sel.runId ? (
            <div className="max-w-[620px]" data-testid="impact-empty">
              <StatePanel state="empty" art="chart" title="Impact needs a plan" action={{ label: "Go to Plan", onClick: () => sel.go("workspace") }}>
                Water accounts, money, fairness and global-goal indicators are computed by the server for a completed plan. Find a plan first, or open a shared link.
              </StatePanel>
            </div>
          ) : run.isLoading ? (
            <div className="grid gap-3 md:grid-cols-2" aria-busy="true" role="status" aria-label="Impact loading" data-testid="impact-loading">
              <Skeleton className="h-72" />
              <Skeleton className="h-72" />
            </div>
          ) : run.error || !run.data ? (
            <div data-testid="impact-error">
              <StatePanel state="error" error={run.error} title="Run unavailable" />
            </div>
          ) : run.data.outcome !== "plan" ? (
            <div data-testid="impact-infeasible">
              <StatePanel state={run.data.solver_status === "INFEASIBLE" ? "infeasible" : "unknown"} title={`No plan (${run.data.solver_status})`}>
                Costs and benefits exist only for runs with a validated plan. Go back to Plan and loosen a rule or raise a budget.
              </StatePanel>
            </div>
          ) : (
            <div className="animate-rise" key={tab}>
              <p className="mb-3 flex items-center gap-1.5 text-[12px] text-ink-tertiary">
                <Info size={13} aria-hidden /> Showing {planName(run.data.plan_kind).toLowerCase()} ({run.data.plan_kind} · run {shortId(run.data.run_id)}). Every number is returned by the server for this run; nothing is re-derived in the browser.
              </p>
              {tab === "water" ? <WaterTab runId={run.data.run_id} /> : null}
              {tab === "economics" ? <EconomicsTab runId={run.data.run_id} /> : null}
              {tab === "equity" ? <EquityTab runId={run.data.run_id} baseline={baseline} /> : null}
              {tab === "sdg" ? <SdgTab runId={run.data.run_id} baseline={baseline} /> : null}
            </div>
          )}
          <NextStep />
        </div>
      </div>
    </div>
  );
}

/* ================================================================ water accounting */
const NODE_LABEL: Record<string, string> = {
  canal_source: "Canal source withdrawal",
  conveyance_loss: "Conveyance loss",
  outlet_receipt: "Outlet receipt",
  pond_storage: "Pond storage",
  pond_rain: "Rain on ponds",
  pond_losses: "Pond evaporation, seepage & spill",
  direct_field_application: "Direct field application",
  field_application_from_pond: "Field application from pond",
  field_application_from_pump: "Field application from pump",
  groundwater: "Groundwater abstraction",
};
const nodeLabel = (n: string) => NODE_LABEL[n] ?? titleCase(n);
const boundaryLabel = (k: string) => titleCase(k.replace(/_m3$/, "")).replace(/\bPond\b/, "Pond");

function WaterTab({ runId }: { runId: string }) {
  const q = useRunAccounting(runId);
  return <ViewGate q={q} title="Water accounting">{(d) => <Water d={d} />}</ViewGate>;
}

function Water({ d }: { d: RunAccounting }) {
  const t = chartTokens();
  const { sel } = usePilotData();
  const label = useFieldLabel();
  const flows = d.flows.filter((f) => Number.isFinite(f.m3));
  const drawn = flows.filter((f) => f.m3 > 0);
  const nodes = [...new Set(drawn.flatMap((f) => [f.from, f.to]))];
  const colour = (n: string) =>
    /loss/.test(n) ? t.danger : /groundwater|pump/.test(n) ? t.warning : /rain/.test(n) ? t.series[3] : /pond/.test(n) ? t.waterDeep : /application/.test(n) ? t.veg : t.water;
  const option = useMemo(
    () => ({
      ...baseOption(),
      tooltip: {
        trigger: "item",
        backgroundColor: t.surface,
        borderColor: t.border,
        textStyle: { color: t.ink, fontSize: 12 },
        confine: true,
        formatter: (p: { dataType: string; data: { source?: string; target?: string; value?: number; name?: string }; value: number }) =>
          p.dataType === "edge" ? `${p.data.source} → ${p.data.target}<br/><b>${formatVolume(p.data.value ?? 0)}</b>` : `${p.data.name}<br/><b>${formatVolume(p.value)}</b>`,
      },
      series: [
        {
          type: "sankey",
          left: 150,
          right: 210,
          top: 28,
          bottom: 12,
          nodeGap: 30,
          nodeWidth: 12,
          draggable: false,
          layoutIterations: 64,
          emphasis: { focus: "adjacency" },
          label: {
            color: t.ink,
            fontSize: 12,
            fontFamily: t.font,
            formatter: (p: { name: string; value: number }) => `${p.name}\n{v|${formatNumber(p.value, 0)} m³}`,
            lineHeight: 15,
            rich: { v: { color: t.ink3, fontSize: 11, fontFamily: t.font } },
          },
          lineStyle: { color: "gradient", opacity: 0.32, curveness: 0.5 },
          data: nodes.map((n) => ({
            name: nodeLabel(n),
            itemStyle: { color: colour(n), borderWidth: 0 },
            // Sources label on the left, sinks on the right, pass-through nodes above, so no label sits on a flow band.
            label: { position: !drawn.some((f) => f.to === n) ? "left" : !drawn.some((f) => f.from === n) ? "right" : "top" },
          })),
          links: drawn.map((f) => ({ source: nodeLabel(f.from), target: nodeLabel(f.to), value: f.m3 })),
        },
      ],
    }),
    [drawn, nodes, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const b = d.boundaries;
  const appTotal = flows.filter((f) => /application/.test(f.to)).reduce((s, f) => s + f.m3, 0);
  const fieldIds = Object.keys(d.per_field);
  const cols = ["outlet_receipt", "pond_fill", "pond_release", "pump_abstraction", "field_application"].filter((c) => fieldIds.some((f) => d.per_field[f][c] !== undefined));
  const residual = d.reconciliation?.source_minus_loss_minus_receipt_m3;
  // A Sankey with ten labelled nodes cannot be read at phone width; open on its table twin there.
  const narrow = useMediaQuery("(max-width: 640px)");
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
        <ChartPanel
          id="water-sankey"
          defaultView={narrow ? "table" : "chart"}
          key={narrow ? "n" : "w"}
          title="Seasonal water ledger"
          summary="Flows exactly as returned by the accounting endpoint: canal source → conveyance loss or outlet receipt → direct application or pond storage; groundwater and pond rainfall enter explicitly."
          chart={
            drawn.length ? (
              <EChart option={option} height={420} ariaLabel="Sankey of seasonal water flows; the table view lists every flow" />
            ) : (
              <p className="p-4 text-[13px] text-ink-secondary">All flows are zero for this run.</p>
            )
          }
          table={
            <DataTable
              caption="Water flows"
              columns={[
                { key: "f", label: "From" },
                { key: "t", label: "To" },
                { key: "v", label: "Seasonal volume", align: "right" },
              ]}
              rows={flows.map((f) => ({ f: nodeLabel(f.from), t: nodeLabel(f.to), v: formatVolume(f.m3) }))}
            />
          }
        />
        <Panel title="Boundary totals">
          <Rows
            rows={Object.entries(b).map(([k, v]) => [
              boundaryLabel(k),
              typeof v === "number" ? <span className="num">{formatNumber(v, 0)} m³</span> : <span className="text-ink-tertiary">Not reported</span>,
            ])}
          />
        </Panel>
      </div>
      <div className="grid gap-3 xl:grid-cols-[minmax(320px,1fr)_minmax(0,1.6fr)]">
        <Panel title="Reconciliation">
          <Rows
            rows={[
              ["Source − conveyance loss − outlet receipt", typeof residual === "number" ? `${formatNumber(Math.abs(residual) < 1e-6 ? 0 : residual, 3)} m³` : "Not reported"],
              ["Sum of field-application flows (chart)", `${formatNumber(appTotal, 0)} m³`],
              ["Gross field application (boundary)", typeof b.gross_field_application_m3 === "number" ? `${formatNumber(b.gross_field_application_m3, 0)} m³` : "Not reported"],
              ...(typeof b.pond_net_storage_change_m3 === "number" && b.pond_net_storage_change_m3 !== 0
                ? ([["Pond net storage change", `${formatNumber(b.pond_net_storage_change_m3, 0)} m³`]] as [string, string][])
                : []),
            ]}
          />
          {d.reconciliation?.note ? (
            <p className="mt-3 flex gap-1.5 text-[12px] leading-snug text-ink-secondary">
              <Info size={13} className="mt-0.5 shrink-0" aria-hidden />
              {d.reconciliation.note}
            </p>
          ) : null}
          {typeof b.pond_net_storage_change_m3 === "number" && b.pond_net_storage_change_m3 < 0 ? (
            <p className="mt-2 text-[12px] leading-snug text-ink-secondary">Pond outflows exceed inflows by the storage drawdown (initial inventory released), so the pond node is not flow-balanced within the season.</p>
          ) : null}
          <div className="mt-3 border-t border-border pt-3">
            <div className="text-[12px] text-ink-secondary">Basin-wide water savings</div>
            <StatusReasonView v={d.basin_savings} className="mt-1" />
          </div>
        </Panel>
        <Panel title={`Per-field ledger · m³ (${fieldIds.length} fields)`} aside={sel.fieldId ? <Chip size="sm" tone="water">Selected {label(sel.fieldId)}</Chip> : null}>
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full min-w-[520px] border-collapse text-[12px]">
              <caption className="sr-only">Per-field seasonal volumes in cubic metres; select a row to select the field</caption>
              <thead className="sticky top-0 z-[1] bg-surface">
                <tr className="border-b border-border text-ink-tertiary">
                  <th scope="col" className="pb-1.5 pt-1 text-left font-medium">Field</th>
                  {cols.map((c) => (
                    <th key={c} scope="col" className="pb-1.5 pt-1 text-right font-medium">
                      {titleCase(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fieldIds.map((f) => {
                  const on = sel.fieldId === f;
                  return (
                    <tr
                      key={f}
                      aria-selected={on}
                      onClick={() => sel.setParams({ field: on ? null : f }, true)}
                      className={cn("cursor-pointer border-b border-border/70 last:border-0 hover:bg-surface-muted/70", on && "bg-water/10")}
                    >
                      <th scope="row" className="whitespace-nowrap py-1.5 pr-2 text-left font-medium text-ink">
                        <button
                          type="button"
                          className="rounded-[4px] text-left focus-visible:outline-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            sel.setParams({ field: on ? null : f }, true);
                          }}
                        >
                          {label(f)}
                        </button>
                      </th>
                      {cols.map((c) => (
                        <td key={c} className="num py-1.5 text-right text-ink">
                          {typeof d.per_field[f][c] === "number" ? formatNumber(d.per_field[f][c], 0) : <span className="text-ink-tertiary">—</span>}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-tertiary">— means the field had no event of that type in the ledger. Withdrawals reduced are not consumptive water savings.</p>
        </Panel>
      </div>
    </div>
  );
}

/* ================================================================ economics */
function EconomicsTab({ runId }: { runId: string }) {
  const q = useRunEconomics(runId);
  return <ViewGate q={q} title="Economics">{(d) => <Economics d={d} />}</ViewGate>;
}

const pkr = (v: number | null | undefined) => (typeof v === "number" ? formatPKR(v) : "Not reported");

function Economics({ d }: { d: RunEconomics }) {
  const t = chartTokens();
  const label = useFieldLabel();
  const grant = d.public_grant_pkr;
  const pumping = [...d.pumping].sort((a, b) => b.seasonal_opex_pkr - a.seasonal_opex_pkr);
  const pumpOption = useMemo(
    () => ({
      ...baseOption(),
      grid: { left: 64, right: 24, top: 8, bottom: 40 },
      tooltip: { ...(baseOption().tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { ...(baseOption().xAxis as object), type: "value", name: "PKR per season", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.ink3, fontSize: 11 }, axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatNumber(v, 0) }, splitLine: { show: true, lineStyle: { color: t.border, opacity: 0.6 } } },
      yAxis: { ...(baseOption().yAxis as object), type: "category", inverse: true, data: pumping.map((p) => label(p.field_id)), axisLabel: { color: t.ink2, fontSize: 12 } },
      series: [
        {
          type: "bar",
          name: "Seasonal pumping cost",
          data: pumping.map((p) => p.seasonal_opex_pkr),
          itemStyle: { color: t.warning, borderRadius: [0, 4, 4, 0] },
          barMaxWidth: 16,
          tooltip: { valueFormatter: (v: number) => formatPKR(v) },
        },
      ],
    }),
    [pumping, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const cats = [...new Set(d.instances.map((i) => i.category))];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Gross project cost" value={pkr(d.gross_project_cost_pkr)} sub={`Capital budget ${pkr(d.capital_budget_pkr)}`}>
          {typeof d.gross_project_cost_pkr === "number" && typeof d.capital_budget_pkr === "number" ? (
            <BudgetMeter used={d.gross_project_cost_pkr} budget={d.capital_budget_pkr} label="Gross project cost as share of capital budget" />
          ) : null}
        </Kpi>
        <Kpi label="Participant cash" value={pkr(d.participant_cash_pkr)} sub="Gross cost less verified grants only" />
        <Kpi label="Public grant (verified only)" value={typeof grant === "number" ? formatPKR(grant) : null}>
          {isStatusReason(grant) ? <StatusReasonView v={grant} className="mt-1" /> : grant === null ? <StatusReasonView v={null} /> : null}
        </Kpi>
        <Kpi label="Seasonal operating" value={pkr(d.seasonal_operating_pkr)} sub={`Operating budget ${pkr(d.operating_budget_pkr)}`}>
          {typeof d.seasonal_operating_pkr === "number" && typeof d.operating_budget_pkr === "number" ? (
            <BudgetMeter used={d.seasonal_operating_pkr} budget={d.operating_budget_pkr} label="Seasonal operating cost as share of operating budget" />
          ) : null}
        </Kpi>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Panel title={`Selected interventions (${d.instances.length})`} aside={<span className="text-[11px] text-ink-tertiary">{cats.map(titleCase).join(" · ")}</span>}>
          {d.instances.length ? (
            <div className="max-h-[380px] overflow-auto">
              <DataTable
                caption="Selected intervention instances"
                dense
                columns={[
                  { key: "i", label: "Instance" },
                  { key: "c", label: "Category" },
                  { key: "cap", label: "Capital", align: "right" },
                  { key: "op", label: "Seasonal opex", align: "right" },
                  { key: "s", label: "Shared", className: "pl-5" },
                  { key: "ch", label: "Charged", className: "pl-3" },
                ]}
                rows={d.instances.map((i) => {
                  const [, fld] = i.instance_id.match(/^(.*):[^:]+$/) ?? [];
                  return {
                    i: (
                      <span title={i.instance_id}>
                        {fld ? label(fld) : i.instance_id}
                        <span className="ml-1 font-mono text-[10px] text-ink-tertiary">{i.instance_id.split(":").pop()}</span>
                      </span>
                    ),
                    c: titleCase(i.category),
                    cap: formatPKR(i.capex_pkr),
                    op: formatPKR(i.seasonal_opex_pkr),
                    s: i.shared ? "Shared" : "No",
                    ch: titleCase(i.charged),
                  };
                })}
              />
            </div>
          ) : (
            <p className="text-[13px] text-ink-secondary">No capital interventions selected in this run.</p>
          )}
        </Panel>
        <ChartPanel
          id="econ-pumping"
          title="Seasonal pumping cost by field"
          summary="Operating cost of groundwater top-up per field, with the pumped volume in the table."
          chart={
            pumping.length ? (
              <EChart option={pumpOption} height={Math.max(170, pumping.length * 30 + 56)} ariaLabel="Bar chart of seasonal pumping cost per field" />
            ) : (
              <p className="p-4 text-[13px] text-ink-secondary">No pumping in this run.</p>
            )
          }
          table={
            <DataTable
              caption="Pumping by field"
              columns={[
                { key: "f", label: "Field" },
                { key: "v", label: "Pumped", align: "right" },
                { key: "c", label: "Seasonal cost", align: "right" },
              ]}
              rows={pumping.map((p) => ({ f: label(p.field_id), v: formatVolume(p.pump_volume_m3), c: formatPKR(p.seasonal_opex_pkr) }))}
            />
          }
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title="Crop value & contribution">
          <Rows
            rows={[
              ["Crop value", <MetricValueView key="cv" metric={d.crop_value} size="sm" />],
              ["Irrigation contribution", <MetricValueView key="ic" metric={d.irrigation_contribution} size="sm" />],
            ]}
          />
          <p className="mt-2 text-[11px] text-ink-tertiary">Revenue figures appear only with a dated crop price record; they never default to zero.</p>
        </Panel>
        <Panel title="Cost sensitivity">
          <DataTable
            caption="Budget sensitivity"
            dense
            columns={[
              { key: "c", label: "Case" },
              { key: "v", label: "Amount", align: "right" },
              { key: "b", label: "Within budget", align: "right" },
            ]}
            rows={d.sensitivity.map((s) => ({
              c: s.case,
              v: pkr(s.gross_capital_pkr ?? s.operating_pkr),
              b: s.within_budget ? "Yes" : <span className="font-medium text-danger">No</span>,
            }))}
          />
          {d.sensitivity_note ? <p className="mt-2 text-[12px] leading-snug text-ink-secondary">{d.sensitivity_note}</p> : null}
        </Panel>
        <Panel title="Multi-year cashflow">
          {isStatusReason(d.cashflow) ? <StatusReasonView v={d.cashflow} /> : d.cashflow ? <pre className="overflow-auto text-[11px]">{JSON.stringify(d.cashflow, null, 2)}</pre> : <StatusReasonView v={null} />}
          <p className="mt-3 text-[11px] text-ink-tertiary">No payback, NPV or IRR is shown without a documented asset life, crop price and discount rate.</p>
        </Panel>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, children }: { label: string; value: string | null; sub?: string; children?: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[18px] border border-border bg-surface p-4 shadow-1">
      <div className="text-[12px] text-ink-secondary">{label}</div>
      {value ? <div className="num mt-1 text-[22px] font-semibold tracking-[-0.01em] text-ink">{value}</div> : null}
      {sub ? <div className="num mt-0.5 text-[12px] text-ink-tertiary">{sub}</div> : null}
      {children}
    </section>
  );
}

/* ================================================================ equity */
const GROUPS = ["head", "middle", "tail"] as const;

function EquityTab({ runId, baseline }: { runId: string; baseline: { kind: PlanKind; id: string } | null }) {
  const q = useRunEquity(runId, baseline?.id);
  return <ViewGate q={q} title="Equity">{(d) => <Equity d={d} baselineKind={baseline?.kind ?? null} />}</ViewGate>;
}

function Equity({ d, baselineKind }: { d: RunEquity; baselineKind: PlanKind | null }) {
  const t = chartTokens();
  const { sel } = usePilotData();
  const label = useFieldLabel();
  const groupColour: Record<string, string> = { head: t.series[0], middle: t.series[3], tail: t.series[1] };
  const eligible = d.fields.filter((f) => typeof f.service_ratio === "number").sort((a, b) => a.service_ratio! - b.service_ratio!);
  const hasDelta = !!d.baseline_run_id && d.fields.some((f) => typeof f.production_delta_kg === "number");
  const cats = eligible.map((f) => label(f.field_id));
  const max = Math.max(1, ...eligible.map((f) => f.service_ratio!));
  const option = useMemo(
    () => ({
      ...baseOption(),
      legend: { top: 0, left: 50, itemWidth: 10, itemHeight: 10, textStyle: { color: t.ink2, fontSize: 12 }, data: GROUPS.map(titleCase) },
      grid: { left: 56, right: 28, top: 40, bottom: 32 },
      tooltip: {
        ...(baseOption().tooltip as object),
        trigger: "item",
        formatter: (p: { name: string; seriesName: string; value: number }) => `${p.name} · ${p.seriesName}<br/><b>${formatPercent(p.value, 1)}</b> of reference allowance`,
      },
      xAxis: {
        ...(baseOption().xAxis as object),
        type: "value",
        min: 0,
        max: Math.ceil(max * 10) / 10,
        name: d.measure_label,
        nameLocation: "middle",
        nameGap: 22,
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => formatPercent(v) },
        splitLine: { show: true, lineStyle: { color: t.border, opacity: 0.6 } },
      },
      yAxis: { ...(baseOption().yAxis as object), type: "category", inverse: true, data: cats, axisLabel: { color: t.ink2, fontSize: 11 }, splitLine: { show: false } },
      series: GROUPS.map((g, gi) => ({
        type: "bar",
        name: titleCase(g),
        barGap: "-100%",
        barMaxWidth: 12,
        data: eligible.map((f) => ({ value: f.group === g ? f.service_ratio : null, fid: f.field_id, itemStyle: { opacity: sel.fieldId && sel.fieldId !== f.field_id ? 0.45 : 1 } })),
        itemStyle: { color: groupColour[g], borderRadius: [0, 3, 3, 0] },
        ...(gi === 0
          ? {
              markLine: {
                silent: true,
                symbol: "none",
                lineStyle: { color: t.ink3, type: "dashed" },
                label: { show: false },
                data: [{ xAxis: 1 }],
              },
            }
          : {}),
      })),
    }),
    [eligible, cats, sel.fieldId, t, d.measure_label, max], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const burden = Object.entries(d.pumping_burden_share)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
  const worse = d.fields_worse_off.map((w) => (typeof w === "string" ? w : w.field_id));
  const fieldClick = useMemo(
    () => ({
      click: (p: unknown) => {
        const f = (p as { data?: { fid?: string } }).data?.fid;
        if (f) sel.setParams({ field: f }, true);
      },
    }),
    [sel],
  );
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[18px] border border-border bg-surface px-4 py-2.5 text-[12px] shadow-1">
        <span>
          <span className="text-ink-secondary">Measure </span>
          <span className="font-medium text-ink">{d.measure_label}</span>
        </span>
        <span>
          <span className="text-ink-secondary">Aggregation </span>
          <span className="font-medium text-ink">{d.aggregation}</span>
        </span>
        <span>
          <span className="text-ink-secondary">Minimum service </span>
          <span className="num font-medium text-ink">{typeof d.min_service_ratio === "number" ? formatPercent(d.min_service_ratio, 1) : "Not reported"}</span>
        </span>
        <span>
          <span className="text-ink-secondary">Baseline </span>
          <span className="font-medium text-ink">{d.baseline_run_id ? `${baselineKind ?? ""} · ${shortId(d.baseline_run_id)}` : "none selected"}</span>
        </span>
        {d.comparison ? (
          <Chip size="sm" tone={d.comparison.compatible ? "water" : "warning"} title={(d.comparison.differences ?? []).map((x) => `${x.condition}: ${x.note ?? ""}`).join("; ")}>
            {d.comparison.label ?? (d.comparison.compatible ? "compatible comparison" : "incompatible comparison")}
          </Chip>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {GROUPS.map((g) => {
          const s = d.groups[g];
          return (
            <section key={g} className="min-w-0 rounded-[18px] border border-border bg-surface p-4 shadow-1">
              <div className="flex items-center gap-2 text-[12px] font-medium text-ink-secondary">
                <span className="inline-block size-2.5 rounded-[3px]" style={{ background: groupColour[g] }} aria-hidden />
                {titleCase(g)} fields
                <span className="num ml-auto text-ink-tertiary">{s ? `${s.eligible} of ${s.fields} eligible` : ""}</span>
              </div>
              {s ? (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <div className="text-[11px] text-ink-tertiary">Mean service</div>
                    <div className="num text-[20px] font-semibold text-ink">{typeof s.mean_service_ratio === "number" ? formatPercent(s.mean_service_ratio, 1) : "—"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-ink-tertiary">Minimum service</div>
                    <div className="num text-[20px] font-semibold text-ink">{typeof s.min_service_ratio === "number" ? formatPercent(s.min_service_ratio, 1) : "—"}</div>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-[12px] text-ink-tertiary">Group not reported.</p>
              )}
            </section>
          );
        })}
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,1fr)]">
        <ChartPanel
          id="equity-chart"
          title="Service ratio per field, lowest first"
          summary={`Field canal receipt ÷ fixed reference allowance (${d.measure_label}; not a legal quota). Colour marks the head / middle / tail group; the dashed line is the full reference allowance. Click a bar to select the field.`}
          chart={
            eligible.length ? (
              <EChart option={option} height={Math.max(240, eligible.length * 17 + 80)} ariaLabel="Horizontal bar chart of field service ratios sorted ascending, coloured by canal position" onEvents={fieldClick} />
            ) : (
              <p className="p-4 text-[13px] text-ink-secondary">No eligible fields with a service ratio.</p>
            )
          }
          table={
            <DataTable
              caption="Field equity"
              dense
              columns={[
                { key: "f", label: "Field" },
                { key: "g", label: "Group" },
                { key: "s", label: "Service", align: "right" },
                { key: "p", label: "Production", align: "right" },
                ...(hasDelta ? [{ key: "dp", label: `Δ vs ${baselineKind ?? "baseline"}`, align: "right" as const }] : []),
                { key: "gw", label: "Groundwater", align: "right" },
              ]}
              rows={[...d.fields]
                .sort((a, b) => (a.service_ratio ?? 9) - (b.service_ratio ?? 9))
                .map((f) => ({
                  f: label(f.field_id),
                  g: f.group ? titleCase(f.group) : "—",
                  s: typeof f.service_ratio === "number" ? formatPercent(f.service_ratio, 1) : titleCase(String(f.service_status)),
                  p: typeof f.production_kg === "number" ? formatMass(f.production_kg) : "—",
                  dp: typeof f.production_delta_kg === "number" ? formatDelta(f.production_delta_kg, "kg") : "—",
                  gw: typeof f.groundwater_m3 === "number" ? formatVolume(f.groundwater_m3) : "—",
                }))}
            />
          }
        />
        <div className="flex min-w-0 flex-col gap-3">
          <Panel title="Fields worse off vs baseline">
            {!d.baseline_run_id ? (
              <p className="text-[12px] text-ink-secondary">Select a B0 or B1 baseline above to list fields whose production falls.</p>
            ) : (
              <>
                <div className="num text-[22px] font-semibold text-ink">{d.fields_worse_off_count ?? worse.length}</div>
                <p className="text-[12px] text-ink-secondary">
                  {worse.length ? worse.map(label).join(", ") : `No field produces less than under ${baselineKind ?? "the baseline"}.`}
                </p>
              </>
            )}
            {hasDelta ? (
              <ProductionDelta fields={d.fields} label={label} />
            ) : null}
          </Panel>
          <Panel title="Pumping burden share">
            {burden.length ? (
              <ul className="flex flex-col gap-1.5">
                {burden.map(([f, v]) => (
                  <li key={f} className="grid grid-cols-[52px_minmax(0,1fr)_48px] items-center gap-2 text-[12px]">
                    <span className="font-medium text-ink">{label(f)}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-surface-muted">
                      <span className="block h-full rounded-full bg-warning" style={{ width: `${(v / burden[0][1]) * 100}%` }} />
                    </span>
                    <span className="num text-right text-ink">{formatPercent(v, 1)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-ink-secondary">No field pumps groundwater in this run.</p>
            )}
            <p className="mt-2 text-[11px] text-ink-tertiary">Share of total groundwater abstraction; {Object.keys(d.pumping_burden_share).length - burden.length} fields pump none.</p>
          </Panel>
          <Panel title="Exclusions & ownership">
            <div className="text-[12px] text-ink-secondary">Zero-reference fields (excluded from service ratios)</div>
            <p className="mt-0.5 text-[13px] text-ink">{d.zero_reference_fields.length ? d.zero_reference_fields.map(label).join(", ") : "None"}</p>
            {d.owner_note ? <p className="mt-2 text-[12px] leading-snug text-ink-secondary">{d.owner_note}</p> : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function ProductionDelta({ fields, label }: { fields: RunEquity["fields"]; label: (id: string) => string }) {
  const ds = fields.filter((f) => typeof f.production_delta_kg === "number").map((f) => f.production_delta_kg!);
  if (!ds.length) return null;
  const gain = ds.filter((v) => v > 0).length;
  const loss = ds.filter((v) => v < 0).length;
  const minF = fields.reduce((m, f) => (typeof f.production_delta_kg === "number" && (m === null || f.production_delta_kg < m.production_delta_kg!) ? f : m), null as RunEquity["fields"][number] | null);
  return (
    <div className="mt-3 border-t border-border pt-2">
      <Rows
        rows={[
          ["Fields with higher production", String(gain)],
          ["Fields with lower production", String(loss)],
          ["Smallest change", minF ? `${label(minF.field_id)} · ${formatDelta(minF.production_delta_kg!, "kg")}` : "—"],
        ]}
      />
    </div>
  );
}

/* ================================================================ SDG proxies */
function SdgTab({ runId, baseline }: { runId: string; baseline: { kind: PlanKind; id: string } | null }) {
  const q = useRunImpact(runId, baseline?.id);
  return (
    <ViewGate q={q} title="SDG proxies" testId="sdg">
      {(d) => <SdgCards impact={d} />}
    </ViewGate>
  );
}

export function useImpactRuns() {
  return useLadderRuns();
}
