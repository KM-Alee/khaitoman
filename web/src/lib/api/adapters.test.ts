import { dateIndex, fieldMetricMap, findMetric, readMapBundle, readTimeline, assetUrl } from "./adapters";
import { metric } from "@/test/fixtures";

test("reads the PilotMap contract shape and keeps assets on the local origin", () => {
  const b = readMapBundle(
    {
      pilot_id: "pilot-a",
      pilot_version: "reviewed-v1",
      aoi_bbox: [72.306, 30.776, 72.33, 30.798],
      aoi_url: "/assets/pilots/pilot-a/reviewed-v1/aoi.geojson",
      fields_url: "/assets/pilots/pilot-a/reviewed-v1/fields.geojson",
      canals_url: "/assets/pilots/pilot-a/reviewed-v1/canals.geojson",
      fields_raw_url: null,
      imagery: [{ scene_id: "S2B_X", acquired_at: "2024-12-10T06:00:29Z", url: "imagery/S2B_X.webp", corners: [[1, 2], [3, 2], [3, 1], [1, 1]], evidence_id: "ev", resolution_m: 10 }],
      terrain: { url: "terrain/dem.png", bounds: [1, 2, 3, 4], encoding: "terrarium", min_m: 146.7, max_m: 160.3 },
      network: { nodes: [{ node_id: "src", kind: "source", lon: 1, lat: 2 }], edges: [] },
      assets: [],
      field_groups: { "field-001": "tail" },
      legends: [],
    },
    "pilot-a",
    "reviewed-v1",
  );
  expect(b.fields?.url).toBe("/assets/pilots/pilot-a/reviewed-v1/fields.geojson");
  expect(b.fieldsRaw).toBeNull();
  expect(b.imagery[0].url).toBe("/assets/pilots/pilot-a/reviewed-v1/imagery/S2B_X.webp");
  expect(b.terrain?.url).toBe("/assets/pilots/pilot-a/reviewed-v1/terrain/dem.png");
  expect(b.terrain?.minM).toBeCloseTo(146.7);
  expect(b.nodes).toHaveLength(1);
  expect(b.fieldGroups["field-001"]).toBe("tail");
  expect(assetUrl("p", "v", "./a/b.png")).toBe("/assets/pilots/p/v/a/b.png");
});

test("timeline keeps gaps as null and reads network flows and ponds", () => {
  const t = readTimeline(
    {
      run_id: "r",
      dates: ["2026-11-01", "2026-11-02", "2026-11-03"],
      series: [{ series_id: "canopy_cover", label: "Canopy cover", unit: "fraction", kind: "crop", values: [0.1, null, 0.3] }],
      edges: [{ edge_id: "e1", values: [0, 120.5, null] }],
      ponds: [{ asset_id: "pond-1", inventory_m3: [10, 20, 30], capacity_m3: 100 }],
      harvest: { date: "2027-04-20", yield_kg_ha: 4200 },
    },
    "r",
    "f",
  );
  expect(t.series[0].values).toEqual([0.1, null, 0.3]);
  expect(t.edgeFlows.e1).toEqual([0, 120.5, null]);
  expect(t.ponds["pond-1"].capacity).toBe(100);
  expect(t.harvest?.yieldKgHa).toBe(4200);
});

test("date cursor resolves to the last date at or before the target", () => {
  const d = ["2026-11-01", "2026-11-02", "2026-11-05"];
  expect(dateIndex(d, "2026-11-03")).toBe(1);
  expect(dateIndex(d, "2026-11-05")).toBe(2);
  expect(dateIndex(d, "2026-10-01")).toBe(-1);
  expect(dateIndex(d, null)).toBe(-1);
});

test("metric lookup separates run-level from per-field values", () => {
  const ms = [
    metric({ definition_id: "production_kg", value: 1000 }),
    metric({ definition_id: "yield_kg_ha", field_id: "f1", value: 4000, unit: "kg/ha" }),
    metric({ definition_id: "yield_kg_ha", field_id: "f2", value: 3000, unit: "kg/ha" }),
  ];
  expect(findMetric(ms, "production_kg")?.value).toBe(1000);
  expect(findMetric(ms, "yield_kg_ha")).toBeNull();
  const per = fieldMetricMap(ms, "yield_kg_ha");
  expect(per.size).toBe(2);
  expect(per.get("f2")?.value).toBe(3000);
});
