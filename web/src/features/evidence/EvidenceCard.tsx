import { ExternalLink, FileSearch, ShieldCheck } from "lucide-react";
import { useEvidence } from "@/lib/api/queries";
import type { EvidenceRecord } from "@/lib/api/types";
import { formatDate, titleCase } from "@/lib/formatting";
import { Chip, Skeleton, StatePanel, type Tone } from "@/components/status";
import { useSelection } from "@/app/selection";
import { cn } from "@/lib/cn";

const VERIF_TONE: Record<string, Tone> = {
  unchecked: "warning",
  source_checked: "water",
  artifact_checked: "water",
  locally_reviewed: "vegetation",
};
const KIND_LABEL: Record<string, string> = {
  observed_remote_sensing: "Remote sensing",
  public_geography: "Public geography",
  gridded_reanalysis: "Historical gridded weather",
  literature: "Literature",
  user_supplied: "User supplied",
  assumption: "Assumption",
  model_output: "Model output",
  derived: "Derived",
};

export function EvidenceSummary({ rec, compact, onOpen }: { rec: EvidenceRecord; compact?: boolean; onOpen?: () => void }) {
  const isRemote = !!rec.source_url && /^https?:/i.test(rec.source_url);
  return (
    <article className={cn("rounded-[12px] border border-border bg-surface", compact ? "p-3" : "p-4")} data-testid="evidence-card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">{KIND_LABEL[rec.kind] ?? titleCase(rec.kind)}</div>
          <h3 className="mt-0.5 text-[13px] font-semibold leading-snug text-ink">{rec.source_title}</h3>
        </div>
        <Chip size="sm" tone={VERIF_TONE[rec.verification_state] ?? "neutral"} icon={<ShieldCheck size={11} aria-hidden />}>
          {titleCase(rec.verification_state)}
        </Chip>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        {rec.source_period ? (
          <>
            <dt className="text-ink-secondary">Period</dt>
            <dd className="text-ink">{rec.source_period}</dd>
          </>
        ) : null}
        {rec.units ? (
          <>
            <dt className="text-ink-secondary">Units</dt>
            <dd className="text-ink">{rec.units}</dd>
          </>
        ) : null}
        {rec.license_id ? (
          <>
            <dt className="text-ink-secondary">Licence</dt>
            <dd className="text-ink">{rec.license_id}</dd>
          </>
        ) : null}
        {rec.retrieved_at ? (
          <>
            <dt className="text-ink-secondary">Retrieved</dt>
            <dd className="text-ink">{formatDate(rec.retrieved_at)}</dd>
          </>
        ) : null}
        {!compact && rec.transformation ? (
          <>
            <dt className="text-ink-secondary">Transform</dt>
            <dd className="text-ink">{rec.transformation}</dd>
          </>
        ) : null}
        {!compact && rec.raw_sha256 ? (
          <>
            <dt className="text-ink-secondary">sha256</dt>
            <dd className="num truncate font-mono text-[11px] text-ink" title={rec.raw_sha256}>
              {rec.raw_sha256.slice(0, 16)}…
            </dd>
          </>
        ) : null}
        {rec.assumption_range ? (
          <>
            <dt className="text-ink-secondary">Range</dt>
            <dd className="num text-ink">
              {rec.assumption_range.low}–{rec.assumption_range.high} {rec.assumption_range.unit}
            </dd>
          </>
        ) : null}
      </dl>
      {rec.limitations?.length ? (
        <ul className="mt-2 list-disc pl-4 text-[12px] text-ink-secondary">
          {rec.limitations.slice(0, compact ? 2 : 10).map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px]">
        {onOpen ? (
          <button type="button" onClick={onOpen} className="inline-flex items-center gap-1 font-medium text-water hover:underline">
            <FileSearch size={13} aria-hidden /> Open record
          </button>
        ) : null}
        {rec.source_url ? (
          isRemote ? (
            <a href={rec.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-ink-secondary hover:text-ink hover:underline">
              <ExternalLink size={12} aria-hidden /> Source (online)
            </a>
          ) : (
            <a href={rec.source_url} className="inline-flex items-center gap-1 text-ink-secondary hover:underline">
              Local source
            </a>
          )
        ) : null}
        <span className="num ml-auto font-mono text-[11px] text-ink-tertiary">{rec.evidence_id}</span>
      </div>
    </article>
  );
}

export function EvidenceById({ id, compact }: { id: string; compact?: boolean }) {
  const q = useEvidence(id);
  const sel = useSelection();
  if (q.isLoading) return <Skeleton className="h-24 w-full" />;
  if (q.error || !q.data)
    return (
      <StatePanel compact state="error" error={q.error} title={`Evidence ${id} unavailable`}>
        {q.error ? undefined : "The record could not be loaded."}
      </StatePanel>
    );
  return <EvidenceSummary rec={q.data} compact={compact} onOpen={() => sel.go("evidence", { ev: id })} />;
}
