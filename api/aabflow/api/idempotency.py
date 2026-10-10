"""Idempotency-Key handling for create routes (T9.1, T9.4).

Same key + same canonical request -> the originally created resource (same body
and status). Same key + different request -> 409 IDEMPOTENCY_CONFLICT. A key is
reserved before the resource is created so concurrent retries cannot both create.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse

from aabflow.api.errors import DomainError
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import ErrorCode
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow


def run_idempotent(
    conn: sqlite3.Connection,
    scope: str,
    key: str | None,
    request: Any,
    create: Callable[[], tuple[int, dict[str, Any]]],
) -> JSONResponse:
    if not key:
        status, body = create()
        return JSONResponse(body, status_code=status)
    if len(key) > 200:
        raise DomainError(
            ErrorCode.INVALID_INPUT, "Idempotency-Key is too long", {"Idempotency-Key": "max 200"}
        )
    h = content_hash(request)
    with tx(conn):
        row = conn.execute(
            "SELECT * FROM idempotency WHERE scope = ? AND key = ?", (scope, key)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO idempotency (scope, key, request_hash, status_code, response, created_at) "
                "VALUES (?,?,?,0,'null',?)",
                (scope, key, h, utcnow()),
            )
    if row is not None:
        if row["request_hash"] != h:
            raise DomainError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency-Key was already used with a different request",
                {"Idempotency-Key": key},
            )
        if row["status_code"] == 0:
            raise DomainError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "a request with this Idempotency-Key is still being processed",
                {"Idempotency-Key": key},
                status=409,
            )
        resp = JSONResponse(loads(row["response"]), status_code=row["status_code"])
        resp.headers["Idempotent-Replay"] = "true"
        return resp
    try:
        status, body = create()
    except BaseException:
        with tx(conn):
            conn.execute("DELETE FROM idempotency WHERE scope = ? AND key = ?", (scope, key))
        raise
    with tx(conn):
        conn.execute(
            "UPDATE idempotency SET status_code = ?, response = ? WHERE scope = ? AND key = ?",
            (status, dumps(body), scope, key),
        )
    return JSONResponse(body, status_code=status)
