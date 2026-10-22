"""Nightly jobs: reset repeating tasks that are due and, if enabled, compress old history."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from todo_db.compression import compress_old_history
from todo_db.models import utcnow
from todo_db.services import TaskService

from .dbadmin import load_settings, save_last_maintenance

log = logging.getLogger("todo_server.maintenance")


def run_maintenance(
    session_factory: Callable[[], Session], now: datetime | None = None
) -> dict[str, Any]:
    """Run all jobs once and return (and store) what they did."""
    now = now or utcnow()
    with session_factory() as session:
        reset = TaskService(session, clock=lambda: now).reset_due_tasks()
        settings = load_settings(session)
        compression = None
        if settings.auto_compress_enabled:
            result = compress_old_history(session, settings.compress_after_days, now=now)
            compression = {"older_than_days": settings.compress_after_days, **asdict(result)}
        report = {"ran_at": now.isoformat(), "reset_tasks": reset, "compression": compression}
        save_last_maintenance(session, report)
    log.info("maintenance: %s", report)
    return report


def seconds_until_next_midnight() -> float:
    """Seconds until just after the next local midnight."""
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return (midnight - now).total_seconds() + 1


async def scheduler(session_factory: Callable[[], Session]) -> None:
    """Run maintenance at start-up and after every local midnight, forever."""
    while True:
        try:
            await asyncio.to_thread(run_maintenance, session_factory)
        except Exception:  # a failed night must not stop the next ones
            log.exception("maintenance failed")
        await asyncio.sleep(seconds_until_next_midnight())
