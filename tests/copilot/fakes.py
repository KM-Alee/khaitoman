"""TEST FIXTURE: scripted stand-ins for the hosted model (labelled; tests only).

``ScriptedProvider`` replays a list of steps. Each step receives the function
outputs of the previous round (parsed JSON by call name) and returns either a list
of ``(tool_name, args)`` calls or a final answer dict. It lets tests drive the real
orchestrator, tools, routes, solver and validation deterministically.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

from aabflow.copilot.provider import FunctionCall, ProviderError, ProviderResponse

Step = Callable[[dict[str, Any]], list[tuple[str, dict[str, Any]]] | dict[str, Any] | Exception]

_ids = itertools.count(1)


def vis(dataset_id: str, chart: str, **kw: Any) -> dict[str, Any]:
    """A strict-mode visual spec (unspecified keys null)."""
    spec = {
        "dataset_id": dataset_id,
        "chart": chart,
        "title": kw.pop("title", "Chart"),
        "caption": None,
        "x": None,
        "y": None,
        "series": None,
        "sort": None,
        "limit": None,
        "highlight_ids": None,
    }
    spec.update(kw)
    return spec


def final(
    blocks: list[dict[str, Any]],
    language: str = "en",
    clarify: str | None = None,
    *,
    headline: str | None = None,
    visuals: list[dict[str, Any]] | None = None,
    follow_ups: list[str] | None = None,
) -> dict[str, Any]:
    full = []
    for b in blocks:
        base = {
            "type": "text",
            "text": None,
            "citations": None,
            "metric_id": None,
            "run_id": None,
            "field_id": None,
            "comparison_id": None,
            "action": None,
            "ref_id": None,
            "label": None,
        }
        base.update(b)
        full.append(base)
    return {
        "language": language,
        "headline": headline,
        "visuals": visuals or [],
        "follow_ups": follow_ups or [],
        "blocks": full,
        "needs_clarification": clarify is not None,
        "clarification_question": clarify,
    }


class Stall:
    """A step that never answers within ``seconds`` (simulates a stalled hosted call)."""

    def __init__(self, seconds: float):
        self.seconds = seconds


class ScriptedProvider:
    model = "scripted-test-provider"

    def __init__(self, steps: list[Step]):
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self._calls: dict[str, str] = {}

    async def respond(
        self, *, instructions, input_items, tools, previous_response_id, tool_choice="auto"
    ):
        self.requests.append(
            {
                "instructions": instructions,
                "input": input_items,
                "tools": [t["name"] for t in tools],
                "previous_response_id": previous_response_id,
                "tool_choice": tool_choice,
            }
        )
        outputs: dict[str, Any] = {}
        for it in input_items:
            if it.get("type") == "function_call_output":
                name = self._calls.get(it["call_id"], "?")
                outputs.setdefault(name, []).append(json.loads(it["output"]))
        if not self.steps:
            raise ProviderError("PROVIDER_ERROR", "script exhausted")
        step = self.steps.pop(0)
        if isinstance(step, Stall):
            import asyncio

            await asyncio.sleep(step.seconds)
            raise ProviderError("PROVIDER_TIMEOUT", "stalled step was not cancelled")
        res = step(outputs) if callable(step) else step
        if isinstance(res, Exception):
            raise res
        rid = f"resp_{next(_ids)}"
        if isinstance(res, dict):
            calls = [("final_answer", res)]
        else:
            calls = res
        fcs = []
        for name, args in calls:
            cid = f"call_{next(_ids)}"
            self._calls[cid] = name
            fcs.append(FunctionCall(call_id=cid, name=name, arguments=json.dumps(args)))
        return ProviderResponse(response_id=rid, calls=fcs, text="", latency_ms=1)


def nulls(**kw: Any) -> dict[str, Any]:
    """Strict-mode style argument dicts: unspecified keys explicitly null."""
    return kw
