import { backendMapRequest } from "@/lib/api/urls";
/**
 * Onboarding map (T10.3): one MapLibre instance per mount. In draw mode it is a constrained
 * polygon tool (click to add vertices, click the first vertex or press Enter to close,
 * Backspace to undo, Escape to clear). In review mode it shows the intake's own API layers:
 * AOI, observed canals (OSM solid, GRAIN dashed), raw Delineate polygons and the proposed
 * fields, with feature-state for hover and selection. Layer order is fixed:
 * background → HD basemap → published-pilot context (inserted below the graticule) → graticule → AOI → raw → proposed →
 * canals → drawing. Context layers are published pilots' AOIs and package imagery; with
 * VITE_ARCGIS_KEY set, Esri World Imagery is a display-only basemap (docs/IMAGERY.md).
 */
import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { cssVar } from "@/components/map/palette";
import type { LngLat } from "@/components/map/geo";
import { HD_IMAGERY_ATTRIBUTION, HD_IMAGERY_KEY, hdActive, hdImageryTiles, isRejection, markHdRejected } from "@/components/map/hdImagery";

export interface ContextLayer {
  id: string;
  bbox: [number, number, number, number];
  image?: { url: string; corners: [number, number][] } | null;
  label: string;
}

export interface ReviewOverlays {
  aoi?: GeoJSON.Geometry | null;
  canals?: GeoJSON.FeatureCollection | null;
  fieldsRaw?: GeoJSON.FeatureCollection | null;
  fieldsProposed?: GeoJSON.FeatureCollection | null;
}

export interface MapSelection {
  field?: string | null;
  model?: string | null;
  canal?: string | null;
}

export type MapPick = { kind: "field" | "model" | "canal"; id: string };

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const SOURCES = { aoi: "onb-aoi", raw: "onb-raw", proposed: "onb-proposed", canals: "onb-canals" } as const;
const PICK_LAYERS: [string, MapPick["kind"], string][] = [
  ["onb-canals-osm", "canal", "source_feature_id"],
  ["onb-canals-grain", "canal", "source_feature_id"],
  ["onb-proposed-fill", "field", "field_id"],
  ["onb-raw-fill", "model", "model_id"],
];

function asCollection(g: GeoJSON.Geometry | GeoJSON.FeatureCollection | null | undefined): GeoJSON.FeatureCollection {
  if (!g) return EMPTY;
  if (g.type === "FeatureCollection") return g;
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] };
}

export function AoiDrawMap({
  vertices,
  closed,
  onChange,
  context,
  className,
  drawing = true,
  overlays,
  visible,
  selected,
  onPick,
  fitBbox,
  label,
}: {
  vertices: LngLat[];
  closed: boolean;
  onChange: (v: LngLat[], closed: boolean) => void;
  context: ContextLayer[];
  className?: string;
  /** False in review mode until the reviewer starts a replacement outline. */
  drawing?: boolean;
  overlays?: ReviewOverlays;
  visible?: { canals?: boolean; fieldsRaw?: boolean; fieldsProposed?: boolean };
  selected?: MapSelection;
  onPick?: (p: MapPick) => void;
  fitBbox?: [number, number, number, number] | null;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loaded = useRef(false);
  const state = useRef({ vertices, closed, onChange, drawing, onPick, overlays, visible, selected, fitBbox, context });
  state.current = { vertices, closed, onChange, drawing, onPick, overlays, visible, selected, fitBbox, context };
  const added = useRef(new Set<string>());
  const fitted = useRef(false);
  const applied = useRef<{ selection: Record<string, string | null>; hover: { source: string; id: string } | null }>({
    selection: { [SOURCES.proposed]: null, [SOURCES.raw]: null, [SOURCES.canals]: null },
    hover: null,
  });

  useEffect(() => {
    if (!ref.current) return;
    const water = cssVar("--water", "#087f8c");
    const m = new maplibregl.Map({
      transformRequest: backendMapRequest,
      container: ref.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--map-bg", "#dfe3da") } }],
      },
      center: [72.6, 30.9],
      zoom: 9,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      attributionControl: { compact: true },
      doubleClickZoom: false,
    });
    mapRef.current = m;
    m.getCanvas().setAttribute(
      "aria-label",
      label ?? "AOI drawing map. Click to add vertices; Enter closes the polygon; Backspace removes the last vertex.",
    );
    m.on("error", (e) => {
      const ev = e as unknown as { sourceId?: string; error?: { status?: number } };
      if (ev.sourceId === "hd" && isRejection(ev.error?.status)) {
        markHdRejected();
        if (m.getLayer("hd")) m.removeLayer("hd");
      }
    });
    m.on("load", () => {
      if (hdActive()) {
        m.addSource("hd", { type: "raster", tiles: [hdImageryTiles(HD_IMAGERY_KEY)], tileSize: 256, maxzoom: 19, attribution: HD_IMAGERY_ATTRIBUTION });
        m.addLayer({ id: "hd", type: "raster", source: "hd", paint: { "raster-saturation": -0.2, "raster-fade-duration": 150 } });
      }
      // graticule every 0.1° for orientation without a basemap
      const lines: GeoJSON.Feature[] = [];
      for (let x = 60; x <= 80; x += 0.1) lines.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[x, 23], [x, 37]] } });
      for (let y = 23; y <= 37; y += 0.1) lines.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[60, y], [80, y]] } });
      m.addSource("grid", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
      m.addLayer({ id: "grid", type: "line", source: "grid", paint: { "line-color": cssVar("--border-strong"), "line-width": 0.5, "line-opacity": hdActive() ? 0.18 : 0.5 } });

      const sel = ["boolean", ["feature-state", "selected"], false];
      const hov = ["boolean", ["feature-state", "hover"], false];
      const focus = cssVar("--focus", "#245fbd");
      m.addSource(SOURCES.aoi, { type: "geojson", data: EMPTY });
      m.addLayer({ id: "onb-aoi-line", type: "line", source: SOURCES.aoi, paint: { "line-color": cssVar("--ink"), "line-width": 2, "line-dasharray": [3, 2] } });
      m.addSource(SOURCES.raw, { type: "geojson", data: EMPTY, promoteId: "model_id" });
      m.addLayer({
        id: "onb-raw-fill",
        type: "fill",
        source: SOURCES.raw,
        paint: { "fill-color": cssVar("--warning", "#975306"), "fill-opacity": ["case", sel, 0.35, 0.04] as never },
      });
      m.addLayer({
        id: "onb-raw-line",
        type: "line",
        source: SOURCES.raw,
        paint: { "line-color": ["case", sel, focus, cssVar("--warning", "#975306")] as never, "line-width": ["case", sel, 2.5, 0.8] as never },
      });
      m.addSource(SOURCES.proposed, { type: "geojson", data: EMPTY, promoteId: "field_id" });
      m.addLayer({
        id: "onb-proposed-fill",
        type: "fill",
        source: SOURCES.proposed,
        paint: { "fill-color": cssVar("--vegetation", "#386a4b"), "fill-opacity": ["case", sel, 0.55, hov, 0.42, 0.28] as never },
      });
      m.addLayer({
        id: "onb-proposed-line",
        type: "line",
        source: SOURCES.proposed,
        paint: { "line-color": ["case", sel, focus, cssVar("--vegetation", "#386a4b")] as never, "line-width": ["case", sel, 3, hov, 2, 1.4] as never },
      });
      m.addSource(SOURCES.canals, { type: "geojson", data: EMPTY, promoteId: "source_feature_id" });
      // Observed OSM geometry is solid; GRAIN classification lines are dashed (style, not color alone).
      m.addLayer({
        id: "onb-canals-osm",
        type: "line",
        source: SOURCES.canals,
        filter: ["==", ["get", "provider"], "osm"],
        paint: { "line-color": ["case", sel, focus, water] as never, "line-width": ["case", sel, 5, 2.5] as never },
      });
      m.addLayer({
        id: "onb-canals-grain",
        type: "line",
        source: SOURCES.canals,
        filter: ["!=", ["get", "provider"], "osm"],
        paint: { "line-color": ["case", sel, focus, cssVar("--water-deep", "#075e68")] as never, "line-width": ["case", sel, 4, 1.6] as never, "line-dasharray": [2, 1.5] },
      });

      m.addSource("draw", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "draw-fill", type: "fill", source: "draw", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": water, "fill-opacity": 0.18 } });
      m.addLayer({ id: "draw-line", type: "line", source: "draw", filter: ["!=", ["geometry-type"], "Point"], paint: { "line-color": water, "line-width": 2.5 } });
      m.addLayer({
        id: "draw-pts",
        type: "circle",
        source: "draw",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": ["case", ["==", ["get", "first"], true], 7, 5], "circle-color": "#ffffff", "circle-stroke-color": water, "circle-stroke-width": 2 },
      });
      loaded.current = true;
      const fit = state.current.fitBbox;
      if (fit) {
        m.fitBounds(fit, { padding: 40, duration: 0, maxZoom: 16 });
        fitted.current = true;
      }
      syncContext();
      syncOverlays();
      syncSelection();
      redraw();
    });
    m.on("click", (e) => {
      const { vertices: v, closed: c, onChange: cb, drawing: d, onPick: pick } = state.current;
      if (!d) {
        if (!pick) return;
        const layers = PICK_LAYERS.filter(([id]) => m.getLayer(id) && m.getLayoutProperty(id, "visibility") !== "none");
        const hits = layers.length ? m.queryRenderedFeatures(e.point, { layers: layers.map(([id]) => id) }) : [];
        for (const [id, kind, key] of layers) {
          const hit = hits.find((h) => h.layer.id === id);
          const value = hit?.properties?.[key];
          if (typeof value === "string") {
            pick({ kind, id: value });
            return;
          }
        }
        return;
      }
      if (c) return;
      if (v.length >= 3) {
        const p0 = m.project(v[0]);
        if (Math.hypot(p0.x - e.point.x, p0.y - e.point.y) < 12) {
          cb(v, true);
          return;
        }
      }
      cb([...v, [e.lngLat.lng, e.lngLat.lat]], false);
    });
    m.on("mousemove", "onb-proposed-fill", (e) => {
      const id = e.features?.[0]?.properties?.field_id;
      const prev = applied.current.hover;
      if (prev && prev.id !== id) m.setFeatureState({ source: prev.source, id: prev.id }, { hover: false });
      if (typeof id === "string") {
        m.setFeatureState({ source: SOURCES.proposed, id }, { hover: true });
        applied.current.hover = { source: SOURCES.proposed, id };
        m.getCanvas().style.cursor = "pointer";
      }
    });
    m.on("mouseleave", "onb-proposed-fill", () => {
      const prev = applied.current.hover;
      if (prev) m.setFeatureState({ source: prev.source, id: prev.id }, { hover: false });
      applied.current.hover = null;
      m.getCanvas().style.cursor = "";
    });
    return () => {
      loaded.current = false;
      m.remove();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** Published-pilot context may arrive after the map loads; layers go below the graticule. */
  function syncContext() {
    const m = mapRef.current;
    if (!m || !loaded.current) return;
    const ctx = state.current.context;
    for (const c of ctx) {
      if (added.current.has(c.id)) continue;
      added.current.add(c.id);
      const key = c.id.replace(/[^A-Za-z0-9_-]/g, "_");
      if (c.image?.url && c.image.corners.length === 4) {
        m.addSource(`ctx-img-${key}`, { type: "image", url: c.image.url, coordinates: c.image.corners as [LngLat, LngLat, LngLat, LngLat] });
        m.addLayer({ id: `ctx-img-${key}`, type: "raster", source: `ctx-img-${key}`, paint: { "raster-opacity": 0.85 } }, "grid");
      }
      const [w, s, e, n] = c.bbox;
      m.addSource(`ctx-${key}`, { type: "geojson", data: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] } } });
      m.addLayer({ id: `ctx-${key}`, type: "line", source: `ctx-${key}`, paint: { "line-color": cssVar("--ink-secondary"), "line-width": 1.2, "line-dasharray": [2, 2] } }, "grid");
    }
    if (!fitted.current && ctx.length && !state.current.vertices.length) {
      const b = ctx.reduce((a, c) => [Math.min(a[0], c.bbox[0]), Math.min(a[1], c.bbox[1]), Math.max(a[2], c.bbox[2]), Math.max(a[3], c.bbox[3])], [180, 90, -180, -90]);
      m.fitBounds(b as [number, number, number, number], { padding: 80, duration: 0, maxZoom: 12 });
      fitted.current = true;
    }
  }

  function syncOverlays() {
    const m = mapRef.current;
    if (!m || !loaded.current) return;
    const o = state.current.overlays ?? {};
    const vis = state.current.visible ?? {};
    const set = (id: string, data: GeoJSON.FeatureCollection) => (m.getSource(id) as GeoJSONSource | undefined)?.setData(data);
    set(SOURCES.aoi, asCollection(o.aoi));
    set(SOURCES.raw, asCollection(o.fieldsRaw));
    set(SOURCES.proposed, asCollection(o.fieldsProposed));
    set(SOURCES.canals, asCollection(o.canals));
    const show = (ids: string[], on: boolean | undefined) =>
      ids.forEach((id) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on === false ? "none" : "visible"));
    show(["onb-raw-fill", "onb-raw-line"], vis.fieldsRaw);
    show(["onb-proposed-fill", "onb-proposed-line"], vis.fieldsProposed);
    show(["onb-canals-osm", "onb-canals-grain"], vis.canals);
  }

  function syncSelection() {
    const m = mapRef.current;
    if (!m || !loaded.current) return;
    const s = state.current.selected ?? {};
    const want: Record<string, string | null> = {
      [SOURCES.proposed]: s.field ?? null,
      [SOURCES.raw]: s.model ?? null,
      [SOURCES.canals]: s.canal ?? null,
    };
    for (const [source, id] of Object.entries(want)) {
      const prev = applied.current.selection[source];
      if (prev === id) continue;
      if (prev) m.setFeatureState({ source, id: prev }, { selected: false });
      if (id) m.setFeatureState({ source, id }, { selected: true });
      applied.current.selection[source] = id;
    }
  }

  const redraw = () => {
    const m = mapRef.current;
    const src = m?.getSource("draw") as GeoJSONSource | undefined;
    if (!src) return;
    const { vertices: v, closed: c } = state.current;
    const feats: GeoJSON.Feature[] = v.map((p, i) => ({ type: "Feature", properties: { first: i === 0 }, geometry: { type: "Point", coordinates: p } }));
    if (v.length >= 2) feats.push({ type: "Feature", properties: {}, geometry: c ? { type: "Polygon", coordinates: [[...v, v[0]]] } : { type: "LineString", coordinates: v } });
    src.setData({ type: "FeatureCollection", features: feats });
  };
  useEffect(redraw, [vertices, closed]);
  useEffect(syncOverlays, [overlays?.aoi, overlays?.canals, overlays?.fieldsRaw, overlays?.fieldsProposed, visible?.canals, visible?.fieldsRaw, visible?.fieldsProposed]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(syncSelection, [selected?.field, selected?.model, selected?.canal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(syncContext, [context.map((c) => c.id).join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const fitKey = fitBbox ? fitBbox.join(",") : "";
  useEffect(() => {
    const m = mapRef.current;
    if (m && loaded.current && fitBbox) {
      m.fitBounds(fitBbox, { padding: 40, duration: 0, maxZoom: 16 });
      fitted.current = true;
    }
  }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={ref}
      tabIndex={0}
      role="application"
      aria-label={label ?? "AOI drawing map"}
      className={className}
      data-testid="aoi-map"
      data-drawing={drawing ? "true" : "false"}
      onKeyDown={(e) => {
        if (!drawing) return;
        if (e.key === "Enter" && vertices.length >= 3) onChange(vertices, true);
        if (e.key === "Backspace" && !closed) onChange(vertices.slice(0, -1), false);
        if (e.key === "Escape") onChange([], false);
      }}
    />
  );
}
