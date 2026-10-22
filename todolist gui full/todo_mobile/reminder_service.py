"""Reminders on the phone: due tasks as an Android notification, also with the app closed.

The app starts this as an Android foreground service (its own process, no
Kivy; android/reminder_service.py is the entry point). Every
reminder_check_minutes it looks for unfinished tasks due today or earlier –
in the phone's own database or on the server, whichever the app uses – and
decides when to remind exactly as the desktop program does
(todo_db.reminder_core): when a task is newly due, or every
reminder_repeat_minutes. The reminder is one notification listing all due
tasks; tapping it opens the app. It is kept up to date in between and goes
away when nothing is due any more.

The settings (mode, database, reminder_*) are read from the app's
settings.json; changes to the mode or the database apply at the next check.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from todo_db import i18n, reminder_core, settings
from todo_db.i18n import tr
from todo_db.reminder_core import DueTask, Reminders, due_tasks_in

from todo_mobile import api as remote
from todo_mobile import storage

NOTIFICATION_ID = 1001  # one notification, replaced each time
CHANNEL_ID = "task_reminders"
MAX_LINES = 20  # as the desktop's reminder window
LOGIN_FILE = "login.json"

log = logging.getLogger("todo_mobile.reminders")


def find_due_tasks(private: Path) -> Callable[[date], list[DueTask]]:
    """find_due(today) for the mode the app is in: the phone's database, or the server."""

    def find_due(today: date) -> list[DueTask]:
        i18n.set_language(i18n.load_language())  # the app's language may have changed
        if settings.load_setting("mode") == "local":
            from todo_mobile.local import LocalApi  # SQLAlchemy only when needed

            api = LocalApi(storage.local_database(private))
            try:
                return due_tasks_in(api.request("GET", "/tasks"), today)
            finally:
                api.close()
        login = remote.load_login(private / LOGIN_FILE)
        if login is None:
            return []  # logged out: nothing to remind of
        server = remote.Api(*login)
        user = server.request("GET", "/auth/me")
        only_mine = settings.flag_setting("reminder_only_mine", reminder_core.ONLY_MINE)
        return due_tasks_in(server.request("GET", "/tasks?done=false"), today, user["id"], only_mine)

    return find_due


def notification_text(due: list[DueTask], today: date) -> tuple[str, str, str]:
    """(title, one-line summary, the full list) of the reminder about the due tasks."""
    title = tr("Tasks due: {n}").format(n=len(due))
    lines = []
    for task in due[:MAX_LINES]:
        line = task.name
        if task.due_date < today:
            line += " " + tr("(overdue since {date})").format(date=task.due_date.isoformat())
        lines.append(line)
    if len(due) > MAX_LINES:
        lines.append(tr("…and {n} more").format(n=len(due) - MAX_LINES))
    return title, ", ".join(task.name for task in due), "\n".join(lines)


class AndroidNotification:
    """Shows the reminder as an Android notification (the show() of Reminders)."""

    def __init__(self) -> None:
        from jnius import autoclass

        self._autoclass = autoclass
        self.context = autoclass("org.kivy.android.PythonService").mService
        self.manager = self.context.getSystemService(
            autoclass("android.content.Context").NOTIFICATION_SERVICE
        )
        channel = autoclass("android.app.NotificationChannel")(
            CHANNEL_ID, self._text(tr("Task reminders")),
            autoclass("android.app.NotificationManager").IMPORTANCE_HIGH,
        )
        self.manager.createNotificationChannel(channel)

    def _text(self, text: str) -> Any:
        return self._autoclass("java.lang.String")(text)

    def _showing(self) -> bool:
        return any(n.getId() == NOTIFICATION_ID for n in self.manager.getActiveNotifications())

    def __call__(self, due: list[DueTask], popup: bool) -> None:
        if not due:
            self.manager.cancel(NOTIFICATION_ID)  # nothing due any more
            return
        if not popup and not self._showing():
            return  # dismissed: it comes back when it is time to remind again
        autoclass = self._autoclass
        title, summary, lines = notification_text(due, date.today())
        package = self.context.getPackageName()
        opener = self.context.getPackageManager().getLaunchIntentForPackage(package)
        pending = autoclass("android.app.PendingIntent")
        on_tap = pending.getActivity(self.context, 0, opener,
                                     pending.FLAG_IMMUTABLE | pending.FLAG_UPDATE_CURRENT)
        style = autoclass("android.app.Notification$BigTextStyle")()
        style.bigText(self._text(lines))
        builder = autoclass("android.app.Notification$Builder")(self.context, CHANNEL_ID)
        builder.setSmallIcon(self.context.getApplicationInfo().icon)
        builder.setContentTitle(self._text(title))
        builder.setContentText(self._text(summary))
        builder.setStyle(style)
        builder.setContentIntent(on_tap)
        builder.setAutoCancel(True)
        builder.setOnlyAlertOnce(not popup)  # an update in between makes no sound
        if popup:
            self.manager.cancel(NOTIFICATION_ID)  # so that it sounds and pops up again
        self.manager.notify(NOTIFICATION_ID, builder.build())


def main() -> None:
    """The service's entry point; the argument is the app's private folder."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    private = Path(os.environ.get("PYTHON_SERVICE_ARGUMENT") or ".")
    settings.SETTINGS_FILE = private / "settings.json"
    i18n.set_language(i18n.load_language())
    checker = Reminders(find_due_tasks(private), show=AndroidNotification())
    checker.start()
    threading.Event().wait()  # the service runs until Android or the app stops it
