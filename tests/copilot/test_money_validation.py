"""Deterministic PKR parsing (T11.3) and prose-number grounding (T11.5)."""

import pytest

from aabflow.copilot.answer_validation import (
    Facts,
    refs_for_text,
    unsupported_numbers,
    withhold_sentences,
)
from aabflow.copilot.tools.money import AmountNeedsClarification, parse_pkr


@pytest.mark.parametrize(
    "text,pkr",
    [
        ("2 million", 2_000_000),
        ("PKR 2 million", 2_000_000),
        ("20 lakh", 2_000_000),
        ("bees lakh", 2_000_000),
        ("۲۰ لاکھ", 2_000_000),
        ("PKR 2,000,000", 2_000_000),
        ("Rs. 500k", 500_000),
        ("2.5m", 2_500_000),
        ("1 crore 20 lakh", 12_000_000),
        ("do crore", 20_000_000),
        ("dedh crore", 15_000_000),
        ("ڈیڑھ کروڑ روپے", 15_000_000),
        ("pachas hazar rupay", 50_000),
        ("20 lakh kar do", 2_000_000),
        ("one and a half million", 1_500_000),
        ("three hundred thousand", 300_000),
        ("0", 0),
        (150000, 150_000),
    ],
)
def test_parse_pkr(text, pkr):
    assert parse_pkr(text).pkr == pkr


@pytest.mark.parametrize(
    "text", ["$20,000", "2 million dollars", "20 bags", "", "€5k", "INR 2 lakh", "-5 lakh"]
)
def test_parse_pkr_needs_clarification(text):
    with pytest.raises(AmountNeedsClarification):
        parse_pkr(text)


def test_display_shows_lakh():
    assert parse_pkr("20 lakh").display == "PKR 2,000,000 (20 lakh)"


@pytest.fixture
def facts():
    f = Facts()
    f.add(
        {
            "run_id": "run_1",
            "metrics": [
                {"metric_id": "production_kg", "value": 123456.7},
                {"metric_id": "min_service_ratio", "value": 0.623},
            ],
            "capital_budget_pkr": 2000000,
            "delta": -512.4,
        }
    )
    return f


@pytest.mark.parametrize(
    "text",
    [
        "Production is 123,457 kg.",
        "about 123.5 t",
        "service 62%",
        "service 62.3%",
        "budget 20 lakh",
        "PKR 2,000,000",
        "fell by 512 kg",
        "field pilot-a:f3 and B0 on 2026-11-05 in 2026-27",
        "۲۰ لاکھ روپے",
        "3 fields are worse off",
    ],
)
def test_supported_numbers(facts, text):
    assert unsupported_numbers(text, facts) == []


@pytest.mark.parametrize(
    "text", ["production rose 5,000 kg", "a 7% gain", "PKR 2.5 million", "130,000 kg"]
)
def test_unsupported_numbers(facts, text):
    assert unsupported_numbers(text, facts)


def test_auto_citation_and_withhold(facts):
    assert refs_for_text("123,457 kg", facts) == ["run_1"]
    out = withhold_sentences("Production is 9,999 kg. Good plan.", ["9,999"], "en")
    assert "9,999" not in out and out.endswith("Good plan.")
