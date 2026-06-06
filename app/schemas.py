"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import FixSession, Issue


class DeclineRequest(BaseModel):
    reason: str = ""


class SessionView(BaseModel):
    devin_session_id: str
    devin_session_url: str
    status: str
    pr_url: str | None = None
    pr_state: str | None = None
    result_summary: str | None = None
    structured_output: Any | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_model(cls, session: FixSession) -> SessionView:
        structured: Any | None = None
        if session.structured_output:
            try:
                structured = json.loads(session.structured_output)
            except (ValueError, TypeError):
                structured = session.structured_output
        return cls(
            devin_session_id=session.devin_session_id,
            devin_session_url=session.devin_session_url,
            status=session.status,
            pr_url=session.pr_url,
            pr_state=session.pr_state,
            result_summary=session.result_summary,
            structured_output=structured,
            created_at=session.created_at,
            updated_at=session.updated_at,
            completed_at=session.completed_at,
        )


class IssueView(BaseModel):
    id: int
    repo: str
    number: int
    title: str
    body: str
    html_url: str
    labels: list[str]
    trigger_label: str
    status: str
    auto_approved: bool
    decline_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    session: SessionView | None = None

    @classmethod
    def from_model(cls, issue: Issue) -> IssueView:
        return cls(
            id=issue.id,
            repo=issue.repo,
            number=issue.number,
            title=issue.title,
            body=issue.body or "",
            html_url=issue.html_url,
            labels=issue.label_list,
            trigger_label=issue.trigger_label,
            status=issue.status.value,
            auto_approved=issue.auto_approved,
            decline_reason=issue.decline_reason,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            session=SessionView.from_model(issue.session) if issue.session else None,
        )
