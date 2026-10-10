"""Field-boundary review of raw Delineate output (PRD §5.2, T2.4 steps 6-7).

Every raw polygon receives one review decision with reasons; geometry checks run
in the pilot's metric CRS (never degrees²). The 30 reviewed fields are chosen from
the eligible candidates by a recorded quality ranking, and stable reviewed ids are
mapped back to the original model ids in a correction log.

Rules (``REVIEW_RULES_VERSION``):

* validity: invalid rings are repaired with ``make_valid`` (action ``repaired_invalid``);
* multipart: minor parts (<5 % of the largest) are dropped (``dropped_minor_parts``),
  otherwise the polygon is rejected as a probable merge;
* AOI: ≥98 % inside is clipped to the AOI (``clipped_to_aoi``), less is rejected;
* area: ``min_area_m2`` ≤ area ≤ ``max_area_m2`` (small parcels at 10 m are unreliable,
  very large ones are usually merged fields);
* slivers: Polsby-Popper compactness ≥ ``min_compactness`` and minimum rotated-rectangle
  width ≥ ``min_width_m``;
* holes smaller than ``fill_hole_m2`` are filled (``holes_filled``);
* overlaps: a pair overlapping more than ``overlap_tolerance`` of the smaller polygon
  is resolved by subtracting the overlap from the lower-ranked polygon
  (``overlap_clipped``); smaller overlaps are also removed the same way;
* manual edits supplied by a reviewer (``ManualEdit``) are applied last and logged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import shapely
from pyproj import CRS
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.validation import explain_validity, make_valid

from ..aoi import Aoi, to_metric, to_wgs84

REVIEW_RULES_VERSION = "field-review-rules-1.1.0"


@dataclass(frozen=True)
class ReviewConfig:
    target_count: int = 30
    # 0.5 ha: Punjab parcels are ~0.4 ha (one killa); ≥1 ha preferred via the ranking.
    min_area_m2: float = 5_000.0
    max_area_m2: float = 150_000.0
    # Polsby-Popper of a pixel-staircase strip parcel is ~0.3-0.5; slivers are caught by
    # width and rectangularity.
    min_compactness: float = 0.30
    min_width_m: float = 45.0
    min_rectangularity: float = 0.70
    fill_hole_m2: float = 1_500.0
    minor_part_fraction: float = 0.05
    aoi_inside_fraction: float = 0.98
    overlap_tolerance: float = 0.01
    edge_buffer_m: float = 0.0


@dataclass
class ManualEdit:
    """A reviewer correction applied to a raw model polygon (logged verbatim)."""

    model_id: str
    action: Literal["reject", "replace_geometry", "split", "merge_with"]
    reason: str
    geometry_wgs84: dict | None = None  # for replace_geometry
    parts_wgs84: list[dict] | None = None  # for split
    other_model_ids: list[str] = field(default_factory=list)  # for merge_with


@dataclass
class Candidate:
    model_id: str
    geom_m: Any  # metric polygon
    actions: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    rejected: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    source_model_ids: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejected = True
        self.reasons.append(reason)


def polsby_popper(g) -> float:
    p = g.length
    return 0.0 if p == 0 else 4 * math.pi * g.area / (p * p)


def rect_metrics(g) -> tuple[float, float, float]:
    """(min width m, length m, rectangularity = area / min rotated rectangle area)."""
    mrr = g.minimum_rotated_rectangle
    if mrr.geom_type != "Polygon":
        return 0.0, 0.0, 0.0
    xs = list(mrr.exterior.coords)
    e1 = math.dist(xs[0], xs[1])
    e2 = math.dist(xs[1], xs[2])
    rect = 0.0 if mrr.area == 0 else g.area / mrr.area
    return min(e1, e2), max(e1, e2), rect


def fill_small_holes(poly: Polygon, max_hole_m2: float) -> tuple[Polygon, int]:
    keep = [r for r in poly.interiors if Polygon(r).area >= max_hole_m2]
    filled = len(poly.interiors) - len(keep)
    return Polygon(poly.exterior, keep), filled


def largest_polygon(g) -> tuple[Polygon | None, float]:
    """Largest polygonal part and the fraction of area in the other parts."""
    if g.is_empty:
        return None, 0.0
    if g.geom_type == "Polygon":
        return g, 0.0
    polys = [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    for p in getattr(g, "geoms", []):
        if p.geom_type == "MultiPolygon":
            polys.extend(p.geoms)
    if not polys:
        return None, 0.0
    polys.sort(key=lambda p: p.area, reverse=True)
    total = sum(p.area for p in polys)
    return polys[0], (total - polys[0].area) / total if total else 0.0


def check_geometry(c: Candidate, aoi_m, cfg: ReviewConfig) -> None:
    g = c.geom_m
    if g.is_empty:
        c.reject("empty geometry")
        return
    if not g.is_valid:
        c.reasons.append(f"invalid: {explain_validity(g)}")
        g = make_valid(g)
        c.actions.append("repaired_invalid")
    if g.geom_type not in ("Polygon",):
        poly, minor = largest_polygon(g)
        if poly is None:
            c.reject(f"no polygonal part ({g.geom_type})")
            return
        if minor > cfg.minor_part_fraction:
            c.reject(
                f"multipart with {minor:.0%} of area outside the largest part (probable merge)"
            )
            return
        if minor > 0:
            c.actions.append("dropped_minor_parts")
            c.reasons.append(f"dropped minor parts ({minor:.1%} of area)")
        g = poly
    inside = g.intersection(aoi_m).area / g.area if g.area else 0.0
    c.metrics["aoi_inside_fraction"] = round(inside, 4)
    if inside < cfg.aoi_inside_fraction:
        c.reject(f"only {inside:.0%} inside the AOI")
        return
    if inside < 1.0:
        g, _ = largest_polygon(g.intersection(aoi_m))
        c.actions.append("clipped_to_aoi")
    g, filled = fill_small_holes(g, cfg.fill_hole_m2)
    if filled:
        c.actions.append("holes_filled")
        c.reasons.append(f"filled {filled} hole(s) < {cfg.fill_hole_m2:.0f} m²")
    c.geom_m = g
    measure(c)
    if c.metrics["area_m2"] < cfg.min_area_m2:
        c.reject(
            f"area {c.metrics['area_m2']:.0f} m² < {cfg.min_area_m2:.0f} m² (unreliable at 10 m)"
        )
    elif c.metrics["area_m2"] > cfg.max_area_m2:
        c.reject(
            f"area {c.metrics['area_m2']:.0f} m² > {cfg.max_area_m2:.0f} m² (probable merged fields)"
        )
    elif c.metrics["compactness"] < cfg.min_compactness:
        c.reject(
            f"sliver/irregular: compactness {c.metrics['compactness']:.2f} < {cfg.min_compactness}"
        )
    elif c.metrics["min_width_m"] < cfg.min_width_m:
        c.reject(f"sliver: width {c.metrics['min_width_m']:.0f} m < {cfg.min_width_m:.0f} m")
    elif c.metrics["rectangularity"] < cfg.min_rectangularity:
        c.reject(
            f"irregular outline: rectangularity {c.metrics['rectangularity']:.2f} < {cfg.min_rectangularity}"
        )


def measure(c: Candidate) -> None:
    g = c.geom_m
    w, length, rect = rect_metrics(g)
    c.metrics.update(
        {
            "area_m2": round(g.area, 2),
            "perimeter_m": round(g.length, 2),
            "compactness": round(polsby_popper(g), 4),
            "min_width_m": round(w, 2),
            "length_m": round(length, 2),
            "rectangularity": round(rect, 4),
            "holes": len(g.interiors),
        }
    )
    c.metrics["quality"] = round(
        0.5 * c.metrics["rectangularity"]
        + 0.3 * min(1.0, c.metrics["compactness"] / 0.785)
        + 0.2 * min(1.0, math.log10(max(g.area, 1)) / 5.0),
        4,
    )


def resolve_overlaps(cands: list[Candidate], cfg: ReviewConfig) -> int:
    """Subtract each overlap from the lower-quality polygon. Returns pairs resolved."""
    live = [c for c in cands if not c.rejected]
    live.sort(key=lambda c: c.metrics.get("quality", 0), reverse=True)
    tree = shapely.STRtree([c.geom_m for c in live])
    n = 0
    for i, c in enumerate(live):
        if c.rejected:
            continue
        for j in tree.query(c.geom_m, predicate="intersects"):
            if j <= i:
                continue
            o = live[j]
            if o.rejected:
                continue
            inter = c.geom_m.intersection(o.geom_m)
            if inter.area <= 1e-6:
                continue
            frac = inter.area / min(c.geom_m.area, o.geom_m.area)
            n += 1
            clipped, _ = largest_polygon(o.geom_m.difference(c.geom_m))
            o.actions.append("overlap_clipped")
            o.reasons.append(f"overlap with {c.model_id} ({frac:.1%} of smaller) removed")
            if clipped is None or frac > 0.5:
                o.reject(f"overlaps {c.model_id} by {frac:.0%} (duplicate detection)")
                continue
            o.geom_m = clipped
            measure(o)
            if o.metrics["area_m2"] < cfg.min_area_m2 or o.metrics["min_width_m"] < cfg.min_width_m:
                o.reject("too small after overlap removal")
    return n


@dataclass
class ReviewResult:
    selected: list[Candidate]
    all: list[Candidate]
    log: list[dict]
    summary: dict


def apply_manual_edits(cands: dict[str, Candidate], edits: list[ManualEdit], crs: CRS) -> None:
    for e in edits:
        c = cands.get(e.model_id)
        if c is None:
            raise ValueError(f"manual edit references unknown model id {e.model_id}")
        c.reasons.append(f"manual: {e.reason}")
        if e.action == "reject":
            c.reject(f"manual rejection: {e.reason}")
        elif e.action == "replace_geometry":
            c.geom_m = to_metric(shape(e.geometry_wgs84), crs)
            c.actions.append("manual_replace_geometry")
            measure(c)
        elif e.action == "merge_with":
            geoms = [c.geom_m] + [cands[m].geom_m for m in e.other_model_ids]
            c.geom_m = shapely.union_all(geoms)
            c.source_model_ids += e.other_model_ids
            for m in e.other_model_ids:
                cands[m].reject(f"merged into {e.model_id}")
            c.actions.append("manual_merge")
            measure(c)
        elif e.action == "split":
            c.reject(f"split by reviewer: {e.reason}")
            for k, part in enumerate(e.parts_wgs84 or []):
                nid = f"{e.model_id}#split{k + 1}"
                nc = Candidate(nid, to_metric(shape(part), crs), source_model_ids=[e.model_id])
                nc.actions.append("manual_split_part")
                measure(nc)
                cands[nid] = nc


def review(
    raw_fc: dict,
    aoi: Aoi,
    cfg: ReviewConfig | None = None,
    manual_edits: list[ManualEdit] | None = None,
    exclusion_wgs84: list | None = None,
) -> ReviewResult:
    """Review raw model polygons and select ``cfg.target_count`` fields.

    ``exclusion_wgs84``: optional geometries (e.g. buffered canal lines) that
    reviewed fields must not intersect.
    """
    cfg = cfg or ReviewConfig()
    crs = aoi.metric_crs
    aoi_m = aoi.metric_geometry
    excl = [to_metric(g, crs) for g in (exclusion_wgs84 or [])]
    cands: dict[str, Candidate] = {}
    for f in raw_fc["features"]:
        mid = str(f.get("id") or f["properties"]["model_id"])
        if mid in cands:
            raise ValueError(f"duplicate raw model id {mid}")
        g = to_metric(shape(f["geometry"]), crs)
        cands[mid] = Candidate(mid, g, source_model_ids=[mid])
    for c in cands.values():
        check_geometry(c, aoi_m, cfg)
        if not c.rejected and excl:
            for x in excl:
                if c.geom_m.intersects(x):
                    c.reject("intersects mapped canal corridor")
                    break
    if manual_edits:
        apply_manual_edits(cands, manual_edits, crs)
    n_overlaps = resolve_overlaps(list(cands.values()), cfg)

    eligible = [c for c in cands.values() if not c.rejected]
    eligible.sort(key=lambda c: (-c.metrics["quality"], c.model_id))
    if len(eligible) < cfg.target_count:
        raise ValueError(
            f"only {len(eligible)} eligible fields after review; {cfg.target_count} required"
        )
    selected = eligible[: cfg.target_count]
    sel_ids = {c.model_id for c in selected}
    log = []
    for rank, c in enumerate(eligible, start=1):
        c.metrics["rank"] = rank
    for c in sorted(cands.values(), key=lambda c: c.model_id):
        if c.rejected:
            decision = "rejected"
        elif c.model_id in sel_ids:
            decision = "corrected" if c.actions else "accepted"
        else:
            decision = "eligible_not_selected"
        log.append(
            {
                "model_id": c.model_id,
                "source_model_ids": c.source_model_ids,
                "decision": decision,
                "actions": c.actions,
                "reasons": c.reasons,
                "metrics": c.metrics,
            }
        )
    corrected = sum(1 for c in selected if c.actions)
    summary = {
        "rules_version": REVIEW_RULES_VERSION,
        "config": vars(cfg),
        "raw_polygons": len(cands),
        "rejected": sum(1 for c in cands.values() if c.rejected),
        "eligible": len(eligible),
        "selected": len(selected),
        "selected_corrected": corrected,
        "selected_correction_rate": round(corrected / len(selected), 4),
        "overlap_pairs_resolved": n_overlaps,
        "manual_edits": len(manual_edits or []),
        "selection_method": "top-ranked eligible polygons by quality score "
        "(0.5·rectangularity + 0.3·compactness/0.785 + 0.2·log10(area)/5)",
        "accuracy_metrics": "not_estimated: no independent reference boundaries",
    }
    return ReviewResult(selected=selected, all=list(cands.values()), log=log, summary=summary)


def selected_wgs84(c: Candidate, crs: CRS) -> dict:
    g = to_wgs84(c.geom_m, crs)
    if isinstance(g, MultiPolygon):  # pragma: no cover - review guarantees Polygon
        raise TypeError("reviewed field must be a single polygon")
    return mapping(g)
