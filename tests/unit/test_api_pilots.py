"""Read-only pilot routes over the labelled TEST FIXTURE package."""

import pytest
from fastapi.testclient import TestClient

from aabflow.main import create_app
from tests.fixtures import synthetic as fx
from tests.fixtures.api_app import settings_for


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pilots")
    fx.build_all(tmp)
    with TestClient(create_app(settings_for(tmp))) as c:
        yield c


def test_pilot_list_and_version(client):
    body = client.get("/api/v2/pilots").json()
    assert [p["pilot_id"] for p in body["pilots"]] == [fx.PILOT_ID]
    p = body["pilots"][0]
    assert p["field_count"] == 4 and p["versions"] == [fx.VERSION]
    assert p["review_flags"]["rights_verification"] == "assumed"
    v = client.get(f"/api/v2/pilots/{fx.PILOT_ID}/versions/{fx.VERSION}").json()
    assert v["counts"]["fields"] == 4 and v["manifest"]["files"]
    assert len(v["package_sha256"]) == 64
    assert client.get(f"/api/v2/pilots/{fx.PILOT_ID}/versions/nope").json()["code"] == "NOT_FOUND"
    assert client.get("/api/v2/pilots/unknown/versions/x").status_code == 404


def test_map_refs_resolve_to_served_assets(client):
    m = client.get(f"/api/v2/pilots/{fx.PILOT_ID}/versions/{fx.VERSION}/map").json()
    assert m["fields_url"].startswith("/assets/pilots/fixture-a/test-v1/")
    assert len(m["imagery"][0]["corners"]) == 4
    assert m["terrain"]["encoding"] == "terrarium"
    assert {e["edge_id"] for e in m["network"]["edges"]} == {"e-main", "e-head", "e-tail"}
    assert any(e["geometry_ref"] is None for e in m["network"]["edges"])
    assert m["field_groups"]["fixture-a:f3"] == "tail"
    for url in (m["fields_url"], m["aoi_url"], m["canals_url"], m["imagery"][0]["url"], m["terrain"]["url"]):
        r = client.get(url)
        assert r.status_code == 200, url
    assert client.get(m["fields_url"]).headers["content-type"].startswith("application/geo+json")


@pytest.mark.parametrize(
    "rel",
    [
        "../../index.json",
        "..%2F..%2Findex.json",
        "imagery/../../../index.json",
        "/etc/passwd",
        "network.json/",
        "missing.json",
        "imagery//S2-TEST.png",
    ],
)
def test_asset_path_traversal_rejected(client, rel):
    r = client.get(f"/assets/pilots/{fx.PILOT_ID}/{fx.VERSION}/{rel}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_asset_bad_ids_rejected(client):
    assert client.get("/assets/pilots/..%2F/test-v1/pilot.json").status_code == 404
    assert client.get(f"/assets/pilots/{fx.PILOT_ID}/..%2F..%2F/pilot.json").status_code == 404


def test_field_detail(client):
    f = client.get("/api/v2/fields/fixture-a:f3", params={"pilot_version": fx.VERSION}).json()
    assert f["field"]["group"] == "tail"
    assert f["route_edge_ids"] == ["e-main", "e-tail"]
    assert [a["asset_id"] for a in f["assets"]] == ["fixture-a:pump-shared"]
    ids = {i["instance_id"] for i in f["interventions"]}
    assert {fx.POND_S, fx.POND_L, fx.REPAIR} <= ids
    assert len(f["roster_windows"][fx.SEASON_ID]) == 3
    assert f["soil"]["soil_profile_id"] == "fixture-loam"
    assert client.get("/api/v2/fields/nope").json()["code"] == "NOT_FOUND"


def test_seasons_weather_uncertainty(client):
    s = client.get("/api/v2/seasons", params={"pilot_id": fx.PILOT_ID}).json()["seasons"]
    assert {x["season"]["season_id"] for x in s} == {fx.SEASON_ID, fx.SEASON_LATE}
    assert all(x["library"]["ready"] is False for x in s)
    w = client.get("/api/v2/weather-scenarios", params={"season_id": fx.SEASON_ID}).json()["weather_scenarios"]
    assert sorted(x["weather_scenario_id"] for x in w) == sorted(fx.WEATHER)
    u = client.get("/api/v2/uncertainty-sets", params={"pilot_id": fx.PILOT_ID, "season_id": fx.SEASON_ID}).json()
    assert len(u["uncertainty_sets"][0]["states"]) == 9
    assert len(u["supply_profiles"]) == 3
    assert client.get("/api/v2/weather-scenarios", params={"season_id": "nope"}).status_code == 404


def test_interventions_eligibility(client):
    r = client.get("/api/v2/interventions", params={"pilot_id": fx.PILOT_ID, "season_id": fx.SEASON_ID}).json()
    by = {i["instance"]["instance_id"]: i for i in r["interventions"]}
    assert by[fx.LEVEL]["eligible"] is True
    late = by["fixture-a:f4:pond-late"]
    assert late["eligible"] is False and "after planting" in late["reasons"][0]
    nocost = by["fixture-a:f2:level-nocost"]
    assert nocost["eligible"] is False and "capex missing" in nocost["reasons"][0]
    naive = client.get(
        "/api/v2/interventions", params={"pilot_id": fx.PILOT_ID, "decision_at": "2026-10-10T08:00:00"}
    )
    assert naive.status_code == 422 and naive.json()["code"] == "INVALID_INPUT"


def test_evidence_lookup_and_search(client):
    e = client.get("/api/v2/evidence/ev-fixture-assets").json()
    assert e["record"]["kind"] == "assumption" and e["pilot_ids"] == [fx.PILOT_ID]
    hits = client.get("/api/v2/evidence/search", params={"q": "shared pump"}).json()["results"]
    assert any(h["doc_id"] == "ev-fixture-assets" for h in hits)
    m = client.get("/api/v2/evidence/search", params={"q": "infeasible finite candidate"}).json()["results"]
    assert any(h["kind"] == "methodology" for h in m)
    md = client.get("/api/v2/evidence/method:solver-proof-scope").json()
    assert md["document"]["kind"] == "methodology"
    # FTS syntax characters are neutralized, not executed
    assert client.get("/api/v2/evidence/search", params={"q": 'pump" OR NEAR(x'}).status_code == 200
    assert client.get("/api/v2/evidence/search", params={"q": ""}).status_code == 422
    assert client.get("/api/v2/evidence/nope").status_code == 404
