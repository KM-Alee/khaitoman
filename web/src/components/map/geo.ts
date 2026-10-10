/** Small, dependency-free geometry helpers for display (not analysis). */

export type LngLat = [number, number];
const R = 6371008.8;
const rad = (d: number) => (d * Math.PI) / 180;

export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]);
  const dLon = rad(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

export function offsetM(p: LngLat, dxM: number, dyM: number): LngLat {
  const dLat = (dyM / R) * (180 / Math.PI);
  const dLon = (dxM / (R * Math.cos(rad(p[1])))) * (180 / Math.PI);
  return [p[0] + dLon, p[1] + dLat];
}

/** Regular polygon ring around a point (closed), radius in metres. */
export function ringAround(p: LngLat, radiusM: number, sides = 48, rotation = 0): LngLat[] {
  const out: LngLat[] = [];
  for (let i = 0; i <= sides; i++) {
    const t = rotation + (i / sides) * Math.PI * 2;
    out.push(offsetM(p, Math.cos(t) * radiusM, Math.sin(t) * radiusM));
  }
  return out;
}

export function bboxOf(geom: GeoJSON.Geometry | null | undefined): [number, number, number, number] | null {
  if (!geom) return null;
  let w = Infinity,
    s = Infinity,
    e = -Infinity,
    n = -Infinity;
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      const [x, y] = c as number[];
      if (x < w) w = x;
      if (x > e) e = x;
      if (y < s) s = y;
      if (y > n) n = y;
    } else if (Array.isArray(c)) c.forEach(visit);
  };
  if (geom.type === "GeometryCollection") geom.geometries.forEach((g) => visit((g as { coordinates?: unknown }).coordinates));
  else visit((geom as { coordinates: unknown }).coordinates);
  return Number.isFinite(w) ? [w, s, e, n] : null;
}

export function bboxOfCollection(fc: GeoJSON.FeatureCollection | null | undefined): [number, number, number, number] | null {
  if (!fc) return null;
  let acc: [number, number, number, number] | null = null;
  for (const f of fc.features) {
    const b = bboxOf(f.geometry);
    if (!b) continue;
    acc = acc ? [Math.min(acc[0], b[0]), Math.min(acc[1], b[1]), Math.max(acc[2], b[2]), Math.max(acc[3], b[3])] : b;
  }
  return acc;
}

/** Area-weighted centroid of the largest polygon ring (display label anchor). */
export function centroid(geom: GeoJSON.Geometry | null | undefined): LngLat | null {
  if (!geom) return null;
  const rings: LngLat[][] =
    geom.type === "Polygon"
      ? [geom.coordinates[0] as LngLat[]]
      : geom.type === "MultiPolygon"
        ? geom.coordinates.map((p) => p[0] as LngLat[])
        : [];
  if (geom.type === "Point") return geom.coordinates as LngLat;
  let best: { a: number; c: LngLat } | null = null;
  for (const ring of rings) {
    let a = 0,
      cx = 0,
      cy = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x0, y0] = ring[i];
      const [x1, y1] = ring[i + 1];
      const f = x0 * y1 - x1 * y0;
      a += f;
      cx += (x0 + x1) * f;
      cy += (y0 + y1) * f;
    }
    if (Math.abs(a) < 1e-14) continue;
    const c: LngLat = [cx / (3 * a), cy / (3 * a)];
    if (!best || Math.abs(a) > best.a) best = { a: Math.abs(a), c };
  }
  if (best) return best.c;
  const b = bboxOf(geom);
  return b ? [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] : null;
}

export function lineCoords(geom: GeoJSON.Geometry | null | undefined): LngLat[][] {
  if (!geom) return [];
  if (geom.type === "LineString") return [geom.coordinates as LngLat[]];
  if (geom.type === "MultiLineString") return geom.coordinates as LngLat[][];
  return [];
}

export interface Polyline {
  coords: LngLat[];
  cum: number[]; // cumulative metres
  length: number;
}

export function toPolyline(coords: LngLat[]): Polyline {
  const cum = [0];
  for (let i = 1; i < coords.length; i++) cum.push(cum[i - 1] + distanceM(coords[i - 1], coords[i]));
  return { coords, cum, length: cum[cum.length - 1] ?? 0 };
}

export function pointAt(pl: Polyline, d: number): LngLat {
  const { coords, cum, length } = pl;
  if (coords.length === 1 || length === 0) return coords[0];
  const t = ((d % length) + length) % length;
  let lo = 0,
    hi = cum.length - 1;
  while (lo < hi - 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= t) lo = mid;
    else hi = mid;
  }
  const seg = cum[hi] - cum[lo] || 1;
  const f = (t - cum[lo]) / seg;
  return [coords[lo][0] + (coords[hi][0] - coords[lo][0]) * f, coords[lo][1] + (coords[hi][1] - coords[lo][1]) * f];
}

/** Join the parts of a (Multi)LineString into one directed path from `start` towards `end`. */
export function orientedPath(parts: LngLat[][], start: LngLat | null, end: LngLat | null): LngLat[] {
  if (!parts.length) return start && end ? [start, end] : [];
  // Greedy chaining of parts by nearest endpoints.
  const remaining = parts.map((p) => [...p]);
  let path = remaining.shift()!;
  while (remaining.length) {
    const tail = path[path.length - 1];
    const head = path[0];
    let bi = 0,
      bd = Infinity,
      mode = 0;
    remaining.forEach((p, i) => {
      const cands = [
        [distanceM(tail, p[0]), 0],
        [distanceM(tail, p[p.length - 1]), 1],
        [distanceM(head, p[p.length - 1]), 2],
        [distanceM(head, p[0]), 3],
      ];
      for (const [d, m] of cands)
        if (d < bd) {
          bd = d;
          bi = i;
          mode = m;
        }
    });
    const p = remaining.splice(bi, 1)[0];
    if (mode === 0) path = path.concat(p);
    else if (mode === 1) path = path.concat(p.reverse());
    else if (mode === 2) path = p.concat(path);
    else path = p.reverse().concat(path);
  }
  if (start && end) {
    const keep = distanceM(path[0], start) + distanceM(path[path.length - 1], end);
    const flip = distanceM(path[0], end) + distanceM(path[path.length - 1], start);
    if (flip < keep) path.reverse();
  } else if (start) {
    if (distanceM(path[path.length - 1], start) < distanceM(path[0], start)) path.reverse();
  }
  return path;
}
