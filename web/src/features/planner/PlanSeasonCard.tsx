/**
 * "Plan my season" entry card (landing page, top-bar menu): one sentence in, a full planning
 * investigation out. Self-contained: it only navigates to the planner route with `?goal=`.
 */
import { useId, useState } from "react";
import { useNavigate } from "react-router";
import { Sparkles } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { EXAMPLE_GOALS, planSeasonHref } from "./timeline";

export interface PlanSeasonCardProps {
  pilotId: string;
  version: string;
  className?: string;
  /** Start text in the goal box. */
  initialGoal?: string;
  /** Card heading (default "Plan my season"). */
  title?: string;
}

const MAX_GOAL = 600;

export function PlanSeasonCard({ pilotId, version, className, initialGoal = "", title = "Plan my season" }: PlanSeasonCardProps) {
  const navigate = useNavigate();
  const [goal, setGoal] = useState(initialGoal);
  const id = useId();
  const go = (g: string) => {
    const text = g.trim().slice(0, MAX_GOAL);
    if (text) void navigate(planSeasonHref(pilotId, version, { goal: text }));
  };
  return (
    <Card tone="hero" className={cn("flex flex-col", className)} data-testid="plan-season-card">
      <CardHeader
        eyebrow="AI planner"
        title={title}
        description="Say what you need in one sentence. AabFlow runs the whole planning investigation with its real tools and writes a one-page decision brief."
      />
      <CardBody className="flex flex-col gap-3">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            go(goal);
          }}
        >
          <label htmlFor={id} className="text-[12.5px] font-medium text-ink-secondary">
            Your goal for the season
          </label>
          <textarea
            id={id}
            value={goal}
            maxLength={MAX_GOAL}
            rows={3}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                go(goal);
              }
            }}
            placeholder={EXAMPLE_GOALS[2].goal}
            className="w-full resize-y rounded-[12px] border border-border bg-surface px-3 py-2 text-[14px] leading-relaxed text-ink placeholder:text-ink-tertiary focus:border-water focus:outline-none focus-visible:ring-2 focus-visible:ring-water/30"
            data-testid="plan-goal-input"
          />
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Example goals">
            {EXAMPLE_GOALS.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => setGoal(g.goal)}
                title={g.goal}
                className="inline-flex h-[28px] items-center rounded-full border border-water/20 bg-water-soft px-3 text-[12px] font-medium text-water-deep transition-colors hover:border-water/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-water/30"
                data-testid={`plan-example-${g.id}`}
              >
                {g.label}
              </button>
            ))}
          </div>
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-[11.5px] text-ink-tertiary">Takes up to 4 minutes; every number comes from a saved run.</span>
            <Button type="submit" variant="primary" icon={<Sparkles size={15} />} disabled={!goal.trim()} data-testid="plan-start">
              Plan my season
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
