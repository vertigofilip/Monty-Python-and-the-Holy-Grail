"""Reminders: system notifications about unfinished tasks due today or overdue.

While the desktop program is open, a background thread looks for such tasks
every CHECK_MINUTES (in server mode, while the server cannot be reached, among
the tasks it sent last: SAVED_TASKS). When one is newly due, or was last shown REPEAT_MINUTES
ago, the reminder appears listing every due task: by default the program's own
orange window (it stays until closed and keeps its list up to date), or system
notifications through plyer. A task done, deleted or moved to a later day is
no longer reminded.

The defaults are the constants in reminder_core (which also decides when to
remind); settings.json (keys in SETTINGS) overrides them without touching the code.
Problems (server unreachable, notification failed) only go to LOG_FILE.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import reminder_core, settings
from .reminder_core import (  # noqa: F401 - also this module's names, as before
    BACKGROUND, CHECK_MINUTES, ENABLED, FONT_SIZE, NOTIFICATION_SECONDS, ONLY_MINE,
    REPEAT_MINUTES, SETTINGS, WINDOW, DueTask, due_tasks_in, is_due,
)
from .i18n import tr
from .models import Stage, Task
from .remote import ApiClient, NotLoggedIn

LOG_FILE = Path("todo_client.log")
# The server's tasks at the last check, for reminders while it cannot be reached.
SAVED_TASKS = Path("reminder_tasks.json")

log = logging.getLogger("todo_db.reminders")


def local_due_tasks(session_factory: Callable[[], Session], today: date) -> list[DueTask]:
    """Due tasks in todo.db; uses its own session, so it is safe in another thread."""
    with session_factory() as session:
        query = (
            select(Task)
            .join(Task.stage)
            .where(Task.due_date.is_not(None), Task.due_date <= today, Stage.is_final.is_(False))
            .order_by(Task.due_date, Task.id)
        )
        return [DueTask(task.id, task.name, task.due_date) for task in session.scalars(query)]


def remote_due_tasks(
    api: ApiClient, user_id: int, today: date, only_mine: bool = True
) -> list[DueTask]:
    """Due tasks on the server; only_mine: just those assigned to the user or to nobody.

    Offline they are found in the tasks kept in SAVED_TASKS at the last check.
    """
    tasks = reminder_core.with_saved_copy(
        lambda: api.request("GET", "/tasks?done=false"), SAVED_TASKS, NotLoggedIn
    )
    return due_tasks_in(tasks, today, user_id, only_mine)


def show_notification(title: str, message: str) -> None:
    """A native system notification; raises if the system cannot show it."""
    from plyer import notification  # imported here: a missing plyer is logged, not fatal

    with warnings.catch_warnings():
        # On Linux without python-dbus plyer warns, then uses notify-send, which works.
        warnings.filterwarnings("ignore", message=".*dbus", category=UserWarning)
        notification.notify(
            title=title, message=message, app_name=tr("To-do list"),
            timeout=int(settings.number_setting("reminder_notification_seconds", NOTIFICATION_SECONDS)),
        )


def system_notifications(due: list[DueTask], popup: bool) -> None:
    """Show the due tasks as system notifications, one each (nothing to update in between)."""
    if popup:
        for task in due:
            show_notification(tr("Task reminder"), task.name)


def only_mine() -> bool:
    """Whether server mode reminds only of the user's own and unassigned tasks."""
    return settings.flag_setting("reminder_only_mine", ONLY_MINE)


class Reminders(reminder_core.Reminders):
    """The shared checker; shows system notifications unless given another display."""

    def __init__(
        self,
        find_due: Callable[[date], list[DueTask]],
        *,
        show: Callable[[list[DueTask], bool], Any] = system_notifications,
        **options: Any,
    ) -> None:
        super().__init__(find_due, show=show, **options)


def setup_logging() -> None:
    """Send the program's log (reminder problems among it) to LOG_FILE."""
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # not every request, only problems
