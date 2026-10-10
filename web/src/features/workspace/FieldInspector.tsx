import { useMemo, useState } from "react";
import { ArrowLeft, MapPin, Route, Search, Sprout, Waves, Droplets } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useField, useRun, useRuns } from "@/lib/api/queries";
import { fieldMetricMap, runMetrics } from "@/lib/api/adapters";
import type { Asset, MetricValue, RosterWindow, RunResult, ServiceReference, SoilProfile } from "@/lib/api/types";
import { formatArea, formatAreaDual, formatDateTime, formatPercent, formatVolume, shortId, titleCase } from "@/lib/formatting";
import { Chip, MetricValueView, Skeleton, StatePanel } from "@/components/status";
import { DL, Eyebrow } from "@/components/ui/primitives";
import { IconButton } from "@/components/ui/Button";
import { EvidenceById } from "@/features/evidence/EvidenceCard";
import { cn } from "@/lib/cn";

const FIELD_METRICS: { ids: string[]; label: string }[] = [
  { ids: ["yield_kg_ha", "field_yield_kg_ha"], label: "Yield" },
  { ids: ["production_kg", "field_production_kg"], label: "Production" },
  { ids: ["field_service_ratio", "service_ratio"], label: "Service ratio" },
  { ids: ["canal_receipt_m3", "field_canal_receipt_m3"], label: "Canal receipts" },
  { ids: ["groundwater_m3", "field_groundwater_m3"], label: "Groundwater" },
  { ids: ["gross_application_m3", "field_application_m3"], label: "Field application" },
];

export function FieldInspector() {
  const { sel, fieldIndex, sortedFields, map } = usePilotData();
  const selectedEdgeId = useUI((s) => s.selectedEdgeId);
  const set = useUI((s) => s.set);
  if (selectedEdgeId && !sel.fieldId) {
    const edge = map.data?.edges.find((e) => e.edge_id === selectedEdgeId);
    if (edge) return <EdgeInspector edgeId={selectedEdgeId} onBack={() => set({ selectedEdgeId: null })} />;
  }
  if (!sel.fieldId) return <FieldList fields={sortedFields} />;
  const entry = fieldIndex.get(sel.fieldId);
  if (fieldIndex.size && !entry)
    return (
      <div className="p-4">
        <StatePanel state="error" title="Field not in this pilot version" action={{ label: "Clear selection", onClick: () => sel.setParams({ field: null }) }}>
          The link refers to <code className="font-mono">{sel.fieldId}</code>, which is not a reviewed field of {sel.pilotId} {sel.version}.
        </StatePanel>
      </div>
    );
  return <FieldDetail fieldId={sel.fieldId} />;
}

function FieldList({ fields }: { fields: ReturnType<typeof usePilotData>["sortedFields"] }) {
  const { sel } = usePilotData();
  const [q, setQ] = useState("");
  const areaUnit = useUI((s) => s.areaUnit);
  const shown = fields.filter((f) => !q || f.label.toLowerCase().includes(q.toLowerCase()) || f.id.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pb-2 pt-4">
        <Eyebrow>Reviewed fields</Eyebrow>
        <p className="mt-1 text-[12px] text-ink-secondary">Select on the map, use <kbd className="font-sans">[</kbd> <kbd className="font-sans">]</kbd>, or pick from the list.</p>
        <label className="relative mt-3 block">
          <span className="sr-only">Search fields</span>
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary" aria-hidden />
          <input
            id="field-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search fields"
            className="h-9 w-full rounded-[10px] border border-border-strong/60 bg-surface pl-8 pr-3 text-[13px] text-ink placeholder:text-ink-tertiary"
          />
        </label>
      </div>
      {!fields.length ? (
        <div className="space-y-2 px-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Fields">
          {shown.map((f) => (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => sel.setParams({ field: f.id }, false)}
                className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-surface-muted"
                data-testid="field-list-item"
              >
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", f.group === "head" ? "bg-water" : f.group === "middle" ? "bg-vegetation" : "bg-warning")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-ink">{f.label}</span>
                  <span className="block text-[11px] capitalize text-ink-tertiary">{f.group ?? "group unknown"}</span>
                </span>
                {f.areaM2 ? <span className="num text-[12px] text-ink-secondary">{formatArea(f.areaM2, areaUnit)}</span> : null}
              </button>
            </li>
          ))}
          {!shown.length ? <li className="px-3 py-4 text-[12px] text-ink-secondary">No field matches “{q}”.</li> : null}
        </ul>
      )}
    </div>
  );
}

function FieldDetail({ fieldId }: { fieldId: string }) {
  const { sel, fieldIndex, map } = usePilotData();
  const q = useField(sel.version, fieldId);
  const areaUnit = useUI((s) => s.areaUnit);
  const entry = fieldIndex.get(fieldId);
  const raw = (q.data?.raw ?? {}) as Record<string, unknown>;
  const f = q.data?.field;
  const soil = raw.soil as SoilProfile | null | undefined;
  const roster = (raw.roster_windows as RosterWindow[] | undefined) ?? [];
  const refs = (raw.service_references as ServiceReference[] | undefined) ?? (raw.service_reference as ServiceReference[] | undefined) ?? [];
  const assets = (raw.assets as Asset[] | undefined) ?? [];
  const route = (raw.route_edge_ids as string[] | undefined) ?? [];
  const evidence = [...new Set([...((raw.evidence_ids as string[] | undefined) ?? []), ...(f?.evidence_ids ?? [])])];
  const runIds = sel.compareRunIds.length ? sel.compareRunIds : sel.runId ? [sel.runId] : [];

  return (
    <div className="flex flex-col gap-5 px-4 py-4" data-testid="field-detail">
      <div className="flex items-start gap-2">
        <IconButton label="Back to field list" size="sm" onClick={() => sel.setParams({ field: null })}>
          <ArrowLeft size={16} />
        </IconButton>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[18px] font-semibold tracking-[-0.01em] text-ink present-lg" data-testid="field-title">
              {entry?.label ?? f?.label ?? fieldId}
            </h2>
            {entry?.group ? <Chip size="sm" tone={entry.group === "tail" ? "warning" : entry.group === "head" ? "water" : "vegetation"}>{titleCase(entry.group)}</Chip> : null}
          </div>
          <div className="num font-mono text-[11px] text-ink-tertiary">{fieldId}</div>
        </div>
      </div>

      <FieldResults fieldId={fieldId} runIds={runIds} />

      <section aria-label="Field facts">
        <Eyebrow className="mb-2">Field</Eyebrow>
        {q.isLoading ? (
          <Skeleton className="h-28" />
        ) : q.error ? (
          <StatePanel compact state="error" error={q.error} title="Field record unavailable" />
        ) : (
          <DL
            rows={[
              ["Area", entry?.areaM2 ?? f?.gross_area_m2 ? formatAreaDual((entry?.areaM2 ?? f?.gross_area_m2)!) : "—"],
              ["Soil", soil ? `${soil.engine_soil_type} · ${soil.archetype}` : f?.soil_profile_id ?? "—"],
              ["Outlet", f?.outlet_node_id ?? "—"],
              ["Application eff.", f ? formatPercent(f.existing_application_efficiency) : "—"],
              ["Geometry", f ? `v${f.geometry_version}${f.source_model_ids.length ? ` · from ${f.source_model_ids.length} AI polygon${f.source_model_ids.length > 1 ? "s" : ""}` : ""}` : "—"],
            ]}
          />
        )}
      </section>

      <section aria-label="Water route">
        <Eyebrow className="mb-2 flex items-center gap-1.5">
          <Route size={12} aria-hidden /> Declared route
        </Eyebrow>
        {route.length ? (
          <ol className="flex flex-wrap items-center gap-1 text-[12px]">
            {route.map((eid, i) => {
              const e = map.data?.edges.find((x) => x.edge_id === eid);
              return (
                <li key={eid} className="flex items-center gap-1">
                  <Chip size="sm" tone={e?.geometry_ref ? "water" : "neutral"} title={e ? `delivery factor ${e.delivery_factor}` : eid}>
                    {e?.reach_label ?? eid} {e ? `· ${formatPercent(e.delivery_factor)}` : ""}
                    {e && !e.geometry_ref ? " · assumed" : ""}
                  </Chip>
                  {i < route.length - 1 ? <span className="text-ink-tertiary">→</span> : null}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-[12px] text-ink-secondary">{q.isLoading ? "Loading…" : "No declared route in the field record."}</p>
        )}
      </section>

      <section aria-label="Roster windows">
        <Eyebrow className="mb-2">Receipt windows</Eyebrow>
        {roster.length ? (
          <ul className="flex flex-col gap-1">
            {roster.slice(0, 6).map((w) => (
              <li key={w.window_id} className="flex items-center justify-between gap-2 rounded-[8px] bg-surface-muted px-2.5 py-1.5 text-[12px]">
                <span className="num text-ink">{formatDateTime(w.start)} → {formatDateTime(w.end).replace(" PKT", "")}</span>
                <Chip size="sm" tone={w.verification === "verified" ? "vegetation" : "warning"}>
                  {w.basis === "time" && w.rate_m3_s ? `${w.rate_m3_s} m³/s` : w.volume_cap_m3 ? formatVolume(w.volume_cap_m3) : w.basis} · {w.verification}
                </Chip>
              </li>
            ))}
            {roster.length > 6 ? <li className="text-[12px] text-ink-tertiary">+{roster.length - 6} more windows</li> : null}
          </ul>
        ) : (
          <p className="text-[12px] text-ink-secondary">{q.isLoading ? "Loading…" : "No roster windows returned."}</p>
        )}
        {refs.length ? (
          <p className="mt-2 text-[12px] text-ink-secondary">
            Reference allowance {formatVolume(refs[0].reference_receipt_m3)} ({refs[0].basis} right; receipt / reference allowance, not a verified legal quota).
          </p>
        ) : null}
      </section>

      {assets.length ? (
        <section aria-label="Accessible assets">
          <Eyebrow className="mb-2">Assets</Eyebrow>
          <ul className="flex flex-col gap-1.5">
            {assets.map((a) => (
              <li key={a.asset_id} className="flex items-center gap-2 rounded-[10px] border border-border px-2.5 py-2 text-[12px]">
                {a.kind === "pond" ? <Waves size={14} className="text-water" aria-hidden /> : <Droplets size={14} className="text-warning" aria-hidden />}
                <span className="flex-1">
                  <span className="font-medium text-ink">{a.kind === "pond" ? "Pond" : "Pump"}</span>{" "}
                  <span className="text-ink-tertiary">{a.asset_id}</span>
                  <span className="block text-ink-secondary">
                    {a.kind === "pond"
                      ? `${a.usable_capacity_m3 ? formatVolume(a.usable_capacity_m3) : "capacity unknown"} usable`
                      : `${a.max_rate_m3_h ?? "—"} m³/h · ${a.field_ids.length > 1 ? `shared by ${a.field_ids.length} fields` : "single field"} · quality ${a.quality_status}`}
                  </span>
                </span>
                <Chip size="sm" tone={a.existing ? "info" : "warning"}>{a.existing ? "Existing" : "Proposed"}</Chip>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {evidence.length ? (
        <section aria-label="Field evidence">
          <Eyebrow className="mb-2 flex items-center gap-1.5">
            <MapPin size={12} aria-hidden /> Evidence
          </Eyebrow>
          <div className="flex flex-col gap-2">
            {evidence.slice(0, 3).map((id) => (
              <EvidenceById key={id} id={id} compact />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function FieldResults({ fieldId, runIds }: { fieldId: string; runIds: string[] }) {
  const runs = useRuns(runIds);
  const single = useRun(runIds.length === 1 ? runIds[0] : null);
  const list: RunResult[] = runIds.length === 1 ? (single.data ? [single.data] : []) : runs.data ?? [];
  const rows = useMemo(
    () =>
      FIELD_METRICS.map((m) => ({
        label: m.label,
        cells: list.map((r) => fieldMetricMap(runMetrics(r), ...m.ids).get(fieldId) ?? null),
      })).filter((r) => r.cells.some(Boolean)),
    [list, fieldId],
  );
  if (!runIds.length)
    return (
      <div className="rounded-[12px] bg-surface-muted p-3 text-[12px] text-ink-secondary">
        <Sprout size={14} className="mb-1 text-vegetation" aria-hidden />
        No run selected. Run a plan to see this field's modeled yield, receipts and service.
      </div>
    );
  if (runs.isLoading || single.isLoading) return <Skeleton className="h-24" />;
  if (!rows.length)
    return <p className="rounded-[12px] bg-surface-muted p-3 text-[12px] text-ink-secondary">The selected run reports no per-field metrics for this field.</p>;
  return (
    <section aria-label="Field results">
      <Eyebrow className="mb-2">Modeled results</Eyebrow>
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-ink-tertiary">
            <th className="pb-1 font-medium">Metric</th>
            {list.map((r) => (
              <th key={r.run_id} className="pb-1 text-right font-medium" title={r.run_id}>
                {r.plan_kind} <span className="font-normal">{shortId(r.run_id, 4)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-border">
              <th scope="row" className="py-1.5 text-left font-normal text-ink-secondary">
                {row.label}
              </th>
              {row.cells.map((c: MetricValue | null, i) => (
                <td key={i} className="py-1.5 text-right">
                  <MetricValueView metric={c} size="sm" showReason={false} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function EdgeInspector({ edgeId, onBack }: { edgeId: string; onBack: () => void }) {
  const { map, canalsFC } = usePilotData();
  const edge = map.data?.edges.find((e) => e.edge_id === edgeId)!;
  const canal = canalsFC?.features.find((f) => [f.id, f.properties?.id, f.properties?.feature_id].map(String).includes(String(edge.geometry_ref)));
  return (
    <div className="flex flex-col gap-4 px-4 py-4" data-testid="edge-detail">
      <div className="flex items-start gap-2">
        <IconButton label="Back" size="sm" onClick={onBack}>
          <ArrowLeft size={16} />
        </IconButton>
        <div>
          <h2 className="text-[16px] font-semibold text-ink">{edge.reach_label ?? edge.edge_id}</h2>
          <div className="font-mono text-[11px] text-ink-tertiary">{edge.edge_id}</div>
        </div>
      </div>
      <section>
        <Eyebrow className="mb-2">Modeled edge parameters</Eyebrow>
        <DL
          rows={[
            ["From → to", `${edge.upstream_node_id} → ${edge.downstream_node_id}`],
            ["Delivery factor", formatPercent(edge.delivery_factor)],
            ["Capacity intervals", String(edge.capacities.length)],
            ["Closures", String(edge.closures.length)],
          ]}
        />
      </section>
      <section>
        <Eyebrow className="mb-2">Observed source feature</Eyebrow>
        {edge.geometry_ref ? (
          <DL
            rows={[
              ["Geometry ref", edge.geometry_ref],
              ["Provider ids", edge.source_feature_ids.join(", ") || "—"],
              ...Object.entries(canal?.properties ?? {})
                .filter(([, v]) => typeof v !== "object")
                .slice(0, 6)
                .map(([k, v]) => [k, String(v)] as [string, string]),
            ]}
          />
        ) : (
          <p className="text-[12px] text-warning">Assumed connection: no observed canal geometry. A crossing line does not create a junction.</p>
        )}
      </section>
      {edge.evidence_ids.length ? (
        <div className="flex flex-col gap-2">
          {edge.evidence_ids.slice(0, 2).map((id) => (
            <EvidenceById key={id} id={id} compact />
          ))}
        </div>
      ) : null}
    </div>
  );
}
