"""Soil profiles from AquaCrop predefined classes and declared initial states.

``initial_water`` grammar (stored on ``SoilProfile``):

* ``"FC"`` / ``"WP"`` / ``"SAT"`` -> AquaCrop ``Prop`` initial water content;
* ``"pct_taw:<0-100>"`` -> AquaCrop ``Pct`` (percent of total available water).

The science default is ``pct_taw:50`` at simulation start (14 days before
planting): a declared post-harvest/pre-season assumption, not a measurement.
Pre-plant field irrigation is outside the v2 adapter (T5.3), so starting at
field capacity would silently credit an unaccounted pre-sowing irrigation.
Pilot packages may publish their own profiles (``soils.json``); those take
precedence for their ids.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from aabflow.domain.schemas import SoilProfile
from aabflow.science.paths import pilots_dir

AQUACROP_SOIL_CLASSES = frozenset(
    {
        "Clay",
        "ClayLoam",
        "Loam",
        "LoamySand",
        "Sand",
        "SandyClay",
        "SandyClayLoam",
        "SandyLoam",
        "Silt",
        "SiltClayLoam",
        "SiltLoam",
        "SiltClay",
    }
)
DEFAULT_INITIAL_WATER = "pct_taw:50"
_PCT = re.compile(r"^pct_taw:(\d+(?:\.\d+)?)$")


class SoilProfileError(ValueError):
    pass


def _builtin(engine: str, archetype: str) -> SoilProfile:
    return SoilProfile(
        soil_profile_id=f"aquacrop-{engine.lower()}-pct50",
        engine_soil_type=engine,
        archetype=archetype,
        initial_water=DEFAULT_INITIAL_WATER,
        evidence_ids=["ev-science-soil-aquacrop-classes"],
        limitations=[
            "AquaCrop predefined texture class; a prior until local soil measurements exist.",
            "Initial water 50% TAW at simulation start is a declared assumption.",
        ],
    )


BUILTIN_SOILS: dict[str, SoilProfile] = {
    s.soil_profile_id: s
    for s in [
        _builtin("SiltLoam", "silt-loam"),
        _builtin("Loam", "loam"),
        _builtin("SandyLoam", "sandy-loam"),
        _builtin("ClayLoam", "clay-loam"),
    ]
}


def parse_initial_water(value: str) -> tuple[str, list[float | str]]:
    """Return (wc_type, value list) for ``InitialWaterContent``."""
    if value in ("FC", "WP", "SAT"):
        return "Prop", [value]
    m = _PCT.match(value)
    if m:
        pct = float(m.group(1))
        if not 0 <= pct <= 100:
            raise SoilProfileError(f"pct_taw must be within [0, 100], got {pct}")
        return "Pct", [pct]
    raise SoilProfileError(f"unsupported initial_water {value!r} (FC|WP|SAT|pct_taw:<n>)")


def validate_soil(s: SoilProfile) -> SoilProfile:
    if s.engine_soil_type not in AQUACROP_SOIL_CLASSES:
        raise SoilProfileError(
            f"{s.soil_profile_id}: {s.engine_soil_type!r} is not an AquaCrop predefined class"
        )
    parse_initial_water(s.initial_water)
    return s


@lru_cache(maxsize=1)
def _pilot_soils() -> dict[str, SoilProfile]:
    out: dict[str, SoilProfile] = {}
    root = pilots_dir()
    if not root.exists():
        return out
    for path in sorted(root.glob("*/*/soils.json")):
        try:
            rows = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for row in rows:
            s = SoilProfile.model_validate(row)
            out[s.soil_profile_id] = s
    return out


def refresh() -> None:
    _pilot_soils.cache_clear()


def soil(soil_profile_id: str) -> SoilProfile:
    if soil_profile_id in BUILTIN_SOILS:
        return BUILTIN_SOILS[soil_profile_id]
    found = _pilot_soils().get(soil_profile_id)
    if found is None:
        refresh()
        found = _pilot_soils().get(soil_profile_id)
    if found is None:
        raise KeyError(f"unknown soil profile {soil_profile_id!r}")
    return validate_soil(found)


def register(s: SoilProfile) -> None:
    """Make a (test or pilot) soil profile resolvable in this process."""
    BUILTIN_SOILS[s.soil_profile_id] = validate_soil(s)
