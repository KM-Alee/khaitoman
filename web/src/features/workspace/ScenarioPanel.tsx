/**
 * Plan settings (PRD §4.2 default view): season, water, money and fairness as plain
 * questions; everything else behind "Planning assumptions". Editing creates a draft;
 * "Find the best plan" creates an immutable revision and solves B0, B1 and P on it.
 */
import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, CloudSun, Coins, Hammer, PanelLeftClose, RotateCcw, Scale, Sparkles, Sprout } from "lucide-react";
import { defaultDecisionAt, useScenario } from "./useScenario";
import { useRevision } from "@/lib/api/queries";
import type { ActionCategory, InterventionInstance } from "@/lib/api/types";
import { formatDate, formatPKR, formatPKRCompact, formatPercent, titleCase } from "@/lib/formatting";
import { parsePKR, fractionToPercent, percentToFraction } from "@/lib/units";
import { GROUP_LABEL, PLANNING_MODE_LABEL } from "@/lib/glossary";
import { Button, IconButton } from "@/components/ui/Button";
import { Segmented, Select, SliderField, Switch } from "@/components/ui/primitives";
import { TermHint } from "@/components/ui/Term";
import { Chip, StatePanel, Skeleton } from "@/components/status";
import { cn } from "@/lib/cn";
import { CATEGORY_META } from "./categories";

export { CATEGORY_META };

function Group({ icon, title, children, tour }: { icon: React.ReactNode; title: React.ReactNode; children: React.ReactNode; tour?: string }) {
  return (
    <fieldset className="flex flex-col gap-3.5" data-tour={tour}>
      <legend className="mb-1 flex items-center gap-2 text-[13.5px] font-semibold text-ink">
        <span className="grid h-6 w-6 place-items-center rounded-[8px] bg-water-soft text-water-deep" aria-hidden>
          {icon}
        </span>
        {title}
      </legend>
      {children}
    </fieldset>
  );
}

export function ScenarioPanel({ onCollapse, className }: { onCollapse?: () => void; className?: string }) {
  const s = useScenario();
  const { draft, catalog } = s;
  const revision = useRevision(s.active?.revisionId);
  const [advanced, setAdvanced] = useState(false);
  const seasons = catalog.seasons.data ?? [];
  const season = seasons.find((x) => x.season_id === draft?.season_id);
  const weather = catalog.weather.data ?? [];
  const supply = catalog.uncertainty.data?.supplyProfiles ?? [];
  const supplyIds = useMemo(() => {
    const ids = new Set(supply.map((p) => p.supply_profile_id));
    for (const st of catalog.uncertainty.data?.sets?.flatMap((x) => x.states) ?? []) ids.add(st.supply_profile_id);
    return [...ids];
  }, [supply, catalog.uncertainty.data]);
  const readiness = revision.data?.readiness ?? undefined;

  return (
    <aside aria-label="Plan settings" className={cn("flex h-full min-h-0 flex-col border-r border-border bg-surface", className)} data-testid="scenario-panel" data-tour="settings">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-5">
        <div className="flex items-center gap-2">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Plan settings</h2>
          <PhaseChip phase={s.phase} />
        </div>
        {onCollapse ? (
          <IconButton label="Hide plan settings" size="sm" onClick={onCollapse}>
            <PanelLeftClose size={16} />
          </IconButton>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {catalog.seasons.error ? (
          <StatePanel compact state="error" error={catalog.seasons.error} title="Season list unavailable">
            The API could not list crop seasons for this pilot. Settings stay disabled until it does.
          </StatePanel>
        ) : !draft ? (
          catalog.seasons.data && !catalog.seasons.data.length ? (
            <StatePanel compact state="empty" title="No crop season configured">
              This pilot version has no published crop season yet, so no plan can be run.
            </StatePanel>
          ) : (
            <div className="flex flex-col gap-4" aria-busy>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          )
        ) : (
          <div className="flex flex-col gap-7">
            <Group icon={<Sprout size={14} />} title="Which season?" tour="settings-season">
              <Select
                label="Crop and season"
                value={draft.season_id}
                onChange={(e) => {
                  const ns = seasons.find((x) => x.season_id === e.target.value);
                  if (!ns) return;
                  s.patch({
                    season_id: ns.season_id,
                    planning_mode: (ns.planning_modes[0] as typeof draft.planning_mode) ?? draft.planning_mode,
                    decision_at: defaultDecisionAt(ns),
                    weather_scenario_ids: [],
                  });
                }}
              >
                {seasons.map((x) => (
                  <option key={x.season_id} value={x.season_id}>
                    {titleCase(x.crop)} · {(x.label ?? x.season_id).replace(/\s*\(.*\)$/, "")}
                    {x.library_ready === false ? " (not ready)" : ""}
                  </option>
                ))}
              </Select>
              {season ? (
                <div className="rounded-[12px] bg-surface-muted/70 px-3 py-2.5">
                  <div className="text-[12.5px] font-semibold text-ink">{PLANNING_MODE_LABEL[draft.planning_mode]?.plain ?? titleCase(draft.planning_mode)}</div>
                  <div className="text-[12px] leading-snug text-ink-secondary">{PLANNING_MODE_LABEL[draft.planning_mode]?.hint}</div>
                  {season.planning_modes.length > 1 ? (
                    <Segmented
                      label="Planning mode"
                      size="sm"
                      className="mt-2"
                      value={draft.planning_mode}
                      onChange={(v) => s.patch({ planning_mode: v })}
                      options={(season.planning_modes as (typeof draft.planning_mode)[]).map((m) => ({
                        value: m,
                        label: m === "historical_replay" ? "Past" : m === "season_response" ? "Coming" : "New works",
                        title: PLANNING_MODE_LABEL[m]?.plain ?? titleCase(m),
                      }))}
                    />
                  ) : null}
                  <div className="num mt-1.5 text-[11.5px] text-ink-tertiary">
                    {formatDate(season.start)} – {formatDate(season.end)} · deciding on {formatDate(draft.decision_at.slice(0, 10))}
                  </div>
                </div>
              ) : null}
            </Group>

            <Group icon={<CloudSun size={14} />} title="How much water?" tour="settings-water">
              <SliderField
                label="Canal water cut"
                help={<TermHint id="shortage" />}
                unit="%"
                value={fractionToPercent(draft.uniform_reduction_fraction)}
                onChange={(v) => s.patch({ uniform_reduction_fraction: percentToFraction(v) })}
                min={0}
                max={60}
                step={1}
                format={(v) => String(Math.round(v * 10) / 10)}
                parse={(t) => (Number.isFinite(Number(t)) && t.trim() !== "" ? Number(t) : null)}
                inputWidth="w-[78px]"
                hint="0% is a normal year; 22% matches this season's projected shortage."
              />
              {catalog.weather.isLoading ? (
                <Skeleton className="h-10 w-full" />
              ) : weather.length ? (
                <Select
                  label="Weather year"
                  help={<TermHint id="weather" />}
                  value={draft.weather_scenario_ids[0] ?? ""}
                  onChange={(e) => s.patch({ weather_scenario_ids: [e.target.value] })}
                  hint="A real past season's weather, used as a scenario (not a forecast)."
                >
                  {!draft.weather_scenario_ids.length ? <option value="">Choose…</option> : null}
                  {weather.map((w) => (
                    <option key={w.weather_scenario_id} value={w.weather_scenario_id}>
                      {titleCase(w.label.replace(/\s*analog.*$/i, ""))} · like {w.analog_season_start.slice(0, 4)}
                      {w.is_typical ? " (typical)" : ""}
                    </option>
                  ))}
                </Select>
              ) : (
                <p className="text-[12px] text-warning">No weather scenarios published for this season.</p>
              )}
            </Group>

            <Group icon={<Coins size={14} />} title="How much money?" tour="settings-money">
              <div data-tour="capital-budget">
                <SliderField
                  label="Budget for new works"
                  help={<TermHint id="capitalBudget" />}
                  value={draft.capital_budget_pkr}
                  onChange={(v) => s.patch({ capital_budget_pkr: Math.floor(v) })}
                  min={0}
                  max={10_000_000}
                  step={50_000}
                  format={(v) => formatPKR(v).replace("PKR ", "")}
                  parse={parsePKR}
                  unit="PKR"
                  hint={`${formatPKRCompact(draft.capital_budget_pkr)} one-time · 0 means no new works.`}
                />
              </div>
              <SliderField
                label="Budget for running costs"
                help={<TermHint id="operatingBudget" />}
                value={draft.operating_budget_pkr}
                onChange={(v) => s.patch({ operating_budget_pkr: Math.floor(v) })}
                min={0}
                max={2_000_000}
                step={10_000}
                format={(v) => formatPKR(v).replace("PKR ", "")}
                parse={parsePKR}
                unit="PKR"
                hint={`${formatPKRCompact(draft.operating_budget_pkr)} this season · pumping and upkeep.`}
              />
            </Group>

            <Group icon={<Scale size={14} />} title="Who must be protected?" tour="settings-fair">
              <Switch
                label="Guarantee a fair share to a group of fields"
                description="Tail-end fields lose most water on the way. A guarantee protects them even if total harvest drops."
                checked={draft.minimum_service_ratio !== null}
                onChange={(on) => s.patch(on ? { minimum_service_ratio: 0.5, service_group: "tail" } : { minimum_service_ratio: null, service_group: null })}
              />
              {draft.minimum_service_ratio !== null ? (
                <>
                  <Segmented
                    label="Protected group"
                    size="sm"
                    value={draft.service_group ?? "all"}
                    onChange={(v) => s.patch({ service_group: v })}
                    options={(["tail", "middle", "head", "all"] as const).map((g) => ({ value: g, label: GROUP_LABEL[g] }))}
                  />
                  <SliderField
                    label="Minimum fair share"
                    help={<TermHint id="service" />}
                    unit="%"
                    value={fractionToPercent(draft.minimum_service_ratio)}
                    onChange={(v) => s.patch({ minimum_service_ratio: percentToFraction(v) })}
                    min={0}
                    max={100}
                    step={1}
                    format={(v) => String(Math.round(v))}
                    parse={(t) => (Number.isFinite(Number(t)) && t.trim() !== "" ? Number(t) : null)}
                    inputWidth="w-[78px]"
                    warning={serviceWarning(readiness?.max_attainable_service, draft.service_group ?? "all", draft.minimum_service_ratio, s.dirty)}
                    hint="The highest reachable share for each group appears once these settings are checked."
                  />
                </>
              ) : null}
            </Group>

            <div className="rounded-[14px] border border-border">
              <button
                type="button"
                className="flex w-full items-center justify-between px-3.5 py-3 text-left text-[13px] font-semibold text-ink"
                aria-expanded={advanced}
                onClick={() => setAdvanced((a) => !a)}
              >
                <span>
                  Planning assumptions
                  <span className="block text-[11.5px] font-normal text-ink-tertiary">Supply pattern, pumping, objective, specific works</span>
                </span>
                <ChevronRight size={15} className={cn("shrink-0 transition-transform duration-150", advanced && "rotate-90")} aria-hidden />
              </button>
              {advanced ? (
                <div className="flex animate-rise flex-col gap-4 border-t border-border px-3.5 py-3.5">
                  <Select label="Canal supply pattern" help={<TermHint id="supply" />} value={draft.supply_profile_id} onChange={(e) => s.patch({ supply_profile_id: e.target.value })}>
                    {supplyIds.length ? null : <option value={draft.supply_profile_id}>{draft.supply_profile_id}</option>}
                    {supplyIds.map((id) => (
                      <option key={id} value={id}>
                        {supply.find((p) => p.supply_profile_id === id)?.label ?? titleCase(id)}
                      </option>
                    ))}
                  </Select>
                  <Switch
                    label="Allow pumping from existing wells"
                    description="Limited by each pump's seasonal cap and the running-cost budget"
                    checked={draft.permit_groundwater}
                    onChange={(v) => s.patch({ permit_groundwater: v })}
                  />
                  <Select label="Aim for" value={draft.objective} onChange={(e) => s.patch({ objective: e.target.value as typeof draft.objective })} hint="Contribution needs a dated crop price and all variable costs.">
                    <option value="production_kg">Most crop harvested (kg)</option>
                    <option value="irrigation_contribution_pkr">Most irrigation contribution (PKR)</option>
                  </Select>
                  <InterventionPicker
                    items={catalog.interventions.data ?? []}
                    loading={catalog.interventions.isLoading}
                    forced={draft.forced_instance_ids}
                    excluded={draft.excluded_instance_ids}
                    onChange={(forced, excluded) => s.patch({ forced_instance_ids: forced, excluded_instance_ids: excluded })}
                  />
                </div>
              ) : null}
            </div>

            {readiness && (readiness.blockers?.length || readiness.warnings?.length) ? (
              <div className="flex flex-col gap-1.5 rounded-[12px] bg-warning-soft p-3 text-[12px] text-warning" role="status">
                {[...(readiness.blockers ?? []), ...(readiness.warnings ?? [])].map((b, i) => (
                  <div key={i} className="flex gap-1.5">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden />
                    <span>{b.detail}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-5 py-4">
        {s.phase === "dirty" ? (
          <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-medium text-warning" role="status">
            <AlertTriangle size={13} aria-hidden /> Settings changed: run again for a new answer
          </p>
        ) : null}
        <div className="flex items-center gap-2">
          <Button
            variant="hero"
            size="lg"
            className="flex-1"
            icon={<Sparkles size={16} />}
            busy={s.busy || s.phase === "running"}
            disabled={!draft || !draft.weather_scenario_ids.length || s.phase === "running"}
            onClick={() => void s.run()}
            data-testid="run-plan"
            data-tour="run"
          >
            {s.phase === "running" ? "Solving three plans…" : s.phase === "dirty" ? "Run again" : "Find the best plan"}
          </Button>
          {s.phase === "dirty" ? (
            <IconButton label="Undo changes since the last run" variant="secondary" size="lg" onClick={s.reset}>
              <RotateCcw size={16} />
            </IconButton>
          ) : null}
        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-ink-tertiary">Solves today's routine, smarter timing and the recommended plan under identical conditions.</p>
      </div>
    </aside>
  );
}

function serviceWarning(max: Record<string, number | null> | undefined, group: string, floor: number, dirty: boolean) {
  if (!max || dirty) return null;
  const vals = Object.values(max).filter((v): v is number => typeof v === "number");
  const m = typeof max[group] === "number" ? max[group] : group === "all" && vals.length ? Math.min(...vals) : null;
  if (typeof m !== "number" || floor <= m) return null;
  return (
    <span className="inline-flex items-start gap-1">
      <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden />
      {formatPercent(floor)} is more than the {GROUP_LABEL[group]?.toLowerCase() ?? group} fields can reach ({formatPercent(m)}) with this water and these repairs. No plan will fit; lower it or add repairs.
    </span>
  );
}

function PhaseChip({ phase }: { phase: string }) {
  const m: Record<string, [string, "neutral" | "warning" | "water" | "vegetation" | "danger"]> = {
    loading: ["Loading", "neutral"],
    unavailable: ["Unavailable", "danger"],
    draft: ["Not run yet", "neutral"],
    dirty: ["Changed", "warning"],
    current: ["Up to date", "vegetation"],
    running: ["Solving", "water"],
  };
  const [t, tone] = m[phase] ?? m.draft;
  return (
    <Chip size="sm" tone={tone}>
      {t}
    </Chip>
  );
}

function InterventionPicker({
  items,
  loading,
  forced,
  excluded,
  onChange,
}: {
  items: InterventionInstance[];
  loading: boolean;
  forced: string[];
  excluded: string[];
  onChange: (f: string[], e: string[]) => void;
}) {
  const [cat, setCat] = useState<ActionCategory | null>(null);
  const byCat = useMemo(() => {
    const m = new Map<ActionCategory, InterventionInstance[]>();
    for (const it of items) m.set(it.category, [...(m.get(it.category) ?? []), it]);
    return m;
  }, [items]);
  if (loading) return <Skeleton className="h-24 w-full" />;
  if (!items.length) return <p className="text-[12px] text-ink-secondary">No works catalog for this season.</p>;
  const stateOf = (id: string) => (forced.includes(id) ? "force" : excluded.includes(id) ? "exclude" : "auto");
  const setState = (id: string, st: "auto" | "force" | "exclude") => {
    const f = forced.filter((x) => x !== id);
    const e = excluded.filter((x) => x !== id);
    if (st === "force") f.push(id);
    if (st === "exclude") e.push(id);
    onChange(f, e);
  };
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-ink-secondary">
        <Hammer size={13} aria-hidden /> Specific works ({items.length}): let the optimiser choose, force or rule out
      </div>
      <ul className="flex flex-col gap-1">
        {(Object.keys(CATEGORY_META) as ActionCategory[]).map((c) => {
          const list = byCat.get(c) ?? [];
          const open = cat === c;
          const nForced = list.filter((x) => forced.includes(x.instance_id)).length;
          const nEx = list.filter((x) => excluded.includes(x.instance_id)).length;
          return (
            <li key={c} className="rounded-[10px] bg-surface-muted/70">
              <button type="button" className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[12.5px] text-ink" aria-expanded={open} onClick={() => setCat(open ? null : c)} disabled={!list.length}>
                {CATEGORY_META[c].icon}
                <span className="flex-1 font-medium" title={CATEGORY_META[c].precise}>
                  {CATEGORY_META[c].label}
                </span>
                {nForced ? <Chip size="sm" tone="water">{nForced} forced</Chip> : null}
                {nEx ? <Chip size="sm" tone="warning">{nEx} ruled out</Chip> : null}
                <span className="num text-ink-tertiary">{list.length}</span>
              </button>
              {open ? (
                <ul className="flex flex-col gap-1 px-2 pb-2">
                  {list.map((it) => (
                    <li key={it.instance_id} className="rounded-[8px] bg-surface px-2.5 py-2">
                      <div className="min-w-0">
                        <div className="truncate text-[12px] font-medium text-ink" title={it.instance_id}>
                          {it.label ?? it.instance_id.split(":").slice(1).join(" · ")}
                        </div>
                        <div className="num text-[11px] text-ink-secondary">
                          {it.capex_pkr ? formatPKRCompact(it.capex_pkr) : "No capex"}
                          {it.seasonal_opex_pkr ? ` · ${formatPKRCompact(it.seasonal_opex_pkr)}/season` : ""}
                          {it.lead_time_days ? ` · ${it.lead_time_days} days to build` : ""}
                          {it.shared ? " · shared" : ""}
                        </div>
                        {it.eligible === false && it.eligibility_reasons?.length ? <div className="mt-0.5 text-[11px] text-warning">{it.eligibility_reasons.join("; ")}</div> : null}
                      </div>
                      <Segmented
                        label={`Treatment of ${it.instance_id}`}
                        size="sm"
                        className="mt-1.5"
                        value={stateOf(it.instance_id)}
                        onChange={(v) => setState(it.instance_id, v)}
                        options={[
                          { value: "auto", label: "Optimiser" },
                          { value: "force", label: "Force", disabled: it.eligible === false, title: it.eligible === false ? "Not eligible" : undefined },
                          { value: "exclude", label: "Rule out" },
                        ]}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
