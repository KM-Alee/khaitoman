import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Droplets,
  Hammer,
  PanelLeftClose,
  Play,
  RotateCcw,
  Tractor,
  Waves,
  Wrench,
  Clock3,
} from "lucide-react";
import { useScenario } from "./useScenario";
import { useRevision } from "@/lib/api/queries";
import type { ActionCategory, InterventionInstance } from "@/lib/api/types";
import { formatDate, formatPKR, formatPKRCompact, formatPercent, titleCase } from "@/lib/formatting";
import { parsePKR, fractionToPercent, percentToFraction } from "@/lib/units";
import { Button, IconButton } from "@/components/ui/Button";
import { Eyebrow, Segmented, Select, SliderField, Switch } from "@/components/ui/primitives";
import { Chip, StatePanel, Skeleton } from "@/components/status";
import { cn } from "@/lib/cn";

export const CATEGORY_META: Record<ActionCategory, { label: string; icon: React.ReactNode }> = {
  timing: { label: "Timing with existing assets", icon: <Clock3 size={14} aria-hidden /> },
  leveling: { label: "Leveling service", icon: <Tractor size={14} aria-hidden /> },
  pond: { label: "New pond", icon: <Waves size={14} aria-hidden /> },
  shared_repair: { label: "Shared repair", icon: <Wrench size={14} aria-hidden /> },
  pump_supplement: { label: "Existing-pump supplement", icon: <Droplets size={14} aria-hidden /> },
};

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
  const readiness = revision.data?.readiness as
    | ({ ready: boolean; blockers?: string[]; warnings?: string[]; max_attainable_service?: Record<string, number> } & Record<string, unknown>)
    | undefined;

  return (
    <aside
      aria-label="Scenario inputs"
      className={cn("flex h-full min-h-0 flex-col border-r border-border bg-surface", className)}
      data-testid="scenario-panel"
    >
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold text-ink">Scenario</h2>
          <PhaseChip phase={s.phase} />
        </div>
        {onCollapse ? (
          <IconButton label="Collapse scenario panel" size="sm" onClick={onCollapse}>
            <PanelLeftClose size={16} />
          </IconButton>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {catalog.seasons.error ? (
          <StatePanel state="error" error={catalog.seasons.error} title="Season catalog unavailable">
            The API could not list crop/season configurations for this pilot. Planning inputs stay disabled until it does.
          </StatePanel>
        ) : !draft ? (
          catalog.seasons.data && !catalog.seasons.data.length ? (
            <StatePanel state="empty" title="No season configurations">
              This pilot version has no published crop/season configuration yet, so no plan can be run.
            </StatePanel>
          ) : (
            <div className="flex flex-col gap-4" aria-busy>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          )
        ) : (
          <div className="flex flex-col gap-5">
            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1">
                <Eyebrow>Season</Eyebrow>
              </legend>
              <Select
                label="Crop and season"
                value={draft.season_id}
                onChange={(e) => {
                  const ns = seasons.find((x) => x.season_id === e.target.value);
                  if (!ns) return;
                  s.patch({
                    season_id: ns.season_id,
                    planning_mode: (ns.planning_modes[0] as typeof draft.planning_mode) ?? draft.planning_mode,
                    decision_at: `${ns.start.slice(0, 10)}T00:00:00+05:00`,
                    weather_scenario_ids: [],
                  });
                }}
              >
                {seasons.map((x) => (
                  <option key={x.season_id} value={x.season_id}>
                    {titleCase(x.crop)} · {x.label ?? x.season_id}
                    {x.library_ready === false ? " (library not ready)" : ""}
                  </option>
                ))}
              </Select>
              {season ? (
                <>
                  <div>
                    <div className="mb-1 text-[12px] font-medium text-ink-secondary">Planning mode</div>
                    <Segmented
                      label="Planning mode"
                      size="sm"
                      value={draft.planning_mode}
                      onChange={(v) => s.patch({ planning_mode: v })}
                      options={(season.planning_modes as (typeof draft.planning_mode)[]).map((m) => ({
                        value: m,
                        label: m === "historical_replay" ? "Replay" : m === "season_response" ? "Season" : "Capital",
                        title: titleCase(m),
                      }))}
                    />
                  </div>
                  <p className="num text-[12px] text-ink-secondary">
                    {formatDate(season.start)} – {formatDate(season.end)} · decision {formatDate(draft.decision_at.slice(0, 10))}
                  </p>
                </>
              ) : null}
            </fieldset>

            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1">
                <Eyebrow>Weather and supply</Eyebrow>
              </legend>
              {catalog.weather.isLoading ? (
                <Skeleton className="h-9 w-full" />
              ) : weather.length ? (
                <Select
                  label="Weather analog"
                  value={draft.weather_scenario_ids[0] ?? ""}
                  onChange={(e) => s.patch({ weather_scenario_ids: [e.target.value] })}
                  hint={weather.find((w) => w.weather_scenario_id === draft.weather_scenario_ids[0])?.selection_basis}
                >
                  {!draft.weather_scenario_ids.length ? <option value="">Choose…</option> : null}
                  {weather.map((w) => (
                    <option key={w.weather_scenario_id} value={w.weather_scenario_id}>
                      {w.label} · analog {w.analog_season_start.slice(0, 4)}
                      {w.is_typical ? " (typical)" : ""}
                    </option>
                  ))}
                </Select>
              ) : (
                <p className="text-[12px] text-warning">No weather scenarios published for this season.</p>
              )}
              <Select label="Supply profile" value={draft.supply_profile_id} onChange={(e) => s.patch({ supply_profile_id: e.target.value })}>
                {supplyIds.length ? null : <option value={draft.supply_profile_id}>{draft.supply_profile_id}</option>}
                {supplyIds.map((id) => (
                  <option key={id} value={id}>
                    {supply.find((p) => p.supply_profile_id === id)?.label ?? titleCase(id)}
                  </option>
                ))}
              </Select>
              <SliderField
                label="Uniform shortage"
                unit="%"
                value={fractionToPercent(draft.uniform_reduction_fraction)}
                onChange={(v) => s.patch({ uniform_reduction_fraction: percentToFraction(v) })}
                min={0}
                max={60}
                step={1}
                format={(v) => String(Math.round(v * 10) / 10)}
                parse={(t) => (Number.isFinite(Number(t)) && t.trim() !== "" ? Number(t) : null)}
                inputWidth="w-[76px]"
                hint="Proportional curtailment of every roster window's cap."
              />
            </fieldset>

            <fieldset className="flex flex-col gap-4">
              <legend className="mb-1">
                <Eyebrow>Budgets</Eyebrow>
              </legend>
              <SliderField
                label="Capital budget (gross project commitment)"
                value={draft.capital_budget_pkr}
                onChange={(v) => s.patch({ capital_budget_pkr: Math.floor(v) })}
                min={0}
                max={10_000_000}
                step={50_000}
                format={(v) => formatPKR(v).replace("PKR ", "")}
                parse={parsePKR}
                unit="PKR"
                hint={`${formatPKRCompact(draft.capital_budget_pkr)} · zero capital means no new assets.`}
              />
              <SliderField
                label="Seasonal operating budget"
                value={draft.operating_budget_pkr}
                onChange={(v) => s.patch({ operating_budget_pkr: Math.floor(v) })}
                min={0}
                max={2_000_000}
                step={10_000}
                format={(v) => formatPKR(v).replace("PKR ", "")}
                parse={parsePKR}
                unit="PKR"
                hint={`${formatPKRCompact(draft.operating_budget_pkr)} · pumping and upkeep.`}
              />
            </fieldset>

            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1">
                <Eyebrow>Service target</Eyebrow>
              </legend>
              <Switch
                label="Minimum service floor"
                description="Hard floor on receipt ÷ reference allowance"
                checked={draft.minimum_service_ratio !== null}
                onChange={(on) => s.patch(on ? { minimum_service_ratio: 0.5, service_group: "tail" } : { minimum_service_ratio: null, service_group: null })}
              />
              {draft.minimum_service_ratio !== null ? (
                <>
                  <Segmented
                    label="Service group"
                    size="sm"
                    value={draft.service_group ?? "all"}
                    onChange={(v) => s.patch({ service_group: v })}
                    options={(["all", "head", "middle", "tail"] as const).map((g) => ({ value: g, label: titleCase(g) }))}
                  />
                  <SliderField
                    label="Floor"
                    unit="%"
                    value={fractionToPercent(draft.minimum_service_ratio)}
                    onChange={(v) => s.patch({ minimum_service_ratio: percentToFraction(v) })}
                    min={0}
                    max={100}
                    step={1}
                    format={(v) => String(Math.round(v))}
                    parse={(t) => (Number.isFinite(Number(t)) && t.trim() !== "" ? Number(t) : null)}
                    inputWidth="w-[76px]"
                    warning={serviceWarning(readiness?.max_attainable_service, draft.service_group ?? "all", draft.minimum_service_ratio, s.dirty)}
                    hint="Maximum attainable service per group appears after the inputs validate."
                  />
                </>
              ) : null}
            </fieldset>

            <div className="rounded-[12px] border border-border">
              <button
                type="button"
                className="flex w-full items-center justify-between px-3 py-2.5 text-left text-[13px] font-medium text-ink"
                aria-expanded={advanced}
                onClick={() => setAdvanced((a) => !a)}
              >
                Planning assumptions
                <ChevronRight size={14} className={cn("transition-transform", advanced && "rotate-90")} aria-hidden />
              </button>
              {advanced ? (
                <div className="flex flex-col gap-4 border-t border-border px-3 py-3">
                  <Switch
                    label="Permit existing-pump groundwater"
                    description="Finite seasonal cap and operating cost apply"
                    checked={draft.permit_groundwater}
                    onChange={(v) => s.patch({ permit_groundwater: v })}
                  />
                  <Select label="Objective" value={draft.objective} onChange={(e) => s.patch({ objective: e.target.value as typeof draft.objective })} hint="Contribution needs a dated crop price and all variable costs.">
                    <option value="production_kg">Modeled production (kg)</option>
                    <option value="irrigation_contribution_pkr">Irrigation contribution (PKR)</option>
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
              <div className="flex flex-col gap-1.5 rounded-[12px] bg-warning-soft p-3 text-[12px] text-warning">
                {[...(readiness.blockers ?? []), ...(readiness.warnings ?? [])].map((b, i) => (
                  <div key={i} className="flex gap-1.5">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden />
                    {b}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-4 py-3">
        {s.phase === "dirty" ? (
          <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-warning" role="status">
            <AlertTriangle size={13} aria-hidden /> Inputs changed — run again
          </p>
        ) : null}
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            className="flex-1"
            icon={<Play size={15} />}
            busy={s.busy || s.phase === "running"}
            disabled={!draft || !draft.weather_scenario_ids.length || s.phase === "running"}
            onClick={() => void s.run()}
            data-testid="run-plan"
          >
            {s.phase === "running" ? "Solving B0 · B1 · P" : s.phase === "dirty" ? "Run again" : "Run plan"}
          </Button>
          {s.phase === "dirty" ? (
            <IconButton label="Discard changes since last run" variant="secondary" onClick={s.reset}>
              <RotateCcw size={15} />
            </IconButton>
          ) : null}
        </div>
        <p className="mt-2 text-[11px] leading-snug text-ink-tertiary">Runs fixed-roster (B0), no-new-capital (B1) and integrated (P) plans under identical conditions.</p>
      </div>
    </aside>
  );
}

function serviceWarning(max: Record<string, number> | undefined, group: string, floor: number, dirty: boolean) {
  if (!max || dirty) return null;
  const m = group === "all" ? Math.min(...Object.values(max)) : max[group];
  if (typeof m !== "number" || floor <= m) return null;
  return (
    <span className="inline-flex items-start gap-1">
      <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden />
      Floor {formatPercent(floor)} exceeds the maximum attainable {group} service ({formatPercent(m)}) under this supply and repair set. The solve will be infeasible.
    </span>
  );
}

function PhaseChip({ phase }: { phase: string }) {
  const m: Record<string, [string, "neutral" | "warning" | "water" | "vegetation" | "danger"]> = {
    loading: ["Loading", "neutral"],
    unavailable: ["Unavailable", "danger"],
    draft: ["Draft", "neutral"],
    dirty: ["Edited", "warning"],
    current: ["Current", "vegetation"],
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
  if (!items.length) return <p className="text-[12px] text-ink-secondary">No intervention catalog for this season.</p>;
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
        <Hammer size={13} aria-hidden /> Interventions ({items.length})
      </div>
      <ul className="flex flex-col gap-1">
        {(Object.keys(CATEGORY_META) as ActionCategory[]).map((c) => {
          const list = byCat.get(c) ?? [];
          const open = cat === c;
          const nForced = list.filter((x) => forced.includes(x.instance_id)).length;
          const nEx = list.filter((x) => excluded.includes(x.instance_id)).length;
          return (
            <li key={c} className="rounded-[10px] bg-surface-muted/70">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[12px] text-ink"
                aria-expanded={open}
                onClick={() => setCat(open ? null : c)}
                disabled={!list.length}
              >
                {CATEGORY_META[c].icon}
                <span className="flex-1 font-medium">{CATEGORY_META[c].label}</span>
                {nForced ? <Chip size="sm" tone="water">{nForced} forced</Chip> : null}
                {nEx ? <Chip size="sm" tone="warning">{nEx} excluded</Chip> : null}
                <span className="num text-ink-tertiary">{list.length}</span>
              </button>
              {open ? (
                <ul className="flex flex-col gap-1 px-2 pb-2">
                  {list.map((it) => (
                    <li key={it.instance_id} className="rounded-[8px] bg-surface px-2.5 py-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-[12px] font-medium text-ink" title={it.instance_id}>
                            {it.label ?? it.instance_id.split(":").slice(1).join(" · ")}
                          </div>
                          <div className="num text-[11px] text-ink-secondary">
                            {it.capex_pkr ? formatPKRCompact(it.capex_pkr) : "No capex"}
                            {it.seasonal_opex_pkr ? ` · ${formatPKRCompact(it.seasonal_opex_pkr)}/season` : ""}
                            {it.lead_time_days ? ` · ${it.lead_time_days} d lead` : ""}
                            {it.shared ? " · shared" : ""}
                          </div>
                          {it.eligible === false && it.eligibility_reasons?.length ? (
                            <div className="mt-0.5 text-[11px] text-warning">{it.eligibility_reasons.join("; ")}</div>
                          ) : null}
                        </div>
                      </div>
                      <Segmented
                        label={`Treatment of ${it.instance_id}`}
                        size="sm"
                        className="mt-1.5"
                        value={stateOf(it.instance_id)}
                        onChange={(v) => setState(it.instance_id, v)}
                        options={[
                          { value: "auto", label: "Optimizer" },
                          { value: "force", label: "Force", disabled: it.eligible === false, title: it.eligible === false ? "Ineligible" : undefined },
                          { value: "exclude", label: "Exclude" },
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
