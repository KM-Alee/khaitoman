/**
 * Tolerant readers for composed API envelopes. They only rename/locate fields that the
 * server produced; they never compute analytical values. Unknown/missing pieces become
 * `null` so the UI shows "unavailable" instead of inventing data.
 */
import type { Asset, Edge, ImageryRef, MetricValue, NetNode, RunResult } from "./types";

type Json = Record<string, unknown>;
const isObj = (v: unknown): v is Json => !!v && typeof v === "object" && !Array.isArray(v);
const pick = <T = unknown>(o: Json | null | undefined, ...keys: string[]): T | undefined => {
  if (!o) return undefined;
  for (const k of keys) if (o[k] !== undefined && o[k] !== null) return o[k] as T;
  return undefined;
};

export interface GeoRef {
  /** URL to fetch, or inline data. */
  url?: string;
  data?: GeoJSON.FeatureCollection | GeoJSON.Feature | GeoJSON.Geometry;
}

export interface ImageryLayer {
  sceneId: string;
  acquiredAt: string | null;
  url: string;
  corners: [number, number][];
  evidenceId: string | null;
  validFraction: number | null;
  resolutionM: number | null;
}

export interface TerrainLayer {
  url: string;
  bounds: [number, number, number, number];
  encoding: "terrarium" | "mapbox";
  minM: number | null;
  maxM: number | null;
  tileSize: number;
  evidenceId: string | null;
}

export interface MapBundle {
  pilotId: string;
  pilotVersion: string;
  bbox: [number, number, number, number] | null;
  aoi: GeoRef | null;
  fields: GeoRef | null;
  fieldsRaw: GeoRef | null;
  canals: GeoRef | null;
  imagery: ImageryLayer[];
  terrain: TerrainLayer | null;
  nodes: NetNode[];
  edges: Edge[];
  assets: Asset[];
  attribution: string[];
}

export function assetUrl(pilotId: string, version: string, ref: string): string {
  if (/^(https?:)?\/\//.test(ref)) return ref; // will be flagged by the offline audit if remote
  if (ref.startsWith("/")) return ref;
  return `/assets/pilots/${encodeURIComponent(pilotId)}/${encodeURIComponent(version)}/${ref.replace(/^\.\//, "")}`;
}

function geoRef(pilotId: string, version: string, v: unknown): GeoRef | null {
  if (!v) return null;
  if (typeof v === "string") return { url: assetUrl(pilotId, version, v) };
  if (isObj(v)) {
    if (v.type === "FeatureCollection" || v.type === "Feature" || typeof v.type === "string")
      return { data: v as unknown as GeoJSON.FeatureCollection };
    const url = pick<string>(v, "url", "href", "ref", "path");
    if (url) return { url: assetUrl(pilotId, version, url) };
    const data = pick<GeoJSON.FeatureCollection>(v, "data", "geojson");
    if (data) return { data };
  }
  return null;
}

export function readMapBundle(raw: unknown, pilotId: string, version: string): MapBundle {
  const o = isObj(raw) ? raw : {};
  const layers = isObj(o.layers) ? (o.layers as Json) : o;
  const geo = isObj(o.geojson) ? (o.geojson as Json) : layers;
  const network = isObj(o.network) ? (o.network as Json) : isObj(o.graph) ? (o.graph as Json) : o;

  const imageryRaw = (pick<unknown[]>(o, "imagery", "images", "scenes") ?? []) as unknown[];
  const imagery: ImageryLayer[] = imageryRaw.filter(isObj).map((im) => {
    const r = im as Partial<ImageryRef> & Json;
    const url = pick<string>(r, "url", "display_image_url", "display_image_ref", "href") ?? "";
    const corners = (pick<[number, number][]>(r, "corners", "display_corners_wgs84", "coordinates") ?? []) as [
      number,
      number,
    ][];
    return {
      sceneId: String(pick(r, "scene_id", "id") ?? "scene"),
      acquiredAt: (pick<string>(r, "acquired_at", "datetime") ?? null) as string | null,
      url: url ? assetUrl(pilotId, version, url) : "",
      corners,
      evidenceId: (pick<string>(r, "evidence_id") ?? null) as string | null,
      validFraction: (pick<number>(r, "aoi_valid_fraction", "valid_fraction") ?? null) as number | null,
      resolutionM: (pick<number>(r, "resolution_m") ?? null) as number | null,
    };
  });

  const t = pick<Json>(o, "terrain", "dem");
  let terrain: TerrainLayer | null = null;
  if (isObj(t)) {
    const url = pick<string>(t, "url", "dem_url", "ref", "png", "href");
    const bounds = pick<[number, number, number, number]>(t, "bounds", "bbox");
    if (url && bounds && bounds.length === 4) {
      terrain = {
        url: assetUrl(pilotId, version, url),
        bounds,
        encoding: (pick<string>(t, "encoding") === "mapbox" ? "mapbox" : "terrarium") as "terrarium" | "mapbox",
        minM: (pick<number>(t, "min_m", "min_elevation_m", "min") ?? null) as number | null,
        maxM: (pick<number>(t, "max_m", "max_elevation_m", "max") ?? null) as number | null,
        tileSize: (pick<number>(t, "tile_size", "tileSize") ?? 256) as number,
        evidenceId: (pick<string>(t, "evidence_id") ?? null) as string | null,
      };
    }
  }

  return {
    pilotId: String(pick(o, "pilot_id") ?? pilotId),
    pilotVersion: String(pick(o, "pilot_version") ?? version),
    bbox: (pick<[number, number, number, number]>(o, "aoi_bbox", "bbox") ?? null) as MapBundle["bbox"],
    aoi: geoRef(pilotId, version, pick(geo, "aoi", "aoi_url", "aoi_geojson", "aoi_geojson_ref")),
    fields: geoRef(pilotId, version, pick(geo, "fields", "fields_url", "fields_geojson", "fields_ref")),
    fieldsRaw: geoRef(pilotId, version, pick(geo, "fields_raw", "fields_raw_url", "raw_fields", "fields_raw_ref")),
    canals: geoRef(pilotId, version, pick(geo, "canals", "canals_url", "canals_geojson", "canals_ref")),
    imagery,
    terrain,
    nodes: ((pick<NetNode[]>(network, "nodes") ?? []) as NetNode[]).filter(isObj),
    edges: ((pick<Edge[]>(network, "edges") ?? []) as Edge[]).filter(isObj),
    assets: ((pick<Asset[]>(o, "assets") ?? []) as Asset[]).filter(isObj),
    attribution: ((pick<string[]>(o, "attribution", "attributions") ?? []) as string[]).filter(
      (s) => typeof s === "string",
    ),
  };
}

/* ---------------------------------------------------------------- run metrics */

export function runMetrics(run: RunResult | null | undefined): MetricValue[] {
  if (!run) return [];
  const m = (run as unknown as Json).metrics;
  if (Array.isArray(m)) return m.filter(isObj) as unknown as MetricValue[];
  if (isObj(m)) return Object.values(m).filter(isObj) as unknown as MetricValue[];
  return [];
}

/** Find a run-level (field_id null) metric by definition id or metric id suffix. */
export function findMetric(metrics: MetricValue[], ...ids: string[]): MetricValue | null {
  for (const id of ids) {
    const hit =
      metrics.find((m) => !m.field_id && (m.definition_id === id || m.metric_id === id)) ??
      metrics.find((m) => !m.field_id && (m.metric_id.endsWith(`:${id}`) || m.metric_id.endsWith(`/${id}`)));
    if (hit) return hit;
  }
  return null;
}

/** Per-field metrics for a definition: field_id → MetricValue. */
export function fieldMetricMap(metrics: MetricValue[], ...ids: string[]): Map<string, MetricValue> {
  const out = new Map<string, MetricValue>();
  for (const m of metrics) {
    if (!m.field_id) continue;
    if (ids.includes(m.definition_id) || ids.some((id) => m.metric_id.endsWith(`:${id}`))) out.set(m.field_id, m);
  }
  return out;
}

/* ---------------------------------------------------------------- timeline */

export interface SeriesDef {
  id: string;
  label: string;
  unit: string;
  kind: string; // water | crop | weather | storage | other
  values: (number | null)[];
  definition?: string | null;
  basis?: string | null;
}

export interface Timeline {
  runId: string;
  fieldId: string | null;
  dates: string[];
  series: SeriesDef[];
  /** Network-wide per-date edge delivery (m³/day) when supplied. */
  edgeFlows: Record<string, (number | null)[]>;
  /** Pond inventory per date when supplied. */
  ponds: Record<string, { inventory: (number | null)[]; capacity: number | null }>;
  markers: { date: string; label: string; kind: string }[];
  harvest: { date: string | null; yieldKgHa: number | null } | null;
}

export function readTimeline(raw: unknown, runId: string, fieldId: string | null): Timeline {
  const o = isObj(raw) ? raw : {};
  const dates = ((pick<string[]>(o, "dates", "date", "index") ?? []) as string[]).map(String);
  let series: SeriesDef[] = [];
  const s = pick<unknown>(o, "series", "tracks");
  if (Array.isArray(s)) {
    series = s.filter(isObj).map((x) => ({
      id: String(pick(x, "series_id", "id", "name") ?? "series"),
      label: String(pick(x, "label", "title", "series_id", "id") ?? "Series"),
      unit: String(pick(x, "unit", "units") ?? ""),
      kind: String(pick(x, "kind", "group", "category") ?? "other"),
      values: ((pick<unknown[]>(x, "values", "data") ?? []) as unknown[]).map((v) =>
        typeof v === "number" && Number.isFinite(v) ? v : null,
      ),
      definition: (pick<string>(x, "definition", "description") ?? null) as string | null,
      basis: (pick<string>(x, "basis", "aggregation") ?? null) as string | null,
    }));
  } else if (isObj(s)) {
    series = Object.entries(s).map(([id, x]) => {
      const xo = isObj(x) ? x : { values: x };
      return {
        id,
        label: String(pick(xo, "label") ?? id),
        unit: String(pick(xo, "unit") ?? ""),
        kind: String(pick(xo, "kind") ?? "other"),
        values: ((pick<unknown[]>(xo, "values") ?? []) as unknown[]).map((v) =>
          typeof v === "number" && Number.isFinite(v) ? v : null,
        ),
      };
    });
  }
  const net = isObj(o.network) ? (o.network as Json) : o;
  const edgeFlows: Timeline["edgeFlows"] = {};
  const ef = pick<unknown>(net, "edge_flows", "edges", "edge_delivered_m3");
  if (isObj(ef)) for (const [k, v] of Object.entries(ef)) if (Array.isArray(v)) edgeFlows[k] = v.map(numOrNull);
  if (Array.isArray(ef))
    for (const row of ef.filter(isObj)) {
      const id = String(pick(row, "edge_id") ?? "");
      const vals = pick<unknown[]>(row, "values", "delivered_m3");
      if (id && Array.isArray(vals)) edgeFlows[id] = vals.map(numOrNull);
    }
  const ponds: Timeline["ponds"] = {};
  const pd = pick<unknown>(net, "ponds", "pond_inventory");
  if (isObj(pd))
    for (const [k, v] of Object.entries(pd)) {
      if (Array.isArray(v)) ponds[k] = { inventory: v.map(numOrNull), capacity: null };
      else if (isObj(v))
        ponds[k] = {
          inventory: ((pick<unknown[]>(v, "inventory_m3", "inventory", "values") ?? []) as unknown[]).map(numOrNull),
          capacity: (pick<number>(v, "capacity_m3", "usable_capacity_m3") ?? null) as number | null,
        };
    }
  if (Array.isArray(pd))
    for (const row of pd.filter(isObj)) {
      const id = String(pick(row, "asset_id") ?? "");
      if (id)
        ponds[id] = {
          inventory: ((pick<unknown[]>(row, "inventory_m3", "values") ?? []) as unknown[]).map(numOrNull),
          capacity: (pick<number>(row, "capacity_m3") ?? null) as number | null,
        };
    }
  const markers = ((pick<unknown[]>(o, "markers", "stages", "events") ?? []) as unknown[]).filter(isObj).map((m) => ({
    date: String(pick(m, "date") ?? ""),
    label: String(pick(m, "label", "stage", "name") ?? ""),
    kind: String(pick(m, "kind", "type") ?? "stage"),
  }));
  const h = pick<Json>(o, "harvest");
  return {
    runId: String(pick(o, "run_id") ?? runId),
    fieldId: (pick<string>(o, "field_id") ?? fieldId) as string | null,
    dates,
    series,
    edgeFlows,
    ponds,
    markers,
    harvest: isObj(h)
      ? {
          date: (pick<string>(h, "date") ?? null) as string | null,
          yieldKgHa: (pick<number>(h, "yield_kg_ha") ?? null) as number | null,
        }
      : null,
  };
}

function numOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Index of the date in `dates` nearest at or before `iso`; -1 when out of range. */
export function dateIndex(dates: string[], iso: string | null | undefined): number {
  if (!iso || !dates.length) return -1;
  const target = iso.slice(0, 10);
  let lo = 0;
  let hi = dates.length - 1;
  if (target < dates[0].slice(0, 10)) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (dates[mid].slice(0, 10) <= target) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
