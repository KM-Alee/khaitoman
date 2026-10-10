"""Physical validation report assembly (T4.7).

Every rule produces a ``RuleResidual`` with entity/time references. A report
passes only if every residual passes. Conservation tolerance defaults to
``1e-6 m3`` absolute plus ``1e-9`` relative to the compared magnitude; it is a
floating-point tolerance, never an engineering fudge.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from aabflow.domain.schemas import PhysicalValidationReport, RuleResidual

ABS_TOL_M3 = 1e-6
REL_TOL = 1e-9

RULES = (
    "receipt_right",
    "route_open",
    "edge_capacity",
    "source_capacity",
    "node_balance",
    "pond_capacity",
    "pond_nonnegative",
    "pond_loss_bound",
    "pond_fill_rate",
    "pond_release_rate",
    "pump_access",
    "pump_rate",
    "pump_seasonal_cap",
    "pump_cost",
    "pump_sharing",
    "field_balance",
    "area",
    "commissioning",
    "cost_completeness",
    "daily_application",
    "event_order",
    "pond_sharing",
)


def tol(magnitude: float, abs_tol: float = ABS_TOL_M3, rel_tol: float = REL_TOL) -> float:
    return abs_tol + rel_tol * abs(magnitude)


def exceeds(value: float, bound: float) -> bool:
    """True when ``value`` is above ``bound`` beyond tolerance."""
    return value - bound > tol(max(abs(value), abs(bound)))


class Residuals:
    """Collects failures per rule plus an explicit pass entry for rules checked clean."""

    def __init__(self) -> None:
        self._fail: list[RuleResidual] = []
        self._checked: set[str] = set()

    def check(self, rule: str) -> None:
        self._checked.add(rule)

    def fail(
        self,
        rule: str,
        violation: float,
        entity_ids: Iterable[str] = (),
        at: datetime | None = None,
        detail: str | None = None,
        unit: str = "m3",
    ) -> None:
        self._checked.add(rule)
        self._fail.append(
            RuleResidual(
                rule=rule,
                passed=False,
                max_violation=float(abs(violation)),
                unit=unit,
                entity_ids=sorted(set(entity_ids)),
                at=at,
                detail=detail,
            )
        )

    def extend(self, other: Residuals) -> None:
        self._fail.extend(other._fail)
        self._checked |= other._checked

    @property
    def failures(self) -> list[RuleResidual]:
        return list(self._fail)

    @property
    def ok(self) -> bool:
        return not self._fail

    def reasons(self) -> list[str]:
        return [f"{r.rule}: {r.detail or ''}".strip() for r in self._fail]

    def report(self) -> PhysicalValidationReport:
        failed_rules = {r.rule for r in self._fail}
        passes = [
            RuleResidual(rule=rule, passed=True, max_violation=0.0)
            for rule in sorted(self._checked - failed_rules)
        ]
        # Collapse many failures of one rule: keep the worst 20 per rule for readability.
        by_rule: dict[str, list[RuleResidual]] = {}
        for r in self._fail:
            by_rule.setdefault(r.rule, []).append(r)
        kept: list[RuleResidual] = []
        for _rule, rs in sorted(by_rule.items()):
            kept.extend(sorted(rs, key=lambda r: -r.max_violation)[:20])
        return PhysicalValidationReport(
            status="passed" if self.ok else "failed",
            abs_tolerance_m3=ABS_TOL_M3,
            rel_tolerance=REL_TOL,
            residuals=passes + kept,
        )
