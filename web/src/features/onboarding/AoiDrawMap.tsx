/**
 * Constrained polygon drawing for onboarding (T10.3): click to add vertices, click the first
 * vertex or press Enter to close, Backspace to undo, Escape to clear. Uses only local
 * context layers (published pilots' AOIs and imagery) — no remote basemap tiles.
 */
import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { cssVar } from "@/components/map/palette";
import type { LngLat } from "@/components/map/geo";

export interface ContextLayer {
  id: string;
  bbox: [number, number, number, number];
  image?: { url: string; corners: [number, number][] } | null;
  label: string;
}

export function AoiDrawMap({
  vertices,
  closed,
  onChange,
  context,
  className,
}: {
  vertices: LngLat[];
  closed: boolean;
  onChange: (v: LngLat[], closed: boolean) => void;
  context: ContextLayer[];
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const state = useRef({ vertices, closed, onChange });
  state.current = { vertices, closed, onChange };

  useEffect(() => {
    if (!ref.current) return;
    const water = cssVar("--water", "#087f8c");
    const m = new maplibregl.Map({
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
    m.getCanvas().setAttribute("aria-label", "AOI drawing map. Click to add vertices; Enter closes the polygon; Backspace removes the last vertex.");
    m.on("load", () => {
      context.forEach((c, i) => {
        if (c.image?.url && c.image.corners.length === 4) {
          m.addSource(`ctx-img-${i}`, { type: "image", url: c.image.url, coordinates: c.image.corners as [LngLat, LngLat, LngLat, LngLat] });
          m.addLayer({ id: `ctx-img-${i}`, type: "raster", source: `ctx-img-${i}`, paint: { "raster-opacity": 0.85 } });
        }
        const [w, s, e, n] = c.bbox;
        m.addSource(`ctx-${i}`, { type: "geojson", data: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] } } });
        m.addLayer({ id: `ctx-${i}`, type: "line", source: `ctx-${i}`, paint: { "line-color": cssVar("--ink-secondary"), "line-width": 1.2, "line-dasharray": [2, 2] } });
      });
      // graticule every 0.1° for orientation without a basemap
      const lines: GeoJSON.Feature[] = [];
      for (let x = 60; x <= 80; x += 0.1) lines.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[x, 23], [x, 37]] } });
      for (let y = 23; y <= 37; y += 0.1) lines.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[60, y], [80, y]] } });
      m.addSource("grid", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
      m.addLayer({ id: "grid", type: "line", source: "grid", paint: { "line-color": cssVar("--border-strong"), "line-width": 0.5, "line-opacity": 0.5 } });
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
      if (context.length) {
        const b = context.reduce((a, c) => [Math.min(a[0], c.bbox[0]), Math.min(a[1], c.bbox[1]), Math.max(a[2], c.bbox[2]), Math.max(a[3], c.bbox[3])], [180, 90, -180, -90]);
        m.fitBounds(b as [number, number, number, number], { padding: 80, duration: 0, maxZoom: 12 });
      }
      redraw();
    });
    m.on("click", (e) => {
      const { vertices: v, closed: c, onChange: cb } = state.current;
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
    return () => m.remove();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  return (
    <div
      ref={ref}
      tabIndex={0}
      className={className}
      data-testid="aoi-map"
      onKeyDown={(e) => {
        if (e.key === "Enter" && vertices.length >= 3) onChange(vertices, true);
        if (e.key === "Backspace" && !closed) onChange(vertices.slice(0, -1), false);
        if (e.key === "Escape") onChange([], false);
      }}
    />
  );
}

/** Geodesic-ish polygon area (m²) via spherical excess approximation; display only. */
export function ringAreaM2(ring: LngLat[]): number {
  if (ring.length < 3) return 0;
  const R = 6371008.8;
  const rad = (d: number) => (d * Math.PI) / 180;
  let s = 0;
  const pts = ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring : [...ring, ring[0]];
  for (let i = 0; i < pts.length - 1; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[i + 1];
    s += rad(x2 - x1) * (2 + Math.sin(rad(y1)) + Math.sin(rad(y2)));
  }
  return Math.abs((s * R * R) / 2);
}
