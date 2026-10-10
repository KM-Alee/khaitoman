/**
 * Centralised presentation formatting (T10.1, T10.5). No analytical math lives here:
 * values arrive from the API; these helpers only render them with units.
 */
import { m2ToAcre, m2ToHa, type AreaUnit } from "@/lib/units";

const LOCALE = "en-US"; // deterministic western grouping; PKR magnitude words added separately
const TZ = "Asia/Karachi";

const nf = (min: number, max: number) =>
  new Intl.NumberFormat(LOCALE, { minimumFractionDigits: min, maximumFractionDigits: max });

export const MINUS = "−";

/** Format a finite number with grouping; uses a true minus sign. */
export function formatNumber(v: number, digits = 0, minDigits = 0): string {
  if (!Number.isFinite(v)) return "—";
  const s = nf(Math.min(minDigits, digits), digits).format(Math.abs(v));
  return (v < 0 && s !== nf(0, digits).format(0) ? MINUS : "") + s;
}

/** Sensible significant digits for a magnitude. */
export function autoDigits(v: number): number {
  const a = Math.abs(v);
  if (a === 0) return 0;
  if (a >= 100) return 0;
  if (a >= 10) return 1;
  if (a >= 1) return 2;
  return 3;
}

export function formatSigned(v: number, digits = 0): string {
  if (!Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  return (v > 0 ? "+" : "") + formatNumber(v, digits);
}

/** PKR always explicit, integer rupees with grouping: "PKR 1,250,000". */
export function formatPKR(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `PKR ${formatNumber(Math.round(v), 0)}`;
}

/** Compact PKR with South-Asian magnitude words: "PKR 12.5 lakh", "PKR 1.25 crore". */
export function formatPKRCompact(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? MINUS : "";
  if (a >= 1e7) return `PKR ${sign}${trim(a / 1e7, 2)} crore`;
  if (a >= 1e5) return `PKR ${sign}${trim(a / 1e5, 2)} lakh`;
  if (a >= 1e3) return `PKR ${sign}${trim(a / 1e3, 1)}k`;
  return `PKR ${sign}${formatNumber(a, 0)}`;
}

function trim(v: number, digits: number): string {
  return nf(0, digits).format(v);
}

export function formatArea(m2: number, unit: AreaUnit = "ha", digits?: number): string {
  if (!Number.isFinite(m2)) return "—";
  if (unit === "acre") {
    const a = m2ToAcre(m2);
    return `${formatNumber(a, digits ?? autoDigits(a))} acre`;
  }
  const h = m2ToHa(m2);
  return `${formatNumber(h, digits ?? autoDigits(h))} ha`;
}

/** Both units, e.g. "2.41 ha · 5.96 acre". */
export function formatAreaDual(m2: number): string {
  return `${formatArea(m2, "ha")} · ${formatArea(m2, "acre")}`;
}

export function formatVolume(m3: number): string {
  if (!Number.isFinite(m3)) return "—";
  const a = Math.abs(m3);
  if (a >= 1e6) return `${formatNumber(m3 / 1e6, 2)} Mm³`;
  if (a >= 1e4) return `${formatNumber(m3 / 1e3, 1)} thousand m³`;
  return `${formatNumber(m3, a >= 100 ? 0 : 1)} m³`;
}

export function formatMass(kg: number): string {
  if (!Number.isFinite(kg)) return "—";
  if (Math.abs(kg) >= 10_000) return `${formatNumber(kg / 1000, 1)} t`;
  return `${formatNumber(kg, 0)} kg`;
}

export function formatPercent(fraction: number, digits = 0): string {
  if (!Number.isFinite(fraction)) return "—";
  return `${formatNumber(fraction * 100, digits)}%`;
}

/** Render a value given a server unit string. Unknown units are printed verbatim. */
export function formatWithUnit(value: number, unit: string): string {
  const u = unit.trim();
  switch (u) {
    case "PKR":
    case "pkr":
      return formatPKR(value);
    case "kg":
      return formatMass(value);
    case "t":
      return `${formatNumber(value, autoDigits(value))} t`;
    case "kg/ha":
    case "kg_ha":
    case "kg ha-1":
      return `${formatNumber(value, 0)} kg/ha`;
    case "t/ha":
      return `${formatNumber(value, 2)} t/ha`;
    case "m3":
    case "m³":
      return formatVolume(value);
    case "mm":
      return `${formatNumber(value, value >= 100 ? 0 : 1)} mm`;
    case "fraction":
    case "ratio":
      return formatPercent(value, Math.abs(value) < 0.1 ? 1 : 0);
    case "percent":
    case "%":
      return `${formatNumber(value, 1)}%`;
    case "kg/m3":
    case "kg m-3":
      return `${formatNumber(value, 2)} kg/m³`;
    case "ha":
      return `${formatNumber(value, autoDigits(value))} ha`;
    case "m2":
      return formatArea(value, "ha");
    case "count":
    case "":
      return formatNumber(value, autoDigits(value));
    case "days":
    case "d":
      return `${formatNumber(value, 0)} d`;
    case "ms":
      return value >= 1000 ? `${formatNumber(value / 1000, 1)} s` : `${formatNumber(value, 0)} ms`;
    default:
      return `${formatNumber(value, autoDigits(value))} ${u.replace("m3", "m³").replace("m2", "m²")}`;
  }
}

/** Signed delta with unit; zero shown explicitly. */
export function formatDelta(value: number, unit: string): string {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return `±0 ${shortUnit(unit)}`.trim();
  const body = formatWithUnit(Math.abs(value), unit);
  return (value > 0 ? "+" : MINUS) + body;
}

export function shortUnit(unit: string): string {
  return unit === "fraction" ? "pp" : unit.replace("m3", "m³");
}

const dateFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" });
const dateShort = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ,
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Parse a date-only "YYYY-MM-DD" as a local crop date (noon UTC avoids TZ day shifts). */
export function parseDateOnly(s: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T12:00:00Z`);
  return new Date(s);
}

export function formatDate(s: string | Date | null | undefined): string {
  if (!s) return "—";
  const d = typeof s === "string" ? parseDateOnly(s) : s;
  return Number.isNaN(d.getTime()) ? "—" : dateFmt.format(d);
}
export function formatDateShort(s: string | Date): string {
  const d = typeof s === "string" ? parseDateOnly(s) : s;
  return Number.isNaN(d.getTime()) ? "—" : dateShort.format(d);
}
export function formatDateTime(s: string | Date | null | undefined): string {
  if (!s) return "—";
  const d = typeof s === "string" ? new Date(s) : s;
  return Number.isNaN(d.getTime()) ? "—" : `${dateTimeFmt.format(d)} PKT`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${formatNumber(s, s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

/** Truncate long immutable IDs for display while keeping them recognisable. */
export function shortId(id: string | null | undefined, keep = 8): string {
  if (!id) return "—";
  if (id.length <= keep + 4) return id;
  const parts = id.split(/[:_-]/);
  const tail = id.slice(-keep);
  return parts.length > 1 && parts[0].length <= 6 ? `${parts[0]}…${tail}` : `…${tail}`;
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
