/**
 * "Plan my season" (WIN_PLAN P2, docs/COPILOT.md §12).
 * - `PlanSeasonScreen`: the route `/p/:pilotId/:version/plan-season?turn=&goal=` (registered in App.tsx).
 * - `PlanSeasonCard`: the landing/top-bar entry card ({pilotId, version, className?, initialGoal?, title?}).
 * - `planSeasonHref(pilotId, version, {turn?, goal?})`: link to a saved replay or a live goal.
 */
export { PlanSeasonScreen } from "./PlanSeasonScreen";
export { PlanSeasonCard, type PlanSeasonCardProps } from "./PlanSeasonCard";
export { EXAMPLE_GOALS, planSeasonHref } from "./timeline";
