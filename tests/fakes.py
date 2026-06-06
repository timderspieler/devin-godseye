"""Fake Devin / GitHub clients for tests."""

from __future__ import annotations

from app.devin_client import CreatedSession, SessionDetails


class FakeDevinClient:
    def __init__(self, details: SessionDetails | None = None) -> None:
        self.created: list[str] = []
        self.terminated: list[tuple[str, bool]] = []
        self._details = details

    def create_session(self, prompt, title=None, tags=None, max_acu_limit=None, idempotent=False):
        sid = f"devin-{len(self.created) + 1}"
        self.created.append(prompt)
        return CreatedSession(session_id=sid, url=f"https://app.devin.ai/sessions/{sid}")

    def terminate_session(self, session_id, archive=True):
        self.terminated.append((session_id, archive))

    def get_session(self, session_id):
        if self._details is not None:
            return self._details
        return SessionDetails(
            session_id=session_id,
            status="running",
            status_enum="working",
            pr_url=None,
            pr_state=None,
            structured_output=None,
            title="t",
            updated_at=None,
            raw={},
        )


class FakeGitHubClient:
    def __init__(self, issues: list[dict] | None = None) -> None:
        self.closed: list[tuple[str, int, str | None]] = []
        self._issues: list[dict] = issues if issues is not None else []

    def comment_on_issue(self, repo, number, body):
        pass

    def close_issue(self, repo, number, comment=None, state_reason="not_planned"):
        self.closed.append((repo, number, comment))

    def list_issues(self, repo, labels="", state="open", per_page=100):
        if labels:
            label_set = {part.strip().lower() for part in labels.split(",")}
            return [
                i
                for i in self._issues
                if label_set & {lbl.get("name", "").lower() for lbl in i.get("labels", [])}
            ]
        return list(self._issues)


def details(
    status_enum="finished",
    pr_url=None,
    pr_state=None,
    structured_output=None,
    status: str | None = None,
) -> SessionDetails:
    return SessionDetails(
        session_id="devin-1",
        status=status if status is not None else status_enum,
        status_enum=status_enum,
        pr_url=pr_url,
        pr_state=pr_state,
        structured_output=structured_output,
        title="t",
        updated_at=None,
        raw={},
    )
