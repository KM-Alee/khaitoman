"""Science-published catalog: seasons, crop profiles, weather scenarios, supply
profiles, uncertainty sets and candidate-library readiness (STREAMS.md).

Formats (science stream):
- ``seasons.json``: ``[Season]``; ``crop_profiles.json``: ``[CropProfile]``
- ``weather_scenarios.json``: ``{default_grid_cell, pilot_grid_cells: {pilot: cell},
  grid_cells: {cell: {scenarios: [WeatherScenario]}}, scenarios: [...]}``
- ``supply.json``: ``{supply_profile_ids, seasons: {season_id: {generic: [SupplyProfile],
  by_pilot: {pilot_id: [SupplyProfile]}}}, uncertainty_sets: [UncertaintySet]}``
- ``<pilot>/<season>/latest.json`` names the current library hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aabflow.domain.schemas import (
    CropProfile,
    Season,
    SupplyProfile,
    UncertaintySet,
    WeatherScenario,
)


def _load(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class Catalog:
    def __init__(self, libraries_dir: Path):
        self.root = Path(libraries_dir)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cached(self, name: str, parse) -> Any:
        p = self.root / name
        if not p.exists():
            return parse(None)
        stamp = p.stat().st_mtime
        hit = self._cache.get(name)
        if hit and hit[0] == stamp:
            return hit[1]
        val = parse(_load(p))
        self._cache[name] = (stamp, val)
        return val

    # ------------------------------------------------------------------ seasons
    def seasons(self) -> list[Season]:
        return self._cached(
            "seasons.json", lambda raw: [Season.model_validate(s) for s in raw or []]
        )

    def season(self, season_id: str) -> Season | None:
        return next((s for s in self.seasons() if s.season_id == season_id), None)

    def crop_profiles(self) -> dict[str, CropProfile]:
        def parse(raw):
            rows = raw.get("profiles", []) if isinstance(raw, dict) else raw or []
            return {p["crop_profile_id"]: CropProfile.model_validate(p) for p in rows}

        return self._cached("crop_profiles.json", parse)

    # ------------------------------------------------------------------ weather
    def _weather_raw(self) -> dict:
        return self._cached("weather_scenarios.json", lambda raw: raw or {})

    def weather_scenarios(
        self, pilot_id: str | None, season_id: str | None
    ) -> list[WeatherScenario]:
        raw = self._weather_raw()
        cell = (raw.get("pilot_grid_cells") or {}).get(pilot_id) if pilot_id else None
        rows = None
        if cell and cell in (raw.get("grid_cells") or {}):
            rows = raw["grid_cells"][cell].get("scenarios")
        if rows is None:
            rows = raw.get("scenarios", [])
        out = [WeatherScenario.model_validate(r) for r in rows]
        if season_id:
            out = [w for w in out if w.season_id == season_id]
        return out

    # ------------------------------------------------------------------- supply
    def _supply_raw(self) -> dict:
        return self._cached("supply.json", lambda raw: raw or {})

    def supply_profiles(self, pilot_id: str | None, season_id: str) -> list[SupplyProfile]:
        seasons = self._supply_raw().get("seasons") or {}
        entry = seasons.get(season_id) or {}
        rows = list(entry.get("generic") or [])
        by_pilot = (entry.get("by_pilot") or {}).get(pilot_id) if pilot_id else None
        if by_pilot:
            ids = {r["supply_profile_id"] for r in by_pilot}
            rows = [r for r in rows if r["supply_profile_id"] not in ids] + list(by_pilot)
        return [SupplyProfile.model_validate(r) for r in rows]

    def supply_profile(
        self, pilot_id: str, season_id: str, profile_id: str
    ) -> SupplyProfile | None:
        return next(
            (
                p
                for p in self.supply_profiles(pilot_id, season_id)
                if p.supply_profile_id == profile_id
            ),
            None,
        )

    def uncertainty_sets(self, pilot_id: str | None, season_id: str | None) -> list[UncertaintySet]:
        rows = [
            UncertaintySet.model_validate(u)
            for u in self._supply_raw().get("uncertainty_sets") or []
        ]
        return [
            u
            for u in rows
            if (pilot_id is None or u.pilot_id == pilot_id)
            and (season_id is None or u.season_id == season_id)
        ]

    def uncertainty_set(self, set_id: str) -> UncertaintySet | None:
        return next(
            (u for u in self.uncertainty_sets(None, None) if u.uncertainty_set_id == set_id), None
        )

    # ------------------------------------------------------------------ library
    def latest_library_hash(self, pilot_id: str, season_id: str) -> str | None:
        p = self.root / pilot_id / season_id / "latest.json"
        raw = _load(p)
        if raw is None:
            return None
        if isinstance(raw, str):
            h = raw
        else:
            h = raw.get("candidate_library_hash") or raw.get("library_hash") or raw.get("hash")
        if not h or not (self.root / pilot_id / season_id / h / "library.json").exists():
            return None
        return h

    def library_summary(self, pilot_id: str, season_id: str) -> dict[str, Any]:
        h = self.latest_library_hash(pilot_id, season_id)
        if h is None:
            return {
                "ready": False,
                "candidate_library_hash": None,
                "reason": "no published candidate library",
            }
        lib = _load(self.root / pilot_id / season_id / h / "library.json") or {}
        cov = lib.get("coverage") or []
        return {
            "ready": True,
            "candidate_library_hash": h,
            "pilot_version": lib.get("pilot_version"),
            "state_ids": lib.get("state_ids", []),
            "configurations": [
                c.get("shared_configuration_id") for c in lib.get("configurations", [])
            ],
            "retained_policies": sum(int(c.get("retained", 0)) for c in cov),
            "fields": len(cov),
            "generator_version": lib.get("generator_version"),
            "created_at": lib.get("created_at"),
        }

    # ------------------------------------------------------------------- prices
    def prices(self) -> list[dict[str, Any]]:
        """Dated crop price records ``[{crop, season_id?, price_pkr_per_kg, evidence_id, observed_on, basis}]``."""
        return self._cached(
            "prices.json", lambda raw: [r for r in raw or [] if isinstance(r, dict)]
        )

    def price(self, crop: str | None, season_id: str) -> dict[str, Any] | None:
        rows = [
            r
            for r in self.prices()
            if r.get("crop") == crop
            and r.get("season_id") in (None, season_id)
            and r.get("price_pkr_per_kg")
            and r.get("evidence_id")
        ]
        rows.sort(key=lambda r: (r.get("season_id") is None, str(r.get("observed_on", ""))))
        return rows[0] if rows else None
