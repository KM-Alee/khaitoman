/**
 * SDG proxy cards for GET /runs/{id}/impact (PRD §8.5, T10).
 * Display-only: formulas, terms, units, limitations and statuses come from the payload.
 */
import { useMemo } from "react";
import { ExternalLink, Info } from "lucide-react";
import { useMediaQuery } from "@/app/environment";
import { ChartPanel, DataTable, EChart, baseOption, chartTokens } from "@/components/charts/EChart";
import { Chip, MetricValueView, StatePanel } from "@/components/status";
import { Eyebrow } from "@/components/ui/primitives";
import { formatDelta, formatMass, formatNumber, formatWithUnit, shortId } from "@/lib/formatting";
import type { MetricStatus, MetricValue } from "@/lib/api/types";
import { Panel, StatusReasonView, statusLabel, useFieldLabel } from "./viewKit";
import {
  plottedNumber,
  readCanonicalImpact,
  termAsMetric,
  unitLabel,
  type CanonicalImpact,
  type CanonicalSdgCard,
  type FieldChangeRow,
  type SdgTerm,
} from "./sdgView";

const TITLES: Record<string, string> = {
  "SDG 2.4": "Sustainable food production",
  "SDG 6.4/6.5": "Water-use efficiency and integrated management",
  "SDG 13.1": "Resilience to climate hazards",
};

const METRIC_LABEL: Record<string, string> = {
  sdg_2_4_production_retained_fraction: "Production retained (worst ÷ typical)",
  production_kg: "Production",
  worst_tested_production_kg: "Worst tested production",
  typical_production_kg: "Typical-state production",
  sdg_6_4_water_productivity_kg_m3: "Water productivity",
  canal_source_withdrawal_m3: "Canal source withdrawal",
  groundwater_m3: "Groundwater abstraction",
  sdg_6_5_min_entitlement_fulfillment: "Minimum entitlement fulfilment",
  sdg_6_4_groundwater_change_m3: "Groundwater change vs baseline",
  sdg_13_1_worst_tested_production_kg: "Worst tested production",
};

function metricLabel(metric: MetricValue): string {
  return metric.label || METRIC_LABEL[metric.metric_id] || metric.metric_id.replace(/_/g, " ");
}

function flagText(value: boolean | null): string {
  if (value === null) return "not returned";
  return value ? "true" : "false";
}

export function SdgCards({ impact }: { impact: object }) {
  const view = useMemo(() => readCanonicalImpact(impact), [impact]);
  return (
    <div className="flex flex-col gap-3" data-testid="sdg">
      <p className="flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-secondary">
        <Info size={13} className="mt-0.5 shrink-0" aria-hidden />
        Project proxies returned by the server and aligned to SDG targets. They are not official UN indicators and are never combined into a 0–100 score.
      </p>
      {view.compatible === false ? (
        <p className="text-[12px] text-ink" data-testid="impact-compatibility">
          <span className="font-medium">Comparison </span>
          {view.compatibility_label ?? "The server marked this baseline as incompatible."}
        </p>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-3" aria-label="SDG proxy cards">
        {view.cards.map((card) => (
          <SdgCardView key={card.card} card={card} />
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_minmax(0,2fr)]">
        <Co2Panel co2={view.co2} />
        <FieldChanges view={view} />
      </div>
    </div>
  );
}

function SdgCardView({ card }: { card: CanonicalSdgCard }) {
  const title = TITLES[card.card] ?? card.card;
  const headingId = `sdg-${card.card.replace(/[^a-z0-9]+/gi, "-")}`;
  return (
    <article className="flex min-w-0 flex-col rounded-[18px] border border-border bg-surface p-4 shadow-1" data-testid="sdg-card" data-card={card.card} data-status={card.missing ? "missing" : (card.status ?? "unknown")} aria-labelledby={headingId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[12px] font-semibold text-water">{card.card}</div>
        <Chip size="sm" tone={card.official_indicator === true ? "danger" : "warning"}>
          {card.official_indicator === false ? "Project proxy · not official" : card.official_indicator === true ? "Official indicator flag is true" : "official_indicator not returned"}
        </Chip>
      </div>
      <h3 id={headingId} className="mt-0.5 text-[14px] font-semibold leading-snug text-ink">
        {title}
      </h3>
      {card.missing ? (
        <StatePanel state="unknown" title={`${card.card} was not returned`} compact className="mt-3">
          The impact response did not include this card. No proxy was estimated in the browser.
        </StatePanel>
      ) : (
        <SdgCardBody card={card} />
      )}
    </article>
  );
}

function SdgCardBody({ card }: { card: CanonicalSdgCard }) {
  const expectsDenominator = card.card !== "SDG 13.1";
  const expectsDifference = card.card === "SDG 13.1" || card.difference_from_typical !== null;
  return (
    <>
      <p className="mt-2 text-[13px] leading-relaxed text-ink" data-testid="official-target">
        {card.official_target_text ?? "Official target text was not returned."}
      </p>
      {card.target_url ? (
        <a href={card.target_url} target="_blank" rel="noreferrer" className="no-print mt-1 inline-flex items-center gap-1 text-[12px] text-water hover:underline">
          UN target for {card.card}
          <ExternalLink size={11} aria-hidden />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ) : (
        <p className="mt-1 text-[12px] text-ink-tertiary">Target URL was not returned.</p>
      )}
      {card.interpretation ? <p className="mt-2 text-[12px] leading-snug text-ink-secondary">{card.interpretation}</p> : null}
      <div className="mt-3" data-testid="card-status">
        <StatusReasonView v={card.status ? { status: card.status, reason: card.reason } : null} />
      </div>
      {card.crop ? (
        <p className="mt-2 text-[12px] text-ink-secondary">
          Crop <span className="font-medium text-ink">{card.crop}</span>
        </p>
      ) : null}
      {card.formula ? (
        <p className="mt-3 text-[12px]">
          <span className="text-ink-secondary">Formula </span>
          <code className="break-words font-mono text-[11px] text-ink">{card.formula}</code>
        </p>
      ) : (
        <p className="mt-3 text-[12px] text-ink-tertiary">Formula was not returned.</p>
      )}
      <div className="mt-3 flex flex-col gap-2">
        <TermSlot label="Numerator" term={card.numerator} />
        {expectsDenominator ? <TermSlot label="Denominator" term={card.denominator} /> : null}
        {expectsDifference ? <TermSlot label="Difference from typical" term={card.difference_from_typical} /> : null}
      </div>
      <ul className="mt-3 flex flex-col divide-y divide-border border-y border-border">
        {card.values.length ? (
          card.values.map((metric) => (
            <li key={metric.metric_id} className="py-2.5" data-metric-id={metric.metric_id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[12px] text-ink-secondary" title={metric.definition_id || metric.metric_id}>
                  {metricLabel(metric)}
                </span>
                <span className="shrink-0 text-right">
                  <MetricValueView metric={metric} size="sm" showReason={false} />
                  <span className="mt-0.5 block text-[11px] text-ink-tertiary">Unit {unitLabel(metric.unit)}</span>
                </span>
              </div>
              {metric.reason ? <div className="mt-0.5 text-[11px] text-ink-tertiary">{metric.reason}</div> : null}
              {card.formulas[metric.metric_id] ? <code className="mt-1 block break-words font-mono text-[11px] leading-snug text-ink">{card.formulas[metric.metric_id]}</code> : null}
            </li>
          ))
        ) : (
          <li className="py-2.5 text-[12px] text-ink-tertiary">No metric values were returned.</li>
        )}
      </ul>
      <div className="mt-3" data-testid="limitations">
        <Eyebrow>Limitations</Eyebrow>
        {card.limitations.length ? (
          <ul className="mt-1 list-disc pl-4 text-[12px] leading-snug text-ink-secondary">
            {card.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[12px] text-ink-tertiary">No limitations were returned.</p>
        )}
      </div>
      <div className="mt-3" data-testid="source-records">
        <Eyebrow>Source records</Eyebrow>
        {card.source_records.length ? (
          <ul className="mt-1 break-all font-mono text-[11px] text-ink-secondary">
            {card.source_records.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[12px] text-ink-tertiary">No source records were returned.</p>
        )}
      </div>
      <div className="mt-auto flex flex-col gap-1 pt-3 text-[11px] text-ink-tertiary">
        <p>
          Runs <span className="font-mono text-ink">{card.run_ids.length ? card.run_ids.map((id) => shortId(id)).join(", ") : "not returned"}</span>
        </p>
        <p>
          Baseline <span className="font-mono text-ink">{card.baseline_run_id ? shortId(card.baseline_run_id) : "none"}</span>
        </p>
        <p data-testid="official-indicator">official_indicator = {flagText(card.official_indicator)}</p>
      </div>
    </>
  );
}

function TermSlot({ label, term }: { label: string; term: SdgTerm | null }) {
  return (
    <div data-testid={`term-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="text-[11px] font-medium text-ink-tertiary">{label}</div>
      {term ? (
        <>
          <div className="text-[12px] text-ink-secondary">{term.label}</div>
          <MetricValueView metric={termAsMetric(term)} size="sm" />
          <div className="text-[11px] text-ink-tertiary">Unit {unitLabel(term.unit)}</div>
          {term.formula ? <code className="mt-0.5 block break-words font-mono text-[11px] text-ink">{term.formula}</code> : null}
        </>
      ) : (
        <p className="text-[12px] text-ink-tertiary">{label} was not returned.</p>
      )}
    </div>
  );
}

function Co2Panel({ co2 }: { co2: CanonicalImpact["co2"] }) {
  const status = co2.status;
  return (
    <section className="min-w-0 self-start rounded-[18px] border border-border bg-surface p-4 shadow-1" data-testid="co2" data-status={status ?? "missing"}>
      <Eyebrow>CO₂ estimate</Eyebrow>
      <p className="mt-2 text-[13px] font-medium text-ink" data-testid="co2-status">
        {status === "not_estimated" ? "Not estimated" : status ? statusLabel(status) : "CO₂ status was not returned."}
      </p>
      {status === "not_estimated" ? <p className="sr-only">not_estimated</p> : null}
      {co2.reason ? <p className="mt-1 text-[12px] leading-snug text-ink-secondary">{co2.reason}</p> : null}
      <p className="mt-2 text-[12px] text-ink-secondary" data-testid="co2-indicator">
        official_indicator = {flagText(co2.official_indicator)}
      </p>
      {status === "available" && co2.value !== null ? (
        <p className="num mt-2 text-[13px] text-ink">{formatWithUnit(co2.value, co2.unit ?? "")}</p>
      ) : (
        <p className="mt-2 text-[12px] text-ink-tertiary" data-testid="co2-value">
          No CO₂ value is shown.
        </p>
      )}
    </section>
  );
}

function FieldChanges({ view }: { view: CanonicalImpact }) {
  const summary = view.field_change_summary;
  const rows = view.distribution;
  const mode: "delta_kg" | "production_kg" = rows.some((row) => typeof row.delta_kg === "number") ? "delta_kg" : "production_kg";
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Panel title="Field-change summary" className="self-start">
        {summary.reported ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]" data-testid="field-change-summary">
            <Count label="Worse off" value={summary.fields_worse_off} />
            <Count label="Better off" value={summary.fields_better_off} />
            <Count label="Unchanged" value={summary.fields_unchanged} />
            <Count label="Not comparable" value={summary.fields_not_comparable} />
            <div className="col-span-2">
              <dt className="text-ink-tertiary">Quantum</dt>
              <dd className="num text-ink">{summary.quantum_kg === null ? "Not reported" : `${formatNumber(summary.quantum_kg, 3)} ${unitLabel(summary.unit)}`}</dd>
            </div>
          </dl>
        ) : (
          <p data-testid="field-change-summary">Field-change summary was not returned. Counts are not calculated in the browser.</p>
        )}
      </Panel>
      <Distribution rows={rows} mode={mode} />
    </div>
  );
}

function Count({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className="num text-[16px] font-semibold text-ink">{value === null ? "Not reported" : String(value)}</dd>
    </div>
  );
}

function Distribution({ rows, mode }: { rows: FieldChangeRow[]; mode: "delta_kg" | "production_kg" }) {
  const t = chartTokens();
  const label = useFieldLabel();
  const narrow = useMediaQuery("(max-width: 640px)");
  const plotted = rows.map((row) => plottedNumber(row.status, mode === "delta_kg" ? row.delta_kg : row.production_kg));
  const gaps = rows.filter((_, index) => plotted[index] === null);
  const anyBar = plotted.some((value) => value !== null);
  const axisUnit = mode === "delta_kg" ? "kg" : rows.find((row) => row.unit)?.unit || "kg";
  const option = useMemo(
    () => ({
      ...baseOption(),
      grid: { left: 48, right: 12, top: 24, bottom: 44 },
      tooltip: { ...(baseOption().tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        ...(baseOption().xAxis as object),
        type: "category",
        data: rows.map((row) => label(row.field_id)),
        axisLabel: { color: t.ink3, fontSize: 10, rotate: 50 },
      },
      yAxis: {
        ...(baseOption().yAxis as object),
        type: "value",
        name: unitLabel(axisUnit),
        nameTextStyle: { color: t.ink3, fontSize: 11 },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (value: number) => formatNumber(value, 0) },
      },
      series: [
        {
          type: "bar",
          name: mode === "delta_kg" ? "Production change" : "Production",
          data: rows.map((_, index) => ({
            value: plotted[index],
            itemStyle: {
              color: mode === "delta_kg" && plotted[index] !== null && plotted[index]! < 0 ? t.danger : t.veg,
              borderRadius: [3, 3, 0, 0],
            },
          })),
          barMaxWidth: 14,
          ...(mode === "delta_kg"
            ? {
                markLine: {
                  silent: true,
                  symbol: "none",
                  lineStyle: { color: t.ink3, type: "dashed" },
                  label: { show: false },
                  data: [{ yAxis: 0 }],
                },
              }
            : {}),
        },
      ],
    }),
    [rows, plotted, t, label, mode, axisUnit],
  );
  const title = mode === "delta_kg" ? "Field production change" : "Production by field";
  const summary =
    mode === "delta_kg"
      ? "Each bar is the server delta_kg. Missing and blocked comparisons stay empty rather than zero."
      : "Each bar is the server production_kg. Missing values stay empty rather than zero.";
  return (
    <div>
      <ChartPanel
        id="sdg-distribution"
        defaultView={narrow ? "table" : "chart"}
        key={narrow ? "n" : "w"}
        title={title}
        summary={summary}
        chart={
          anyBar ? (
            <EChart option={option} height={220} ariaLabel={`${title}. The table lists every field, including blocked and missing rows.`} />
          ) : (
            <p className="p-4 text-[13px] text-ink-secondary">No comparable field values were returned to plot.</p>
          )
        }
        table={
          <DataTable
            caption="Field production change"
            dense
            columns={[
              { key: "f", label: "Field" },
              { key: "p", label: "Production", align: "right" },
              { key: "b", label: "Baseline", align: "right" },
              { key: "d", label: "Change", align: "right" },
              { key: "s", label: "Status" },
            ]}
            rows={rows.map((row) => ({
              f: label(row.field_id),
              p: amount(row.status, row.production_kg, row.unit || "kg"),
              b: amount(row.status, row.baseline_production_kg, row.unit || "kg"),
              d: changeText(row),
              s: row.reason ? `${statusLabel(row.status ?? "not returned")} · ${row.reason}` : statusLabel(row.status ?? "not returned"),
            }))}
          />
        }
      />
      <DistributionGaps rows={gaps} />
    </div>
  );
}

function changeText(row: FieldChangeRow): string {
  if (row.status === "available" && typeof row.delta_kg === "number") return formatDelta(row.delta_kg, row.unit || "kg");
  return statusLabel(row.status ?? "not returned");
}

function amount(status: MetricStatus | null, value: number | null, unit: string): string {
  if (status === "available" && value !== null) {
    return unit === "kg" || unit === "" ? formatMass(value) : formatWithUnit(value, unit);
  }
  return "—";
}

function DistributionGaps({ rows }: { rows: FieldChangeRow[] }) {
  const label = useFieldLabel();
  if (!rows.length) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1 text-[12px] text-ink-secondary" data-testid="distribution-gaps">
      {rows.map((row) => (
        <li key={row.field_id}>
          {label(row.field_id)} · {statusLabel(row.status ?? "not returned")}
          {row.reason ? ` · ${row.reason}` : ""} · Unit {unitLabel(row.unit)}
        </li>
      ))}
    </ul>
  );
}
