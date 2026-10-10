import {
  formatArea,
  formatAreaDual,
  formatDate,
  formatDelta,
  formatDuration,
  formatMass,
  formatNumber,
  formatPKR,
  formatPKRCompact,
  formatPercent,
  formatVolume,
  formatWithUnit,
  MINUS,
  shortId,
} from "@/lib/formatting";
import { M2_PER_ACRE, fractionToPercent, haToAcre, parsePKR, percentToFraction } from "@/lib/units";

describe("PKR", () => {
  test("explicit currency with grouping", () => {
    expect(formatPKR(1250000)).toBe("PKR 1,250,000");
    expect(formatPKR(0)).toBe("PKR 0");
  });
  test("compact uses lakh/crore magnitudes", () => {
    expect(formatPKRCompact(1250000)).toBe("PKR 12.5 lakh");
    expect(formatPKRCompact(25_000_000)).toBe("PKR 2.5 crore");
    expect(formatPKRCompact(4500)).toBe("PKR 4.5k");
    expect(formatPKRCompact(800)).toBe("PKR 800");
  });
  test("parses entry forms and never rounds up", () => {
    expect(parsePKR("1,250,000")).toBe(1250000);
    expect(parsePKR("PKR 12.5 lakh")).toBe(1250000);
    expect(parsePKR("1.2 crore")).toBe(12000000);
    expect(parsePKR("3m")).toBe(3000000);
    expect(parsePKR("999.99")).toBe(999);
    expect(parsePKR("abc")).toBeNull();
    expect(parsePKR("")).toBeNull();
    expect(parsePKR("-5")).toBeNull();
  });
});

describe("area", () => {
  test("exact acre conversion", () => {
    expect(M2_PER_ACRE).toBe(4046.8564224);
    expect(haToAcre(1)).toBeCloseTo(2.4710538, 6);
  });
  test("formats ha and acres", () => {
    expect(formatArea(24100)).toBe("2.41 ha");
    expect(formatArea(24100, "acre")).toBe("5.96 acre");
    expect(formatAreaDual(10000)).toBe("1 ha · 2.47 acre");
  });
});

describe("numbers and units", () => {
  test("true minus sign", () => {
    expect(formatNumber(-1234.5, 1)).toBe(`${MINUS}1,234.5`);
  });
  test("non-finite renders a dash, never zero", () => {
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatPKR(Number.POSITIVE_INFINITY)).toBe("—");
  });
  test("volume and mass magnitudes", () => {
    expect(formatVolume(512)).toBe("512 m³");
    expect(formatVolume(48_250)).toBe("48.3 thousand m³");
    expect(formatVolume(2_400_000)).toBe("2.40 Mm³");
    expect(formatMass(950)).toBe("950 kg");
    expect(formatMass(152_340)).toBe("152.3 t");
  });
  test("server unit strings", () => {
    expect(formatWithUnit(4321.7, "kg/ha")).toBe("4,322 kg/ha");
    expect(formatWithUnit(0.734, "fraction")).toBe("73%");
    expect(formatWithUnit(1.234, "kg/m3")).toBe("1.23 kg/m³");
    expect(formatWithUnit(150000, "PKR")).toBe("PKR 150,000");
    expect(formatWithUnit(3, "widgets")).toBe("3.00 widgets");
  });
  test("deltas are signed and zero is explicit", () => {
    expect(formatDelta(1200, "kg")).toBe("+1,200 kg");
    expect(formatDelta(-0.05, "fraction")).toBe(`${MINUS}5.0%`);
    expect(formatDelta(0, "kg")).toBe("±0 kg");
  });
  test("percent conversion is exact at display precision", () => {
    expect(percentToFraction(22)).toBe(0.22);
    expect(fractionToPercent(0.07)).toBe(7);
    expect(formatPercent(0.225, 1)).toBe("22.5%");
  });
});

describe("dates and ids", () => {
  test("date-only strings do not shift across time zones", () => {
    expect(formatDate("2026-11-15")).toBe("15 Nov 2026");
  });
  test("durations", () => {
    expect(formatDuration(420)).toBe("420 ms");
    expect(formatDuration(4200)).toBe("4.2 s");
    expect(formatDuration(75_000)).toBe("1 min 15 s");
  });
  test("short ids keep a recognisable tail", () => {
    expect(shortId("run_0123456789abcdef")).toBe("run…89abcdef");
    expect(shortId("abc")).toBe("abc");
  });
});
