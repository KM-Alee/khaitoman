"""Canonical JSON and SHA-256 content hashes (T3.6)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


class CanonicalizationError(ValueError):
    pass


def _normalize(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise CanonicalizationError(f"nonfinite float {obj!r} cannot be hashed")
        return obj
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise CanonicalizationError(f"nonfinite decimal {obj!r}")
        # One normalized representation: no exponent, no trailing zeros.
        s = format(obj.normalize(), "f")
        return {"$decimal": s if s != "-0" else "0"}
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise CanonicalizationError("naive datetimes are ambiguous; use UTC instants")
        return obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        if not all(isinstance(k, str) for k in obj):
            raise CanonicalizationError("object keys must be strings")
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_normalize(v) for v in obj)
    raise CanonicalizationError(f"unsupported type {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, explicit nulls. Sets sort; lists keep order.

    Callers sort set-like ID arrays (or pass a set) before hashing.
    """
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def file_sha256(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()
