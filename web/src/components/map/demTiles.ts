/**
 * Serves raster-dem tiles from the pilot package's single local Terrarium PNG
 * (`terrain/dem.png` + bounds). The image is decoded once to float elevations, and each
 * requested web-mercator tile is resampled bilinearly in elevation space (never by
 * interpolating encoded RGB bytes, which would corrupt Terrarium values) and re-encoded.
 * Everything stays on the local origin (AT15).
 */
import maplibregl from "maplibre-gl";

export const DEM_PROTOCOL = "aabdem";
const TILE = 256;

interface DemGrid {
  w: number;
  h: number;
  bounds: [number, number, number, number]; // w s e n (EPSG:4326)
  elev: Float32Array;
  base: number; // elevation used outside the DEM footprint
  min: number;
  max: number;
}

const grids = new Map<string, Promise<DemGrid>>();
/** Encoded tiles shared by every map and source (terrain + hillshade, paired maps). */
const tileCache = new Map<string, Promise<ArrayBuffer>>();
const TILE_CACHE_MAX = 400;
let registered = false;

export function decodeTerrarium(r: number, g: number, b: number): number {
  return r * 256 + g + b / 256 - 32768;
}
export function encodeTerrarium(m: number): [number, number, number] {
  const v = m + 32768;
  const r = Math.floor(v / 256);
  const g = Math.floor(v - r * 256);
  const b = Math.round((v - r * 256 - g) * 256);
  return [clamp8(r), clamp8(g), clamp8(b === 256 ? 255 : b)];
}
export function decodeMapbox(r: number, g: number, b: number): number {
  return -10000 + (r * 256 * 256 + g * 256 + b) * 0.1;
}
const clamp8 = (x: number) => (x < 0 ? 0 : x > 255 ? 255 : x);

async function loadGrid(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox"): Promise<DemGrid> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`DEM ${res.status}`);
  const bmp = await createImageBitmap(await res.blob(), { premultiplyAlpha: "none", colorSpaceConversion: "none" });
  const c = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(bmp, 0, 0);
  const px = ctx.getImageData(0, 0, bmp.width, bmp.height).data;
  const n = bmp.width * bmp.height;
  const elev = new Float32Array(n);
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  let cnt = 0;
  for (let i = 0; i < n; i++) {
    const a = px[i * 4 + 3];
    const v = a === 0 ? Number.NaN : encoding === "mapbox" ? decodeMapbox(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]) : decodeTerrarium(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]);
    elev[i] = v;
    if (Number.isFinite(v)) {
      if (v < min) min = v;
      if (v > max) max = v;
      sum += v;
      cnt++;
    }
  }
  const base = cnt ? sum / cnt : 0;
  for (let i = 0; i < n; i++) if (!Number.isFinite(elev[i])) elev[i] = base;
  return { w: bmp.width, h: bmp.height, bounds, elev, base, min, max };
}

function tileLonLat(z: number, x: number, y: number, px: number, py: number): [number, number] {
  const n = 2 ** z;
  const lon = ((x + px / TILE) / n) * 360 - 180;
  const merc = Math.PI * (1 - (2 * (y + py / TILE)) / n);
  const lat = (Math.atan(Math.sinh(merc)) * 180) / Math.PI;
  return [lon, lat];
}

function sample(g: DemGrid, lon: number, lat: number): number {
  const [w, s, e, nn] = g.bounds;
  if (lon < w || lon > e || lat < s || lat > nn) {
    // Feather to the mean outside the footprint to avoid a cliff at the package edge.
    return g.base;
  }
  const fx = ((lon - w) / (e - w)) * (g.w - 1);
  const fy = ((nn - lat) / (nn - s)) * (g.h - 1);
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = Math.min(g.w - 1, x0 + 1);
  const y1 = Math.min(g.h - 1, y0 + 1);
  const tx = fx - x0;
  const ty = fy - y0;
  const a = g.elev[y0 * g.w + x0];
  const b = g.elev[y0 * g.w + x1];
  const c = g.elev[y1 * g.w + x0];
  const d = g.elev[y1 * g.w + x1];
  return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
}

async function renderTile(g: DemGrid, z: number, x: number, y: number): Promise<ArrayBuffer> {
  const c = new OffscreenCanvas(TILE, TILE);
  const ctx = c.getContext("2d")!;
  const img = ctx.createImageData(TILE, TILE);
  for (let py = 0; py < TILE; py++) {
    for (let px = 0; px < TILE; px++) {
      const [lon, lat] = tileLonLat(z, x, y, px + 0.5, py + 0.5);
      const [r, gg, b] = encodeTerrarium(sample(g, lon, lat));
      const i = (py * TILE + px) * 4;
      img.data[i] = r;
      img.data[i + 1] = gg;
      img.data[i + 2] = b;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const blob = await c.convertToBlob({ type: "image/png" });
  return blob.arrayBuffer();
}

/** Register the protocol once; returns the tile URL template for a DEM. */
export function demTileTemplate(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox"): string {
  const key = `${url}|${bounds.join(",")}|${encoding}`;
  if (!grids.has(key)) grids.set(key, loadGrid(url, bounds, encoding));
  if (!registered) {
    registered = true;
    maplibregl.addProtocol(DEM_PROTOCOL, async (params) => {
      const m = params.url.match(/^aabdem:\/\/([^/]+)\/(\d+)\/(\d+)\/(\d+)$/);
      if (!m) throw new Error("bad dem url");
      const k = decodeURIComponent(m[1]);
      const g = await grids.get(k);
      if (!g) throw new Error("dem not registered");
      const tk = params.url;
      let t = tileCache.get(tk);
      if (!t) {
        t = renderTile(g, Number(m[2]), Number(m[3]), Number(m[4]));
        tileCache.set(tk, t);
        if (tileCache.size > TILE_CACHE_MAX) tileCache.delete(tileCache.keys().next().value!);
      }
      // MapLibre may transfer the buffer to a worker; hand out a copy.
      return { data: (await t).slice(0) };
    });
  }
  return `${DEM_PROTOCOL}://${encodeURIComponent(key)}/{z}/{x}/{y}`;
}

export async function demStats(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox") {
  const key = `${url}|${bounds.join(",")}|${encoding}`;
  if (!grids.has(key)) grids.set(key, loadGrid(url, bounds, encoding));
  const g = await grids.get(key)!;
  return { min: g.min, max: g.max, base: g.base };
}
