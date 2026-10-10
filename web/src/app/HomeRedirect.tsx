import { Link, Navigate } from "react-router";
import { ArrowRight, PlusCircle } from "lucide-react";
import { useCapabilities, useHealth, usePilots } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { BrandMark } from "@/components/layout/NavigationRail";
import { ConnectionState } from "@/components/layout/ContextBar";
import { ReviewFlagChips, Skeleton, StatePanel } from "@/components/status";
import { buttonClass } from "@/components/ui/Button";

/** `/` opens the first published pilot; without one it explains what is missing. */
export function HomeRedirect({ notFound }: { notFound?: boolean }) {
  const pilots = usePilots();
  const list = pilots.data ?? [];
  if (!notFound && list.length === 1) {
    const p = list[0];
    return <Navigate to={`/p/${encodeURIComponent(p.pilot_id)}/${encodeURIComponent(p.pilot_version)}/workspace`} replace />;
  }
  return <Landing pilots={pilots} notFound={notFound} />;
}

function Landing({ pilots, notFound }: { pilots: ReturnType<typeof usePilots>; notFound?: boolean }) {
  const health = useHealth();
  const caps = useCapabilities();
  const list = pilots.data ?? [];
  return (
    <div className="min-h-dvh bg-canvas" data-testid="landing">
      <header className="flex h-16 items-center gap-3 px-6">
        <BrandMark className="h-9 w-9" />
        <span className="text-[17px] font-semibold tracking-[-0.01em] text-ink">AabFlow</span>
        <div className="ml-auto">
          <ConnectionState />
        </div>
      </header>
      <main className="mx-auto max-w-[980px] px-6 pb-16 pt-10 md:pt-20">
        <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-water">Watercourse investment planning</p>
        <h1 className="mt-3 max-w-[16ch] font-display text-[44px] font-[560] leading-[1.03] tracking-[-0.02em] text-ink md:text-[64px]">
          Test the season before you spend.
        </h1>
        <p className="mt-5 max-w-[60ch] text-[16px] leading-relaxed text-ink-secondary">
          Compare a fixed roster, a no-capital plan and an integrated portfolio of leveling, ponds, shared repairs and pumping — with modeled production, cost,
          water use and the consequences for tail fields.
        </p>
        {notFound ? (
          <div className="mt-8 max-w-[560px]">
            <StatePanel state="empty" title="That page does not exist">
              The link does not match a pilot screen. Choose a published pilot below.
            </StatePanel>
          </div>
        ) : null}
        <section className="mt-12" aria-labelledby="pilots-h">
          <h2 id="pilots-h" className="text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-tertiary">
            Published pilots
          </h2>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {pilots.isLoading ? (
              <>
                <Skeleton className="h-36" />
                <Skeleton className="h-36" />
              </>
            ) : pilots.error ? (
              <div className="md:col-span-2">
                <StatePanel state="error" title={describeError(pilots.error).title}>
                  {describeError(pilots.error).detail} Start the stack with <code className="font-mono">make up</code> (or <code className="font-mono">make demo</code>).
                </StatePanel>
              </div>
            ) : list.length ? (
              list.map((p) => (
                <Link
                  key={`${p.pilot_id}@${p.pilot_version}`}
                  to={`/p/${encodeURIComponent(p.pilot_id)}/${encodeURIComponent(p.pilot_version)}/workspace`}
                  className="group rounded-[16px] border border-border bg-surface p-5 shadow-1 transition-shadow hover:shadow-2"
                  data-testid="pilot-card"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[12px] text-ink-tertiary">
                        {p.pilot_id} · {p.pilot_version}
                      </div>
                      <div className="mt-1 text-[18px] font-semibold tracking-[-0.01em] text-ink">{p.name}</div>
                    </div>
                    <ArrowRight size={18} className="mt-1 text-ink-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-water" aria-hidden />
                  </div>
                  <ReviewFlagChips flags={p.review_flags} className="mt-4" />
                </Link>
              ))
            ) : (
              <div className="md:col-span-2">
                <StatePanel state="empty" title="No pilot package is published yet">
                  The local API lists no published pilot. A pilot appears here once a reviewed package under <code className="font-mono">data/pilots/</code> is
                  published, or after onboarding a region.
                </StatePanel>
              </div>
            )}
          </div>
          <div className="mt-4">
            <Link to="/onboarding" className={buttonClass("secondary", "md")}>
              <PlusCircle size={16} aria-hidden /> Add region
            </Link>
          </div>
        </section>
        <footer className="mt-16 flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-ink-tertiary">
          <span>Contract {health.data?.contract_version ?? "—"}</span>
          <span>Exact crop science: {caps.data ? (caps.data.exact_science ? "available" : "unavailable") : "—"}</span>
          <span>Surrogate gate: {caps.data?.surrogate_gate?.replace(/_/g, " ") ?? "—"}</span>
          <span>Runs locally · no remote map tiles</span>
        </footer>
      </main>
    </div>
  );
}
