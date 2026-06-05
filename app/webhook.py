"""GitHub webhook signature verification and payload parsing."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any


def verify_signature(payload_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify a GitHub ``X-Hub-Signature-256`` header.

    If no secret is configured, verification is skipped (returns True) so the
    service is usable in local/dev setups without a webhook secret.
    """
    if not secret:
        return True
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@dataclass
class IssueEvent:
    action: str
    repo: str
    number: int
    github_id: int | None
    title: str
    body: str
    html_url: str
    labels: list[str] = field(default_factory=list)
    label_added: str | None = None


def parse_issue_event(payload: dict[str, Any]) -> IssueEvent | None:
    """Parse a GitHub ``issues`` webhook payload into an IssueEvent.

    Returns None if the payload does not contain an issue (e.g. ping events).
    """
    issue = payload.get("issue")
    if not issue:
        return None
    repo = (payload.get("repository") or {}).get("full_name", "")
    label_added = None
    if payload.get("action") == "labeled":
        label_added = (payload.get("label") or {}).get("name")
    return IssueEvent(
        action=payload.get("action", ""),
        repo=repo,
        number=issue.get("number"),
        github_id=issue.get("id"),
        title=issue.get("title", ""),
        body=issue.get("body") or "",
        html_url=issue.get("html_url", ""),
        labels=[lbl.get("name", "") for lbl in issue.get("labels", [])],
        label_added=label_added,
    )
