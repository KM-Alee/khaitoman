/**
 * Stages 1–2 (PRD §5.3): draw or import a bounded AOI, show the server's area/limit check
 * and source availability before any job starts, then choose online acquisition or a
 * previously downloaded raw source package and start processing.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { FileUp, Globe2, Package, Play } from "lucide-react";
import { useUI } from "@/app/store";
import { describeError } from "@/lib/api/client";
import { formatArea, formatDateTime, formatNumber, shortId } from "@/lib/formatting";
import { Chip, StatePanel } from "@/components/status";
import { Button } from "@/components/ui/Button";
import { DL, Segmented, Select } from "@/components/ui/primitives";
import { toast } from "@/components/ui/Toast";
import type { LngLat } from "@/components/map/geo";
import { AoiDrawMap, type ContextLayer } from "./AoiDrawMap";
import { useAoiCheck, useCreateAndProcess, useRawPackages, type IntakeCreateBody, type RawPackage } from "./onboardingApi";
import { Alert, Card, ErrorAlert, IssueList, TextArea, TextField } from "./parts";
import { openRing, parsePolygon, ringToPolygon, sameRing } from "./wizard";

export function NewIntake({ context, onDraftChange }: { context: ContextLayer[]; onDraftChange: (closed: boolean) => void }) {
  const navigate = useNavigate();
  const trackJob = useUI((s) => s.trackJob);
  const [vertices, setVertices] = useState<LngLat[]>([]);
  const [closed, setClosed] = useState(false);
  const [mode, setMode] = useState<"online" | "raw_package">("raw_package");
  const [bundleRef, setBundleRef] = useState("");
  const [name, setName] = useState("");
  const [pilotId, setPilotId] = useState("");
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const packages = useRawPackages();
  const check = useAoiCheck();
  const start = useCreateAndProcess();

  const pkg: RawPackage | undefined = useMemo(() => packages.data?.packages.find((p) => p.bundle_ref === bundleRef), [packages.data, bundleRef]);
  const polygon = closed && vertices.length >= 3 ? ringToPolygon(vertices) : null;
  const polygonKey = polygon ? JSON.stringify(polygon) : "";
  const checkedKey = check.variables ? JSON.stringify(check.variables) : "";
  const checkCurrent = !!polygon && checkedKey === polygonKey;
  const result = checkCurrent ? check.data : undefined;
  const checkError = checkCurrent ? check.error : null;
  const pkgMismatch = mode === "raw_package" && !!pkg?.aoi && closed && !sameRing(vertices, pkg.aoi);

  useEffect(() => onDraftChange(closed), [closed, onDraftChange]);
  // Server check runs whenever a closed polygon changes; no client-side area is shown.
  useEffect(() => {
    if (polygon) check.mutate(polygon);
  }, [polygonKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const setRing = (v: LngLat[], c: boolean) => {
    setVertices(v);
    setClosed(c);
  };

  const choosePackage = (ref: string) => {
    setBundleRef(ref);
    const chosen = packages.data?.packages.find((p) => p.bundle_ref === ref);
    if (chosen?.aoi) setRing(openRing(chosen.aoi), true);
  };

  const importGeo = () => {
    try {
      setRing(parsePolygon(importText), true);
      setImportError(null);
    } catch (e) {
      setImportError((e as Error).message);
    }
  };

  const canStart =
    !!polygon &&
    !!result &&
    result.blockers.length === 0 &&
    !start.isPending &&
    (mode === "online" || (!!pkg && !pkgMismatch));

  const startProcessing = () => {
    if (!polygon) return;
    const body: IntakeCreateBody = {
      contract_version: "2.0.0",
      aoi: polygon as unknown as IntakeCreateBody["aoi"],
      source_mode: mode,
      name: name.trim() || null,
    };
    if (mode === "raw_package") body.raw_package_id = bundleRef;
    if (mode === "online" && pilotId.trim()) body.pilot_id = pilotId.trim();
    start.mutate(body, {
      onSuccess: ({ created, processing, processError }) => {
        const id = created.onboarding_id;
        if (processing) {
          trackJob({
            jobId: processing.job_id,
            label: `Onboarding · ${created.name ?? shortId(id)}`,
            operation: "onboarding.process",
            revisionId: null,
            pilotKey: `onboarding:${id}`,
          });
        } else if (processError) {
          const d = describeError(processError);
          toast({ tone: "danger", title: `Intake created; processing did not start: ${d.title}`, description: d.detail });
        }
        navigate(`/onboarding/${encodeURIComponent(id)}`);
      },
    });
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]" data-testid="onboarding-new">
      <section className="self-start overflow-hidden rounded-[18px] border border-border bg-surface shadow-1" aria-labelledby="aoi-h">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 id="aoi-h" className="text-[13px] font-semibold text-ink">
            1 · Draw the area of interest
          </h2>
          <div className="flex items-center gap-2 text-[12px] text-ink-secondary">
            <span aria-live="polite">
              {vertices.length} vertices{closed ? " · closed" : ""}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setRing([], false)} disabled={!vertices.length}>
              Clear
            </Button>
          </div>
        </div>
        <AoiDrawMap
          vertices={vertices}
          closed={closed}
          onChange={setRing}
          context={context}
          fitBbox={result?.bbox ?? null}
          className="h-[52vh] min-h-[340px] w-full outline-none"
          label="AOI drawing map. Click to add vertices; Enter closes the polygon; Backspace removes the last vertex; Escape clears."
        />
        <p className="border-t border-border px-4 py-2 text-[12px] text-ink-secondary">
          Click to add vertices; click the first vertex or press Enter to close. Dashed boxes are published pilot areas. Without a basemap key no tiles are
          loaded; imagery comes from the acquisition job or the raw package.
        </p>
      </section>

      <aside className="flex flex-col gap-3">
        <Card id="aoi-import" title="Or import GeoJSON" description="A single Polygon, Feature or one-feature FeatureCollection.">
          <TextArea
            label="AOI GeoJSON"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            rows={4}
            placeholder='{"type":"Polygon","coordinates":[[[72.23,30.65],…]]}'
            className="font-mono"
          />
          {importError ? (
            <p role="alert" className="mt-1 text-[12px] text-danger">
              GeoJSON not usable: {importError}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" icon={<FileUp size={13} aria-hidden />} onClick={importGeo} disabled={!importText.trim()}>
              Use GeoJSON
            </Button>
            <label className="inline-flex cursor-pointer items-center rounded-[8px] px-2 py-1 text-[12px] font-medium text-water-deep underline-offset-2 hover:underline focus-within:outline-2 focus-within:outline-focus">
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
        </Card>

        <Card id="aoi-check" title="Area and limits" description="Checked by the server before any job starts." testId="aoi-check">
          {!polygon ? (
            <p className="text-[13px] text-ink-secondary">Close the polygon or import one to check its area and source availability.</p>
          ) : check.isPending || !checkCurrent ? (
            <StatePanel state="busy" compact title="Checking the AOI with the server…" />
          ) : checkError ? (
            <ErrorAlert error={checkError} title="AOI rejected by the server" />
          ) : result ? (
            <div className="flex flex-col gap-2.5">
              <DL
                rows={[
                  ["Area", formatArea(result.area_m2, "ha", 1) + ` (${formatNumber(result.area_m2 / 1e6, 2)} km²)`],
                  ["Metric CRS", result.metric_crs],
                  ["Estimated 10 m pixels", formatNumber(result.estimated_pixels)],
                  ["Raw packages on this server", result.source_availability ? formatNumber(result.source_availability.raw_bundle_count) : "—"],
                  ["Online sources", result.source_availability?.online.replace(/_/g, " ") ?? "—"],
                ]}
              />
              <IssueList items={result.blockers} kind="blocker" />
              <IssueList items={result.warnings} kind="warning" />
              {result.blockers.length === 0 ? <Chip tone="vegetation">Within the server limits</Chip> : null}
              {result.source_availability?.note ? <p className="text-[12px] text-ink-secondary">{result.source_availability.note}</p> : null}
            </div>
          ) : null}
        </Card>

        <Card id="sources" title="2 · Sources" testId="sources">
          <Segmented
            label="Source mode"
            size="sm"
            value={mode}
            onChange={(v) => setMode(v as typeof mode)}
            options={[
              {
                value: "raw_package",
                label: (
                  <>
                    <Package size={13} aria-hidden /> Raw package
                  </>
                ),
              },
              {
                value: "online",
                label: (
                  <>
                    <Globe2 size={13} aria-hidden /> Online
                  </>
                ),
              },
            ]}
          />
          <p className="mt-2 text-[12px] text-ink-secondary">
            {mode === "raw_package"
              ? "Re-enters the same processing, review and validation code with a previously downloaded raw source package. This is not importing a finished pilot."
              : "Acquires Sentinel-2 windows and canal data online. Needs connectivity and may take minutes; the job reports its real stages."}
          </p>
          {mode === "raw_package" ? (
            <div className="mt-3 flex flex-col gap-2">
              {packages.isLoading ? (
                <StatePanel state="busy" compact title="Loading raw source packages…" />
              ) : packages.error ? (
                <ErrorAlert error={packages.error} title="Raw packages unavailable" />
              ) : !packages.data?.packages.length ? (
                <StatePanel state="empty" compact title="No raw source packages">
                  No bundle is stored under data/raw/bundles on this server. Use online acquisition or add a raw bundle.
                </StatePanel>
              ) : (
                <Select label="Raw source package" value={bundleRef} onChange={(e) => choosePackage(e.target.value)} data-testid="raw-package-select">
                  <option value="">Choose a package…</option>
                  {packages.data.packages.map((p) => (
                    <option key={p.bundle_ref} value={p.bundle_ref}>
                      {p.pilot_id ?? "unknown pilot"} · {p.bundle_id}
                      {p.created_at ? ` · ${formatDateTime(p.created_at)}` : ""}
                    </option>
                  ))}
                </Select>
              )}
              {pkg ? (
                <p className="break-all font-mono text-[11px] text-ink-tertiary">
                  {pkg.bundle_ref} · manifest {shortId(pkg.manifest_sha256, 12)}
                </p>
              ) : null}
              {pkg && !pkg.aoi ? (
                <Alert tone="warning" title="Package AOI not listed">
                  This server does not list the package AOI. Import the package’s aoi.geojson so the intake AOI matches it exactly.
                </Alert>
              ) : null}
              {pkgMismatch && pkg?.aoi ? (
                <Alert
                  tone="warning"
                  title="AOI differs from the package AOI"
                  action={
                    <Button size="sm" variant="secondary" onClick={() => setRing(openRing(pkg.aoi!), true)}>
                      Use the package AOI
                    </Button>
                  }
                >
                  A raw-package intake must use exactly the AOI the package was acquired for; the server refuses a different polygon.
                </Alert>
              ) : null}
            </div>
          ) : (
            <TextField className="mt-3" label="Pilot id (optional)" value={pilotId} onChange={(e) => setPilotId(e.target.value)} placeholder="e.g. pilot-c" hint="Needed at publish time if not set here." />
          )}
          <TextField className="mt-2" label="Region name (optional)" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. North distributary" />
          {start.error ? <ErrorAlert error={start.error} title="Could not create the intake" testId="start-error" /> : null}
          <Button
            className="mt-3 w-full"
            variant="primary"
            icon={<Play size={14} aria-hidden />}
            busy={start.isPending}
            disabled={!canStart}
            onClick={startProcessing}
            data-testid="start-onboarding"
          >
            Create intake and start processing
          </Button>
          {!canStart && !start.isPending ? (
            <p className="mt-1.5 text-[12px] text-ink-secondary" data-testid="start-hint">
              {!polygon
                ? "Close or import an AOI first."
                : !result
                  ? "Waiting for the server AOI check."
                  : result.blockers.length
                    ? "Resolve the AOI blockers first."
                    : mode === "raw_package" && !pkg
                      ? "Choose a raw source package."
                      : pkgMismatch
                        ? "Use the package AOI."
                        : null}
            </p>
          ) : null}
        </Card>
      </aside>
    </div>
  );
}
