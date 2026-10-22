"""The phone app's server connection and list logic (the Kivy screens are not tested)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from tests.test_remote import PASSWORD, server  # noqa: E402,F401 - the live server fixture

from todo_db import i18n  # noqa: E402
from todo_mobile import api as remote  # noqa: E402
from todo_mobile.tasks import (  # noqa: E402
    SHOW_ALL, SHOW_DONE, SHOW_OPEN, final_stage_id, history_lines, is_overdue, next_stage_id,
    parse_due, repeat_label, sorted_rules, task_details, task_rows,
)


def logged_in(server: str, email: str = "ada@example.com") -> remote.Api:  # noqa: F811
    api = remote.Api(server)
    api.login(email, PASSWORD)
    return api


def stage(data: dict, workflow: str, name: str) -> int:
    for item in data["workflows"]:
        if item["name"] == workflow:
            return next(s["id"] for s in item["stages"] if s["name"] == name)
    raise KeyError(workflow)


def test_login_and_wrong_password(server: str) -> None:  # noqa: F811
    api = remote.Api(server.removeprefix("http://"))  # the scheme may be left out
    assert api.base_url == server
    user = api.login("ada@example.com", PASSWORD)
    assert user["name"] == "Ada" and api.token

    with pytest.raises(remote.RemoteError, match="Wrong email or password"):
        remote.Api(server).login("ada@example.com", "nope")


def test_unreachable_server() -> None:
    with pytest.raises(remote.RemoteError, match="Cannot reach the server"):
        remote.Api("http://127.0.0.1:9").request("GET", "/auth/me")


def test_logout_ends_the_token(server: str) -> None:  # noqa: F811
    api = logged_in(server)
    token = api.token
    api.logout()
    with pytest.raises(remote.NotLoggedIn):
        remote.Api(server, token).request("GET", "/auth/me")


def test_tasks_tree_changes_and_history(server: str) -> None:  # noqa: F811
    api = logged_in(server, "ola@example.com")
    data = api.load_all()
    todo = stage(data, "Simple", "To do")
    parent = api.request("POST", "/tasks", {"name": "Garden", "stage_id": todo})
    child = api.request("POST", "/tasks", {"name": "Weed beds", "stage_id": todo,
                                           "parent_id": parent["id"], "priority": "Important"})
    data = api.load_all()

    rows = task_rows(data["tasks"])
    assert [(r.task["name"], r.depth, r.matches) for r in rows] == [
        ("Garden", 0, True), ("Weed beds", 1, True)
    ]
    # Searching for the subtask keeps its parent as context.
    rows = task_rows(data["tasks"], "weed")
    assert [(r.task["name"], r.matches) for r in rows] == [("Garden", False), ("Weed beds", True)]

    task = next(t for t in data["tasks"] if t["id"] == child["id"])
    assert next_stage_id(task, data["workflows"]) == final_stage_id(task, data["workflows"])
    api.request("PATCH", f"/tasks/{child['id']}", {"stage_id": final_stage_id(task, data["workflows"])})
    data = api.load_all()
    assert [r.task["name"] for r in task_rows(data["tasks"], show=SHOW_OPEN)] == ["Garden"]
    assert [r.task["name"] for r in task_rows(data["tasks"], show=SHOW_DONE)] == [
        "Garden", "Weed beds"
    ]
    assert len(task_rows(data["tasks"], show=SHOW_ALL)) == 2
    done = next(t for t in data["tasks"] if t["id"] == child["id"])
    assert next_stage_id(done, data["workflows"]) is None
    assert task_details(done).startswith("Done · Important")

    history = api.request("GET", f"/tasks/{child['id']}/history")
    lines = history_lines(history)
    assert "Ola" in lines[0][0] and "Completed" in lines[0][0]  # newest first
    assert "StageChanged" in lines[1][0] and lines[1][1] == "StageId: To do → Done"
    assert "Created" in lines[-1][0]


def test_not_logged_in_after_token_is_revoked(server: str) -> None:  # noqa: F811
    api = logged_in(server)
    other = remote.Api(server, api.token)
    api.logout()
    with pytest.raises(remote.NotLoggedIn):
        other.load_all()


def test_remembered_login(tmp_path: Path) -> None:
    path = tmp_path / "login.json"
    assert remote.load_login(path) is None
    remote.save_login(path, "http://x:8000", "secret")
    assert remote.load_login(path) == ("http://x:8000", "secret")
    assert path.stat().st_mode & 0o777 == 0o600
    remote.forget_login(path)
    assert remote.load_login(path) is None


def test_repeat_labels_in_polish() -> None:
    rules = [{"id": 1, "name": "", "interval": 2, "unit": "Week"},
             {"id": 2, "name": "", "interval": 1, "unit": "Day"},
             {"id": 3, "name": "", "interval": 5, "unit": "Day"}]
    i18n.set_language("pl")
    try:
        assert [repeat_label(r) for r in sorted_rules(rules)] == [
            "Codziennie", "Co 5 dni", "Co 2 tygodnie"
        ]
    finally:
        i18n.set_language("en")


def test_new_task_is_assigned_to_whoever_adds_it(server: str) -> None:  # noqa: F811
    api = logged_in(server, "ola@example.com")
    data = api.load_all()
    ola = next(user["id"] for user in data["users"] if user["name"] == "Ola")
    todo = stage(data, "Simple", "To do")
    assert api.request("POST", "/tasks", {"name": "Mine", "stage_id": todo})["assignee_id"] == ola
    nobody = api.request("POST", "/tasks", {"name": "Nobody's", "stage_id": todo, "assignee_id": None})
    assert nobody["assignee_id"] is None  # a choice made in the form is kept


def test_location_travels_through_the_server(server: str) -> None:  # noqa: F811
    api = logged_in(server, "ola@example.com")
    todo = stage(api.load_all(), "Simple", "To do")
    created = api.request("POST", "/tasks", {"name": "Run", "stage_id": todo, "location": "Park"})
    assert created["location"] == "Park"
    changed = api.request("PATCH", f"/tasks/{created['id']}", {"location": None})
    assert changed["location"] is None


def test_due_date_and_location_on_the_phone(server: str) -> None:  # noqa: F811
    assert parse_due(" 2026-10-31 ") == date(2026, 10, 31) and parse_due("") is None
    with pytest.raises(ValueError):
        parse_due("31.10.2026")

    api = logged_in(server, "ola@example.com")
    todo = stage(api.load_all(), "Simple", "To do")
    api.request("POST", "/tasks", {"name": "Run", "stage_id": todo, "due_date": "2026-10-13",
                                   "location": "Park"})
    task = next(t for t in api.load_all()["tasks"] if t["name"] == "Run")
    today = date(2026, 10, 14)
    assert is_overdue(task, today) and not is_overdue(task, date(2026, 10, 13))
    details = task_details(task, today)
    assert "Due date: 2026-10-13 (overdue)" in details and "Park" in details
    assert [row.task["name"] for row in task_rows([task], "park")] == ["Run"]  # found by place


def test_phone_reminders_from_the_server(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    from todo_db import settings
    from todo_mobile.reminder_service import find_due_tasks

    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    ola = logged_in(server, "ola@example.com")
    data = ola.load_all()
    todo = stage(data, "Simple", "To do")
    ada_id = next(user["id"] for user in data["users"] if user["name"] == "Ada")
    today = date.today().isoformat()
    ola.request("POST", "/tasks", {"name": "Mine", "stage_id": todo, "due_date": today})
    ola.request("POST", "/tasks", {"name": "Ada's", "stage_id": todo, "due_date": today,
                                   "assignee_id": ada_id})
    remote.save_login(tmp_path / "login.json", ola.base_url, ola.token or "")
    assert [t.name for t in find_due_tasks(tmp_path)(date.today())] == ["Mine"]  # only mine
    settings.save_setting("reminder_only_mine", False)
    assert sorted(t.name for t in find_due_tasks(tmp_path)(date.today())) == ["Ada's", "Mine"]
