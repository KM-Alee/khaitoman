"""Job execution: a dispatcher in the API process feeds a process pool (T9.4).

One API process owns the dispatcher. CPU work runs in ``settings.workers``
spawned processes (default 2), never on the event loop. Each running job keeps a
lease alive from a heartbeat thread, which also notices cancellation requests and
fires the cooperative cancel hooks (for example ``CpSolver.stop_search``).
On restart, jobs left running are marked ``interrupted`` honestly; queued jobs
are executed as normal because they had not started.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import multiprocessing as mp
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from aabflow.config import Settings
from aabflow.domain.schemas import JobState
from aabflow.jobs import queue
from aabflow.jobs.cancellation import CancelToken, JobCancelled
from aabflow.jobs.events import append_event
from aabflow.repositories.sqlite import connect, dumps, loads, tx

log = logging.getLogger("aabflow.jobs")

# operation -> "module:function"; handler(ctx: JobContext, payload: dict) -> dict (result)
HANDLERS: dict[str, str] = {
    "solve": "aabflow.services.runs.jobs:solve_job",
    "analysis.frontier": "aabflow.services.analyses.jobs:frontier_job",
    "analysis.stress": "aabflow.services.analyses.jobs:stress_job",
    "analysis.why_not": "aabflow.services.analyses.jobs:why_not_job",
    "analysis.sensitivity": "aabflow.services.analyses.jobs:sensitivity_job",
    "analysis.synergy": "aabflow.services.analyses.jobs:synergy_job",
    "surrogate.verify": "aabflow.services.surrogate_service:verify_job",
    "report": "aabflow.services.reports:report_job",
    "onboarding.process": "aabflow.services.onboarding:process_job",
    "test.sleep": "aabflow.jobs.worker:_sleep_job",
    "test.fail": "aabflow.jobs.worker:_fail_job",
}


class JobContext:
    """What a handler sees: progress/stage reporting and cooperative cancellation."""

    def __init__(self, settings: Settings, job_id: str, owner: str, conn):
        self.settings = settings
        self.job_id = job_id
        self.owner = owner
        self.conn = conn
        self.token = CancelToken()
        self.started = time.monotonic()

    def stage(self, name: str, detail: Any = None, progress: float | None = None) -> None:
        queue.set_stage(self.conn, self.job_id, name, progress, detail)

    def progress(self, fraction: float, detail: Any = None) -> None:
        """Only from completed sub-units (subruns, candidates), never time-based guesses."""
        queue.set_stage(self.conn, self.job_id, None, max(0.0, min(1.0, fraction)), detail)

    def event(self, type_: str, payload: dict[str, Any]) -> None:
        with tx(self.conn):
            append_event(self.conn, self.job_id, type_, payload)

    def check_cancel(self) -> None:
        self.token.check()

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled


def _resolve(operation: str):
    spec = HANDLERS.get(operation)
    if spec is None:
        raise LookupError(f"no handler registered for operation {operation!r}")
    mod, fn = spec.split(":")
    return getattr(importlib.import_module(mod), fn)


def _heartbeat_loop(ctx: JobContext, stop: threading.Event) -> None:
    conn = connect(ctx.settings.db_path)
    last_event = time.monotonic()
    try:
        while not stop.wait(ctx.settings.heartbeat_s):
            try:
                st = queue.heartbeat(conn, ctx.job_id, ctx.owner, ctx.settings.lease_s)
            except Exception:
                log.debug("heartbeat failed", exc_info=True)
                continue
            if st is None or st == JobState.cancel_requested.value:
                ctx.token.cancel()
            if time.monotonic() - last_event >= 10:
                last_event = time.monotonic()
                try:
                    with tx(conn):
                        append_event(
                            conn,
                            ctx.job_id,
                            "heartbeat",
                            {"elapsed_s": round(time.monotonic() - ctx.started, 1)},
                        )
                except Exception:
                    log.debug("heartbeat event failed", exc_info=True)
    finally:
        conn.close()


def run_job(settings: Settings, job_id: str, owner: str) -> str:
    """Executed in a worker process. Returns the final state."""
    conn = connect(settings.db_path)
    try:
        row = queue.get(conn, job_id)
        if row is None:
            return "missing"
        ctx = JobContext(settings, job_id, owner, conn)
        if row["state"] == JobState.cancel_requested.value:
            ctx.token.cancel()
        stop = threading.Event()
        hb = threading.Thread(target=_heartbeat_loop, args=(ctx, stop), daemon=True)
        hb.start()
        try:
            handler = _resolve(row["operation"])
            ctx.check_cancel()
            result = handler(ctx, loads(row["payload"]) or {})
            result_ref = result if isinstance(result, str) else (dumps(result) if result is not None else None)
            if ctx.cancelled:
                queue.finish(
                    conn,
                    job_id,
                    JobState.cancelled,
                    result_ref=result_ref,
                    event_payload={
                        "detail": "cancelled; any result completed before cancellation is "
                        "inspectable but was not applied as the scenario's current result"
                    },
                )
                return "cancelled"
            queue.finish(conn, job_id, JobState.succeeded, result_ref=result_ref)
            return "succeeded"
        except JobCancelled:
            queue.finish(conn, job_id, JobState.cancelled, event_payload={"detail": "cancelled"})
            return "cancelled"
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the job
            from aabflow.api.errors import DomainError

            if isinstance(exc, DomainError):
                err = {
                    "code": exc.code.value,
                    "detail": exc.detail,
                    "fields": exc.fields,
                    **exc.extra,
                }
            else:
                err = {
                    "code": "JOB_FAILED",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=8)[-4000:],
                }
            queue.finish(conn, job_id, JobState.failed, error=err)
            return "failed"
        finally:
            stop.set()
            hb.join(timeout=5)
    finally:
        conn.close()


def _worker_init() -> None:
    # Bounded math threads per worker (T12.3): no BLAS/LightGBM oversubscription.
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "2")


def _sleep_job(ctx: JobContext, payload: dict) -> dict:
    """Diagnostic operation used by the job-runtime tests: sleeps in checked slices."""
    steps = int(payload.get("steps", 5))
    for i in range(steps):
        ctx.check_cancel()
        time.sleep(float(payload.get("step_s", 0.1)))
        ctx.progress((i + 1) / steps, {"completed_steps": i + 1})
    return {"slept_steps": steps}


def _fail_job(ctx: JobContext, payload: dict) -> dict:
    raise RuntimeError(payload.get("message", "requested failure"))


class Dispatcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.owner = f"dispatcher-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._pool: ProcessPoolExecutor | None = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._active: dict[str, asyncio.Future] = {}
        self.running = False
        self.interrupted_on_start: list[str] = []

    async def start(self) -> None:
        conn = connect(self.settings.db_path)
        try:
            self.interrupted_on_start = queue.mark_interrupted(
                conn, "API restarted while the job was running; no valid lease remained"
            )
        finally:
            conn.close()
        self._pool = ProcessPoolExecutor(
            max_workers=max(1, self.settings.workers),
            mp_context=mp.get_context("spawn"),
            initializer=_worker_init,
        )
        self.running = True
        self._task = asyncio.create_task(self._loop())

    def notify(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self.running = False
        self._wake.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                log.debug("dispatcher loop stopped")
        if self._active:
            conn = connect(self.settings.db_path)
            try:
                for jid in list(self._active):
                    queue.request_cancel(conn, jid)
            finally:
                conn.close()
            await asyncio.wait(list(self._active.values()), timeout=10)
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if self._active:
            conn = connect(self.settings.db_path)
            try:
                for jid in list(self._active):
                    queue.finish(
                        conn,
                        jid,
                        JobState.interrupted,
                        error={"code": "INTERRUPTED", "detail": "shutdown"},
                    )
            finally:
                conn.close()

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        last_lease_check = 0.0
        while self.running:
            try:
                while len(self._active) < max(1, self.settings.workers):
                    jid = await asyncio.to_thread(self._claim)
                    if jid is None:
                        break
                    try:
                        fut = loop.run_in_executor(self._pool, run_job, self.settings, jid, self.owner)
                    except Exception as exc:  # noqa: BLE001 - submission failure must not strand the job
                        await asyncio.to_thread(self._submit_failed, jid, exc)
                        continue
                    self._active[jid] = fut
                    fut.add_done_callback(lambda f, j=jid: self._done(j, f))
                if time.monotonic() - last_lease_check > self.settings.lease_s:
                    last_lease_check = time.monotonic()
                    await asyncio.to_thread(self._check_leases)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("dispatcher iteration failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.25)
            except TimeoutError:
                pass

    def _claim(self) -> str | None:
        conn = connect(self.settings.db_path)
        try:
            return queue.claim_next(conn, self.owner, self.settings.lease_s)
        finally:
            conn.close()

    def _submit_failed(self, job_id: str, exc: Exception) -> None:
        conn = connect(self.settings.db_path)
        try:
            queue.finish(conn, job_id, JobState.interrupted,
                         error={"code": "INTERRUPTED", "detail": f"could not start worker: {exc!r}"})
        finally:
            conn.close()

    def _check_leases(self) -> None:
        conn = connect(self.settings.db_path)
        try:
            for jid in queue.expired_leases(conn):
                if jid not in self._active:
                    queue.finish(
                        conn,
                        jid,
                        JobState.interrupted,
                        error={"code": "INTERRUPTED", "detail": "worker lease expired"},
                    )
        finally:
            conn.close()

    def _done(self, job_id: str, fut) -> None:
        self._active.pop(job_id, None)
        exc = fut.exception() if not fut.cancelled() else None
        if exc is not None or fut.cancelled():
            conn = connect(self.settings.db_path)
            try:
                detail = "worker process died" if isinstance(exc, BrokenProcessPool) else f"{exc!r}"
                queue.finish(
                    conn,
                    job_id,
                    JobState.interrupted,
                    error={"code": "INTERRUPTED", "detail": detail},
                )
            finally:
                conn.close()
            if isinstance(exc, BrokenProcessPool) and self.running:
                self._pool = ProcessPoolExecutor(
                    max_workers=max(1, self.settings.workers),
                    mp_context=mp.get_context("spawn"),
                    initializer=_worker_init,
                )
        self._wake.set()
