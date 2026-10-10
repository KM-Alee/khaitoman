"""Roster window caps, supply curtailment and closures (T4.3, T3.5).

Semantics (shared with the data stream):

* ``RosterWindow.outlet_node_id`` is the accounting node where the cap is
  measured. ``accounting_boundary="outlet"``: the cap is counted at that node
  (the watercourse head / mogha); the field receives it times the product of
  the delivery factors on the edges from that node down to the field's node, so
  tail outlets receive less of the same time right. ``"field_inlet"``: the cap
  is counted at the field node itself.
* time basis: cap = rate_m3_s x open seconds; volume basis: volume_cap x open
  fraction of the window. A time right is never converted into a seasonal volume.
* the supply profile's multiplier is resolved once from its ordered
  transformations: ``absolute_multiplier`` replaces the multiplier,
  ``relative_multiplier`` multiplies it; a transformation id may appear only
  once; a pre-reduced profile rejects an additional scalar reduction.
* closures (supply ``closure`` transformations and edge closures on the path)
  remove the closed seconds from the window; water flows at a constant fraction
  of the curtailed boundary rate across the open sub-intervals.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from aabflow.domain import units
from aabflow.domain.calendar import to_utc
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import RightsBasis, RosterWindow, SupplyProfile, SupplyTransformation
from aabflow.water.network import Network, NetworkError, overlap_seconds


class SupplyError(ValueError):
    pass


@dataclass(frozen=True)
class Closure:
    start: datetime
    end: datetime
    edge_ids: frozenset[str]  # empty = whole source
    reason: str


@dataclass(frozen=True)
class ResolvedSupply:
    supply_profile_id: str
    multiplier: float
    closures: tuple[Closure, ...]
    resolved_hash: str


def resolve_supply(profile: SupplyProfile, extra_uniform_reduction: float = 0.0) -> ResolvedSupply:
    """Apply transformations in order; curtailment is applied exactly once."""
    seen: set[str] = set()
    mult = 1.0
    closures: list[Closure] = []
    for t in profile.transformations:
        if t.transformation_id in seen:
            raise SupplyError(f"transformation {t.transformation_id} applied twice")
        seen.add(t.transformation_id)
        if t.kind == "absolute_multiplier":
            if t.multiplier is None:
                raise SupplyError(f"{t.transformation_id}: absolute multiplier needs a value")
            mult = units.fraction(t.multiplier, "multiplier")
        elif t.kind == "relative_multiplier":
            if t.multiplier is None:
                raise SupplyError(f"{t.transformation_id}: relative multiplier needs a value")
            mult *= units.fraction(t.multiplier, "multiplier")
        elif t.kind == "closure":
            if t.start is None or t.end is None or to_utc(t.end) <= to_utc(t.start):
                raise SupplyError(f"{t.transformation_id}: closure needs start < end")
            closures.append(
                Closure(to_utc(t.start), to_utc(t.end), frozenset(t.edge_ids), t.transformation_id)
            )
    r = units.fraction(extra_uniform_reduction, "uniform_reduction_fraction")
    if r > 0:
        if profile.pre_reduced:
            raise SupplyError(
                f"profile {profile.supply_profile_id} is pre-reduced; a further uniform reduction "
                "would apply the same curtailment twice"
            )
        mult *= 1.0 - r
    h = content_hash(
        {
            "base": profile.base_profile_hash,
            "multiplier": mult,
            "closures": [[c.start, c.end, sorted(c.edge_ids)] for c in closures],
        }
    )
    return ResolvedSupply(profile.supply_profile_id, mult, tuple(closures), h)


def profile_hash(
    supply_profile_id: str,
    base_profile_hash: str,
    transformations: Iterable[SupplyTransformation],
    pre_reduced: bool = False,
) -> str:
    return content_hash(
        {
            "supply_profile_id": supply_profile_id,
            "base": base_profile_hash,
            "transformations": [t.model_dump(mode="json") for t in transformations],
            "pre_reduced": pre_reduced,
        }
    )


@dataclass(frozen=True)
class SubInterval:
    start: datetime
    end: datetime
    open_s: float  # seconds open for delivery to the field
    path_factor: float  # boundary -> field factor during this piece


@dataclass(frozen=True)
class WindowCap:
    window_id: str
    field_id: str
    boundary_cap_m3: float  # at the accounting boundary
    field_cap_m3: float  # deliverable at the field node
    pieces: tuple[SubInterval, ...]
    closed_fraction: float

    def split(self, volume_at_field: float) -> list[tuple[SubInterval, float]]:
        """Constant-fraction flow: field receipt per piece proportional to open_s x factor."""
        w = [p.open_s * p.path_factor for p in self.pieces]
        tot = sum(w)
        if tot <= 0:
            return []
        return [
            (p, volume_at_field * wi / tot) for p, wi in zip(self.pieces, w, strict=True) if wi > 0
        ]


def window_cap(
    window: RosterWindow,
    field_node_id: str,
    network: Network,
    supply: ResolvedSupply,
    *,
    factor_overrides: Mapping[str, float] | None = None,
    extra_closures: Iterable[Closure] = (),
    boundaries: Iterable[datetime] = (),
) -> WindowCap:
    """Deliverable cap for one roster window under a resolved supply and configuration.

    ``boundaries`` (atomic interval edges) split the window into pieces so
    resource use can be attributed per atomic interval.
    """
    w0, w1 = to_utc(window.start), to_utc(window.end)
    if w1 <= w0:
        raise SupplyError(f"window {window.window_id} ends before it starts")
    if window.outlet_node_id not in network.nodes:
        raise NetworkError(
            f"window {window.window_id} boundary node {window.outlet_node_id} unknown"
        )
    path = network.path_edges(field_node_id)
    if window.accounting_boundary == "outlet":
        below = network.path_between(window.outlet_node_id, field_node_id)
    else:
        if window.outlet_node_id != field_node_id:
            raise SupplyError(
                f"window {window.window_id}: field_inlet boundary must be the field node "
                f"{field_node_id}, got {window.outlet_node_id}"
            )
        below = []
    cuts = sorted({w0, w1, *(to_utc(b) for b in boundaries if w0 < to_utc(b) < w1)})
    closures = list(supply.closures) + list(extra_closures)
    for eid in path:
        for c0, c1 in network.edges[eid].closures:
            closures.append(Closure(to_utc(c0), to_utc(c1), frozenset({eid}), f"edge:{eid}"))
    pieces: list[SubInterval] = []
    total_s = (w1 - w0).total_seconds()
    open_total = 0.0
    for a, b in itertools.pairwise(cuts):
        dur = (b - a).total_seconds()
        closed = _closed_seconds(a, b, closures, set(path))
        open_s = max(0.0, dur - closed)
        open_total += open_s
        pieces.append(SubInterval(a, b, open_s, network.path_factor(below, factor_overrides)))
    open_frac = open_total / total_s
    if window.basis is RightsBasis.time:
        if window.rate_m3_s is None:
            raise SupplyError(f"time-basis window {window.window_id} lacks rate_m3_s")
        per_s = window.rate_m3_s * supply.multiplier
        boundary = sum(per_s * p.open_s for p in pieces)
        field_cap = sum(per_s * p.open_s * p.path_factor for p in pieces)
    else:
        if window.volume_cap_m3 is None:
            raise SupplyError(f"volume-basis window {window.window_id} lacks volume_cap_m3")
        boundary = window.volume_cap_m3 * supply.multiplier * open_frac
        # distribute the volume uniformly over open time
        field_cap = sum(
            (window.volume_cap_m3 * supply.multiplier * p.open_s / total_s) * p.path_factor
            for p in pieces
        )
    return WindowCap(
        window.window_id, window.field_id, boundary, field_cap, tuple(pieces), 1 - open_frac
    )


def _closed_seconds(a: datetime, b: datetime, closures: list[Closure], path: set[str]) -> float:
    """Union of closure overlaps affecting this path within [a, b)."""
    spans = []
    for c in closures:
        if c.edge_ids and not (c.edge_ids & path):
            continue
        lo, hi = max(a, c.start), min(b, c.end)
        if hi > lo:
            spans.append((lo, hi))
    spans.sort()
    total = 0.0
    cur0 = cur1 = None
    for lo, hi in spans:
        if cur1 is None or lo > cur1:
            if cur1 is not None:
                total += (cur1 - cur0).total_seconds()
            cur0, cur1 = lo, hi
        else:
            cur1 = max(cur1, hi)
    if cur1 is not None:
        total += (cur1 - cur0).total_seconds()
    return total


def check_exclusive(windows: Iterable[RosterWindow], group_of: Mapping[str, str]) -> list[str]:
    """Return overlapping window pairs among fields of the same watercourse group."""
    by_group: dict[str, list[RosterWindow]] = {}
    for w in windows:
        by_group.setdefault(group_of.get(w.field_id, "?"), []).append(w)
    bad = []
    for g, ws in by_group.items():
        ws = sorted(ws, key=lambda w: to_utc(w.start))
        for a, b in itertools.pairwise(ws):
            if overlap_seconds(to_utc(a.start), to_utc(a.end), to_utc(b.start), to_utc(b.end)) > 0:
                bad.append(f"{g}: {a.window_id} overlaps {b.window_id}")
    return bad
