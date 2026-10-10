"""Shared helpers for real-source acquisition (T2): HTTP with backoff, immutable raw
storage, JSON writing, and evidence construction.

Raw bytes are written once under ``data/raw/<provider>/<...>`` and never rewritten:
a second write with different content is an error, the same content is a no-op.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from aabflow.domain.hashes import file_sha256, sha256_hex

USER_AGENT = "AabFlow/2.0 (AICON hackathon research prototype; irrigation planning)"
INGESTION_VERSION = "aabflow-ingestion-1.0.0"


class IngestionError(RuntimeError):
    """A real-source step failed; message says which source and why."""


class ImmutableRawError(IngestionError):
    """Attempt to overwrite raw source bytes with different content."""


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# --- HTTP ------------------------------------------------------------------


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes
    retrieved_at: datetime
    headers: dict[str, str]
    request_body: str | None = None

    @property
    def sha256(self) -> str:
        return sha256_hex(self.content)


def http_request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 120.0,
    retries: int = 4,
    backoff_s: float = 2.0,
    client: httpx.Client | None = None,
) -> FetchResult:
    """GET/POST with exponential backoff on 429/5xx/network errors.

    Respects ``Retry-After`` when the provider sends it (Open-Meteo, Overpass).
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last: Exception | None = None
    own = client is None
    cl = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        for attempt in range(retries + 1):
            try:
                r = cl.request(method, url, params=params, data=data, headers=hdrs)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = float(r.headers.get("Retry-After", backoff_s * 2**attempt))
                    last = IngestionError(f"{url}: HTTP {r.status_code}")
                    if attempt < retries:
                        time.sleep(min(wait, 60))
                        continue
                    raise last
                if r.status_code >= 400:
                    raise IngestionError(f"{url}: HTTP {r.status_code}: {r.text[:300]}")
                body = None
                if data:
                    body = "&".join(f"{k}={v}" for k, v in data.items())
                return FetchResult(
                    url=str(r.url),
                    status=r.status_code,
                    content=r.content,
                    retrieved_at=utc_now(),
                    headers={k.lower(): v for k, v in r.headers.items()},
                    request_body=body,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                if attempt < retries:
                    time.sleep(backoff_s * 2**attempt)
                    continue
                raise IngestionError(f"{url}: network error after {retries + 1} tries: {exc}")
        raise IngestionError(f"{url}: failed: {last}")
    finally:
        if own:
            cl.close()


# --- immutable raw store ---------------------------------------------------


class RawStore:
    """Write-once store for source bytes under a root (default ``data/raw``)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root.resolve()) + os.sep):
            raise ImmutableRawError(f"raw path escapes store: {rel}")
        return p

    def put(self, rel: str, content: bytes) -> tuple[Path, str]:
        p = self.path(rel)
        digest = sha256_hex(content)
        if p.exists():
            if file_sha256(p) != digest:
                raise ImmutableRawError(f"refusing to overwrite raw source {rel} with new bytes")
            return p, digest
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".partial")
        tmp.write_bytes(content)
        tmp.replace(p)
        os.chmod(p, 0o444)
        return p, digest

    def put_json(self, rel: str, obj: Any) -> tuple[Path, str]:
        return self.put(rel, json.dumps(obj, indent=2, sort_keys=True, default=str).encode())

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def read_bytes(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()


# --- JSON output -----------------------------------------------------------


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return iso(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=_default, allow_nan=False) + "\n"


def write_json(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
