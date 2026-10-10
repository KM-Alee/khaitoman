"""Bounded provider/tool loop for one copilot turn (T11.4).

receive message + pinned context -> provider -> validate and dispatch completed
function calls (reads concurrently, mutations one at a time) -> function outputs by
call_id -> ... -> validated final answer with server-rendered cards and visuals.

Limits per turn: 8 model rounds, 12 tool calls, 3 new analytical jobs, 90 s wall
time. Provider failures end the turn with a typed error and no invented result.
Cancellation stops the loop, cancels jobs this turn started and discards its view
intents. Progress is published as events (see ``contract.EventType``) for SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from aabflow.copilot import store
from aabflow.copilot.answer_validation import (
    FINAL_ANSWER_TOOL,
    AnswerBlock,
    Facts,
    FinalAnswer,
    apply_fallback,
    order_blocks,
    validate_answer,
)
from aabflow.copilot.context import PinnedContext, detect_language, workspace_digest
from aabflow.copilot.contract import CopilotAnswer
from aabflow.copilot.prompts import PROMPT_VERSION, build_instructions
from aabflow.copilot.provider import Provider, ProviderError
from aabflow.copilot.registry import REGISTRY, openai_tools, tool_schema_version
from aabflow.copilot.tools.backend import Backend, ToolFailure
from aabflow.copilot.tools.base import CURRENT_CALL, TERMINAL_JOB_STATES, ToolCtx, TurnBudget
from aabflow.copilot.visuals import Dataset, default_visual
from aabflow.domain.hashes import content_hash

log = logging.getLogger("aabflow.copilot")

# A final answer with visuals takes the hosted model ~15-25 s; start it with this much time left.
FINAL_RESERVE_S = 28.0


@dataclass(frozen=True)
class TurnLimits:
    max_rounds: int = 8
    max_tool_calls: int = 12
    max_jobs: int = 3
    wall_s: float = 90.0


@dataclass
class TurnResult:
    turn_id: str
    status: str
    answer: dict[str, Any] | None
    view_intents: list[dict[str, Any]]
    created: list[dict[str, Any]]
    job_ids: list[str]
    error: dict[str, Any] | None
    rounds: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    latency_ms: int = 0
    timings: dict[str, Any] = field(default_factory=dict)


ACTION_FOR = {
    "branch": "open_branch",
    "run": "open_run",
    "report": "open_report",
    "analysis": "open_analysis",
    "comparison": "open_comparison",
}

THINKING = {
    1: "Reading your question and planning",
    2: "Looking at the results",
}


def _compact(o: Any, max_list: int | None = None) -> Any:
    if isinstance(o, float):
        return float(f"{o:.6g}")
    if isinstance(o, dict):
        return {k: _compact(v, max_list) for k, v in o.items()}
    if isinstance(o, list):
        items = [_compact(v, max_list) for v in (o if max_list is None else o[:max_list])]
        if max_list is not None and len(o) > max_list:
            items.append({"omitted_items": len(o) - max_list})
        return items
    return o


def _fit(result: dict[str, Any], limit: int) -> str:
    """Serialize within the tool's size limit, trimming long lists structurally (never mid-JSON).

    Dataset descriptors are kept intact so the model can always reference them."""
    ds = result.get("datasets") if isinstance(result, dict) else None
    for max_list in (None, 24, 12, 6, 3, 1):
        body = _compact(result, max_list)
        if ds is not None:
            body["datasets"] = ds
        s = json.dumps(body, default=str, ensure_ascii=False)
        if len(s) <= limit:
            return s
    return json.dumps(
        {
            "ok": result.get("ok", True),
            "truncated": True,
            "datasets": ds or [],
            "note": "result too large for this tool; ask a narrower question",
        },
        default=str,
    )


def memory_from(turns: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    mem = []
    for t in turns[-limit:]:
        ans = t.get("answer") or {}
        text = " ".join(
            b.get("text", "")
            for b in ans.get("blocks", [])
            if b.get("type") in ("headline", "text")
        )[:400]
        refs = [c["ref_id"] for c in t.get("created_refs") or []]
        mem.append(
            {
                "user": t["user_message"][:300],
                "assistant": text,
                "status": t["status"],
                "created": refs[:6],
                "pilot_id": (t.get("context") or {}).get("pilot_id"),
            }
        )
    return mem


class Turn:
    def __init__(
        self,
        *,
        provider: Provider,
        backend: Backend,
        connect: Callable[[], Any],
        session_id: str,
        turn_id: str,
        message: str,
        context: PinnedContext,
        cancel: asyncio.Event | None = None,
        limits: TurnLimits | None = None,
        memory: list[dict[str, Any]] | None = None,
        known_ids: set[str] | None = None,
        idem_namespace: str | None = None,
    ):
        self.provider = provider
        self.backend = backend
        self.connect = connect
        self.session_id = session_id
        self.turn_id = turn_id
        self.message = message
        self.context = context
        self.cancel = cancel or asyncio.Event()
        self.limits = limits or TurnLimits()
        self.memory = memory or []
        self.known_ids = known_ids or set()
        self.idem_namespace = idem_namespace
        self.conn = connect()
        store.ensure(self.conn)
        self._seen_calls: dict[str, dict[str, Any]] = {}
        self.timings: dict[str, Any] = {"provider_calls": [], "tools": []}
        self._t0 = time.monotonic()

    def emit(self, type_: str, payload: dict[str, Any]) -> None:
        store.append_event(self.conn, self.turn_id, type_, payload)

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    async def run(self) -> TurnResult:
        self._t0 = t0 = time.monotonic()
        lang, lang_note = detect_language(self.message, self.context.language)
        if lang != self.context.language:
            self.context = self.context.model_copy(update={"language": lang})
        ctx = self.context
        store.create_turn(
            self.conn,
            self.turn_id,
            self.session_id,
            self.message,
            ctx.model_dump(mode="json"),
            getattr(self.provider, "model", "unknown"),
            PROMPT_VERSION,
            tool_schema_version(),
            self.idem_namespace,
        )
        self.emit(
            "turn_started",
            {
                "turn_id": self.turn_id,
                "context": ctx.prompt_view(),
                "language": ctx.language,
                "badge": {
                    "pilot_id": ctx.pilot_id,
                    "pilot_version": ctx.pilot_version,
                    "run_id": ctx.selected_run_id,
                    "plan_kind": ctx.selected_run_plan_kind,
                    "season_id": ctx.season_id,
                },
            },
        )
        facts = Facts()
        for k in (
            "pilot_id",
            "scenario_revision_id",
            "selected_run_id",
            "selected_field_id",
            "scenario_id",
        ):
            v = getattr(ctx, k)
            if v:
                facts.add_id(v, k.replace("selected_", "").removesuffix("_id"))
        facts.add_text_numbers(self.message)
        tctx = ToolCtx(
            backend=self.backend,
            context=ctx,
            turn_id=self.turn_id,
            session_id=self.session_id,
            budget=TurnBudget(max_jobs=self.limits.max_jobs),
            deadline=time.monotonic() + self.limits.wall_s,
            session_ids=set(self.known_ids),
            cancel=self.cancel,
            idem_namespace=self.idem_namespace,
        )

        def on_dataset(ds: Dataset) -> None:
            ref = (ds.source.run_ids or ds.source.analysis_ids or [None])[0]
            facts.add(ds.rows, ref)
            for rid in ds.source.run_ids:
                facts.add_id(rid, "run")
            for aid in ds.source.analysis_ids:
                facts.add_id(aid, "analysis")
            for cid in ds.source.comparison_ids:
                facts.add_id(cid, "comparison")
            self.emit(
                "dataset_ready",
                {
                    "dataset_id": ds.dataset_id,
                    "kind": ds.kind,
                    "title": ds.title,
                    "rows": len(ds.rows),
                    "charts": ds.charts,
                    "call_id": ds.source.call_id,
                    "tool": ds.source.tool,
                },
            )

        tctx.datasets.on_add = on_dataset
        self.tctx = tctx
        tools = openai_tools(ctx.role, [FINAL_ANSWER_TOOL])
        digest = await workspace_digest(self.backend, ctx)
        notes = list(ctx.notes) + ([lang_note] if lang_note else [])
        instructions = build_instructions(ctx.prompt_view(), self.memory, notes, digest)
        items: list[dict[str, Any]] = [{"role": "user", "content": self.message}]
        prev: str | None = None
        rounds = calls_made = 0
        regen_used = False
        final: dict[str, Any] | None = None
        status = "completed"
        error: dict[str, Any] | None = None
        request_ids: list[str] = []
        while rounds < self.limits.max_rounds:
            if self.cancel.is_set():
                status = "cancelled"
                break
            remaining = tctx.remaining_s()
            if remaining < 4:
                status = "budget_exhausted"
                break
            force_final = rounds == self.limits.max_rounds - 1 or (
                rounds > 0 and remaining < FINAL_RESERVE_S
            )
            choice: Any = {"type": "function", "name": "final_answer"} if force_final else "auto"
            self.emit(
                "thinking",
                {
                    "round": rounds + 1,
                    "label": "Writing the answer"
                    if force_final
                    else THINKING.get(rounds + 1, "Checking the results"),
                    "elapsed_ms": self._elapsed_ms(),
                    "remaining_s": round(remaining, 1),
                },
            )
            t_call = time.monotonic()
            try:
                resp = await self._respond(instructions, items, tools, prev, choice, remaining)
            except asyncio.CancelledError:
                status = "cancelled"
                break
            except ProviderError as exc:
                status = "provider_unavailable"
                error = {"code": exc.code, "detail": exc.detail, "retryable": exc.retryable}
                self.emit("error", error)
                break
            except TimeoutError:
                status = "budget_exhausted"
                error = {"code": "TURN_TIMEOUT", "detail": "the turn reached its time budget"}
                break
            rounds += 1
            self.timings["provider_calls"].append(
                {
                    "round": rounds,
                    "latency_ms": int((time.monotonic() - t_call) * 1000),
                    "calls": [c.name for c in resp.calls],
                    "usage": resp.usage,
                    "forced_final": bool(force_final),
                }
            )
            prev = resp.response_id
            request_ids.append(resp.response_id)
            if self.cancel.is_set():
                status = "cancelled"
                break
            if not resp.calls:
                ans = FinalAnswer(
                    language=ctx.language,
                    headline=None,
                    needs_clarification=False,
                    blocks=[AnswerBlock(type="text", text=resp.text or "")],
                )
                final = await self._finalize(ans, facts, tctx, last_try=True)
                break
            outputs: list[dict[str, Any]] = []
            work = [c for c in resp.calls if c.name != "final_answer"]
            finals = [c for c in resp.calls if c.name == "final_answer"]
            if work:
                results = await self._dispatch(work, tctx, facts, rounds, calls_made)
                calls_made += len(work)
                outputs += results
                for c in finals:
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": c.call_id,
                            "output": json.dumps(
                                {
                                    "accepted": False,
                                    "reason": "final_answer must come after you have read the tool results",
                                }
                            ),
                        }
                    )
            elif finals:
                c = finals[0]
                try:
                    ans = FinalAnswer.model_validate(c.parsed())
                except (ValidationError, ValueError) as exc:
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": c.call_id,
                            "output": json.dumps(
                                {"accepted": False, "reason": f"invalid answer: {exc}"[:800]}
                            ),
                        }
                    )
                    items = outputs
                    continue
                last_try = (
                    regen_used
                    or tctx.remaining_s() < FINAL_RESERVE_S
                    or rounds >= self.limits.max_rounds - 1
                )
                v_or_final = await self._finalize(ans, facts, tctx, last_try=last_try)
                if isinstance(v_or_final, dict):
                    final = v_or_final
                    break
                regen_used = True
                self.emit(
                    "thinking",
                    {
                        "round": rounds + 1,
                        "label": "Double-checking the numbers",
                        "elapsed_ms": self._elapsed_ms(),
                        "problems": len(v_or_final),
                    },
                )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": c.call_id,
                        "output": json.dumps(
                            {
                                "accepted": False,
                                "problems": v_or_final,
                                "instruction": "Call final_answer again: quote only numbers present in tool results "
                                "(or use metric/comparison blocks and visuals), cite only returned IDs and use "
                                "only dataset_ids and chart kinds the tools returned.",
                            }
                        ),
                    }
                )
                for extra in finals[1:]:
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": extra.call_id,
                            "output": json.dumps(
                                {"accepted": False, "reason": "duplicate final_answer"}
                            ),
                        }
                    )
            items = outputs
        else:
            status = "budget_exhausted"
        if status == "cancelled":
            await self._cancel_jobs(tctx)
            final = None
            tctx.view_intents.clear()
        elif final is None:
            final = await self._fallback_answer(tctx, status, error)
        if final is not None:
            if final.get("needs_clarification") and status == "completed":
                status = "clarification"
            for i, b in enumerate(final["blocks"]):
                self.emit("answer_block", {"index": i, "block": b})
            self.emit("answer", final)
        pending = []
        if status != "cancelled":
            if tctx.view_intents:
                self.emit("view_intents", {"intents": tctx.view_intents})
            pending = await self._pending_jobs(tctx)
        latency = int((time.monotonic() - t0) * 1000)
        self.timings["total_ms"] = latency
        self.timings["provider_ms"] = sum(p["latency_ms"] for p in self.timings["provider_calls"])
        self.timings["tool_ms"] = sum(t["ms"] for t in self.timings["tools"])
        store.finish_turn(
            self.conn,
            self.turn_id,
            status=status,
            answer=final,
            view_intents=tctx.view_intents,
            created=tctx.created,
            job_ids=tctx.job_ids,
            error=error,
            request_ids=request_ids,
            rounds=rounds,
            latency_ms=latency,
            timings=self.timings,
            language=ctx.language,
        )
        self.emit(
            "turn_finished",
            {
                "status": status,
                "rounds": rounds,
                "tool_calls": calls_made,
                "latency_ms": latency,
                "provider_ms": self.timings["provider_ms"],
                "pending_job_ids": pending,
                "error": error,
            },
        )
        result = TurnResult(
            self.turn_id,
            status,
            final,
            tctx.view_intents,
            tctx.created,
            tctx.job_ids,
            error,
            rounds,
            store.tool_calls(self.conn, self.turn_id),
            request_ids,
            latency,
            self.timings,
        )
        self.pending_jobs = pending
        return result

    async def _respond(self, instructions, items, tools, prev, choice, remaining):
        task = asyncio.ensure_future(
            self.provider.respond(
                instructions=instructions,
                input_items=items,
                tools=tools,
                previous_response_id=prev,
                tool_choice=choice,
            )
        )
        stop = asyncio.ensure_future(self.cancel.wait())
        done, _ = await asyncio.wait(
            {task, stop}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            stop.cancel()
            return task.result()
        task.cancel()
        stop.cancel()
        if self.cancel.is_set():
            raise asyncio.CancelledError
        raise TimeoutError

    async def _dispatch(
        self, calls, tctx: ToolCtx, facts: Facts, rnd: int, already: int
    ) -> list[dict[str, Any]]:
        outputs: dict[str, str] = {}
        reads, muts = [], []
        for i, c in enumerate(calls):
            if already + i >= self.limits.max_tool_calls:
                outputs[c.call_id] = json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "TURN_TOOL_LIMIT",
                            "detail": "tool call limit reached for this turn; answer now",
                        },
                    }
                )
                continue
            spec = REGISTRY.get(c.name)
            (muts if spec is not None and spec.mutation else reads).append(c)

        async def one(c):
            outputs[c.call_id] = await self._call(c, tctx, facts, rnd)

        await asyncio.gather(*(one(c) for c in reads))
        for c in muts:  # one mutation at a time, in the model's order
            if self.cancel.is_set():
                outputs[c.call_id] = json.dumps(
                    {"ok": False, "error": {"code": "CANCELLED", "detail": "turn cancelled"}}
                )
                continue
            await one(c)
        return [
            {"type": "function_call_output", "call_id": c.call_id, "output": outputs[c.call_id]}
            for c in calls
        ]

    def _reject(self, c, rnd: int, raw: Any, code: str, detail: str) -> str:
        out = {"ok": False, "error": {"code": code, "detail": detail}}
        pk = store.start_call(self.conn, self.turn_id, c.call_id, rnd, c.name, raw, None)
        store.finish_call(self.conn, pk, "rejected", out)
        self.emit(
            "tool_finished",
            {
                "call_id": c.call_id,
                "tool": c.name,
                "ok": False,
                "error": out["error"],
                "activity": "Rejected tool call",
                "duration_ms": 0,
            },
        )
        return json.dumps(out)

    async def _call(self, c, tctx: ToolCtx, facts: Facts, rnd: int) -> str:
        spec = REGISTRY.get(c.name)
        try:
            raw = c.parsed()
        except ValueError:
            return self._reject(c, rnd, c.arguments, "INVALID_ARGUMENTS", "arguments are not JSON")
        if spec is None:
            return self._reject(c, rnd, raw, "UNKNOWN_TOOL", f"no tool {c.name}")
        if tctx.context.role not in spec.roles:
            return self._reject(
                c, rnd, raw, "NOT_PERMITTED", f"role {tctx.context.role} cannot use {c.name}"
            )
        try:
            args = spec.args.model_validate(raw)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
            return self._reject(c, rnd, raw, "INVALID_ARGUMENTS", msg)
        canon = args.model_dump(mode="json")
        dedupe = content_hash({"tool": c.name, "args": canon})
        idem = tctx.idem(c.name, canon) if spec.mutation else None
        activity = spec.activity_for(canon)
        if (
            dedupe in self._seen_calls
        ):  # provider retry of an identical call: reuse, never repeat a mutation
            result = self._seen_calls[dedupe]
            self.emit(
                "tool_finished",
                {
                    "call_id": c.call_id,
                    "tool": c.name,
                    "ok": result.get("ok", True),
                    "reused": True,
                    "activity": activity,
                    "duration_ms": 0,
                },
            )
            return _fit(result, spec.max_result_chars)
        pk = store.start_call(self.conn, self.turn_id, c.call_id, rnd, c.name, canon, idem)
        self.emit(
            "tool_started",
            {
                "call_id": c.call_id,
                "tool": c.name,
                "activity": activity,
                "semantics": spec.semantics,
                "round": rnd,
            },
        )
        status = "succeeded"
        t_tool = time.monotonic()
        token = CURRENT_CALL.set((c.call_id, c.name))
        try:
            result = await asyncio.wait_for(
                spec.handler(tctx, args), timeout=min(spec.timeout_s, max(5.0, tctx.remaining_s()))
            )
            result.setdefault("ok", True)
        except ToolFailure as exc:
            result = exc.as_output()
            status = "failed"
        except TimeoutError:
            result = {
                "ok": False,
                "error": {
                    "code": "TOOL_TIMEOUT",
                    "detail": f"{c.name} exceeded its time limit; any job it started keeps running",
                },
            }
            status = "failed"
        except Exception as exc:
            log.exception("copilot tool %s failed", c.name)
            result = {
                "ok": False,
                "error": {
                    "code": "TOOL_ERROR",
                    "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                },
            }
            status = "failed"
        finally:
            CURRENT_CALL.reset(token)
        ms = int((time.monotonic() - t_tool) * 1000)
        self.timings["tools"].append(
            {"tool": c.name, "call_id": c.call_id, "round": rnd, "ms": ms, "status": status}
        )
        facts.add(result)
        self._seen_calls[dedupe] = result
        store.finish_call(self.conn, pk, status, result)
        self.emit(
            "tool_finished",
            {
                "call_id": c.call_id,
                "tool": c.name,
                "ok": result.get("ok", False),
                "activity": activity,
                "error": result.get("error"),
                "duration_ms": ms,
                "datasets": [d.get("dataset_id") for d in result.get("datasets") or []],
                "job_ids": list(tctx.job_ids),
                "created": list(tctx.created),
            },
        )
        return _fit(result, spec.max_result_chars)

    async def _finalize(self, ans: FinalAnswer, facts: Facts, tctx: ToolCtx, *, last_try: bool):
        v = await validate_answer(ans, facts, tctx)
        if not v.ok and not last_try:
            return list(v.issues) + [
                f"{where}: unsupported numbers {bad}" for where, bad in v.numeric_issues
            ]
        blocks = v.blocks
        extra: list[dict[str, Any]] = []
        if not v.ok:
            blocks = apply_fallback(v, ans.language)
            if v.issues:
                extra.append(
                    {
                        "type": "uncertainty",
                        "citations": [],
                        "text": "Some references or charts in the draft answer could not be verified against "
                        "this turn's tool results and were left out.",
                    }
                )
        language = ans.language
        out = {
            "language": language,
            "blocks": order_blocks(
                badges=await self._badges(tctx),
                headline=v.headline,
                blocks=blocks + extra + self._created_actions(blocks, tctx),
                visuals=v.visuals,
                follow_ups=v.follow_ups,
            ),
            "needs_clarification": ans.needs_clarification,
            "clarification_question": ans.clarification_question
            if ans.needs_clarification
            else None,
            "validated": v.ok,
            "issues": v.issues + [f"{w}: unsupported numbers {b}" for w, b in v.numeric_issues],
        }
        return self._checked(out)

    def _checked(self, out: dict[str, Any]) -> dict[str, Any]:
        """Every answer leaves through the public contract model (drops nothing silently)."""
        return CopilotAnswer.model_validate(out).model_dump(mode="json")

    async def _badges(self, tctx: ToolCtx) -> list[dict[str, Any]]:
        c = self.context
        wanted: list[tuple[str, str]] = []
        if c.selected_run_id:
            wanted.append(("context", c.selected_run_id))
        for x in tctx.created:
            if x["kind"] == "run":
                wanted.append(("created", x["ref_id"]))
        out = []
        for role, rid in wanted:
            try:
                view = await tctx.run_in_pilot(rid)
            except ToolFailure:
                continue
            run = view["run"]
            out.append(
                {
                    "type": "run_badge",
                    "role": role,
                    "run_id": rid,
                    "plan_kind": run.get("plan_kind"),
                    "solver_status": run.get("solver_status"),
                    "outcome": run.get("outcome"),
                    "scenario_revision_id": run.get("scenario_revision_id"),
                    "pilot_id": c.pilot_id,
                    "pilot_version": c.pilot_version,
                    "season_id": (view.get("meta") or {}).get("season_id"),
                    "label": view.get("label"),
                }
            )
        return out

    @staticmethod
    def _created_actions(blocks: list[dict[str, Any]], tctx: ToolCtx) -> list[dict[str, Any]]:
        have = {b.get("ref_id") for b in blocks if b["type"] == "action"}
        return [
            {
                "type": "action",
                "action": ACTION_FOR[c["kind"]],
                "ref_id": c["ref_id"],
                "label": c["label"],
                "auto": True,
            }
            for c in tctx.created
            if c["ref_id"] not in have and c["kind"] in ACTION_FOR
        ]

    async def _fallback_answer(
        self, tctx: ToolCtx, status: str, error: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Server-written, honest answer when the model could not finish: no invented text or numbers.

        Results the tools already produced are shown as plain (unexplained) visuals and links."""
        msg = {
            "provider_unavailable": "The hosted assistant is unavailable right now, so this answer is incomplete. "
            "No result was invented; saved results, controls and evidence still work.",
            "budget_exhausted": "I reached this turn's time or step limit before I could finish the explanation.",
        }.get(status, "I could not finish this answer.")
        blocks: list[dict[str, Any]] = [{"type": "uncertainty", "text": msg, "citations": []}]
        visuals = []
        for ds in list(tctx.datasets.items.values())[:2]:
            vb = default_visual(ds, f"v{len(visuals) + 1}")
            if vb is not None:
                visuals.append(vb.model_dump(mode="json"))
        if visuals:
            blocks.append(
                {
                    "type": "uncertainty",
                    "text": "The charts below show results the tools already returned in this turn, without an "
                    "explanation.",
                    "citations": [],
                }
            )
        out = {
            "language": self.context.language,
            "blocks": order_blocks(
                badges=await self._badges(tctx),
                headline=None,
                blocks=blocks + self._created_actions([], tctx),
                visuals=visuals,
                follow_ups=[],
            ),
            "needs_clarification": False,
            "clarification_question": None,
            "validated": True,
            "issues": [],
            "deterministic": True,
        }
        return self._checked(out)

    async def _pending_jobs(self, tctx: ToolCtx) -> list[str]:
        pending = []
        for jid in tctx.job_ids:
            try:
                j = await self.backend.get(f"/jobs/{jid}")
            except ToolFailure:
                continue
            if j["state"] not in TERMINAL_JOB_STATES:
                pending.append(jid)
        return pending

    async def _cancel_jobs(self, tctx: ToolCtx) -> None:
        for jid in tctx.job_ids:
            try:
                await self.backend.post(f"/jobs/{jid}/cancel")
            except ToolFailure:
                log.debug("cancel of %s failed", jid)
        self.emit("jobs_cancelled", {"job_ids": list(tctx.job_ids)})

    async def follow_jobs(self, max_wait_s: float = 900.0) -> None:
        """After the turn: follow running jobs to completion and publish their results as events."""
        from aabflow.copilot.tools.read import describe_job

        pending = list(getattr(self, "pending_jobs", []))
        t0 = time.monotonic()
        while pending and time.monotonic() - t0 < max_wait_s and not self.cancel.is_set():
            await asyncio.sleep(1.0)
            for jid in list(pending):
                try:
                    j = await self.backend.get(f"/jobs/{jid}")
                except ToolFailure:
                    pending.remove(jid)
                    continue
                if j["state"] in TERMINAL_JOB_STATES:
                    pending.remove(jid)
                    try:
                        payload = await describe_job(self.tctx, j)
                    except ToolFailure as exc:
                        payload = {
                            "job_id": jid,
                            "state": j["state"],
                            "error": exc.as_output()["error"],
                        }
                    self.emit("job_update", payload)
        self.emit("jobs_settled", {"pending_job_ids": pending})

    def close(self) -> None:
        self.conn.close()
