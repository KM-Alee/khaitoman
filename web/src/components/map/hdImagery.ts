/** Optional sub-metre display basemap (Esri World Imagery via ArcGIS Location Platform).
 * Display-only per Esri terms: never cached, never used for analysis or delineation.
 * Absent key or no network → the package Sentinel-2 scene underneath shows as before. */
export const HD_IMAGERY_KEY: string = (import.meta.env.VITE_ARCGIS_KEY as string | undefined)?.trim() ?? "";
export const HD_IMAGERY_ATTRIBUTION = "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community";
export const hdImageryTiles = (key: string) =>
  `https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?token=${encodeURIComponent(key)}`;

