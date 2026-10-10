/**
 * Pilot-scoped data assembled from immutable, version-keyed queries.
 */
import { useMemo } from "react";
import { useGeoJSON, useMapBundle, usePilot, usePilots } from "@/lib/api/queries";
import type { FieldRecord } from "@/lib/api/types";
import { useSelection } from "./selection";

export interface FieldIndexEntry {
  id: string;
  label: string;
  group: FieldRecord["group"] | null;
  areaM2: number | null;
  props: Record<string, unknown>;
  geometry: GeoJSON.Geometry | null;
}

export function usePilotData() {
  const sel = useSelection();
  const pilots = usePilots();
  const pilot = usePilot(sel.pilotId, sel.version);
  const map = useMapBundle(sel.pilotId, sel.version);
  const fields = useGeoJSON(map.data?.fields?.url ?? null);
  const canals = useGeoJSON(map.data?.canals?.url ?? null);
  const aoi = useGeoJSON(map.data?.aoi?.url ?? null);
  const raw = useGeoJSON(map.data?.fieldsRaw?.url ?? null);

  const fieldsFC = map.data?.fields?.data ? (map.data.fields.data as GeoJSON.FeatureCollection) : fields.data ?? null;
  const canalsFC = map.data?.canals?.data ? (map.data.canals.data as GeoJSON.FeatureCollection) : canals.data ?? null;
  const aoiFC = map.data?.aoi?.data ? toFC(map.data.aoi.data) : aoi.data ?? null;
  const rawFC = map.data?.fieldsRaw?.data ? (map.data.fieldsRaw.data as GeoJSON.FeatureCollection) : raw.data ?? null;

  const fieldIndex = useMemo(() => {
    const idx = new Map<string, FieldIndexEntry>();
    for (const f of fieldsFC?.features ?? []) {
      const p = (f.properties ?? {}) as Record<string, unknown>;
      const id = String(p.field_id ?? f.id ?? "");
      if (!id) continue;
      idx.set(id, {
        id,
        label: String(p.label ?? id),
        group: (p.group as FieldRecord["group"]) ?? null,
        areaM2: typeof p.gross_area_m2 === "number" ? p.gross_area_m2 : null,
        props: p,
        geometry: f.geometry ?? null,
      });
    }
    return idx;
  }, [fieldsFC]);

  const sortedFields = useMemo(
    () => [...fieldIndex.values()].sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true })),
    [fieldIndex],
  );

  return {
    sel,
    pilots,
    pilot,
    map,
    fieldsFC,
    canalsFC,
    aoiFC,
    rawFC,
    fieldIndex,
    sortedFields,
    geoLoading: fields.isLoading || canals.isLoading,
    geoError: fields.error ?? canals.error ?? null,
  };
}

function toFC(d: GeoJSON.FeatureCollection | GeoJSON.Feature | GeoJSON.Geometry): GeoJSON.FeatureCollection {
  if (d.type === "FeatureCollection") return d;
  if (d.type === "Feature") return { type: "FeatureCollection", features: [d] };
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: d }] };
}
