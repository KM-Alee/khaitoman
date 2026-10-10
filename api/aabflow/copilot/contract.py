"""Public copilot contract for the UI: answer blocks, turn views and SSE events.

These Pydantic models are the executable contract (exported through OpenAPI and the
generated TypeScript types). ``docs/COPILOT.md`` explains how the UI renders them.
Every quantitative block carries the run/analysis/comparison IDs and units of the
service result it was copied from.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aabflow.copilot.visuals import VisualBlock

Language = Literal["en", "ur", "roman_ur"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(_Out):
    ref_id: str
    kind: str = Field(
        description="run, comparison, analysis, evidence, scenario_revision, field, ..."
    )
    auto: bool = Field(False, description="Added by the server because the text quotes its numbers")


class HeadlineBlock(_Out):
    type: Literal["headline"] = "headline"
    text: str
    citations: list[Citation] = Field(default_factory=list)
    withheld: bool = False


class TextBlock(_Out):
    type: Literal["text"] = "text"
    text: str
    citations: list[Citation] = Field(default_factory=list)
    withheld: bool = Field(False, description="A sentence with an unsupported figure was removed")


class UncertaintyBlock(_Out):
    """Caveat / limitation / running-job / unavailable notice (always shown, never collapsed away)."""

    type: Literal["uncertainty"] = "uncertainty"
    text: str
    citations: list[Citation] = Field(default_factory=list)
    withheld: bool = False


class MetricBlock(_Out):
    """One metric card; value resolved server-side from the run's stored metrics."""

    type: Literal["metric"] = "metric"
    metric_id: str
    definition_id: str | None = None
    label: str | None = None
    run_id: str
    field_id: str | None = None
    value: float | None = None
    unit: str | None = None
    status: str | None = None
    reason: str | None = None
    basis: str
    plan_kind: str | None = None
    solver_status: str | None = None


class Delta(_Out):
    metric_id: str
    unit: str | None = None
    a: float | None = None
    b: float | None = None
    delta: float | None = None
    status: str | None = None


class ComparisonBlock(_Out):
    type: Literal["comparison"] = "comparison"
    comparison_id: str
    run_ids: list[str]
    compatible: bool
    label: str
    deltas: list[Delta]
    fields_worse_off: list[Any] = Field(default_factory=list)


ActionKind = Literal[
    "open_run",
    "open_branch",
    "open_field",
    "open_report",
    "open_analysis",
    "open_comparison",
]


class ActionBlock(_Out):
    """A button: selecting it updates the existing workspace (never operates anything physical)."""

    type: Literal["action"] = "action"
    action: ActionKind
    ref_id: str
    label: str
    auto: bool = Field(False, description="Added by the server for an object created this turn")


class FollowUpsBlock(_Out):
    type: Literal["follow_ups"] = "follow_ups"
    questions: list[str]


class RunBadgeBlock(_Out):
    """Identity of a run the answer is about (AT13: same run IDs as UI and report)."""

    type: Literal["run_badge"] = "run_badge"
    role: Literal["context", "created"]
    run_id: str
    plan_kind: str | None = None
    solver_status: str | None = None
    outcome: str | None = None
    scenario_revision_id: str | None = None
    pilot_id: str
    pilot_version: str
    season_id: str | None = None
    label: str | None = None


AnswerBlockOut = Annotated[
    RunBadgeBlock
    | HeadlineBlock
    | TextBlock
    | MetricBlock
    | VisualBlock
    | ComparisonBlock
    | UncertaintyBlock
    | ActionBlock
    | FollowUpsBlock,
    Field(discriminator="type"),
]


class CopilotAnswer(_Out):
    """The validated answer of one turn, rendered top to bottom in block order."""

    language: Language
    blocks: list[AnswerBlockOut]
    needs_clarification: bool = False
    clarification_question: str | None = None
    validated: bool = Field(description="True when every reference and number passed validation")
    issues: list[str] = Field(default_factory=list)
    deterministic: bool = Field(
        False,
        description="Server-written (provider unavailable / budget exhausted); not a model answer",
    )


TurnStatus = Literal[
    "running",
    "completed",
    "clarification",
    "failed",
    "cancelled",
    "provider_unavailable",
    "budget_exhausted",
]


class CreatedRef(_Out):
    kind: Literal["branch", "run", "report", "analysis", "comparison"]
    ref_id: str
    label: str


class ViewIntent(_Out):
    """Typed UI intent from navigate_view, applied after the turn finishes."""

    model_config = ConfigDict(extra="allow")
    target: str


class TurnView(_Out):
    turn_id: str
    session_id: str
    seq: int
    status: TurnStatus
    user_message: str
    language: Language | None = None
    context: dict[str, Any]
    answer: CopilotAnswer | None = None
    view_intents: list[ViewIntent] = Field(default_factory=list)
    created_refs: list[CreatedRef] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    model: str | None = None
    prompt_version: str | None = None
    tool_schema_version: str | None = None
    request_ids: list[str] = Field(default_factory=list)
    rounds: int = 0
    latency_ms: int | None = None
    timings: dict[str, Any] | None = None
    idem_namespace: str | None = None
    created_at: str
    finished_at: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    events: list[dict[str, Any]] | None = None


class SessionSummary(_Out):
    session_id: str
    created_at: str
    role: str
    title: str | None = None
    turns: int
    last_turn_at: str | None = None


class SessionList(_Out):
    sessions: list[SessionSummary]


# ------------------------------------------------------------------ SSE events

EventType = Literal[
    "turn_started",
    "thinking",
    "tool_started",
    "tool_finished",
    "dataset_ready",
    "answer_block",
    "answer",
    "view_intents",
    "error",
    "turn_finished",
    "job_update",
    "jobs_settled",
    "jobs_cancelled",
]


class CopilotEvent(_Out):
    """One server-sent event (``id`` = event_id; resume with Last-Event-ID or ?after=)."""

    event_id: int
    turn_id: str
    created_at: str
    type: EventType
    payload: dict[str, Any]


class ContractExample(_Out):
    """Schema anchor so OpenAPI exports the answer, turn and event shapes."""

    answer: CopilotAnswer
    event: CopilotEvent
    turn: TurnView
