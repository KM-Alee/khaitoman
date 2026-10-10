/**
 * Landing "Plan my season" band: the goal card (live) beside the saved investigation from the
 * seeded session (`plan_turn_id`), which replays from its stored event log.
 */
import { Link } from "react-router";
import { History, PlayCircle } from "lucide-react";
import { PlanSeasonCard, planSeasonHref } from "@/features/planner";
import { useDemoSession } from "@/features/tour/api";
import { useHeadline } from "@/lib/api/showcase";
import { buttonClass } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/formatting";

export function PlanSeasonSection({ pilotId, version }: { pilotId: string; version: string }) {
  const demo = useDemoSession();
  const h = useHeadline();
  const s = demo.kind === "ready" || demo.kind === "incomplete" ? demo.session : null;
  const turn = s?.plan_turn_id ?? null;
  const pid = s?.pilot_id ?? h.data?.pilot_id ?? pilotId;
  const ver = s?.pilot_version ?? h.data?.pilot_version ?? version;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]" data-testid="plan-season-section">
      <PlanSeasonCard pilotId={pid} version={ver} />
      <div className="flex flex-col justify-between gap-4 rounded-[22px] border border-border bg-surface p-6 shadow-1">
        <div>
          <p className="eyebrow flex items-center gap-2 text-wheat-ink">
            <History size={14} aria-hidden /> Watch one first
          </p>
          <h3 className="display mt-2 text-[24px] leading-tight text-ink">See the AI plan a whole season in about a minute</h3>
          <p className="mt-2 text-[14px] leading-relaxed text-ink-secondary">
            It reads the watercourse, solves the plans, tests budgets and bad years, checks who goes short, and writes a one-page brief. Every step is a real stored run.
          </p>
          {s?.plan_goal ? (
            <blockquote className="mt-4 border-l-2 border-wheat pl-3 text-[14px] italic text-ink">“{s.plan_goal}”</blockquote>
          ) : null}
        </div>
        {turn ? (
          <div className="flex flex-col gap-2">
            <Link to={planSeasonHref(pid, ver, { turn })} className={buttonClass("secondary", "lg", "self-start")} data-testid="plan-season-saved">
              <PlayCircle size={17} aria-hidden /> Replay the saved investigation
            </Link>
            <span className="text-[12px] text-ink-tertiary">
              Saved investigation · computed {formatDateTime(s?.plan_computed_at ?? null)} · you can run it live from there
            </span>
          </div>
        ) : (
          <p className="text-[12.5px] text-ink-tertiary">No saved investigation yet (seed one with make demo-seed and --plan-goal). Try your own goal on the left.</p>
        )}
      </div>
    </div>
  );
}
