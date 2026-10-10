/**
 * Review (PRD §5.2–5.3 fields and operational graph; T9.3 versioned edits). Shows the
 * intake's own layers on the map with a table twin, stages reviewer edits (reject /
 * replace geometry with a reason), the explicit network assumptions and review-rule
 * overrides, and sends them with `expected_version`. A stale version is a 409 that is
 * shown with a reload; the server re-runs the selection, so counts are never computed here.
 */
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, PenLine, RefreshCw, Trash2, X } from "lucide-react";
import { formatArea, shortId } from "@/lib/formatting";
import { Chip, StatePanel } from "@/components/status";
import { Button, IconButton } from "@/components/ui/Button";
import { Select } from "@/components/ui/primitives";
import { toast } from "@/components/ui/Toast";
import type { LngLat } from "@/components/map/geo";
import { cn } from "@/lib/cn";
import { AoiDrawMap, type ContextLayer, type MapPick } from "./AoiDrawMap";
import { onbKeys, useIntakeLayer, useReview, type FieldEdit, type IntakeView, type LayerList } from "./onboardingApi";
import { Alert, Card, ErrorAlert, TextArea, TextField } from "./parts";
import { RULE_KEYS, buildReviewBody, draftFromView, draftProblems, parsePolygon, reviewConflict, ringToPolygon, useAttemptKey, type ReviewDraft } from "./wizard";

type EditAction = "reject" | "replace_geometry";

export function ReviewStage({ view, layers, context }: { view: IntakeView; layers: LayerList | undefined; context: ContextLayer[] }) {
  const qc = useQueryClient();
  const has = (l: string) => !!layers?.available.includes(l as never);
  const [showRaw, setShowRaw] = useState(false);
  const [showProposed, setShowProposed] = useState(true);
  const [showCanals, setShowCanals] = useState(true);
  const aoi = useIntakeLayer(view, "aoi", has("aoi"));
  const canals = useIntakeLayer(view, "canals", has("canals"));
  const proposed = useIntakeLayer(view, "fields-proposed", has("fields-proposed"));
  const [selField, setSelField] = useState<string | null>(null);
  const [selModel, setSelModel] = useState<string | null>(null);
  const raw = useIntakeLayer(view, "fields-raw", has("fields-raw") && (showRaw || !!selModel));
  const [draft, setDraft] = useState<ReviewDraft>(() => draftFromView(view));
  const patch = (p: Partial<ReviewDraft>) => setDraft((d) => ({ ...d, ...p }));
  const review = useReview(view.onboarding_id);
  const keyFor = useAttemptKey(`review-${view.onboarding_id}`);

  // edit composer
  const [action, setAction] = useState<EditAction>("reject");
  const [reason, setReason] = useState("");
  const [drawMode, setDrawMode] = useState(false);
  const [ring, setRing] = useState<LngLat[]>([]);
  const [ringClosed, setRingClosed] = useState(false);
  const [geoText, setGeoText] = useState("");
  const [composeError, setComposeError] = useState<string | null>(null);

  const fields = useMemo(
    () => [...(proposed.data?.geojson.features ?? [])].sort((a, b) => a.properties.label.localeCompare(b.properties.label)),
    [proposed.data],
  );
  const canalList = canals.data?.geojson.features ?? [];
  const field = fields.find((f) => f.properties.field_id === selField) ?? null;
  const modelChoices = field ? field.properties.source_model_ids : selModel ? [selModel] : [];
  const [modelPick, setModelPick] = useState<string | null>(null);
  const targetModel = modelPick && modelChoices.includes(modelPick) ? modelPick : (modelChoices[0] ?? null);
  const editedIds = new Set(draft.fieldEdits.map((e) => e.model_id));

  const pick = (p: MapPick) => {
    if (p.kind === "field") {
      setSelField(p.id);
      setSelModel(null);
    } else if (p.kind === "model") {
      setSelModel(p.id);
      setSelField(null);
    } else patch({ sourceCanal: p.id });
    setModelPick(null);
  };

  const resetComposer = () => {
    setReason("");
    setRing([]);
    setRingClosed(false);
    setGeoText("");
    setDrawMode(false);
    setComposeError(null);
  };

  const addEdit = () => {
    if (!targetModel) return;
    if (!reason.trim()) return setComposeError("A reason is required for every field edit.");
    const edit: FieldEdit = { model_id: targetModel, action, reason: reason.trim() };
    if (action === "replace_geometry") {
      try {
        const vertices = ringClosed && ring.length >= 3 ? ring : geoText.trim() ? parsePolygon(geoText) : null;
        if (!vertices) return setComposeError("Draw and close a replacement outline on the map, or paste a GeoJSON polygon.");
        edit.geometry_wgs84 = ringToPolygon(vertices) as unknown as FieldEdit["geometry_wgs84"];
      } catch (e) {
        return setComposeError((e as Error).message);
      }
    }
    patch({ fieldEdits: [...draft.fieldEdits.filter((x) => x.model_id !== targetModel), edit] });
    resetComposer();
  };

  const problems = draftProblems(draft);
  const conflict = reviewConflict(review.error);
  const submit = () => {
    const body = buildReviewBody(draft, view.review_version, view);
    review.mutate(
      { body, key: keyFor(body) },
      {
        onSuccess: (r) =>
          toast({
            tone: r.blockers.length ? "warning" : "success",
            title: `Review v${r.review_version} applied`,
            description: r.blockers.length ? `${r.blockers.length} blocker(s) reported by the server.` : `State: ${r.state.replace(/_/g, " ")}`,
          }),
      },
    );
  };
  const reload = () => void qc.invalidateQueries({ queryKey: onbKeys.intake(view.onboarding_id) });

  const bbox = view.aoi_check?.bbox ?? null;
  const loadingLayers = proposed.isLoading || canals.isLoading;

  return (
    <>
      <Card
        id="review"
        title="3 · Review fields"
        description="Proposed fields from the cached inference. Select a field on the map or in the table, then reject it or replace its outline with a reason."
        testId="review"
        aside={<Chip tone="info">Review v{view.review_version}</Chip>}
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <fieldset className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink">
              <legend className="sr-only">Map layers</legend>
              <LayerToggle checked={showProposed} onChange={setShowProposed} swatch="bg-vegetation" label={`Proposed fields (${fields.length})`} />
              <LayerToggle checked={showRaw} onChange={setShowRaw} swatch="bg-warning" label="Raw model polygons" />
              <LayerToggle checked={showCanals} onChange={setShowCanals} swatch="bg-water" label="Observed canals (OSM solid, GRAIN dashed)" />
            </fieldset>
            <div className="relative overflow-hidden rounded-[12px] border border-border">
              <AoiDrawMap
                vertices={drawMode ? ring : []}
                closed={drawMode ? ringClosed : false}
                onChange={(v, c) => {
                  setRing(v);
                  setRingClosed(c);
                }}
                drawing={drawMode}
                context={context}
                overlays={{
                  aoi: aoi.data?.geojson ?? null,
                  canals: canals.data?.geojson ?? null,
                  fieldsRaw: raw.data?.geojson ?? null,
                  fieldsProposed: proposed.data?.geojson ?? null,
                }}
                visible={{ canals: showCanals, fieldsRaw: showRaw, fieldsProposed: showProposed }}
                selected={{ field: selField, model: selModel, canal: draft.sourceCanal || null }}
                onPick={pick}
                fitBbox={bbox}
                label={drawMode ? "Review map, drawing a replacement outline. Click to add vertices; Enter closes; Backspace undoes; Escape clears." : "Review map. Click a field, raw polygon or canal to select it; the tables list the same features."}
                className="h-[48vh] min-h-[320px] w-full outline-none"
              />
              {loadingLayers ? (
                <div className="absolute inset-x-3 top-3">
                  <StatePanel state="busy" compact title="Loading intake layers…" />
                </div>
              ) : null}
              {drawMode ? (
                <div className="absolute inset-x-3 bottom-3 rounded-[10px] border border-water/40 bg-surface/95 px-3 py-2 text-[12px] text-ink shadow-2" role="status">
                  Drawing a replacement outline · {ring.length} vertices{ringClosed ? " · closed" : ""}
                </div>
              ) : null}
            </div>
            <p className="mt-1.5 text-[12px] text-ink-secondary">
              Blue outline: the selected field or polygon and the chosen source canal. Dashed black: intake AOI. Imagery underneath is published-pilot
              context for display only.
            </p>
            {raw.isLoading ? <p className="mt-1 text-[12px] text-ink-secondary">Loading raw model polygons…</p> : null}
            {raw.error ? <ErrorAlert error={raw.error} title="Raw polygons unavailable" /> : null}
            {proposed.error ? <ErrorAlert error={proposed.error} title="Proposed fields unavailable" /> : null}
            {canals.error ? <ErrorAlert error={canals.error} title="Canal layer unavailable" /> : null}
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            <FieldTable fields={fields} selected={selField} edited={editedIds} onSelect={(id) => pick({ kind: "field", id })} loading={proposed.isLoading} />
            <section aria-labelledby="compose-h" className="rounded-[12px] border border-border bg-surface-muted/50 p-3" data-testid="edit-composer">
              <h3 id="compose-h" className="text-[13px] font-semibold text-ink">
                {field ? `Edit ${field.properties.label}` : selModel ? `Edit raw polygon ${shortId(selModel, 6)}` : "Select a field to edit"}
              </h3>
              {targetModel ? (
                <div className="mt-2 flex flex-col gap-2">
                  {modelChoices.length > 1 ? (
                    <Select label="Source model polygon" value={targetModel} onChange={(e) => setModelPick(e.target.value)} compact>
                      {modelChoices.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <p className="font-mono text-[11px] text-ink-secondary">Model polygon {targetModel}</p>
                  )}
                  <fieldset className="flex flex-wrap gap-3 text-[13px] text-ink">
                    <legend className="mb-1 text-[12px] font-medium text-ink-secondary">Action</legend>
                    {(["reject", "replace_geometry"] as const).map((a) => (
                      <label key={a} className="inline-flex items-center gap-1.5">
                        <input
                          type="radio"
                          name="edit-action"
                          value={a}
                          checked={action === a}
                          onChange={() => {
                            setAction(a);
                            setComposeError(null);
                          }}
                          className="accent-[var(--water)]"
                        />
                        {a === "reject" ? "Reject" : "Replace outline"}
                      </label>
                    ))}
                  </fieldset>
                  <TextArea label="Reason (required, logged verbatim)" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} data-testid="edit-reason" />
                  {action === "replace_geometry" ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" variant={drawMode ? "primary" : "secondary"} icon={<PenLine size={13} aria-hidden />} onClick={() => setDrawMode((d) => !d)} aria-pressed={drawMode}>
                          {drawMode ? "Stop drawing" : "Draw on the map"}
                        </Button>
                        {ring.length ? (
                          <Button size="sm" variant="ghost" onClick={() => { setRing([]); setRingClosed(false); }}>
                            Clear outline
                          </Button>
                        ) : null}
                      </div>
                      <TextArea label="Or paste a GeoJSON polygon" value={geoText} onChange={(e) => setGeoText(e.target.value)} rows={2} className="font-mono" />
                    </div>
                  ) : null}
                  {composeError ? (
                    <p role="alert" className="text-[12px] text-danger">
                      {composeError}
                    </p>
                  ) : null}
                  <div className="flex gap-2">
                    <Button size="sm" variant="primary" icon={<Check size={13} aria-hidden />} onClick={addEdit} data-testid="add-edit">
                      Stage edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<X size={13} aria-hidden />}
                      onClick={() => {
                        setSelField(null);
                        setSelModel(null);
                        resetComposer();
                      }}
                    >
                      Deselect
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="mt-1 text-[12px] text-ink-secondary">Choose a row in the table or click a polygon on the map. Turn on raw model polygons to edit one that was not selected.</p>
              )}
            </section>
          </div>
        </div>
      </Card>

      <Card id="graph" title="4 · Operational graph" description="Explicit direction, source, outlet, capacity and roster assumptions. “Automatic” never means guessed rights or hydraulic truth." testId="graph">
        <div className="grid gap-3 md:grid-cols-2">
          <Select
            label="Source (parent) canal"
            value={draft.sourceCanal}
            onChange={(e) => patch({ sourceCanal: e.target.value })}
            hint="Observed canal features from this intake. The selection is highlighted on the map."
            data-testid="source-canal"
          >
            <option value="">Choose an observed canal…</option>
            {canalList.map((c) => (
              <option key={c.properties.source_feature_id} value={c.properties.source_feature_id}>
                {c.properties.name ?? c.properties.waterway ?? c.properties.provider} · {c.properties.source_feature_id}
              </option>
            ))}
          </Select>
          <TextField
            label="Source capacity (m³/s)"
            type="number"
            inputMode="decimal"
            step="0.01"
            value={draft.capacity}
            onChange={(e) => patch({ capacity: e.target.value })}
            hint="An assumption you enter; the server accepts 0.05–0.20 m³/s and rejects other values."
            data-testid="capacity"
          />
          <Select label="Roster basis" value={draft.roster} onChange={(e) => patch({ roster: e.target.value as ReviewDraft["roster"] })}>
            <option value="declared_cca">Declared CCA</option>
            <option value="selected_area">Selected field area</option>
          </Select>
          <div className="flex flex-col gap-1 text-[13px]">
            <span className="text-[12px] font-medium text-ink-secondary">Fixed by this build</span>
            <span className="text-ink">Direction: downstream · Outlet: reach group</span>
          </div>
        </div>
        <label className="mt-3 flex items-start gap-2 text-[13px] text-ink">
          <input type="checkbox" checked={draft.acknowledged} onChange={(e) => patch({ acknowledged: e.target.checked })} className="mt-0.5 accent-[var(--water)]" data-testid="acknowledge" />
          <span>I reviewed the direction, source, outlet, capacity and roster assumptions. They publish as explicit assumptions, not verified hydraulics.</span>
        </label>
        {view.review?.network?.acknowledged ? <p className="mt-2 text-[12px] text-ink-secondary">The server holds an acknowledged network from review v{view.review.version}.</p> : null}
      </Card>

      <Card id="review-submit" title="Review edits and rules" description="Every review sends the full edit set; the server re-runs the selection from the raw polygons." testId="review-submit">
        <StagedEdits edits={draft.fieldEdits} onRemove={(id) => patch({ fieldEdits: draft.fieldEdits.filter((e) => e.model_id !== id) })} />
        <details className="mt-3 rounded-[10px] border border-border px-3 py-2">
          <summary className="cursor-pointer text-[13px] font-medium text-ink">Review rules (optional overrides)</summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {RULE_KEYS.map((r) => (
              <TextField
                key={r.key}
                label={`${r.label} (${r.unit})`}
                type="number"
                inputMode="decimal"
                value={draft.rules[r.key] ?? ""}
                onChange={(e) => patch({ rules: { ...draft.rules, [r.key]: e.target.value } })}
              />
            ))}
          </div>
        </details>
        <TextField className="mt-3 max-w-[420px]" label="Reviewer (logged with this version)" value={draft.reviewer} onChange={(e) => patch({ reviewer: e.target.value })} />
        {problems.length ? (
          <ul className="mt-3 flex flex-col gap-1 text-[12px] text-danger" aria-label="Fix before sending">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
        {conflict ? (
          <Alert
            tone="danger"
            title="The review changed underneath this view"
            testId="review-conflict"
            className="mt-3"
            action={
              <Button size="sm" variant="secondary" icon={<RefreshCw size={13} aria-hidden />} onClick={reload}>
                Reload the current review
              </Button>
            }
          >
            You edited review v{conflict.expectedVersion ?? view.review_version}; the server is at v{conflict.serverVersion ?? "?"}. Nothing was written. Reload to
            continue from the server’s version (your unsent edits are discarded).
          </Alert>
        ) : review.error ? (
          <div className="mt-3">
            <ErrorAlert error={review.error} title="Review rejected; the version did not change" testId="review-error" />
          </div>
        ) : null}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="primary" busy={review.isPending} disabled={problems.length > 0 || !!conflict} onClick={submit} data-testid="apply-review">
            Apply review (v{view.review_version} → v{view.review_version + 1})
          </Button>
          <span className="text-[12px] text-ink-secondary">
            {draft.fieldEdits.length} field edit{draft.fieldEdits.length === 1 ? "" : "s"} · network {draft.acknowledged ? "acknowledged" : "not acknowledged"}
          </span>
        </div>
      </Card>
    </>
  );
}

function LayerToggle({ checked, onChange, label, swatch }: { checked: boolean; onChange: (v: boolean) => void; label: string; swatch: string }) {
  return (
    <label className="inline-flex items-center gap-1.5">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--water)]" />
      <span aria-hidden className={cn("h-2.5 w-2.5 rounded-[3px]", swatch)} />
      {label}
    </label>
  );
}

function FieldTable({
  fields,
  selected,
  edited,
  onSelect,
  loading,
}: {
  fields: GeoJSON.Feature<GeoJSON.Geometry, { field_id: string; label: string; area_m2: number; source_model_ids: string[]; actions: string[] }>[];
  selected: string | null;
  edited: Set<string>;
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  if (loading) return <StatePanel state="busy" compact title="Loading proposed fields…" />;
  if (!fields.length) return <StatePanel state="empty" compact title="No proposed fields">The review selection is empty. Adjust the rules or edits and apply the review again.</StatePanel>;
  return (
    <div className="max-h-[300px] overflow-auto rounded-[12px] border border-border" data-testid="field-table">
      <table className="w-full text-left text-[12px]">
        <caption className="sr-only">Proposed fields (table twin of the map)</caption>
        <thead className="sticky top-0 bg-surface text-ink-secondary">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Field</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Area</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Model polygon</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Review actions</th>
          </tr>
        </thead>
        <tbody className="text-ink">
          {fields.map((f) => {
            const p = f.properties;
            const isSel = p.field_id === selected;
            const staged = p.source_model_ids.some((m) => edited.has(m));
            return (
              <tr key={p.field_id} className={cn("border-t border-border", isSel && "bg-water-soft")} data-field-id={p.field_id}>
                <td className="px-2 py-1">
                  <button type="button" onClick={() => onSelect(p.field_id)} aria-pressed={isSel} className="rounded-[6px] px-1 font-semibold text-water-deep underline-offset-2 hover:underline">
                    {p.label}
                  </button>
                </td>
                <td className="num px-2 py-1">{formatArea(p.area_m2, "ha", 2)}</td>
                <td className="px-2 py-1 font-mono text-[11px]">{p.source_model_ids.map((m) => shortId(m, 6)).join(", ")}</td>
                <td className="px-2 py-1">
                  {staged ? <Chip size="sm" tone="warning">edit staged</Chip> : null} {p.actions.length ? p.actions.join(", ").replace(/_/g, " ") : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StagedEdits({ edits, onRemove }: { edits: FieldEdit[]; onRemove: (modelId: string) => void }) {
  if (!edits.length) return <p className="text-[13px] text-ink-secondary">No field edits staged. Applying the review keeps the rule-based selection.</p>;
  return (
    <ul className="flex flex-col divide-y divide-border rounded-[12px] border border-border" aria-label="Staged field edits" data-testid="staged-edits">
      {edits.map((e) => (
        <li key={e.model_id} className="flex items-start justify-between gap-2 px-3 py-2 text-[13px]">
          <div className="min-w-0">
            <div className="font-medium text-ink">
              {e.action === "reject" ? "Reject" : e.action === "replace_geometry" ? "Replace outline" : e.action.replace(/_/g, " ")} ·{" "}
              <span className="font-mono text-[12px]">{e.model_id}</span>
            </div>
            <div className="text-[12px] text-ink-secondary">{e.reason}</div>
          </div>
          <IconButton label={`Remove edit for ${e.model_id}`} size="sm" onClick={() => onRemove(e.model_id)}>
            <Trash2 size={13} />
          </IconButton>
        </li>
      ))}
    </ul>
  );
}
