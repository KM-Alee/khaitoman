"""Read-only pilot routes (T9.1): pilots, map, fields, seasons, weather,
uncertainty sets, interventions, evidence, and validated static package assets."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from aabflow.api.errors import invalid, not_found
from aabflow.api.models import (
    EvidenceDetail,
    EvidenceSearch,
    FieldDetail,
    InterventionEligibility,
    InterventionList,
    Legend,
    LegendItem,
    MapImagery,
    MapTerrain,
    PilotList,
    PilotMap,
    PilotSummary,
    PilotVersionDetail,
    SeasonEntry,
    SeasonList,
    UncertaintySetList,
    WeatherScenarioList,
)
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.services import evidence as evidence_service
from aabflow.services.interventions import eligibility
from aabflow.services.pilots import CONTENT_TYPES, PilotPackage

router = APIRouter()
assets_router = APIRouter()

State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def asset_url(pkg: PilotPackage, rel: str) -> str:
    return f"/assets/pilots/{pkg.pilot_id}/{pkg.pilot_version}/{rel}"


def _exists(pkg: PilotPackage, rel: str) -> bool:
    return (pkg.directory / rel).is_file() and pkg.file_listed(rel)


def _summary(state: AppState, pkg: PilotPackage) -> PilotSummary:
    p = pkg.pilot
    return PilotSummary(
        pilot_id=pkg.pilot_id,
        pilot_version=pkg.pilot_version,
        name=p.name,
        state=p.state,
        review_flags=p.review_flags,
        aoi_bbox=p.aoi_bbox,
        aoi_area_m2=p.aoi_area_m2,
        imagery=p.imagery,
        versions=state.pilots.versions(pkg.pilot_id),
        field_count=len(pkg.fields),
    )


@router.get("/pilots", response_model=PilotList)
def list_pilots(state: State) -> PilotList:
    return PilotList(pilots=[_summary(state, pkg) for pkg in state.pilots.published()])


@router.get("/pilots/{pilot_id}/versions/{version}", response_model=PilotVersionDetail)
def pilot_version(pilot_id: str, version: str, state: State) -> PilotVersionDetail:
    pkg = state.pilots.package(pilot_id, version)
    p = pkg.pilot
    return PilotVersionDetail(
        pilot_id=pkg.pilot_id,
        pilot_version=pkg.pilot_version,
        name=p.name,
        geographic_name_basis=p.geographic_name_basis,
        state=p.state,
        review_flags=p.review_flags,
        metric_crs=p.metric_crs,
        timezone=p.timezone,
        aoi_bbox=p.aoi_bbox,
        aoi_area_m2=p.aoi_area_m2,
        created_at=p.created_at,
        package_sha256=pkg.package_hash,
        source_refs=p.source_refs,
        imagery=p.imagery,
        manifest=pkg.manifest,
        resource_status=pkg.resource_status,
        counts={
            "fields": len(pkg.fields),
            "nodes": len(pkg.nodes),
            "edges": len(pkg.edges),
            "assets": len(pkg.assets),
            "intervention_instances": len(pkg.instances),
            "evidence_records": len(pkg.evidence),
        },
        seasons=sorted(pkg.roster),
    )


LEGENDS = [
    Legend(
        legend_id="canals",
        label="Canal network",
        items=[
            LegendItem(key="observed", label="Observed canal geometry (OSM/GRAIN)", style="solid"),
            LegendItem(
                key="assumed",
                label="Assumed operational connection (no observed geometry)",
                style="dashed",
            ),
        ],
    ),
    Legend(
        legend_id="field_groups",
        label="Field position on the watercourse",
        items=[
            LegendItem(key="head", label="Head", style="group-head"),
            LegendItem(key="middle", label="Middle", style="group-middle"),
            LegendItem(key="tail", label="Tail", style="group-tail"),
        ],
    ),
    Legend(
        legend_id="assets",
        label="Assets",
        items=[
            LegendItem(key="existing", label="Existing asset", style="filled"),
            LegendItem(key="proposed", label="Proposed intervention site", style="outline"),
        ],
    ),
    Legend(
        legend_id="imagery",
        label="Imagery",
        items=[
            LegendItem(
                key="sentinel2",
                label="Sentinel-2 L2A display stretch, 10 m source resolution (not reflectance)",
                style="raster",
            )
        ],
    ),
]


@router.get("/pilots/{pilot_id}/versions/{version}/map", response_model=PilotMap)
def pilot_map(pilot_id: str, version: str, state: State) -> PilotMap:
    pkg = state.pilots.package(pilot_id, version)
    p = pkg.pilot
    imagery = []
    for img in p.imagery:
        side = pkg.imagery_corners.get(img.scene_id) or {}
        corners = side.get("corners_wgs84") or img.display_corners_wgs84
        ndvi_rel = f"imagery/{img.scene_id}.ndvi.json"
        imagery.append(
            MapImagery(
                scene_id=img.scene_id,
                acquired_at=img.acquired_at,
                url=asset_url(pkg, img.display_image_ref),
                corners=[tuple(c) for c in corners],
                evidence_id=img.evidence_id,
                resolution_m=img.resolution_m,
                aoi_valid_fraction=img.aoi_valid_fraction,
                ndvi_url=asset_url(pkg, ndvi_rel) if _exists(pkg, ndvi_rel) else None,
            )
        )
    terrain = None
    if pkg.terrain:
        t = pkg.terrain
        rel = t.get("image_ref", "terrain/dem.png")
        terrain = MapTerrain(
            url=asset_url(pkg, rel),
            bounds=tuple(t["bounds"]),
            encoding=t.get("encoding", "terrarium"),
            min_m=t.get("min_m"),
            max_m=t.get("max_m"),
            width=t.get("width"),
            height=t.get("height"),
            evidence_id=t.get("evidence_id"),
        )
    return PilotMap(
        pilot_id=pkg.pilot_id,
        pilot_version=pkg.pilot_version,
        aoi_bbox=p.aoi_bbox,
        aoi_url=asset_url(pkg, p.aoi_geojson_ref),
        fields_url=asset_url(pkg, "fields.geojson"),
        canals_url=asset_url(pkg, "canals.geojson") if _exists(pkg, "canals.geojson") else None,
        fields_raw_url=asset_url(pkg, "fields_raw.geojson")
        if _exists(pkg, "fields_raw.geojson")
        else None,
        imagery=imagery,
        terrain=terrain,
        network={"nodes": list(pkg.nodes.values()), "edges": list(pkg.edges.values())},
        assets=list(pkg.assets.values()),
        field_groups={fid: f.group for fid, f in pkg.fields.items()},
        legends=LEGENDS,
    )


@router.get("/fields/{field_id}", response_model=FieldDetail)
def field_detail(
    field_id: str,
    state: State,
    pilot_version: str | None = None,
    pilot_id: str | None = None,
) -> FieldDetail:
    pkg = state.pilots.find_field(field_id, pilot_id, pilot_version)
    f = pkg.fields[field_id]
    windows = {sid: [w for w in ws if w.field_id == field_id] for sid, ws in pkg.roster.items()}
    assets = [a for a in pkg.assets.values() if field_id in a.field_ids]
    interventions = [
        i
        for i in pkg.instances.values()
        if field_id in i.target_ids or any(a.asset_id in i.target_ids for a in assets)
    ]
    route = pkg.route_edge_ids(field_id)
    for eid in route:
        interventions += [
            i for i in pkg.instances.values() if eid in i.target_ids and i not in interventions
        ]
    feat = pkg.field_features.get(field_id)
    ev = set(f.evidence_ids)
    for a in assets:
        ev.update(a.evidence_ids)
    return FieldDetail(
        pilot_id=pkg.pilot_id,
        pilot_version=pkg.pilot_version,
        field=f,
        geometry=feat.get("geometry") if feat else None,
        soil=pkg.soils.get(f.soil_profile_id),
        assets=assets,
        roster_windows=windows,
        service_references=[r for r in pkg.service_references if r.field_id == field_id],
        route_edge_ids=route,
        interventions=interventions,
        evidence_ids=sorted(ev),
    )


@router.get("/seasons", response_model=SeasonList)
def seasons(
    state: State, pilot_id: str | None = None, pilot_version: str | None = None
) -> SeasonList:
    pkg = state.pilots.package(pilot_id, pilot_version) if pilot_id else None
    out = []
    for s in state.catalog.seasons():
        lib = (
            state.catalog.library_summary(pilot_id, s.season_id)
            if pilot_id
            else {"ready": False, "reason": "pass pilot_id for library readiness"}
        )
        out.append(
            SeasonEntry(
                season=s, library=lib, roster_configured=bool(pkg and pkg.roster.get(s.season_id))
            )
        )
    return SeasonList(seasons=out)


@router.get("/weather-scenarios", response_model=WeatherScenarioList)
def weather_scenarios(
    state: State, pilot_id: str | None = None, season_id: str | None = None
) -> WeatherScenarioList:
    if pilot_id:
        state.pilots.package(pilot_id)
    if season_id and state.catalog.season(season_id) is None:
        raise not_found("season_id", season_id)
    return WeatherScenarioList(
        weather_scenarios=state.catalog.weather_scenarios(pilot_id, season_id)
    )


@router.get("/uncertainty-sets", response_model=UncertaintySetList)
def uncertainty_sets(
    state: State, pilot_id: str | None = None, season_id: str | None = None
) -> UncertaintySetList:
    if pilot_id:
        state.pilots.package(pilot_id)
    if season_id and state.catalog.season(season_id) is None:
        raise not_found("season_id", season_id)
    profiles = state.catalog.supply_profiles(pilot_id, season_id) if season_id else []
    return UncertaintySetList(
        uncertainty_sets=state.catalog.uncertainty_sets(pilot_id, season_id),
        supply_profiles=profiles,
    )


@router.get("/interventions", response_model=InterventionList)
def interventions(
    state: State,
    pilot_id: str,
    season_id: str | None = None,
    pilot_version: str | None = None,
    decision_at: datetime | None = None,
) -> InterventionList:
    pkg = state.pilots.package(pilot_id, pilot_version)
    season = None
    if season_id:
        season = state.catalog.season(season_id)
        if season is None:
            raise not_found("season_id", season_id)
    if decision_at is not None and decision_at.tzinfo is None:
        raise invalid("decision_at must include a UTC offset", {"decision_at": "naive timestamp"})
    when = decision_at or (season.decision_at if season else None)
    planting = (season.planting_date or season.start) if season else None
    excluded: dict[str, str] = {}
    in_library: set[str] | None = None
    if season_id and state.catalog.latest_library_hash(pilot_id, season_id):
        excluded, in_library = _library_instances(state, pilot_id, season_id)
    out = []
    for inst in sorted(pkg.instances.values(), key=lambda i: i.instance_id):
        on, reasons = eligibility(pkg, inst, when, planting)
        if inst.instance_id in excluded and excluded[inst.instance_id] not in reasons:
            reasons.append(f"candidate library: {excluded[inst.instance_id]}")
        t = pkg.intervention_types.get(inst.type_id)
        out.append(
            InterventionEligibility(
                instance=inst,
                type_label=t.effect_model if t else None,
                category=inst.category,
                commissioned_on=on,
                eligible=not reasons,
                reasons=reasons,
                in_library=None if in_library is None else inst.instance_id in in_library,
            )
        )
    return InterventionList(
        pilot_id=pkg.pilot_id,
        pilot_version=pkg.pilot_version,
        season_id=season_id,
        decision_at=when,
        planting_date=planting,
        interventions=out,
    )


def _library_instances(
    state: AppState, pilot_id: str, season_id: str
) -> tuple[dict[str, str], set[str]]:
    import json

    h = state.catalog.latest_library_hash(pilot_id, season_id)
    d = state.catalog.root / pilot_id / season_id / h
    lib = json.loads((d / "library.json").read_text())
    used: set[str] = set()
    for c in lib.get("configurations", []):
        used.update(c.get("repair_instance_ids", []))
    pol = d / "policies.jsonl"
    if pol.exists():
        with pol.open() as fh:
            for line in fh:
                if '"required_instance_ids"' in line:
                    used.update(json.loads(line).get("required_instance_ids", []))
    return lib.get("excluded_instances", {}) or {}, used


@router.get("/evidence/search", response_model=EvidenceSearch)
def evidence_search(
    state: State,
    conn: Conn,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    pilot_id: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=evidence_service.MAX_RESULTS)] = 10,
) -> EvidenceSearch:
    evidence_service.ensure_index(conn, state.pilots)
    return EvidenceSearch(
        query=q, results=evidence_service.search(conn, q, pilot_id=pilot_id, kind=kind, limit=limit)
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceDetail)
def evidence_detail(evidence_id: str, state: State, conn: Conn) -> EvidenceDetail:
    holders = [pkg for pkg in state.pilots.published() if evidence_id in pkg.evidence]
    if holders:
        return EvidenceDetail(
            record=holders[-1].evidence[evidence_id], pilot_ids=[p.pilot_id for p in holders]
        )
    evidence_service.ensure_index(conn, state.pilots)
    row = conn.execute(
        "SELECT doc_id, kind, pilot_id, title, body, source_url FROM evidence_fts WHERE doc_id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise not_found("evidence_id", evidence_id)
    return EvidenceDetail(
        document=dict(row), pilot_ids=[row["pilot_id"]] if row["pilot_id"] else []
    )


@assets_router.get("/assets/pilots/{pilot_id}/{version}/{rel:path}", include_in_schema=False)
def pilot_asset(pilot_id: str, version: str, rel: str, state: State) -> FileResponse:
    path = state.pilots.asset_path(pilot_id, version, rel)
    return FileResponse(
        path,
        media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
