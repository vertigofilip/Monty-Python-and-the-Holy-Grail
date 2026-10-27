"""Reminders about due tasks: what is due, how often it is shown, errors, the thread."""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import World
from tests.test_mobile import logged_in, stage
from tests.test_remote import server  # noqa: F401 - the live server fixture
from todo_db import reminder_core, reminders, settings
from todo_db.remote import ApiClient, NotLoggedIn, RemoteError
from todo_db.reminders import DueTask, Reminders, is_due, local_due_tasks
from todo_db.services import TaskService

TODAY = date(2026, 10, 14)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 14, 9, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += timedelta(minutes=minutes)


@pytest.fixture(autouse=True)
def no_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", path)
    return path


@pytest.fixture(autouse=True)
def saved_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "reminder_tasks.json"
    monkeypatch.setattr(reminders, "SAVED_TASKS", path)
    return path


def test_is_due() -> None:
    assert is_due(TODAY, done=False, today=TODAY)
    assert is_due(TODAY - timedelta(days=3), done=False, today=TODAY)  # overdue
    assert not is_due(TODAY + timedelta(days=1), done=False, today=TODAY)
    assert not is_due(TODAY, done=True, today=TODAY)
    assert not is_due(None, done=False, today=TODAY)


def test_local_due_tasks(session: Session, service: TaskService, world: World) -> None:
    def add(name: str, due: date | None, stage: int = world.todo) -> int:
        return service.create_task(name, stage, world.anna, due_date=due).id

    today = add("Trening kalisteniki", TODAY)
    overdue = add("Pay the bill", TODAY - timedelta(days=2))
    add("Later", TODAY + timedelta(days=1))
    add("No deadline", None)
    add("Already done", TODAY, stage=world.done)

    factory = sessionmaker(session.get_bind())
    found = local_due_tasks(factory, TODAY)
    assert [(task.id, task.name) for task in found] == [
        (overdue, "Pay the bill"), (today, "Trening kalisteniki")
    ]


def test_due_date_is_kept_and_logged(service: TaskService, world: World) -> None:
    task = service.create_task("Report", world.todo, world.anna)
    service.update_task(task.id, world.anna, due_date=TODAY)
    assert task.due_date == TODAY
    change = service.get_history(task.id)[-1]
    assert (change.field_name, change.old_value, change.new_value) == ("DueDate", None, "2026-10-14")


class Display:
    """Records what the reminder was asked to show."""

    def __init__(self) -> None:
        self.popups: list[list[str]] = []  # the task names of each reminder that appeared
        self.updates: list[list[str]] = []  # what an open reminder was brought up to date with

    def __call__(self, due: list[DueTask], popup: bool) -> None:
        (self.popups if popup else self.updates).append([task.name for task in due])


def test_shown_at_most_once_an_hour_and_no_more_when_done() -> None:
    due = [DueTask(1, "Trening kalisteniki", TODAY)]
    display, clock = Display(), Clock()
    checker = Reminders(lambda _today: list(due), check_minutes=15, repeat_minutes=60,
                        show=display, clock=clock)

    checker.check()
    assert display.popups == [["Trening kalisteniki"]]
    for _ in range(3):  # 15, 30 and 45 minutes later: not again, only kept up to date
        clock.advance(15)
        checker.check()
    assert len(display.popups) == 1 and len(display.updates) == 3
    clock.advance(15)  # an hour after the first one
    checker.check()
    assert len(display.popups) == 2

    due.clear()  # marked as done
    clock.advance(60)
    checker.check()
    assert len(display.popups) == 2
    assert display.updates[-1] == []  # an open reminder empties (and closes)


def test_a_newly_due_task_brings_the_reminder_with_all_due_tasks() -> None:
    due = [DueTask(1, "Report", TODAY - timedelta(days=1))]
    display, clock = Display(), Clock()
    checker = Reminders(lambda _today: list(due), check_minutes=15, repeat_minutes=60,
                        show=display, clock=clock)
    checker.check()
    clock.advance(15)
    due.append(DueTask(2, "Trening kalisteniki", TODAY))
    checker.check()
    assert display.popups == [["Report"], ["Report", "Trening kalisteniki"]]


def test_task_due_again_is_shown_at_once() -> None:
    due = [DueTask(1, "Report", TODAY)]
    display, clock = Display(), Clock()
    checker = Reminders(lambda _today: list(due), check_minutes=15, repeat_minutes=60,
                        show=display, clock=clock)
    checker.check()
    due.clear()  # done...
    clock.advance(15)
    checker.check()
    due.append(DueTask(1, "Report", TODAY))  # ...and reopened
    clock.advance(15)
    checker.check()
    assert display.popups == [["Report"], ["Report"]]


def test_errors_are_logged_and_checking_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="todo_db.reminders")
    calls = 0

    def flaky_show(_due: list[DueTask], _popup: bool) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("no notification service")

    def server_down(_today: date) -> list[DueTask]:
        raise RemoteError("Cannot reach the server at http://x:8000.")

    clock = Clock()
    checker = Reminders(lambda _today: [DueTask(1, "Report", TODAY)], check_minutes=15,
                        repeat_minutes=60, show=flaky_show, clock=clock)
    assert checker.check() == []  # the reminder failed...
    assert "Cannot show the reminder about Report" in caplog.text
    clock.advance(15)
    assert [task.id for task in checker.check()] == [1]  # ...so it is tried again

    checker.find_due = server_down
    assert checker.check() == []
    assert "Cannot reach the server" in caplog.text


def test_system_notifications_one_per_task(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(reminders, "show_notification", lambda *args: sent.append(args))
    due = [DueTask(1, "Report", TODAY), DueTask(2, "Trening kalisteniki", TODAY)]
    reminders.system_notifications(due, popup=False)
    assert sent == []
    reminders.system_notifications(due, popup=True)
    assert sent == [("Task reminder", "Report"), ("Task reminder", "Trening kalisteniki")]


def test_intervals_from_settings_file(no_settings_file: Path) -> None:
    no_settings_file.write_text(json.dumps(
        {"reminder_check_minutes": 0.5, "reminder_repeat_minutes": "soon"}
    ))
    checker = Reminders(lambda _today: [])
    assert checker.check_every == timedelta(seconds=30)
    assert checker.repeat_after == timedelta(minutes=reminders.REPEAT_MINUTES)  # bad value ignored


def test_defaults_are_added_and_own_values_kept(no_settings_file: Path) -> None:
    no_settings_file.write_text(json.dumps({"language": "pl", "reminder_check_minutes": 0.1}))
    settings.add_defaults(reminders.SETTINGS)
    saved = json.loads(no_settings_file.read_text())
    assert saved["language"] == "pl" and saved["reminder_check_minutes"] == 0.1
    assert saved["reminder_repeat_minutes"] == reminders.REPEAT_MINUTES
    assert saved["reminders_enabled"] is True and saved["reminder_only_mine"] is True


def test_reminders_can_be_switched_off(no_settings_file: Path) -> None:
    no_settings_file.write_text(json.dumps({"reminders_enabled": False}))
    shown = threading.Event()
    checker = Reminders(lambda _today: [DueTask(1, "Report", TODAY)], check_minutes=60,
                        repeat_minutes=60, show=lambda *_args: shown.set())
    checker.start()
    try:
        assert not shown.wait(0.3)  # off: nothing is checked
        checker.set_enabled(True)  # e.g. from the tray menu
        assert shown.wait(5)  # checks at once
    finally:
        checker.stop()
    assert json.loads(no_settings_file.read_text())["reminders_enabled"] is True
    no_settings_file.write_text(json.dumps({"reminders_enabled": "no"}))  # not true/false
    assert settings.flag_setting("reminders_enabled", True) is True


def test_check_now_shows_tasks_shown_a_moment_ago() -> None:
    popups: list[bool] = []
    first, second = threading.Event(), threading.Event()

    def show(_due: list[DueTask], popup: bool) -> None:
        popups.append(popup)
        (first if len(popups) == 1 else second).set()

    checker = Reminders(lambda _today: [DueTask(1, "Report", TODAY)], check_minutes=60,
                        repeat_minutes=60, show=show)
    checker.start()
    try:
        assert first.wait(5)  # the check at start
        checker.check_now()
        assert second.wait(5)
    finally:
        checker.stop()
    assert popups == [True, True]  # not just an update, although shown a moment before


def test_background_thread_checks_and_stops() -> None:
    shown = threading.Event()
    checker = Reminders(lambda _today: [DueTask(1, "Report", TODAY)], check_minutes=60,
                        repeat_minutes=60, show=lambda _due, _popup: shown.set())
    checker.start()
    try:
        assert shown.wait(5)  # the first check runs at once
    finally:
        checker.stop()
    assert checker._thread is not None and not checker._thread.is_alive()


def test_remote_due_tasks(server: str) -> None:  # noqa: F811
    ola = logged_in(server, "ola@example.com")
    data = ola.load_all()
    todo, done = stage(data, "Simple", "To do"), stage(data, "Simple", "Done")
    ada_id = next(user["id"] for user in data["users"] if user["name"] == "Ada")
    ola_id = next(user["id"] for user in data["users"] if user["name"] == "Ola")
    today = date.today().isoformat()
    for name, fields in [
        ("Mine", {"assignee_id": ola_id}),
        ("Nobody's", {}),
        ("Ada's", {"assignee_id": ada_id}),
        ("Finished", {"stage_id": done}),
    ]:
        ola.request("POST", "/tasks", {"name": name, "stage_id": todo, "due_date": today} | fields)

    api = ApiClient(server, ola.token)
    try:
        found = reminders.remote_due_tasks(api, ola_id, date.today())
        everyone = reminders.remote_due_tasks(api, ola_id, date.today(), only_mine=False)
    finally:
        api.close()
    assert sorted(task.name for task in found) == ["Mine", "Nobody's"]
    assert sorted(task.name for task in everyone) == ["Ada's", "Mine", "Nobody's"]



def test_offline_the_tasks_from_the_last_check_are_used(
    saved_tasks: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tasks = [{"id": 1, "name": "Report", "due_date": TODAY.isoformat(), "done": False,
              "assignee_id": None}]
    answers: list[object] = [RemoteError("Cannot reach the server"), tasks]

    def fetch() -> object:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def due() -> list[str]:
        found = reminder_core.with_saved_copy(fetch, saved_tasks, NotLoggedIn)
        return [task.name for task in reminders.due_tasks_in(found, TODAY)]

    with pytest.raises(RemoteError):  # nothing kept yet: the error goes on
        reminder_core.with_saved_copy(fetch, saved_tasks, NotLoggedIn)
    assert due() == ["Report"]
    assert saved_tasks.stat().st_mode & 0o777 == 0o600
    answers += [RemoteError("Cannot reach the server")] * 2
    assert due() == ["Report"]
    assert due() == ["Report"]
    assert caplog.text.count("using the tasks known at") == 1  # once while offline
    answers.append(NotLoggedIn("Login expired"))
    with pytest.raises(NotLoggedIn):
        due()
    assert not saved_tasks.exists()


def test_remote_due_tasks_offline(server: str, saved_tasks: Path) -> None:  # noqa: F811
    ola = logged_in(server, "ola@example.com")
    todo = stage(ola.load_all(), "Simple", "To do")
    ola.request("POST", "/tasks", {"name": "Mine", "stage_id": todo,
                                   "due_date": date.today().isoformat()})
    user_id = ola.request("GET", "/auth/me")["id"]
    api = ApiClient(server, ola.token)
    try:
        assert [t.name for t in reminders.remote_due_tasks(api, user_id, date.today())] == ["Mine"]
    finally:
        api.close()
    offline = ApiClient("http://127.0.0.1:9", ola.token)  # nothing listens there
    try:
        found = reminders.remote_due_tasks(offline, user_id, date.today())
    finally:
        offline.close()
    assert [task.name for task in found] == ["Mine"]
