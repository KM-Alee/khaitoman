import { describe, expect, it } from "vitest";
import { fromServerKind, isLive, objectiveUnit, paddedRange, toServerKind } from "./api";

describe("explore api helpers", () => {
  it("maps URL and server analysis kinds both ways", () => {
    expect(toServerKind("why-not")).toBe("why_not");
    expect(fromServerKind("why_not")).toBe("why-not");
    expect(fromServerKind("frontier")).toBe("frontier");
    expect(fromServerKind("nonsense")).toBeNull();
  });

  it("stops polling once the analysis or its job is terminal", () => {
    expect(isLive({ status: "running", job_state: "running" })).toBe(true);
    expect(isLive({ status: "queued", job_state: null })).toBe(true);
    expect(isLive({ status: "completed", job_state: "succeeded" })).toBe(false);
    // a crashed worker leaves the stored result "running" but the job failed
    expect(isLive({ status: "running", job_state: "failed" })).toBe(false);
    expect(isLive(null)).toBe(false);
  });

  it("derives the objective unit from its id", () => {
    expect(objectiveUnit("production_kg")).toBe("kg");
    expect(objectiveUnit("net_value_pkr")).toBe("PKR");
    expect(objectiveUnit(undefined)).toBe("");
  });

  it("pads a flat series instead of inventing a slope", () => {
    const r = paddedRange([150_000, 150_000, null])!;
    expect(r.min).toBeLessThan(150_000);
    expect(r.max).toBeGreaterThan(150_000);
    expect(paddedRange([null, undefined])).toBeNull();
  });
});
