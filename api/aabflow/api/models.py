"""Public response/request models of the read-only pilot routes (extra=forbid)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from aabflow.domain.schemas import (
    ActionCategory,
    Asset,
    Edge,
    EvidenceRecord,
    FieldRecord,
    ImageryRef,
    InterventionInstance,
    Node,
    PackageState,
    PilotManifest,
    ReviewFlags,
    RosterWindow,
    Season,
    ServiceReference,
    SoilProfile,
    StrictModel,
    SupplyProfile,
    UncertaintySet,
    WeatherScenario,
)


class Health(StrictModel):
    status: Literal["ok", "degraded"]
    contract_version: str
    schema_version: str | None
    database: Literal["ok", "unavailable"]
    pilots_published: int
    libraries_ready: int
    workers: int
    dispatcher: Literal["running", "stopped"]
    versions: dict[str, str | None]


class FeatureStatus(StrictModel):
    status: Literal["available", "not_available", "partial", "blocked"]
    reason: str | None = None


class Capabilities(StrictModel):
    pilots: list[dict[str, str]]
    exact_science: bool
    surrogate_gate: str
    chat: dict[str, Any]
    features: dict[str, FeatureStatus]


class PilotSummary(StrictModel):
    pilot_id: str
    pilot_version: str
    name: str
    state: PackageState
    review_flags: ReviewFlags
    aoi_bbox: tuple[float, float, float, float]
    aoi_area_m2: float
    imagery: list[ImageryRef]
    versions: list[str]
    field_count: int


class PilotList(StrictModel):
    pilots: list[PilotSummary]


class PilotVersionDetail(StrictModel):
    pilot_id: str
    pilot_version: str
    name: str
    geographic_name_basis: str
    state: PackageState
    review_flags: ReviewFlags
    metric_crs: str
    timezone: str
    aoi_bbox: tuple[float, float, float, float]
    aoi_area_m2: float
    created_at: datetime
    package_sha256: str
    source_refs: list[str]
    imagery: list[ImageryRef]
    manifest: PilotManifest | None
    resource_status: Any = None
    counts: dict[str, int]
    seasons: list[str]


class MapImagery(StrictModel):
    scene_id: str
    acquired_at: datetime
    url: str
    corners: list[tuple[float, float]]
    evidence_id: str
    resolution_m: float
    aoi_valid_fraction: float
    ndvi_url: str | None = None


class MapTerrain(StrictModel):
    url: str
    bounds: tuple[float, float, float, float]
    encoding: str
    min_m: float | None = None
    max_m: float | None = None
    width: int | None = None
    height: int | None = None
    evidence_id: str | None = None


class LegendItem(StrictModel):
    key: str
    label: str
    style: str


class Legend(StrictModel):
    legend_id: str
    label: str
    items: list[LegendItem]


class PilotMap(StrictModel):
    pilot_id: str
    pilot_version: str
    aoi_bbox: tuple[float, float, float, float]
    aoi_url: str
    fields_url: str
    canals_url: str | None
    fields_raw_url: str | None
    imagery: list[MapImagery]
    terrain: MapTerrain | None
    network: dict[str, list[Node] | list[Edge]]
    assets: list[Asset]
    field_groups: dict[str, str]
    legends: list[Legend]


class InterventionEligibility(StrictModel):
    instance: InterventionInstance
    type_label: str | None
    category: ActionCategory
    commissioned_on: date | None
    eligible: bool
    reasons: list[str]
    in_library: bool | None


class FieldDetail(StrictModel):
    pilot_id: str
    pilot_version: str
    field: FieldRecord
    geometry: dict[str, Any] | None
    soil: SoilProfile | None
    assets: list[Asset]
    roster_windows: dict[str, list[RosterWindow]]
    service_references: list[ServiceReference]
    route_edge_ids: list[str]
    interventions: list[InterventionInstance]
    evidence_ids: list[str]


class SeasonEntry(StrictModel):
    season: Season
    library: dict[str, Any]
    roster_configured: bool


class SeasonList(StrictModel):
    seasons: list[SeasonEntry]


class WeatherScenarioList(StrictModel):
    weather_scenarios: list[WeatherScenario]


class UncertaintySetList(StrictModel):
    uncertainty_sets: list[UncertaintySet]
    supply_profiles: list[SupplyProfile]


class InterventionList(StrictModel):
    pilot_id: str
    pilot_version: str
    season_id: str | None
    decision_at: datetime | None
    planting_date: date | None
    interventions: list[InterventionEligibility]


class EvidenceHit(StrictModel):
    doc_id: str
    kind: str
    pilot_id: str | None
    title: str
    snippet: str
    source_url: str | None
    score: float


class EvidenceSearch(StrictModel):
    query: str
    results: list[EvidenceHit]


class EvidenceDetail(StrictModel):
    record: EvidenceRecord | None = None
    document: dict[str, Any] | None = None
    pilot_ids: list[str] = Field(default_factory=list)
