import { deflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { decodePng, decodeTerrarium } from "./demTiles";

function crc32(buf: Uint8Array) {
  let c = ~0;
  for (const b of buf) {
    c ^= b;
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
function chunk(type: string, body: Uint8Array) {
  const out = new Uint8Array(12 + body.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, body.length);
  out.set([...type].map((ch) => ch.charCodeAt(0)), 4);
  out.set(body, 8);
  dv.setUint32(8 + body.length, crc32(out.subarray(4, 8 + body.length)));
  return out;
}
/** RGB PNG with a different filter type on every row, so all five unfilter paths run. */
function png(w: number, h: number, px: Uint8Array) {
  const raw = new Uint8Array(h * (w * 3 + 1));
  for (let y = 0; y < h; y++) {
    const f = y % 5;
    raw[y * (w * 3 + 1)] = f;
    for (let x = 0; x < w * 3; x++) {
      const i = y * w * 3 + x;
      const a = x >= 3 ? px[i - 3] : 0;
      const b = y > 0 ? px[i - w * 3] : 0;
      const c = x >= 3 && y > 0 ? px[i - w * 3 - 3] : 0;
      const p = a + b - c;
      const pr = Math.abs(p - a) <= Math.abs(p - b) && Math.abs(p - a) <= Math.abs(p - c) ? a : Math.abs(p - b) <= Math.abs(p - c) ? b : c;
      const pred = [0, a, b, (a + b) >> 1, pr][f];
      raw[y * (w * 3 + 1) + 1 + x] = (px[i] - pred) & 255;
    }
  }
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, w);
  dv.setUint32(4, h);
  ihdr.set([8, 2, 0, 0, 0], 8);
  const parts = [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", new Uint8Array(deflateSync(raw))), chunk("IEND", new Uint8Array())];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out.buffer;
}

describe("decodePng", () => {
  it("returns the exact stored bytes for every filter type", async () => {
    const w = 7;
    const h = 10;
    const px = new Uint8Array(w * h * 3).map((_, i) => (i * 37 + (i >> 3) * 11) & 255);
    const d = await decodePng(png(w, h, px));
    expect([d.w, d.h, d.channels]).toEqual([w, h, 3]);
    expect(Array.from(d.px)).toEqual(Array.from(px));
  });

  it("keeps Terrarium elevations exact (no canvas in the path)", async () => {
    const px = new Uint8Array([128, 180, 64, 128, 181, 0]); // 180.25 m, 181 m
    const d = await decodePng(png(2, 1, px));
    expect(decodeTerrarium(d.px[0], d.px[1], d.px[2])).toBeCloseTo(180.25, 6);
    expect(decodeTerrarium(d.px[3], d.px[4], d.px[5])).toBe(181);
  });
});
