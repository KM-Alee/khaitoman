"""Per-app state shared by routers (settings, repositories, dispatcher)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from aabflow.config import Settings
from aabflow.repositories.sqlite import connect
from aabflow.services.catalog import Catalog
from aabflow.services.pilots import PilotRepository


@dataclass
class AppState:
    settings: Settings
    pilots: PilotRepository
    catalog: Catalog
    schema_version: str | None = None
    dispatcher: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    def connect(self) -> sqlite3.Connection:
        return connect(self.settings.db_path)


def get_state(request: Request) -> AppState:
    return request.app.state.aab


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = request.app.state.aab.connect()
    try:
        yield conn
    finally:
        conn.close()
