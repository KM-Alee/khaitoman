/**
 * Surrogate explorer (PRD §7.4, T8.4–T8.5): debounced, explicitly approximate yield preview
 * for a proposed gross irrigation schedule on one field, explicit out-of-domain refusal, and
 * "Verify with crop model" which runs the exact AquaCrop experiment as a job and records the
 * exact yield next to the preview. The preview never stands in for exact outputs.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, Plus, ShieldAlert, Sparkles, Trash2 } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useCapabilities, useField, useSeasons, useWeatherScenarios } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { formatDate, formatDateTime, formatDelta, formatPercent, formatWithUnit, shortId } from "@/lib/formatting";
import { Chip, EstimateBadge, JobBadge, StatePanel } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Eyebrow, Select, SliderField } from "@/components/ui/primitives";
import { Rows } from "@/features/impact/viewKit";
import { useAnalysisJob, useCreatePreview, usePreviewView, useVerifyPreview, type ExploreBase, type PreviewRequest, type PreviewView } from "./api";
import { Card, CardHeader } from "./kit";

interface Ev {
  date: string;
  mm: number;
}

export function Surrogate({ base }: { base: ExploreBase }) {
  const { sel, sortedFields } = usePilotData();
  const caps = useCapabilities();
  const seasons = useSeasons(sel.pilotId);
  const seasonId = base.revision.data?.revision.request.season_id ?? seasons.data?.[0]?.season_id;
  const season = seasons.data?.find((x) => x.season_id === seasonId);
  const weather = useWeatherScenarios(sel.pilotId, seasonId).data ?? [];
  const [fieldId, setFieldId] = useState<string>(sel.fieldId ?? "");
  const field = useField(sel.version, fieldId || null, sel.pilotId).data?.field;
  const [weatherId, setWeatherId] = useState<string>("");
  const [events, setEvents] = useState<Ev[]>([]);
  const [eff, setEff] = useState<number | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const create = useCreatePreview();
  const verify = useVerifyPreview();
  const trackJob = useUI((st) => st.trackJob);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!fieldId && (sel.fieldId || sortedFields[0])) setFieldId(sel.fieldId ?? sortedFields[0].id);
  }, [sel.fieldId, sortedFields, fieldId]);
  useEffect(() => {
    if (!weatherId && weather.length) setWeatherId((weather.find((w) => w.is_typical) ?? weather[0]).weather_scenario_id);
  }, [weather, weatherId]);
  useEffect(() => {
    if (events.length || !season) return;
    const start = new Date(`${(season.planting_date ?? season.start).slice(0, 10)}T12:00:00Z`);
    const mk = (d: number, mm: number) => ({ date: new Date(start.getTime() + d * 864e5).toISOString().slice(0, 10), mm });
    // A starting template the user edits; nothing is previewed until the inputs settle.
    setEvents([mk(0, 75), mk(25, 75), mk(55, 75), mk(85, 75)]);
  }, [season, events.length]);
  useEffect(() => setEff(null), [fieldId]);
  const efficiency = eff ?? field?.existing_application_efficiency ?? null;

  const body = useMemo<PreviewRequest | null>(
    () =>
      field && season && weatherId && events.length && efficiency !== null
        ? {
            crop_profile_id: season.crop_profile_id,
            soil_profile_id: field.soil_profile_id,
            application_efficiency: efficiency,
            season_id: season.season_id,
            weather_scenario_id: weatherId,
            pilot_id: sel.pilotId ?? null,
            schedule: events.filter((e) => e.date && e.mm > 0).map((e) => ({ date: e.date, gross_depth_mm: e.mm })),
          }
        : null,
    [field, season, weatherId, events, efficiency, sel.pilotId],
  );

  // Debounced preview after the inputs settle (150 ms: the model answers in milliseconds).
  useEffect(() => {
    if (!body) return;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      create.mutate(body, { onSuccess: (p) => setPreviewId(p.preview_id) });
    }, 150);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [JSON.stringify(body)]); // eslint-disable-line react-hooks/exhaustive-deps

  const pv = usePreviewView(previewId, false);
  const p = pv.data;
  const verifyJob = useAnalysisJob(p?.verify_job_id ?? null, !!p?.verify_job_id && !p?.verification);
  const gate = String(caps.data?.surrogate_gate ?? "unknown");
  const total = events.reduce((a, e) => a + (e.mm || 0), 0);
  const stale = create.isPending || (create.data && create.data.preview_id !== previewId);

  const startVerify = async () => {
    if (!p) return;
    try {
      const r = await verify.mutateAsync(p.preview_id);
      trackJob({ jobId: r.job_id, label: "Exact crop verification", operation: "surrogate_verify", revisionId: null, pilotKey: sel.pilotKey });
      void pv.refetch();
    } catch {
      /* surfaced through verify.error */
    }
  };

  return (
    <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_380px]" data-testid="surrogate">
      <Card>
        <CardHeader
          icon={<Sparkles size={16} className="text-warning" aria-hidden />}
          title="Surrogate explorer"
          aside={
            <Chip tone={gate === "passed" ? "vegetation" : "warning"} title="Held-out evaluation gate (T8.3)">
              Evaluation gate: {gate.replace(/_/g, " ")}
            </Chip>
          }
        >
          Try an irrigation schedule on one field and get a fast, explicitly approximate yield preview from a model trained on executed crop simulations. It guides which schedule to
          simulate next; it never replaces the exact crop model or water and rights validation.
        </CardHeader>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <Select label="Field" value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
            {sortedFields.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </Select>
          <Select label="Weather analog" value={weatherId} onChange={(e) => setWeatherId(e.target.value)}>
            {weather.map((w) => (
              <option key={w.weather_scenario_id} value={w.weather_scenario_id}>
                {w.label}
              </option>
            ))}
          </Select>
          <Select label="Application efficiency" value={efficiency === null ? "" : String(efficiency)} onChange={(e) => setEff(Number(e.target.value))}>
            {[...new Set([field?.existing_application_efficiency, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85].filter((x): x is number => typeof x === "number"))]
              .sort()
              .map((v) => (
                <option key={v} value={v}>
                  {formatPercent(v)}
                  {v === field?.existing_application_efficiency ? " (field's existing)" : ""}
                </option>
              ))}
          </Select>
        </div>
        <div className="mt-2 text-[12px] text-ink-tertiary">
          {season ? `${season.label ?? season.season_id} · crop profile ${season.crop_profile_id}` : "Loading season…"}
          {field ? ` · soil ${field.soil_profile_id.replace(/^[^:]+:/, "")}` : ""}
        </div>
        <div className="mt-4 rounded-[14px] border border-water/25 bg-water-soft/40 p-3" data-testid="instant-slider">
          <SliderField
            label="Water per irrigation (instant AI estimate)"
            value={events.length ? Math.max(...events.map((e) => e.mm)) : 75}
            min={0}
            max={150}
            step={5}
            unit="mm"
            format={(v) => String(v)}
            parse={(t) => Number(t)}
            onChange={(v) => setEvents((xs) => xs.map((x) => ({ ...x, mm: v })))}
            hint="Drag it: the trained model re-estimates the yield as you move. Then confirm one setting with the exact crop model."
          />
        </div>
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <Eyebrow>Gross irrigation schedule</Eyebrow>
            <span className="num text-[12px] text-ink-secondary">
              {events.length} events · {total} mm total
            </span>
          </div>
          <ul className="flex flex-col gap-1.5">
            {events.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <span className="num w-5 text-right text-[11px] text-ink-tertiary">{i + 1}</span>
                <input
                  type="date"
                  aria-label={`Event ${i + 1} date`}
                  value={e.date}
                  min={season?.start?.slice(0, 10)}
                  max={season?.end?.slice(0, 10)}
                  onChange={(ev) => setEvents((xs) => xs.map((x, j) => (j === i ? { ...x, date: ev.target.value } : x)))}
                  className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[13px] text-ink"
                />
                <label className="flex items-center gap-1 text-[12px] text-ink-secondary">
                  <input
                    type="number"
                    min={0}
                    max={300}
                    step={5}
                    aria-label={`Event ${i + 1} gross depth in millimetres`}
                    value={e.mm}
                    onChange={(ev) => setEvents((xs) => xs.map((x, j) => (j === i ? { ...x, mm: Math.max(0, Number(ev.target.value) || 0) } : x)))}
                    className="num h-8 w-[76px] rounded-[8px] border border-border-strong/60 bg-surface px-2 text-right text-[13px] text-ink"
                  />
                  mm
                </label>
                <IconButton label={`Remove event ${i + 1}`} size="sm" onClick={() => setEvents((xs) => xs.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </IconButton>
              </li>
            ))}
          </ul>
          <Button
            size="sm"
            variant="ghost"
            className="mt-1.5"
            icon={<Plus size={13} />}
            onClick={() =>
              setEvents((xs) => {
                const last = xs[xs.length - 1]?.date ?? season?.planting_date ?? season?.start ?? new Date().toISOString();
                const d = new Date(`${last.slice(0, 10)}T12:00:00Z`);
                return [...xs, { date: new Date(d.getTime() + 25 * 864e5).toISOString().slice(0, 10), mm: 75 }];
              })
            }
          >
            Add irrigation
          </Button>
        </div>
      </Card>

      <section className="flex flex-col gap-3" aria-live="polite" aria-label="Preview and exact result">
        {!body ? (
          <StatePanel state="empty" title="Choose a field and schedule">
            A preview appears shortly after the inputs settle.
          </StatePanel>
        ) : create.error && !stale ? (
          <StatePanel state={gate !== "passed" ? "blocked" : "error"} title={gate !== "passed" ? "Preview unavailable" : describeError(create.error).title}>
            {describeError(create.error).detail}
          </StatePanel>
        ) : !p ? (
          <div className="rounded-[14px] border border-warning/30 bg-surface p-4 shadow-1" aria-busy>
            <EstimateBadge kind="preview" />
            <div className="skeleton mt-3 h-8 w-40" />
          </div>
        ) : (
          <PreviewCard
            p={p}
            stale={!!stale}
            onVerify={startVerify}
            verifying={verify.isPending}
            verifyError={verify.error}
            elapsedMs={create.data?.preview_id === p.preview_id ? (create.data.elapsed_ms ?? null) : null}
          />
        )}
        {p && (p.verify_job_id || p.verification) ? <ExactCard p={p} jobState={verifyJob.data?.state ?? null} jobStage={verifyJob.data?.stage ?? null} jobError={verifyJob.data?.error ?? null} /> : null}
        <p className="px-1 text-[11px] leading-relaxed text-ink-tertiary">
          Crop replay is unavailable for preview-only schedules. A schedule used in a final plan needs exact crop outputs and full physical validation in a solve.
        </p>
      </section>
    </div>
  );
}

function PreviewCard({
  p,
  stale,
  onVerify,
  verifying,
  verifyError,
  elapsedMs,
}: {
  p: PreviewView;
  stale: boolean;
  onVerify: () => void;
  verifying: boolean;
  verifyError: unknown;
  elapsedMs: number | null;
}) {
  const ood = p.domain_status === "out_of_domain";
  const done = !!p.verification;
  const verifyBtn = (
    <Button className="mt-3 w-full" variant={ood ? "primary" : "secondary"} icon={<FlaskConical size={15} />} busy={verifying} disabled={stale || !!p.verify_job_id} onClick={onVerify} data-testid="verify-preview">
      {done ? "Exact result recorded" : p.verify_job_id ? "Crop model running…" : ood ? "Run crop model" : "Verify with crop model"}
    </Button>
  );
  return (
    <div className={stale ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={stale} data-testid="preview-card" data-domain={p.domain_status}>
      {ood ? (
        <div className="rounded-[14px] border border-warning/40 bg-warning-soft/70 p-4" data-testid="preview-ood">
          <div className="flex items-center justify-between gap-2">
            <EstimateBadge kind="preview" size="md" />
            <span className="font-mono text-[11px] text-ink-tertiary">{p.model_version}</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-[14px] font-semibold text-warning">
            <ShieldAlert size={16} aria-hidden /> {p.message ?? "Outside validated preview range — run crop model."}
          </div>
          <p className="mt-1 text-[12px] text-ink-secondary">No estimate is shown: these inputs fall outside the model's training domain.</p>
          <ul className="mt-2 list-disc pl-5 text-[12px] text-ink-secondary">
            {p.domain_reasons.map((r, i) => (
              <li key={i} className="num">
                {r}
              </li>
            ))}
          </ul>
          {verifyBtn}
        </div>
      ) : (
        <div className="rounded-[14px] border border-warning/30 bg-surface p-4 shadow-1" data-testid="preview-in-domain">
          <div className="flex items-center justify-between gap-2">
            <EstimateBadge kind="preview" size="md" />
            <span className="font-mono text-[11px] text-ink-tertiary">{p.model_version}</span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <Sparkles size={16} className="text-warning" aria-hidden />
            <span className="num text-[28px] font-semibold tracking-[-0.02em] text-ink" data-testid="preview-yield">
              {p.estimated_yield_kg_ha !== null ? formatWithUnit(p.estimated_yield_kg_ha, "kg/ha") : "—"}
            </span>
            <span className="text-[12px] text-ink-tertiary">preview (AI estimate)</span>
          </div>
          {elapsedMs !== null ? (
            <p className="num mt-1 text-[12px] text-water-deep" data-testid="preview-elapsed">
              Computed on the server in {elapsedMs < 10 ? elapsedMs.toFixed(1) : Math.round(elapsedMs)} ms (measured)
            </p>
          ) : null}
          {p.residual_band_kg_ha ? (
            <p className="num mt-1 text-[12px] text-ink-secondary">
              Held-out residual band {formatDelta(p.residual_band_kg_ha[0], "kg/ha")} to {formatDelta(p.residual_band_kg_ha[1], "kg/ha")} (empirical 5–95%, not a confidence interval)
            </p>
          ) : null}
          {verifyBtn}
        </div>
      )}
      {verifyError ? <p className="mt-2 text-[12px] text-danger">{describeError(verifyError).detail}</p> : null}
      <div className="mt-3 rounded-[12px] border border-border bg-surface px-3 py-2">
        <Rows
          rows={[
            ["Physical pre-check", <span key="pc">{p.physical_precheck_status.replace(/_/g, " ")}</span>],
            ["Preview", <span key="id" className="font-mono text-[11px]">{shortId(p.preview_id)}</span>],
            ["Features", <span key="fv" className="font-mono text-[11px]">{p.feature_version}</span>],
          ]}
        />
        <p className="mt-1 text-[11px] leading-relaxed text-ink-tertiary">{p.uncertainty_note}</p>
        {p.physical_precheck_reasons.length ? <p className="mt-1 text-[11px] text-ink-tertiary">{p.physical_precheck_reasons.join("; ")}</p> : null}
      </div>
    </div>
  );
}

function ExactCard({ p, jobState, jobStage, jobError }: { p: PreviewView; jobState: string | null; jobStage: string | null; jobError: Record<string, unknown> | null }) {
  const v = p.verification;
  return (
    <div className="rounded-[14px] border border-vegetation/30 bg-surface p-4 shadow-1" data-testid="exact-card">
      <div className="flex items-center justify-between gap-2">
        <EstimateBadge kind="exact" size="md" />
        {v ? <JobBadge state="succeeded" /> : jobState ? <JobBadge state={jobState as "running"} /> : null}
      </div>
      {v ? (
        <>
          <div className="num mt-3 text-[28px] font-semibold tracking-[-0.02em] text-ink" data-testid="exact-yield">
            {v.exact_yield_kg_ha !== null ? formatWithUnit(v.exact_yield_kg_ha, "kg/ha") : "Not reported"}
            <span className="ml-2 text-[12px] font-normal text-ink-tertiary">exact (crop model)</span>
          </div>
          <p className="mt-0.5 text-[12px] text-ink-secondary">
            {v.preview_minus_exact_kg_ha !== null
              ? `Preview − exact: ${formatDelta(v.preview_minus_exact_kg_ha, "kg/ha")}`
              : v.preview_domain_status === "out_of_domain"
                ? "No preview difference: the preview refused these inputs as out of domain."
                : "Preview difference not reported."}
          </p>
          <div className="mt-2">
            <Rows
              rows={[
                ["Seasonal irrigation", v.seasonal_irrigation_mm !== null ? formatWithUnit(v.seasonal_irrigation_mm, "mm") : "—"],
                ["Harvest", v.outcome?.actual_harvest_date ? formatDate(String(v.outcome.actual_harvest_date)) : v.has_finished === false ? "season did not finish" : "—"],
                ["Yield basis", String(v.outcome?.yield_basis ?? "—").replace(/_/g, " ")],
                ["Engine", v.outcome?.engine_name ? `${v.outcome.engine_name} ${v.outcome.engine_version ?? ""}` : "—"],
                ["Verified", formatDateTime(v.verified_at)],
              ]}
            />
          </div>
          {v.note ? <p className="mt-2 text-[11px] leading-relaxed text-ink-tertiary">{v.note}</p> : null}
        </>
      ) : jobState === "failed" || jobState === "interrupted" || jobState === "cancelled" ? (
        <p className="mt-2 text-[12px] text-danger" role="alert">
          The exact crop run {jobState}: {String((jobError as { detail?: string } | null)?.detail ?? "no detail reported")}. The preview remains approximate.
        </p>
      ) : (
        <p className="mt-2 text-[12px] text-ink-secondary">{jobStage ?? "Running the exact crop model…"} The preview card is not replaced until the exact result is recorded.</p>
      )}
    </div>
  );
}
