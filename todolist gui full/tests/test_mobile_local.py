"""The phone app without a server: LocalApi on a database file."""

from __future__ import annotations

from pathlib import Path

import pytest

from todo_db import i18n
from todo_mobile.api import RemoteError
from todo_mobile.local import LocalApi
from todo_mobile.tasks import final_stage_id, history_lines, task_details, task_rows


def stage(data: dict, workflow: str, name: str) -> int:
    stages = next(w for w in data["workflows"] if w["name"] == workflow)["stages"]
    return next(s["id"] for s in stages if s["name"] == name)


def test_a_new_phone_database_has_the_reference_data_and_one_user(tmp_path: Path) -> None:
    api = LocalApi(tmp_path / "todo.db")
    data = api.load_all()
    assert [u["name"] for u in data["users"]] == ["Me"] == [api.user["name"]]
    assert {w["name"] for w in data["workflows"]} == {"Simple", "Software"}
    assert data["repeat_rules"] and data["tags"] and data["tasks"] == []
    assert api.request("GET", "/auth/me") == api.user


def test_the_user_is_named_in_the_app_language(tmp_path: Path) -> None:
    i18n.set_language("pl")
    try:
        assert LocalApi(tmp_path / "todo.db").user["name"] == "Ja"
    finally:
        i18n.set_language("en")


def test_tasks_are_kept_changed_and_logged_like_on_the_server(tmp_path: Path) -> None:
    api = LocalApi(tmp_path / "todo.db")
    data = api.load_all()
    todo = stage(data, "Simple", "To do")
    tag = data["tags"][0]
    created = api.request("POST", "/tasks", {
        "name": "Pay the bill", "stage_id": todo, "priority": "Important",
        "due_date": "2026-10-10", "location": "Bank", "tag_ids": [tag["id"]],
    })
    assert created["assignee_id"] == api.user["id"]  # assigned to whoever adds it
    assert created["due_date"] == "2026-10-10" and created["priority"] == "Important"
    sub = api.request("POST", "/tasks", {"name": "Find the invoice", "stage_id": todo,
                                         "parent_id": created["id"], "assignee_id": None})
    assert sub["assignee_id"] is None

    api.request("PATCH", f"/tasks/{created['id']}", {"location": "Post office", "urgency": "High"})
    # Kept in the file: a new LocalApi (the next start of the app) sees the same.
    data = LocalApi(tmp_path / "todo.db").load_all()
    rows = task_rows(data["tasks"], "post")
    assert [row.task["name"] for row in rows] == ["Pay the bill"]
    assert "Post office" in task_details(rows[0].task)

    task = rows[0].task
    api.request("PATCH", f"/tasks/{task['id']}", {"stage_id": final_stage_id(task, data["workflows"])})
    lines = history_lines(api.request("GET", f"/tasks/{task['id']}/history"))
    assert any("Location: Bank → Post office" in text for _heading, text in lines)
    assert all("Me" in heading for heading, _text in lines)

    with pytest.raises(RemoteError):  # it has a subtask
        api.request("DELETE", f"/tasks/{task['id']}")
    api.request("DELETE", f"/tasks/{sub['id']}")
    assert [t["name"] for t in api.load_all()["tasks"]] == ["Pay the bill"]


def test_refused_changes_become_messages(tmp_path: Path) -> None:
    api = LocalApi(tmp_path / "todo.db")
    with pytest.raises(RemoteError, match="does not exist"):
        api.request("PATCH", "/tasks/99", {"name": "x"})
    with pytest.raises(RemoteError):
        api.request("POST", "/tasks", {"name": "x", "stage_id": 999})
    assert api.load_all()["tasks"] == []  # nothing half-saved


def test_typed_locations_become_database_files(tmp_path: Path) -> None:
    from todo_mobile.storage import DB_NAME, database_file, inside

    assert database_file("tasks.db", tmp_path) == tmp_path / "tasks.db"  # relative: app folder
    assert database_file(str(tmp_path), Path("/")) == tmp_path / DB_NAME  # a folder: todo.db in it
    assert database_file("new/folder/", tmp_path) == tmp_path / "new" / "folder" / DB_NAME
    assert database_file("~/x.db", tmp_path) == Path.home() / "x.db"
    assert inside(tmp_path / "a" / "b.db", [tmp_path])
    assert not inside(Path("/storage/emulated/0/Documents/todo.db"), [tmp_path])


def test_moving_copies_the_tasks_or_starts_empty(tmp_path: Path) -> None:
    from todo_mobile.storage import move_database

    old = tmp_path / "todo.db"
    api = LocalApi(old)
    todo = stage(api.load_all(), "Simple", "To do")
    api.request("POST", "/tasks", {"name": "Water the plants", "stage_id": todo})
    api.close()  # what the app does before switching

    copied = tmp_path / "sd" / "Documents" / "todo.db"
    move_database(old, copied, copy=True)
    assert [t["name"] for t in LocalApi(copied).load_all()["tasks"]] == ["Water the plants"]
    empty = tmp_path / "other" / "empty.db"
    move_database(old, empty, copy=False)
    assert LocalApi(empty).load_all()["tasks"] == []
    assert [t["name"] for t in api.load_all()["tasks"]] == ["Water the plants"]  # old one still works
    with pytest.raises(FileExistsError):  # never overwrites a database that is there
        move_database(old, copied, copy=True)


def test_a_file_that_is_not_a_database_is_refused(tmp_path: Path) -> None:
    junk = tmp_path / "photo.db"
    junk.write_text("not a database " * 100)
    with pytest.raises(RemoteError, match="Cannot open the database"):
        LocalApi(junk)


def test_phone_reminders_find_due_tasks_in_either_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from datetime import date

    from todo_db import settings
    from todo_mobile.reminder_service import find_due_tasks, notification_text

    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    settings.save_setting("mode", "local")
    settings.save_setting("local_database", str(tmp_path / "phone.db"))
    api = LocalApi(tmp_path / "phone.db")
    todo = stage(api.load_all(), "Simple", "To do")
    for name, due in (("Pay the bill", "2026-10-10"), ("Water the plants", "2026-10-14"),
                      ("Later", "2026-11-01"), ("No date", None)):
        api.request("POST", "/tasks", {"name": name, "stage_id": todo, "due_date": due})
    api.close()

    today = date(2026, 10, 14)
    due = find_due_tasks(tmp_path)(today)
    assert [task.name for task in due] == ["Pay the bill", "Water the plants"]
    title, summary, lines = notification_text(due, today)
    assert title == "Tasks due: 2" and summary == "Pay the bill, Water the plants"
    assert lines == "Pay the bill (overdue since 2026-10-10)\nWater the plants"

    settings.save_setting("mode", "server")  # logged out of the server: nothing to remind of
    assert find_due_tasks(tmp_path)(today) == []
    assert json.loads((tmp_path / "settings.json").read_text())["mode"] == "server"
