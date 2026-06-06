"""Tests for the GitHub issue scanner."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import Issue
from app.scanner import scan_once
from tests.fakes import FakeDevinClient, FakeGitHubClient


def _gh_issue(number=1, title="Bug", body="desc", labels=None):
    labels = labels or [{"name": "devin-fix"}]
    return {
        "number": number,
        "id": 8000 + number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/timderspieler/superset/issues/{number}",
        "labels": labels,
    }


def test_scan_discovers_new_issues():
    gh = FakeGitHubClient(issues=[_gh_issue(1), _gh_issue(2)])
    recorded = scan_once(github_client=gh, devin_client=FakeDevinClient())
    assert recorded == 2
    with SessionLocal() as db:
        issues = db.query(Issue).all()
        assert len(issues) == 2
        assert {i.number for i in issues} == {1, 2}


def test_scan_skips_already_tracked():
    gh = FakeGitHubClient(issues=[_gh_issue(3)])
    recorded1 = scan_once(github_client=gh, devin_client=FakeDevinClient())
    assert recorded1 == 1
    # Running again should find 0 new issues.
    recorded2 = scan_once(github_client=gh, devin_client=FakeDevinClient())
    assert recorded2 == 0


def test_scan_auto_approves():
    gh = FakeGitHubClient(
        issues=[_gh_issue(4, labels=[{"name": "devin-fix"}, {"name": "devin-fix-auto"}])]
    )
    dv = FakeDevinClient()
    recorded = scan_once(github_client=gh, devin_client=dv)
    assert recorded == 1
    assert len(dv.created) == 1


def test_scan_ignores_non_matching_labels():
    gh = FakeGitHubClient(issues=[_gh_issue(5, labels=[{"name": "enhancement"}])])
    recorded = scan_once(github_client=gh, devin_client=FakeDevinClient())
    assert recorded == 0
