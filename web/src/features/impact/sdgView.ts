/**
 * Read the canonical impact payload for display (PRD §8.5, T7.5, T10.1).
 * This module copies server fields. It does not divide, subtract, score, or fill gaps with zero.
 */
import type { MetricStatus, MetricValue } from "@/lib/api/types";

export const SDG_CARDS = ["SDG 2.4", "SDG 6.4/6.5", "SDG 13.1"] as const;

const STATUSES = new Set<MetricStatus>(["available", "not_estimated", "not_applicable", "blocked"]);
const ROLES = new Set(["numerator", "denominator", "difference", "component"]);

export interface SdgTerm {
  role: "numerator" | "denominator" | "difference" | "component";
  label: string;
  metric_id: string | null;
  definition_id: string | null;
  value: number | null;
  unit: string;
  status: MetricStatus;
  run_id: string | null;
  reason: string | null;
  formula: string | null;
  evidence_ids: string[];
}

export interface CanonicalSdgCard {
  card: string;
  missing: boolean;
  official_target_text: string | null;
  target_url: string | null;
  official_indicator: boolean | null;
  interpretation: string | null;
  status: MetricStatus | null;
  reason: string | null;
  formula: string | null;
  formulas: Record<string, string>;
  numerator: SdgTerm | null;
  denominator: SdgTerm | null;
  difference_from_typical: SdgTerm | null;
  metrics: string[];
  values: MetricValue[];
  limitations: string[];
  run_id: string | null;
  baseline_run_id: string | null;
  run_ids: string[];
  source_records: string[];
  crop: string | null;
}

export interface FieldChangeRow {
  field_id: string;
  production_kg: number | null;
  baseline_production_kg: number | null;
  delta_kg: number | null;
  unit: string;
  status: MetricStatus | null;
  reason: string | null;
  run_id: string | null;
  baseline_run_id: string | null;
  definition_id: string | null;
  crop: string | null;
  causal: boolean;
}

export interface FieldChangeSummaryView {
  reported: boolean;
  unit: string;
  quantum_kg: number | null;
  fields_worse_off: number | null;
  fields_better_off: number | null;
  fields_unchanged: number | null;
  fields_not_comparable: number | null;
}

export interface Co2View {
  status: string | null;
  value: number | null;
  unit: string | null;
  reason: string | null;
  official_indicator: boolean | null;
}

export interface CanonicalImpact {
  run_id: string | null;
  baseline_run_id: string | null;
  compatible: boolean | null;
  compatibility_label: string | null;
  cards: CanonicalSdgCard[];
  distribution: FieldChangeRow[];
  field_change_summary: FieldChangeSummaryView;
  co2: Co2View;
}

function rec(v: unknown): Record<string, unknown> | null {
  return !!v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function statusOf(v: unknown): MetricStatus | null {
  return typeof v === "string" && STATUSES.has(v as MetricStatus) ? (v as MetricStatus) : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function integer(v: unknown): number | null {
  return typeof v === "number" && Number.isInteger(v) ? v : null;
}

function text(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function flag(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null;
}

function texts(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function formulasOf(v: unknown): Record<string, string> {
  const o = rec(v);
  if (!o) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(o)) {
    if (typeof value === "string" && value.length > 0) out[key] = value;
  }
  return out;
}

export function unitLabel(unit: string): string {
  if (!unit) return "not returned";
  if (unit === "m3" || unit === "m³") return "m³";
  if (unit === "kg/m3" || unit === "kg m-3" || unit === "kg/m³") return "kg/m³";
  return unit;
}

export function termAsMetric(term: SdgTerm): MetricValue {
  return {
    metric_id: term.metric_id ?? term.label,
    definition_id: term.definition_id ?? "",
    run_id: term.run_id ?? "",
    value: term.status === "available" ? term.value : null,
    unit: term.unit,
    status: term.status,
    reason: term.reason,
    evidence_ids: term.evidence_ids,
    crop: null,
    field_id: null,
    label: term.label,
    formula: term.formula ?? undefined,
  };
}

/** A stored number is plotted only when the server marked that row available. */
export function plottedNumber(status: MetricStatus | null, value: number | null): number | null {
  if (status !== "available" || value === null) return null;
  return value;
}

function readTerm(v: unknown): SdgTerm | null {
  const o = rec(v);
  if (!o) return null;
  const status = statusOf(o.status);
  const role = typeof o.role === "string" && ROLES.has(o.role) ? (o.role as SdgTerm["role"]) : null;
  const label = text(o.label);
  if (!status || !role || !label || typeof o.unit !== "string") return null;
  return {
    role,
    label,
    metric_id: text(o.metric_id),
    definition_id: text(o.definition_id),
    value: num(o.value),
    unit: o.unit,
    status,
    run_id: text(o.run_id),
    reason: text(o.reason),
    formula: text(o.formula),
    evidence_ids: texts(o.evidence_ids),
  };
}

function readMetric(v: unknown): MetricValue | null {
  const o = rec(v);
  const metricId = text(o?.metric_id);
  const status = statusOf(o?.status);
  if (!o || !metricId || !status || typeof o.unit !== "string") return null;
  return {
    metric_id: metricId,
    definition_id: text(o.definition_id) ?? "",
    run_id: text(o.run_id) ?? "",
    value: status === "available" ? num(o.value) : null,
    unit: o.unit,
    status,
    reason: text(o.reason),
    evidence_ids: texts(o.evidence_ids),
    crop: text(o.crop),
    field_id: text(o.field_id),
    label: text(o.label) ?? undefined,
    formula: text(o.formula) ?? undefined,
  };
}

function missingCard(card: string): CanonicalSdgCard {
  return {
    card,
    missing: true,
    official_target_text: null,
    target_url: null,
    official_indicator: null,
    interpretation: null,
    status: null,
    reason: null,
    formula: null,
    formulas: {},
    numerator: null,
    denominator: null,
    difference_from_typical: null,
    metrics: [],
    values: [],
    limitations: [],
    run_id: null,
    baseline_run_id: null,
    run_ids: [],
    source_records: [],
    crop: null,
  };
}

function readCard(v: unknown): CanonicalSdgCard | null {
  const o = rec(v);
  const card = text(o?.card);
  if (!o || !card) return null;
  return {
    card,
    missing: false,
    official_target_text: text(o.official_target_text),
    target_url: text(o.target_url),
    official_indicator: flag(o.official_indicator),
    interpretation: text(o.interpretation),
    status: statusOf(o.status),
    reason: text(o.reason),
    formula: text(o.formula),
    formulas: formulasOf(o.formulas),
    numerator: readTerm(o.numerator),
    denominator: readTerm(o.denominator),
    difference_from_typical: readTerm(o.difference_from_typical),
    metrics: texts(o.metrics),
    values: Array.isArray(o.values) ? o.values.map(readMetric).filter((m): m is MetricValue => !!m) : [],
    limitations: texts(o.limitations),
    run_id: text(o.run_id),
    baseline_run_id: text(o.baseline_run_id),
    run_ids: texts(o.run_ids),
    source_records: texts(o.source_records),
    crop: text(o.crop),
  };
}

function readChange(v: unknown): FieldChangeRow | null {
  const o = rec(v);
  const fieldId = text(o?.field_id);
  if (!o || !fieldId) return null;
  return {
    field_id: fieldId,
    production_kg: num(o.production_kg),
    baseline_production_kg: num(o.baseline_production_kg),
    delta_kg: num(o.delta_kg),
    unit: typeof o.unit === "string" ? o.unit : "",
    status: statusOf(o.status),
    reason: text(o.reason),
    run_id: text(o.run_id),
    baseline_run_id: text(o.baseline_run_id),
    definition_id: text(o.definition_id),
    crop: text(o.crop),
    causal: o.causal === true,
  };
}

function readSummary(v: unknown): FieldChangeSummaryView {
  const o = rec(v);
  if (!o) {
    return {
      reported: false,
      unit: "",
      quantum_kg: null,
      fields_worse_off: null,
      fields_better_off: null,
      fields_unchanged: null,
      fields_not_comparable: null,
    };
  }
  return {
    reported: true,
    unit: typeof o.unit === "string" ? o.unit : "",
    quantum_kg: num(o.quantum_kg),
    fields_worse_off: integer(o.fields_worse_off),
    fields_better_off: integer(o.fields_better_off),
    fields_unchanged: integer(o.fields_unchanged),
    fields_not_comparable: integer(o.fields_not_comparable),
  };
}

function readCo2(v: unknown): Co2View {
  const o = rec(v);
  if (!o) return { status: null, value: null, unit: null, reason: null, official_indicator: null };
  const status = text(o.status);
  return {
    status,
    value: status === "available" ? num(o.value) : null,
    unit: text(o.unit),
    reason: text(o.reason),
    official_indicator: flag(o.official_indicator),
  };
}

export function readCanonicalImpact(raw: object): CanonicalImpact {
  const body = rec(raw) ?? {};
  const parsed = new Map<string, CanonicalSdgCard>();
  if (Array.isArray(body.cards)) {
    for (const item of body.cards) {
      const card = readCard(item);
      if (card) parsed.set(card.card, card);
    }
  }
  const cards: CanonicalSdgCard[] = [];
  for (const id of SDG_CARDS) {
    cards.push(parsed.get(id) ?? missingCard(id));
    parsed.delete(id);
  }
  for (const extra of parsed.values()) cards.push(extra);
  return {
    run_id: text(body.run_id),
    baseline_run_id: text(body.baseline_run_id),
    compatible: flag(body.compatible),
    compatibility_label: text(body.compatibility_label),
    cards,
    distribution: Array.isArray(body.distribution) ? body.distribution.map(readChange).filter((row): row is FieldChangeRow => !!row) : [],
    field_change_summary: readSummary(body.field_change_summary),
    co2: readCo2(body.co2),
  };
}
