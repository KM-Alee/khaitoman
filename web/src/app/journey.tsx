/**
 * The five destinations, framed as the user's questions (docs/UI_SYSTEM.md › IA).
 * Route ids stay the PRD's (`workspace`, `compare`, `explore`, `impact`, `evidence`) so
 * shared links and the copilot's navigation keep working; the labels are plain.
 */
import type { ReactNode } from "react";
import { CloudRain, Coins, Map as MapIcon, Scale, ShieldCheck } from "lucide-react";
import type { Screen } from "./selection";

export interface JourneyStep {
  screen: Screen;
  /** Sub-screens that belong to this step (highlight the same nav item). */
  also?: Screen[];
  step: number;
  /** Plain nav label. */
  label: string;
  /** The PRD name of the destination, kept for traceability (tooltips, command menu). */
  precise: string;
  /** The user's question this destination answers. */
  question: string;
  /** One-line promise shown under the question. */
  blurb: string;
  icon: ReactNode;
  shortcut: string;
}

export const JOURNEY: JourneyStep[] = [
  {
    screen: "workspace",
    step: 1,
    label: "Plan",
    precise: "Workspace",
    question: "What's the best plan for this watercourse?",
    blurb: "Set the season, water and money, then let AabFlow find the best mix of works and water timing.",
    icon: <MapIcon size={18} />,
    shortcut: "1",
  },
  {
    screen: "compare",
    also: ["replay"],
    step: 2,
    label: "Compare",
    precise: "Compare",
    question: "How much better is it than today?",
    blurb: "The same season solved three ways, under identical conditions, field by field.",
    icon: <Scale size={18} />,
    shortcut: "2",
  },
  {
    screen: "explore",
    step: 3,
    label: "What if",
    precise: "Explore",
    question: "What if money or water is short?",
    blurb: "Change the budget, test bad years and water cuts, and challenge the plan's choices.",
    icon: <CloudRain size={18} />,
    shortcut: "3",
  },
  {
    screen: "impact",
    also: ["report"],
    step: 4,
    label: "Impact",
    precise: "Impact",
    question: "What does it cost, and who benefits?",
    blurb: "Water accounts, money, fairness between fields, global-goal indicators and a printable action plan.",
    icon: <Coins size={18} />,
    shortcut: "4",
  },
  {
    screen: "evidence",
    step: 5,
    label: "Trust",
    precise: "Evidence",
    question: "Can I trust these numbers?",
    blurb: "Every source, assumption and calculation behind the results, with what is verified and what is assumed.",
    icon: <ShieldCheck size={18} />,
    shortcut: "5",
  },
];

export function journeyFor(screen: Screen): JourneyStep {
  return JOURNEY.find((j) => j.screen === screen || j.also?.includes(screen)) ?? JOURNEY[0];
}

export function nextJourney(screen: Screen): JourneyStep | null {
  const i = JOURNEY.indexOf(journeyFor(screen));
  return i >= 0 && i < JOURNEY.length - 1 ? JOURNEY[i + 1] : null;
}
