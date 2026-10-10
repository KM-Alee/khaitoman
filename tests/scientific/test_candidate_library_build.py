"""End-to-end library build on the labelled fixture pilot with real AquaCrop + published ERA5 analogs.

The pilot is a TEST FIXTURE (synthetic geometry/rights/costs); crop runs are real.
"""

import json
import shutil

import pytest

from aabflow.config import DATA_DIR as REPO_DATA
from aabflow.optimizer.candidates import build_library, load_library
from aabflow.science import scenarios
from aabflow.water.ledger import reconstruct
from tests.fixtures.science_fixture_pilot import FIXTURE_ID, science_env

pytestmark = pytest.mark.scientific
SEASON = "cotton-kharif-2027"


@pytest.fixture
def env(tmp_path, monkeypatch):
    science_env(tmp_path, monkeypatch, weather=False)
    src = REPO_DATA / "libraries"
    assert (src / "weather_scenarios.json").exists(), "run scripts/science_publish.py first"
    doc = json.loads((src / "weather_scenarios.json").read_text())
    doc["pilot_grid_cells"][FIXTURE_ID] = doc["default_grid_cell"]
    (tmp_path / "libraries" / "weather").mkdir(parents=True, exist_ok=True)
    (tmp_path / "libraries" / "weather_scenarios.json").write_text(json.dumps(doc))
    for row in doc["scenarios"]:
        if row["season_id"] == SEASON:
            f = f"{row['transformed_sha256']}.parquet"
            shutil.copy(src / "weather" / f, tmp_path / "libraries" / "weather" / f)
    scenarios.publish_supply([FIXTURE_ID])
    return tmp_path


def test_build_publish_load_reconstruct(env):
    lib = build_library(FIXTURE_ID, SEASON, workers=4)
    lib2, pols = load_library(FIXTURE_ID, SEASON)
    assert lib2.candidate_library_hash == lib.candidate_library_hash
    assert (env / "libraries" / FIXTURE_ID / SEASON / "latest.json").exists()
    assert len(lib.state_ids) == 9 and lib.typical_state_id == "typical__nominal-roster-v1"
    assert len(lib.configurations) == 2  # base + one shared repair (cotton leaves time to build)
    by_field: dict[tuple, list] = {}
    for p in pols:
        by_field.setdefault((p.field_id, p.shared_configuration_id), []).append(p)
    for (fid, cid), ps in by_field.items():
        fams = {p.family for p in ps}
        assert "rainfed" in fams and "baseline_B0" in fams, (fid, cid)
        assert all(o.deliverable for p in ps if p.family == "rainfed" for o in p.outcomes)
        assert 15 <= len(ps) <= 60
    # every deliverable outcome is backed by an exact finished crop run with the policy's water
    from aabflow.science.experiments import load_outcome

    for p in pols[:40]:
        for o in p.outcomes:
            if o.deliverable:
                co = load_outcome(o.crop_outcome_hash)
                assert co.has_finished and co.yield_kg_ha == pytest.approx(o.yield_kg_ha)
                assert co.seasonal_irrigation_mm == pytest.approx(p.gross_application_mm)
    # a plan: best typical-state deliverable policy per field under the base config, no pumps
    plan = []
    for fid in sorted({p.field_id for p in pols}):
        cands = [p for p in by_field[(fid, "cfg:base")] if not p.pump_events]
        best = max(
            cands,
            key=lambda p: next(
                o.production_kg or -1 for o in p.outcomes if o.state_id == lib.typical_state_id
            ),
        )
        plan.append(best.candidate_policy_id)
    events, rep = reconstruct(plan, lib, lib.typical_state_id, "cfg:base")
    assert rep.status == "passed", [r for r in rep.residuals if not r.passed]
    assert events and any(e.kind.value == "edge_loss" for e in events)
    # differentiation: the repair config changes tail receipts (cross-field coupling)
    tail_base = [p for p in by_field[("fx-f3", "cfg:base")] if p.family == "full_window"]
    tail_rep = [
        p for p in by_field[("fx-f3", "cfg:fx:fx-e-mid:repair")] if p.family == "full_window"
    ]
    assert max(p.receipt_volume_m3 for p in tail_rep) > max(p.receipt_volume_m3 for p in tail_base)
    cov = {c.field_id: c for c in lib.coverage}
    assert all(c.retained > 0 and c.generated >= c.retained for c in cov.values())
