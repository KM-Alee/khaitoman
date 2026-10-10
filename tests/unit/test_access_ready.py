"""Labelled temporary app fixture: edge-login return URL safety and HTML landing."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from aabflow.main import create_app
from tests.fixtures.api_app import settings_for


@pytest.fixture
def client(tmp_path):
    settings = replace(settings_for(tmp_path), cors_origins=("https://app.example.com",))
    with TestClient(create_app(settings)) as app:
        yield app


def test_access_landing_preserves_deep_link_and_escapes_html(client):
    target = 'https://app.example.com/p/pilot/v/report?run=real&id="quoted"#result'
    response = client.get("/api/v2/access/ready", params={"return_to": target})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert (
        'content="0;url=https://app.example.com/p/pilot/v/report?run=real&amp;id=&quot;quoted&quot;#result"'
        in response.text
    )
    assert "Continue to the app" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/",
        "https://app.example.com.evil.example/",
        "https://user:pass@app.example.com/",
        "//app.example.com/",
        "javascript:alert(1)",
        "http://app.example.com/",
        "https://app.example.com\\@evil.example/",
        "https://app.example.com/\nmalformed",
        "https://[malformed/",
    ],
)
def test_access_landing_rejects_untrusted_return_urls(client, target):
    response = client.get("/api/v2/access/ready", params={"return_to": target})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"
    assert "location" not in response.headers


def test_access_landing_requires_bounded_return_url(client):
    assert client.get("/api/v2/access/ready").status_code == 422
    assert (
        client.get(
            "/api/v2/access/ready", params={"return_to": "https://app.example.com/" + "x" * 2048}
        ).status_code
        == 422
    )
