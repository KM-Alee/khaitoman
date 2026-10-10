"""Pilot package entities: geography, network, rights, assets, interventions (T3.4, T2.6)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from .base import PKR, ActionCategory, DeliveryFactor, Fraction, NonNegFloat, Sha256, StrictModel


class PackageState(StrEnum):
    acquired_raw = "acquired_raw"
    processed = "processed"
    needs_review = "needs_review"
    reviewed = "reviewed"
    validated = "validated"
    published = "published"


class ReviewFlags(StrictModel):
    """Independent flags; never collapse into one 'verified' badge (PRD §2.3)."""

    geography_reviewed: bool = False
    topology_structurally_valid: bool = False
    rights_verification: Literal["assumed", "configured", "verified"] = "assumed"
    cost_evidence: Literal["assumed", "referenced", "quoted"] = "assumed"
    crop_calibration: Literal["uncalibrated", "plausibility_checked", "calibrated"] = "uncalibrated"


class Pilot(StrictModel):
    pilot_id: str
    pilot_version: str
    name: str
    geographic_name_basis: str
    aoi_geojson_ref: str  # relative path inside the package
    aoi_bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)
    aoi_area_m2: NonNegFloat
    metric_crs: str  # e.g. EPSG:32643
    timezone: str = "Asia/Karachi"
    state: PackageState
    review_flags: ReviewFlags
    source_refs: list[str] = Field(default_factory=list)  # evidence ids
    imagery: list[ImageryRef] = Field(default_factory=list)
    package_sha256: Sha256 | None = None
    created_at: datetime
    # Additive (data stream): package-relative refs; None when absent.
    terrain_ref: str | None = None  # terrain/dem.json (Terrarium DEM metadata)
    weather_index_ref: str | None = None  # weather/index.json ([WeatherSeries])
    bundle_ref: str | None = None  # raw bundle the package was processed from


class ImageryRef(StrictModel):
    scene_id: str
    collection: str = "sentinel-2-l2a"
    acquired_at: datetime
    aoi_valid_fraction: Fraction
    display_image_ref: str  # PNG/WebP path
    display_corners_wgs84: list[tuple[float, float]]  # TL, TR, BR, BL for MapLibre ImageSource
    resolution_m: float = 10.0
    evidence_id: str


class Field_(StrictModel):
    """A reviewed field. Named Field_ to avoid shadowing pydantic.Field; exported as FieldRecord."""

    field_id: str
    label: str
    geometry_ref: str  # feature id in fields.geojson
    geometry_version: int = 1
    gross_area_m2: NonNegFloat
    gross_area_ha: NonNegFloat
    soil_profile_id: str
    outlet_node_id: str
    group: Literal["head", "middle", "tail"]
    owner_ref: str | None = None  # pseudonymous
    source_model_ids: list[str] = Field(default_factory=list)  # raw Delineate ids
    supersedes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    existing_application_efficiency: Fraction = 0.6


FieldRecord = Field_


class NodeKind(StrEnum):
    source = "source"
    junction = "junction"
    outlet = "outlet"
    pump = "pump"


class Node(StrictModel):
    node_id: str
    kind: NodeKind
    lon: float
    lat: float
    label: str | None = None


class CapacityInterval(StrictModel):
    start: datetime
    end: datetime
    max_rate_m3_s: NonNegFloat


class Edge(StrictModel):
    edge_id: str
    upstream_node_id: str
    downstream_node_id: str
    geometry_ref: str | None  # None => assumed connecting edge, rendered dashed
    source_feature_ids: list[str] = Field(default_factory=list)  # e.g. osm:way/123
    delivery_factor: DeliveryFactor
    capacities: list[CapacityInterval] = Field(default_factory=list)
    closures: list[tuple[datetime, datetime]] = Field(default_factory=list)
    reach_label: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class RightsBasis(StrEnum):
    time = "time"
    volume = "volume"


class RosterWindow(StrictModel):
    window_id: str
    field_id: str
    outlet_node_id: str
    start: datetime
    end: datetime
    basis: RightsBasis = RightsBasis.time
    rate_m3_s: NonNegFloat | None = None  # time basis
    volume_cap_m3: NonNegFloat | None = None  # volume basis
    accounting_boundary: Literal["outlet", "field_inlet"] = "outlet"
    verification: Literal["assumed", "configured", "verified"] = "assumed"
    source_rule: str


class ServiceReference(StrictModel):
    field_id: str
    season_id: str
    reference_receipt_m3: NonNegFloat  # fixed full-supply reference
    basis: RightsBasis
    evidence_ids: list[str] = Field(default_factory=list)


class AssetKind(StrEnum):
    pond = "pond"
    pump = "pump"


class Asset(StrictModel):
    asset_id: str
    kind: AssetKind
    existing: bool
    field_ids: list[str]  # accessible fields (shared pump => several)
    node_id: str | None = None  # injection point for pumps
    commissioned_at: date | None = None  # explicit for existing assets
    # pond
    usable_capacity_m3: NonNegFloat | None = None
    surface_area_m2: NonNegFloat | None = None
    footprint_m2: NonNegFloat | None = None
    initial_inventory_m3: NonNegFloat = 0.0
    max_fill_m3_day: NonNegFloat | None = None
    max_release_m3_day: NonNegFloat | None = None
    seepage_m3_day: NonNegFloat = 0.0
    k_evap: NonNegFloat = 1.0
    rain_capture_fraction: Fraction = 1.0
    # pump
    max_rate_m3_h: NonNegFloat | None = None
    seasonal_cap_m3: NonNegFloat | None = None
    cost_per_m3_pkr: str | None = None  # decimal string
    head_m: NonNegFloat | None = None
    efficiency: Fraction | None = None
    quality_status: Literal["unknown", "acceptable", "marginal", "poor"] = "unknown"
    annual_upkeep_pkr: PKR = 0
    evidence_ids: list[str] = Field(default_factory=list)


class InterventionType(StrictModel):
    type_id: str
    category: ActionCategory
    effect_model: str
    effect_model_version: str
    applicability_schema: dict[str, Any] = Field(default_factory=dict)
    required_parameters: list[str] = Field(default_factory=list)


class InterventionInstance(StrictModel):
    """E.g. `pilot-a:field-007:pond-small` or `pilot-a:edge-02:repair` (PRD §6.2)."""

    instance_id: str
    type_id: str
    category: ActionCategory
    target_ids: list[str]
    parameters: dict[str, Any] = Field(default_factory=dict)
    prerequisites: list[str] = Field(default_factory=list)
    mutually_exclusive_group: str | None = None
    capex_pkr: PKR = 0
    seasonal_opex_pkr: PKR = 0
    procurement_delay_days: int = Field(default=0, ge=0)
    lead_time_days: int = Field(default=0, ge=0)
    shared: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class ManifestFile(StrictModel):
    path: str  # relative, no traversal
    size_bytes: int = Field(ge=0)
    sha256: Sha256
    kind: str


class PilotManifest(StrictModel):
    manifest_version: Literal["1"] = "1"
    pilot_id: str
    pilot_version: str
    state: PackageState
    files: list[ManifestFile]
    source_ids: list[str]
    licenses: list[str]
    processing_versions: dict[str, str]
    generated_at: datetime


Pilot.model_rebuild()
