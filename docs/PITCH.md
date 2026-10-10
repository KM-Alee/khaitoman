# AabFlow: the pitch, the proof, and the plan to win

> **Test the season before you spend.**
> AabFlow lets a village water committee try out irrigation investments on a digital copy of its own watercourse. Before anyone spends a rupee, it shows how much crop each choice grows, what it costs, how much water it uses, and which farmers at the far end of the canal still go short.

Every number in this document comes from a run that was actually executed in this repo. Each one says which pilot, season and run it comes from. If a number isn't measured yet, this document says so. (Anything marked *[add source]* needs a citation before it goes on a slide.)

---

## 1. The story (open with this)

**The people.** In Punjab, a few dozen farmers share one *watercourse*, a small earthen channel fed by a government canal. They take turns: each field gets water for a fixed slot each week (*warabandi*). The fields nearest the canal (the **head**) get water first. The fields at the end (the **tail**) get whatever is left after seepage and losses.

**The decision.** Each season the Water User Association committee has a small budget. One farmer wants a storage pond. Another wants his field laser-leveled. Someone says the channel needs lining. The pump owner offers to pump more groundwater. **They can afford only some of these, and they choose by argument, habit, or whoever speaks loudest.**

**The squeeze.** APP reports a projected **22% system-level water shortage for Rabi 2026–27** in Punjab and Sindh ([APP](https://www.app.com.pk/national/22pc-water-shortage-projected-for-rabi-season-2026-27/)). Less water means every rupee and every turn matters more, and the tail farmers are the first to lose.

**The twist our model found** (real runs: pilot A, Rabi wheat 2026-27, 30 reviewed fields):

| Plan | What it is | Wheat produced | Worst-served tail field gets | New capital |
|---|---|---|---|---|
| **B0** | Today's fixed turns, no changes | 129.0 t | **62%** of its reference water | ₨0 |
| **B1** | Smarter timing with existing pumps only | 138.3 t (+7%) | **46%** ⚠️ | ₨0 |
| **P** | AabFlow's integrated plan | **150.5 t (+17%)** | **56%** | **₨357,893** of a ₨1,500,000 budget |

> *"Just optimise what we already have" really does grow more wheat, but it **quietly takes water from the tail farmer** (62% → 46%). AabFlow catches that. Its integrated plan grows **17% more wheat than today**, gives most of the tail farmer's water back, and spends **less than a quarter of the money available**."*

That is the hook: **better harvest, fairer split, smaller bill**, and you can see the trade-off before you commit.

> Note: P pumps 7,149 m³ of groundwater, where B0 pumps none. Say so on stage. Being upfront about the costs of a plan is part of what makes the tool credible.

**Two more reveals from executed runs** (pilot A, wheat 2027-28, capital-planning mode; `evidence/benchmarks/analyses-20261010T114936Z.json`):

1. **Where extra money stops paying off (resilience frontier, 6 settings, all solved to optimality):**
   ₨0 → 140.5 t · ₨5 lakh → 152.9 t · ₨15 lakh → 153.3 t · ₨30 lakh → 154.1 t · ₨80 lakh → 154.6 t.
   **The first ₨5 lakh buys +12.4 t. The next ₨75 lakh buys only +1.7 t.** AabFlow tells a committee when *not* to spend.
   Asking for a 95% tail-service floor at ₨30 lakh is **proven infeasible** within the candidate options. That is an honest "no" rather than a fake "yes".

2. **The plan that looks best on paper breaks in a bad year (9-state stress test).**
   The plan optimised for a typical year **cannot be delivered in 6 of 9 tested states**: every shortage or canal-closure scenario. AabFlow names the rule each one breaks and reports **no yield** for those states instead of a made-up number.
   The **robust plan** holds up in **all 9 states**. In return it gives up 27,360 kg of production in a typical year. That is insurance with a price tag the committee can see.

---

## 2. What AabFlow does, in plain words

AabFlow answers the four questions a committee actually asks:

| Their question | What AabFlow shows |
|---|---|
| **"What should we do this season?"** | Today's turns (B0) vs smarter use of what we have (B1) vs the best investment portfolio (P) vs the safest plan (R), all under identical conditions, with a dated action list per field. |
| **"Is it worth the money, and who benefits?"** | Cost, crop gained, groundwater pumped, water productivity, and a field-by-field breakdown of head, middle and tail service, all computed by the server. |
| **"What if the water doesn't come?"** | Dry, typical and wet weather × normal, 22%-cut and 14-day-closure supply: 9 stress states. A replay of the season day by day shows when a pond fills and empties and when crops get stressed. |
| **"Why should we trust it?"** | Every number links to its run ID, data source, licence, assumption and validation check. Assumptions (water rights, costs, uncalibrated crop model) are labelled on screen, never hidden. |

You can also just **ask** the AI assistant in English or Urdu ("Which farmers lose out?" or "What if the canal closes for two weeks?"). It runs the real tools and answers with charts, tables and map highlights.

---

## 3. Feature tour (what's built)

| Area | What it does | Status today |
|---|---|---|
| **Real geography (F01)** | Two real pilots on the Lower Chenab, each with Sentinel-2 imagery, terrain, mapped canals and 30 reviewed fields. A 3D map shows yield as field height and colour. | Built; AT01 passed |
| **Field-detection AI (F02)** | *Delineate Anything* segmentation on Sentinel-2 found **931 field polygons** (pilot A) and **303** (pilot B). Rule-based review plus a visual check kept the best 30 per pilot. Raw AI output and reviewed fields are both viewable. | Built; detections cached |
| **Onboard a new region (F03)** | Draw an area, run or reuse the AI, review the fields (reject or redraw, with conflict protection), validate, and publish a new immutable pilot version. Pilot B `reviewed-v2` was published this way. | Wizard just wired; AT16 not yet run |
| **Crop & weather science (F04)** | AquaCrop (FAO crop model) for wheat and cotton on historical Open-Meteo weather. **45,619 exact crop simulations** are stored. | Built; AT02 passed |
| **Water rules (F05)** | A day-by-day water ledger: delivery routes, turn windows, pond storage (no water released before it exists), shared pump capacity. Physically impossible plans are rejected. | Built; AT03/AT04 passed |
| **Five kinds of action (F06)** | Timing changes, laser leveling, farm ponds, shared channel repair, existing-pump top-up. Each has a cost, a commissioning date and prerequisites. | Built |
| **Live re-planning (F07)** | Change the budget or a water cut and the plan is re-solved in seconds by an exact optimizer (CP-SAT), with proven optimality or an honest "unknown". | Built; AT05–AT08 and AT12 passed |
| **Fair comparison ladder (F08)** | B0 → B1 → P → R, all solved under the same conditions, with a matched-comparison certificate. | Built |
| **Season replay (F09)** | Scrub through the season: canal receipts, pond level, pumping, canopy and biomass growth per field. | Built |
| **Frontier (F10)** | Six or more budget/fairness settings, each its own solved run; shows where spending stops paying off. | Built; AT09 passed |
| **Stress & robust plan (F11)** | A 3×3 weather × supply matrix. States a plan can't deliver show the broken rule and no yield. | Built; AT10 passed |
| **Instant crop preview (F12)** | A LightGBM model **trained on our 45k simulations on an RTX 5060 GPU** predicts yield in **6.8 ms**, then an exact AquaCrop run confirms it. Held-out error is about 8% (wheat 7.8–7.9%, cotton 8.0–8.1% nMAE). | Built; model gates pass |
| **Why-not & synergy (F13)** | "Why didn't you pick the pond?" forces it in and shows the cost. Pairs of actions are tested for whether they help each other. | Built |
| **Money, fairness, water (F14/F15)** | Action plan, economics, head/middle/tail equity, and a water-flow diagram showing every cubic metre's source and destination. | Built |
| **Impact & SDGs (F16)** | SDG 2.4 / 6.4 / 13.1 proxy cards read from stored metrics, each with its formula and limitations. **No made-up 0–100 score; CO₂ is honestly "not estimated".** | Built |
| **Evidence & reproducibility (F17)** | Every source with its licence and hash. Both published pilots re-derive byte-for-byte. A proof package (`make evidence-pack`): 805 files, all hash-verified. | Built |
| **Design & guided tour (F18)** | A plain-language interface aimed at non-experts, with an animated guided tour that opens saved real runs. You can leave the tour at any point and try things live. | In progress |
| **AI copilot (F19)** | GPT-6 Luna with **27 tools** over the real services: answers in charts, tables and map highlights, runs what-ifs, answers in Urdu, and every number is traced to a tool result. | Backend built (6/7 live smoke turns finished within the 90 s budget); chat UI in progress; formal 30×3 evaluation **not run** |
| **Reliable demo (F20)** | Runs in Docker from frozen images; core analytics work offline. | Cold-launch timing not measured yet |

---

## 4. Why it is genuinely useful

- **It replaces arguments with evidence.** The committee leaves with a printed, dated action plan that shows who does what, when, at what cost, and who still goes short. This is something they can take to a funder or an extension officer.
- **It protects the weakest farmer by default.** Fairness to tail fields is measured on every run, not left as an afterthought. Our very first comparison showed "efficient" can mean "unfair".
- **It saves money before it is spent.** Seeing where returns flatten (₨5 lakh vs ₨80 lakh above) is worth more than any single optimisation.
- **It plans for bad years, not average ones.** With a 22% shortage on the horizon, a plan that only works in a typical year is a liability.
- **It is honest about uncertainty.** Assumed water rights, assumed costs and an uncalibrated crop model are badges on screen. This is what a real program officer needs before trusting a tool.
- **It scales by onboarding, not custom work.** Draw a new area → AI finds the fields → review → publish. Pilot B v2 went through exactly that path.

**Who would use it.** The operator is a WUA coordinator or extension officer. The first buyer is likely a program funding irrigation improvement or resilience work. IWMI's PRIAT project runs water budgeting and participatory planning with **72 WUAs** in Punjab ([IWMI](https://www.iwmi.org/projects/strengthening-community-level-water-management-in-punjab-priat-project/)), which shows the workflow exists. (This is not a partnership or customer claim.) The pitch ask is **a supervised pilot partner**.

---

## 5. Is AI the core? An honest assessment

AabFlow has four AI layers. A judge will grade how much each one **carries the product** and how **visible** it is.

| Layer | What it is | Is it really load-bearing? | Is it ours? | Visible to a layperson today? | Score |
|---|---|---|---|---|---|
| **Perception**: field detection | Delineate Anything (deep segmentation) on Sentinel-2: 931 + 303 detections | **Yes**: without it there are no fields and no onboarding | Pretrained model; our pipeline, review rules and onboarding | Medium: buried on the map | 7/10 |
| **Prediction**: crop surrogate | LightGBM trained on 45,619 AquaCrop simulations on GPU; ~8% held-out nMAE; 6.8 ms | Medium: speeds up exploration, and every recommendation is still confirmed exactly | **Fully ours**: data, training, validation gates | Low: hidden in an "Explore" tab | 6/10 |
| **Decision**: planner | CP-SAT constraint optimisation over exact candidate libraries (17,480 policies for pilot B), robust selection, frontier | **Yes**: this is the brain that picks the plan | Ours (model formulation) | High, but people call it "math", not "AI" | 8/10 |
| **Language**: copilot agent | GPT-6 Luna, 27 tools, grounded charts, Urdu, number tracing | Currently an add-on | Agent design, tools and grounding are ours | **Highest**: what laypeople think AI is | 6/10 now, 9/10 with the big improvement |

**Verdict: about 7/10 as currently presented.** The AI is real and does real work in at least three layers. The risk is in the *presentation*. A non-expert judge will see a beautiful map-and-charts dashboard with a chat box on the side and conclude "GIS + optimisation + ChatGPT wrapper". The pieces that make AabFlow special (AI that finds the fields, a model trained on our own 45k simulations, an AI planner that proves its answer) are hidden behind tabs.

**How to frame it on stage:** *"AabFlow is an AI planning agent with four senses: it **sees** fields from satellite, **predicts** crops in milliseconds, **plans** with a provably optimal solver, and **explains** in your language."*
Then make each layer visible in the demo (quick wins 1–4 below) and make the agent the protagonist (the big improvement).

**What to say if challenged:**
- *"Isn't this just ChatGPT?"* No. The language model never makes up a number. It calls 27 real tools, and the server builds every chart from tool results. Any number in its text that can't be traced to a tool result is withheld.
- *"You didn't train the vision model."* Right. We used a strong pretrained segmenter and built the pipeline around it: rule-based quality review, human correction with version conflicts, and publishing. We trained the crop surrogate ourselves on GPU and gated it on held-out years.
- *"Is optimisation AI?"* Constraint reasoning and search are classic AI. And it's the part that *decides*, with a proof attached.

---

## 6. Small changes with a big effect (do these first)

Ordered by impact per hour. Each takes roughly 0.5–2 hours.

1. **Lead with the tail-farmer twist.** On the landing page and the tour's first screen, show one sentence and three numbers from the real B0/B1/P runs: *"Optimising without investment cut the tail farmer's water from 62% to 46%. AabFlow's plan: +17% wheat, tail back to 56%, for ₨3.6 lakh."* Text and numbers come from server metrics, never hard-coded.
2. **An "AI inside" strip.** Four badges (Sees · Predicts · Plans · Explains), each with one live fact (931 fields detected · 6.8 ms prediction · optimal plan proven · 27 tools) and a link to its proof. It answers the "is AI the core?" question in five seconds.
3. **Make the field-detection AI dramatic.** In the tour's second step, animate the raw detections (931 outlines) collapsing to the 30 reviewed fields, with a toggle back to the raw output. Seeing AI at work on real satellite imagery is the strongest single visual in the product.
4. **Put the instant-crop slider in the tour.** Drag the irrigation amount and the yield updates in milliseconds (surrogate), then press "Confirm with exact science" (AquaCrop). It turns an invisible model into a magic moment, and the distinction between preview and exact result is itself a trust story.
5. **Make the copilot the front door.** An "Ask AabFlow anything" box on the landing page, with three suggested questions that can be answered from saved analyses (fast, because the `read_analysis` tool reuses stored frontier and stress results). Ask one question in **Urdu** live; it already works.
6. **Hand the judges paper.** Print the one-page action plan for the hero run (the report already exists). Something a judge can hold beats any slide.
7. **Show money in judges' units.** Next to PKR, add an approximate USD figure using a dated exchange rate shown on screen. It must be a server-side or display-only conversion that is clearly labelled.
8. **Rehearse the safety nets.** Seed the demo session (`make demo-seed`), do a cold `make demo` launch, and record a backup video labelled **"recorded"**. Optional but impressive: pull the network cable mid-demo and keep planning, because the core runs offline.

## 7. The one big improvement: "Plan my season", an autonomous planning agent

**What it is.** One box, one sentence:
> *"We have ₨10 lakh. Don't hurt the tail farmers, and make sure it survives a dry year."*

The GPT-6 Luna agent turns that into an **investigation plan** and **executes it as a background job**, streaming each step on screen while the map reacts:

1. Read the context → 2. solve the B0/B1/P ladder → 3. run the budget frontier → 4. stress-test the best candidates across the 9 states → 5. ask "why not" about the disputed pond → 6. pick the robust plan that meets the fairness floor → 7. write a **one-page decision brief**: recommendation, charts, trade-offs, caveats, and every run ID.

**Why this one change raises the whole project a level:**
- **The AI becomes the core loop, not a sidebar.** The demo becomes *perceive* (vision) → *simulate* (crop model + surrogate) → *decide* (optimizer) → *explain and act* (agent). That loop is exactly what "AI as the core technology" means.
- **Laymen get it instantly.** They watch an AI do a planner's day of work in about a minute, on a real map, with real numbers. It also replaces a demo of five screens with one sentence.
- **It's mostly built already.** The 27 tools, server-built visual blocks, number tracing, saved analyses and the job/event system all exist. The new work is an agent "plan then execute" loop that runs as a **job** (so it isn't capped by the 90 s chat turn), a step-timeline view, and a brief template on top of the existing report.
- **It's safe.** Every step creates ordinary immutable runs and analyses, every number is traced, and the parent scenario is never changed. If any step fails, the brief says what wasn't completed; it never says "done" when it isn't.

**Effort and risk.** About 6–10 focused hours for one strong agent. The main risk is latency (around 14 s per model call). Keep the plan to at most 6 tool rounds, call tools in parallel, reuse saved analyses, and pre-seed the hero question so the first live run is warm.

---

## 8. Five-minute demo script

| Time | On screen | Say |
|---|---|---|
| 0:00 | Landing page: the tail-farmer twist | "A committee can fund only some improvements. Optimising without investment quietly cut this tail farmer's water from 62% to 46%. Let's fix that." |
| 0:35 | Map: AI detections → 30 reviewed fields on real Sentinel-2 | "Our AI found 931 fields from satellite; we reviewed and kept the 30 best. Rights and costs are labelled as assumed, right there." |
| 1:00 | Run B0 · B1 · P live | "Same conditions, three plans. +17% wheat, tail back to 56%, using a quarter of the budget." |
| 1:50 | Change the budget → re-solve live | "Cut the budget: watch the plan change in seconds. Every result is a new, traceable run." |
| 2:35 | Replay the decisive week | Narrate what the hero run's replay actually shows (pick the interval during rehearsal, e.g. a pond release or pump top-up that keeps a tail field going). Don't script an event the run doesn't contain. |
| 3:15 | Frontier + stress matrix | "The first ₨5 lakh buys 12 tonnes; the next ₨75 lakh buys under 2. And the 'best' plan fails in 6 of 9 bad seasons. The robust one doesn't." |
| 3:45 | **"Plan my season"** (or copilot) in Urdu/English | "Now the AI does the whole investigation from one sentence, and every number is traced to a real run." |
| 4:25 | Printed action plan + evidence page | "This is what the committee takes home. Next step: a supervised pilot with a WUA program. Who wants to be first?" |

## 9. Honest limits (say them before a judge does)

- **The crop model is uncalibrated** for these districts. Absolute yields are indicative; the *comparisons* between plans are the product. Calibration needs a supervised pilot.
- **Water rights, roster rates and action costs are assumed** from documented sources. Each is labelled and can be edited.
- **Field-detection accuracy is not estimated**, because there are no independent reference boundaries for these sites. We report the review rate instead.
- **The optimiser proves the best plan within its finite set of candidate options**, not the best possible farming in the real world.
- **Copilot:** 6 of 7 live smoke turns finished inside the 90 s budget. The formal 30×3 evaluation (AT17) has **not** been run. Do not claim it.
- **Not yet verified:** offline mode (AT15), restart recovery (AT18), the accessibility pass (AT14), and cold-launch timing.
