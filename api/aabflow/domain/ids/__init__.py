"""Internal IDs and provider-namespaced source IDs (T3.1)."""

from __future__ import annotations

import re
import uuid

_PREFIX = re.compile(r"^[a-z][a-z0-9_]*$")


def new_id(prefix: str) -> str:
    """Opaque internal ID, e.g. ``run_3f2a...``. Never derived from data values."""
    if not _PREFIX.match(prefix):
        raise ValueError(f"invalid id prefix {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex}"


def source_id(provider: str, raw_id: str | int) -> str:
    """Namespace an imported identifier by provider, e.g. ``osm:way/123``."""
    if not _PREFIX.match(provider):
        raise ValueError(f"invalid provider {provider!r}")
    raw = str(raw_id)
    if not raw:
        raise ValueError("empty source id")
    return f"{provider}:{raw}"
