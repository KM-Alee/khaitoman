/**
 * Pure wizard helpers: map the server's intake state onto the PRD §5.3 stepper, parse
 * imported GeoJSON, build review bodies and read conflicts. No metric is derived here;
 * every number shown in the wizard is read from an API record.
 */
import { useCallback, useRef } from "react";
import { ApiError } from "@/lib/api/client";
import type { LngLat } from "@/components/map/geo";
import type { FieldEdit, IntakeView, NetworkReview, ReviewBody } from "./onboardingApi";

export const STEPS = [
  { key: "aoi", label: "Area of interest" },
  { key: "sources", label: "Sources" },
  { key: "fields", label: "Imagery & fields" },
  { key: "graph", label: "Operational graph" },
  { key: "params", label: "Crop, soil, rights, assets" },
  { key: "validation", label: "Validation" },
  { key: "publish", label: "Publish" },
] as const;
export type StepKey = (typeof STEPS)[number]["key"];

export interface StepStatus {
  current: StepKey;
  done: Set<StepKey>;
}

const PROCESSING = new Set(["created", "queued", "acquired_raw", "processed", "awaiting_inference", "failed", "cancelled"]);

/** Stepper position from the server record (never from elapsed time). */
export function stepStatus(view: IntakeView | undefined, draft: { closed: boolean }): StepStatus {
  if (!view) return { current: draft.closed ? "sources" : "aoi", done: new Set(draft.closed ? ["aoi"] : []) };
  const done = new Set<StepKey>(["aoi", "sources"]);
  const state = String(view.state);
  const network = !!view.review?.network?.acknowledged;
  const publishBlockers = view.validation.publish_blockers ?? [];
  if (state === "published") {
    STEPS.forEach((s) => done.add(s.key));
    return { current: "publish", done };
  }
  if (PROCESSING.has(state)) return { current: "fields", done };
  if (view.review_version > 0) done.add("fields");
  if (network) done.add("graph");
  if (state === "needs_review") {
    return { current: view.review_version === 0 ? "fields" : network ? "validation" : "graph", done };
  }
  if (state === "reviewed" || state === "validated") {
    done.add("fields");
    done.add("params");
    if (publishBlockers.length === 0 && view.validation.blockers.length === 0) {
      done.add("validation");
      return { current: "publish", done };
    }
    return { current: network ? "validation" : "graph", done };
  }
  return { current: "fields", done };
}

/** Prefill the next immutable version name, e.g. reviewed-v2 → reviewed-v3. The server still decides. */
export function nextPilotVersion(versions: readonly string[] | undefined): string {
  let max = 0;
  for (const v of versions ?? []) {
    const m = /^reviewed-v(\d+)$/.exec(v);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `reviewed-v${max + 1}`;
}

/** Accepts a Polygon, a Feature, or a one-feature FeatureCollection. Returns the open ring. */
export function parsePolygon(text: string): LngLat[] {
  let g: unknown;
  try {
    g = JSON.parse(text);
  } catch {
    throw new Error("Not valid JSON.");
  }
  const obj = g as { type?: string; features?: { geometry?: unknown }[]; geometry?: unknown };
  let geom: unknown = obj;
  if (obj?.type === "FeatureCollection") {
    if (!Array.isArray(obj.features) || obj.features.length !== 1) throw new Error("A FeatureCollection must hold exactly one polygon feature.");
    geom = obj.features[0]?.geometry;
  } else if (obj?.type === "Feature") geom = obj.geometry;
  const p = geom as { type?: string; coordinates?: unknown };
  if (p?.type !== "Polygon" || !Array.isArray(p.coordinates) || !Array.isArray(p.coordinates[0])) {
    throw new Error("Expected a single GeoJSON Polygon (MultiPolygon is not accepted).");
  }
  const ring = (p.coordinates[0] as unknown[]).map((c) => {
    if (!Array.isArray(c) || c.length < 2 || !c.slice(0, 2).every((n) => typeof n === "number" && Number.isFinite(n))) {
      throw new Error("Each position must be [longitude, latitude] numbers.");
    }
    return [c[0], c[1]] as LngLat;
  });
  const open = ring.length > 1 && sameLngLat(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
  if (open.length < 3) throw new Error("A polygon needs at least three distinct vertices.");
  return open;
}

const sameLngLat = (a: LngLat, b: LngLat) => a[0] === b[0] && a[1] === b[1];

export function ringToPolygon(vertices: LngLat[]): GeoJSON.Polygon {
  return { type: "Polygon", coordinates: [[...vertices, vertices[0]]] };
}

/** True when the drawn ring is exactly the package polygon (the server requires equality). */
export function sameRing(vertices: LngLat[], polygon: GeoJSON.Polygon | null | undefined): boolean {
  if (!polygon) return false;
  const ring = polygon.coordinates[0] as LngLat[];
  const open = ring.length > 1 && sameLngLat(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
  return open.length === vertices.length && open.every((p, i) => sameLngLat(p, vertices[i]));
}

export function openRing(polygon: GeoJSON.Polygon): LngLat[] {
  const ring = polygon.coordinates[0] as LngLat[];
  return ring.length > 1 && sameLngLat(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1).map((p) => [p[0], p[1]] as LngLat) : ring;
}

export interface ReviewDraft {
  reviewer: string;
  fieldEdits: FieldEdit[];
  sourceCanal: string;
  capacity: string;
  roster: NetworkReview["roster_basis"];
  acknowledged: boolean;
  rules: Record<string, string>;
}

/** Review-rule knobs the server's ReviewConfig accepts (numbers only). */
export const RULE_KEYS = [
  { key: "min_area_m2", label: "Minimum field area", unit: "m²" },
  { key: "max_area_m2", label: "Maximum field area", unit: "m²" },
  { key: "min_width_m", label: "Minimum width", unit: "m" },
  { key: "min_compactness", label: "Minimum compactness", unit: "0–1" },
  { key: "min_rectangularity", label: "Minimum rectangularity", unit: "0–1" },
] as const;

export function draftFromView(view: IntakeView): ReviewDraft {
  const r = view.review;
  const cfg = view.review_summary?.config ?? {};
  const overrides = r?.review_config ?? {};
  const rules: Record<string, string> = {};
  for (const { key } of RULE_KEYS) {
    const v = overrides[key] ?? cfg[key];
    rules[key] = typeof v === "number" ? String(v) : "";
  }
  return {
    reviewer: r?.reviewer ?? "",
    fieldEdits: (r?.field_edits ?? []).map((e) => ({ ...e })),
    sourceCanal: r?.network?.source_feature_id ?? r?.parent_canal_feature_id ?? view.inference?.parent_canal_feature_id ?? "",
    capacity: r?.network ? String(r.network.capacity_m3_s) : "",
    roster: r?.network?.roster_basis ?? "declared_cca",
    acknowledged: !!r?.network?.acknowledged,
    rules,
  };
}

/**
 * The PATCH body. The server re-runs review from the raw polygons with exactly these
 * edits (it does not merge earlier versions), so the draft always carries the full set.
 */
export function buildReviewBody(draft: ReviewDraft, expectedVersion: number, view: IntakeView): ReviewBody {
  const cfg = view.review_summary?.config ?? {};
  const overrides = view.review?.review_config ?? {};
  const rules: Record<string, unknown> = {};
  for (const { key } of RULE_KEYS) {
    const text = draft.rules[key]?.trim();
    if (!text) continue;
    const n = Number(text);
    if (!Number.isFinite(n)) continue;
    // review_config replaces the stored overrides, so keep earlier overrides and add changed rules.
    if (key in overrides || n !== cfg[key]) rules[key] = n;
  }
  const config: Record<string, unknown> = { ...rules };
  if (draft.acknowledged || draft.capacity.trim()) {
    config.network = {
      direction: "downstream",
      source_feature_id: draft.sourceCanal,
      capacity_m3_s: draft.capacity.trim() === "" ? null : Number(draft.capacity),
      roster_basis: draft.roster,
      outlet: "reach_group",
      acknowledged: draft.acknowledged,
    };
  }
  const body: ReviewBody = {
    contract_version: "2.0.0",
    expected_version: expectedVersion,
    field_edits: draft.fieldEdits,
    review_config: config,
  };
  if (draft.reviewer.trim()) body.reviewer = draft.reviewer.trim();
  if (draft.sourceCanal && !config.network) body.parent_canal_feature_id = draft.sourceCanal;
  return body;
}

/** Form-level checks before sending (the server still validates every value). */
export function draftProblems(draft: ReviewDraft): string[] {
  const out: string[] = [];
  for (const { key, label } of RULE_KEYS) {
    const text = draft.rules[key]?.trim();
    if (text && !Number.isFinite(Number(text))) out.push(`${label} must be a number.`);
  }
  if (draft.capacity.trim() && !Number.isFinite(Number(draft.capacity))) out.push("Capacity must be a number in m³/s.");
  if (draft.acknowledged && !draft.sourceCanal) out.push("Choose the source canal before acknowledging the network.");
  if (draft.acknowledged && !draft.capacity.trim()) out.push("Enter the source capacity before acknowledging the network.");
  draft.fieldEdits.forEach((e) => {
    if (!e.reason.trim()) out.push(`Edit for ${e.model_id} needs a reason.`);
  });
  return out;
}

export interface ConflictInfo {
  serverVersion: number | null;
  expectedVersion: number | null;
  detail: string;
}

export function reviewConflict(err: unknown): ConflictInfo | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const diff = ((err.body as { dependency_diff?: Record<string, unknown> } | null)?.dependency_diff ?? {}) as Record<string, unknown>;
  return {
    serverVersion: typeof diff.review_version === "number" ? diff.review_version : null,
    expectedVersion: typeof diff.expected_version === "number" ? diff.expected_version : null,
    detail: err.message,
  };
}

/** Same request body → same Idempotency-Key (safe retry); a changed body gets a new key. */
export function useAttemptKey(prefix: string) {
  const last = useRef<{ body: string; key: string } | null>(null);
  return useCallback(
    (body: unknown) => {
      const text = JSON.stringify(body);
      if (last.current?.body === text) return last.current.key;
      const rnd = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
      last.current = { body: text, key: `${prefix}-${rnd}` };
      return last.current.key;
    },
    [prefix],
  );
}
