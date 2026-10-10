import { useSyncExternalStore } from "react";

/** Optional sub-metre display basemap (Esri World Imagery via ArcGIS Location Platform).
 * Display-only per Esri terms: never cached, never used for analysis or delineation.
 * Absent key or no network → the package Sentinel-2 scene underneath shows as before. */
export const HD_IMAGERY_KEY: string = (import.meta.env.VITE_ARCGIS_KEY as string | undefined)?.trim() ?? "";
export const HD_IMAGERY_ATTRIBUTION = "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community";
export const hdImageryTiles = (key: string) =>
  `https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?token=${encodeURIComponent(key)}`;


/** Session-wide key health: a 401/403/498 from Esri stops all HD requests until reload. */
export type HdStatus = "off" | "ok" | "rejected";
let status: HdStatus = HD_IMAGERY_KEY ? "ok" : "off";
const subs = new Set<() => void>();
export const hdStatus = (): HdStatus => status;
export const hdActive = () => status === "ok";
export const isRejection = (code: number | undefined) => code === 401 || code === 403 || code === 498 || code === 499;
export function markHdRejected() {
  if (status !== "ok") return;
  status = "rejected";
  subs.forEach((f) => f());
}
export function subscribeHd(fn: () => void): () => void {
  subs.add(fn);
  return () => subs.delete(fn);
}
export function useHdStatus(): HdStatus {
  return useSyncExternalStore(subscribeHd, hdStatus, hdStatus);
}
