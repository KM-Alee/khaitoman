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
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MLMap,
  type MapGeoJSONFeature,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapBundle } from "@/lib/api/adapters";
import type { Asset, Edge, NetNode } from "@/lib/api/types";
import { demTileTemplate, demStats } from "./demTiles";
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

export interface EngineOptions {
  reducedMotion: boolean;
  mode: MapMode;
  /** Secondary maps (compare) skip attribution duplication. */
  secondary?: boolean;
}

const MAX_EXTRUDE_M = 46;
const MIN_EXTRUDE_M = 3;
const SRC = {
  imagery: "imagery",
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
  private rawVisible = false;
  private dataKey = "";

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
      attributionControl: opts.secondary ? false : { compact: true },
      canvasContextAttributes: { antialias: true },
      fadeDuration: 0,
      dragRotate: true,
      pitchWithRotate: true,
      cancelPendingTileRequestsWhileZooming: true,
    });
    this.map.getCanvas().setAttribute("aria-label", "Pilot map. Use [ and ] to move between fields, Enter to select, Escape to clear.");
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
  on(fn: (e: EngineEvent) => void) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
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
  async setData(args: {
    bundle: MapBundle;
    fields: GeoJSON.FeatureCollection | null;
    canals: GeoJSON.FeatureCollection | null;
    aoi: GeoJSON.FeatureCollection | null;
    raw: GeoJSON.FeatureCollection | null;
    imageryIndex?: number;
  }) {
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
      m.addSource(SRC.imagery, { type: "image", url: im.url, coordinates: im.corners as [LngLat, LngLat, LngLat, LngLat] });
      m.addLayer({
        id: "imagery",
        type: "raster",
        source: SRC.imagery,
        layout: { visibility: this.imageryVisible ? "visible" : "none" },
        paint: { "raster-opacity": 1, "raster-saturation": -0.12, "raster-contrast": 0.06, "raster-fade-duration": 0, "raster-resampling": "linear" },
      });
    }

    // --- terrain (optional)
    const t = args.bundle.terrain;
    if (t) {
      try {
        const tiles = demTileTemplate(t.url, t.bounds, t.encoding);
        const stats = await demStats(t.url, t.bounds, t.encoding);
        if (this.destroyed) return;
        const relief = Math.max(1, stats.max - stats.min);
        // Flat Punjab plains: exaggerate modestly so canal-scale relief is legible; labelled in the legend.
        this.terrainExaggeration = Math.round(Math.max(1, Math.min(6, 24 / relief)) * 10) / 10;
        const demSrc = { type: "raster-dem" as const, tiles: [tiles], tileSize: 256, encoding: "terrarium" as const, bounds: t.bounds, minzoom: 8, maxzoom: 14 };
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
      m.addLayer({ id: "aoi-mask", type: "fill", source: SRC.mask, paint: { "fill-color": cssVar("--canvas"), "fill-opacity": 0.38 } });
      m.addSource(SRC.aoi, { type: "geojson", data: aoiFC });
      m.addLayer({
        id: "aoi-outline",
        type: "line",
        source: SRC.aoi,
        paint: { "line-color": surface, "line-width": 1.5, "line-opacity": 0.9, "line-dasharray": [3, 2] },
      });
    }

    // --- raw AI output (review overlay)
    if (args.raw) {
      m.addSource(SRC.raw, { type: "geojson", data: args.raw });
      m.addLayer({
        id: "fields-raw",
        type: "line",
        source: SRC.raw,
        layout: { visibility: this.rawVisible ? "visible" : "none" },
        paint: { "line-color": cssVar("--warning"), "line-width": 1.2, "line-dasharray": [2, 1.5], "line-opacity": 0.95 },
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
        "fill-extrusion-opacity": 0.9,
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
    for (const l of [...(m.getStyle()?.layers ?? [])]) if (l.id !== "bg") m.removeLayer(l.id);
    if (m.getTerrain()) m.setTerrain(null);
    this.terrainOn = false;
    for (const s of Object.keys(m.getStyle()?.sources ?? {})) m.removeSource(s);
  }

  /* ------------------------------------------------------------ appearance */
  private applySky() {
    const dark = document.documentElement.dataset.theme === "dark";
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
    if (this.map.getLayer("aoi-mask")) this.map.setPaintProperty("aoi-mask", "fill-color", cssVar("--canvas"));
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

  /** Emphasise a subset (e.g. frontier portfolio fields); others dim. null clears. */
  setHighlight(ids: string[] | null) {
    this.highlightIds = ids && ids.length ? new Set(ids) : null;
    this.applyVisuals();
  }

  private applyVisuals() {
    const m = this.map;
    if (!m.getSource(SRC.fields)) return;
    const neutral = cssVar("--surface-sunken", "#e4e8e1");
    const canvas = cssVar("--canvas", "#f4f2eb");
    const anyFocus = !!this.selected || !!this.highlightIds;
    for (const id of this.fieldOrder) {
      const v = this.visuals.get(id);
      const base = v?.color ?? neutral;
      const focus = this.highlightIds ? this.highlightIds.has(id) || id === this.selected : !this.selected || id === this.selected;
      const dim = anyFocus && !focus;
      const color = dim ? mix(base, canvas, 0.5) : base;
      const h = v ? MIN_EXTRUDE_M + v.norm * (MAX_EXTRUDE_M - MIN_EXTRUDE_M) : MIN_EXTRUDE_M * 0.6;
      m.setFeatureState({ source: SRC.fields, id }, { color, hcolor: mix(base, "#ffffff", 0.28), h, dim });
    }
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
    const b = this.bundle?.bbox ?? bboxOfCollection(this.fields);
    if (!b) return;
    const three = this.opts.mode === "3d" && !this.opts.reducedMotion;
    const cam = this.map.cameraForBounds(b as LngLatBoundsLike, { padding: paddingFor(this.map), bearing: three ? -18 : 0, pitch: three ? 52 : 0 });
    if (!cam) return;
    const opts = { ...cam, pitch: three ? 52 : 0, bearing: three ? -18 : 0 };
    if (!animate || this.opts.reducedMotion) this.map.jumpTo(opts);
    else this.map.flyTo({ ...opts, duration: 900, essential: false, curve: 1.3 });
  }

  flyToField(id: string) {
    const b = this.fieldBBox.get(id);
    if (!b) return;
    const three = this.opts.mode === "3d" && !this.opts.reducedMotion;
    const cam = this.map.cameraForBounds(b as LngLatBoundsLike, { padding: paddingFor(this.map, 0.3), maxZoom: 16.5, bearing: this.map.getBearing(), pitch: three ? 58 : 0 });
    if (!cam) return;
    const zoom = Math.min(16.2, (cam.zoom ?? 15) - 0.6);
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
