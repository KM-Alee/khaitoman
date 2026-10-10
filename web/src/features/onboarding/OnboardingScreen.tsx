/**
 * Guided regional onboarding (F03, PRD §5.3): AOI → sources → imagery/fields → graph →
 * parameters → validation → publish. Every stage reflects a real API record or job; nothing
 * advances on a timer.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, CircleDot, FileUp, Globe2, Package, Rocket } from "lucide-react";
import { api, describeError } from "@/lib/api/client";
import { usePilots } from "@/lib/api/queries";
import { formatNumber } from "@/lib/formatting";
import { useUI } from "@/app/store";
import { BrandMark } from "@/components/layout/NavigationRail";
import { ConnectionState } from "@/components/layout/ContextBar";
import { JobTray, JobWatchers } from "@/components/layout/JobTray";
import { Chip, JobBadge, Progress, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { Eyebrow, Segmented } from "@/components/ui/primitives";
import { toast } from "@/components/ui/Toast";
import type { LngLat } from "@/components/map/geo";
import { AoiDrawMap, ringAreaM2, type ContextLayer } from "./AoiDrawMap";
import { cn } from "@/lib/cn";

const STAGES = [
  { key: "aoi", label: "Area of interest" },
  { key: "sources", label: "Sources" },
  { key: "fields", label: "Imagery & fields" },
  { key: "graph", label: "Operational graph" },
  { key: "params", label: "Crop, soil, rights, assets" },
  { key: "validation", label: "Validation" },
  { key: "publish", label: "Publish" },
] as const;
type StageKey = (typeof STAGES)[number]["key"];

const MAX_AOI_KM2 = 25;

export function OnboardingScreen() {
  const { intakeId } = useParams();
  const navigate = useNavigate();
  const pilots = usePilots();
  const [vertices, setVertices] = useState<LngLat[]>([]);
  const [closed, setClosed] = useState(false);
  const [mode, setMode] = useState<"online" | "raw_package">("raw_package");
  const [rawPackage, setRawPackage] = useState("");
  const [name, setName] = useState("");
  const [importText, setImportText] = useState("");
  const trackJob = useUI((s) => s.trackJob);
  const jobs = useUI((s) => s.jobs);

  const intake = useQuery({
    queryKey: ["onboarding", intakeId ?? ""],
    enabled: !!intakeId,
    queryFn: () => api.get<Record<string, unknown>>(`/onboarding/${encodeURIComponent(intakeId!)}`),
    refetchInterval: 2000,
  });

  const context: ContextLayer[] = useMemo(
    () =>
      (pilots.data ?? [])
        .filter((p) => p.aoi_bbox)
        .map((p) => ({
          id: p.pilot_id,
          bbox: p.aoi_bbox!,
          label: p.name,
          image: (p as unknown as { imagery?: { display_image_ref?: string; display_corners_wgs84?: [number, number][] }[] }).imagery?.[0]
            ? {
                url: `/assets/pilots/${p.pilot_id}/${p.pilot_version}/${(p as unknown as { imagery: { display_image_ref: string }[] }).imagery[0].display_image_ref}`,
                corners: (p as unknown as { imagery: { display_corners_wgs84: [number, number][] }[] }).imagery[0].display_corners_wgs84,
              }
            : null,
        })),
    [pilots.data],
  );

  const areaKm2 = closed ? ringAreaM2(vertices) / 1e6 : 0;
  const tooBig = areaKm2 > MAX_AOI_KM2;

  const create = useMutation({
    mutationFn: () =>
      api.post<Record<string, unknown>>(
        "/onboarding",
        {
          name: name || undefined,
          aoi: { type: "Polygon", coordinates: [[...vertices, vertices[0]]] },
          source_mode: mode,
          raw_package_id: mode === "raw_package" ? rawPackage || undefined : undefined,
        },
        { idempotent: true },
      ),
    onSuccess: async (r) => {
      const id = String(r.intake_id ?? r.onboarding_id ?? r.id ?? "");
      if (!id) return;
      try {
        const p = await api.post<Record<string, unknown>>(`/onboarding/${encodeURIComponent(id)}/process`, {}, { idempotent: true });
        if (p.job_id) trackJob({ jobId: String(p.job_id), label: "Onboarding: acquire & process", operation: "onboarding", revisionId: null, pilotKey: `onboarding:${id}` });
      } catch (e) {
        const d = describeError(e);
        toast({ tone: "danger", title: d.title, description: d.detail });
      }
      navigate(`/onboarding/${encodeURIComponent(id)}`);
    },
    onError: (e) => {
      const d = describeError(e);
      toast({ tone: "danger", title: `Could not start onboarding: ${d.title}`, description: d.detail });
    },
  });

  const publish = useMutation({
    mutationFn: () => api.post<Record<string, unknown>>(`/onboarding/${encodeURIComponent(intakeId!)}/publish`, {}, { idempotent: true }),
    onSuccess: (r) => {
      const pid = r.pilot_id as string | undefined;
      const v = r.pilot_version as string | undefined;
      toast({ tone: "success", title: "Published a new immutable pilot version", description: pid && v ? `${pid}@${v}` : undefined });
      if (pid && v) navigate(`/p/${encodeURIComponent(pid)}/${encodeURIComponent(v)}/workspace`);
    },
    onError: (e) => {
      const d = describeError(e);
      toast({ tone: "danger", title: `Publish blocked: ${d.title}`, description: d.detail });
    },
  });

  const it = intake.data;
  const stageFromApi = String(it?.stage ?? it?.state ?? "");
  const blockers = (it?.blockers as string[] | undefined) ?? ((it?.validation as Record<string, unknown> | undefined)?.blockers as string[] | undefined) ?? [];
  const warnings = (it?.warnings as string[] | undefined) ?? ((it?.validation as Record<string, unknown> | undefined)?.warnings as string[] | undefined) ?? [];
  const review = (it?.review ?? it?.review_summary ?? null) as Record<string, unknown> | null;
  const job = jobs.find((j) => j.pilotKey === `onboarding:${intakeId}`);
  const current: StageKey = !intakeId ? (closed ? "sources" : "aoi") : stageKeyFrom(stageFromApi);

  const importGeo = () => {
    try {
      const g = JSON.parse(importText);
      const geom = g.type === "FeatureCollection" ? g.features[0]?.geometry : g.type === "Feature" ? g.geometry : g;
      const ring = (geom?.type === "Polygon" ? geom.coordinates[0] : geom?.type === "MultiPolygon" ? geom.coordinates[0][0] : null) as LngLat[] | null;
      if (!ring || ring.length < 4) throw new Error("Expected a Polygon");
      setVertices(ring.slice(0, -1));
      setClosed(true);
    } catch (e) {
      toast({ tone: "warning", title: "GeoJSON not usable", description: (e as Error).message });
    }
  };

  return (
    <div className="flex h-dvh flex-col bg-canvas" data-testid="onboarding">
      <JobWatchers />
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <Link to="/" className="flex items-center gap-2 rounded-[10px] px-1.5 py-1 text-ink-secondary hover:text-ink" aria-label="Back to pilots">
          <ArrowLeft size={16} aria-hidden />
          <BrandMark className="h-8 w-8" />
        </Link>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">Add region</div>
          <h1 className="text-[15px] font-semibold text-ink">Guided onboarding</h1>
        </div>
        <div className="ml-auto">
          <ConnectionState />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label="Onboarding stages" className="shrink-0 border-b border-border bg-surface p-3 md:w-[260px] md:border-b-0 md:border-r md:p-4">
          <ol className="flex gap-1 overflow-x-auto md:flex-col">
            {STAGES.map((s, i) => {
              const ci = STAGES.findIndex((x) => x.key === current);
              const done = i < ci;
              const active = i === ci;
              return (
                <li key={s.key} className={cn("flex shrink-0 items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13px]", active ? "bg-water-soft font-semibold text-water-deep" : done ? "text-ink" : "text-ink-tertiary")} aria-current={active ? "step" : undefined}>
                  <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px]", done ? "border-vegetation bg-vegetation text-white" : active ? "border-water text-water-deep" : "border-border-strong/60")}>
                    {done ? <Check size={12} aria-hidden /> : i + 1}
                  </span>
                  {s.label}
                </li>
              );
            })}
          </ol>
        </nav>
        <main className="min-h-0 flex-1 overflow-y-auto p-3 md:p-5">
          {!intakeId ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <section className="overflow-hidden rounded-[14px] border border-border bg-surface shadow-1">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
                  <div className="text-[13px] font-semibold text-ink">Draw the area of interest</div>
                  <div className="flex items-center gap-2 text-[12px] text-ink-secondary">
                    {vertices.length} vertices
                    {closed ? <Chip size="sm" tone={tooBig ? "danger" : "vegetation"}>{formatNumber(areaKm2, 2)} km² · {formatNumber(areaKm2 * 100, 0)} ha</Chip> : null}
                    <Button size="sm" variant="ghost" onClick={() => { setVertices([]); setClosed(false); }}>
                      Clear
                    </Button>
                  </div>
                </div>
                <AoiDrawMap vertices={vertices} closed={closed} onChange={(v, c) => { setVertices(v); setClosed(c); }} context={context} className="h-[52vh] min-h-[360px] w-full outline-none" />
                <p className="border-t border-border px-4 py-2 text-[12px] text-ink-secondary">
                  Click to add vertices; click the first vertex or press Enter to close. Dashed boxes are published pilot areas. No basemap tiles are loaded — imagery is fetched by the acquisition job.
                </p>
              </section>
              <aside className="flex flex-col gap-3">
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Or import GeoJSON</Eyebrow>
                  <textarea
                    value={importText}
                    onChange={(e) => setImportText(e.target.value)}
                    rows={4}
                    aria-label="Paste AOI GeoJSON"
                    placeholder='{"type":"Polygon","coordinates":[[[72.5,30.8],…]]}'
                    className="w-full rounded-[10px] border border-border-strong/60 bg-surface p-2 font-mono text-[12px] text-ink"
                  />
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="secondary" icon={<FileUp size={13} />} onClick={importGeo} disabled={!importText.trim()}>
                      Use GeoJSON
                    </Button>
                    <label className="inline-flex cursor-pointer items-center text-[12px] font-medium text-water hover:underline">
                      Load file
                      <input
                        type="file"
                        accept=".geojson,.json,application/geo+json,application/json"
                        className="sr-only"
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          if (f) setImportText(await f.text());
                        }}
                      />
                    </label>
                  </div>
                </section>
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Area and limits</Eyebrow>
                  {closed ? (
                    <>
                      <div className="num text-[22px] font-semibold text-ink">{formatNumber(areaKm2, 2)} km²</div>
                      <p className={cn("mt-1 text-[12px]", tooBig ? "text-danger" : "text-ink-secondary")}>
                        {tooBig ? `Exceeds the ${MAX_AOI_KM2} km² window limit; retrieve windows, not whole-country rasters.` : `Within the ${MAX_AOI_KM2} km² acquisition window. The server validates again.`}
                      </p>
                      <p className="num mt-2 font-mono text-[11px] text-ink-tertiary">
                        {vertices.slice(0, 4).map((v) => `${v[0].toFixed(4)}, ${v[1].toFixed(4)}`).join(" · ")}
                        {vertices.length > 4 ? " …" : ""}
                      </p>
                    </>
                  ) : (
                    <p className="text-[12px] text-ink-secondary">Close the polygon to see its area and source availability.</p>
                  )}
                </section>
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Sources</Eyebrow>
                  <Segmented
                    label="Source mode"
                    size="sm"
                    value={mode}
                    onChange={(v) => setMode(v as typeof mode)}
                    options={[
                      { value: "raw_package", label: <><Package size={13} aria-hidden /> Raw package</> },
                      { value: "online", label: <><Globe2 size={13} aria-hidden /> Online</> },
                    ]}
                  />
                  <p className="mt-2 text-[12px] text-ink-secondary">
                    {mode === "raw_package"
                      ? "Re-enters the same processing, review and validation code with a previously downloaded raw source package. Not the same as importing a finished pilot."
                      : "Acquires Sentinel-2 windows and canal data online. Needs connectivity and may take minutes; real progress is shown."}
                  </p>
                  {mode === "raw_package" ? (
                    <input
                      value={rawPackage}
                      onChange={(e) => setRawPackage(e.target.value)}
                      placeholder="Raw package id (e.g. pilot-b-raw)"
                      aria-label="Raw package id"
                      className="mt-2 h-9 w-full rounded-[10px] border border-border-strong/60 bg-surface px-3 text-[13px] text-ink"
                    />
                  ) : null}
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Region name (optional)"
                    aria-label="Region name"
                    className="mt-2 h-9 w-full rounded-[10px] border border-border-strong/60 bg-surface px-3 text-[13px] text-ink"
                  />
                  <Button
                    className="mt-3 w-full"
                    variant="primary"
                    busy={create.isPending}
                    disabled={!closed || tooBig || (mode === "raw_package" && !rawPackage.trim())}
                    onClick={() => create.mutate()}
                    data-testid="start-onboarding"
                  >
                    Start processing
                  </Button>
                </section>
              </aside>
            </div>
          ) : intake.isLoading ? (
            <StatePanel state="busy" title="Loading intake record…" />
          ) : intake.error ? (
            <StatePanel state="error" error={intake.error} title="Intake record unavailable">
              {describeError(intake.error).detail} The onboarding API may not be implemented in this build yet.
            </StatePanel>
          ) : (
            <div className="mx-auto flex max-w-[860px] flex-col gap-3">
              <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                <div className="flex flex-wrap items-center gap-2">
                  <CircleDot size={16} className="text-water" aria-hidden />
                  <h2 className="text-[15px] font-semibold text-ink">Intake {intakeId}</h2>
                  <Chip>{stageFromApi || "unknown stage"}</Chip>
                  {job ? <JobBadge state={job.state} size="md" /> : null}
                </div>
                {job && !["succeeded", "failed", "cancelled", "interrupted"].includes(job.state) ? (
                  <div className="mt-3">
                    <Progress value={job.progress} label="Onboarding progress" />
                    <p className="mt-1 text-[12px] text-ink-secondary">{job.stage ?? "Waiting for the first stage event…"}</p>
                  </div>
                ) : null}
              </section>
              {review ? (
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Field review</Eyebrow>
                  <dl className="grid grid-cols-3 gap-3 text-[13px]">
                    {Object.entries(review)
                      .filter(([, v]) => typeof v !== "object")
                      .slice(0, 9)
                      .map(([k, v]) => (
                        <div key={k}>
                          <dt className="text-[12px] text-ink-secondary">{k.replace(/_/g, " ")}</dt>
                          <dd className="num font-semibold text-ink">{String(v)}</dd>
                        </div>
                      ))}
                  </dl>
                  <p className="mt-2 text-[12px] text-ink-secondary">Accuracy is reported only against an independent reference with an explained matching method.</p>
                </section>
              ) : null}
              <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                <Eyebrow className="mb-2">Validation</Eyebrow>
                {blockers.length || warnings.length ? (
                  <ul className="flex flex-col gap-1 text-[13px]">
                    {blockers.map((b, i) => (
                      <li key={`b${i}`} className="text-danger">Blocker: {b}</li>
                    ))}
                    {warnings.map((w, i) => (
                      <li key={`w${i}`} className="text-warning">Assumption / warning: {w}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-ink-secondary">No validation report yet.</p>
                )}
              </section>
              <div className="flex justify-end">
                <Button variant="primary" icon={<Rocket size={15} />} busy={publish.isPending} disabled={blockers.length > 0 || !/valid|review/i.test(stageFromApi)} onClick={() => publish.mutate()}>
                  Publish pilot version
                </Button>
              </div>
            </div>
          )}
        </main>
      </div>
      <div className="pointer-events-none fixed bottom-3 right-3 z-30">
        <JobTray />
      </div>
    </div>
  );
}

function stageKeyFrom(s: string): StageKey {
  if (/publish/.test(s)) return "publish";
  if (/valid/.test(s)) return "validation";
  if (/param|crop|soil|asset|right/.test(s)) return "params";
  if (/graph|topolog|network/.test(s)) return "graph";
  if (/field|imagery|infer|review|process/.test(s)) return "fields";
  return "sources";
}
