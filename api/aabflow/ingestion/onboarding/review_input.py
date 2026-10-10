"""Reviewer input checks for field and network edits (PRD §5.2–5.3, T9.3).

Unknown fields, missing reasons and out-of-range network assumptions are
rejections: they do not advance the review version. A short selection is a
structural blocker and is not published.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import shape

from ..review.fields import ManualEdit

CAPACITY_M3_S = (0.05, 0.20)
ROSTER_BASES = ("declared_cca", "selected_area")


class ReviewRejected(ValueError):
    """The edit itself is invalid. The stored review version stays put."""


def _polygon(geojson: dict | None, label: str) -> None:
    if not isinstance(geojson, dict):
        raise ReviewRejected(f"{label} must be a GeoJSON polygon")
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise ReviewRejected(f"{label} is not valid GeoJSON: {exc}") from exc
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ReviewRejected(f"{label} must be a polygon")
    if not geom.is_valid:
        raise ReviewRejected(f"{label} is an invalid polygon")


def field_edits(raw: list[dict[str, Any]], known_ids: set[str]) -> list[ManualEdit]:
    edits: list[ManualEdit] = []
    for item in raw:
        model_id = str(item.get("model_id") or "")
        action = item.get("action")
        reason = str(item.get("reason") or "").strip()
        if not model_id:
            raise ReviewRejected("field edit model_id is required")
        if model_id not in known_ids:
            raise ReviewRejected(f"manual edit references unknown model id {model_id}")
        if not reason:
            raise ReviewRejected(f"field edit {model_id} needs a reason")
        if action not in ("reject", "replace_geometry", "split", "merge_with"):
            raise ReviewRejected(f"unknown field edit action {action!r}")
        others = [str(x) for x in item.get("other_model_ids") or []]
        for other in others:
            if other not in known_ids:
                raise ReviewRejected(f"manual edit references unknown model id {other}")
        geometry = item.get("geometry_wgs84")
        parts = item.get("parts_wgs84")
        if action == "replace_geometry":
            _polygon(geometry, f"{model_id} geometry")
        if action == "split":
            if not parts:
                raise ReviewRejected(f"split of {model_id} needs parts_wgs84")
            for index, part in enumerate(parts):
                _polygon(part, f"{model_id} part {index + 1}")
        if action == "merge_with" and not others:
            raise ReviewRejected(f"merge of {model_id} needs other_model_ids")
        edits.append(
            ManualEdit(
                model_id=model_id,
                action=action,
                reason=reason,
                geometry_wgs84=geometry,
                parts_wgs84=parts,
                other_model_ids=others,
            )
        )
    return edits


def network_review(raw: dict[str, Any], canal_ids: set[str]) -> dict[str, Any]:
    """Explicit direction, source, outlet, capacity and roster before publication."""
    direction = raw.get("direction")
    if direction != "downstream":
        raise ReviewRejected("network direction must be downstream")
    source = str(raw.get("source_feature_id") or "")
    if not source or source not in canal_ids:
        raise ReviewRejected("network source_feature_id is not an observed canal in this intake")
    try:
        capacity = float(raw["capacity_m3_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewRejected("network capacity_m3_s must be a finite number") from exc
    low, high = CAPACITY_M3_S
    if not math.isfinite(capacity) or not (low <= capacity <= high):
        raise ReviewRejected(f"network capacity_m3_s must be within {low}–{high}")
    roster = raw.get("roster_basis")
    if roster not in ROSTER_BASES:
        raise ReviewRejected("roster_basis must be declared_cca or selected_area")
    if raw.get("outlet") != "reach_group":
        raise ReviewRejected("outlet must be reach_group")
    if raw.get("acknowledged") is not True:
        raise ReviewRejected("network assumptions must be explicitly acknowledged")
    return {
        "direction": "downstream",
        "source_feature_id": source,
        "capacity_m3_s": capacity,
        "roster_basis": roster,
        "outlet": "reach_group",
        "acknowledged": True,
    }


def structural_blockers(st: dict[str, Any]) -> list[str]:
    blockers = [str(item) for item in (st.get("review_blockers") or [])]
    network = st.get("network_review") or {}
    if not network.get("acknowledged"):
        blockers.append(
            "structural: direction, source, outlet, capacity and roster are not reviewed"
        )
    summary = st.get("review_summary") or {}
    selected = summary.get("selected")
    if selected is not None and selected != 30:
        blockers.append(f"structural: {selected} fields selected; 30 required")
    return blockers
