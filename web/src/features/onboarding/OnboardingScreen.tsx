/**
 * Guided regional onboarding (F03, PRD §5.3): AOI → sources → imagery/fields → graph →
 * parameters → validation → publish. Every stage reflects a real API record or job; the
 * stepper position is derived from the intake's server state, never from a timer.
 */
import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Check, Plus } from "lucide-react";
import { usePilots } from "@/lib/api/queries";
import { BrandMark } from "@/components/layout/NavigationRail";
import { ConnectionState } from "@/components/layout/ContextBar";
import { JobTray, JobWatchers } from "@/components/layout/JobTray";
import { StatePanel } from "@/components/status";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import type { ContextLayer } from "./AoiDrawMap";
import { IntakeWorkspace } from "./IntakeWorkspace";
import { NewIntake } from "./NewIntake";
import { useIntake } from "./onboardingApi";
import { STEPS, stepStatus, type StepKey } from "./wizard";

const STEP_ANCHOR: Record<StepKey, string> = {
  aoi: "aoi-check",
  sources: "sources",
  fields: "review",
  graph: "graph",
  params: "params",
  validation: "validation",
  publish: "publish",
};

function anchorFor(step: StepKey, hasIntake: boolean, state: string | undefined): string {
  if (!hasIntake) return STEP_ANCHOR[step];
  if (step === "aoi" || step === "sources") return "intake-summary";
  if (step === "fields" && !["needs_review", "reviewed", "validated"].includes(String(state))) return "processing";
  return STEP_ANCHOR[step];
}

interface PilotImagery {
  display_image_ref?: string;
  display_corners_wgs84?: [number, number][];
}

export function OnboardingScreen() {
  const { intakeId } = useParams();
  const pilots = usePilots();
  const intake = useIntake(intakeId);
  const [draftClosed, setDraftClosed] = useState(false);
  const onDraftChange = useCallback((c: boolean) => setDraftClosed(c), []);

  // Published pilots as display context (dashed AOI boxes and their package imagery).
  const context: ContextLayer[] = useMemo(
    () =>
      (pilots.data ?? [])
        .filter((p, i, all) => p.aoi_bbox && all.findIndex((q) => q.pilot_id === p.pilot_id) === i)
        .map((p) => {
          const img = (p as unknown as { imagery?: PilotImagery[] }).imagery?.[0];
          return {
            id: p.pilot_id,
            bbox: p.aoi_bbox!,
            label: p.name,
            image:
              img?.display_image_ref && img.display_corners_wgs84
                ? { url: `/assets/pilots/${p.pilot_id}/${p.pilot_version}/${img.display_image_ref}`, corners: img.display_corners_wgs84 }
                : null,
          };
        }),
    [pilots.data],
  );

  const steps = stepStatus(intake.data, { closed: draftClosed });
  const currentIndex = STEPS.findIndex((s) => s.key === steps.current);

  return (
    <div className="flex h-dvh flex-col bg-canvas" data-testid="onboarding">
      <JobWatchers />
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <Link to="/" className="flex items-center gap-2 rounded-[10px] px-1.5 py-1 text-ink-secondary hover:text-ink" aria-label="Back to pilots">
          <ArrowLeft size={16} aria-hidden />
          <BrandMark className="h-8 w-8" />
        </Link>
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">Add region</div>
          <h1 className="truncate text-[15px] font-semibold text-ink">Guided onboarding</h1>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {intakeId ? (
            <Link to="/onboarding" className={buttonClass("ghost", "sm")}>
              <Plus size={14} aria-hidden /> New intake
            </Link>
          ) : null}
          <ConnectionState />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label="Onboarding stages" className="shrink-0 border-b border-border bg-surface p-3 md:w-[260px] md:border-b-0 md:border-r md:p-4">
          <ol className="flex gap-1 overflow-x-auto md:flex-col" data-testid="stepper">
            {STEPS.map((s, i) => {
              const done = steps.done.has(s.key);
              const active = s.key === steps.current;
              const reachable = !!intakeId ? i <= Math.max(currentIndex, 1) || done : i <= currentIndex;
              const content = (
                <>
                  <span
                    className={cn(
                      "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px]",
                      done ? "border-vegetation bg-vegetation text-white" : active ? "border-water text-water-deep" : "border-border-strong/60",
                    )}
                  >
                    {done ? <Check size={12} aria-hidden /> : i + 1}
                  </span>
                  <span>
                    {s.label}
                    {done ? <span className="sr-only"> (done)</span> : null}
                  </span>
                </>
              );
              const cls = cn(
                "flex shrink-0 items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13px]",
                active ? "bg-water-soft font-semibold text-water-deep" : done ? "text-ink" : "text-ink-tertiary",
              );
              return (
                <li key={s.key} aria-current={active ? "step" : undefined} data-step={s.key} data-done={done || undefined}>
                  {reachable ? (
                    <a href={`#${anchorFor(s.key, !!intakeId, intake.data?.state)}`} className={cn(cls, "hover:bg-surface-muted")}>
                      {content}
                    </a>
                  ) : (
                    <span className={cls}>{content}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
        <main className="min-h-0 flex-1 overflow-y-auto p-3 pb-32 md:p-5 md:pb-32" id="onboarding-main">
          {!intakeId ? (
            <NewIntake context={context} onDraftChange={onDraftChange} />
          ) : intake.isLoading ? (
            <StatePanel state="busy" title="Loading the intake record…" />
          ) : intake.error ? (
            <StatePanel
              state="error"
              error={intake.error}
              title="Intake record unavailable"
              action={
                <Link to="/onboarding" className={buttonClass("secondary", "sm")}>
                  Start a new intake
                </Link>
              }
            />
          ) : intake.data ? (
            <IntakeWorkspace view={intake.data} context={context} />
          ) : null}
        </main>
      </div>
      <div className="pointer-events-none fixed bottom-3 right-3 z-30">
        <JobTray scopeKey={intakeId ? `onboarding:${intakeId}` : "onboarding:"} />
      </div>
    </div>
  );
}
