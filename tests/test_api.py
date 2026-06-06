"""End-to-end tests for the HTTP API and webhook via TestClient."""

from __future__ import annotations

import pytest

from app import scanner, services
from tests.fakes import FakeDevinClient, FakeGitHubClient


@pytest.fixture()
def fake_devin(monkeypatch):
    fake = FakeDevinClient()
    monkeypatch.setattr(services, "DevinClient", lambda *a, **k: fake)
    return fake


@pytest.fixture()
def fake_github(monkeypatch):
    fake = FakeGitHubClient()
    monkeypatch.setattr(services, "GitHubClient", lambda *a, **k: fake)
    return fake


def _webhook_payload(number=1, labels=None, added="devin-fix"):
    return {
        "action": "labeled",
        "label": {"name": added},
        "repository": {"full_name": "timderspieler/superset"},
        "issue": {
            "number": number,
            "id": 5000 + number,
            "title": "Something is broken",
            "body": "Steps to reproduce...",
            "html_url": f"https://github.com/timderspieler/superset/issues/{number}",
            "labels": labels or [{"name": added}],
        },
    }


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_dashboard_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Devin Godseye" in res.text


def test_webhook_records_pending(client):
    res = client.post(
        "/webhooks/github",
        json=_webhook_payload(),
        headers={"X-GitHub-Event": "issues"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "recorded"
    assert data["issue_status"] == "pending_approval"

    listing = client.get("/api/issues").json()
    assert len(listing["pending"]) == 1


def test_webhook_ignores_non_trigger_label(client):
    res = client.post(
        "/webhooks/github",
        json=_webhook_payload(added="question"),
        headers={"X-GitHub-Event": "issues"},
    )
    assert res.json()["status"] == "ignored"


def test_webhook_ping(client):
    res = client.post(
        "/webhooks/github", json={"zen": "x"}, headers={"X-GitHub-Event": "ping"}
    )
    assert res.json()["status"] == "pong"


def test_webhook_auto_approve(client, fake_devin):
    payload = _webhook_payload(
        number=2, labels=[{"name": "devin-fix"}, {"name": "devin-fix-auto"}]
    )
    res = client.post(
        "/webhooks/github", json=payload, headers={"X-GitHub-Event": "issues"}
    )
    assert res.json()["auto_approved"] is True
    listing = client.get("/api/issues").json()
    assert len(listing["active"]) == 1
    assert len(fake_devin.created) == 1


def test_approve_flow(client, fake_devin):
    client.post(
        "/webhooks/github", json=_webhook_payload(), headers={"X-GitHub-Event": "issues"}
    )
    issue_id = client.get("/api/issues").json()["pending"][0]["id"]

    res = client.post(f"/api/issues/{issue_id}/approve")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "running"
    assert body["session"]["devin_session_id"] == "devin-1"


def test_decline_flow(client, fake_github):
    client.post(
        "/webhooks/github", json=_webhook_payload(), headers={"X-GitHub-Event": "issues"}
    )
    issue_id = client.get("/api/issues").json()["pending"][0]["id"]

    res = client.post(f"/api/issues/{issue_id}/decline", json={"reason": "wontfix"})
    assert res.status_code == 200
    assert res.json()["status"] == "declined"
    assert fake_github.closed[0][1] == 1

    # Declining again should conflict.
    assert client.post(f"/api/issues/{issue_id}/decline", json={"reason": "x"}).status_code == 409


def test_approve_missing_issue(client):
    assert client.post("/api/issues/999/approve").status_code == 404


def test_scan_endpoint(client, monkeypatch):
    gh = FakeGitHubClient(
        issues=[
            {
                "number": 10,
                "id": 9010,
                "title": "Scanned bug",
                "body": "found via scan",
                "html_url": "https://github.com/timderspieler/superset/issues/10",
                "labels": [{"name": "devin-fix"}],
            }
        ]
    )
    monkeypatch.setattr(scanner, "GitHubClient", lambda *a, **k: gh)
    monkeypatch.setattr(scanner, "DevinClient", lambda *a, **k: FakeDevinClient())

    res = client.post("/api/scan")
    assert res.status_code == 200
    data = res.json()
    assert data["new_issues_recorded"] == 1

    listing = client.get("/api/issues").json()
    assert len(listing["pending"]) == 1
    assert listing["pending"][0]["number"] == 10
