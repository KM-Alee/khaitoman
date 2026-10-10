import { backendCredentials } from "@/lib/api/urls";
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
  lo: number;
  step: number;
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

/**
 * Decode an 8-bit, non-interlaced PNG (RGB or RGBA) straight from its bytes. Elevation is
 * packed into pixel values, so it must never pass through a canvas: browsers with
 * anti-fingerprinting (Brave, Firefox resistFingerprinting) or colour management perturb
 * canvas readback, and a one-level change in Terrarium red is a 256 m spike.
 */
export async function decodePng(buf: ArrayBuffer): Promise<{ w: number; h: number; channels: number; px: Uint8Array }> {
  const d = new DataView(buf);
  const u8 = new Uint8Array(buf);
  if (d.getUint32(0) !== 0x89504e47) throw new Error("not a PNG");
  let off = 8;
  let w = 0;
  let h = 0;
  let channels = 0;
  const idat: Uint8Array[] = [];
  while (off < u8.length) {
    const len = d.getUint32(off);
    const type = String.fromCharCode(u8[off + 4], u8[off + 5], u8[off + 6], u8[off + 7]);
    const body = u8.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") {
      w = d.getUint32(off + 8);
      h = d.getUint32(off + 12);
      const depth = body[8];
      const color = body[9];
      if (depth !== 8 || body[12] !== 0 || (color !== 2 && color !== 6)) throw new Error("unsupported DEM PNG");
      channels = color === 6 ? 4 : 3;
    } else if (type === "IDAT") idat.push(body);
    else if (type === "IEND") break;
    off += 12 + len;
  }
  const all = new Uint8Array(idat.reduce((n, c) => n + c.length, 0));
  idat.reduce((o, c) => (all.set(c, o), o + c.length), 0);
  const zipped = new ReadableStream<Uint8Array>({
    start(ctrl) {
      ctrl.enqueue(all);
      ctrl.close();
    },
  }).pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(zipped).arrayBuffer());
  const stride = w * channels;
  const px = new Uint8Array(h * stride);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)];
    const src = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const row = y * stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? px[row + x - channels] : 0;
      const b = y > 0 ? px[row - stride + x] : 0;
      const c = x >= channels && y > 0 ? px[row - stride + x - channels] : 0;
      let v = src[x];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      px[row + x] = v & 255;
    }
  }
  return { w, h, channels, px };
}

async function loadGrid(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox"): Promise<DemGrid> {
  const res = await fetch(url, { credentials: backendCredentials(url) });
  if (!res.ok) throw new Error(`DEM ${res.status}`);
  const { w, h, channels, px } = await decodePng(await res.arrayBuffer());
  const n = w * h;
  const elev = new Float32Array(n);
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  let cnt = 0;
  for (let i = 0; i < n; i++) {
    const k = i * channels;
    const transparent = channels === 4 && px[k + 3] === 0;
    const v = transparent ? Number.NaN : encoding === "mapbox" ? decodeMapbox(px[k], px[k + 1], px[k + 2]) : decodeTerrarium(px[k], px[k + 1], px[k + 2]);
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
  if (!cnt) {
    min = 0;
    max = 0;
  }
  const lo = min - 1;
  const step = Math.max(0.02, (max + 1 - lo) / 765);
  return { w, h, bounds, elev, base, min, max, lo, step };
}

/**
 * Tiles are written in a noise-tolerant custom encoding: elevation = (R + G + B) · step + lo,
 * with the three channels within one level of each other. A ±1 perturbation of any channel
 * (canvas farbling, PNG round trips) moves the surface by one step — centimetres here —
 * instead of hundreds of metres.
 */
function encodeTolerant(g: DemGrid, m: number): [number, number, number] {
  const n = Math.max(0, Math.min(765, Math.round((m - g.lo) / g.step)));
  const q = Math.floor(n / 3);
  const r = n - q * 3;
  return [Math.min(255, q + (r > 0 ? 1 : 0)), Math.min(255, q + (r > 1 ? 1 : 0)), q];
}

/** MapLibre raster-dem source fields for a registered DEM's tiles. */
export async function demEncoding(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox") {
  const g = await gridFor(url, bounds, encoding);
  return { encoding: "custom" as const, redFactor: g.step, greenFactor: g.step, blueFactor: g.step, baseShift: -g.lo }; // MapLibre subtracts baseShift
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
      const [r, gg, b] = encodeTolerant(g, sample(g, lon, lat));
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

function gridFor(url: string, bounds: DemGrid["bounds"], encoding: "terrarium" | "mapbox") {
  const key = `${url}|${bounds.join(",")}|${encoding}`;
  if (!grids.has(key)) grids.set(key, loadGrid(url, bounds, encoding));
  return grids.get(key)!;
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
  const g = await gridFor(url, bounds, encoding);
  return { min: g.min, max: g.max, base: g.base };
}

/**
 * MapLibre decodes DEM tiles through a canvas. Where readback is randomised beyond ±1 level
 * (e.g. Firefox resistFingerprinting), relief would turn into noise, so terrain stays off.
 */
let readbackOk: boolean | null = null;
export function canvasReadbackIsTrustworthy(): boolean {
  if (readbackOk !== null) return readbackOk;
  try {
    const c = document.createElement("canvas");
    c.width = 16;
    c.height = 16;
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    const img = ctx.createImageData(16, 16);
    for (let i = 0; i < img.data.length; i += 4) {
      img.data[i] = (i * 7) & 255;
      img.data[i + 1] = (i * 13) & 255;
      img.data[i + 2] = (i * 29) & 255;
      img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    const back = ctx.getImageData(0, 0, 16, 16).data;
    let worst = 0;
    for (let i = 0; i < back.length; i++) worst = Math.max(worst, Math.abs(back[i] - img.data[i]));
    readbackOk = worst <= 1;
  } catch {
    readbackOk = false;
  }
  return readbackOk;
}
