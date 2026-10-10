"""Job routes: GET /jobs/{id}, SSE /jobs/{id}/events (resumable), POST cancel."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from aabflow.api.errors import not_found
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import Job, JobState
from aabflow.jobs import queue
from aabflow.jobs.events import events_after

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

SSE_POLL_S = 0.3
SSE_KEEPALIVE_S = 10.0


def load_job(conn: sqlite3.Connection, job_id: str) -> Job:
    row = queue.get(conn, job_id)
    if row is None:
        raise not_found("job_id", job_id)
    return queue.row_to_job(row)


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, conn: Conn) -> Job:
    return load_job(conn, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, conn: Conn, state: State) -> Job:
    if queue.request_cancel(conn, job_id) is None:
        raise not_found("job_id", job_id)
    if state.dispatcher:
        state.dispatcher.notify()
    return load_job(conn, job_id)


def _fmt(ev) -> str:
    data = json.dumps(ev.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {ev.event_id}\nevent: {ev.type}\ndata: {data}\n\n"


@router.get(
    "/jobs/{job_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE stream of JobEvent records"}
    },
)
async def job_events(
    job_id: str,
    request: Request,
    state: State,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[int | None, Query(ge=0, description="resume after this event id")] = None,
) -> StreamingResponse:
    conn = state.connect()
    try:
        load_job(conn, job_id)
    finally:
        conn.close()
    try:
        start = int(last_event_id) if last_event_id else (after or 0)
    except ValueError:
        start = after or 0

    async def stream():
        cursor = start
        idle = 0.0
        terminal = {s.value for s in queue.TERMINAL}
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return

            def poll(cursor=cursor):
                c = state.connect()
                try:
                    evs = events_after(c, job_id, cursor)
                    row = queue.get(c, job_id)
                    return evs, row["state"] if row else JobState.failed.value
                finally:
                    c.close()

            evs, st = await asyncio.to_thread(poll)
            for ev in evs:
                cursor = ev.event_id
                yield _fmt(ev)
            if evs:
                idle = 0.0
            if st in terminal and not evs:
                return
            await asyncio.sleep(SSE_POLL_S)
            idle += SSE_POLL_S
            if idle >= SSE_KEEPALIVE_S:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
