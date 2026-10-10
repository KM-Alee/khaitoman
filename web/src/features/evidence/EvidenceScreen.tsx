import { useEffect, useState } from "react";
import { ClipboardCheck, Fingerprint, Satellite, Search } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { planName } from "@/lib/glossary";
import { usePilotData } from "@/app/pilotData";
import { useEvidence, useEvidenceSearch, useRun } from "@/lib/api/queries";
import { formatDate, formatDateTime, shortId, titleCase } from "@/lib/formatting";
import { Chip, Provenance, ReviewFlagChips, Skeleton, SOLVER_COPY, StatePanel, TrustSummary } from "@/components/status";
import { Dialog, DialogContent, Eyebrow } from "@/components/ui/primitives";
import { EvidenceById, VERIF_TONE } from "./EvidenceCard";
import { useShell } from "@/components/layout/AppShell";

export function EvidenceScreen() {
  const { sel, pilot } = usePilotData();
  const { mobile } = useShell();
  const [q, setQ] = useState(sel.q ?? "");
  useEffect(() => {
    const t = setTimeout(() => sel.setParams({ q: q || null }), 300);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const search = useEvidenceSearch(sel.q ?? "", sel.pilotId);
  const run = useRun(sel.runId);
  const p = pilot.data?.pilot;
  const detail = sel.evidenceId;

  const im = p?.imagery?.[0];
  return (
    <div className="flex min-h-0 flex-1 overflow-hidden" data-testid="evidence">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-6 p-4 md:p-8">
          <PageHeader
            lead="Every input, assumption and calculation behind this watercourse, with what is verified and what is still assumed. Saved versions never change; a correction creates a new version."
            meta={run.data ? <Provenance run={run.data} /> : null}
          />

          <div className="grid gap-4 lg:grid-cols-3" data-tour="trust">
            <Card className="p-5">
              <div className="mb-3 flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-vegetation-soft text-vegetation" aria-hidden>
                  <Satellite size={16} />
                </span>
                <h2 className="text-[15px] font-semibold text-ink">What is real</h2>
              </div>
              <ul className="flex flex-col gap-2.5 text-[13px] leading-snug text-ink-secondary">
                <li>
                  <span className="font-semibold text-ink">Satellite imagery.</span> Sentinel-2 scene{im ? ` of ${formatDate(im.acquired_at)}, ${im.resolution_m ?? 10} m pixels` : ""}.
                </li>
                <li>
                  <span className="font-semibold text-ink">Field boundaries.</span> Drawn by the Delineate Anything AI model on that imagery, then checked by a person
                  {p?.review_flags?.geography_reviewed === false ? " (not yet reviewed)" : ""}.
                </li>
                <li>
                  <span className="font-semibold text-ink">Weather.</span> Daily historical gridded weather of real past seasons, used as scenarios, not forecasts.
                </li>
                <li>
                  <span className="font-semibold text-ink">Crop and water results.</span> Executed AquaCrop crop runs and an exact optimiser, with every litre re-traced day by day.
                </li>
              </ul>
            </Card>
            <Card className="p-5">
              <div className="mb-3 flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-warning-soft text-warning" aria-hidden>
                  <ClipboardCheck size={16} />
                </span>
                <h2 className="text-[15px] font-semibold text-ink">Checked and assumed</h2>
              </div>
              {p ? <TrustSummary flags={p.review_flags} /> : <Skeleton className="h-40" />}
            </Card>
            <Card className="p-5" data-testid="run-lineage">
              <div className="mb-3 flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-water-soft text-water-deep" aria-hidden>
                  <Fingerprint size={16} />
                </span>
                <h2 className="text-[15px] font-semibold text-ink">How this result was made</h2>
              </div>
              {run.data ? (
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12.5px]">
                  <dt className="text-ink-secondary">Saved calculation</dt>
                  <dd className="truncate font-mono text-ink" title={run.data.run_id}>
                    {run.data.run_id}
                  </dd>
                  <dt className="text-ink-secondary">Plan</dt>
                  <dd className="text-ink">
                    {planName(run.data.plan_kind)} ({run.data.plan_kind})
                  </dd>
                  <dt className="text-ink-secondary">Settings version</dt>
                  <dd className="truncate font-mono text-ink" title={run.data.scenario_revision_id}>
                    {shortId(run.data.scenario_revision_id)}
                  </dd>
                  <dt className="text-ink-secondary">Option library</dt>
                  <dd className="truncate font-mono text-ink" title={run.data.candidate_library_hash}>
                    {run.data.candidate_library_hash.slice(0, 16)}…
                  </dd>
                  <dt className="text-ink-secondary">Solver</dt>
                  <dd className="text-ink" title={SOLVER_COPY[run.data.solver_status].friendly}>
                    {SOLVER_COPY[run.data.solver_status].plain} ({run.data.solver_status})
                  </dd>
                  {run.data.outcome === "plan" ? (
                    <>
                      <dt className="text-ink-secondary">Water check</dt>
                      <dd className="text-ink">{run.data.physical_validation.status === "passed" ? "Books balance (passed)" : run.data.physical_validation.status}</dd>
                    </>
                  ) : null}
                  <dt className="text-ink-secondary">Computed</dt>
                  <dd className="text-ink">{formatDateTime(run.data.created_at)}</dd>
                  <dt className="text-ink-secondary">Proof scope</dt>
                  <dd className="text-ink">The finite set of modelled options</dd>
                </dl>
              ) : (
                <p className="text-[13px] leading-relaxed text-ink-secondary">Open a plan (or any saved run link) to see exactly which settings, option library, solver result and water check produced it.</p>
              )}
            </Card>
          </div>

          <section aria-labelledby="ev-search-h" className="flex flex-col gap-3">
            <h2 id="ev-search-h" className="text-[16px] font-semibold tracking-[-0.01em] text-ink">
              Look up any source, assumption or method
            </h2>
            <label className="relative block">
              <span className="sr-only">Search evidence</span>
              <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-tertiary" aria-hidden />
              <input
                type="search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search: canal, Sentinel, wheat, pond cost, solver…"
                className="h-12 w-full rounded-[14px] border border-border-strong/55 bg-surface-raised pl-10 pr-3 text-[14.5px] text-ink shadow-1 placeholder:text-ink-tertiary"
                data-testid="evidence-search"
              />
            </label>
          </section>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <section aria-label="Search results" className="flex flex-col gap-2">
              <Eyebrow>{sel.q ? `Results for “${sel.q}”` : "Sources this watercourse cites"}</Eyebrow>
              {!sel.q ? (
                <EvidenceStart refs={p?.source_refs ?? []} onTopic={(t) => setQ(t)} onOpen={(id) => sel.setParams({ ev: id }, false)} />
              ) : search.isLoading ? (
                [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)
              ) : search.error ? (
                <StatePanel state="error" error={search.error} title="Evidence search unavailable" />
              ) : !search.data?.length ? (
                <StatePanel state="empty" art="search" title="No matching evidence">
                  {sel.q ? "Try a broader term." : "The curated evidence index is empty for this pilot."}
                </StatePanel>
              ) : (
                <ul className="flex flex-col gap-2">
                  {search.data.map((h) => (
                    <li key={h.doc_id}>
                      <button
                        type="button"
                        onClick={() => sel.setParams({ ev: h.doc_id }, false)}
                        className="w-full rounded-[14px] border border-border bg-surface p-4 text-left shadow-1 transition-[box-shadow,border-color] hover:border-water/35 hover:shadow-2"
                        data-testid="evidence-hit"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="eyebrow">{titleCase(h.kind)}</span>
                          <span className="font-mono text-[11px] text-ink-tertiary">{h.doc_id}</span>
                        </div>
                        <div className="mt-0.5 text-[14px] font-semibold text-ink">{h.title}</div>
                        {h.snippet ? <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-secondary">{h.snippet}</p> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <aside className="flex flex-col gap-3">
              <section className="rounded-[18px] border border-border bg-surface p-4 shadow-1">
                <Eyebrow className="mb-2">Watercourse package</Eyebrow>
                {p ? (
                  <>
                    <div className="text-[14px] font-semibold text-ink">{p.name}</div>
                    <div className="font-mono text-[11px] text-ink-tertiary">
                      {p.pilot_id}@{p.pilot_version}
                    </div>
                    <ReviewFlagChips flags={p.review_flags} className="mt-2" />
                    <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
                      <dt className="text-ink-secondary">State</dt>
                      <dd className="text-ink">{titleCase(p.state)}</dd>
                      <dt className="text-ink-secondary">Package</dt>
                      <dd className="truncate font-mono text-ink" title={p.package_sha256 ?? ""}>
                        {p.package_sha256 ? `${p.package_sha256.slice(0, 16)}…` : "—"}
                      </dd>
                      <dt className="text-ink-secondary">CRS</dt>
                      <dd className="text-ink">{p.metric_crs}</dd>
                      <dt className="text-ink-secondary">Created</dt>
                      <dd className="text-ink">{formatDateTime(p.created_at)}</dd>
                    </dl>
                  </>
                ) : (
                  <Skeleton className="h-24" />
                )}
              </section>
              {p?.source_refs?.length ? (
                <section className="rounded-[18px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Package sources ({p.source_refs.length})</Eyebrow>
                  <ul className="flex flex-col gap-1">
                    {p.source_refs.slice(0, 30).map((id) => (
                      <li key={id}>
                        <button type="button" className="break-all text-left font-mono text-[12px] text-water-deep hover:underline" onClick={() => sel.setParams({ ev: id }, false)}>
                          {id}
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              <Chip tone="info">Online source links open only when clicked; nothing is fetched remotely.</Chip>
            </aside>
          </div>
        </div>
      </div>
      <Dialog open={!!detail} onOpenChange={(o) => !o && sel.setParams({ ev: null })}>
        {detail ? (
          <DialogContent title="Evidence record" description={detail} side={mobile ? "bottom" : "right"}>
            <div className="p-4" data-testid="evidence-drawer">
              <EvidenceById id={detail} />
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

const TOPICS = ["Sentinel-2", "canal", "roster", "wheat", "AquaCrop", "pond", "pump", "delivery factor", "solver", "surrogate"];

/** One cited record: its title and verification state, loaded from the evidence index. */
function RefCard({ id, onOpen }: { id: string; onOpen: () => void }) {
  const rec = useEvidence(id);
  const r = rec.data;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex h-full w-full flex-col items-start gap-1 rounded-[14px] border border-border bg-surface px-4 py-3 text-left shadow-1 transition-[box-shadow,border-color] hover:border-water/35 hover:shadow-2"
      data-testid="evidence-hit"
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="eyebrow">{r?.kind ? titleCase(String(r.kind)) : evidenceKind(id)}</span>
        {r?.verification_state ? (
          <Chip size="sm" tone={VERIF_TONE[r.verification_state] ?? "neutral"}>
            {titleCase(r.verification_state)}
          </Chip>
        ) : null}
      </span>
      {rec.isLoading ? <Skeleton className="h-4 w-3/4" /> : <span className="text-[13px] font-semibold leading-snug text-ink">{r?.source_title ?? id}</span>}
      <span className="break-all font-mono text-[11px] text-ink-tertiary">{id}</span>
    </button>
  );
}

function evidenceKind(id: string): string {
  const k = id.split(":")[0];
  return (
    { ev: "Source", asm: "Assumption", metric: "Metric definition", tx: "Transformation", run: "Run" } as Record<string, string>
  )[k] ?? titleCase(k);
}

/** Empty-query state: topic shortcuts plus every evidence record the package cites. */
function EvidenceStart({ refs, onTopic, onOpen }: { refs: string[]; onTopic: (t: string) => void; onOpen: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Search topics">
        {TOPICS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onTopic(t)}
            className="rounded-full border border-border bg-surface px-3 py-1 text-[12px] font-medium text-ink-secondary shadow-1 transition-colors hover:border-water/50 hover:text-water"
          >
            {t}
          </button>
        ))}
      </div>
      {refs.length ? (
        <ul className="grid gap-2 sm:grid-cols-2">
          {refs.map((id) => (
            <li key={id}>
              <RefCard id={id} onOpen={() => onOpen(id)} />
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel state="empty" title="No package evidence listed">This pilot version cites no evidence records.</StatePanel>
      )}
    </div>
  );
}
