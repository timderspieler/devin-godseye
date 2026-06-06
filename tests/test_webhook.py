"""Tests for webhook signature verification and payload parsing."""

from __future__ import annotations

import hashlib
import hmac

from app.webhook import parse_issue_event, verify_signature


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_valid():
    body = b'{"hello":"world"}'
    secret = "s3cret"
    assert verify_signature(body, _sign(body, secret), secret) is True


def test_verify_signature_invalid():
    body = b'{"hello":"world"}'
    assert verify_signature(body, "sha256=deadbeef", "s3cret") is False


def test_verify_signature_skipped_when_no_secret():
    assert verify_signature(b"x", None, "") is True


def test_parse_issue_event_labeled():
    payload = {
        "action": "labeled",
        "label": {"name": "devin-fix"},
        "repository": {"full_name": "org/repo"},
        "issue": {
            "number": 7,
            "id": 99,
            "title": "Crash on save",
            "body": "It crashes",
            "html_url": "https://github.com/org/repo/issues/7",
            "labels": [{"name": "bug"}, {"name": "devin-fix"}],
        },
    }
    event = parse_issue_event(payload)
    assert event is not None
    assert event.action == "labeled"
    assert event.label_added == "devin-fix"
    assert event.repo == "org/repo"
    assert event.number == 7
    assert "devin-fix" in event.labels


def test_parse_issue_event_no_issue():
    assert parse_issue_event({"zen": "ping"}) is None
