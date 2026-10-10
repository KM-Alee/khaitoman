/**
 * Colour scales shared by map legends and charts. Colours come from the CSS tokens so
 * light/dark themes and the legend always agree. Pure presentation: input values are
 * server-computed metrics.
 */

export type ScaleKind = "sequential-yield" | "sequential-service" | "diverging" | "categorical";

export function cssVar(name: string, fallback = "#888888"): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function rgbToHex([r, g, b]: [number, number, number]): string {
  return "#" + [r, g, b].map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, "0")).join("");
}
export function mix(a: string, b: string, t: number): string {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  return rgbToHex([A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t]);
}
export function ramp(stops: string[], t: number): string {
  if (!Number.isFinite(t)) return stops[0];
  const x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  return mix(stops[i], stops[i + 1], x - i);
}

/** Relative luminance & WCAG contrast — used by tests and to pick legible label ink. */
export function luminance(hex: string): number {
  const c = hexToRgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

export function readPalette(prefix: "seq" | "svc"): string[] {
  return [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--${prefix}-${i}`));
}
export function readDiverging(): string[] {
  return ["--div-neg-2", "--div-neg-1", "--div-zero", "--div-pos-1", "--div-pos-2"].map((v) => cssVar(v));
}

export interface Scale {
  kind: ScaleKind;
  domain: [number, number];
  color: (v: number | null | undefined) => string;
  /** 0..1 for extrusion height; diverging returns |v|/max. */
  norm: (v: number | null | undefined) => number;
  stops: { t: number; color: string; value: number }[];
  noData: string;
}

export function niceDomain(values: number[], kind: ScaleKind): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (kind === "sequential-service") return [0, Math.max(1, ...finite.map((v) => Math.min(v, 1.5)))];
  if (!finite.length) return [0, 1];
  if (kind === "diverging") {
    const m = Math.max(...finite.map(Math.abs)) || 1;
    return [-m, m];
  }
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (lo === hi) {
    lo = lo * 0.9;
    hi = hi * 1.1 || 1;
  }
  return [lo, hi];
}

export function makeScale(kind: ScaleKind, values: number[], shared?: [number, number] | null): Scale {
  const domain = shared ?? niceDomain(values, kind);
  const noData = cssVar("--surface-sunken", "#e4e8e1");
  if (kind === "diverging") {
    const pal = readDiverging();
    const m = Math.max(Math.abs(domain[0]), Math.abs(domain[1])) || 1;
    return {
      kind,
      domain: [-m, m],
      color: (v) => (v === null || v === undefined || !Number.isFinite(v) ? noData : ramp(pal, (v / m + 1) / 2)),
      norm: (v) => (v === null || v === undefined || !Number.isFinite(v) ? 0 : Math.min(1, Math.abs(v) / m)),
      stops: pal.map((c, i) => ({ t: i / (pal.length - 1), color: c, value: -m + (2 * m * i) / (pal.length - 1) })),
      noData,
    };
  }
  const pal = kind === "sequential-service" ? readPalette("svc") : readPalette("seq");
  const [lo, hi] = domain;
  const span = hi - lo || 1;
  const t = (v: number) => (v - lo) / span;
  return {
    kind,
    domain,
    color: (v) => (v === null || v === undefined || !Number.isFinite(v) ? noData : ramp(pal, t(v))),
    norm: (v) => (v === null || v === undefined || !Number.isFinite(v) ? 0 : Math.max(0, Math.min(1, t(v)))),
    stops: pal.map((c, i) => ({ t: i / (pal.length - 1), color: c, value: lo + (span * i) / (pal.length - 1) })),
    noData,
  };
}

export const GROUP_COLORS = (): Record<string, string> => ({
  head: cssVar("--svc-4"),
  middle: cssVar("--seq-3"),
  tail: cssVar("--warning"),
});
