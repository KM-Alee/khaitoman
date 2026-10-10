# AabFlow: talking points

Speaker notes for the pitch and the Q&A. Every number below comes from a stored run, analysis
or evidence file in this repo. The source is named in brackets. Seeded demo session:
`data/demo/session.json`. If you re-seed, the numbers change: re-read them from
`GET /api/v2/demo/headline` and `GET /api/v2/ai-stack` before you present.

Pilot: **Lower Chenab representative pilot A**, Rabi wheat 2027-28, capital-planning mode,
30 reviewed fields, ₨30 lakh capital budget.

---

## 1. The one-liner

> **Test the season before you spend.** AabFlow is an AI planning agent for a village water
> committee. It **sees** every field from space, **predicts** the crop in milliseconds, **plans**
> the best use of a small budget with a proof attached, and **explains** it in English or Urdu.

## 2. The hook (30 seconds; say it with the landing page on screen)

- A few dozen farmers share one watercourse. The **tail** farmer, at the far end, gets water last.
- Each season the committee can fund only some improvements: laser levelling, a pond, a canal
  repair, extra pumping.
- **The twist our model found.** "Just optimise what we already have" grows **8.3% more wheat**,
  but it cuts the worst-off tail field from **61% to 44%** of its water.
  [B0 `run_8b6f…`, B1 `run_6980…`]
- **AabFlow's integrated plan** grows **+18.8% wheat** (129.7 t → **154.1 t**), keeps the tail at
  **61%**, and uses **65% of the budget** (₨19.5 lakh of ₨30 lakh). [P `run_5f2a…`]
- Say the cost too: it pumps **8,288 m³** of groundwater where today's routine pumps none, within
  each well's cap. Being upfront about trade-offs is why committees can trust it.

## 3. "Is AI really the core?" (the four engines)

| Engine | What it does | Proof on screen |
|---|---|---|
| **Sees** | Delineate Anything segmentation on Sentinel-2 found **931** possible fields on pilot A (**1,234** across both pilots). Review rules plus a person kept the **30** clearest per pilot. | Tour step 2, "The AI reveal": 931 outlines recede to the 30 reviewed fields. [`review_log.json`] |
| **Predicts** | A LightGBM model **we trained on GPU** on **45,619** executed AquaCrop simulations. Held-out error about 7–8% (wheat nMAE 0.071, cotton 0.080). One estimate takes **~6.8 ms** (benchmark). On the live server the slider measured **6–15 ms**. | What if › Quick estimate: drag the water slider, then "Verify with crop model" for the exact answer. [`data/models/surrogate-v7-gpu/evaluation.json`, `evidence/benchmarks/p04-preview-timing.json`] |
| **Plans** | An exact optimiser (CP-SAT) searched **7,745** candidate field policies and **proved** the best plan (gap 0%) in **368 ms**. | The "Best plan proven" badge on every result. [P run, its candidate library] |
| **Explains** | GPT-6 Luna with **27 real tools**. It never types a number: every chart is built on the server from tool results, and any untraceable figure is withheld. It answers in Urdu. | Ask box on the landing page; **Plan my season**. |

The loop judges should remember: **perceive → simulate → decide → explain and act.**

## 4. The three reveals (what the tour shows)

1. **Where extra money stops paying off** (frontier: 6 settings, each its own solved run).
   ₨0 → 140.5 t · ₨5 lakh → 152.9 t · ₨15 lakh → 153.3 t · ₨30 lakh → 154.1 t · ₨80 lakh → 154.6 t.
   **The first ₨5 lakh buys +12.4 t. The next ₨75 lakh buys only +1.7 t.**
   AabFlow tells a committee when *not* to spend. A 95% tail-service floor at ₨30 lakh is
   **proven infeasible**: an honest "no", not a fake "yes". [`ana_5bfa…`]
2. **Bad years.** The robust plan (R) is deliverable in **all 9** weather × supply states
   (dry/typical/wet × normal, 22% cut, 14-day closure). Dry-year production is 55.3 t, typical
   126.8 t, wet 175.7 t. Where a plan breaks a rule, AabFlow names the rule and reports **no
   yield** for that state instead of inventing one. [`ana_4e96…`]
3. **The budget cut.** Drop the budget to ₨5 lakh and the plan changes: three works drop out and
   capital falls from ₨19.5 lakh to ₨3.6 lakh, while production stays at **152.9 t**.
   [budget-change revision, P `run_ddef…`]

## 5. Plan my season (the big moment)

- Type one sentence: *"We have ₨10 lakh. Don't hurt the tail farmers, and make sure it survives
  a dry year."*
- The agent runs a real investigation and streams each step: it reads the context, solves the
  plan ladder, builds a budget frontier, stress-tests the plan, checks fairness, and writes a
  one-page decision brief with a recommendation, KPIs, charts, dated actions and caveats.
- Every step creates ordinary stored runs and analyses. If something doesn't finish in time,
  the brief says what is missing. It never says "done" when it isn't.
- On stage, start with the **saved investigation** (replay, labelled "Saved investigation"),
  then press **Run it live** as the encore.

## 6. Why it is useful

- **It replaces arguments with evidence.** The committee leaves with a one-page, dated action
  plan (`make print-brief`): who does what, when, at what cost, and who still goes short.
- **It protects the weakest farmer by default.** Tail fairness is measured on every run.
- **It saves money before it is spent.** The frontier shows where returns flatten.
- **It plans for bad years.** APP projects a 22% water shortage for Rabi 2026–27; a plan that
  only works in a typical year is a liability.
- **It scales by onboarding.** Draw an area → the AI finds the fields → review → publish. Pilot B
  `reviewed-v2` was published that way.
- **It runs offline.** Planning, the crop model and the optimiser run locally in Docker. Only
  the chat needs the internet.

## 7. Q&A: likely challenges

- **"Isn't this just ChatGPT?"** No. The language model calls 27 real tools, and the server
  builds every chart from tool results. Numbers it can't trace are withheld.
- **"You didn't train the vision model."** Correct: it's a strong pretrained segmenter. We built
  the pipeline around it: review rules, human correction with version conflicts, and publishing.
  We trained the crop model ourselves, on GPU, and gated it on held-out years.
- **"Is optimisation AI?"** Constraint reasoning and search are classic AI, and it's the part that
  *decides*, with a proof attached.
- **"Are the yields real?"** They are crop-model estimates. The model is **not calibrated** for
  these districts, so absolute yields are indicative; the comparisons between plans are the
  product. Calibration needs a supervised pilot.
- **"Are the water rights and costs real?"** They are **assumed** from documented sources. They are
  labelled on screen and editable. We don't claim measured rights or quoted costs.
- **"How accurate is the field detection?"** Not estimated: there are no independent reference
  boundaries for these sites. We report the review rate instead (pilot A: 931 raw, 30 selected).
- **"Is the plan the best possible?"** It's proven best *within the candidate options we
  generated* (7,745 policies), not the best possible farming in the real world.
- **"Has the copilot been formally evaluated?"** Not yet. The 30×3 evaluation (AT17) has not been
  run, so we don't claim it. We've run live smoke turns; the Urdu landing question answered in
  Urdu with a map and a comparison in 54 s. [`evidence/copilot/landing-urdu-20261010T1526Z.json`]

## 8. Close

> "This is what the committee takes home." (Hold up the printed brief.) "Next step: a supervised
> pilot with a Water User Association programme to calibrate the crop model and verify rights
> and costs. Who wants to be first?"

## 9. Don't say

- Don't say AT17 has passed, or that yields are calibrated.
- Don't say rights or costs are measured.
- Don't show the recorded fallback video as live; it carries a permanent **RECORDED** badge.
