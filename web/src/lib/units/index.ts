/**
 * Display-unit conversions (T10.5). Canonical values stay in SI/API units; these
 * functions only change presentation. Conversions are exact and documented.
 */

/** International acre, exactly 4046.8564224 m² (1 acre = 43 560 ft², 1 ft = 0.3048 m). */
export const M2_PER_ACRE = 4046.8564224;
export const M2_PER_HA = 10_000;

export type AreaUnit = "ha" | "acre";

export function m2ToHa(m2: number): number {
  return m2 / M2_PER_HA;
}
export function m2ToAcre(m2: number): number {
  return m2 / M2_PER_ACRE;
}
export function haToAcre(ha: number): number {
  return (ha * M2_PER_HA) / M2_PER_ACRE;
}

/** Shortage % shown to the user ↔ canonical fraction sent to the API. */
export function percentToFraction(pct: number): number {
  return Math.round(pct * 1e6) / 1e8;
}
export function fractionToPercent(f: number): number {
  return Math.round(f * 1e8) / 1e6;
}

/** Depth (mm) over an area (m²) → volume (m³). 1 mm over 1 m² = 0.001 m³. */
export function mmOverAreaToM3(mm: number, areaM2: number): number {
  return (mm / 1000) * areaM2;
}

/** Parse a user-entered PKR amount ("1,250,000", "12.5 lakh", "1.2 crore", "3m") to an integer. */
export function parsePKR(input: string): number | null {
  const s = input.trim().toLowerCase().replace(/^pkr\s*/, "").replace(/rs\.?\s*/, "").replace(/,/g, "").replace(/_/g, "");
  if (!s) return null;
  const m = s.match(/^(\d+(?:\.\d+)?)\s*(k|thousand|lakh|lac|l|m|mn|million|cr|crore)?$/);
  if (!m) return null;
  const n = Number(m[1]);
  const mult: Record<string, number> = {
    k: 1e3,
    thousand: 1e3,
    lakh: 1e5,
    lac: 1e5,
    l: 1e5,
    m: 1e6,
    mn: 1e6,
    million: 1e6,
    cr: 1e7,
    crore: 1e7,
  };
  const v = n * (m[2] ? mult[m[2]] : 1);
  if (!Number.isFinite(v)) return null;
  // Never silently round upward (T10.5): truncate fractional rupees only.
  return Math.floor(v + 1e-9);
}
