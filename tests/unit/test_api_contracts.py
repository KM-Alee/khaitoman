"""T9.1: one example per public request validates against the Pydantic contract, and the exported
OpenAPI document is current (regenerate with `make contracts`)."""

import json
from pathlib import Path

import pytest

from aabflow.api.runs import ComparisonRequest
from aabflow.api.scenarios import RevisionCreate, ScenarioCreate
from aabflow.domain.schemas import SolveRequest
from aabflow.services import analyses as A

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "contracts" / "examples"
MODELS = {
    "scenario_create": ScenarioCreate,
    "revision_create": RevisionCreate,
    "solve": SolveRequest,
    "comparison": ComparisonRequest,
    "analysis_frontier": A.FrontierRequest,
    "analysis_stress": A.StressRequest,
    "analysis_why_not": A.WhyNotRequest,
    "analysis_sensitivity": A.SensitivityRequest,
    "analysis_synergy": A.SynergyRequest,
}


@pytest.mark.parametrize("name", sorted(MODELS))
def test_request_examples_validate(name):
    MODELS[name].model_validate_json((EX / f"{name}.request.json").read_text())


def test_unknown_fields_and_nonfinite_rejected():
    body = json.loads((EX / "analysis_stress.request.json").read_text())
    with pytest.raises(ValueError):
        A.StressRequest.model_validate({**body, "surprise": 1})
    with pytest.raises(ValueError):
        A.SensitivityRequest.model_validate(
            {
                "base_revision_id": "r",
                "parameter": "capital_budget_pkr",
                "values": [1.0, float("nan")],
            }
        )


def test_surrogate_example_validates():
    pytest.importorskip("aquacrop")
    from aabflow.surrogate.prediction import PreviewRequest

    PreviewRequest.model_validate_json((EX / "surrogate_preview.request.json").read_text())


def test_openapi_export_is_current():
    from aabflow.main import app

    current = json.loads((ROOT / "contracts" / "openapi.json").read_text())
    assert current == json.loads(json.dumps(app.openapi(), sort_keys=True)), "run `make contracts`"
