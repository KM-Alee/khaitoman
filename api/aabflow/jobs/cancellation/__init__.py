"""Cooperative cancellation primitives shared by job handlers and the solver."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("aabflow.jobs")


class JobCancelled(Exception):
    """Raised inside a handler once cancellation was requested."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._callbacks: list = []
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb()
            except Exception:
                log.warning("cancel hook failed", exc_info=True)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise JobCancelled("cancellation requested")

    def on_cancel(self, cb) -> None:
        """Register a hook (e.g. CpSolver.stop_search) run when cancellation arrives."""
        with self._lock:
            self._callbacks.append(cb)
            fire = self._event.is_set()
        if fire:
            cb()

    def remove(self, cb) -> None:
        with self._lock:
            if cb in self._callbacks:
                self._callbacks.remove(cb)


NEVER = CancelToken()
