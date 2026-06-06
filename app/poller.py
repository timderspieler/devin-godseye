"""Background poller that keeps active Devin sessions in sync."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config import get_settings
from app.database import session_scope
from app.devin_client import DevinClient
from app.models import FAILURE_STATUSES, SUCCESS_STATUSES, FixSession
from app.services import sync_session

logger = logging.getLogger("godseye.poller")

_TERMINAL = SUCCESS_STATUSES | FAILURE_STATUSES


def poll_once(devin_client: DevinClient | None = None) -> int:
    """Sync all non-terminal sessions once. Returns the number synced."""
    client = devin_client or DevinClient()
    synced = 0
    with session_scope() as db:
        sessions = db.scalars(
            select(FixSession).where(FixSession.status.notin_(_TERMINAL))
        ).all()
        for session in sessions:
            try:
                sync_session(db, session, client)
                synced += 1
            except Exception:  # noqa: BLE001 - keep polling other sessions
                logger.exception(
                    "Failed to sync session %s", session.devin_session_id
                )
    return synced


async def poller_loop(stop_event: asyncio.Event) -> None:
    """Run :func:`poll_once` on an interval until ``stop_event`` is set."""
    settings = get_settings()
    interval = max(5, settings.poll_interval_seconds)
    logger.info("Session poller started (interval=%ss)", interval)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_once)
        except Exception:  # noqa: BLE001
            logger.exception("Poller iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
    logger.info("Session poller stopped")
