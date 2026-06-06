"""GitHub issue scanner that discovers pre-existing labeled issues.

The webhook handler only captures issues at the moment the trigger label is
*added*. The scanner fills the gap by periodically polling the GitHub API for
all open issues that already carry a trigger label and recording any that are
not yet tracked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings, get_settings
from app.database import session_scope
from app.devin_client import DevinAPIError, DevinClient
from app.github_client import GitHubClient
from app.services import approve_issue, find_issue_by_repo_number, record_issue_from_event
from app.webhook import IssueEvent

logger = logging.getLogger("godseye.scanner")


def _github_issue_to_event(item: dict[str, Any], trigger_label: str) -> IssueEvent:
    """Convert a raw GitHub issue dict to an IssueEvent."""
    return IssueEvent(
        action="labeled",
        repo=item.get("repository", {}).get("full_name", "")
        or item.get("repository_url", "").rsplit("/repos/", 1)[-1],
        number=item["number"],
        github_id=item.get("id"),
        title=item.get("title", ""),
        body=item.get("body") or "",
        html_url=item.get("html_url", ""),
        labels=[lbl.get("name", "") for lbl in item.get("labels", [])],
        label_added=trigger_label,
    )


def scan_once(
    github_client: GitHubClient | None = None,
    devin_client: DevinClient | None = None,
    settings: Settings | None = None,
) -> int:
    """Scan GitHub for open issues with trigger labels.

    Returns the number of *new* issues recorded (not already in DB).
    """
    settings = settings or get_settings()
    gh = github_client or GitHubClient()
    dv = devin_client or DevinClient()
    recorded = 0

    for trigger_label in sorted(settings.trigger_label_set):
        try:
            items = gh.list_issues(settings.target_repo, labels=trigger_label, state="open")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to list issues for label %r", trigger_label)
            continue

        for item in items:
            repo = settings.target_repo
            number = item["number"]

            with session_scope() as db:
                existing = find_issue_by_repo_number(db, repo, number)
                if existing is not None:
                    continue

                # Build a repo-qualified event. GitHub list endpoint does not
                # include repository.full_name, so we inject it from config.
                event = _github_issue_to_event(item, trigger_label)
                event.repo = repo
                issue, should_auto = record_issue_from_event(db, event, settings)
                if issue is None:
                    continue
                recorded += 1
                logger.info(
                    "Scanner discovered issue %s#%s (%s)",
                    repo,
                    number,
                    "auto-approve" if should_auto else "pending",
                )
                if should_auto:
                    try:
                        approve_issue(db, issue, devin_client=dv)
                    except (DevinAPIError, ValueError) as exc:
                        logger.error(
                            "Auto-approval failed for scanned issue %s: %s",
                            issue.id,
                            exc,
                        )

    return recorded


async def scanner_loop(stop_event: asyncio.Event) -> None:
    """Periodically run :func:`scan_once` until *stop_event* is set."""
    settings = get_settings()
    interval = max(10, settings.scan_interval_seconds)
    logger.info("GitHub issue scanner started (interval=%ss)", interval)

    # Run immediately on startup to catch pre-existing issues.
    try:
        await asyncio.to_thread(scan_once)
    except Exception:  # noqa: BLE001
        logger.exception("Initial scan failed")

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await asyncio.to_thread(scan_once)
        except Exception:  # noqa: BLE001
            logger.exception("Scanner iteration failed")

    logger.info("GitHub issue scanner stopped")
