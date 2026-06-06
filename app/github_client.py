"""Thin client for the GitHub REST API (close issues, list issues)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class GitHubAPIError(RuntimeError):
    """Raised when the GitHub API returns an error response."""


class GitHubClient:
    """Minimal wrapper around the GitHub issues API."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.token = token if token is not None else settings.github_token
        self.base_url = (base_url or settings.github_api_base_url).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise GitHubAPIError("GITHUB_TOKEN is not configured")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def comment_on_issue(self, repo: str, number: int, body: str) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/repos/{repo}/issues/{number}/comments",
                headers=self._headers(),
                json={"body": body},
            )
        if resp.status_code >= 400:
            raise GitHubAPIError(
                f"comment_on_issue failed ({resp.status_code}): {resp.text}"
            )

    def list_issues(
        self,
        repo: str,
        labels: str = "",
        state: str = "open",
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Return issues for *repo* matching the given label(s).

        ``labels`` is a comma-separated string (GitHub API format).
        Paginates automatically until all matching issues are fetched.
        """
        all_issues: list[dict[str, Any]] = []
        page = 1
        while True:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/repos/{repo}/issues",
                    headers=self._headers(),
                    params={
                        "labels": labels,
                        "state": state,
                        "per_page": per_page,
                        "page": page,
                    },
                )
            if resp.status_code >= 400:
                raise GitHubAPIError(
                    f"list_issues failed ({resp.status_code}): {resp.text}"
                )
            batch = resp.json()
            if not batch:
                break
            # GitHub's issues endpoint also returns PRs; filter them out.
            all_issues.extend(item for item in batch if "pull_request" not in item)
            if len(batch) < per_page:
                break
            page += 1
        return all_issues

    def close_issue(
        self,
        repo: str,
        number: int,
        comment: str | None = None,
        state_reason: str = "not_planned",
    ) -> None:
        """Optionally comment, then close the issue."""
        if comment:
            self.comment_on_issue(repo, number, comment)
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.patch(
                f"{self.base_url}/repos/{repo}/issues/{number}",
                headers=self._headers(),
                json={"state": "closed", "state_reason": state_reason},
            )
        if resp.status_code >= 400:
            raise GitHubAPIError(
                f"close_issue failed ({resp.status_code}): {resp.text}"
            )
