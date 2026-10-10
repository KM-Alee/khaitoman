"""Copilot routes (T9.1): sessions, messages -> turns, resumable SSE turn events, cancel.

Include with ``api.include_router(aabflow.copilot.router.router)`` under /api/v2.
Turns run as asyncio tasks in the API process; tools call the same app in-process.
The provider is created per turn from the environment (or an injected factory in
tests and the evaluation harness).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from aabflow.api.errors import DomainError, not_found
from aabflow.api.state import AppState, get_state
from aabflow.copilot import store
from aabflow.copilot.context import UIContext, resolve
from aabflow.copilot.contract import CopilotEvent, PlanStep, SessionList, TurnMode, TurnView
from aabflow.copilot.orchestrator import PLAN_LIMITS, Turn, TurnLimits, memory_from
from aabflow.copilot.prompts import PROMPT_VERSION
from aabflow.copilot.provider import (
    ProviderError,
    configured_model,
    default_provider,
    key_configured,
)
from aabflow.copilot.registry import tool_schema_version
from aabflow.copilot.tools.backend import Backend, ToolFailure
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import ErrorCode, StrictModel

log = logging.getLogger("aabflow.copilot")
router = APIRouter(prefix="/copilot", tags=["copilot"])
State = Annotated[AppState, Depends(get_state)]

SSE_POLL_S = 0.25
SSE_KEEPALIVE_S = 10.0


class SessionCreate(StrictModel):
    contract_version: Literal["2.0.0"] = "2.0.0"
    context: UIContext = Field(default_factory=UIContext)
    role: Literal["planner", "viewer"] = "planner"


class SessionOut(StrictModel):
    session_id: str
    role: str
    status: dict[str, Any]


class MessageIn(StrictModel):
    contract_version: Literal["2.0.0"] = "2.0.0"
    message: str = Field(min_length=1, max_length=4000)
    context: UIContext
    mode: TurnMode = Field(
        "chat",
        description="chat = answer a question; plan = run a full 'Plan my season' investigation (bigger "
        "limits, the planner recipe and the brief layout check; emits plan_step events)",
    )


class TurnAccepted(StrictModel):
    turn_id: str
    session_id: str
    context: dict[str, Any]
    events_url: str


def _hub(state: AppState) -> dict[str, Any]:
    hub = state.extras.setdefault("copilot", {"turns": {}, "tasks": set(), "lock": asyncio.Lock()})
    return hub


def _conn(state: AppState):
    c = state.connect()
    store.ensure(c)
    return c


def status_view(state: AppState) -> dict[str, Any]:
    factory = state.extras.get("copilot_provider_factory")
    configured = factory is not None or key_configured()
    return {
        "configured": configured,
        "state": "ready" if configured else "unavailable",
        "reason": None
        if configured
        else "No hosted-model key is configured on the server, so the conversational copilot is unavailable.",
        "model": state.extras.get("copilot_model") or configured_model(),
        "prompt_version": PROMPT_VERSION,
        "tool_schema_version": tool_schema_version(),
        "offline_note": "Hosted chat needs internet and a configured key. Saved results, deterministic "
        "explanations and controls work offline; there is no offline generative assistant.",
    }


@router.get("/status")
def copilot_status(state: State) -> dict[str, Any]:
    return status_view(state)


@router.get("/sessions", response_model=SessionList)
def list_sessions(state: State, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> SessionList:
    """Recent conversations (restorable after a restart)."""
    c = _conn(state)
    try:
        return SessionList(sessions=store.list_sessions(c, limit))
    finally:
        c.close()


@router.post("/sessions", status_code=201, response_model=SessionOut)
def create_session(body: SessionCreate, state: State) -> SessionOut:
    sid = new_id("cps")
    c = _conn(state)
    try:
        store.create_session(c, sid, body.role, body.context.model_dump(mode="json"))
    finally:
        c.close()
    return SessionOut(session_id=sid, role=body.role, status=status_view(state))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, state: State) -> dict[str, Any]:
    c = _conn(state)
    try:
        row = store.get_session(c, session_id)
        if row is None:
            raise not_found("session_id", session_id)
        turns = [_reap(state, c, t) for t in store.session_turns(c, session_id)]
    finally:
        c.close()
    return {
        "session_id": session_id,
        "role": row["role"],
        "created_at": row["created_at"],
        "turns": [
            {
                k: t.get(k)
                for k in (
                    "turn_id",
                    "seq",
                    "mode",
                    "status",
                    "user_message",
                    "language",
                    "answer",
                    "view_intents",
                    "created_refs",
                    "job_ids",
                    "error",
                    "rounds",
                    "latency_ms",
                    "created_at",
                    "finished_at",
                )
            }
            for t in turns
        ],
    }


def _reap(state: AppState, conn, t: dict[str, Any]) -> dict[str, Any]:
    """A turn stored as running that this process does not own was interrupted by a restart (AT18)."""
    if t["status"] == "running" and t["turn_id"] not in _hub(state)["turns"]:
        store.interrupt_turn(conn, t["turn_id"])
        return store.get_turn(conn, t["turn_id"]) or t
    return t


def _call_hook(fn, *args):
    import inspect

    n = len(inspect.signature(fn).parameters)
    return fn(*args[:n])


def _provider(state: AppState, session_id: str):
    factory = state.extras.get("copilot_provider_factory")
    if factory is not None:
        return _call_hook(factory, session_id)
    return default_provider()


@router.post("/sessions/{session_id}/messages", status_code=202, response_model=TurnAccepted)
async def post_message(
    session_id: str, body: MessageIn, request: Request, state: State
) -> TurnAccepted:
    return await _start_turn(session_id, body.message, body.context, request, state, mode=body.mode)


@router.post("/turns/{turn_id}/retry", status_code=202, response_model=TurnAccepted)
async def retry_turn(turn_id: str, request: Request, state: State) -> TurnAccepted:
    """Re-run a finished turn with its original message and pinned UI context. Mutation idempotency keys
    derive from the original turn, so a retry returns the existing branch/job/report instead of a duplicate."""
    c = _conn(state)
    try:
        t = store.get_turn(c, turn_id)
    finally:
        c.close()
    if t is None:
        raise not_found("turn_id", turn_id)
    if t["status"] == "running":
        raise DomainError(ErrorCode.VERSION_CONFLICT, "the turn is still running")
    ctx = t["context"]
    ui = UIContext(
        pilot_id=ctx["pilot_id"],
        pilot_version=ctx["pilot_version"],
        season_id=ctx.get("season_id"),
        scenario_revision_id=ctx.get("scenario_revision_id"),
        selected_run_id=ctx.get("selected_run_id"),
        selected_field_id=ctx.get("selected_field_id"),
        timeline_date=ctx.get("timeline_date"),
        view=ctx.get("view"),
        language=ctx.get("language", "en"),
        ui_revision=ctx.get("ui_revision"),
    )
    return await _start_turn(
        t["session_id"],
        t["user_message"],
        ui,
        request,
        state,
        idem_namespace=t.get("idem_namespace") or turn_id,
        mode=t.get("mode") or "chat",
    )


async def _start_turn(
    session_id: str,
    message: str,
    ui: UIContext,
    request: Request,
    state: AppState,
    idem_namespace: str | None = None,
    mode: str = "chat",
) -> TurnAccepted:
    c = _conn(state)
    try:
        row = store.get_session(c, session_id)
        if row is None:
            raise not_found("session_id", session_id)
        prior = [_reap(state, c, t) for t in store.session_turns(c, session_id)]
        known = store.session_known_ids(c, session_id)
    finally:
        c.close()
    running = [t for t in prior if t["status"] == "running"]
    if running:
        raise DomainError(
            ErrorCode.VERSION_CONFLICT,
            "a turn is still running in this session; it finishes "
            "against its pinned context. Ask again after it completes, or cancel it.",
            extra={"running_turn_id": running[0]["turn_id"]},
        )
    try:
        provider = _provider(state, session_id)
    except ProviderError as exc:
        raise DomainError(
            ErrorCode.PROVIDER_UNAVAILABLE, exc.detail, extra={"provider_code": exc.code}
        ) from exc
    backend = Backend(request.app)
    wrap = state.extras.get("copilot_backend_wrapper")  # evaluation harness test doubles only
    if wrap is not None:
        backend = _call_hook(wrap, backend, session_id)
    try:
        ctx = await resolve(backend, ui, role=row["role"])
    except ToolFailure as exc:
        await backend.aclose()
        raise DomainError(ErrorCode.ASSET_UNAVAILABLE, exc.detail) from exc
    turn_id = new_id("turn")
    if mode == "plan":
        limits = state.extras.get("copilot_plan_limits") or PLAN_LIMITS
    else:
        limits = state.extras.get("copilot_limits") or TurnLimits()
    turn = Turn(
        provider=provider,
        backend=backend,
        connect=lambda: _conn(state),
        session_id=session_id,
        turn_id=turn_id,
        message=message,
        context=ctx,
        limits=limits,
        memory=memory_from(prior),
        known_ids=known,
        idem_namespace=idem_namespace,
        mode=mode,
    )
    hub = _hub(state)
    hub["turns"][turn_id] = turn

    async def drive():
        try:
            await turn.run()
            await turn.follow_jobs()
        except Exception:
            log.exception("copilot turn %s crashed", turn_id)
            try:
                turn.emit(
                    "error", {"code": "TURN_FAILED", "detail": "internal error in the copilot turn"}
                )
                store.finish_turn(
                    turn.conn,
                    turn_id,
                    status="failed",
                    answer=None,
                    view_intents=[],
                    created=[],
                    job_ids=[],
                    error={"code": "TURN_FAILED"},
                    request_ids=[],
                    rounds=0,
                    latency_ms=0,
                )
                turn.emit("turn_finished", {"status": "failed", "pending_job_ids": []})
            except Exception:
                log.exception("could not record failure")
        finally:
            turn.close()
            await backend.aclose()
            hub["turns"].pop(turn_id, None)

    task = asyncio.create_task(drive())
    hub["tasks"].add(task)
    task.add_done_callback(hub["tasks"].discard)
    for _ in range(40):  # the turn row exists before we return, so GET/SSE work immediately
        c = _conn(state)
        try:
            if store.get_turn(c, turn_id):
                break
        finally:
            c.close()
        await asyncio.sleep(0.01)
    return TurnAccepted(
        turn_id=turn_id,
        session_id=session_id,
        context=ctx.prompt_view(),
        events_url=f"/api/v2/copilot/turns/{turn_id}/events",
    )


@router.get("/turns/{turn_id}", response_model=TurnView)
def get_turn(turn_id: str, state: State, include_tools: bool = False) -> dict[str, Any]:
    """A turn with its validated answer (CopilotAnswer), created objects, view intents and timings."""
    c = _conn(state)
    try:
        t = store.get_turn(c, turn_id)
        if t is None:
            raise not_found("turn_id", turn_id)
        t = _reap(state, c, t)
        if include_tools:
            t["tool_calls"] = store.tool_calls(c, turn_id)
        t["events"] = store.events_after(c, turn_id, 0)[-200:] if include_tools else None
    finally:
        c.close()
    return t


@router.get("/turns/{turn_id}/event-log", response_model=list[CopilotEvent])
def turn_event_log(
    turn_id: str, state: State, after: Annotated[int, Query(ge=0)] = 0
) -> list[dict[str, Any]]:
    """The same events as the SSE stream, as JSON (restore a finished turn's activity log)."""
    c = _conn(state)
    try:
        if store.get_turn(c, turn_id) is None:
            raise not_found("turn_id", turn_id)
        return store.events_after(c, turn_id, after)
    finally:
        c.close()


@router.get("/turns/{turn_id}/plan-steps", response_model=list[PlanStep])
def turn_plan_steps(turn_id: str, state: State) -> list[dict[str, Any]]:
    """The ``plan_step`` payloads of a plan-mode turn, in order (empty for chat turns)."""
    c = _conn(state)
    try:
        if store.get_turn(c, turn_id) is None:
            raise not_found("turn_id", turn_id)
        return [e["payload"] for e in store.events_after(c, turn_id, 0) if e["type"] == "plan_step"]
    finally:
        c.close()


@router.post("/turns/{turn_id}/cancel")
async def cancel_turn(turn_id: str, state: State) -> dict[str, Any]:
    turn = _hub(state)["turns"].get(turn_id)
    c = _conn(state)
    try:
        t = store.get_turn(c, turn_id)
    finally:
        c.close()
    if t is None:
        raise not_found("turn_id", turn_id)
    if turn is not None:
        turn.cancel.set()
        return {"turn_id": turn_id, "cancel_requested": True, "status": "cancelling"}
    return {"turn_id": turn_id, "cancel_requested": False, "status": t["status"]}


@router.get(
    "/turns/{turn_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE copilot turn events"}
    },
)
async def turn_events(
    turn_id: str,
    request: Request,
    state: State,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    c = _conn(state)
    try:
        if store.get_turn(c, turn_id) is None:
            raise not_found("turn_id", turn_id)
    finally:
        c.close()
    try:
        start = int(last_event_id) if last_event_id else (after or 0)
    except ValueError:
        start = after or 0

    async def stream():
        cursor = start
        idle = 0.0
        finished = False
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            c2 = _conn(state)
            try:
                evs = store.events_after(c2, turn_id, cursor)
            finally:
                c2.close()
            for ev in evs:
                cursor = ev["event_id"]
                data = json.dumps(ev, separators=(",", ":"), ensure_ascii=False, default=str)
                yield f"id: {ev['event_id']}\nevent: {ev['type']}\ndata: {data}\n\n"
                if ev["type"] == "turn_finished" and not ev["payload"].get("pending_job_ids"):
                    finished = True
                if ev["type"] == "jobs_settled":
                    finished = True
            if finished:
                return
            idle = 0.0 if evs else idle + SSE_POLL_S
            await asyncio.sleep(SSE_POLL_S)
            if idle >= SSE_KEEPALIVE_S:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def on_startup(state: AppState) -> int:
    """Call from the app lifespan: turns left running by a previous process are marked failed."""
    c = state.connect()
    try:
        return store.interrupt_running(c)
    finally:
        c.close()
