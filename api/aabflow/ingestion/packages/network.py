"""Declared operational graph (T2.3, T4.2-T4.3, PRD §6.1).

The graph is a reviewed *assumption* built separately from the observed canal
features: geometric intersections never become hydraulic junctions automatically.

Layout per pilot (``NETWORK_TEMPLATE``)::

    source ──(observed parent-canal reach, geometry_ref=osm:way/…)──▶ bifurcation
    bifurcation ──(assumed)──▶ mogha WC1 ──reach 1──▶ head ──reach 2──▶ middle ──reach 3──▶ tail
    bifurcation ──(assumed)──▶ mogha WC2 ──reach 1──▶ head ──reach 2──▶ middle ──reach 3──▶ tail

Each watercourse has three reaches with distinct delivery factors, so a repair
on a downstream reach measurably changes tail receipts (review/CHANGES.md #1).
Field ``outlet_node_id`` is the outlet node of its reach group; the roster cap is
accounted at the watercourse head (mogha).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points

from aabflow.domain.schemas import CapacityInterval, Edge, Node, NodeKind

from ..aoi import to_metric, to_wgs84

NETWORK_TEMPLATE = "two-watercourse-three-reach-v1"
GROUPS = ("head", "middle", "tail")


@dataclass(frozen=True)
class WatercourseParams:
    """Assumed reach delivery factors (fractional-loss model, uncalibrated)."""

    mogha_factor: float  # bifurcation -> mogha (short distributary reach)
    reach_factors: tuple[float, float, float]  # mogha->head, head->middle, middle->tail


DEFAULT_WATERCOURSES = (
    WatercourseParams(0.98, (0.93, 0.86, 0.79)),  # earthen, unlined
    WatercourseParams(0.98, (0.95, 0.90, 0.84)),  # partly lined head reach
)
SOURCE_FACTOR = 0.97  # observed parent canal reach to the bifurcation
FACTOR_RANGES = {"watercourse_reach": (0.70, 0.97), "parent_canal": (0.93, 0.99)}


@dataclass
class FieldSite:
    field_id: str
    centroid_lonlat: tuple[float, float]
    area_m2: float


@dataclass
class NetworkBuild:
    nodes: list[Node]
    edges: list[Edge]
    field_outlet: dict[str, str]  # field_id -> outlet node
    field_group: dict[str, str]  # field_id -> head/middle/tail
    field_watercourse: dict[str, str]  # field_id -> watercourse id
    mogha_of: dict[str, str]  # watercourse id -> mogha node id
    watercourse_fields: dict[str, list[str]]  # ordered head -> tail
    reach_edges: dict[str, list[str]]  # watercourse id -> [reach1, reach2, reach3]
    source_edge_id: str
    parent_feature_id: str
    notes: list[str]


def _pid(pilot_id: str, kind: str, name: str) -> str:
    return f"{pilot_id}:{kind}-{name}"


def split_watercourses(sites: list[FieldSite], crs, n: int = 2) -> list[list[FieldSite]]:
    """Split fields into ``n`` contiguous command areas along their principal axis."""
    pts = np.array([to_metric(Point(s.centroid_lonlat), crs).coords[0] for s in sites])
    c = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    proj = c @ vt[0]
    order = np.argsort(proj, kind="stable")
    size = math.ceil(len(sites) / n)
    return [[sites[i] for i in order[k * size : (k + 1) * size]] for k in range(n)]


def build_network(
    pilot_id: str,
    sites: list[FieldSite],
    parent_canal: dict,  # observed canal GeoJSON feature (EPSG:4326)
    crs,
    season_closures: list[tuple[datetime, datetime]],
    source_capacity: list[CapacityInterval] | None = None,
    watercourses: tuple[WatercourseParams, ...] = DEFAULT_WATERCOURSES,
    evidence_ids: dict[str, list[str]] | None = None,
) -> NetworkBuild:
    ev = evidence_ids or {}
    canal_m: LineString = to_metric(shape(parent_canal["geometry"]), crs)
    groups = split_watercourses(sites, crs, n=len(watercourses))
    nodes: list[Node] = []
    edges: list[Edge] = []
    field_outlet: dict[str, str] = {}
    field_group: dict[str, str] = {}
    field_wc: dict[str, str] = {}
    mogha_of: dict[str, str] = {}
    wc_fields: dict[str, list[str]] = {}
    reach_edges: dict[str, list[str]] = defaultdict(list)

    def node(nid: str, kind: NodeKind, xy_m, label: str) -> str:
        lon, lat = to_wgs84(Point(xy_m), crs).coords[0]
        nodes.append(Node(node_id=nid, kind=kind, lon=round(lon, 7), lat=round(lat, 7), label=label))
        return nid

    # Moghas: nearest point on the observed parent canal to each command area.
    mogha_pts = []
    for grp in groups:
        cm = np.mean([to_metric(Point(s.centroid_lonlat), crs).coords[0] for s in grp], axis=0)
        mogha_pts.append(nearest_points(canal_m, Point(cm))[0])
    dists = [canal_m.project(p) for p in mogha_pts]
    first = min(dists)
    # Source node upstream along the observed canal (direction = digitized order,
    # recorded as an assumption; slope does not verify flow direction, T4.2).
    src_d = max(0.0, first - 600.0)
    bif_d = max(src_d + 1.0, first - 150.0)
    src = node(_pid(pilot_id, "node", "source"), NodeKind.source, canal_m.interpolate(src_d).coords[0],
               "Parent canal intake point (assumed)")  # fmt: skip
    bif = node(_pid(pilot_id, "node", "bifurcation"), NodeKind.junction,
               canal_m.interpolate(bif_d).coords[0], "Parent canal junction above moghas (assumed)")  # fmt: skip
    parent_id = parent_canal["properties"]["source_feature_id"]
    source_edge = _pid(pilot_id, "edge", "parent-canal")
    edges.append(
        Edge(
            edge_id=source_edge,
            upstream_node_id=src,
            downstream_node_id=bif,
            geometry_ref=parent_id,
            source_feature_ids=[parent_id],
            delivery_factor=SOURCE_FACTOR,
            capacities=source_capacity or [],
            closures=season_closures,
            reach_label="Parent canal reach (observed geometry)",
            evidence_ids=ev.get("parent", []),
        )
    )
    for k, (grp, params, mp) in enumerate(zip(groups, watercourses, mogha_pts, strict=True), 1):
        wc = f"wc{k}"
        mogha = node(_pid(pilot_id, "node", f"{wc}-mogha"), NodeKind.outlet, mp.coords[0],
                     f"Watercourse {k} head (mogha), assumed")  # fmt: skip
        mogha_of[wc] = mogha
        edges.append(
            Edge(
                edge_id=_pid(pilot_id, "edge", f"{wc}-offtake"),
                upstream_node_id=bif,
                downstream_node_id=mogha,
                geometry_ref=parent_id,
                source_feature_ids=[parent_id],
                delivery_factor=params.mogha_factor,
                reach_label=f"Parent canal to WC{k} mogha (observed canal, assumed offtake)",
                evidence_ids=ev.get("parent", []),
            )
        )
        # Order fields by distance from the mogha; thirds -> head/middle/tail.
        order = sorted(grp, key=lambda s: (mp.distance(to_metric(Point(s.centroid_lonlat), crs)), s.field_id))
        wc_fields[wc] = [s.field_id for s in order]
        thirds = np.array_split(np.arange(len(order)), 3)
        prev = mogha
        for gi, (gname, idx) in enumerate(zip(GROUPS, thirds, strict=True)):
            members = [order[i] for i in idx]
            cxy = np.mean([to_metric(Point(s.centroid_lonlat), crs).coords[0] for s in members], axis=0)
            out = node(_pid(pilot_id, "node", f"{wc}-{gname}"), NodeKind.outlet, tuple(cxy),
                       f"WC{k} {gname} outlet (assumed)")  # fmt: skip
            eid = _pid(pilot_id, "edge", f"{wc}-reach{gi + 1}")
            edges.append(
                Edge(
                    edge_id=eid,
                    upstream_node_id=prev,
                    downstream_node_id=out,
                    geometry_ref=None,
                    source_feature_ids=[],
                    delivery_factor=params.reach_factors[gi],
                    reach_label=f"WC{k} reach {gi + 1} ({gname}), assumed earthen watercourse",
                    evidence_ids=ev.get("reach", []),
                )
            )
            reach_edges[wc].append(eid)
            for s in members:
                field_outlet[s.field_id] = out
                field_group[s.field_id] = gname
                field_wc[s.field_id] = wc
            prev = out
    notes = [
        "Graph is a declared operational assumption; watercourse reaches are not in OSM "
        "and have geometry_ref=null (rendered dashed).",
        f"Parent canal geometry {parent_id} is observed; flow direction along it is assumed.",
        "Moghas are placed at the nearest parent-canal point to each command area (assumption).",
    ]
    return NetworkBuild(
        nodes=nodes,
        edges=edges,
        field_outlet=field_outlet,
        field_group=field_group,
        field_watercourse=field_wc,
        mogha_of=mogha_of,
        watercourse_fields=wc_fields,
        reach_edges=dict(reach_edges),
        source_edge_id=source_edge,
        parent_feature_id=parent_id,
        notes=notes,
    )


def reach_length_m(edge: Edge, nodes: dict[str, Node], crs) -> float:
    a, b = nodes[edge.upstream_node_id], nodes[edge.downstream_node_id]
    pa = to_metric(Point(a.lon, a.lat), crs)
    pb = to_metric(Point(b.lon, b.lat), crs)
    return float(pa.distance(pb))


def path_factor(edges: list[Edge], from_node: str, to_node: str) -> float:
    """Product of delivery factors along the unique path from ``from_node`` down to ``to_node``."""
    up = {e.downstream_node_id: e for e in edges}
    f = 1.0
    cur = to_node
    while cur != from_node:
        e = up.get(cur)
        if e is None:
            raise ValueError(f"{to_node} is not downstream of {from_node}")
        f *= e.delivery_factor
        cur = e.upstream_node_id
    return f
