/**
 * One intake (PRD §5.3 stages 3–7). Every section renders a real API record: the intake
 * view, its process job and stage events, its layers, the review result and the publish
 * response. Nothing advances on a timer; polling runs only while the server reports an
 * active job.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCw, Rocket, Square } from "lucide-react";
import { isTerminal, useUI } from "@/app/store";
import { describeError, ApiError } from "@/lib/api/client";
import { useCancelJob, usePilots } from "@/lib/api/queries";
import { formatArea, formatDateShort, formatDateTime, formatNumber, formatPercent, shortId } from "@/lib/formatting";
import { Chip, JobBadge, Progress, StatePanel } from "@/components/status";
import { Button, buttonClass } from "@/components/ui/Button";
import { DL } from "@/components/ui/primitives";
import { toast } from "@/components/ui/Toast";
import type { ContextLayer } from "./AoiDrawMap";
import {
  isJobActive,
  onbKeys,
  useIntakeLayer,
  useIntakeLayers,
  useProcess,
  usePublish,
  type IntakeView,
  type LayerList,
  type PublishBody,
} from "./onboardingApi";
import { Alert, Card, ErrorAlert, IssueList, TextField } from "./parts";
import { ReviewStage } from "./ReviewStage";
import { useStageLog } from "./useStageLog";
import { nextPilotVersion, useAttemptKey } from "./wizard";

const STATE_COPY: Record<string, { label: string; tone: "neutral" | "water" | "vegetation" | "warning" | "danger" }> = {
  created: { label: "Created", tone: "neutral" },
  queued: { label: "Queued", tone: "neutral" },
  acquired_raw: { label: "Raw sources acquired", tone: "water" },
  processed: { label: "Processed", tone: "water" },
  awaiting_inference: { label: "Awaiting inference", tone: "warning" },
  needs_review: { label: "Needs review", tone: "warning" },
  reviewed: { label: "Reviewed", tone: "vegetation" },
  validated: { label: "Validated", tone: "vegetation" },
  published: { label: "Published", tone: "vegetation" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function stateCopy(state: string) {
  return STATE_COPY[state] ?? { label: state.replace(/_/g, " "), tone: "neutral" as const };
}

const REVIEWABLE = new Set(["needs_review", "reviewed", "validated"]);

export function IntakeWorkspace({ view, context }: { view: IntakeView; context: ContextLayer[] }) {
  const qc = useQueryClient();
  const jobs = useUI((s) => s.jobs);
  const trackJob = useUI((s) => s.trackJob);
  const id = view.onboarding_id;
  const tracked = jobs.find((j) => j.jobId === view.job_id);
  const layers = useIntakeLayers(view);

  // Re-attach to a running process job after a reload; the API record is the source of truth.
  useEffect(() => {
    if (view.job_id && isJobActive(view.job_state) && !tracked) {
      trackJob({ jobId: view.job_id, label: `Onboarding · ${view.name ?? shortId(id)}`, operation: "onboarding.process", revisionId: null, pilotKey: `onboarding:${id}` });
    }
  }, [view.job_id, view.job_state, tracked, trackJob, id, view.name]);

  // When the watched job ends, refetch the intake record (state, blockers, lineage).
  const trackedState = tracked?.state;
  useEffect(() => {
    if (trackedState && isTerminal(trackedState)) void qc.invalidateQueries({ queryKey: onbKeys.intake(id) });
  }, [trackedState, qc, id]);

  const state = String(view.state);
  const st = stateCopy(state);
  const available = layers.data?.available ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-3" data-testid="intake" data-state={state}>
      <section id="intake-summary" className="scroll-mt-4 rounded-[14px] border border-border bg-surface p-4 shadow-1" aria-labelledby="intake-h">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="intake-h" className="text-[15px] font-semibold text-ink">
            {view.name ?? "Unnamed region"}
          </h2>
          <Chip tone={st.tone} size="md">
            <span data-testid="intake-state">{st.label}</span>
          </Chip>
          {view.job_state ? <JobBadge state={view.job_state} size="md" /> : null}
          {view.cache_hit ? <Chip tone="info">Inference cache hit</Chip> : null}
        </div>
        <DL
          className="mt-3 max-w-[640px]"
          rows={[
            ["Intake", <span className="font-mono text-[12px]">{id}</span>],
            ["Source", view.source_mode === "raw_package" ? "Raw source package" : view.source_mode === "online" ? "Online acquisition" : "—"],
            ["Package", <span className="font-mono text-[12px]">{view.bundle_ref ?? "—"}</span>],
            ["Pilot", view.pilot_id ?? "not set"],
            ["AOI area (server)", view.aoi_check ? formatArea(view.aoi_check.area_m2, "ha", 1) : "—"],
            ["Review version", `v${view.review_version}`],
            ["Updated", formatDateTime(view.updated_at)],
          ]}
        />
      </section>

      <ProcessingCard view={view} />

      {layers.error ? <ErrorAlert error={layers.error} title="Intake layers unavailable" /> : null}
      {available.length > 1 ? <SourcesCard view={view} layers={layers.data} /> : null}

      {REVIEWABLE.has(state) ? (
        <ReviewStage key={`${id}:${view.review_version}`} view={view} layers={layers.data} context={context} />
      ) : null}

      {REVIEWABLE.has(state) || state === "published" ? (
        <>
          <Card id="params" title="Crop, soil, rights and assets" description="PRD §5.3 parameters stage." testId="params">
            <Alert tone="info" title="Not editable through onboarding in this build">
              The onboarding API accepts field, network and review-rule edits only. The package builder applies its own crop, soil, rights and asset
              defaults, and the published pilot shows them as review flags (rights, cost evidence, crop calibration) in the workspace.
            </Alert>
          </Card>
          <ValidationCard view={view} />
          <PublishCard view={view} />
        </>
      ) : null}
    </div>
  );
}

function ProcessingCard({ view }: { view: IntakeView }) {
  const id = view.onboarding_id;
  const jobs = useUI((s) => s.jobs);
  const trackJob = useUI((s) => s.trackJob);
  const tracked = jobs.find((j) => j.jobId === view.job_id);
  const process = useProcess(id);
  const cancel = useCancelJob();
  const log = useStageLog(view.job_id);
  const state = String(view.state);
  const active = isJobActive(view.job_state) || (!!tracked && !isTerminal(tracked.state));
  const jobState = tracked && !isTerminal(tracked.state) ? tracked.state : view.job_state;
  const stage = (tracked && !isTerminal(tracked.state) ? tracked.stage : null) ?? view.job_stage;
  const progress = tracked && !isTerminal(tracked.state) && tracked.progress != null ? tracked.progress : view.progress;
  const failed = !active && (state === "failed" || view.job_state === "failed" || view.job_state === "interrupted" || state === "cancelled" || view.job_state === "cancelled");
  const needsStart = state === "created" && !view.job_id;
  const awaiting = state === "awaiting_inference";
  const showCard = active || failed || needsStart || awaiting || log.length > 0 || !!view.job_id;
  if (!showCard) return null;

  const retry = () =>
    process.mutate(undefined, {
      onSuccess: (r) => trackJob({ jobId: r.job_id, label: `Onboarding · ${view.name ?? shortId(id)}`, operation: "onboarding.process", revisionId: null, pilotKey: `onboarding:${id}` }),
      onError: (e) => {
        const d = describeError(e);
        toast({ tone: "danger", title: `Processing did not start: ${d.title}`, description: d.detail });
      },
    });

  return (
    <Card
      id="processing"
      title="3 · Imagery & fields: processing job"
      description="Stages and progress come from the worker's job events."
      testId="processing"
      aside={jobState ? <JobBadge state={jobState} size="md" /> : null}
    >
      {active ? (
        <div className="flex flex-col gap-2">
          <Progress value={progress} label="Onboarding processing progress" />
          <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-secondary">
            <span aria-live="polite" data-testid="job-stage">
              {stage ?? "Waiting for the first stage event…"}
            </span>
            {view.job_id ? (
              <Button size="sm" variant="ghost" icon={<Square size={12} aria-hidden />} onClick={() => cancel.mutate(view.job_id!)} disabled={jobState === "cancel_requested" || cancel.isPending}>
                Cancel job
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
      {needsStart ? (
        <Alert tone="info" title="Processing has not started" action={<Button size="sm" variant="primary" busy={process.isPending} onClick={retry}>Start processing</Button>}>
          The intake record exists but no process job was queued.
        </Alert>
      ) : null}
      {failed ? (
        <Alert
          tone="danger"
          testId="process-failed"
          title={
            view.job_state === "interrupted"
              ? "Processing was interrupted (the service restarted)"
              : state === "cancelled" || view.job_state === "cancelled"
                ? "Processing was cancelled"
                : "Processing failed"
          }
          action={
            <Button size="sm" variant="secondary" icon={<RefreshCw size={13} aria-hidden />} busy={process.isPending} onClick={retry}>
              Run processing again
            </Button>
          }
        >
          {view.error?.detail ?? tracked?.error ?? "The job ended without a result. Earlier records remain inspectable."}
          {view.error?.code ? <span className="ml-1 font-mono text-[11px]">({view.error.code})</span> : null}
        </Alert>
      ) : null}
      {awaiting ? (
        <Alert tone="warning" title="No cached field inference matches this imagery" testId="awaiting-inference">
          This build reuses a Delineate run by content hash and does not start vision inference from the UI. Run it with the command below, then process
          again.
          {view.inference?.command ? <code className="mt-1 block break-all rounded-[8px] bg-surface p-2 font-mono text-[11px] text-ink">{view.inference.command}</code> : null}
        </Alert>
      ) : null}
      {log.length ? (
        <ol className="mt-3 flex flex-col gap-1 border-t border-border pt-3" aria-label="Job stage events" data-testid="stage-log">
          {log.map((e) => (
            <li key={e.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-2 text-[12px]">
              <span className="num text-ink-tertiary">{formatDateTime(e.at).replace(" PKT", "")}</span>
              <span className="min-w-0 text-ink">
                <span className="font-medium">{e.type === "result" ? "result recorded" : e.stage}</span>
                {e.detail ? <span className="text-ink-secondary"> · {e.detail}</span> : null}
              </span>
              <span className="num text-ink-secondary">{e.progress != null ? formatPercent(e.progress) : ""}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </Card>
  );
}

function SourcesCard({ view, layers }: { view: IntakeView; layers: LayerList | undefined }) {
  const has = (l: string) => !!layers?.available.includes(l as never);
  const imagery = useIntakeLayer(view, "imagery", has("imagery"));
  const weather = useIntakeLayer(view, "weather", has("weather"));
  const terrain = useIntakeLayer(view, "terrain", has("terrain"));
  const inf = view.inference;
  const summary = view.review_summary;
  const w = weather.data?.weather as Record<string, unknown> | undefined;
  const t = terrain.data?.metadata as Record<string, unknown> | undefined;
  return (
    <Card id="sources-evidence" title="Imagery, inference and context" description="Read from the intake's processed layers." testId="sources-evidence">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Imagery scenes</h3>
          {imagery.isLoading ? (
            <StatePanel state="busy" compact title="Loading imagery metadata…" />
          ) : imagery.error ? (
            <ErrorAlert error={imagery.error} title="Imagery layer unavailable" />
          ) : imagery.data?.scenes.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]" data-testid="imagery-table">
                <caption className="sr-only">Imagery scenes used for this intake</caption>
                <thead className="text-ink-secondary">
                  <tr>
                    <th scope="col" className="py-1 pr-2 font-medium">Scene</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Date</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Scene cloud</th>
                    <th scope="col" className="py-1 pr-2 font-medium">AOI valid</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Resolution</th>
                    <th scope="col" className="py-1 font-medium">Bands</th>
                  </tr>
                </thead>
                <tbody className="text-ink">
                  {imagery.data.scenes.map((s) => (
                    <tr key={s.scene_id} className="border-t border-border">
                      <td className="py-1 pr-2 font-mono text-[11px]">{s.scene_id}</td>
                      <td className="py-1 pr-2">{formatDateShort(s.acquired_at.slice(0, 10))}</td>
                      <td className="num py-1 pr-2">{s.scene_cloud_cover != null ? formatPercent(s.scene_cloud_cover, 2) : "—"}</td>
                      <td className="num py-1 pr-2">{s.aoi_valid_fraction != null ? formatPercent(s.aoi_valid_fraction) : "—"}</td>
                      <td className="num py-1 pr-2">{formatNumber(s.resolution_m)} m</td>
                      <td className="py-1">{s.assets ? Object.keys(s.assets).join(", ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-[13px] text-ink-secondary">No imagery scene was written for this intake.</p>
          )}
          <h3 className="mb-1.5 mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Weather and terrain</h3>
          <DL
            rows={[
              ["Weather series", w ? <span className="font-mono text-[11px]">{String(w.weather_series_id ?? "—")}</span> : "—"],
              ["Weather years", w && Array.isArray(w.complete_years) ? `${(w.complete_years as number[])[0]}–${(w.complete_years as number[]).at(-1)} (${(w.complete_years as number[]).length} complete)` : "—"],
              ["Terrain elevation", t && typeof t.min_m === "number" && typeof t.max_m === "number" ? `${formatNumber(t.min_m, 1)}–${formatNumber(t.max_m, 1)} m` : "—"],
            ]}
          />
          {t?.note ? <p className="mt-1 text-[12px] text-ink-secondary">{String(t.note)}</p> : null}
        </div>
        <div className="min-w-0">
          <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Field inference</h3>
          {inf ? (
            <DL
              rows={[
                ["Inference", inf.inference_completed ? "completed" : "pending"],
                ["Cache", inf.cache_hit ? `hit (${inf.cache_hits.join(", ") || "content hash"})` : "miss"],
                ["Device (run record)", inf.device ?? "—"],
                ["Inference key", <span className="font-mono text-[11px]">{inf.inference_key ?? "—"}</span>],
                ["Output sha256", <span className="font-mono text-[11px]">{shortId(inf.gpkg_sha256, 16)}</span>],
                ["Run record", <span className="font-mono text-[11px]">{inf.run_record ?? "—"}</span>],
              ]}
            />
          ) : (
            <p className="text-[13px] text-ink-secondary">No inference lineage recorded yet.</p>
          )}
          <h3 className="mb-1.5 mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Review summary</h3>
          {summary ? (
            <>
              <DL
                rows={[
                  ["Raw polygons", summary.raw_polygons != null ? formatNumber(summary.raw_polygons) : "—"],
                  ["Eligible", summary.eligible != null ? formatNumber(summary.eligible) : "—"],
                  ["Selected", summary.selected != null ? `${formatNumber(summary.selected)} of ${summary.config?.target_count ?? "—"}` : "—"],
                  ["Rejected by rules", summary.rejected != null ? formatNumber(summary.rejected) : "—"],
                  ["Manual edits", summary.manual_edits != null ? formatNumber(summary.manual_edits) : "—"],
                  ["Selected and corrected", summary.selected_corrected != null ? formatNumber(summary.selected_corrected) : "—"],
                  ["Correction rate", summary.selected_correction_rate != null ? formatPercent(summary.selected_correction_rate, 1) : "—"],
                  ["Rules", summary.rules_version ?? "—"],
                ]}
              />
              {summary.accuracy_metrics ? <p className="mt-1 text-[12px] text-ink-secondary">Accuracy: {summary.accuracy_metrics.replace(/_/g, " ")}</p> : null}
            </>
          ) : (
            <p className="text-[13px] text-ink-secondary">No review summary yet.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function ValidationCard({ view }: { view: IntakeView }) {
  const v = view.validation;
  const publishBlockers = v.publish_blockers;
  const none = v.blockers.length === 0 && (publishBlockers?.length ?? 0) === 0;
  return (
    <Card id="validation" title="6 · Validation" description="Blockers prevent publishing. Warnings may publish as explicit assumptions." testId="validation">
      <div className="flex flex-col gap-2">
        <IssueList items={v.blockers} kind="blocker" />
        {publishBlockers ? <IssueList items={publishBlockers} kind="blocker" /> : null}
        {none && publishBlockers ? <Chip tone="vegetation">No structural blockers reported by the server</Chip> : null}
        {none && !publishBlockers ? (
          <p className="text-[13px] text-ink-secondary">This server does not report publish checks before publishing; publish shows any structural error it finds.</p>
        ) : null}
        <IssueList items={v.warnings} kind="warning" />
      </div>
    </Card>
  );
}

function PublishCard({ view }: { view: IntakeView }) {
  const navigate = useNavigate();
  const trackJob = useUI((s) => s.trackJob);
  const pilots = usePilots();
  const publish = usePublish(view.onboarding_id);
  const keyFor = useAttemptKey(`publish-${view.onboarding_id}`);
  const [pilotId, setPilotId] = useState(view.pilot_id ?? "");
  const versions = useMemo(
    () => Array.from(new Set((pilots.data ?? []).filter((p) => p.pilot_id === pilotId).flatMap((p) => [p.pilot_version, ...(p.versions ?? [])]))),
    [pilots.data, pilotId],
  );
  const suggested = nextPilotVersion(versions);
  const [version, setVersion] = useState<string | null>(null);
  const pilotVersion = version ?? suggested;
  const state = String(view.state);

  if (state === "published" && view.pilot_id && view.pilot_version) {
    const href = `/p/${encodeURIComponent(view.pilot_id)}/${encodeURIComponent(view.pilot_version)}/workspace`;
    return (
      <Card id="publish" title="7 · Publish" testId="publish">
        <Alert tone="success" title={`Published ${view.pilot_id} / ${view.pilot_version}`} action={<Link to={href} className={buttonClass("primary", "sm")}>Open the workspace <ArrowRight size={13} aria-hidden /></Link>}>
          This version is immutable. Older libraries are flagged rather than reused as current.
        </Alert>
      </Card>
    );
  }

  const blockers = view.validation.blockers.length + (view.validation.publish_blockers?.length ?? 0);
  const ready = (state === "reviewed" || state === "validated") && blockers === 0;
  const err = publish.error;
  const conflict = err instanceof ApiError && err.status === 409;

  const submit = () => {
    const body: PublishBody = { contract_version: "2.0.0", pilot_id: pilotId.trim() || null, pilot_version: pilotVersion.trim() };
    publish.mutate(
      { body, key: keyFor(body) },
      {
        onSuccess: (r) => {
          const pilotKey = `${r.pilot_id}@${r.pilot_version}`;
          for (const j of r.jobs ?? []) {
            trackJob({ jobId: j.job_id, label: j.operation === "onboarding.baseline" ? "Baseline readiness" : "Candidate readiness", operation: j.operation, revisionId: null, pilotKey });
          }
          toast({ tone: "success", title: "Published a new immutable pilot version", description: `${r.pilot_id} / ${r.pilot_version}` });
          navigate(`/p/${encodeURIComponent(r.pilot_id)}/${encodeURIComponent(r.pilot_version)}/workspace`);
        },
      },
    );
  };

  return (
    <Card id="publish" title="7 · Publish" description="Creates an immutable pilot version. An existing version is never replaced." testId="publish">
      <form
        className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) submit();
        }}
      >
        <TextField
          label="Pilot id"
          value={pilotId}
          onChange={(e) => setPilotId(e.target.value)}
          readOnly={!!view.pilot_id}
          hint={view.pilot_id ? "Set by the intake; the server refuses a different pilot." : "Required. One path segment, e.g. pilot-c."}
          required
        />
        <TextField
          label="New pilot version"
          value={pilotVersion}
          onChange={(e) => setVersion(e.target.value)}
          hint={versions.length ? `Published: ${versions.join(", ")}` : "No published version of this pilot yet."}
          required
          data-testid="publish-version"
        />
        <Button type="submit" variant="primary" icon={<Rocket size={14} aria-hidden />} busy={publish.isPending} disabled={!ready || !pilotVersion.trim() || !pilotId.trim()} data-testid="publish-button" className="sm:mb-[22px]">
          Publish
        </Button>
      </form>
      {!ready ? (
        <p className="mt-2 text-[12px] text-ink-secondary" data-testid="publish-hint">
          {state === "needs_review" ? "Apply a review first." : blockers ? "Resolve the blockers above first." : "Publishing opens after review."}
        </p>
      ) : null}
      {err ? (
        conflict ? (
          <Alert tone="danger" title="That version already exists" testId="publish-error" className="mt-3">
            {(err as ApiError).message} Choose a new version name; published versions are immutable.
          </Alert>
        ) : (
          <div className="mt-3">
            <ErrorAlert error={err} title={`Publish refused: ${describeError(err).title}`} testId="publish-error" />
          </div>
        )
      ) : null}
    </Card>
  );
}
