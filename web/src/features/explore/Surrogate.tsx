/**
 * Surrogate explorer (F12, T8.5): debounced "Approximate preview" for a proposed schedule,
 * explicit OOD refusal, and "Verify with crop model" that starts a real job and replaces
 * the provisional card only when exact results return.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, Plus, ShieldAlert, Sparkles, Trash2 } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useCapabilities, useSurrogatePreview, useVerifyPreview } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { formatDelta, formatWithUnit, shortId } from "@/lib/formatting";
import { Chip, EstimateBadge, StatePanel, JobBadge } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Eyebrow, Select } from "@/components/ui/primitives";
import { useScenario } from "@/features/workspace/useScenario";
import { pickNum } from "./analysis";

interface Ev {
  date: string;
  mm: number;
}

export function Surrogate() {
  const { sel, sortedFields } = usePilotData();
  const s = useScenario();
  const caps = useCapabilities();
  const season = s.catalog.seasons.data?.find((x) => x.season_id === s.draft?.season_id);
  const weather = s.catalog.weather.data ?? [];
  const [fieldId, setFieldId] = useState<string>(sel.fieldId ?? "");
  const [weatherId, setWeatherId] = useState<string>("");
  const [events, setEvents] = useState<Ev[]>([]);
  const preview = useSurrogatePreview();
  const verify = useVerifyPreview();
  const trackJob = useUI((st) => st.trackJob);
  const jobs = useUI((st) => st.jobs);
  const [verifyJob, setVerifyJob] = useState<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!fieldId && sel.fieldId) setFieldId(sel.fieldId);
  }, [sel.fieldId, fieldId]);
  useEffect(() => {
    if (!weatherId && weather.length) setWeatherId((weather.find((w) => w.is_typical) ?? weather[0]).weather_scenario_id);
  }, [weather, weatherId]);
  useEffect(() => {
    if (events.length || !season) return;
    const start = new Date(`${(season.planting_date ?? season.start).slice(0, 10)}T12:00:00Z`);
    const mk = (d: number, mm: number) => ({ date: new Date(start.getTime() + d * 864e5).toISOString().slice(0, 10), mm });
    // Starting template the user edits; the preview only runs on explicit inputs below.
    setEvents([mk(0, 75), mk(25, 75), mk(55, 75), mk(85, 75)]);
  }, [season, events.length]);

  const body = useMemo(
    () =>
      fieldId && weatherId && events.length && sel.pilotId && s.draft
        ? { pilot_id: sel.pilotId, pilot_version: sel.version, season_id: s.draft.season_id, field_id: fieldId, weather_scenario_id: weatherId, schedule: events.map((e) => ({ date: e.date, gross_depth_mm: e.mm })) }
        : null,
    [fieldId, weatherId, events, sel.pilotId, sel.version, s.draft],
  );

  // Debounced preview on input change (≥ 400 ms after the last edit), never per keystroke.
  useEffect(() => {
    if (!body) return;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => preview.mutate(body), 450);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [body]); // eslint-disable-line react-hooks/exhaustive-deps

  const p = preview.data as Record<string, unknown> | undefined;
  const ood = p && String(p.domain_status ?? "") === "out_of_domain";
  const est = pickNum(p, "estimated_yield_kg_ha");
  const vj = jobs.find((j) => j.jobId === verifyJob);
  const exact = vj?.state === "succeeded" ? (vj as unknown as { exact?: number }).exact ?? null : null;
  const gate = String(caps.data?.surrogate_gate ?? "not_run");
  const total = events.reduce((a, e) => a + e.mm, 0);

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_340px]" data-testid="surrogate">
      <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Surrogate explorer</h2>
            <p className="mt-0.5 max-w-[60ch] text-[12px] text-ink-secondary">
              Try an admissible irrigation schedule and get a fast, explicitly approximate yield preview. Before it can be used in a plan, the schedule must be verified with the exact
              crop model and physical validation.
            </p>
          </div>
          <Chip tone={gate === "passed" ? "vegetation" : "warning"} title="Held-out evaluation gate (T8.3)">
            Evaluation gate: {gate.replace(/_/g, " ")}
          </Chip>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Select label="Field" value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
            <option value="">Choose…</option>
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
        </div>
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <Eyebrow>Gross irrigation schedule</Eyebrow>
            <span className="num text-[12px] text-ink-secondary">{events.length} events · {total} mm total</span>
          </div>
          <ul className="flex flex-col gap-1.5">
            {events.map((e, i) => (
              <li key={i} className="flex items-center gap-2">
                <input
                  type="date"
                  aria-label={`Event ${i + 1} date`}
                  value={e.date}
                  onChange={(ev) => setEvents((xs) => xs.map((x, j) => (j === i ? { ...x, date: ev.target.value } : x)))}
                  className="h-8 rounded-[8px] border border-border-strong/60 bg-surface px-2 text-[13px] text-ink"
                />
                <label className="flex items-center gap-1 text-[12px] text-ink-secondary">
                  <input
                    type="number"
                    min={0}
                    max={200}
                    step={5}
                    aria-label={`Event ${i + 1} depth in millimetres`}
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
            onClick={() => setEvents((xs) => [...xs, { date: xs[xs.length - 1]?.date ?? new Date().toISOString().slice(0, 10), mm: 75 }])}
          >
            Add irrigation
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3" aria-live="polite">
        {!body ? (
          <StatePanel state="empty" title="Choose a field and schedule">A preview appears shortly after the inputs settle.</StatePanel>
        ) : preview.isPending ? (
          <div className="rounded-[14px] border border-warning/30 bg-surface p-4 shadow-1" aria-busy>
            <EstimateBadge kind="preview" />
            <div className="skeleton mt-3 h-8 w-40" />
          </div>
        ) : preview.error ? (
          <StatePanel state="error" title={describeError(preview.error).title}>
            {describeError(preview.error).detail}
          </StatePanel>
        ) : p ? (
          ood ? (
            <div className="rounded-[14px] border border-warning/40 bg-warning-soft/70 p-4" data-testid="preview-ood">
              <div className="flex items-center gap-2 text-[13px] font-semibold text-warning">
                <ShieldAlert size={16} aria-hidden /> Outside validated preview range — run crop model.
              </div>
              <ul className="mt-2 list-disc pl-5 text-[12px] text-ink-secondary">
                {((p.domain_reasons as string[] | undefined) ?? []).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="rounded-[14px] border border-warning/30 bg-surface p-4 shadow-1" data-testid="preview-card">
              <div className="flex items-center justify-between gap-2">
                <EstimateBadge kind="preview" size="md" />
                <span className="num font-mono text-[11px] text-ink-tertiary">{String(p.model_version ?? "")}</span>
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <Sparkles size={16} className="text-warning" aria-hidden />
                <span className="num text-[28px] font-semibold tracking-[-0.02em] text-ink">{est !== null ? formatWithUnit(est, "kg/ha") : "—"}</span>
              </div>
              <p className="mt-1 text-[12px] text-ink-secondary">{String(p.uncertainty_note ?? "Approximate; not a calibrated confidence interval.")}</p>
              {p.residual_band ? <p className="num mt-1 text-[12px] text-ink-secondary">Held-out residual band: {JSON.stringify(p.residual_band)}</p> : null}
              <p className="mt-1 text-[12px] text-ink-tertiary">Physical pre-check: {String(p.physical_precheck_status ?? "not run").replace(/_/g, " ")}</p>
              <Button
                className="mt-3 w-full"
                variant="primary"
                icon={<FlaskConical size={15} />}
                busy={verify.isPending}
                disabled={!p.preview_id}
                onClick={async () => {
                  try {
                    const r = await verify.mutateAsync(String(p.preview_id));
                    const jid = String(r.job_id ?? "");
                    if (jid) {
                      setVerifyJob(jid);
                      trackJob({ jobId: jid, label: "Exact crop verification", operation: "surrogate_verify", revisionId: null, pilotKey: sel.pilotKey });
                    }
                  } catch {
                    /* surfaced by mutation state */
                  }
                }}
                data-testid="verify-preview"
              >
                Verify with crop model
              </Button>
              {verify.error ? <p className="mt-2 text-[12px] text-danger">{describeError(verify.error).detail}</p> : null}
            </div>
          )
        ) : null}
        {vj ? (
          <div className="rounded-[14px] border border-vegetation/30 bg-surface p-4 shadow-1" data-testid="exact-card">
            <div className="flex items-center justify-between">
              <EstimateBadge kind="exact" size="md" />
              <JobBadge state={vj.state} />
            </div>
            {vj.state === "succeeded" ? (
              <>
                <p className="mt-2 text-[13px] text-ink">Exact result recorded as {shortId(vj.resultRef)}.</p>
                {exact !== null && est !== null ? <p className="num text-[12px] text-ink-secondary">Preview − exact: {formatDelta(est - exact, "kg/ha")}</p> : null}
              </>
            ) : (
              <p className="mt-2 text-[12px] text-ink-secondary">{vj.stage ?? "Running the exact crop model and ledger validation…"}</p>
            )}
          </div>
        ) : null}
        <p className="px-1 text-[11px] text-ink-tertiary">Crop replay is unavailable for preview-only schedules.</p>
      </section>
    </div>
  );
}
