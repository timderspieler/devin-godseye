"""Thin client for the Devin API v3 (https://docs.devin.ai/api-reference)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class DevinAPIError(RuntimeError):
    """Raised when the Devin API returns an error response."""


@dataclass
class CreatedSession:
    session_id: str
    url: str
    is_new_session: bool | None = None


@dataclass
class SessionDetails:
    session_id: str
    status: str
    status_enum: str | None
    pr_url: str | None
    pr_state: str | None
    structured_output: Any | None
    title: str | None
    updated_at: str | None
    raw: dict[str, Any]


class DevinClient:
    """Wrapper around the Devin v3 sessions API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        org_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.devin_api_key
        self.base_url = (base_url or settings.devin_api_base_url).rstrip("/")
        self.org_id = org_id if org_id is not None else settings.devin_org_id
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DevinAPIError("DEVIN_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _sessions_url(self) -> str:
        if not self.org_id:
            raise DevinAPIError("DEVIN_ORG_ID is not configured")
        return f"{self.base_url}/v3/organizations/{self.org_id}/sessions"

    def create_session(
        self,
        prompt: str,
        title: str | None = None,
        tags: list[str] | None = None,
        max_acu_limit: int | None = None,
        idempotent: bool = False,
    ) -> CreatedSession:
        payload: dict[str, Any] = {"prompt": prompt}
        if title:
            payload["title"] = title
        if tags:
            payload["tags"] = tags
        if max_acu_limit:
            payload["max_acu_limit"] = max_acu_limit

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self._sessions_url(),
                headers=self._headers(),
                json=payload,
            )
        if resp.status_code >= 400:
            raise DevinAPIError(
                f"create_session failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        return CreatedSession(
            session_id=data["session_id"],
            url=data["url"],
            is_new_session=data.get("is_new_session"),
        )

    def terminate_session(self, session_id: str, archive: bool = True) -> None:
        """Terminate a session and optionally archive it for future reference."""
        params = {"archive": "true"} if archive else {}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.delete(
                f"{self._sessions_url()}/{session_id}",
                headers=self._headers(),
                params=params,
            )
        if resp.status_code >= 400:
            raise DevinAPIError(
                f"terminate_session failed ({resp.status_code}): {resp.text}"
            )

    def get_session(self, session_id: str) -> SessionDetails:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self._sessions_url()}/{session_id}",
                headers=self._headers(),
            )
        if resp.status_code >= 400:
            raise DevinAPIError(
                f"get_session failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        # v3 returns pull_requests as a list; extract the first PR.
        pull_requests = data.get("pull_requests") or []
        first_pr = pull_requests[0] if pull_requests else {}
        return SessionDetails(
            session_id=data["session_id"],
            status=data.get("status", ""),
            status_enum=data.get("status_detail"),
            pr_url=first_pr.get("pr_url"),
            pr_state=first_pr.get("pr_state"),
            structured_output=data.get("structured_output"),
            title=data.get("title"),
            updated_at=data.get("updated_at"),
            raw=data,
        )
