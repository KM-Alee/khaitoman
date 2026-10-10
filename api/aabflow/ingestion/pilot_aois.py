"""Reviewed pilot AOI definitions and the evidence behind their selection (T2.2).

Both AOIs lie inside the published Mungi literature search extent
[72.133333, 30.55, 72.8, 31.033333], are disjoint, ≤25 km², agricultural, and have
mapped canal context in OpenStreetMap. A bounded Overpass search of the whole
extent (2026-10-09) found no waterway named Mungi, so neither pilot is called
Mungi; they are named "Lower Chenab representative pilot A/B" (PRD §2.1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PilotAoi:
    pilot_id: str
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    parent_canal_osm_way: int  # observed canal feeding the declared graph
    geographic_name_basis: str
    selection_rationale: str


PILOT_A = PilotAoi(
    pilot_id="pilot-a",
    name="Lower Chenab representative pilot A",
    bbox=(72.306, 30.776, 72.330, 30.798),
    parent_canal_osm_way=1429447136,
    geographic_name_basis=(
        "Inside the published Mungi study search extent (doi:10.3390/w14030405) but no "
        "OSM waterway named Mungi was found in that extent (Overpass, 2026-10-09). The AOI "
        "is crossed by the Gugera (Gogera) Branch canal of the Lower Chenab Canal system "
        "(OSM way 1429447136, wikidata Q5615200), so it is named a Lower Chenab "
        "representative pilot, not Mungi."
    ),
    selection_rationale=(
        "Densest mapped minor-watercourse context in the extent: Gugera Branch plus several "
        "OSM waterway=ditch/drain features mapped at field scale near 72.32E 30.79N; "
        "irrigated wheat parcels clearly visible in a clear Feb 2025 Sentinel-2 scene; "
        "village area kept small."
    ),
)

PILOT_B = PilotAoi(
    pilot_id="pilot-b",
    name="Lower Chenab representative pilot B",
    bbox=(72.234, 30.657, 72.256, 30.677),
    parent_canal_osm_way=488499235,
    geographic_name_basis=(
        "Inside the published Mungi study search extent (doi:10.3390/w14030405); no Mungi "
        "waterway identified. The AOI lies along the canal mapped in OSM as 'R-1' "
        "(way 488499235) about 12 km south-west of pilot A in the same broader Lower Chenab "
        "irrigated region, so it is named a Lower Chenab representative pilot."
    ),
    selection_rationale=(
        "Second, disjoint agricultural AOI with a mapped distributary-scale canal (R-1) on "
        "its western edge and large contiguous wheat parcels in the same Feb 2025 scene; "
        "selected to demonstrate geographic/network portability, not climate diversity."
    ),
)

PILOTS = {p.pilot_id: p for p in (PILOT_A, PILOT_B)}
