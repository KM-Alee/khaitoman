"""Visual contract unit tests: datasets are server-materialized, specs only choose columns/charts.

TEST FIXTURE rows below are synthetic and labelled; no product number comes from them.
"""

from __future__ import annotations

import pytest

from aabflow.copilot.answer_validation import FINAL_ANSWER_TOOL, Facts, unsupported_numbers
from aabflow.copilot.contract import CopilotAnswer
from aabflow.copilot.registry import check_strict
from aabflow.copilot.visuals import (
    Column,
    DatasetSource,
    DatasetStore,
    Encoding,
    VisualSpec,
    default_visual,
    materialize,
)


def spec(**kw):
    base = {
        "dataset_id": "ds1",
        "chart": "bar",
        "title": "t",
        "caption": None,
        "x": None,
        "y": None,
        "series": None,
        "sort": None,
        "limit": None,
        "highlight_ids": None,
    }
    base.update(kw)
    return VisualSpec(**base)


@pytest.fixture
def store():
    s = DatasetStore()
    s.add(  # TEST FIXTURE dataset
        kind="field_outcomes",
        title="Fixture field results",
        columns=[
            Column(key="field", label="Field", kind="category"),
            Column(key="field_id", label="Field ID", kind="id", ref="field"),
            Column(key="group", label="Group", kind="category"),
            Column(key="production_kg", label="Production", unit="kg", basis="model_output"),
            Column(key="run_id", label="Run", kind="id", ref="run"),
        ],
        rows=[
            {
                "field": "F1",
                "field_id": "fx:f1",
                "group": "head",
                "production_kg": 10.0,
                "run_id": "run_x",
            },
            {
                "field": "F2",
                "field_id": "fx:f2",
                "group": "tail",
                "production_kg": None,
                "run_id": "run_x",
            },
            {
                "field": "F3",
                "field_id": "fx:f3",
                "group": "tail",
                "production_kg": 30.0,
                "run_id": "run_x",
            },
            {
                "field": "F4",
                "field_id": "fx:f4",
                "group": "tail",
                "production_kg": float("nan"),
                "run_id": "run_x",
            },
        ],
        charts=["bar", "map"],
        defaults={
            "bar": Encoding(x="field", y=["production_kg"], id="field_id"),
            "map": Encoding(id="field_id", value="production_kg"),
        },
        source=DatasetSource(tool="inspect_run", call_id="call_1", run_ids=["run_x"]),
        basis=["model_output"],
    )
    return s


def test_materialize_copies_rows_and_provenance(store):
    m = materialize(spec(sort="desc", highlight_ids=["fx:f3", "fx:other"]), store, "v1")
    assert m.issues == [] and m.block is not None
    b = m.block
    assert [r["field"] for r in b.rows] == ["F3", "F1", "F2", "F4"]  # gaps last, never zero
    assert b.rows[3]["production_kg"] is None  # NaN cleaned to a gap
    assert b.source.run_ids == ["run_x"] and b.source.call_id == "call_1"
    assert b.highlight_ids == ["fx:f3"] and any("ignored" in n for n in b.notes)
    assert {i.intent for i in b.interactions} == {"open_field", "open_run"}
    assert b.table_fallback is True and b.columns[3].unit == "kg"


def test_limit_and_table_columns(store):
    b = materialize(spec(chart="table", y=["production_kg"], limit=2), store, "v1").block
    assert len(b.rows) == 2 and b.truncated is True
    assert {c.key for c in b.columns} == {"production_kg", "field_id", "run_id"}


@pytest.mark.parametrize(
    "bad,needle",
    [
        ({"dataset_id": "ds9"}, "was not returned"),
        ({"chart": "sankey"}, "supports"),
        ({"y": ["group"]}, "needs number"),
        ({"x": "nope"}, "does not exist"),
    ],
)
def test_invalid_specs_rejected(store, bad, needle):
    m = materialize(spec(**bad), store, "v1")
    assert m.block is None and any(needle in i for i in m.issues), m.issues


def test_map_needs_field_ids(store):
    m = materialize(spec(chart="map"), store, "v1")
    assert m.block is not None and m.block.encoding.id == "field_id"


def test_default_visual_is_marked_auto(store):
    b = default_visual(store.get("ds1"), "v1")
    assert b.auto is True and b.chart == "bar"


def test_final_answer_schema_is_strict_and_contract_round_trips(store):
    assert check_strict(FINAL_ANSWER_TOOL["parameters"]) == []
    props = FINAL_ANSWER_TOOL["parameters"]["properties"]
    assert {"headline", "visuals", "follow_ups"} <= set(props)
    b = materialize(spec(), store, "v1").block
    ans = CopilotAnswer(
        language="en",
        blocks=[
            {"type": "headline", "text": "Tail fields gain most."},
            b.model_dump(mode="json"),
            {"type": "follow_ups", "questions": ["Why?"]},
        ],
        validated=True,
    )
    assert ans.blocks[1].type == "visual"


def test_caption_numbers_are_checked():
    facts = Facts()
    facts.add({"run_id": "run_x", "production_kg": 154117.9})
    assert unsupported_numbers("About 154 t in total", facts) == []
    assert unsupported_numbers("About 999 t in total", facts) == ["999 t"]


def test_action_kind_follows_the_id():
    from aabflow.copilot.answer_validation import action_for_id

    assert action_for_id("run_abc") == "open_run"
    assert action_for_id("ana_abc") == "open_analysis"
    assert action_for_id("rev_abc") == "open_branch"
    assert action_for_id("cmp_abc") == "open_comparison"
    assert action_for_id("rpt_abc") == "open_report"
    assert action_for_id("pilot-a:field-001") == "open_field"
