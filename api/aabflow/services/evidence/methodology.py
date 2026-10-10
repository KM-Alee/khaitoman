"""Curated methodology corpus for evidence search (T11.6).

Short, topic-chunked statements of how AabFlow computes and what each result
does and does not establish. These are product documentation, not measurements.
"""

from __future__ import annotations

METHODOLOGY: list[dict[str, str]] = [
    {
        "id": "method:solver-proof-scope",
        "title": "What a solver proof means",
        "section": "T6.4",
        "body": "OPTIMAL, FEASIBLE, INFEASIBLE and UNKNOWN describe the finite candidate-policy model only. "
        "An optimal plan is the best combination of the vetted candidate policies under the stated budgets, "
        "supply and service constraints; it is not a proof of the best possible real-world farming practice. "
        "Global optimality across shared-repair configurations requires every configuration to be proven "
        "infeasible or bounded no better than the incumbent.",
    },
    {
        "id": "method:infeasibility-kinds",
        "title": "Kinds of infeasibility",
        "section": "T5.7",
        "body": "An infeasible run distinguishes missing valid input, an empty field option set, finite candidate "
        "incompatibility (for example a service floor no retained candidate meets), and an independently "
        "established bound contradiction. Only the last supports a physical-impossibility explanation. "
        "A timeout without an incumbent is UNKNOWN, not infeasible; a failed job is neither.",
    },
    {
        "id": "method:integer-scaling",
        "title": "Conservative integer scaling",
        "section": "T6.2",
        "body": "Water uses a quantum of 0.1 m3: resource consumption rounds up and capacities round down; credited "
        "service rounds down and required service rounds up. Production uses a 0.1 kg quantum rounded down, and "
        "the aggregate objective quantization bound is reported. Rounding may create false infeasibility but "
        "never false feasibility. Every accepted plan is re-validated at original float precision.",
    },
    {
        "id": "method:lexicographic",
        "title": "Tie-breaks after the primary objective",
        "section": "T6.3",
        "body": "After the primary objective (modeled crop production, or worst tested production for robust plans) "
        "the solver preserves the attained integer primary value and minimizes operating spend, then capital "
        "commitment, then canal source withdrawal. Each stage records its own proof status.",
    },
    {
        "id": "method:baseline-ladder",
        "title": "Baseline ladder B0, B1, P, R",
        "section": "PRD 6.4",
        "body": "B0 is the fixed-roster operating habit executed through the ledger and crop model. B1 optimizes "
        "operations of existing assets with new capital fixed at zero. P selects eligible investment instances "
        "and operations under budgets. R selects one shared plan that is physically valid in every state of the "
        "uncertainty set and maximizes the worst tested production. All share supply, weather, crop parameters "
        "and initial state, so differences come from the defined treatment.",
    },
    {
        "id": "method:service-ratio",
        "title": "Receipt / reference allowance",
        "section": "T4.3",
        "body": "Field service is canal receipt at the field divided by a fixed reference allowance at the same "
        "boundary. When the right is time-based the denominator is derived from an assumed discharge, so the "
        "ratio is a receipt / reference allowance, not a verified legal quota. The denominator is fixed across "
        "compared plans and values above one are not clamped. Zero-reference fields are excluded and listed.",
    },
    {
        "id": "method:field-coupling",
        "title": "How fields affect each other",
        "section": "PRD 6.1",
        "body": "Roster windows are exclusive in time, so one field taking its turn does not reduce another field's "
        "turn. Downstream consequences arise through reach delivery factors, shared repairs that change them, "
        "shared pumps and their caps, shared source and edge capacity, and the capital and operating budgets.",
    },
    {
        "id": "method:water-accounting",
        "title": "Water accounting boundaries",
        "section": "PRD 8.4, T7.5",
        "body": "Source withdrawal, conveyance loss, outlet receipt, pond fill, release, evaporation, seepage, rain "
        "and spill, groundwater abstraction and field application are reported separately from the "
        "chronological original-precision ledger. Withdrawal reductions are not consumptive water savings; "
        "basin-wide savings are not estimated. Terminal pond inventory is reported, not given a salvage value.",
    },
    {
        "id": "method:productivity",
        "title": "Withdrawal productivity",
        "section": "T7.5",
        "body": "Withdrawal productivity is modeled production in kg divided by canal source withdrawal plus "
        "groundwater abstraction in m3. With zero withdrawal it is not applicable rather than infinite.",
    },
    {
        "id": "method:sdg-proxies",
        "title": "SDG alignment proxies",
        "section": "PRD 8.5",
        "body": "SDG 2.4, 6.4/6.5 and 13.1 cards show computed project proxies: crop-specific production retained "
        "across tested scenarios, kg per m3 of defined withdrawal, groundwater change, entitlement fulfillment, "
        "and worst tested scenario outcome. They are not official UN indicator values (official_indicator=false), "
        "there is no 0-100 score, and no CO2 figure without cited energy and emission factors.",
    },
    {
        "id": "method:stress",
        "title": "Stress tests and recovery plans",
        "section": "T7.2",
        "body": "A fixed-plan stress test freezes investments and dated field policies and re-checks deliverability "
        "in each of the nine weather x supply states. An undeliverable cell has no achievable production. "
        "A recovery plan holds investments fixed and re-optimizes operations for one state; it is a conditional "
        "comparison, not a prospective plan. Worst case means worst within the tested states, not a probability.",
    },
    {
        "id": "method:why-not",
        "title": "Forced and excluded alternatives",
        "section": "T7.3",
        "body": "Why-not analysis solves a child scenario that forces or excludes one intervention instance and "
        "compares identical metric definitions. With incumbents and bounds [L1,U1] and [L2,U2] the supported "
        "difference interval is [L1-U2, U1-L2]; an exact difference is reported only when both are proven.",
    },
    {
        "id": "method:synergy",
        "title": "Synergy of two actions",
        "section": "T7.4",
        "body": "Synergy solves none, A only, B only and both under matched conditions with one declared rule for "
        "other investments, and reports outcome_AB - outcome_A - outcome_B + outcome_none. Positive, zero and "
        "negative synergy are valid; infeasible or unresolved combinations are reported as limitations.",
    },
    {
        "id": "method:frontier",
        "title": "Resilience frontier",
        "section": "T7.1",
        "body": "Each frontier point is an independently solved child scenario at an explicit capital budget and "
        "service floor. Nondominance is computed among evaluated feasible points only; unknown and infeasible "
        "settings are shown separately and no curve is interpolated through them.",
    },
    {
        "id": "method:commissioning",
        "title": "Commissioning and lead time",
        "section": "T4.6",
        "body": "A proposed asset is available only after decision date plus procurement delay plus lead time. "
        "Ponds and leveling must be commissioned before planting in v2; repairs may carry dated downtime. "
        "An instance with missing cost is unavailable rather than free.",
    },
    {
        "id": "method:crop-model",
        "title": "Crop model outputs",
        "section": "T5.3",
        "body": "Yields are AquaCrop-OSPy 3.1.0 simulations on dated gross irrigation schedules with configured "
        "soil archetypes and historical gridded weather. They are model output, uncalibrated unless stated, "
        "not measured harvests. Leveling changes application efficiency in the model, not a fixed yield bonus.",
    },
    {
        "id": "method:surrogate",
        "title": "Surrogate previews",
        "section": "T8.4",
        "body": "A surrogate preview is an approximate LightGBM yield estimate for an in-domain proposed schedule. "
        "Out-of-domain inputs are refused. A preview never becomes part of a recommended plan until the exact "
        "crop model and physical ledger confirm it.",
    },
]
