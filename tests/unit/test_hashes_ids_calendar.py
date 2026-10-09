import math
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aabflow.domain import calendar as cal
from aabflow.domain import hashes, ids


def test_canonical_json_is_order_independent_for_keys_and_sets():
    a = {"b": 1, "a": [3, 1], "ids": {"y", "x"}}
    b = {"ids": {"x", "y"}, "a": [3, 1], "b": 1}
    assert hashes.content_hash(a) == hashes.content_hash(b)
    # Lists keep semantic order.
    assert hashes.content_hash({"a": [1, 3]}) != hashes.content_hash({"a": [3, 1]})


def test_decimals_have_one_representation():
    assert hashes.canonical_json(Decimal("1.50")) == hashes.canonical_json(Decimal("1.5"))
    assert hashes.canonical_json(Decimal("1E+2")) == '{"$decimal":"100"}'


def test_rejects_nonfinite_and_naive_datetimes():
    with pytest.raises(hashes.CanonicalizationError):
        hashes.canonical_json({"x": math.nan})
    with pytest.raises(hashes.CanonicalizationError):
        hashes.canonical_json(datetime(2026, 10, 10))


def test_aware_instants_normalize_to_utc():
    pkt = datetime(2026, 10, 10, 8, 0, tzinfo=cal.PKT)
    utc = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
    assert hashes.canonical_json(pkt) == hashes.canonical_json(utc)


def test_ids():
    a, b = ids.new_id("run"), ids.new_id("run")
    assert a != b and a.startswith("run_")
    assert ids.source_id("osm", "way/123") == "osm:way/123"
    with pytest.raises(ValueError):
        ids.new_id("Bad-Prefix")


def test_local_crop_date_uses_karachi():
    # 20:30 UTC on 9 Oct is 01:30 on 10 Oct in PKT (UTC+5).
    assert cal.local_crop_date(cal.parse_instant("2026-10-09T20:30:00Z")) == date(2026, 10, 10)
    with pytest.raises(ValueError):
        cal.local_crop_date(datetime(2026, 10, 10))
