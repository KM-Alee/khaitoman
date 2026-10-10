import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useEvidenceSearch, useRun } from "@/lib/api/queries";
import { formatDateTime, shortId, titleCase } from "@/lib/formatting";
import { Chip, ReviewFlagChips, Skeleton, StatePanel } from "@/components/status";
import { Dialog, DialogContent, Eyebrow } from "@/components/ui/primitives";
import { EvidenceById } from "./EvidenceCard";
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

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden" data-testid="evidence">
      <div className="min-w-0 flex-1 overflow-y-auto p-3 md:p-5">
        <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
          <header>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-ink">Evidence and reproducibility</h1>
            <p className="mt-1 max-w-[70ch] text-[13px] text-ink-secondary">
              Every input, assumption and transformation behind this pilot version, with source, licence, hashes and limitations. Versions are immutable; corrections create new versions.
            </p>
          </header>
          <label className="relative block">
            <span className="sr-only">Search evidence</span>
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-tertiary" aria-hidden />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search sources, assumptions, methods (e.g. canal, Sentinel, wheat, pond cost)"
              className="h-11 w-full rounded-[12px] border border-border-strong/60 bg-surface pl-10 pr-3 text-[14px] text-ink shadow-1 placeholder:text-ink-tertiary"
              data-testid="evidence-search"
            />
          </label>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <section aria-label="Search results" className="flex flex-col gap-2">
              <Eyebrow>{sel.q ? `Results for “${sel.q}”` : "Curated index"}</Eyebrow>
              {search.isLoading ? (
                [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)
              ) : search.error ? (
                <StatePanel state="error" error={search.error} title="Evidence search unavailable" />
              ) : !search.data?.length ? (
                <StatePanel state="empty" title="No matching evidence">
                  {sel.q ? "Try a broader term." : "The curated evidence index is empty for this pilot."}
                </StatePanel>
              ) : (
                <ul className="flex flex-col gap-2">
                  {search.data.map((h) => (
                    <li key={h.doc_id}>
                      <button
                        type="button"
                        onClick={() => sel.setParams({ ev: h.doc_id }, false)}
                        className="w-full rounded-[12px] border border-border bg-surface p-3.5 text-left shadow-1 transition-shadow hover:shadow-2"
                        data-testid="evidence-hit"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">{titleCase(h.kind)}</span>
                          <span className="font-mono text-[11px] text-ink-tertiary">{h.doc_id}</span>
                        </div>
                        <div className="mt-0.5 text-[14px] font-semibold text-ink">{h.title}</div>
                        {h.snippet ? <p className="mt-1 line-clamp-2 text-[12px] text-ink-secondary">{h.snippet}</p> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <aside className="flex flex-col gap-3">
              <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                <Eyebrow className="mb-2">Pilot version</Eyebrow>
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
              {run.data ? (
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1" data-testid="run-lineage">
                  <Eyebrow className="mb-2">Run lineage</Eyebrow>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
                    <dt className="text-ink-secondary">Run</dt>
                    <dd className="truncate font-mono text-ink">{run.data.run_id}</dd>
                    <dt className="text-ink-secondary">Revision</dt>
                    <dd className="truncate font-mono text-ink">{shortId(run.data.scenario_revision_id)}</dd>
                    <dt className="text-ink-secondary">Library</dt>
                    <dd className="truncate font-mono text-ink">{run.data.candidate_library_hash.slice(0, 16)}…</dd>
                    <dt className="text-ink-secondary">Solver</dt>
                    <dd className="text-ink">{run.data.solver_status}</dd>
                    {run.data.outcome === "plan" ? (
                      <>
                        <dt className="text-ink-secondary">Validation</dt>
                        <dd className="text-ink">{run.data.physical_validation.status}</dd>
                      </>
                    ) : null}
                  </dl>
                </section>
              ) : null}
              {p?.source_refs?.length ? (
                <section className="rounded-[14px] border border-border bg-surface p-4 shadow-1">
                  <Eyebrow className="mb-2">Package sources ({p.source_refs.length})</Eyebrow>
                  <ul className="flex flex-col gap-1">
                    {p.source_refs.slice(0, 30).map((id) => (
                      <li key={id}>
                        <button type="button" className="font-mono text-[12px] text-water hover:underline" onClick={() => sel.setParams({ ev: id }, false)}>
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
