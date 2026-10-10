"""Impact route rejections: path, ownership, unknown fields, nonfinite, idempotency."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aabflow.api import errors
from aabflow.api.impact import ImpactRequest, router
from aabflow.api.state import AppState
from aabflow.domain.schemas import MetricStatus
from aabflow.repositories.sqlite import init_db
from aabflow.services.catalog import Catalog
from aabflow.services.impact import view
from aabflow.services.impact.view import assemble
from aabflow.services.metrics import mv
from aabflow.services.pilots import PilotRepository
from tests.fixtures.api_app import settings_for

BLOCKED = "at least one tested state is undeliverable for this plan"


class FakeRun:
    def __init__(
        self,
        run_id: str,
        *,
        pilot: str | None = "pilot-a",
        states: list[str] | None = None,
        metrics: list | None = None,
        outcome: str = "plan",
        library: str = "lib",
    ):
        self.run_id = run_id
        self._metrics = list(metrics or [])
        states = list(states or ["typical"])
        compatibility = {
            "pilot_id": pilot,
            "pilot_version": "reviewed-v1",
            "season_id": "wheat-rabi",
            "states": states,
            "typical_state": states[0],
            "uniform_reduction_fraction": 0.0,
            "blocked_edge_ids": [],
            "metrics_version": "metrics-1.0.0",
            "initial_state": "library-declared initial soil and pond state",
        }
        self.meta = {"pilot_id": pilot, "compatibility": compatibility}
        self._scenario = {"request": {}}
        self.result = SimpleNamespace(
            outcome=outcome,
            plan_kind=SimpleNamespace(value="P"),
            candidate_library_hash=library,
        )

    def metrics(self):
        return list(self._metrics)

    def json(self, name: str):
        if name == "scenario.json":
            return self._scenario
        raise FileNotFoundError(name)


@pytest.fixture
def client(tmp_path):
    settings = settings_for(tmp_path)
    init_db(settings.db_path)
    app = FastAPI()
    app.state.aab = AppState(
        settings=settings,
        pilots=PilotRepository(settings.pilots_dir),
        catalog=Catalog(settings.libraries_dir),
    )
    errors.install(app)
    api = APIRouter(prefix="/api/v2")
    api.include_router(router)
    app.include_router(api)
    with TestClient(app) as test_client:
        yield test_client


def test_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ImpactRequest.model_validate({"run_id": "run_a", "score": 80})
    with pytest.raises(ValidationError):
        ImpactRequest.model_validate({"run_id": "run_a", "contract_version": "1.0.0"})


def test_unknown_run_is_404(client):
    response = client.get("/api/v2/runs/run_missing/impact")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["fields"]["run_id"] == "run_missing"


def test_path_identifiers_rejected(client):
    dotted = client.get("/api/v2/runs/bad.id/impact")
    assert dotted.status_code == 422
    assert dotted.json()["code"] == "INVALID_INPUT"
    assert dotted.json()["fields"]["run_id"] == "rejected"
    parent = client.get("/api/v2/runs/run_a/impact", params={"baseline_run_id": "../secret"})
    assert parent.status_code == 422
    assert parent.json()["fields"]["baseline_run_id"] == "rejected"
    posted = client.post("/api/v2/impact", json={"run_id": "run_a", "score": 100})
    assert posted.status_code == 422
    assert posted.json()["code"] == "INVALID_INPUT"
    assert "score" in posted.json()["fields"]


def test_non_plan_does_not_invent_metrics(client, monkeypatch):
    decoy = mv("production_kg", "run_a", 999)
    monkeypatch.setattr(
        view, "load_run", lambda conn, run_id: FakeRun(run_id, metrics=[decoy], outcome="no_plan")
    )
    response = client.get("/api/v2/runs/run_a/impact")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["cards"] == []
    assert body["co2"]["status"] == "not_estimated"
    assert body["co2"]["value"] is None
    assert "999" not in response.text


def test_baseline_other_pilot_rejected(client, monkeypatch):
    runs = {
        "run_a": FakeRun("run_a", pilot="pilot-a"),
        "run_b": FakeRun("run_b", pilot="pilot-b"),
    }
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: runs[run_id])
    response = client.get("/api/v2/runs/run_a/impact", params={"baseline_run_id": "run_b"})
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert response.json()["dependency_diff"]["baseline_pilot_id"] == "pilot-b"


def test_stored_metric_from_another_run_rejected(monkeypatch):
    foreign = mv("production_kg", "run_other", 10)
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: FakeRun(run_id, metrics=[foreign]))
    with pytest.raises(Exception) as caught:
        assemble(None, "run_a")
    assert caught.value.code.value == "VERSION_CONFLICT"
    assert caught.value.extra["dependency_diff"]["metric_run_id"] == "run_other"


def test_incompatible_baseline_is_labeled(monkeypatch):
    runs = {
        "run_a": FakeRun(
            "run_a",
            states=["wet", "dry"],
            metrics=[
                mv("groundwater_m3", "run_a", 3),
                mv("field_production_kg", "run_a", 8, field_id="f1"),
            ],
        ),
        "run_b": FakeRun(
            "run_b",
            states=["wet"],
            metrics=[
                mv("groundwater_m3", "run_b", 5),
                mv("field_production_kg", "run_b", 4, field_id="f1"),
            ],
        ),
    }
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: runs[run_id])
    body = assemble(None, "run_a", "run_b")
    assert body["compatible"] is False
    change = next(
        row
        for card in body["cards"]
        if card["card"] == "SDG 6.4/6.5"
        for row in card["values"]
        if row["metric_id"] == "sdg_6_4_groundwater_change_m3"
    )
    assert change["value"] is None
    assert change["status"] == "not_applicable"
    assert body["distribution"][0]["delta_kg"] is None


def test_nonfinite_stress_metric_rejected(client, monkeypatch):
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: FakeRun(run_id))
    monkeypatch.setattr(
        view,
        "get_analysis",
        lambda conn, analysis_id: {
            "kind": "stress",
            "base_run_id": "run_a",
            "result": {
                "mode": "fixed_plan",
                "metrics_by_id": {
                    "sdg_13_1_worst_tested_production_kg": {
                        "metric_id": "sdg_13_1_worst_tested_production_kg",
                        "definition_id": "sdg_13_1_worst_tested_production_kg@metrics-1.0.0",
                        "run_id": "run_a",
                        "value": float("nan"),
                        "unit": "kg",
                        "status": "available",
                        "evidence_ids": [],
                    }
                },
            },
        },
    )
    response = client.get("/api/v2/runs/run_a/impact", params={"stress_analysis_id": "an_1"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"
    assert "metrics_by_id" in response.json()["fields"]


def test_unknown_stress_analysis_is_404(client, monkeypatch):
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: FakeRun(run_id))
    response = client.get("/api/v2/runs/run_a/impact", params={"stress_analysis_id": "an_missing"})
    assert response.status_code == 404
    assert response.json()["fields"]["analysis_id"] == "an_missing"


def test_stress_owned_by_another_run_rejected(client, monkeypatch):
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: FakeRun(run_id))
    monkeypatch.setattr(
        view,
        "get_analysis",
        lambda conn, analysis_id: {
            "kind": "stress",
            "base_run_id": "run_other",
            "result": {"mode": "fixed_plan", "metrics_by_id": {}},
        },
    )
    response = client.get("/api/v2/runs/run_a/impact", params={"stress_analysis_id": "an_1"})
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"


def test_undeliverable_stress_blocks_13_1_and_recovery_does_not(monkeypatch):
    run = FakeRun(
        "run_a",
        metrics=[
            mv(
                "sdg_13_1_worst_tested_production_kg",
                "run_a",
                None,
                status=MetricStatus.not_applicable,
                reason="needs a multi-state stress or robust evaluation",
            ),
            mv("typical_production_kg", "run_a", 800),
        ],
    )
    monkeypatch.setattr(view, "load_run", lambda conn, run_id: run)
    blocked = mv(
        "sdg_13_1_worst_tested_production_kg",
        "run_a",
        None,
        status=MetricStatus.blocked,
        reason=BLOCKED,
    ).model_dump(mode="json")
    monkeypatch.setattr(
        view,
        "get_analysis",
        lambda conn, analysis_id: {
            "kind": "stress",
            "base_run_id": "run_a",
            "result": {
                "mode": "fixed_plan",
                "metrics_by_id": {"sdg_13_1_worst_tested_production_kg": blocked},
            },
        },
    )
    blocked_body = assemble(None, "run_a", stress_analysis_id="an_fixed")
    robust = next(item for item in blocked_body["cards"] if item["card"] == "SDG 13.1")
    assert robust["status"] == "blocked"
    assert robust["values"][0]["value"] is None

    monkeypatch.setattr(
        view,
        "get_analysis",
        lambda conn, analysis_id: {
            "kind": "stress",
            "base_run_id": "run_a",
            "result": {
                "mode": "recovery_plan",
                "metrics_by_id": {
                    "sdg_13_1_worst_tested_production_kg": {
                        **blocked,
                        "status": "available",
                        "value": 50,
                        "reason": None,
                    }
                },
            },
        },
    )
    recovery = assemble(None, "run_a", stress_analysis_id="an_recovery")
    robust = next(item for item in recovery["cards"] if item["card"] == "SDG 13.1")
    assert robust["status"] == "not_applicable"
    assert robust["values"][0]["value"] is None
    assert any("Recovery-plan" in line for line in robust["limitations"])
    assert "50" not in str(robust["values"])


def test_idempotency_replay_and_conflict(client, monkeypatch):
    calls = {"n": 0}

    def load(conn, run_id):
        calls["n"] += 1
        return FakeRun(run_id, metrics=[mv("production_kg", run_id, 12, crop="wheat")])

    monkeypatch.setattr(view, "load_run", load)
    body = {"contract_version": "2.0.0", "run_id": "run_a"}
    headers = {"Idempotency-Key": "impact-1"}
    first = client.post("/api/v2/impact", json=body, headers=headers)
    second = client.post("/api/v2/impact", json=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()
    assert first.json()["co2"]["status"] == "not_estimated"
    assert calls["n"] == 1
    conflict = client.post(
        "/api/v2/impact",
        json={**body, "baseline_run_id": "run_b"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert calls["n"] == 1
