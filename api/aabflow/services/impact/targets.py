"""Official SDG target text for project proxies (PRD §8.5, T7.5).

The URLs are the goal pages cited in the tech doc. Target sentences are the UN
target definitions. None of these cards is an official indicator.
"""

from __future__ import annotations

GOAL_2 = "https://sdgs.un.org/goals/goal2"
GOAL_6 = "https://sdgs.un.org/goals/goal6"
GOAL_13 = "https://sdgs.un.org/goals/goal13"

TARGET_2_4 = (
    "By 2030, ensure sustainable food production systems and implement resilient "
    "agricultural practices that increase productivity and production, that help "
    "maintain ecosystems, that strengthen capacity for adaptation to climate change, "
    "extreme weather, drought, flooding and other disasters and that progressively "
    "improve land and soil quality."
)
TARGET_6_4 = (
    "By 2030, substantially increase water-use efficiency across all sectors and "
    "ensure sustainable withdrawals and supply of freshwater to address water scarcity "
    "and substantially reduce the number of people suffering from water scarcity."
)
TARGET_6_5 = (
    "By 2030, implement integrated water resources management at all levels, including "
    "through transboundary cooperation as appropriate."
)
TARGET_13_1 = (
    "Strengthen resilience and adaptive capacity to climate-related hazards and natural "
    "disasters in all countries."
)

NO_SCORE = "No arbitrary 0–100 SDG score is computed for this proxy."
NOT_A_REPORT = "This card is not a substitute for the action report."
CO2_LIMIT = "CO₂ is not_estimated and is not inferred from water saving."

CO2_REASON = (
    "CO₂ is not_estimated: the metric registry has no evidence-backed energy use, "
    "fuel/grid emission factor and system boundary, and CO₂ is not synthesized from "
    "water saving."
)
