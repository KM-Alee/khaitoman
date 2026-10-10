"""Directed-tree canal network and routing (T4.2).

Routing rule: for an outlet delivery ``D`` through the unique path edges with
factors ``eta_e``, each edge's intake is its downstream demand divided by its
own factor, recursively upstream; demands sharing an edge are summed per
atomic interval. Loss = intake - delivery. No aggregated path factor is applied
a second time. A closed edge has zero capacity for the affected interval, so all
canal delivery through it is unavailable.

This is an explicitly simplified fractional-loss scenario model; it does not
estimate transit hydraulics, backwater, gate response or recharge.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from aabflow.domain import units
from aabflow.domain.calendar import to_utc
from aabflow.domain.schemas import Edge, Node, NodeKind


class NetworkError(ValueError):
    """Invalid topology or routing request."""


def overlap_seconds(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    lo, hi = max(a0, b0), min(a1, b1)
    return max(0.0, (hi - lo).total_seconds())


@dataclass(frozen=True)
class RouteLeg:
    edge_id: str
    intake_m3: float
    delivered_m3: float

    @property
    def loss_m3(self) -> float:
        return self.intake_m3 - self.delivered_m3


@dataclass
class Network:
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    parent_edge: dict[str, str] = field(default_factory=dict)  # node -> incoming edge id
    children: dict[str, list[str]] = field(default_factory=dict)  # node -> outgoing edge ids

    @classmethod
    def from_records(cls, nodes: Iterable[Node], edges: Iterable[Edge]) -> Network:
        nmap: dict[str, Node] = {}
        for n in nodes:
            if n.node_id in nmap:
                raise NetworkError(f"duplicate node {n.node_id}")
            nmap[n.node_id] = n
        emap: dict[str, Edge] = {}
        parent: dict[str, str] = {}
        children: dict[str, list[str]] = {nid: [] for nid in nmap}
        for e in edges:
            if e.edge_id in emap:
                raise NetworkError(f"duplicate edge {e.edge_id}")
            for nid in (e.upstream_node_id, e.downstream_node_id):
                if nid not in nmap:
                    raise NetworkError(f"edge {e.edge_id} references unknown node {nid}")
            if e.upstream_node_id == e.downstream_node_id:
                raise NetworkError(f"edge {e.edge_id} is a self loop")
            units.delivery_factor(e.delivery_factor, f"{e.edge_id}.delivery_factor")
            if e.downstream_node_id in parent:
                raise NetworkError(
                    f"node {e.downstream_node_id} has two incoming edges "
                    f"({parent[e.downstream_node_id]}, {e.edge_id}); network must be a tree"
                )
            for c in e.capacities:
                if to_utc(c.end) <= to_utc(c.start):
                    raise NetworkError(f"edge {e.edge_id} capacity interval ends before start")
            for c0, c1 in e.closures:
                if to_utc(c1) <= to_utc(c0):
                    raise NetworkError(f"edge {e.edge_id} closure ends before start")
            emap[e.edge_id] = e
            parent[e.downstream_node_id] = e.edge_id
            children[e.upstream_node_id].append(e.edge_id)
        net = cls(nmap, emap, parent, children)
        for nid, n in nmap.items():
            if nid not in parent and n.kind is not NodeKind.source and children[nid]:
                raise NetworkError(f"node {nid} has outgoing edges but no supply (not a source)")
        for nid in nmap:
            net.path_edges(nid)  # raises on cycles
        for nid, n in nmap.items():
            if n.kind is NodeKind.source and nid in parent:
                raise NetworkError(f"source node {nid} has an incoming edge")
        return net

    # ------------------------------------------------------------------ topology

    def root_of(self, node_id: str) -> str:
        path = self.path_edges(node_id)
        return self.edges[path[0]].upstream_node_id if path else node_id

    def path_edges(self, node_id: str) -> list[str]:
        """Edges from the root down to ``node_id`` (top-down order)."""
        if node_id not in self.nodes:
            raise NetworkError(f"unknown node {node_id}")
        out: list[str] = []
        seen: set[str] = set()
        cur = node_id
        while cur in self.parent_edge:
            if cur in seen:
                raise NetworkError(f"cycle through node {cur}")
            seen.add(cur)
            eid = self.parent_edge[cur]
            out.append(eid)
            cur = self.edges[eid].upstream_node_id
        out.reverse()
        return out

    def path_between(self, upper: str, lower: str) -> list[str]:
        """Edges strictly below ``upper`` down to ``lower`` (``upper`` must be an ancestor)."""
        full = self.path_edges(lower)
        if upper == lower:
            return []
        for i, eid in enumerate(full):
            if self.edges[eid].upstream_node_id == upper:
                return full[i:]
        raise NetworkError(f"{upper} is not upstream of {lower}")

    def is_reachable(self, node_id: str) -> bool:
        root = self.root_of(node_id)
        return self.nodes[root].kind is NodeKind.source

    # ------------------------------------------------------------------ routing

    def factor(self, edge_id: str, overrides: Mapping[str, float] | None = None) -> float:
        if overrides and edge_id in overrides:
            return units.delivery_factor(overrides[edge_id], f"{edge_id}.delivery_factor")
        return self.edges[edge_id].delivery_factor

    def path_factor(self, edge_ids: Iterable[str], overrides: Mapping[str, float] | None = None) -> float:
        f = 1.0
        for eid in edge_ids:
            f *= self.factor(eid, overrides)
        return f

    def route(
        self, delivery_m3: float, edge_ids: list[str], overrides: Mapping[str, float] | None = None
    ) -> list[RouteLeg]:
        """Recursive intake for a delivery at the bottom of ``edge_ids`` (top-down list)."""
        demand = units.nonnegative(delivery_m3, "delivery_m3")
        legs: list[RouteLeg] = []
        for eid in reversed(edge_ids):
            intake = demand / self.factor(eid, overrides)
            legs.append(RouteLeg(eid, intake, demand))
            demand = intake
        legs.reverse()
        return legs

    # ------------------------------------------------------------------ time

    def closed_seconds(self, edge_id: str, start: datetime, end: datetime) -> float:
        e = self.edges[edge_id]
        return sum(overlap_seconds(start, end, to_utc(c0), to_utc(c1)) for c0, c1 in e.closures)

    def capacity_m3(self, edge_id: str, start: datetime, end: datetime) -> float | None:
        """Max volume through the edge in [start, end); None = no declared limit.

        Declared capacity intervals give a rate over their span; portions of the
        interval outside any declared span carry no declared limit (None if the
        edge has no capacities at all). Closures are handled separately.
        """
        e = self.edges[edge_id]
        if not e.capacities:
            return None
        total = (end - start).total_seconds()
        covered = 0.0
        vol = 0.0
        for c in e.capacities:
            s = overlap_seconds(start, end, to_utc(c.start), to_utc(c.end))
            covered += s
            vol += c.max_rate_m3_s * s
        if covered + 1e-6 < total:
            return None
        return vol
