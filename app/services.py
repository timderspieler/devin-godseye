"""Business logic: recording issues, approving/declining, and syncing sessions."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.devin_client import DevinClient
from app.github_client import GitHubClient
from app.models import (
    FAILURE_STATUSES,
    SUCCESS_STATUSES,
    FixSession,
    Issue,
    IssueStatus,
)
from app.webhook import IssueEvent

logger = logging.getLogger("godseye.services")


def build_prompt(issue: Issue) -> str:
    """Build the Devin session prompt from an issue."""
    body = (issue.body or "").strip() or "(no description provided)"
    return (
        f"A GitHub issue in `{issue.repo}` has been labeled for an automated fix.\n\n"
        f"Title: {issue.title}\n\n"
        f"Description:\n{body}\n\n"
        f"GitHub issue link: {issue.html_url}\n\n"
        "Please investigate and fix this issue. You can pull additional context "
        "directly from the GitHub issue link above (comments, linked PRs, etc.). "
        "When you are done, open a pull request that resolves the issue and "
        "reference the issue number in the PR description. Provide a concise "
        "summary of the root cause and how you fixed it."
    )


def get_issue(db: Session, issue_id: int) -> Issue | None:
    return db.get(Issue, issue_id)


def find_issue_by_repo_number(db: Session, repo: str, number: int) -> Issue | None:
    return db.scalar(select(Issue).where(Issue.repo == repo, Issue.number == number))


def record_issue_from_event(
    db: Session, event: IssueEvent, settings: Settings | None = None
) -> tuple[Issue | None, bool]:
    """Record an incoming labeled issue.

    Returns (issue, should_auto_approve). Returns (None, False) when the event
    does not match the configured trigger labels.
    """
    settings = settings or get_settings()
    triggers = settings.trigger_label_set

    # Only react to a "labeled" action where the added label is a trigger.
    added = (event.label_added or "").lower()
    if added not in triggers:
        return None, False

    existing = find_issue_by_repo_number(db, event.repo, event.number)
    auto = bool(settings.auto_approve_label_set & {lbl.lower() for lbl in event.labels})

    if existing:
        # Refresh metadata but never re-open an issue we've already acted on.
        existing.title = event.title
        existing.body = event.body
        existing.labels = ",".join(event.labels)
        db.commit()
        db.refresh(existing)
        should_auto = auto and existing.status == IssueStatus.PENDING_APPROVAL
        return existing, should_auto

    issue = Issue(
        repo=event.repo,
        number=event.number,
        github_id=event.github_id,
        title=event.title,
        body=event.body,
        html_url=event.html_url,
        labels=",".join(event.labels),
        trigger_label=event.label_added or "",
        status=IssueStatus.PENDING_APPROVAL,
        auto_approved=auto,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue, auto


def approve_issue(
    db: Session, issue: Issue, devin_client: DevinClient | None = None
) -> Issue:
    """Approve an issue: create a Devin session and store the mapping."""
    if issue.status not in (IssueStatus.PENDING_APPROVAL, IssueStatus.APPROVED):
        raise ValueError(
            f"Issue {issue.id} cannot be approved from status {issue.status.value}"
        )
    if issue.session is not None:
        raise ValueError(f"Issue {issue.id} already has a session")

    settings = get_settings()
    client = devin_client or DevinClient()
    created = client.create_session(
        prompt=build_prompt(issue),
        title=f"Fix {issue.repo}#{issue.number}: {issue.title}"[:200],
        tags=["godseye", "devin-fix", f"{issue.repo}#{issue.number}"],
        max_acu_limit=settings.session_max_acu_limit,
    )

    session = FixSession(
        issue_id=issue.id,
        devin_session_id=created.session_id,
        devin_session_url=created.url,
        status="working",
    )
    db.add(session)
    issue.status = IssueStatus.RUNNING
    db.commit()
    db.refresh(issue)
    logger.info("Created session %s for issue %s", created.session_id, issue.id)
    return issue


def decline_issue(
    db: Session,
    issue: Issue,
    reason: str,
    github_client: GitHubClient | None = None,
) -> Issue:
    """Decline an issue: close the GitHub issue with a reason."""
    if issue.status != IssueStatus.PENDING_APPROVAL:
        raise ValueError(
            f"Issue {issue.id} cannot be declined from status {issue.status.value}"
        )
    client = github_client or GitHubClient()
    comment = (
        "This issue was reviewed by Devin Godseye and declined for an automated fix.\n\n"
        f"Reason: {reason.strip() or 'No reason provided.'}"
    )
    client.close_issue(issue.repo, issue.number, comment=comment)
    issue.status = IssueStatus.DECLINED
    issue.decline_reason = reason
    db.commit()
    db.refresh(issue)
    logger.info("Declined and closed issue %s", issue.id)
    return issue


def sync_session(
    db: Session, session: FixSession, devin_client: DevinClient | None = None
) -> FixSession:
    """Poll Devin for the latest status of a session and update local state."""
    client = devin_client or DevinClient()
    details = client.get_session(session.devin_session_id)

    status_enum = details.status_enum or details.status or session.status
    session.status = status_enum
    if details.pr_url:
        session.pr_url = details.pr_url
    if details.structured_output is not None:
        session.structured_output = json.dumps(details.structured_output)
        summary = _extract_summary(details.structured_output)
        if summary:
            session.result_summary = summary

    issue = session.issue
    if status_enum in SUCCESS_STATUSES:
        issue.status = IssueStatus.COMPLETED
        if session.completed_at is None:
            session.completed_at = datetime.now(UTC)
    elif status_enum in FAILURE_STATUSES:
        issue.status = IssueStatus.FAILED
        if session.completed_at is None:
            session.completed_at = datetime.now(UTC)
    else:
        # working / blocked / resumed etc. -> still in progress.
        if issue.status not in (IssueStatus.COMPLETED, IssueStatus.FAILED):
            issue.status = IssueStatus.RUNNING

    db.commit()
    db.refresh(session)
    return session


def _extract_summary(structured_output: object) -> str | None:
    if isinstance(structured_output, dict):
        for key in ("summary", "result", "result_summary", "description"):
            value = structured_output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(structured_output)[:2000]
    if isinstance(structured_output, str):
        return structured_output.strip() or None
    return None
