"""Expanded analysis services (T7.1–T7.4, PRD §7.2–7.5).

Each analysis is an immutable request stored in ``analyses`` plus one durable job
that solves child runs through the ordinary run path (``services.runs.execute``):
every point/cell/arm maps back to a run record with its own artifacts, so nothing
here invents outcomes. Pure functions below (nondominance, objective-difference
intervals, synergy bounds) are separated from orchestration for direct testing.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from pydantic import Field, model_validator

from aabflow.api.errors import invalid, not_found
from aabflow.domain.hashes import content_hash
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import CONTRACT_VERSION, StrictModel
from aabflow.jobs import queue
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow

KINDS = ("frontier", "stress", "why_not", "sensitivity", "synergy")
ANALYSIS_VERSION = "analyses-1.0.0"


# ----------------------------------------------------------------------------- requests


class FrontierSetting(StrictModel):
    capital_budget_pkr: int = Field(ge=0)
    minimum_service_ratio: float | None = Field(default=None, ge=0, le=1)
    service_group: Literal["all", "head", "middle", "tail"] | None = None

    @model_validator(mode="after")
    def _pair(self) -> FrontierSetting:
        if self.minimum_service_ratio is not None and self.service_group is None:
            self.service_group = "all"
        if self.minimum_service_ratio is None:
            self.service_group = None
        return self


class FrontierRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    base_revision_id: str
    settings: list[FrontierSetting] = Field(min_length=6, max_length=24)
    plan_kind: Literal["P", "R"] = (
        "P"  # R solves every point robustly over the revision's uncertainty set
    )
    time_limit_per_point_s: float = Field(default=10.0, gt=0, le=60)
    total_budget_s: float = Field(default=180.0, gt=0, le=900)

    @model_validator(mode="after")
    def _distinct(self) -> FrontierRequest:
        keys = [s.model_dump_json() for s in self.settings]
        if len(set(keys)) != len(keys):
            raise ValueError("frontier settings must be distinct")
        return self


class StressRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    run_id: str
    mode: Literal["fixed_plan", "recovery_plan"] = "fixed_plan"
    state_ids: list[str] | None = Field(
        default=None, max_length=9
    )  # None = the uncertainty set's states
    uncertainty_set_id: str | None = (
        None  # None = the run's revision set, else the season's published set
    )
    reference_run_id: str | None = (
        None  # typical-only plan for the robust "foregone output" display
    )
    time_limit_per_cell_s: float = Field(default=8.0, gt=0, le=60)


class WhyNotRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    base_revision_id: str
    instance_id: str
    action: Literal["force", "exclude"] = "force"
    base_run_id: str | None = None
    time_limit_s: float = Field(default=10.0, gt=0, le=60)


SENSITIVITY_PARAMETERS = (
    "capital_budget_pkr",
    "operating_budget_pkr",
    "uniform_reduction_fraction",
    "minimum_service_ratio",
)


class SensitivityRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    base_revision_id: str
    parameter: Literal[
        "capital_budget_pkr",
        "operating_budget_pkr",
        "uniform_reduction_fraction",
        "minimum_service_ratio",
    ]
    values: list[float] = Field(min_length=2, max_length=12)
    service_group: Literal["all", "head", "middle", "tail"] | None = (
        None  # for minimum_service_ratio
    )
    time_limit_per_point_s: float = Field(default=10.0, gt=0, le=60)

    @model_validator(mode="after")
    def _check(self) -> SensitivityRequest:
        if len(set(self.values)) != len(self.values):
            raise ValueError("values must be distinct")
        for v in self.values:
            if v < 0:
                raise ValueError("values must be non-negative")
            if self.parameter in ("uniform_reduction_fraction", "minimum_service_ratio") and v > 1:
                raise ValueError(f"{self.parameter} values are fractions in [0, 1]")
            if self.parameter == "uniform_reduction_fraction" and v >= 1:
                raise ValueError("uniform_reduction_fraction must stay below 1")
        return self


class SynergyRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    base_revision_id: str
    instance_a: str
    instance_b: str
    other_actions: Literal["fixed", "reoptimize"] = "reoptimize"
    base_run_id: str | None = (
        None  # required source of the "fixed" other investments (solved if absent)
    )
    time_limit_per_arm_s: float = Field(default=10.0, gt=0, le=60)

    @model_validator(mode="after")
    def _distinct(self) -> SynergyRequest:
        if self.instance_a == self.instance_b:
            raise ValueError("synergy needs two distinct intervention instances")
        return self


REQUEST_MODELS: dict[str, type[StrictModel]] = {
    "frontier": FrontierRequest,
    "stress": StressRequest,
    "why_not": WhyNotRequest,
    "sensitivity": SensitivityRequest,
    "synergy": SynergyRequest,
}


# ----------------------------------------------------------------------------- storage


def create(
    conn: sqlite3.Connection,
    kind: str,
    request: StrictModel,
    *,
    base_revision_id: str | None,
    base_run_id: str | None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    """Insert the analysis row and enqueue its job in one transaction; returns (analysis_id, job_id)."""
    if kind not in KINDS:
        raise invalid(f"unknown analysis kind {kind}", {"kind": kind})
    aid = new_id("ana")
    req = request.model_dump(mode="json")
    now = utcnow()
    with tx(conn):
        conn.execute(
            "INSERT INTO analyses (analysis_id, kind, base_revision_id, base_run_id, job_id, request, result, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                aid,
                kind,
                base_revision_id,
                base_run_id,
                None,
                dumps(req),
                dumps(_initial(kind, req)),
                now,
                now,
            ),
        )
    payload = {"analysis_id": aid}
    jid = queue.enqueue(
        conn,
        f"analysis.{kind}",
        payload,
        content_hash({"kind": kind, "request": req, "id": aid}),
        subject_id=aid,
    )
    with tx(conn):
        conn.execute(
            "UPDATE analyses SET job_id = ?, updated_at = ? WHERE analysis_id = ?",
            (jid, utcnow(), aid),
        )
    return aid, jid


def _initial(kind: str, req: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "queued",
        "analysis_version": ANALYSIS_VERSION,
        "child_run_ids": [],
    }


def row(conn: sqlite3.Connection, analysis_id: str) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
    if r is None:
        raise not_found("analysis_id", analysis_id)
    return r


def save_result(conn: sqlite3.Connection, analysis_id: str, result: dict[str, Any]) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE analyses SET result = ?, updated_at = ? WHERE analysis_id = ?",
            (dumps(result), utcnow(), analysis_id),
        )


def get_analysis(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
    if r is None:
        return None
    return view(conn, r)


def view(conn: sqlite3.Connection, r: sqlite3.Row) -> dict[str, Any]:
    job = queue.get(conn, r["job_id"]) if r["job_id"] else None
    result = loads(r["result"]) if r["result"] else None
    job_state = job["state"] if job is not None else None
    status = (result or {}).get("status", "queued")
    if job_state in ("failed", "cancelled", "interrupted") and status not in ("completed",):
        status = job_state
    pilot = (
        conn.execute(
            "SELECT request FROM scenario_revisions WHERE scenario_revision_id = ?",
            (r["base_revision_id"],),
        ).fetchone()
        if r["base_revision_id"]
        else None
    )
    return {
        "analysis_id": r["analysis_id"],
        "kind": r["kind"],
        "pilot_id": loads(pilot["request"]).get("pilot_id") if pilot else None,
        "base_revision_id": r["base_revision_id"],
        "base_run_id": r["base_run_id"],
        "job_id": r["job_id"],
        "job_state": job_state,
        "job_error": loads(job["error_ref"]) if job is not None and job["error_ref"] else None,
        "status": status,
        "request": loads(r["request"]),
        "result": result,
        "child_run_ids": (result or {}).get("child_run_ids", []),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def list_analyses(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    base_revision_id: str | None = None,
    base_run_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM analyses"
    where, args = [], []
    for col, val in (
        ("kind", kind),
        ("base_revision_id", base_revision_id),
        ("base_run_id", base_run_id),
    ):
        if val is not None:
            where.append(f"{col} = ?")
            args.append(val)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(sql, args).fetchall():
        v = view(conn, r)
        v.pop("result", None)
        out.append(v)
    return out


# ----------------------------------------------------------------------------- pure analysis math


def objective_interval(point: dict[str, Any]) -> tuple[float, float] | None:
    """Supported interval [L, U] for a maximisation run's attainable objective (None: no incumbent)."""
    lo = point.get("objective_value")
    if lo is None:
        return None
    hi = point.get("objective_upper_bound")
    return float(lo), float(hi if hi is not None and hi >= lo else lo)


def difference_interval(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Objective difference ``b - a`` for two maximisation runs (T7.3): ``[L_b - U_a, U_b - L_a]``."""
    ia, ib = objective_interval(a), objective_interval(b)
    if ia is None or ib is None:
        missing = [n for n, i in (("a", ia), ("b", ib)) if i is None]
        return {
            "status": "not_comparable",
            "lower": None,
            "upper": None,
            "point": None,
            "reason": f"no feasible incumbent for {', '.join(missing)}",
        }
    lo, hi = ib[0] - ia[1], ib[1] - ia[0]
    exact = abs(hi - lo) <= quantum_tolerance(a, b)
    return {
        "status": "exact" if exact else "interval",
        "lower": lo,
        "upper": hi,
        "point": ib[0] - ia[0] if exact else None,
        "reason": None if exact else "solver bounds overlap; only the interval is supported",
    }


def quantum_tolerance(*points: dict[str, Any]) -> float:
    return sum(float(p.get("quantization_bound") or 0.0) for p in points) + 1e-6


VECTOR = (
    ("objective_value", "max"),
    ("capital_commitment_pkr", "min"),
    ("min_service_ratio", "max"),
)


def _vec(p: dict[str, Any]) -> list[float] | None:
    out = []
    for k, _ in VECTOR:
        v = p.get(k)
        if v is None:
            return None
        out.append(float(v))
    return out


def _dominates(a: list[float], b: list[float], eps: float = 1e-9) -> bool:
    better_somewhere = False
    for (_, sense), x, y in zip(VECTOR, a, b, strict=True):
        if sense == "max":
            if x < y - eps:
                return False
            if x > y + eps:
                better_somewhere = True
        else:
            if x > y + eps:
                return False
            if x < y - eps:
                better_somewhere = True
    return better_somewhere


def classify_frontier(points: list[dict[str, Any]]) -> None:
    """Nondominance among evaluated feasible plans (in place).

    ``dominance`` is ``nondominated``, ``dominated`` (another incumbent is at least as good on every
    axis and that holds even at this point's objective upper bound), ``dominance_unresolved``
    (dominated by incumbents but this point's solver bound overlaps), or ``not_applicable``
    (infeasible/unknown/invalid: shown separately, never on the curve).
    """
    feas = [p for p in points if p.get("outcome") == "plan" and _vec(p) is not None]
    for p in points:
        if p not in feas:
            p["dominance"] = "not_applicable"
            p["dominated_by"] = []
    for p in feas:
        vp = _vec(p)
        doms = [q for q in feas if q is not p and _dominates(_vec(q), vp)]
        if not doms:
            p["dominance"] = "nondominated"
            p["dominated_by"] = []
            continue
        ub = p.get("objective_upper_bound")
        optimistic = list(vp)
        if ub is not None:
            optimistic[0] = max(optimistic[0], float(ub))
        resolved = [q for q in doms if _dominates(_vec(q), optimistic)]
        p["dominated_by"] = [q["point_id"] for q in doms]
        p["dominance"] = "dominated" if resolved else "dominance_unresolved"


def portfolio_key(run_view: dict[str, Any]) -> str | None:
    run = run_view.get("run") or {}
    if run.get("outcome") != "plan":
        return None
    return content_hash(
        {
            "config": run.get("shared_configuration_id"),
            "instances": sorted(run.get("selected_intervention_instance_ids") or []),
            "policies": sorted(run.get("selected_candidate_policy_ids") or []),
        }
    )


def synergy(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``AB - A - B + none`` with bounds (T7.4). Arms carry objective_value/upper_bound or no incumbent."""
    need = ("none", "a", "b", "ab")
    missing = [k for k in need if objective_interval(arms.get(k, {})) is None]
    if missing:
        return {
            "status": "not_available",
            "value": None,
            "lower": None,
            "upper": None,
            "reason": "no feasible plan for arm(s) "
            + ", ".join(missing)
            + "; an exact synergy needs all four matched runs",
        }
    i = {k: objective_interval(arms[k]) for k in need}
    lo = i["ab"][0] - i["a"][1] - i["b"][1] + i["none"][0]
    hi = i["ab"][1] - i["a"][0] - i["b"][0] + i["none"][1]
    point = (
        arms["ab"]["objective_value"]
        - arms["a"]["objective_value"]
        - arms["b"]["objective_value"]
        + arms["none"]["objective_value"]
    )
    exact = hi - lo <= quantum_tolerance(*(arms[k] for k in need))
    sign = None
    if exact:
        tol = quantum_tolerance(*(arms[k] for k in need))
        sign = "positive" if point > tol else ("negative" if point < -tol else "zero")
    elif lo > 0:
        sign = "positive"
    elif hi < 0:
        sign = "negative"
    return {
        "status": "exact" if exact else "interval",
        "value": point if exact else None,
        "incumbent_value": point,
        "lower": lo,
        "upper": hi,
        "sign": sign,
        "reason": None
        if exact
        else "some arms are not proven optimal; the synergy is the supported interval",
    }
