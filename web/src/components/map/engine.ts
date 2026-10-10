/**
 * MapEngine: owns one MapLibre instance and updates sources/feature-state in place (T10.3).
 *
 * Deterministic layer order (bottom → top):
 *   background · imagery · hillshade · aoi-mask · aoi-outline · raw-fields · canals (observed)
 *   · edges (declared: solid observed / dashed assumed) · route highlight · flow particles
 *   · fields (2D fill | 3D extrusion) · field outlines · selection cap/outline · assets (3D)
 *
 * All sources are local: package imagery (ImageSource with corner coordinates), a DEM tiled
 * on the client from the package PNG, GeoJSON from /assets. No glyphs/sprites are used —
 * labels are DOM markers — so nothing is fetched from a remote host (AT15).
 */
import { HD_IMAGERY_ATTRIBUTION, HD_IMAGERY_KEY, hdActive, hdImageryTiles, isRejection, markHdRejected, subscribeHd } from "./hdImagery";
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MLMap,
  type MapGeoJSONFeature,
  type ExpressionSpecification,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapBundle } from "@/lib/api/adapters";
import type { Asset, Edge, NetNode } from "@/lib/api/types";
import { canvasReadbackIsTrustworthy, demEncoding, demTileTemplate, demStats } from "./demTiles";
import {
  bboxOf,
  bboxOfCollection,
  centroid,
  lineCoords,
  orientedPath,
  pointAt,
  ringAround,
  toPolyline,
  type LngLat,
  type Polyline,
} from "./geo";
import { cssVar, mix } from "./palette";

export type MapMode = "3d" | "2d";

export interface FieldVisual {
  value: number | null;
  color: string;
  /** 0..1, drives extrusion height */
  norm: number;
}

export interface PondLevel {
  inventory_m3: number | null;
  capacity_m3: number | null;
}

export type EngineEvent =
  | { type: "field-click"; fieldId: string | null }
  | { type: "field-hover"; fieldId: string | null; x: number; y: number }
  | { type: "edge-click"; edgeId: string | null }
  | { type: "edge-hover"; edgeId: string | null; x: number; y: number }
  | { type: "asset-hover"; assetId: string | null; x: number; y: number }
  | { type: "camera" }
  | { type: "ready" };

export interface MapDataArgs {
  bundle: MapBundle;
  fields: GeoJSON.FeatureCollection | null;
  canals: GeoJSON.FeatureCollection | null;
  aoi: GeoJSON.FeatureCollection | null;
  raw: GeoJSON.FeatureCollection | null;
  imageryIndex?: number;
}

export interface EngineOptions {
  reducedMotion: boolean;
  mode: MapMode;
  /** Secondary maps (compare) skip attribution duplication. */
  secondary?: boolean;
}

const MAX_EXTRUDE_M = 30;
const MIN_EXTRUDE_M = 3;
const SRC = {
  imagery: "imagery",
  imageryHd: "imagery-hd",
  dem: "dem",
  demHs: "dem-hs",
  aoi: "aoi",
  mask: "aoi-mask",
  raw: "fields-raw",
  canals: "canals",
  edges: "edges",
  route: "route",
  particles: "particles",
  fields: "fields",
  assets: "assets-3d",
} as const;

interface EdgeGeom {
  edge: Edge;
  path: Polyline;
  assumed: boolean;
}

const isDark = () => document.documentElement.dataset.theme === "dark";

/** Esri imagery is far crisper and greener than Sentinel-2: mute it so result colours read first. */
function hdPaint(dark: boolean) {
  return { "raster-opacity": 1, "raster-saturation": dark ? -0.42 : -0.28, "raster-contrast": dark ? 0.06 : 0.02, "raster-brightness-max": dark ? 0.72 : 0.9, "raster-brightness-min": 0 };
}
function parcelLineOpacity(hd: boolean): ExpressionSpecification {
  const k = hd ? 0.6 : 1;
  return ["interpolate", ["linear"], ["zoom"], 12.5, 0.12 * k, 14.5, 0.42 * k, 16, 0.55 * k];
}

function bboxOfCorners(c: LngLat[], pad = 0.01): [number, number, number, number] {
  const xs = c.map((p) => p[0]);
  const ys = c.map((p) => p[1]);
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

const imageryCache = new Map<string, Promise<ImageBitmap>>();
function decodeImagery(url: string): Promise<ImageBitmap> {
  let p = imageryCache.get(url);
  if (!p) {
    p = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`imagery ${r.status}`);
        return r.blob();
      })
      .then((b) => createImageBitmap(b));
    p.catch(() => imageryCache.delete(url));
    imageryCache.set(url, p);
  }
  return p;
}

/**
 * Display-only enhancement of the 10 m scene: 4× upsampling with high-quality smoothing and
 * a mild unsharp mask, so field edges read as edges instead of a bilinear smear when the
 * camera is close. Pixels are never used analytically; the source scene is untouched.
 */
const displayCache = new Map<string, HTMLCanvasElement>();
function displayCanvas(url: string, bitmap: ImageBitmap): HTMLCanvasElement {
  const hit = displayCache.get(url);
  if (hit) {
    const c = document.createElement("canvas");
    c.width = hit.width;
    c.height = hit.height;
    c.getContext("2d")!.drawImage(hit, 0, 0);
    return c;
  }
  const scale = Math.max(1, Math.min(4, Math.floor(2048 / Math.max(bitmap.width, bitmap.height))));
  const w = bitmap.width * scale;
  const h = bitmap.height * scale;
  const out = document.createElement("canvas");
  out.width = w;
  out.height = h;
  const ctx = out.getContext("2d", { willReadFrequently: true })!;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, 0, 0, w, h);
  try {
    const blur = document.createElement("canvas");
    blur.width = w;
    blur.height = h;
    const bctx = blur.getContext("2d", { willReadFrequently: true })!;
    bctx.filter = `blur(${(scale * 0.7).toFixed(1)}px)`;
    bctx.drawImage(out, 0, 0);
    const a = ctx.getImageData(0, 0, w, h);
    const b = bctx.getImageData(0, 0, w, h).data;
    const d = a.data;
    const amount = 0.85;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue;
      d[i] = d[i] + amount * (d[i] - b[i]);
      d[i + 1] = d[i + 1] + amount * (d[i + 1] - b[i + 1]);
      d[i + 2] = d[i + 2] + amount * (d[i + 2] - b[i + 2]);
    }
    ctx.putImageData(a, 0, 0);
  } catch {
    // Canvas filters or readback unavailable: the smooth upsample alone is still an improvement.
  }
  displayCache.set(url, out);
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  c.getContext("2d")!.drawImage(out, 0, 0);
  return c;
}

export class MapEngine {
  readonly map: MLMap;
  private opts: EngineOptions;
  private listeners = new Set<(e: EngineEvent) => void>();
  private loaded: Promise<void>;
  private bundle: MapBundle | null = null;
  private fields: GeoJSON.FeatureCollection | null = null;
  private fieldOrder: string[] = [];
  private fieldCentroid = new Map<string, LngLat>();
  private fieldBBox = new Map<string, [number, number, number, number]>();
  private fieldLabel = new Map<string, string>();
  private visuals = new Map<string, FieldVisual>();
  private selected: string | null = null;
  private hovered: string | null = null;
  private edges: EdgeGeom[] = [];
  private flows = new Map<string, number>();
  private flowMax = 0;
  private ponds = new Map<string, PondLevel>();
  private routeEdgeIds: string[] = [];
  private highlightIds: Set<string> | null = null;
  private raf = 0;
  private orbitRaf = 0;
  private particlePhase = 0;
  private lastFrame = 0;
  private selMarker: maplibregl.Marker | null = null;
  private terrainExaggeration = 1;
  private terrainOn = false;
  private wantTerrain = true;
  private destroyed = false;
  private syncing = false;
  private flowEnabled = true;
  private imageryVisible = true;
  private hdVisible = true;
  private offHd: () => void = () => {};
  private rawVisible = false;
  private rawOpacity = 0.95;
  private parcelsVisible = true;
  private dataKey = "";
  private dimAmount = 0.42;
  private dataQueue: Promise<void> = Promise.resolve();

  constructor(container: HTMLElement, opts: EngineOptions) {
    this.opts = opts;
    const style: StyleSpecification = {
      version: 8,
      sources: {},
      layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--map-bg", "#dfe3da") } }],
    };
    this.map = new maplibregl.Map({
      container,
      style,
      center: [72.5, 30.8],
      zoom: 12,
      pitch: 0,
      maxPitch: 72,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      attributionControl: opts.secondary && !hdActive() ? false : { compact: true },
      canvasContextAttributes: { antialias: true },
      fadeDuration: 0,
      dragRotate: true,
      pitchWithRotate: true,
      cancelPendingTileRequestsWhileZooming: true,
    });
    this.map.getCanvas().setAttribute("aria-label", "Pilot map. Use [ and ] to move between fields, Enter to select, Escape to clear.");
    // A rejected/expired Esri key: drop the HD layer everywhere; Sentinel-2 underneath remains.
    this.map.on("error", (e) => {
      const ev = e as unknown as { sourceId?: string; error?: { status?: number } };
      if (ev.sourceId === SRC.imageryHd && isRejection(ev.error?.status)) markHdRejected();
    });
    this.offHd = subscribeHd(() => this.dropHd());
    this.loaded = new Promise((res) => this.map.once("load", () => res()));
    this.loaded.then(() => {
      this.applySky();
      this.bindEvents();
      this.emit({ type: "ready" });
    });
    this.map.on("move", () => {
      if (!this.syncing) this.emit({ type: "camera" });
    });
  }

  /* ------------------------------------------------------------ events */
  on(fn: (e: EngineEvent) => void): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }
  private emit(e: EngineEvent) {
    for (const l of this.listeners) l(e);
  }
  whenReady() {
    return this.loaded;
  }

  private fieldLayerIds() {
    return ["fields-ext", "fields-fill"].filter((id) => this.map.getLayer(id));
  }

  private bindEvents() {
    const m = this.map;
    m.on("mousemove", (e) => {
      const fl = this.fieldLayerIds();
      const hits = fl.length ? m.queryRenderedFeatures(e.point, { layers: fl }) : [];
      const fid = hits.length ? featureFieldId(hits[0]) : null;
      if (fid !== this.hovered) {
        this.setHover(fid);
        this.emit({ type: "field-hover", fieldId: fid, x: e.point.x, y: e.point.y });
      } else if (fid) this.emit({ type: "field-hover", fieldId: fid, x: e.point.x, y: e.point.y });
      let edgeId: string | null = null;
      let assetId: string | null = null;
      if (!fid) {
        const el = ["edges-hit"].filter((id) => m.getLayer(id));
        const eh = el.length ? m.queryRenderedFeatures(e.point, { layers: el }) : [];
        edgeId = eh.length ? String(eh[0].properties?.edge_id ?? "") || null : null;
        this.emit({ type: "edge-hover", edgeId, x: e.point.x, y: e.point.y });
        const al = ["assets-ext"].filter((id) => m.getLayer(id));
        const ah = al.length ? m.queryRenderedFeatures(e.point, { layers: al }) : [];
        assetId = ah.length ? String(ah[0].properties?.asset_id ?? "") || null : null;
        this.emit({ type: "asset-hover", assetId, x: e.point.x, y: e.point.y });
      }
      m.getCanvas().style.cursor = fid || edgeId || assetId ? "pointer" : "";
    });
    m.on("mouseout", () => {
      this.setHover(null);
      this.emit({ type: "field-hover", fieldId: null, x: 0, y: 0 });
      this.emit({ type: "edge-hover", edgeId: null, x: 0, y: 0 });
    });
    m.on("click", (e) => {
      const fl = this.fieldLayerIds();
      const hits = fl.length ? m.queryRenderedFeatures(e.point, { layers: fl }) : [];
      if (hits.length) {
        this.emit({ type: "field-click", fieldId: featureFieldId(hits[0]) });
        return;
      }
      const eh = m.getLayer("edges-hit") ? m.queryRenderedFeatures(e.point, { layers: ["edges-hit"] }) : [];
      if (eh.length) {
        this.emit({ type: "edge-click", edgeId: String(eh[0].properties?.edge_id ?? "") || null });
        return;
      }
      this.emit({ type: "field-click", fieldId: null });
    });
  }

  /* ------------------------------------------------------------ data */
  /** Serialised: overlapping calls (e.g. GeoJSON arriving in pieces) never interleave layer rebuilds. */
  setData(args: MapDataArgs): Promise<void> {
    this.dataQueue = this.dataQueue.then(() => this.applyData(args)).catch((e) => console.warn("map data", e));
    return this.dataQueue;
  }

  private async applyData(args: MapDataArgs) {
    await this.loaded;
    if (this.destroyed) return;
    const key = `${args.bundle.pilotId}@${args.bundle.pilotVersion}|${args.fields?.features.length ?? 0}|${args.canals?.features.length ?? 0}|${args.aoi ? 1 : 0}|${args.raw ? 1 : 0}|${args.imageryIndex ?? 0}`;
    if (key === this.dataKey) return;
    const pilotChanged = this.bundle?.pilotId !== args.bundle.pilotId || this.bundle?.pilotVersion !== args.bundle.pilotVersion;
    this.dataKey = key;
    this.bundle = args.bundle;
    this.clearLayers();
    const m = this.map;
    const ink = cssVar("--ink", "#172b2a");
    const water = cssVar("--water", "#087f8c");
    const surface = cssVar("--surface", "#ffffff");

    // --- normalise fields
    const fields: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: (args.fields?.features ?? []).map((f) => {
        const id = String(f.properties?.field_id ?? f.id ?? "");
        return { ...f, id, properties: { ...(f.properties ?? {}), field_id: id } };
      }),
    };
    this.fields = fields;
    this.fieldOrder = [];
    this.fieldCentroid.clear();
    this.fieldBBox.clear();
    this.fieldLabel.clear();
    for (const f of fields.features) {
      const id = String(f.id);
      this.fieldOrder.push(id);
      const c = centroid(f.geometry);
      if (c) this.fieldCentroid.set(id, c);
      const b = bboxOf(f.geometry);
      if (b) this.fieldBBox.set(id, b);
      this.fieldLabel.set(id, String(f.properties?.label ?? id));
    }
    this.fieldOrder.sort((a, b) => {
      // west→east sweep within north→south bands reads naturally for keyboard travel
      const ca = this.fieldCentroid.get(a);
      const cb = this.fieldCentroid.get(b);
      if (!ca || !cb) return a.localeCompare(b);
      return this.fieldLabel.get(a)!.localeCompare(this.fieldLabel.get(b)!, undefined, { numeric: true });
    });

    // --- imagery
    const im = args.bundle.imagery[args.imageryIndex ?? 0] ?? args.bundle.imagery[0];
    if (im && im.url && im.corners.length === 4) {
      // Decoded once per URL and drawn into a per-map canvas: two maps (compare) sharing one
      // image URL otherwise race in MapLibre's image-request queue and the second never loads.
      const coords = im.corners as [LngLat, LngLat, LngLat, LngLat];
      const bitmap = await decodeImagery(im.url).catch(() => null);
      if (this.destroyed || this.dataKey !== key) return;
      if (bitmap) {
        m.addSource(SRC.imagery, { type: "canvas", canvas: displayCanvas(im.url, bitmap), coordinates: coords, animate: false });
      } else {
        m.addSource(SRC.imagery, { type: "image", url: im.url, coordinates: coords });
      }
      m.addLayer({
        id: "imagery",
        type: "raster",
        source: SRC.imagery,
        layout: { visibility: this.imageryVisible ? "visible" : "none" },
        // Muted so server-coloured fields read first; the scene itself is unaltered data.
        paint: { "raster-opacity": 1, "raster-saturation": -0.38, "raster-contrast": 0.04, "raster-brightness-max": 0.9, "raster-fade-duration": 0, "raster-resampling": "linear" },
      });
    }

    // --- high-res display basemap (optional, online)
    if (HD_IMAGERY_KEY && hdActive()) {
      m.addSource(SRC.imageryHd, {
        type: "raster",
        tiles: [hdImageryTiles(HD_IMAGERY_KEY)],
        tileSize: 256,
        maxzoom: 19,
        attribution: HD_IMAGERY_ATTRIBUTION,
        ...(im && im.corners.length === 4 ? { bounds: bboxOfCorners(im.corners as LngLat[], 0.04) } : {}),
      });
      m.addLayer({
        id: "imagery-hd",
        type: "raster",
        source: SRC.imageryHd,
        layout: { visibility: this.imageryVisible && this.hdVisible ? "visible" : "none" },
        paint: { ...hdPaint(isDark()), "raster-fade-duration": 180, "raster-resampling": "linear" },
      });
    }

    // --- terrain (optional)
    const t = args.bundle.terrain;
    if (t && canvasReadbackIsTrustworthy()) {
      try {
        const tiles = demTileTemplate(t.url, t.bounds, t.encoding);
        const stats = await demStats(t.url, t.bounds, t.encoding);
        const enc = await demEncoding(t.url, t.bounds, t.encoding);
        if (this.destroyed) return;
        const relief = Math.max(1, stats.max - stats.min);
        // Flat Punjab plains: exaggerate modestly so canal-scale relief is legible; labelled in the legend.
        this.terrainExaggeration = Math.round(Math.max(1, Math.min(6, 24 / relief)) * 10) / 10;
        const demSrc = { type: "raster-dem" as const, tiles: [tiles], tileSize: 256, ...enc, bounds: t.bounds, minzoom: 8, maxzoom: 12 }; // ~30 m DEM: z12 already oversamples it
        m.addSource(SRC.dem, demSrc);
        m.addSource(SRC.demHs, demSrc);
        m.addLayer({
          id: "hillshade",
          type: "hillshade",
          source: SRC.demHs,
          paint: {
            "hillshade-exaggeration": 0.45,
            "hillshade-shadow-color": mix(ink, "#000000", 0.2),
            "hillshade-highlight-color": "#ffffff",
            "hillshade-accent-color": ink,
            "hillshade-illumination-direction": 315,
          },
        });
      } catch {
        // DEM unreadable → flat map, stated in legend
      }
    }

    // --- AOI mask + outline
    const aoiFC = args.aoi;
    const aoiRing = aoiFC ? firstRing(aoiFC) : null;
    if (aoiFC && aoiRing) {
      m.addSource(SRC.mask, {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "Polygon", coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], aoiRing] },
        },
      });
      m.addLayer({ id: "aoi-mask", type: "fill", source: SRC.mask, paint: { "fill-color": maskColor(), "fill-opacity": 0.42 } });
      m.addSource(SRC.aoi, { type: "geojson", data: aoiFC });
      m.addLayer({
        id: "aoi-outline",
        type: "line",
        source: SRC.aoi,
        paint: { "line-color": surface, "line-width": 1.5, "line-opacity": 0.9, "line-dasharray": [3, 2] },
      });
    }

    // --- raw AI output: every delineated parcel as quiet context, plus the review overlay
    if (args.raw) {
      m.addSource(SRC.raw, { type: "geojson", data: args.raw });
      const dark = document.documentElement.dataset.theme === "dark";
      m.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: SRC.raw,
        layout: { visibility: this.parcelsVisible ? "visible" : "none" },
        paint: { "fill-color": "#ffffff", "fill-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 15, dark ? 0.035 : 0.06] },
      });
      m.addLayer({
        id: "parcels-line",
        type: "line",
        source: SRC.raw,
        layout: { visibility: this.parcelsVisible ? "visible" : "none", "line-join": "round" },
        paint: {
          "line-color": dark ? "#e8f1ee" : "#fffdf5",
          "line-opacity": parcelLineOpacity(this.hdShown()),
          "line-width": ["interpolate", ["linear"], ["zoom"], 13, 0.4, 16, 1.1],
        },
      });
      m.addLayer({
        id: "fields-raw",
        type: "line",
        source: SRC.raw,
        layout: { visibility: this.rawVisible ? "visible" : "none" },
        paint: { "line-color": cssVar("--warning"), "line-width": 1.2, "line-dasharray": [2, 1.5], "line-opacity": this.rawOpacity },
      });
    }

    // --- observed canals
    if (args.canals) {
      m.addSource(SRC.canals, { type: "geojson", data: args.canals });
      m.addLayer({
        id: "canals-casing",
        type: "line",
        source: SRC.canals,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": mix(ink, "#000000", 0.3), "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 7] },
      });
      m.addLayer({
        id: "canals-line",
        type: "line",
        source: SRC.canals,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": mix(water, "#9fe6ec", 0.35), "line-opacity": 0.9, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.2, 16, 3.5] },
      });
    }

    // --- declared network edges
    this.edges = buildEdgeGeoms(args.bundle.nodes, args.bundle.edges, args.canals);
    m.addSource(SRC.edges, { type: "geojson", data: this.edgeFC(), promoteId: "edge_id" });
    m.addLayer({
      id: "edges-observed",
      type: "line",
      source: SRC.edges,
      filter: ["==", ["get", "assumed"], false],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": water,
        "line-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 1, 0.85],
        "line-width": ["+", ["get", "w"], ["case", ["boolean", ["feature-state", "hover"], false], 2, 0]],
      },
    });
    m.addLayer({
      id: "edges-assumed",
      type: "line",
      source: SRC.edges,
      filter: ["==", ["get", "assumed"], true],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: {
        "line-color": mix(water, surface, 0.15),
        "line-opacity": 0.95,
        "line-width": ["+", ["get", "w"], ["case", ["boolean", ["feature-state", "hover"], false], 2, 0]],
        "line-dasharray": [1.6, 1.4],
      },
    });
    m.addLayer({ id: "edges-hit", type: "line", source: SRC.edges, paint: { "line-color": "#000", "line-opacity": 0, "line-width": 14 } });

    // --- route highlight (selected field's declared water path)
    m.addSource(SRC.route, { type: "geojson", data: emptyFC() });
    m.addLayer({
      id: "route-glow",
      type: "line",
      source: SRC.route,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#7ee3ea", "line-width": 10, "line-blur": 6, "line-opacity": 0.75 },
    });
    m.addLayer({
      id: "route-line",
      type: "line",
      source: SRC.route,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.95 },
    });

    // --- flow particles (direction/activity only; legend says so)
    m.addSource(SRC.particles, { type: "geojson", data: emptyFC() });
    m.addLayer({
      id: "particles-glow",
      type: "circle",
      source: SRC.particles,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 7],
        "circle-color": "#8ef0f5",
        "circle-blur": 1,
        "circle-opacity": ["*", 0.55, ["get", "a"]],
        "circle-pitch-alignment": "map",
      },
    });
    m.addLayer({
      id: "particles-core",
      type: "circle",
      source: SRC.particles,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 0.9, 16, 2.4],
        "circle-color": "#f2feff",
        "circle-opacity": ["get", "a"],
        "circle-pitch-alignment": "map",
      },
    });

    // --- fields
    m.addSource(SRC.fields, { type: "geojson", data: fields, promoteId: "field_id" });
    m.addLayer({
      id: "fields-fill",
      type: "fill",
      source: SRC.fields,
      layout: { visibility: this.opts.mode === "2d" || this.opts.reducedMotion ? "visible" : "none" },
      paint: {
        "fill-color": ["to-color", ["coalesce", ["feature-state", "color"], cssVar("--surface-sunken")]],
        "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.9, 0.74],
      },
    });
    m.addLayer({
      id: "fields-ext",
      type: "fill-extrusion",
      source: SRC.fields,
      layout: { visibility: this.opts.mode === "3d" && !this.opts.reducedMotion ? "visible" : "none" },
      paint: {
        "fill-extrusion-color": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          ["to-color", ["coalesce", ["feature-state", "hcolor"], ["feature-state", "color"], "#cccccc"]],
          ["to-color", ["coalesce", ["feature-state", "color"], cssVar("--surface-sunken")]],
        ],
        "fill-extrusion-height": ["coalesce", ["feature-state", "h"], MIN_EXTRUDE_M],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.94,
        "fill-extrusion-vertical-gradient": true,
      },
    });
    m.addLayer({
      id: "fields-outline",
      type: "line",
      source: SRC.fields,
      paint: {
        "line-color": surface,
        "line-opacity": ["case", ["boolean", ["feature-state", "dim"], false], 0.35, 0.85],
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.6, 16, 1.6],
      },
    });
    m.addLayer({
      id: "fields-hover",
      type: "line",
      source: SRC.fields,
      filter: ["==", ["get", "field_id"], ""],
      paint: { "line-color": surface, "line-width": 2.5 },
    });
    m.addLayer({
      id: "fields-sel-glow",
      type: "line",
      source: SRC.fields,
      filter: ["==", ["get", "field_id"], ""],
      paint: { "line-color": "#ffd27a", "line-width": 9, "line-blur": 6, "line-opacity": 0.85 },
    });
    m.addLayer({
      id: "fields-sel-line",
      type: "line",
      source: SRC.fields,
      filter: ["==", ["get", "field_id"], ""],
      paint: { "line-color": "#fff6df", "line-width": 2.6 },
    });
    m.addLayer({
      id: "fields-sel-cap",
      type: "fill-extrusion",
      source: SRC.fields,
      filter: ["==", ["get", "field_id"], ""],
      layout: { visibility: this.opts.mode === "3d" && !this.opts.reducedMotion ? "visible" : "none" },
      paint: {
        "fill-extrusion-color": "#ffe3a3",
        "fill-extrusion-base": ["coalesce", ["feature-state", "h"], MIN_EXTRUDE_M],
        "fill-extrusion-height": ["+", ["coalesce", ["feature-state", "h"], MIN_EXTRUDE_M], 2.2],
        "fill-extrusion-opacity": 0.95,
      },
    });

    // --- assets (3D markers: pond water bodies, pump pillars, outlet posts, source)
    m.addSource(SRC.assets, { type: "geojson", data: this.assetFC() });
    m.addLayer({
      id: "assets-flat",
      type: "fill",
      source: SRC.assets,
      layout: { visibility: this.opts.mode === "2d" || this.opts.reducedMotion ? "visible" : "none" },
      filter: ["!=", ["get", "part"], "rim"],
      paint: { "fill-color": ["get", "color"], "fill-opacity": 0.95, "fill-outline-color": surface },
    });
    m.addLayer({
      id: "assets-ext",
      type: "fill-extrusion",
      source: SRC.assets,
      layout: { visibility: this.opts.mode === "3d" && !this.opts.reducedMotion ? "visible" : "none" },
      paint: {
        "fill-extrusion-color": ["get", "color"],
        "fill-extrusion-height": ["get", "h"],
        "fill-extrusion-base": ["get", "base"],
        "fill-extrusion-opacity": 0.96,
        "fill-extrusion-vertical-gradient": true,
      },
    });

    this.applyTerrain();
    this.applyVisuals();
    this.applySelection();
    this.startFlow();
    if (pilotChanged) this.fitAOI(false);
  }

  private clearLayers() {
    const m = this.map;
    cancelAnimationFrame(this.fieldRaf);
    this.fieldNow.clear();
    for (const l of [...(m.getStyle()?.layers ?? [])]) if (l.id !== "bg") m.removeLayer(l.id);
    if (m.getTerrain()) m.setTerrain(null);
    this.terrainOn = false;
    for (const s of Object.keys(m.getStyle()?.sources ?? {})) m.removeSource(s);
  }

  /* ------------------------------------------------------------ appearance */
  private applySky() {
    const dark = document.documentElement.dataset.theme === "dark";
    try {
      // Low warm sun from the south-west: extrusion walls shade, so block heights read in 3D.
      this.map.setLight({ anchor: "map", color: dark ? "#cfe3e1" : "#fff4e0", intensity: dark ? 0.32 : 0.42, position: [1.4, 215, 38] });
    } catch {
      /* light unsupported */
    }
    try {
      this.map.setSky({
        "sky-color": dark ? "#0b1716" : "#bcd9da",
        "horizon-color": dark ? "#1a2a28" : "#efe9da",
        "fog-color": dark ? "#0e1716" : "#f4f2eb",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.6,
        "fog-ground-blend": 0.35,
        "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 10, 1, 15, 0.2],
      });
    } catch {
      /* sky unsupported */
    }
  }

  refreshTheme() {
    if (!this.map.isStyleLoaded()) return;
    this.map.setPaintProperty("bg", "background-color", cssVar("--map-bg"));
    if (this.map.getLayer("aoi-mask")) this.map.setPaintProperty("aoi-mask", "fill-color", maskColor());
    if (this.map.getLayer("imagery-hd")) for (const [k, v] of Object.entries(hdPaint(isDark()))) this.map.setPaintProperty("imagery-hd", k, v);
    this.applySky();
  }

  setMode(mode: MapMode, reducedMotion: boolean) {
    this.opts = { ...this.opts, mode, reducedMotion };
    const m = this.map;
    const three = mode === "3d" && !reducedMotion;
    const vis = (id: string, on: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    vis("fields-ext", three);
    vis("fields-sel-cap", three);
    vis("assets-ext", three);
    vis("fields-fill", !three);
    vis("assets-flat", !three);
    this.applyTerrain();
    if (!three) m.easeTo({ pitch: 0, bearing: 0, duration: reducedMotion ? 0 : 400 });
    else if (m.getPitch() < 20) m.easeTo({ pitch: 52, bearing: -18, duration: 450 });
    this.startFlow();
  }

  setTerrainEnabled(on: boolean) {
    this.wantTerrain = on;
    this.applyTerrain();
  }

  private applyTerrain() {
    const m = this.map;
    const three = this.opts.mode === "3d" && !this.opts.reducedMotion;
    const should = three && this.wantTerrain && !!m.getSource(SRC.dem);
    if (should && !this.terrainOn) {
      m.setTerrain({ source: SRC.dem, exaggeration: this.terrainExaggeration });
      this.terrainOn = true;
    } else if (!should && this.terrainOn) {
      m.setTerrain(null);
      this.terrainOn = false;
    }
  }

  terrainInfo() {
    return { available: !!this.map.getSource(SRC.dem), on: this.terrainOn, exaggeration: this.terrainExaggeration };
  }

  setImageryVisible(on: boolean) {
    this.imageryVisible = on;
    if (this.map.getLayer("imagery")) this.map.setLayoutProperty("imagery", "visibility", on ? "visible" : "none");
    this.syncHd();
  }
  setHdImageryVisible(on: boolean) {
    this.hdVisible = on;
    this.syncHd();
  }
  private hdShown() {
    return !!this.map.getLayer("imagery-hd") && this.imageryVisible && this.hdVisible;
  }
  private syncHd() {
    if (!this.map.getLayer("imagery-hd")) return;
    const on = this.hdShown();
    this.map.setLayoutProperty("imagery-hd", "visibility", on ? "visible" : "none");
    // Sharp imagery already shows every bund; quieten the parcel web so modeled fields lead.
    if (this.map.getLayer("parcels-line")) this.map.setPaintProperty("parcels-line", "line-opacity", parcelLineOpacity(on));
  }
  private dropHd() {
    if (this.destroyed) return;
    if (this.map.getLayer("imagery-hd")) this.map.removeLayer("imagery-hd");
    if (this.map.getSource(SRC.imageryHd)) this.map.removeSource(SRC.imageryHd);
    if (this.map.getLayer("parcels-line")) this.map.setPaintProperty("parcels-line", "line-opacity", parcelLineOpacity(false));
  }
  setParcelsVisible(on: boolean) {
    this.parcelsVisible = on;
    for (const id of ["parcels-fill", "parcels-line"]) if (this.map.getLayer(id)) this.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }

  /** Fade the raw AI outlines (tour reveal): 1 = as drawn, lower = receding behind the reviewed fields. */
  setRawOpacity(k: number, ms = 0) {
    this.rawOpacity = 0.95 * Math.max(0, Math.min(1, k));
    if (!this.map.getLayer("fields-raw")) return;
    this.map.setPaintProperty("fields-raw", "line-opacity-transition", { duration: ms, delay: 0 });
    this.map.setPaintProperty("fields-raw", "line-opacity", this.rawOpacity);
  }

  setRawVisible(on: boolean) {
    this.rawVisible = on;
    if (this.map.getLayer("fields-raw")) this.map.setLayoutProperty("fields-raw", "visibility", on ? "visible" : "none");
  }

  /** Per-field colour/height from server metric values (presentation only). */
  setFieldVisuals(v: Map<string, FieldVisual>) {
    this.visuals = v;
    this.applyVisuals();
  }

  /** How strongly unselected fields fade when one is selected (replay keeps context visible). */
  setDimAmount(t: number) {
    this.dimAmount = Math.max(0, Math.min(1, t));
    this.applyVisuals();
  }

  /** Emphasise a subset (e.g. frontier portfolio fields); others dim. null clears. */
  setHighlight(ids: string[] | null) {
    this.highlightIds = ids && ids.length ? new Set(ids) : null;
    this.applyVisuals();
  }

  private applyVisuals() {
    const m = this.map;
    if (!m.getSource(SRC.fields)) return;
    const dark = document.documentElement.dataset.theme === "dark";
    // Fields without a result read as pale, low plots in both themes (never black slabs).
    const neutral = dark ? "#8f8a7c" : "#e7e1d1";
    const canvas = cssVar("--canvas", "#f4f2eb");
    const anyFocus = !!this.selected || !!this.highlightIds;
    const targets = new Map<string, { color: string; h: number; dim: boolean; base: string }>();
    for (const id of this.fieldOrder) {
      const v = this.visuals.get(id);
      const base = v?.color ?? neutral;
      const focus = this.highlightIds ? this.highlightIds.has(id) || id === this.selected : !this.selected || id === this.selected;
      const dim = anyFocus && !focus;
      const color = dim ? mix(base, canvas, this.dimAmount) : base;
      const h = v ? MIN_EXTRUDE_M + v.norm * (MAX_EXTRUDE_M - MIN_EXTRUDE_M) : MIN_EXTRUDE_M * 0.6;
      targets.set(id, { color, h, dim, base });
    }
    this.tweenFields(targets);
  }

  /** Eases every field block from its current height/colour to the new one (blocks grow, not jump). */
  private fieldNow = new Map<string, { color: string; h: number }>();
  private fieldRaf = 0;
  private tweenFields(targets: Map<string, { color: string; h: number; dim: boolean; base: string }>) {
    const m = this.map;
    cancelAnimationFrame(this.fieldRaf);
    const from = new Map(this.fieldNow);
    const instant = this.opts.reducedMotion || this.opts.mode === "2d";
    const dur = 520;
    const t0 = performance.now();
    const step = (now: number) => {
      if (this.destroyed || !m.getSource(SRC.fields)) return;
      const k = instant ? 1 : easeOutCubic(Math.min(1, (now - t0) / dur));
      for (const [id, t] of targets) {
        // New blocks rise from the ground in their final colour.
        const f = from.get(id) ?? { h: 0, color: t.color };
        const h = f.h + (t.h - f.h) * k;
        const color = k < 1 ? mix(f.color, t.color, k) : t.color;
        this.fieldNow.set(id, { color, h });
        m.setFeatureState({ source: SRC.fields, id }, { color, hcolor: mix(t.base, "#ffffff", 0.28), h, dim: t.dim });
      }
      if (k < 1) this.fieldRaf = requestAnimationFrame(step);
    };
    if (instant) step(t0);
    else this.fieldRaf = requestAnimationFrame(step);
  }

  /* ------------------------------------------------------------ selection */
  setSelected(fieldId: string | null, opts: { fly?: boolean } = {}) {
    const changed = fieldId !== this.selected;
    this.selected = fieldId && this.fieldCentroid.has(fieldId) ? fieldId : null;
    this.applySelection();
    if (changed) this.applyVisuals();
    if (this.selected && opts.fly !== false && changed) this.flyToField(this.selected);
  }
  getSelected() {
    return this.selected;
  }

  private applySelection() {
    const m = this.map;
    if (!m.getLayer("fields-sel-line")) return;
    const f: maplibregl.FilterSpecification = ["==", ["get", "field_id"], this.selected ?? ""];
    m.setFilter("fields-sel-line", f);
    m.setFilter("fields-sel-glow", f);
    m.setFilter("fields-sel-cap", f);
    this.selMarker?.remove();
    this.selMarker = null;
    if (this.selected) {
      const c = this.fieldCentroid.get(this.selected);
      if (c) {
        const el = document.createElement("div");
        el.className = "map-label";
        el.dataset.kind = "selected";
        el.setAttribute("aria-hidden", "true");
        const v = this.visuals.get(this.selected);
        el.textContent = this.fieldLabel.get(this.selected) ?? this.selected;
        if (v?.value !== undefined && v?.value !== null) el.title = String(v.value);
        this.selMarker = new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat(c).addTo(m);
      }
    }
    this.updateRoute();
  }

  setRoute(edgeIds: string[]) {
    this.routeEdgeIds = edgeIds;
    this.updateRoute();
  }
  private updateRoute() {
    const src = this.map.getSource(SRC.route) as GeoJSONSource | undefined;
    if (!src) return;
    const ids = new Set(this.routeEdgeIds);
    src.setData({
      type: "FeatureCollection",
      features: this.edges
        .filter((e) => ids.has(e.edge.edge_id))
        .map((e) => ({ type: "Feature", properties: { edge_id: e.edge.edge_id }, geometry: { type: "LineString", coordinates: e.path.coords } })),
    });
  }

  private setHover(fid: string | null) {
    const m = this.map;
    if (this.hovered && m.getSource(SRC.fields)) m.setFeatureState({ source: SRC.fields, id: this.hovered }, { hover: false });
    this.hovered = fid;
    if (fid && m.getSource(SRC.fields)) m.setFeatureState({ source: SRC.fields, id: fid }, { hover: true });
    if (m.getLayer("fields-hover")) m.setFilter("fields-hover", ["==", ["get", "field_id"], fid ?? ""]);
  }
  hoverField(fid: string | null) {
    this.setHover(fid);
  }

  fieldIds() {
    return [...this.fieldOrder];
  }
  fieldName(id: string) {
    return this.fieldLabel.get(id) ?? id;
  }
  fieldScreenPoint(id: string): { x: number; y: number } | null {
    const c = this.fieldCentroid.get(id);
    if (!c) return null;
    const p = this.map.project(c);
    return { x: p.x, y: p.y };
  }

  /* ------------------------------------------------------------ network flow */
  /** Delivered volume per edge for the current date (m³/day); empty map = no replay date. */
  setEdgeFlows(flows: Map<string, number> | null) {
    this.flows = flows ?? new Map();
    this.flowMax = Math.max(0, ...[...this.flows.values()].filter(Number.isFinite));
    const src = this.map.getSource(SRC.edges) as GeoJSONSource | undefined;
    src?.setData(this.edgeFC());
    this.startFlow();
  }

  setPondLevels(levels: Map<string, PondLevel> | null) {
    this.ponds = levels ?? new Map();
    const src = this.map.getSource(SRC.assets) as GeoJSONSource | undefined;
    src?.setData(this.assetFC());
  }

  setFlowEnabled(on: boolean) {
    this.flowEnabled = on;
    this.startFlow();
  }

  private edgeFC(): GeoJSON.FeatureCollection {
    const hasFlows = this.flows.size > 0;
    return {
      type: "FeatureCollection",
      features: this.edges.map((e) => {
        const v = this.flows.get(e.edge.edge_id);
        const rel = hasFlows && this.flowMax > 0 && v ? Math.sqrt(v / this.flowMax) : 0;
        const w = hasFlows ? (v && v > 0 ? 1.6 + rel * 5 : 1) : 2.4;
        return {
          type: "Feature",
          id: e.edge.edge_id,
          properties: { edge_id: e.edge.edge_id, assumed: e.assumed, w, v: v ?? 0, reach: e.edge.reach_label ?? "" },
          geometry: { type: "LineString", coordinates: e.path.coords },
        };
      }),
    };
  }

  private assetFC(): GeoJSON.FeatureCollection {
    const b = this.bundle;
    if (!b) return emptyFC();
    const feats: GeoJSON.Feature[] = [];
    const nodeById = new Map(b.nodes.map((n) => [n.node_id, n]));
    const waterC = cssVar("--water", "#087f8c");
    const earth = "#9a8466";
    const pumpC = cssVar("--warning", "#a35b08");
    const ink = cssVar("--ink", "#172b2a");
    // Source and outlets
    for (const n of b.nodes) {
      if (n.kind === "source") {
        feats.push(poly(ringAround([n.lon, n.lat], 16, 6, Math.PI / 6), { part: "node", kind: "source", asset_id: n.node_id, h: 26, base: 0, color: waterC }));
      } else if (n.kind === "outlet") {
        feats.push(poly(ringAround([n.lon, n.lat], 3.5, 4, Math.PI / 4), { part: "node", kind: "outlet", asset_id: n.node_id, h: 7, base: 0, color: ink }));
      }
    }
    for (const a of b.assets) {
      const pos = assetPosition(a, nodeById, this.fieldCentroid);
      if (!pos) continue;
      if (a.kind === "pump") {
        feats.push(poly(ringAround(pos, 7, 6), { part: "body", kind: "pump", asset_id: a.asset_id, h: 18, base: 0, color: a.existing ? pumpC : mix(pumpC, "#ffffff", 0.4) }));
        feats.push(poly(ringAround(pos, 9, 6), { part: "body", kind: "pump-cap", asset_id: a.asset_id, h: 21, base: 18, color: mix(pumpC, "#000000", 0.25) }));
      } else {
        const footprint = a.footprint_m2 ?? a.surface_area_m2 ?? 900;
        const r = Math.sqrt(footprint / Math.PI);
        const level = this.ponds.get(a.asset_id);
        const cap = level?.capacity_m3 ?? a.usable_capacity_m3 ?? null;
        const inv = level?.inventory_m3 ?? (this.ponds.size ? null : a.initial_inventory_m3);
        const frac = cap && inv !== null && inv !== undefined ? Math.max(0, Math.min(1, inv / cap)) : 0;
        const depth = 8; // display depth (m) — legend states it is schematic
        const outer = ringAround(pos, r + 2.5, 56);
        const inner = ringAround(pos, r, 56);
        feats.push({
          type: "Feature",
          properties: { part: "rim", kind: "pond-rim", asset_id: a.asset_id, h: depth + 0.6, base: 0, color: a.existing ? earth : mix(earth, "#ffffff", 0.45) },
          geometry: { type: "Polygon", coordinates: [outer, [...inner].reverse()] },
        });
        if (frac > 0)
          feats.push(poly(inner, { part: "water", kind: "pond-water", asset_id: a.asset_id, h: 0.3 + frac * depth, base: 0, color: mix(waterC, "#5fd6df", 0.25) }));
        else feats.push(poly(inner, { part: "water", kind: "pond-empty", asset_id: a.asset_id, h: 0.25, base: 0, color: mix(earth, "#000000", 0.15) }));
      }
    }
    return { type: "FeatureCollection", features: feats };
  }

  private startFlow() {
    cancelAnimationFrame(this.raf);
    const src = this.map.getSource(SRC.particles) as GeoJSONSource | undefined;
    if (!src) return;
    const animate = this.flowEnabled && !this.opts.reducedMotion;
    const active = this.edges.filter((e) => (this.flows.size ? (this.flows.get(e.edge.edge_id) ?? 0) > 0 : true));
    if (!active.length || !this.flowEnabled) {
      src.setData(emptyFC());
      return;
    }
    const spacing = 70; // metres between particles
    const draw = (ts: number) => {
      if (this.destroyed) return;
      const dt = this.lastFrame ? Math.min(64, ts - this.lastFrame) : 16;
      this.lastFrame = ts;
      this.particlePhase += dt / 1000;
      const feats: GeoJSON.Feature[] = [];
      for (const e of active) {
        const v = this.flows.get(e.edge.edge_id);
        const rel = this.flows.size && this.flowMax > 0 && v ? Math.sqrt(v / this.flowMax) : 0.6;
        const speed = 18 + rel * 60; // m/s on screen — schematic, not hydraulic velocity
        const n = Math.max(2, Math.floor(e.path.length / spacing));
        const off = animate ? (this.particlePhase * speed) % spacing : 0;
        for (let i = 0; i < n; i++) {
          const d = i * spacing + off;
          if (d > e.path.length) break;
          const fadeIn = Math.min(1, d / 40, (e.path.length - d) / 40);
          feats.push({ type: "Feature", properties: { a: Math.max(0, fadeIn) * (e.assumed ? 0.7 : 1) }, geometry: { type: "Point", coordinates: pointAt(e.path, d) } });
        }
      }
      src.setData({ type: "FeatureCollection", features: feats });
      if (animate) this.raf = requestAnimationFrame((t) => setTimeout(() => draw(t), 16));
    };
    this.lastFrame = 0;
    this.raf = requestAnimationFrame(draw);
  }

  /* ------------------------------------------------------------ camera */
  fitAOI(animate = true) {
    // Frame the reviewed fields (the subject), falling back to the AOI box.
    const b = (this.fields?.features.length ? bboxOfCollection(this.fields) : null) ?? this.bundle?.bbox;
    if (!b) return;
    const three = this.opts.mode === "3d" && !this.opts.reducedMotion;
    const cam = this.map.cameraForBounds(b as LngLatBoundsLike, { padding: paddingFor(this.map), bearing: three ? -18 : 0, pitch: three ? 52 : 0 });
    if (!cam) return;
    // cameraForBounds is conservative under pitch (it fits the far edge); nudge in so blocks read.
    const opts = { ...cam, zoom: (cam.zoom ?? 14) + (three ? 0.2 : 0), pitch: three ? 52 : 0, bearing: three ? -18 : 0 };
    if (!animate || this.opts.reducedMotion) this.map.jumpTo(opts);
    else this.map.flyTo({ ...opts, duration: 900, essential: false, curve: 1.3 });
  }

  flyToField(id: string) {
    const b = this.fieldBBox.get(id);
    if (!b) return;
    const three = this.opts.mode === "3d" && !this.opts.reducedMotion;
    const cam = this.map.cameraForBounds(b as LngLatBoundsLike, { padding: paddingFor(this.map, 0.3), maxZoom: this.hdShown() ? 17.4 : this.map.getContainer().clientHeight < 520 ? 15.6 : 16.5, bearing: this.map.getBearing(), pitch: three ? 58 : 0 });
    if (!cam) return;
    // Sub-metre imagery holds up closer in; 10 m Sentinel-2 turns to mush past ~16.
    const zoom = Math.min(this.hdShown() ? 17 : 16.2, (cam.zoom ?? 15) - 0.6);
    const opts = { center: cam.center, zoom, pitch: three ? 58 : 0, bearing: this.map.getBearing() };
    if (this.opts.reducedMotion) this.map.jumpTo(opts);
    else this.map.easeTo({ ...opts, duration: 420, easing: easeOutCubic });
  }

  zoomBy(d: number) {
    this.map.easeTo({ zoom: this.map.getZoom() + d, duration: this.opts.reducedMotion ? 0 : 220 });
  }
  resetNorth() {
    this.map.easeTo({ bearing: 0, duration: this.opts.reducedMotion ? 0 : 300 });
  }

  startOrbit() {
    if (this.opts.reducedMotion) return;
    cancelAnimationFrame(this.orbitRaf);
    let last = 0;
    const step = (ts: number) => {
      if (this.destroyed) return;
      const dt = last ? ts - last : 16;
      last = ts;
      this.map.setBearing(this.map.getBearing() + dt * 0.006);
      this.orbitRaf = requestAnimationFrame(step);
    };
    if (this.map.getPitch() < 40) this.map.easeTo({ pitch: 55, duration: 500 });
    this.orbitRaf = requestAnimationFrame(step);
  }
  stopOrbit() {
    cancelAnimationFrame(this.orbitRaf);
    this.orbitRaf = 0;
  }

  /** Camera sync for paired maps with a re-entrancy guard (T10.3). */
  syncFrom(other: MapEngine) {
    if (this.syncing) return;
    this.syncing = true;
    this.map.jumpTo({ center: other.map.getCenter(), zoom: other.map.getZoom(), bearing: other.map.getBearing(), pitch: other.map.getPitch() });
    this.syncing = false;
  }

  resize() {
    this.map.resize();
  }

  destroy() {
    this.destroyed = true;
    this.offHd();
    cancelAnimationFrame(this.raf);
    cancelAnimationFrame(this.orbitRaf);
    this.selMarker?.remove();
    this.listeners.clear();
    this.map.remove();
  }

  /** Introspection for tests and the layer legend. */
  debugState() {
    const m = this.map;
    return {
      layers: (m.getStyle()?.layers ?? []).map((l) => l.id),
      sources: Object.keys(m.getStyle()?.sources ?? {}),
      fields: this.fieldOrder.length,
      edges: this.edges.length,
      selected: this.selected,
      terrain: this.terrainInfo(),
      pitch: m.getPitch(),
      bearing: m.getBearing(),
      mode: this.opts.mode,
      reducedMotion: this.opts.reducedMotion,
      flows: this.flows.size,
    };
  }
}

/* ---------------------------------------------------------------- helpers */
function maskColor(): string {
  // Outside the pilot AOI: a cool ink veil in light mode, deeper canvas in dark mode.
  return document.documentElement.dataset.theme === "dark" ? cssVar("--canvas", "#0e1716") : mix(cssVar("--ink", "#172b2a"), "#ffffff", 0.35);
}
function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
function poly(ring: LngLat[], props: Record<string, unknown>): GeoJSON.Feature {
  return { type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [ring] } };
}
function featureFieldId(f: MapGeoJSONFeature): string | null {
  const v = f.properties?.field_id ?? f.id;
  return v === undefined || v === null ? null : String(v);
}
function firstRing(fc: GeoJSON.FeatureCollection): LngLat[] | null {
  for (const f of fc.features) {
    const g = f.geometry;
    if (g?.type === "Polygon") return g.coordinates[0] as LngLat[];
    if (g?.type === "MultiPolygon") return g.coordinates[0][0] as LngLat[];
  }
  return null;
}
function paddingFor(m: MLMap, frac = 0.08) {
  const c = m.getContainer();
  const p = Math.round(Math.min(c.clientWidth, c.clientHeight) * frac) + 16;
  return { top: p, bottom: p, left: p, right: p };
}
const easeOutCubic = (t: number) => 1 - (1 - t) ** 3;

function assetPosition(a: Asset, nodes: Map<string, NetNode>, fieldCentroid: Map<string, LngLat>): LngLat | null {
  if (typeof a.lon === "number" && typeof a.lat === "number") return [a.lon, a.lat];
  if (a.node_id && nodes.get(a.node_id)) {
    const n = nodes.get(a.node_id)!;
    return [n.lon, n.lat];
  }
  // In-field pond without coordinates: anchor near the field centroid (display only).
  const c = a.field_ids.map((f) => fieldCentroid.get(f)).find(Boolean);
  return c ?? null;
}

/** Match each declared edge to its observed canal geometry, oriented upstream→downstream. */
export function buildEdgeGeoms(nodes: NetNode[], edges: Edge[], canals: GeoJSON.FeatureCollection | null): EdgeGeom[] {
  const nodeById = new Map(nodes.map((n) => [n.node_id, n]));
  const canalById = new Map<string, GeoJSON.Feature>();
  for (const f of canals?.features ?? []) {
    const keys = [f.id, f.properties?.id, f.properties?.feature_id, f.properties?.canal_id, f.properties?.provider_id, f.properties?.source_feature_id, f.properties?.osm_id];
    for (const k of keys) if (k !== undefined && k !== null) canalById.set(String(k), f);
  }
  const out: EdgeGeom[] = [];
  for (const e of edges) {
    const up = nodeById.get(e.upstream_node_id);
    const down = nodeById.get(e.downstream_node_id);
    const start: LngLat | null = up ? [up.lon, up.lat] : null;
    const end: LngLat | null = down ? [down.lon, down.lat] : null;
    let parts: LngLat[][] = [];
    if (e.geometry_ref) {
      const ids = [e.geometry_ref, ...e.source_feature_ids];
      for (const id of ids) {
        const f = canalById.get(id);
        if (f) {
          parts = lineCoords(f.geometry);
          if (parts.length) break;
        }
      }
    }
    const assumed = e.geometry_ref === null || !parts.length;
    let path = parts.length ? orientedPath(parts, start, end) : start && end ? [start, end] : [];
    // If observed geometry stops short of the nodes, connect to them so the route is continuous.
    if (parts.length && start && path.length) path = [start, ...path];
    if (parts.length && end && path.length) path = [...path, end];
    if (path.length >= 2) out.push({ edge: e, path: toPolyline(path), assumed });
  }
  return out;
}
