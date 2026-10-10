/**
 * Starter questions tuned to what the visitor is looking at (screen, run, field). Prompts
 * only; they never contain numbers from results.
 */
import type { Screen } from "@/app/selection";

export interface Suggestion {
  text: string;
  /** Short tag shown on the chip ("Plan", "What if", ...). */
  tag: string;
  lang?: "ur";
}

export interface SuggestionContext {
  screen: Screen;
  hasRun: boolean;
  planKind?: string | null;
  runHasPlan?: boolean;
  fieldLabel?: string | null;
  hasAnalysis?: boolean;
  tab?: string | null;
}

export function suggestQuestions(c: SuggestionContext, max = 6): Suggestion[] {
  const out: Suggestion[] = [];
  const add = (text: string, tag: string, lang?: "ur") => {
    if (!out.some((s) => s.text === text)) out.push({ text, tag, lang });
  };
  if (c.fieldLabel) {
    add(`Why does field ${c.fieldLabel} get this much water?`, "This field");
    add(`Show the season for field ${c.fieldLabel}.`, "This field");
  }
  if (c.hasRun && c.runHasPlan === false) {
    add("Why is there no valid plan, and what should we change first?", "No plan");
  }
  switch (c.screen) {
    case "compare":
    case "replay":
      add("How much better is the plan than today's routine?", "Compare");
      add("Which farmers lose out, and are the tail-end fields treated fairly?", "Fairness");
      break;
    case "explore":
      add("How robust is the plan in a dry year or if canal water is cut?", "Risk");
      add("Show the trade-off between spending and protecting tail-end fields.", "Trade-off");
      add("What if the canal is closed for two weeks?", "What if");
      break;
    case "impact":
    case "report":
      add("Where does all the canal water actually go?", "Water");
      add("Is the pond worth the money?", "Money");
      add("What does this plan mean for the Sustainable Development Goals?", "Impact");
      break;
    case "evidence":
      add("How is the crop yield calculated, and can I trust it?", "Trust");
      add("Which assumption should we check before spending?", "Trust");
      break;
    default:
      break;
  }
  if (c.hasRun) {
    add("What's the best plan for our canal? Keep it simple.", "Plan");
    add("What if we only had 10 lakh rupees to spend?", "What if");
    add("Which farmers lose out?", "Fairness");
    add("How robust is this plan in a dry year?", "Risk");
    add("What are the steps, and who has to do what?", "Action plan");
  } else {
    add("What's the best plan for this watercourse?", "Plan");
    add("Where does the canal water go?", "Water");
    add("How does this tool decide, and what is assumed?", "Trust");
  }
  add("اگر نہر دو ہفتے بند رہے تو فصل پر کیا اثر ہوگا؟", "اردو", "ur");
  // Keep the Urdu example even when trimming, so bilingual support is visible.
  const urdu = out.filter((s) => s.lang === "ur");
  const rest = out.filter((s) => s.lang !== "ur");
  return [...rest.slice(0, max - urdu.length), ...urdu].slice(0, max);
}
