"""Bindings from the optimizer/API stream to the science stream's entry points.

Production uses ``bindings(settings)`` below, which imports the real science
modules lazily (STREAMS.md signatures). Tests may pass a different
``Settings.science_bindings`` factory; production configuration never reads it
from the environment, so a test fixture cannot leak into a live path.
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from aabflow.api.errors import DomainError
from aabflow.config import Settings
from aabflow.domain.schemas import (
    CandidateLibrary,
    CandidatePolicy,
    ErrorCode,
    LedgerEvent,
    PhysicalValidationReport,
    StateOutcome,
    SupplyProfile,
)


class ScienceBindings(Protocol):
    def load_library(
        self, pilot_id: str, season_id: str, library_hash: str | None
    ) -> tuple[CandidateLibrary, list[CandidatePolicy]]: ...

    def resolve_supply(self, profile: SupplyProfile, extra_uniform_reduction: float) -> Any: ...

    def closure(self, start, end, edge_ids: frozenset[str], reason: str) -> Any: ...

    def season_context(self, pilot_id: str, season_id: str, pilot_version: str) -> Any: ...

    def evaluate_policy(
        self,
        policy: CandidatePolicy,
        ctx: Any,
        resolved_supply: Any,
        weather_scenario_id: str,
        config_id: str,
        *,
        state_id: str,
        extra_closures: tuple = (),
    ) -> StateOutcome: ...

    def reconstruct(
        self,
        policy_ids: list[str],
        library: CandidateLibrary,
        state_id: str,
        config_id: str,
        *,
        resolved_supply: Any = None,
        extra_closures: tuple = (),
        policies: dict | None = None,
    ) -> tuple[list[LedgerEvent], PhysicalValidationReport]: ...

    def load_trajectory(self, crop_outcome_hash: str) -> Any: ...

    def crop_outcome(self, crop_outcome_hash: str) -> Any: ...


def _unavailable(what: str, exc: Exception) -> DomainError:
    return DomainError(
        ErrorCode.ASSET_UNAVAILABLE, f"science entry point unavailable ({what}): {exc}"
    )


class ProductionScience:
    """Real science stream functions (aabflow.optimizer.candidates, aabflow.water.ledger, ...)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        _align_science_paths(settings.data_dir)

    def load_library(self, pilot_id, season_id, library_hash=None):
        try:
            from aabflow.optimizer.candidates import load_library
        except ImportError as exc:  # pragma: no cover - depends on the science stream
            raise _unavailable("load_library", exc) from exc
        try:
            return load_library(pilot_id, season_id, library_hash)
        except FileNotFoundError as exc:
            raise DomainError(
                ErrorCode.ASSET_UNAVAILABLE, f"candidate library unavailable: {exc}"
            ) from exc

    def resolve_supply(self, profile, extra_uniform_reduction=0.0):
        from aabflow.water.roster import resolve_supply

        return resolve_supply(profile, extra_uniform_reduction)

    def closure(self, start, end, edge_ids, reason):
        from aabflow.water.roster import Closure

        return Closure(start, end, frozenset(edge_ids), reason)

    def season_context(self, pilot_id, season_id, pilot_version):
        from aabflow.water.ledger import season_context

        return season_context(pilot_id, season_id, pilot_version)

    def evaluate_policy(
        self,
        policy,
        ctx,
        resolved_supply,
        weather_scenario_id,
        config_id,
        *,
        state_id,
        extra_closures=(),
    ):
        from aabflow.water.ledger import evaluate_policy

        return evaluate_policy(
            policy,
            ctx,
            resolved_supply,
            weather_scenario_id,
            config_id,
            state_id=state_id,
            extra_closures=tuple(extra_closures),
        )

    def reconstruct(
        self,
        policy_ids,
        library,
        state_id,
        config_id,
        *,
        resolved_supply=None,
        extra_closures=(),
        policies=None,
    ):
        from aabflow.water.ledger import reconstruct

        return reconstruct(
            policy_ids,
            library,
            state_id,
            config_id,
            resolved_supply=resolved_supply,
            extra_closures=tuple(extra_closures),
            policies=policies,
        )

    def load_trajectory(self, crop_outcome_hash):
        from aabflow.science.experiments import load_outcome, load_trajectory

        out = load_outcome(crop_outcome_hash)
        if out is None:
            return None
        try:
            return load_trajectory(out)
        except (FileNotFoundError, OSError):
            return None

    def crop_outcome(self, crop_outcome_hash):
        from aabflow.science.experiments import load_outcome

        return load_outcome(crop_outcome_hash)


def _align_science_paths(data_dir: Path) -> None:
    """The science stream resolves artifacts from ``aabflow.science.paths.DATA_DIR``; keep it equal to
    the API's data directory (identical in production, a temp dir in tests)."""
    try:
        paths = importlib.import_module("aabflow.science.paths")
    except ImportError:  # pragma: no cover
        return
    if Path(paths.DATA_DIR) != Path(data_dir):
        paths.DATA_DIR = Path(data_dir)
        try:
            ledger = importlib.import_module("aabflow.water.ledger")
            ledger._cached_context.cache_clear()
            ledger._policies_cached.cache_clear()
            importlib.import_module("aabflow.science.soils").refresh()
        except (ImportError, AttributeError):
            pass


def bindings(settings: Settings) -> ProductionScience:
    return ProductionScience(settings)


@lru_cache(maxsize=8)
def _factory(spec: str):
    mod, attr = spec.split(":")
    return getattr(importlib.import_module(mod), attr)


_instances: dict[tuple, Any] = {}


def get_bindings(settings: Settings) -> ScienceBindings:
    key = (settings.science_bindings, str(settings.data_dir))
    if key not in _instances:
        _instances[key] = _factory(settings.science_bindings)(settings)
    return _instances[key]
