"""Tests for the service-layer business logic."""

from __future__ import annotations

from app import services
from app.database import SessionLocal
from app.models import FixSession, Issue, IssueStatus
from app.webhook import IssueEvent
from tests.fakes import FakeDevinClient, FakeGitHubClient, details


def _event(label="devin-fix", labels=None, number=1):
    return IssueEvent(
        action="labeled",
        repo="org/repo",
        number=number,
        github_id=100 + number,
        title="Bug title",
        body="Bug body",
        html_url=f"https://github.com/org/repo/issues/{number}",
        labels=labels if labels is not None else ["bug", label],
        label_added=label,
    )


def test_build_prompt_includes_link_and_title():
    issue = Issue(
        repo="org/repo", number=5, title="Crash", body="boom",
        html_url="https://github.com/org/repo/issues/5",
    )
    prompt = services.build_prompt(issue)
    assert "Crash" in prompt
    assert "boom" in prompt
    assert "https://github.com/org/repo/issues/5" in prompt


def test_record_issue_ignores_non_trigger_label():
    with SessionLocal() as db:
        issue, auto = services.record_issue_from_event(db, _event(label="question"))
    assert issue is None
    assert auto is False


def test_record_issue_creates_pending():
    with SessionLocal() as db:
        issue, auto = services.record_issue_from_event(db, _event())
        assert issue is not None
        assert issue.status == IssueStatus.PENDING_APPROVAL
        assert auto is False


def test_record_issue_auto_approve_label():
    with SessionLocal() as db:
        ev = _event(label="devin-fix", labels=["devin-fix", "devin-fix-auto"])
        issue, auto = services.record_issue_from_event(db, ev)
        assert auto is True
        assert issue.auto_approved is True


def test_approve_creates_session():
    fake = FakeDevinClient()
    with SessionLocal() as db:
        issue, _ = services.record_issue_from_event(db, _event())
        issue = services.approve_issue(db, issue, devin_client=fake)
        assert issue.status == IssueStatus.RUNNING
        assert issue.session is not None
        assert issue.session.devin_session_id == "devin-1"
        assert len(fake.created) == 1


def test_decline_closes_issue():
    fake_gh = FakeGitHubClient()
    with SessionLocal() as db:
        issue, _ = services.record_issue_from_event(db, _event())
        issue = services.decline_issue(db, issue, "duplicate", github_client=fake_gh)
        assert issue.status == IssueStatus.DECLINED
        assert issue.decline_reason == "duplicate"
        assert fake_gh.closed and fake_gh.closed[0][1] == 1


def test_sync_session_marks_completed_with_pr():
    devin = FakeDevinClient()
    with SessionLocal() as db:
        issue, _ = services.record_issue_from_event(db, _event())
        services.approve_issue(db, issue, devin_client=devin)
        session = db.get(FixSession, issue.session.id)

    devin_done = FakeDevinClient(
        details(
            status_enum="finished",
            pr_url="https://github.com/org/repo/pull/12",
            structured_output={"summary": "Fixed the null deref"},
        )
    )
    with SessionLocal() as db:
        session = db.get(FixSession, session.id)
        services.sync_session(db, session, devin_client=devin_done)
        assert session.status == "finished"
        assert session.pr_url.endswith("/pull/12")
        assert session.result_summary == "Fixed the null deref"
        assert session.completed_at is not None
        assert session.issue.status == IssueStatus.COMPLETED


def test_sync_session_completes_on_merged_pr():
    """A session with a merged PR should transition to COMPLETED even if Devin is still running."""
    devin = FakeDevinClient()
    with SessionLocal() as db:
        issue, _ = services.record_issue_from_event(db, _event(number=3))
        services.approve_issue(db, issue, devin_client=devin)
        sid = issue.session.id

    devin_merged = FakeDevinClient(
        details(
            status_enum="waiting_for_user",
            pr_url="https://github.com/org/repo/pull/42",
            pr_state="merged",
        )
    )
    with SessionLocal() as db:
        session = db.get(FixSession, sid)
        services.sync_session(db, session, devin_client=devin_merged)
        assert session.pr_state == "merged"
        assert session.issue.status == IssueStatus.COMPLETED
        assert session.completed_at is not None


def test_sync_session_marks_failed_on_expired():
    devin = FakeDevinClient()
    with SessionLocal() as db:
        issue, _ = services.record_issue_from_event(db, _event(number=2))
        services.approve_issue(db, issue, devin_client=devin)
        sid = issue.session.id

    devin_fail = FakeDevinClient(details(status_enum="expired"))
    with SessionLocal() as db:
        session = db.get(FixSession, sid)
        services.sync_session(db, session, devin_client=devin_fail)
        assert session.issue.status == IssueStatus.FAILED
