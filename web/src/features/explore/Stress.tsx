import { useMemo, useState } from "react";
import { Ban, CheckCircle2, CircleHelp, Play } from "lucide-react";
import { useSelection } from "@/app/selection";
import { formatWithUnit, shortId, titleCase } from "@/lib/formatting";
import { DataTable } from "@/components/charts/EChart";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Segmented, Eyebrow } from "@/components/ui/primitives";
import { makeScale } from "@/components/map/palette";
import { useScenario } from "@/features/workspace/useScenario";
import { pickNum, useAnalysisRunner, useCurrentAnalysis } from "./analysis";
import { cn } from "@/lib/cn";

interface Cell {
  stateId: string;
  weather: string;
  supply: string;
  deliverable: boolean | null;
  production: number | null;
  yieldKgHa: number | null;
  violations: { rule?: string; entity_ids?: string[]; at?: string; detail?: string }[];
  runId: string | null;
}

function readCells(a: Record<string, unknown> | undefined): Cell[] {
  return ((a?.cells as Record<string, unknown>[] | undefined) ?? []).map((c) => ({
    stateId: String(c.state_id ?? ""),
    weather: String(c.weather_scenario_id ?? c.weather ?? "?"),
    supply: String(c.supply_profile_id ?? c.supply ?? "?"),
    deliverable: typeof c.deliverable === "boolean" ? c.deliverable : null,
    // Undeliverable cells never carry an achievable outcome (AT10).
    production: c.deliverable === false ? null : pickNum(c, "production_kg"),
    yieldKgHa: c.deliverable === false ? null : pickNum(c, "yield_kg_ha", "mean_yield_kg_ha"),
    violations: (c.violations as Cell["violations"]) ?? [],
    runId: (c.run_id as string | undefined) ?? null,
  }));
}

export function Stress() {
  const sel = useSelection();
  const s = useScenario();
  const cur = useCurrentAnalysis("stress");
  const runner = useAnalysisRunner("stress");
  const [mode, setMode] = useState<"fixed_plan" | "recovery">("fixed_plan");
  const [picked, setPicked] = useState<string | null>(null);
  const cells = useMemo(() => readCells(cur.data), [cur.data]);
  const weathers = [...new Set(cells.map((c) => c.weather))];
  const supplies = [...new Set(cells.map((c) => c.supply))];
  const scale = useMemo(() => makeScale("sequential-yield", cells.map((c) => c.production).filter((v): v is number => v !== null)), [cells]);
  const result = (cur.data?.result ?? {}) as Record<string, unknown>;
  const undeliverable = cells.filter((c) => c.deliverable === false).length;
  const pc = cells.find((c) => c.stateId === picked);
  const uset = s.draft?.uncertainty_set_id ?? s.catalog.uncertainty.data?.sets?.[0]?.uncertainty_set_id ?? null;

  return (
    <div className="flex flex-col gap-3" data-testid="stress">
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Stress matrix</h2>
            <p className="mt-0.5 max-w-[64ch] text-[12px] text-ink-secondary">
              The chosen plan under three historical weather analogs × three supply profiles. Each cell first answers “can this plan actually be delivered?”. Worst case means worst
              within these nine tested states — not a probability.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Segmented
              label="Stress mode"
              size="sm"
              value={mode}
              onChange={(v) => setMode(v as typeof mode)}
              options={[
                { value: "fixed_plan", label: "Fixed plan" },
                { value: "recovery", label: "Recovery replanning", title: "Scenario-specific replanning with investments held fixed" },
              ]}
            />
            <Button
              size="sm"
              variant="primary"
              icon={<Play size={13} />}
              busy={runner.pending}
              disabled={!sel.runId || !uset}
              title={!sel.runId ? "Open a run first" : !uset ? "No uncertainty set published" : undefined}
              onClick={() => void runner.run({ run_id: sel.runId, uncertainty_set_id: uset, mode })}
              data-testid="run-stress"
            >
              Evaluate 9 states
            </Button>
          </div>
        </div>
      </section>

      {cur.loading ? (
        <Skeleton className="h-72" />
      ) : cur.error ? (
        <StatePanel state="error" error={cur.error} title="Stress matrix unavailable" />
      ) : !cells.length ? (
        <StatePanel state="empty" title="No stress evaluation yet">
          Evaluate the displayed run across the published uncertainty set{uset ? ` (${uset})` : ""}.
        </StatePanel>
      ) : (
        <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1" aria-labelledby="stress-h">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h3 id="stress-h" className="text-[13px] font-semibold text-ink">
              {titleCase(String(cur.data?.mode ?? mode))} · {cells.length} states
            </h3>
            {undeliverable ? <Chip tone="warning" icon={<Ban size={11} aria-hidden />}>{undeliverable} undeliverable</Chip> : <Chip tone="vegetation">All deliverable</Chip>}
            {pickNum(result, "worst_tested_production_kg") !== null ? (
              <Chip tone="info">
                {undeliverable ? "Conditional minimum over deliverable cells" : "Worst tested"}: {formatWithUnit(pickNum(result, "worst_tested_production_kg")!, "kg")}
              </Chip>
            ) : null}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-separate border-spacing-1.5" aria-label="Stress matrix: weather analogs by supply profiles">
              <thead>
                <tr>
                  <th scope="col" className="text-left text-[11px] font-medium text-ink-tertiary">
                    Weather ↓ · Supply →
                  </th>
                  {supplies.map((sp) => (
                    <th key={sp} scope="col" className="text-left text-[12px] font-semibold text-ink">
                      {titleCase(sp)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weathers.map((w) => (
                  <tr key={w}>
                    <th scope="row" className="pr-2 text-left text-[12px] font-semibold text-ink">
                      {titleCase(w)}
                    </th>
                    {supplies.map((sp) => {
                      const c = cells.find((x) => x.weather === w && x.supply === sp);
                      if (!c) return <td key={sp} className="rounded-[10px] bg-surface-muted p-3 text-[12px] text-ink-tertiary">not evaluated</td>;
                      const ok = c.deliverable;
                      return (
                        <td key={sp} className="p-0">
                          <button
                            type="button"
                            onClick={() => setPicked(c.stateId)}
                            aria-pressed={picked === c.stateId}
                            className={cn(
                              "relative flex h-[92px] w-full flex-col justify-between overflow-hidden rounded-[12px] border p-3 text-left transition-shadow hover:shadow-2",
                              picked === c.stateId ? "border-ink ring-2 ring-ink/20" : "border-border",
                              ok === false && "bg-[repeating-linear-gradient(135deg,var(--warning-soft)_0_8px,var(--surface)_8px_16px)]",
                            )}
                            style={ok ? { background: scale.color(c.production) } : undefined}
                            data-testid="stress-cell"
                            data-deliverable={String(ok)}
                          >
                            <span
                              className={cn(
                                "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-semibold",
                                ok ? "bg-surface/90 text-vegetation" : ok === false ? "bg-surface/90 text-warning" : "bg-surface/90 text-ink-tertiary",
                              )}
                            >
                              {ok ? <CheckCircle2 size={11} aria-hidden /> : ok === false ? <Ban size={11} aria-hidden /> : <CircleHelp size={11} aria-hidden />}
                              {ok ? "Deliverable" : ok === false ? "Not deliverable" : "Unknown"}
                            </span>
                            <span className="num rounded-[6px] bg-surface/85 px-1.5 py-0.5 text-[13px] font-semibold text-ink">
                              {ok && c.production !== null ? formatWithUnit(c.production, "kg") : ok === false ? "No achievable yield" : "—"}
                            </span>
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-tertiary">Deliverability is shown by icon, text and hatch; colour encodes production only for deliverable cells.</p>
          {pc ? (
            <div className="mt-3 rounded-[12px] border border-border bg-surface-muted/60 p-3" data-testid="stress-detail">
              <Eyebrow className="mb-1">
                {titleCase(pc.weather)} × {titleCase(pc.supply)}
              </Eyebrow>
              {pc.deliverable === false ? (
                <>
                  <p className="text-[13px] text-ink">The planned receipts cannot be delivered in this state. The original schedule's yield is not shown as achievable.</p>
                  {pc.violations.length ? (
                    <DataTable
                      dense
                      caption="Violations"
                      columns={[
                        { key: "rule", label: "Rule" },
                        { key: "ent", label: "Receipt / route" },
                        { key: "at", label: "When" },
                        { key: "detail", label: "Detail" },
                      ]}
                      rows={pc.violations.map((v) => ({ rule: titleCase(v.rule ?? "—"), ent: (v.entity_ids ?? []).join(", ") || "—", at: v.at ?? "—", detail: v.detail ?? "—" }))}
                    />
                  ) : null}
                </>
              ) : (
                <p className="num text-[13px] text-ink">
                  Production {pc.production !== null ? formatWithUnit(pc.production, "kg") : "—"}
                  {pc.yieldKgHa !== null ? ` · mean ${formatWithUnit(pc.yieldKgHa, "kg/ha")}` : ""}
                </p>
              )}
              {pc.runId ? (
                <button type="button" className="mt-2 text-[12px] font-medium text-water hover:underline" onClick={() => sel.setParams({ run: pc.runId })}>
                  Open state run {shortId(pc.runId)}
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
