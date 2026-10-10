"""Landing showcase: ``GET /demo/headline`` story rules and ``GET /ai-stack`` sources.

Every metric list, manifest, review log and model file below is a labelled TEST FIXTURE written
in a temporary directory; none of these numbers are real results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aabflow.api import showcase
from aabflow.api.demo import manifest_path
from aabflow.main import create_app
from tests.fixtures.api_app import settings_for
from tests.integration.test_demo_session import fixture_manifest


def metrics(run_id: str, prod: float, tail: float, cap: float, gw: float) -> list[dict]:
    """TEST FIXTURE metrics.json rows."""
    rows = [
        ("production_kg", prod, "kg"),
        ("tail_min_service_ratio", tail, "ratio"),
        ("capital_commitment_pkr", cap, "PKR"),
        ("groundwater_m3", gw, "m3"),
    ]
    return [
        {
            "metric_id": m,
            "value": v,
            "unit": u,
            "status": "available",
            "run_id": run_id,
            "field_id": None,
        }
        for m, v, u in rows
    ]


def headline(b1_tail: float, p_tail: float, p_cap: float, *, p_gw: float = 0.0):
    return showcase.build_headline(
        pilot_id="pilot-a",
        pilot_version="v",
        season_id="s",
        revision_id="rev_fx",
        budget_pkr=1000.0,
        metrics_by_kind={
            "B0": ("run_fx_b0", metrics("run_fx_b0", 100.0, 0.6, 0.0, 0.0)),
            "B1": ("run_fx_b1", metrics("run_fx_b1", 110.0, b1_tail, 0.0, 5.0)),
            "P": ("run_fx_p", metrics("run_fx_p", 120.0, p_tail, p_cap, p_gw)),
        },
        created_at={},
    )


def test_tail_tradeoff_story_and_derived_figures():
    h = headline(b1_tail=0.4, p_tail=0.6, p_cap=650.0, p_gw=8.0)
    assert h.story == "tail_tradeoff"
    assert h.production_gain_pct_vs_b0["B1"].value == pytest.approx(10.0)
    assert h.production_gain_pct_vs_b0["P"].value == pytest.approx(20.0)
    assert h.production_gain_pct_vs_b0["P"].run_ids == ["run_fx_b0", "run_fx_p"]
    assert h.tail_service_change_pts["B1"].value == pytest.approx(-20.0)
    assert h.tail_service_change_pts["P"].unit == "pct_points"
    assert h.budget_used_fraction.value == pytest.approx(0.65)
    assert h.groundwater_above_b0 is True


def test_budget_efficiency_story():
    h = headline(b1_tail=0.7, p_tail=0.7, p_cap=400.0)
    assert h.story == "budget_efficiency"
    assert h.groundwater_above_b0 is False


def test_plain_gain_story():
    assert headline(b1_tail=0.7, p_tail=0.7, p_cap=900.0).story == "plain_gain"


def test_missing_metric_gives_none_with_reason_never_zero():
    rows = [r for r in metrics("run_fx", 1, 1, 1, 1) if r["metric_id"] != "groundwater_m3"]
    f = showcase.plan_figures("run_fx", rows)
    assert f.groundwater_m3.value is None and "not recorded" in (f.groundwater_m3.reason or "")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as c:
        yield c, tmp_path


def test_headline_404_without_manifest(client):
    c, _ = client
    r = c.get("/api/v2/demo/headline")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_headline_404_when_a_run_is_missing(client):
    c, tmp = client
    p = manifest_path(tmp)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(fixture_manifest()))
    r = c.get("/api/v2/demo/headline")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_ai_stack_without_sources_is_unavailable_not_zero(client):
    c, _ = client
    showcase._FILE_CACHE.clear()
    r = c.get("/api/v2/ai-stack")
    assert r.status_code == 200, r.text
    eng = {e["id"]: e for e in r.json()["engines"]}
    assert list(eng) == ["sees", "predicts", "plans", "explains"]
    for k in ("sees", "predicts", "plans"):
        assert (
            eng[k]["status"] == "unavailable" and eng[k]["fact_value"] is None and eng[k]["reason"]
        )


def test_sees_and_predicts_read_fixture_files(tmp_path: Path):
    d = tmp_path / "pilots" / "pilot-x" / "v1"
    d.mkdir(parents=True)
    (d / "review_log.json").write_text(json.dumps({"summary": {"raw_polygons": 50, "selected": 7}}))
    (d / "manifest.json").write_text(
        json.dumps({"processing_versions": {"delineate_checkpoint": "ck"}})
    )
    sees = showcase.sees_engine(
        tmp_path / "pilots", [{"pilot_id": "pilot-x", "pilot_version": "v1"}]
    )
    assert sees.status == "available" and sees.fact_value == 50
    assert sees.by_pilot == {"pilot-x": {"raw_polygons": 50, "selected": 7}}

    m = tmp_path / "models"
    (m / "sv-fx").mkdir(parents=True)
    (m / "surrogate-latest.json").write_text(json.dumps({"model_version": "sv-fx"}))
    (m / "sv-fx" / "evaluation.json").write_text(
        json.dumps({"training_device": "gpu", "crops": {"wheat": {"test": {"nmae": 0.05}}}})
    )
    ev = tmp_path / "evidence" / "benchmarks"
    ev.mkdir(parents=True)
    (ev / "p04-preview-timing.json").write_text(
        json.dumps({"model_version": "sv-fx", "preview": {"elapsed_ms_after_load": 4.2}})
    )
    (tmp_path / "experiments" / "e1").mkdir(parents=True)
    pred = showcase.predicts_engine(tmp_path, tmp_path / "evidence")
    assert (
        pred.status == "available" and pred.fact_value == pytest.approx(4.2) and pred.unit == "ms"
    )
    assert any(f.label.startswith("crop-model experiments") and f.value == 1 for f in pred.facts)
