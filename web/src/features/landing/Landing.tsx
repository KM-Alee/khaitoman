/**
 * Landing (`/`): what AabFlow is in one sentence, the guided tour, and the published
 * watercourses shown as their real imagery with AI-drawn field boundaries.
 */
import { Link, useNavigate } from "react-router";
import { ArrowRight, BookOpenCheck, CloudRain, Coins, Cpu, Map as MapIcon, PlayCircle, PlusCircle, Satellite, Scale, ShieldCheck, Sparkles, WifiOff } from "lucide-react";
import { useCapabilities, useHealth, usePilots } from "@/lib/api/queries";
import { describeError } from "@/lib/api/client";
import { BACKEND_ORIGIN } from "@/lib/api/urls";
import type { PilotSummary } from "@/lib/api/types";
import { formatArea, formatDate } from "@/lib/formatting";
import { ConnectionState } from "@/components/layout/ContextBar";
import { Skeleton, StatePanel } from "@/components/status";
import { Button, buttonClass } from "@/components/ui/Button";
import { Wordmark } from "@/components/ui/Art";
import { useUI } from "@/app/store";
import { JOURNEY } from "@/app/journey";
import { useTour } from "@/features/tour/store";
import { cn } from "@/lib/cn";
import { AiStackStrip } from "@/components/layout/AiStackStrip";
import { PilotPortrait } from "./PilotPortrait";
import { HeadlineInsight } from "./HeadlineInsight";
import { AskBox } from "./AskBox";
import { PlanSeasonSection } from "./PlanSeasonSection";

const pilotHref = (p: PilotSummary, screen = "workspace") => `/p/${encodeURIComponent(p.pilot_id)}/${encodeURIComponent(p.pilot_version)}/${screen}`;

export function Landing({ pilots, notFound }: { pilots: ReturnType<typeof usePilots>; notFound?: boolean }) {
  const health = useHealth();
  const caps = useCapabilities();
  const list = pilots.data ?? [];
  const first = list[0] ?? null;
  const startTour = useTour((s) => s.start);
  const set = useUI((s) => s.set);
  const navigate = useNavigate();
  return (
    <div className="min-h-dvh overflow-x-hidden bg-canvas" data-testid="landing">
      <header className="mx-auto flex h-16 max-w-[1280px] items-center gap-3 px-4 md:px-8">
        <Wordmark />
        <div className="ml-auto flex items-center gap-2">
          <ConnectionState />
          <Link to="/onboarding" className={buttonClass("ghost", "sm", "hidden sm:inline-flex")}>
            <PlusCircle size={15} aria-hidden /> Add a region
          </Link>
        </div>
      </header>

      <main>
        {/* hero */}
        <section className="relative">
          <div className="bg-dawn absolute inset-0 -z-10" aria-hidden />
          <div className="mx-auto grid max-w-[1280px] items-center gap-10 px-4 pb-14 pt-8 md:px-8 md:pt-14 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:gap-14">
            <div className="animate-rise">
              <p className="eyebrow flex items-center gap-2 text-water-deep">
                <span className="h-px w-6 bg-water" aria-hidden /> Irrigation planning for watercourse committees
              </p>
              <h1 className="display mt-4 max-w-[13ch] text-[46px] leading-[1.02] text-ink md:text-[68px]">Test the season before you spend.</h1>
              <p className="mt-5 max-w-[56ch] text-[17px] leading-relaxed text-ink-secondary">
                A watercourse committee can fund only some of the improvements its farmers need. AabFlow's AI shows what each choice changes, what it costs, and which fields
                downstream would still go short, before any money is spent.
              </p>
              <AskBox className="mt-7 max-w-[640px]" fallbackHref={first ? pilotHref(first) : null} />
              <div className="mt-6 flex flex-wrap items-center gap-3">
                <Button
                  variant="hero"
                  size="xl"
                  icon={<PlayCircle size={19} />}
                  onClick={() => {
                    set({ tourSeen: true });
                    startTour(0);
                  }}
                  data-testid="landing-tour"
                >
                  Take the 3-minute tour
                </Button>
                {first ? (
                  <Button variant="secondary" size="xl" trailing={<ArrowRight size={17} />} onClick={() => navigate(pilotHref(first))} data-testid="landing-explore">
                    Explore on my own
                  </Button>
                ) : null}
              </div>
              <p className="mt-3 text-[13px] text-ink-tertiary">The tour opens real results that were computed earlier and saved. You can leave it at any step and try everything yourself.</p>
              <ul className="mt-8 grid max-w-[620px] grid-cols-2 gap-x-6 gap-y-3 text-[13px] text-ink-secondary sm:grid-cols-4">
                {[
                  { i: <Satellite size={16} />, t: "Real satellite imagery" },
                  { i: <Sparkles size={16} />, t: "AI-drawn, human-checked fields" },
                  { i: <Cpu size={16} />, t: "Executed crop model" },
                  { i: <WifiOff size={16} />, t: "Runs fully offline" },
                ].map((x) => (
                  <li key={x.t} className="flex items-start gap-2">
                    <span className="mt-0.5 text-water" aria-hidden>
                      {x.i}
                    </span>
                    {x.t}
                  </li>
                ))}
              </ul>
            </div>

            <div className="relative animate-[pop_420ms_var(--ease-out)_both] [animation-delay:120ms]">
              {first ? (
                <figure className="relative mx-auto aspect-square w-full max-w-[540px] overflow-hidden rounded-[28px] border border-border bg-ink shadow-3">
                  <PilotPortrait pilotId={first.pilot_id} version={first.pilot_version} />
                  <figcaption className="absolute inset-x-3 bottom-3 flex flex-wrap items-end justify-between gap-2">
                    <span className="glass rounded-[14px] border border-white/20 px-3.5 py-2.5 shadow-2">
                      <span className="block text-[13.5px] font-semibold text-ink">{first.name}</span>
                      <span className="block text-[12px] text-ink-secondary">
                        {first.field_count ?? "—"} fields drawn by AI on Sentinel-2{first.imagery?.[0] ? ` · ${formatDate(first.imagery[0].acquired_at)}` : ""}
                      </span>
                    </span>
                    <span className="glass inline-flex items-center gap-1.5 rounded-full border border-white/20 px-3 py-1.5 text-[12px] font-medium text-ink shadow-2">
                      <span className="h-2.5 w-2.5 rounded-sm bg-wheat" aria-hidden /> tail-end fields
                    </span>
                  </figcaption>
                </figure>
              ) : pilots.isLoading ? (
                <Skeleton className="mx-auto aspect-square w-full max-w-[540px] rounded-[28px]" />
              ) : null}
            </div>
          </div>
        </section>

        <section className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 pb-4 md:px-8" aria-label="What the AI found">
          <HeadlineInsight
            onSeeHow={() => {
              set({ tourSeen: true });
              startTour(0);
            }}
          />
          <div>
            <h2 className="eyebrow mb-3 flex items-center gap-2 text-water-deep">
              <span className="h-px w-6 bg-water" aria-hidden /> AI inside: four engines, each with its proof
            </h2>
            <AiStackStrip />
          </div>
          {first ? <PlanSeasonSection pilotId={first.pilot_id} version={first.pilot_version} /> : null}
        </section>

        {notFound ? (
          <div className="mx-auto max-w-[1280px] px-4 md:px-8">
            <StatePanel state="empty" art="search" title="That page does not exist">
              The link does not match a watercourse screen. Choose a published watercourse below.
            </StatePanel>
          </div>
        ) : null}

        {/* how it works */}
        <section className="border-y border-border bg-surface/60" aria-labelledby="how-h">
          <div className="mx-auto max-w-[1280px] px-4 py-14 md:px-8">
            <h2 id="how-h" className="display text-[30px] leading-tight text-ink md:text-[36px]">
              Five questions, one honest answer each
            </h2>
            <p className="mt-2 max-w-[64ch] text-[15px] text-ink-secondary">AabFlow walks you through the questions a committee actually asks. Every number comes from an executed model run you can trace.</p>
            <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
              {JOURNEY.map((j, i) => (
                <li key={j.screen} className="animate-rise" style={{ animationDelay: `${i * 60}ms` }}>
                  {first ? (
                    <Link to={pilotHref(first, j.screen)} className="group flex h-full flex-col gap-3 rounded-[20px] border border-border bg-surface p-5 shadow-1 transition-[box-shadow,border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-water/35 hover:shadow-2">
                      <JourneyCardBody i={i} j={j} />
                    </Link>
                  ) : (
                    <div className="flex h-full flex-col gap-3 rounded-[20px] border border-border bg-surface p-5 shadow-1">
                      <JourneyCardBody i={i} j={j} />
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* pilots */}
        <section className="mx-auto max-w-[1280px] px-4 py-14 md:px-8" aria-labelledby="pilots-h">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 id="pilots-h" className="display text-[30px] leading-tight text-ink md:text-[36px]">
                Choose a watercourse
              </h2>
              <p className="mt-2 max-w-[60ch] text-[15px] text-ink-secondary">Each one is a reviewed package: imagery, canals, field boundaries and the assumptions still to be checked locally.</p>
            </div>
            <Link to="/onboarding" className={buttonClass("secondary", "md")}>
              <PlusCircle size={16} aria-hidden /> Add a new region
            </Link>
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {pilots.isLoading ? (
              <>
                <Skeleton className="h-[360px] rounded-[22px]" />
                <Skeleton className="h-[360px] rounded-[22px]" />
              </>
            ) : pilots.error ? (
              <div className="md:col-span-2">
                <StatePanel state="error" title={describeError(pilots.error).title}>
                  {describeError(pilots.error).detail}{" "}
                  {BACKEND_ORIGIN ? "Use the backend sign-in and retry controls above to reconnect." : <>Start the stack with <code className="font-mono">make up</code> (or <code className="font-mono">make demo</code>).</>}
                </StatePanel>
              </div>
            ) : list.length ? (
              list.map((p) => <PilotCard key={`${p.pilot_id}@${p.pilot_version}`} p={p} />)
            ) : (
              <div className="md:col-span-2">
                <StatePanel state="empty" title="No pilot package is published yet" action={<Link to="/onboarding" className={buttonClass("primary", "sm")}>Add a region</Link>}>
                  The local API lists no published pilot. A pilot appears here once a reviewed package under <code className="font-mono">data/pilots/</code> is published, or after
                  onboarding a region.
                </StatePanel>
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[1280px] flex-wrap gap-x-6 gap-y-1 px-4 py-6 text-[12px] text-ink-tertiary md:px-8">
          <span>Contract {health.data?.contract_version ?? "—"}</span>
          <span>Exact crop science: {caps.data ? (caps.data.exact_science ? "available" : "unavailable") : "—"}</span>
          <span>Surrogate gate: {caps.data?.surrogate_gate?.replace(/_/g, " ") ?? "—"}</span>
          <span>Runs locally · no remote map tiles</span>
          <span className="ml-auto">Results are model estimates for planning, not measured harvests or legal water rights.</span>
        </div>
      </footer>
    </div>
  );
}

const JOURNEY_ICON = [<MapIcon key="m" size={18} />, <Scale key="s" size={18} />, <CloudRain key="c" size={18} />, <Coins key="o" size={18} />, <ShieldCheck key="t" size={18} />];

function JourneyCardBody({ i, j }: { i: number; j: (typeof JOURNEY)[number] }) {
  return (
    <>
      <span className="flex items-center justify-between">
        <span className="grid h-10 w-10 place-items-center rounded-[12px] bg-water-soft text-water-deep" aria-hidden>
          {JOURNEY_ICON[i]}
        </span>
        <span className="num text-[12px] font-semibold text-ink-tertiary">0{j.step}</span>
      </span>
      <span className="text-[15.5px] font-semibold leading-snug text-ink">{j.question}</span>
      <span className="text-[13px] leading-relaxed text-ink-secondary">{j.blurb}</span>
      <span className="mt-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-water-deep">
        {j.label} <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </>
  );
}

function PilotCard({ p }: { p: PilotSummary }) {
  const f = p.review_flags;
  const checked = f ? [f.geography_reviewed, f.topology_structurally_valid, f.rights_verification === "verified", f.cost_evidence === "quoted", f.crop_calibration === "calibrated"].filter(Boolean).length : 0;
  return (
    <Link
      to={pilotHref(p)}
      className="group flex flex-col overflow-hidden rounded-[22px] border border-border bg-surface shadow-1 transition-[box-shadow,border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-water/35 hover:shadow-3"
      data-testid="pilot-card"
    >
      <div className="relative aspect-[16/10] overflow-hidden bg-ink">
        <PilotPortrait pilotId={p.pilot_id} version={p.pilot_version} className="transition-transform duration-500 group-hover:scale-[1.03]" />
        <span className="absolute left-3 top-3 rounded-full bg-ink/75 px-2.5 py-1 font-mono text-[11px] text-canvas">
          {p.pilot_id} · {p.pilot_version}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-[17px] font-semibold leading-snug tracking-[-0.01em] text-ink">{p.name}</h3>
          <ArrowRight size={18} className="mt-1 shrink-0 text-ink-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-water" aria-hidden />
        </div>
        <dl className="grid grid-cols-3 gap-2 text-[12px]">
          <div>
            <dt className="text-ink-tertiary">Fields</dt>
            <dd className="num text-[15px] font-semibold text-ink">{p.field_count ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-tertiary">Area</dt>
            <dd className="num text-[15px] font-semibold text-ink">{p.aoi_area_m2 ? formatArea(p.aoi_area_m2, "ha", 0) : "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-tertiary">Imagery</dt>
            <dd className="num text-[15px] font-semibold text-ink">{p.imagery?.[0] ? formatDate(p.imagery[0].acquired_at).replace(/^\d+ /, "") : "—"}</dd>
          </div>
        </dl>
        {f ? (
          <p className={cn("mt-auto flex items-center gap-2 rounded-[12px] px-3 py-2 text-[12.5px]", checked === 5 ? "bg-vegetation-soft text-vegetation" : "bg-warning-soft text-warning")}>
            <BookOpenCheck size={14} aria-hidden />
            {checked} of 5 inputs verified · {5 - checked} assumed, listed under Trust
          </p>
        ) : null}
      </div>
    </Link>
  );
}
