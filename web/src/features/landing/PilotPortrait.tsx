/**
 * A still "portrait" of a published pilot: its real Sentinel-2 display image with the
 * mapped canals and the reviewed, AI-drawn field boundaries drawn on top, all from the
 * local package (no tiles, no network). Geometry is placed with a local equirectangular
 * frame over the image corners, which is accurate to a pixel at this few-km scale.
 */
import { useMemo } from "react";
import { useGeoJSON, useMapBundle } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { Skeleton } from "@/components/status";

type Ring = [number, number][];

function rings(g: GeoJSON.Geometry | null | undefined): Ring[] {
  if (!g) return [];
  if (g.type === "Polygon") return g.coordinates as Ring[];
  if (g.type === "MultiPolygon") return (g.coordinates as Ring[][]).flat();
  return [];
}
function lines(g: GeoJSON.Geometry | null | undefined): Ring[] {
  if (!g) return [];
  if (g.type === "LineString") return [g.coordinates as Ring];
  if (g.type === "MultiLineString") return g.coordinates as Ring[];
  return [];
}

export function PilotPortrait({
  pilotId,
  version,
  className,
  highlightFieldId,
  showCanals = true,
  label,
}: {
  pilotId: string;
  version: string;
  className?: string;
  highlightFieldId?: string | null;
  showCanals?: boolean;
  label?: string;
}) {
  const map = useMapBundle(pilotId, version);
  const fields = useGeoJSON(map.data?.fields?.data ? null : map.data?.fields?.url ?? null);
  const canals = useGeoJSON(showCanals && !map.data?.canals?.data ? map.data?.canals?.url ?? null : null);
  const fieldsFC = (map.data?.fields?.data as GeoJSON.FeatureCollection | undefined) ?? fields.data ?? null;
  const canalsFC = (map.data?.canals?.data as GeoJSON.FeatureCollection | undefined) ?? canals.data ?? null;
  const im = map.data?.imagery[0];

  const frame = useMemo(() => {
    if (!im?.corners?.length) return null;
    const lons = im.corners.map((c) => c[0]);
    const lats = im.corners.map((c) => c[1]);
    const w = Math.min(...lons);
    const e = Math.max(...lons);
    const s = Math.min(...lats);
    const n = Math.max(...lats);
    const k = Math.cos((((n + s) / 2) * Math.PI) / 180);
    const W = 1000;
    const H = (W * (n - s)) / ((e - w) * k);
    const px = ([lon, lat]: [number, number]) => [((lon - w) / (e - w)) * W, ((n - lat) / (n - s)) * H] as const;
    return { W, H, px };
  }, [im]);

  const fieldPaths = useMemo(() => {
    if (!frame || !fieldsFC) return [];
    return fieldsFC.features.map((f) => {
      const id = String((f.properties as Record<string, unknown> | null)?.field_id ?? f.id ?? "");
      const group = String((f.properties as Record<string, unknown> | null)?.group ?? "");
      const d = rings(f.geometry)
        .map((r) => r.map((c, i) => `${i ? "L" : "M"}${frame.px(c).map((v) => v.toFixed(1)).join(" ")}`).join("") + "Z")
        .join("");
      return { id, group, d };
    });
  }, [frame, fieldsFC]);
  const canalPaths = useMemo(() => {
    if (!frame || !canalsFC) return [];
    return canalsFC.features.flatMap((f) => lines(f.geometry).map((r) => r.map((c, i) => `${i ? "L" : "M"}${frame.px(c).map((v) => v.toFixed(1)).join(" ")}`).join("")));
  }, [frame, canalsFC]);

  // Frame the reviewed fields (padded) rather than the whole scene.
  const view = useMemo(() => {
    if (!frame) return null;
    if (!fieldsFC?.features.length) return `0 0 ${frame.W} ${frame.H.toFixed(1)}`;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const f of fieldsFC.features)
      for (const r of rings(f.geometry))
        for (const c of r) {
          const [x, y] = frame.px(c);
          x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
        }
    const pad = Math.max(x1 - x0, y1 - y0) * 0.14;
    const side = Math.max(x1 - x0, y1 - y0) + pad * 2;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    return `${(cx - side / 2).toFixed(1)} ${(cy - side / 2).toFixed(1)} ${side.toFixed(1)} ${side.toFixed(1)}`;
  }, [frame, fieldsFC]);

  if (map.isLoading || (!fieldsFC && fields.isLoading)) return <Skeleton className={cn("aspect-square w-full", className)} />;
  if (!frame || !im?.url)
    return (
      <div className={cn("grid aspect-square w-full place-items-center rounded-[inherit] bg-surface-muted text-[12px] text-ink-tertiary", className)}>
        No imagery in this package
      </div>
    );
  return (
    <svg
      viewBox={view ?? `0 0 ${frame.W} ${frame.H.toFixed(1)}`}
      className={cn("block h-full w-full", className)}
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={label ?? `Sentinel-2 image of ${pilotId} with ${fieldPaths.length} reviewed field boundaries`}
    >
      <image href={im.url} x="0" y="0" width={frame.W} height={frame.H} preserveAspectRatio="none" style={{ filter: "saturate(1.08) contrast(1.05)" }} />
      <rect x="0" y="0" width={frame.W} height={frame.H} fill="rgb(9 30 31 / 0.18)" />
      {canalPaths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="#5fd0da" strokeOpacity="0.85" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      ))}
      {fieldPaths.map((f) => (
        <path
          key={f.id}
          d={f.d}
          fill={f.id === highlightFieldId ? "rgb(240 207 134 / 0.55)" : f.group === "tail" ? "rgb(240 207 134 / 0.22)" : "rgb(255 255 255 / 0.14)"}
          stroke={f.id === highlightFieldId ? "#f0cf86" : "#ffffff"}
          strokeOpacity={f.id === highlightFieldId ? 1 : 0.9}
          strokeWidth={f.id === highlightFieldId ? 3.2 : 1.6}
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}
