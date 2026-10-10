/**
 * Plain-language vocabulary (docs/UI_SYSTEM.md › Language). Every expert term the UI shows
 * gets a plain label for first-time visitors, the precise term (kept for traceability), and
 * a one- or two-sentence "what this means". `<Term id>` renders the plain label with the
 * precise term and explanation behind hover/focus/tap. Copy only: no numbers live here.
 */
import type { PlanKind, SolverStatus } from "@/lib/api/types";

export interface GlossaryEntry {
  /** Short plain label shown in the UI. */
  plain: string;
  /** The precise term used in the specification, run records and reports. */
  precise: string;
  /** What it means, in plain words. */
  explain: string;
}

export const GLOSSARY = {
  B0: {
    plain: "Today's routine",
    precise: "B0 · fixed-roster baseline",
    explain:
      "Water is used the way it usually is: each field irrigates when its turn comes, with the ponds and pumps that already exist. No optimisation, no new works.",
  },
  B1: {
    plain: "Smarter timing",
    precise: "B1 · optimised, no new capital",
    explain:
      "Same water, same existing ponds and pumps, but the timing of irrigation and pumping is optimised. Shows how much better operations alone can do before anyone spends money.",
  },
  P: {
    plain: "Recommended plan",
    precise: "P · integrated investment portfolio",
    explain:
      "The optimiser may also fund new works (land levelling, ponds, canal repairs, pump use) within your budgets, and picks the combination that grows the most crop.",
  },
  R: {
    plain: "Bad-year-proof plan",
    precise: "R · robust plan",
    explain:
      "One plan chosen to do as well as possible in the worst of the tested weather and water-cut conditions, instead of only in a typical year.",
  },
  service: {
    plain: "Fair share received",
    precise: "Service ratio · canal receipt ÷ reference allowance",
    explain:
      "How much canal water a field actually receives compared with its reference allowance. 100% means it gets its full turn's worth; it is a planning reference, not a verified legal quota.",
  },
  tail: {
    plain: "Tail-end fields",
    precise: "Tail group",
    explain: "Fields farthest down the watercourse. They lose the most water to seepage on the way, so they are usually the first to go short.",
  },
  tailService: {
    plain: "Tail-end fields' fair share",
    precise: "Tail minimum service ratio",
    explain: "The lowest fair-share percentage among the tail-end fields: the field that is worst off at the end of the channel.",
  },
  production: {
    plain: "Crop harvested",
    precise: "Modeled production (kg)",
    explain: "Total harvest the crop model predicts for all fields in this plan. It is a model estimate, not a measured harvest.",
  },
  capex: {
    plain: "Money for new works",
    precise: "Capital commitment (gross project cost, PKR)",
    explain: "One-time spending on new works such as levelling, ponds or canal repairs. Shared repairs are charged once.",
  },
  opex: {
    plain: "Running cost this season",
    precise: "Seasonal operating expenditure (PKR)",
    explain: "Season costs such as pumping diesel or electricity and upkeep.",
  },
  groundwater: {
    plain: "Groundwater pumped",
    precise: "Groundwater abstraction (m³)",
    explain: "Water pumped from existing wells. It is finite, costs money, and its quality is not verified.",
  },
  productivity: {
    plain: "Crop per drop",
    precise: "Withdrawal productivity (kg/m³)",
    explain: "Kilograms of crop for every cubic metre of water taken from the canal and wells.",
  },
  worse: {
    plain: "Fields worse off",
    precise: "Fields worse off vs baseline",
    explain: "How many fields would harvest less than under today's routine. A good plan keeps this at zero, or says so plainly when it does not.",
  },
  capitalBudget: {
    plain: "Budget for new works",
    precise: "Capital budget (gross project commitment, PKR)",
    explain: "The most the committee is willing to commit to one-time works. Zero means no new works at all.",
  },
  operatingBudget: {
    plain: "Budget for running costs",
    precise: "Seasonal operating budget (PKR)",
    explain: "The most that can be spent this season on pumping and upkeep.",
  },
  shortage: {
    plain: "Canal water cut",
    precise: "Uniform reduction fraction",
    explain: "How much less water the canal delivers than its normal roster. Every turn is cut by the same share. 0% is a normal year.",
  },
  serviceFloor: {
    plain: "Protect a group of fields",
    precise: "Minimum service floor",
    explain: "A hard rule: every field in the chosen group must receive at least this fair-share percentage, even if total harvest drops.",
  },
  weather: {
    plain: "Weather year",
    precise: "Weather analog",
    explain: "A real past season's daily weather, chosen as typical, dry or wet. It is a scenario, not a forecast.",
  },
  supply: {
    plain: "Canal supply pattern",
    precise: "Supply profile",
    explain: "How canal water arrives over the season: the normal roster, an even cut, or a concentrated interruption.",
  },
  planningMode: {
    plain: "What are you planning?",
    precise: "Planning mode",
    explain:
      "Replay a past season, respond to the coming season with what can be ready in time, or plan new works for a later season. Which works are possible follows from their build times.",
  },
  optimal: {
    plain: "Best plan proven",
    precise: "OPTIMAL",
    explain: "The solver proved no better plan exists among the options modelled. It is a proof about the modelled options, not about every possible farming practice.",
  },
  feasible: {
    plain: "Good plan found",
    precise: "FEASIBLE",
    explain: "A valid plan was found, but the search stopped before proving it is the best one.",
  },
  infeasible: {
    plain: "No plan fits every rule",
    precise: "INFEASIBLE",
    explain: "No combination of the modelled options satisfies every rule you set. Relaxing a rule (budget, protection level) may help. It is not proof that the real situation is impossible.",
  },
  unknown: {
    plain: "No answer yet",
    precise: "UNKNOWN",
    explain: "The search ended without finding a valid plan or proving there is none.",
  },
  validated: {
    plain: "Water books balance",
    precise: "Physically validated",
    explain: "Every litre in the plan was traced day by day: it has a source, a route and a permitted time, and no pond releases water before it holds it.",
  },
  frontier: {
    plain: "Spend vs harvest",
    precise: "Resilience frontier",
    explain: "The same question solved at several budget levels, so you can see how much extra harvest each extra rupee buys.",
  },
  nondominated: {
    plain: "Best value for its cost",
    precise: "Nondominated among evaluated plans",
    explain: "No other tested plan grows more crop for the same or less money. Only the tested budget levels are compared.",
  },
  stress: {
    plain: "Bad-year test",
    precise: "Stress matrix (3 weather × 3 supply)",
    explain: "The plan is re-checked under 9 combinations of dry/typical/wet weather and normal/reduced/interrupted canal water.",
  },
  deliverable: {
    plain: "Plan can still be carried out",
    precise: "Deliverable",
    explain: "Whether the plan's scheduled water can actually arrive under that condition. If not, no harvest is shown for that cell.",
  },
  whyNot: {
    plain: "Why not this option?",
    precise: "Why-not / forced inclusion",
    explain: "Force an option the optimiser left out and solve again, to see exactly what it would cost or change.",
  },
  synergy: {
    plain: "Better together?",
    precise: "Synergy (none, A, B, A+B)",
    explain: "Solves four plans: neither option, each alone, and both. Shows whether two works help more together than separately.",
  },
  sensitivity: {
    plain: "Which assumptions matter",
    precise: "Sensitivity analysis",
    explain: "Re-solves with uncertain inputs (costs, prices, efficiencies) moved up and down to see which ones could change the decision.",
  },
  surrogate: {
    plain: "Quick estimate",
    precise: "Surrogate preview (LightGBM)",
    explain: "A fast machine-learning estimate trained on past crop-model runs. It is approximate and must be confirmed by the full crop model before use.",
  },
  replay: {
    plain: "Season replay",
    precise: "Season replay (crop and water traces)",
    explain: "Steps through the season day by day: when water arrived, when it was applied, pond levels and how the crop grew.",
  },
  revision: {
    plain: "Settings version",
    precise: "Scenario revision",
    explain: "An unchangeable snapshot of the settings a plan was solved with. Editing settings creates a new version; old results stay inspectable.",
  },
  run: {
    plain: "Saved calculation",
    precise: "Run",
    explain: "One completed solve, stored with its inputs, solver log and results so anyone can trace or reproduce it.",
  },
  sdg: {
    plain: "Global goals",
    precise: "SDG alignment proxies",
    explain: "Planning indicators that relate to UN Sustainable Development Goals 2.4, 6.4/6.5 and 13.1. They are project proxies, not official UN scores.",
  },
  evidence: {
    plain: "Sources and proof",
    precise: "Evidence and lineage",
    explain: "Where every input came from (satellite scenes, maps, weather, assumptions) and how each result was computed.",
  },
  aiBoundaries: {
    plain: "AI-drawn field boundaries",
    precise: "Delineate Anything inference, human-reviewed",
    explain: "Field outlines were detected by an AI model on real satellite imagery and then checked and corrected by a person.",
  },
  assumed: {
    plain: "Assumed, not yet verified",
    precise: "Assumption",
    explain: "A documented starting value that still needs local confirmation before real money is spent.",
  },
} satisfies Record<string, GlossaryEntry>;

export type TermId = keyof typeof GLOSSARY;

export const PLAN_TERM: Record<PlanKind, TermId> = { B0: "B0", B1: "B1", P: "P", R: "R" };

/** Plain plan names (cards, tables, map tags). The precise code stays visible next to them. */
export function planName(kind: PlanKind | string): string {
  return (GLOSSARY as Record<string, GlossaryEntry>)[kind]?.plain ?? kind;
}

export const SOLVER_TERM: Record<SolverStatus, TermId | null> = {
  OPTIMAL: "optimal",
  FEASIBLE: "feasible",
  INFEASIBLE: "infeasible",
  UNKNOWN: "unknown",
  MODEL_INVALID: null,
};

export const PLANNING_MODE_LABEL: Record<string, { plain: string; hint: string }> = {
  historical_replay: { plain: "Replay a past season", hint: "Known weather; a look back, not a forecast." },
  season_response: { plain: "Plan the coming season", hint: "Only works that can be ready in time." },
  capital_planning: { plain: "Plan new works", hint: "A later season, with time to build." },
};

export const GROUP_LABEL: Record<string, string> = { head: "Head-end", middle: "Middle", tail: "Tail-end", all: "All fields" };
