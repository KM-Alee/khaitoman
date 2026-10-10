"""navigate_view: a typed UI intent, applied by the client after the turn (T11.2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from aabflow.copilot.registry import ToolArgs, tool
from aabflow.copilot.tools.backend import ToolFailure
from aabflow.copilot.tools.base import ToolCtx

Tab = Literal[
    "workspace", "compare", "explore", "impact", "onboarding", "evidence", "replay", "report"
]


class NavigateArgs(ToolArgs):
    target: Literal[
        "pilot", "field", "run", "branch", "tab", "date", "report", "analysis", "comparison"
    ]
    ref_id: str | None = Field(
        None, description="ID of the pilot/field/run/revision/report/analysis/comparison"
    )
    tab: Tab | None = None
    date: str | None = Field(None, description="YYYY-MM-DD for the timeline")


@tool("navigate_view", args=NavigateArgs, semantics="view", activity="Preparing the view")
async def navigate_view(ctx: ToolCtx, args: NavigateArgs) -> dict[str, Any]:
    """Ask the UI to open a permitted pilot, field, run, branch, tab, date, report, analysis or comparison.
    The intent is applied after this turn; it does not retarget tools that are already running, and a pilot
    switch takes effect for the next question."""
    intent: dict[str, Any] = {"target": args.target}
    c = ctx.context
    if args.target == "pilot":
        if args.ref_id not in {p["pilot_id"] for p in c.permitted_pilots}:
            raise ToolFailure(
                "NOT_PERMITTED", f"pilot {args.ref_id!r} is not in the permitted pilot catalog"
            )
        intent["pilot_id"] = args.ref_id
    elif args.target == "field":
        fid = ctx.default_field(args.ref_id)
        await ctx.field_in_pilot(fid)
        intent["field_id"] = fid
    elif args.target == "run":
        rid = ctx.default_run(args.ref_id)
        await ctx.run_in_pilot(rid)
        intent["run_id"] = rid
    elif args.target == "branch":
        if not args.ref_id:
            raise ToolFailure("INVALID_INPUT", "branch needs a scenario revision ID")
        await ctx.revision_in_pilot(args.ref_id)
        intent["scenario_revision_id"] = args.ref_id
    elif args.target == "tab":
        if not args.tab:
            raise ToolFailure("INVALID_INPUT", "tab target needs a tab")
        intent["tab"] = args.tab
    elif args.target == "date":
        from datetime import date

        try:
            intent["date"] = date.fromisoformat(args.date or "").isoformat()
        except ValueError as exc:
            raise ToolFailure("INVALID_INPUT", "date must be YYYY-MM-DD") from exc
    else:  # report / analysis / comparison: must be known to this conversation or the current pilot
        if not args.ref_id:
            raise ToolFailure("INVALID_INPUT", f"{args.target} needs an ID")
        if args.ref_id not in ctx.session_ids:
            path = {"report": "/reports/", "analysis": "/analyses/", "comparison": "/comparisons/"}[
                args.target
            ]
            obj = await ctx.backend.get(path + args.ref_id)
            run_ids = obj.get("run_ids") or obj.get("child_run_ids") or []
            for rid in run_ids[:4]:
                await ctx.run_in_pilot(rid)
        intent[f"{args.target}_id"] = args.ref_id
    if args.tab and "tab" not in intent:
        intent["tab"] = args.tab
    ctx.view_intents.append(intent)
    return {"ok": True, "intent": intent, "applies": "after this turn completes"}
