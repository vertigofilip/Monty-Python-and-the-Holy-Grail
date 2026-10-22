"""Reminders without a user interface: which tasks are due, and when to remind of them.

Shared by the desktop program (todo_db.reminders adds its window and system
notifications) and the phone app's background service
(todo_mobile.reminder_service, Android notifications). Only the standard
library is used, so it also runs on the phone.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from . import settings

ENABLED = True  # show reminders at all
CHECK_MINUTES = 15  # how often to look for due tasks
REPEAT_MINUTES = 60  # how long before the same task is shown again
NOTIFICATION_SECONDS = 10  # system notifications: how long they stay (if the system allows)
WINDOW = True  # True: the program's own window; False: system notifications
BACKGROUND = "#FF8C00"  # the window's colour (orange)
FONT_SIZE = 16  # the window's text size in points
ONLY_MINE = True  # server mode: only tasks assigned to me or to nobody
# settings.json keys and their defaults.
SETTINGS: dict[str, Any] = {
    "reminders_enabled": ENABLED,
    "reminder_check_minutes": CHECK_MINUTES,
    "reminder_repeat_minutes": REPEAT_MINUTES,
    "reminder_window": WINDOW,
    "reminder_background": BACKGROUND,
    "reminder_font_size": FONT_SIZE,
    "reminder_notification_seconds": NOTIFICATION_SECONDS,
    "reminder_only_mine": ONLY_MINE,
}

log = logging.getLogger("todo_db.reminders")


@dataclass(frozen=True)
class DueTask:
    """An unfinished task whose due date is today or has passed."""

    id: int
    name: str
    due_date: date


def is_due(due_date: date | None, done: bool, today: date) -> bool:
    """Whether a task needs a reminder: not done, due today or earlier."""
    return not done and due_date is not None and due_date <= today


def due_tasks_in(
    tasks: list[dict[str, Any]], today: date, user_id: int | None = None, only_mine: bool = False
) -> list[DueTask]:
    """The due tasks among tasks as the server sends them (dicts); oldest due first.

    only_mine: just those assigned to user_id or to nobody.
    """
    due = []
    for task in tasks:
        due_date = date.fromisoformat(task["due_date"]) if task.get("due_date") else None
        mine = not only_mine or task["assignee_id"] in (None, user_id)
        if mine and is_due(due_date, task["done"], today):
            due.append(DueTask(task["id"], task["name"], due_date))  # type: ignore[arg-type]
    return sorted(due, key=lambda task: (task.due_date, task.id))


class Reminders:
    """Checks for due tasks in a background thread and shows them when it is time."""

    def __init__(
        self,
        find_due: Callable[[date], list[DueTask]],
        *,
        check_minutes: float | None = None,
        repeat_minutes: float | None = None,
        show: Callable[[list[DueTask], bool], Any] = lambda _due, _popup: None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """find_due(today) lists the due tasks.

        show(due, popup) is called after every check with all due tasks: popup
        True means it is time to remind; False only brings an open reminder up
        to date (a task done in the meantime disappears from it).
        """
        self.find_due = find_due
        self.check_every = timedelta(
            minutes=check_minutes or settings.number_setting("reminder_check_minutes", CHECK_MINUTES)
        )
        self.repeat_after = timedelta(
            minutes=repeat_minutes
            or settings.number_setting("reminder_repeat_minutes", REPEAT_MINUTES)
        )
        self.show = show
        self.clock = clock
        self._last_shown: dict[int, datetime] = {}  # task id -> when it was last shown
        self._stopped = threading.Event()
        self._wake = threading.Event()  # check at once instead of waiting
        self._force = False  # the next check reminds even of tasks shown recently
        self._thread: threading.Thread | None = None
        # Switched off: the thread keeps running but checks nothing (see set_enabled).
        self.enabled = settings.flag_setting("reminders_enabled", ENABLED)

    def check(self, force: bool = False) -> list[DueTask]:
        """One round: remind if it is time (force: in any case if something is due).

        Returns the tasks shown (empty if none).
        """
        now = self.clock()
        try:
            due = self.find_due(now.date())
        except ValueError as error:  # the server refused or could not be reached
            log.warning("Cannot check for due tasks: %s", error)
            return []
        except Exception:
            log.exception("Cannot check for due tasks")
            return []

        # Tasks no longer due (done, deleted, moved) are forgotten: their reminders
        # stop, and if one becomes due again it is shown at once.
        due_ids = {task.id for task in due}
        for task_id in set(self._last_shown) - due_ids:
            del self._last_shown[task_id]

        # Time to remind when a task is newly due or was last shown long enough ago.
        popup = bool(due) and force or any(
            task.id not in self._last_shown or now - self._last_shown[task.id] >= self.repeat_after
            for task in due
        )
        try:
            self.show(due, popup)
        except Exception:
            log.exception("Cannot show the reminder about %s", ", ".join(t.name for t in due))
            return []  # not marked as shown: tried again at the next check
        if not popup:
            return []
        # The reminder lists every due task, so each one counts as shown now.
        for task in due:
            log.info("Reminder shown: task %s (%s), due %s", task.id, task.name, task.due_date)
            self._last_shown[task.id] = now
        return due

    def set_enabled(self, enabled: bool) -> None:
        """Switch reminders on or off, now and for the next start (settings.json)."""
        self.enabled = enabled
        settings.save_setting("reminders_enabled", enabled)
        log.info("Reminders switched %s", "on" if enabled else "off")
        if enabled:
            self._wake.set()

    def check_now(self) -> None:
        """Check at once and show every due task, even ones shown a moment ago."""
        self._force = True
        self._wake.set()

    def start(self) -> None:
        """Start checking in the background: now, then every check interval."""
        if not self.enabled:
            log.info("Reminders are off (reminders_enabled in settings.json)")
        self._thread = threading.Thread(target=self._run, name="reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop checking (waits briefly for a check in progress)."""
        self._stopped.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        log.info(
            "Reminders on: checking every %s, repeating every %s",
            self.check_every, self.repeat_after,
        )
        while not self._stopped.is_set():
            force, self._force = self._force, False
            if self.enabled:
                self.check(force)
            self._wake.wait(self.check_every.total_seconds())
            self._wake.clear()
