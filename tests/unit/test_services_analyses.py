"""Pure analysis math (T7.1, T7.3, T7.4): nondominance, objective-difference intervals, synergy bounds."""

import pytest

from aabflow.services import analyses as A


def pt(pid, obj, ub=None, capex=0.0, svc=0.5, outcome="plan", q=0.0):
    return {
        "point_id": pid,
        "outcome": outcome,
        "objective_value": obj,
        "objective_upper_bound": ub,
        "capital_commitment_pkr": capex,
        "min_service_ratio": svc,
        "quantization_bound": q,
    }


def test_difference_interval_exact_and_overlapping_bounds():
    a, b = pt("a", 100.0, 100.0), pt("b", 90.0, 90.0)
    d = A.difference_interval(a, b)
    assert d["status"] == "exact" and d["point"] == pytest.approx(-10.0)
    a, b = pt("a", 100.0, 120.0), pt("b", 90.0, 105.0)
    d = A.difference_interval(a, b)  # [L_b - U_a, U_b - L_a]
    assert d["status"] == "interval" and d["point"] is None
    assert (d["lower"], d["upper"]) == pytest.approx((90 - 120, 105 - 100))
    d = A.difference_interval(a, pt("c", None, outcome="no_plan"))
    assert d["status"] == "not_comparable" and d["lower"] is None


def test_quantization_counts_as_exact():
    d = A.difference_interval(pt("a", 100.0, 100.3, q=0.4), pt("b", 90.0, 90.4, q=0.4))
    assert d["status"] == "exact"


def test_frontier_classification():
    pts = [
        pt("cheap", 100.0, 100.0, capex=0),
        pt("rich", 150.0, 150.0, capex=500),
        pt("waste", 140.0, 140.0, capex=600),  # dominated by rich: less output, more capital
        pt("maybe", 140.0, 160.0, capex=600),  # dominated by incumbents but its bound overlaps
        pt("none", None, outcome="no_plan"),
    ]
    A.classify_frontier(pts)
    d = {p["point_id"]: p["dominance"] for p in pts}
    assert d == {
        "cheap": "nondominated",
        "rich": "nondominated",
        "waste": "dominated",
        "maybe": "dominance_unresolved",
        "none": "not_applicable",
    }
    assert pts[2]["dominated_by"] == ["rich", "maybe"] or "rich" in pts[2]["dominated_by"]


def test_equal_points_do_not_dominate_each_other():
    pts = [pt("a", 100.0, 100.0, capex=10), pt("b", 100.0, 100.0, capex=10)]
    A.classify_frontier(pts)
    assert {p["dominance"] for p in pts} == {"nondominated"}


def arms(none, a, b, ab, ub=None):
    out = {}
    for k, v in (("none", none), ("a", a), ("b", b), ("ab", ab)):
        out[k] = {
            "objective_value": v,
            "objective_upper_bound": (ub or {}).get(k, v),
            "outcome": "plan",
        }
    return out


@pytest.mark.parametrize(
    "vals,sign",
    [((10, 15, 14, 25), "positive"), ((10, 15, 14, 17), "negative"), ((10, 12, 13, 15), "zero")],
)
def test_synergy_sign_and_value(vals, sign):
    s = A.synergy(arms(*vals))
    none, a, b, ab = vals
    assert (
        s["status"] == "exact"
        and s["value"] == pytest.approx(ab - a - b + none)
        and s["sign"] == sign
    )


def test_synergy_interval_with_unresolved_bounds_and_missing_arm():
    s = A.synergy(arms(10, 15, 14, 25, ub={"ab": 27, "a": 16}))
    assert s["status"] == "interval" and s["value"] is None
    assert s["lower"] == pytest.approx(25 - 16 - 14 + 10) and s["upper"] == pytest.approx(
        27 - 15 - 14 + 10
    )
    assert s["sign"] == "positive"  # lower bound > 0 even though unresolved
    bad = arms(10, 15, 14, 25)
    bad["ab"] = {"objective_value": None, "outcome": "no_plan"}
    s = A.synergy(bad)
    assert s["status"] == "not_available" and s["value"] is None and "ab" in s["reason"]


def test_request_validation():
    with pytest.raises(ValueError):
        A.FrontierRequest(
            base_revision_id="r", settings=[{"capital_budget_pkr": i} for i in range(5)]
        )
    with pytest.raises(ValueError):
        A.SynergyRequest(base_revision_id="r", instance_a="x", instance_b="x")
    with pytest.raises(ValueError):
        A.SensitivityRequest(
            base_revision_id="r", parameter="uniform_reduction_fraction", values=[0.1, 1.0]
        )
    fs = A.FrontierSetting(capital_budget_pkr=5, minimum_service_ratio=0.5)
    assert fs.service_group == "all"
