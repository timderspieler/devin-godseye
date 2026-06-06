"""Fake Devin / GitHub clients for tests."""

from __future__ import annotations

from app.devin_client import CreatedSession, SessionDetails


class FakeDevinClient:
    def __init__(self, details: SessionDetails | None = None) -> None:
        self.created: list[str] = []
        self._details = details

    def create_session(self, prompt, title=None, tags=None, max_acu_limit=None, idempotent=False):
        sid = f"devin-{len(self.created) + 1}"
        self.created.append(prompt)
        return CreatedSession(session_id=sid, url=f"https://app.devin.ai/sessions/{sid}")

    def get_session(self, session_id):
        if self._details is not None:
            return self._details
        return SessionDetails(
            session_id=session_id,
            status="running",
            status_enum="working",
            pr_url=None,
            structured_output=None,
            title="t",
            updated_at=None,
            raw={},
        )


class FakeGitHubClient:
    def __init__(self) -> None:
        self.closed: list[tuple[str, int, str | None]] = []

    def comment_on_issue(self, repo, number, body):
        pass

    def close_issue(self, repo, number, comment=None, state_reason="not_planned"):
        self.closed.append((repo, number, comment))


def details(status_enum="finished", pr_url=None, structured_output=None) -> SessionDetails:
    return SessionDetails(
        session_id="devin-1",
        status=status_enum,
        status_enum=status_enum,
        pr_url=pr_url,
        structured_output=structured_output,
        title="t",
        updated_at=None,
        raw={},
    )
