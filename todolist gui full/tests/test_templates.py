"""Subtask templates: kept in the database, on the server and on the phone; adding them as subtasks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, select, text

from todo_db import settings, templates
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.management import ManagementError
from todo_db.models import Priority, Task, Urgency, User
from todo_db.seed import seed
from todo_mobile.api import RemoteError
from todo_mobile.local import LocalApi

WRITE_TESTS = {"name": "Write tests", "description": "Unit and GUI", "priority": "Important",
               "urgency": "High"}


def test_templates_are_kept_changed_and_deleted(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'todo.db'}")
    create_all(engine)
    with make_session_factory(engine)() as session:
        added = templates.add_template(session, WRITE_TESTS)
        templates.add_template(session, {"name": "  Review  "})
        assert [templates.template_data(t) for t in templates.list_templates(session)] == [
            {"id": 2, "name": "Review", "description": None, "priority": "Normal",
             "urgency": "Medium"},
            {"id": added.id, **WRITE_TESTS},
        ]
        with pytest.raises(ManagementError, match="already exists"):
            templates.add_template(session, {"name": "Review"})
        with pytest.raises(ManagementError, match="Enter a name"):
            templates.update_template(session, added.id, {"name": " "})
        session.rollback()
        changed = templates.update_template(session, added.id, {"urgency": "Low", "description": ""})
        assert (changed.name, changed.priority, changed.urgency, changed.description) == (
            "Write tests", Priority.Important, Urgency.Low, None
        )
        templates.delete_template(session, added.id)
        assert [t.name for t in templates.list_templates(session)] == ["Review"]


def test_an_older_database_gets_the_templates_table(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    engine = make_engine(f"sqlite:///{path}")
    create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE "SubtaskTemplate"'))
    create_all(make_engine(f"sqlite:///{path}"))
    assert "SubtaskTemplate" in inspect(make_engine(f"sqlite:///{path}")).get_table_names()


def test_subtask_fields_start_in_the_parents_workflow_for_its_assignee() -> None:
    template = {"id": 1, **WRITE_TESTS}
    parent = {"id": 7, "first_stage_id": 3, "assignee_id": 2}
    assert templates.subtask_fields(template, parent) == {
        "name": "Write tests", "stage_id": 3, "parent_id": 7, "description": "Unit and GUI",
        "priority": "Important", "urgency": "High", "assignee_id": 2,
    }


# -- the phone without a server -----------------------------------------------------


def test_phone_database_keeps_templates_and_adds_them_as_subtasks(tmp_path: Path) -> None:
    api = LocalApi(tmp_path / "todo.db")
    created = api.request("POST", "/subtask-templates", WRITE_TESTS)
    api.request("POST", "/subtask-templates", {"name": "Deploy"})
    assert [t["name"] for t in api.request("GET", "/subtask-templates")] == ["Deploy", "Write tests"]
    api.request("PATCH", f"/subtask-templates/{created['id']}", {"name": "Write the tests"})
    with pytest.raises(RemoteError, match="already exists"):
        api.request("POST", "/subtask-templates", {"name": "Deploy"})

    data = api.load_all()
    software = next(w for w in data["workflows"] if w["name"] == "Software")
    stages = sorted(software["stages"], key=lambda s: s["order"])
    parent = api.request("POST", "/tasks", {"name": "Release", "stage_id": stages[2]["id"],
                                            "assignee_id": None})
    template = next(t for t in api.request("GET", "/subtask-templates") if t["id"] == created["id"])
    subtask = api.request("POST", "/tasks", templates.subtask_fields(
        template, {"id": parent["id"], "first_stage_id": stages[0]["id"], "assignee_id": None}
    ))
    assert (subtask["name"], subtask["parent_id"], subtask["stage_id"], subtask["priority"],
            subtask["urgency"], subtask["description"], subtask["assignee_id"]) == (
        "Write the tests", parent["id"], stages[0]["id"], "Important", "High", "Unit and GUI", None
    )

    api.request("DELETE", f"/subtask-templates/{created['id']}")
    assert [t["name"] for t in api.request("GET", "/subtask-templates")] == ["Deploy"]
    assert any(t["id"] == subtask["id"] for t in api.load_all()["tasks"])  # the subtask stays


# -- the server -------------------------------------------------------------------------


@pytest.fixture
def server_client(tmp_path: Path) -> Iterator[Any]:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from todo_db.models import UserRole
    from todo_server.api import ServerConfig, create_app
    from todo_server.security import hash_password

    app = create_app(ServerConfig(db_path=tmp_path / "server.db", run_scheduler=False))
    with make_session_factory(app.state.engine)() as session:
        session.add(User(name="Ola", email="ola@example.com", role=UserRole.User,
                         password_hash=hash_password("correct horse")))
        session.commit()
    with TestClient(app) as test_client:
        yield test_client


def test_server_templates(server_client: Any) -> None:
    client = server_client
    assert client.get("/subtask-templates").status_code == 401  # only when logged in
    token = client.post("/auth/login", json={"email": "ola@example.com",
                                             "password": "correct horse"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    response = client.post("/subtask-templates", json=WRITE_TESTS, headers=auth)
    assert response.status_code == 201, response.text  # an ordinary user may add them
    template_id = response.json()["id"]
    assert client.post("/subtask-templates", json=WRITE_TESTS, headers=auth).status_code == 400
    assert client.post("/subtask-templates", json={"name": "X", "priority": "Huge"},
                       headers=auth).status_code == 422
    response = client.patch(f"/subtask-templates/{template_id}", json={"priority": "Maybe"},
                            headers=auth)
    assert response.json() == {"id": template_id, **WRITE_TESTS, "priority": "Maybe"}
    assert client.patch("/subtask-templates/99", json={"name": "Y"}, headers=auth).status_code == 404
    assert client.get("/subtask-templates", headers=auth).json() == [response.json()]
    assert client.delete(f"/subtask-templates/{template_id}", headers=auth).status_code == 204
    assert client.delete(f"/subtask-templates/{template_id}", headers=auth).status_code == 404
    assert client.get("/subtask-templates", headers=auth).json() == []


# -- the desktop program -------------------------------------------------------------------


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    tk = pytest.importorskip("tkinter")
    from todo_db.app import TodoApp

    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    engine = make_engine("sqlite://")
    create_all(engine)
    session = make_session_factory(engine)()
    seed(session)
    app = TodoApp(session)
    app.update()
    yield app
    app.destroy()


def test_desktop_window_edits_the_templates(window: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from tkinter import messagebox

    from todo_db.app import LocalTemplates, SubtaskTemplatesDialog

    warnings: list[str] = []
    monkeypatch.setattr(messagebox, "showwarning", lambda _title, text, **_kw: warnings.append(text))
    monkeypatch.setattr(messagebox, "askyesno", lambda *_args, **_kw: True)
    dialog = SubtaskTemplatesDialog(window, LocalTemplates(window.session))
    dialog._name.insert(0, "Pack the car")
    dialog._description.insert("1.0", "Tent, stove")
    dialog._priority.current(2)  # Important
    dialog.add_template()
    assert [item["name"] for item in dialog._items.values()] == ["Pack the car"]
    dialog.add_template()  # the same name again
    assert warnings == ["A template with this name already exists."]

    dialog.clear_form()
    assert dialog._name.get() == "" and dialog._priority.value() == "Normal"
    (iid,) = dialog._items
    dialog.list.selection_set(iid)
    dialog.update()
    assert dialog._name.get() == "Pack the car" and dialog._priority.value() == "Important"
    dialog._name.delete(0, "end")
    dialog._name.insert(0, "Pack the van")
    dialog.save_template()
    assert dialog.list.item(iid, "values")[0] == "Pack the van"

    dialog.list.selection_set(iid)
    dialog.delete_template()
    assert dialog._items == {}
    dialog.destroy()


def test_desktop_adds_subtasks_from_chosen_templates(
    window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from todo_db import app as todo_app

    session = window.session
    first = templates.add_template(session, WRITE_TESTS)
    second = templates.add_template(session, {"name": "Review"})
    chosen = [templates.template_data(first), templates.template_data(second)]
    parent = next(t for t in session.scalars(select(Task)) if t.assignee_id is not None)
    parent_stage = parent.stage

    class Picked:  # the templates window, with both templates chosen
        def __init__(self, _master: Any, _store: Any, parent_name: str | None = None) -> None:
            assert parent_name == parent.name
            self.chosen = chosen

    monkeypatch.setattr(todo_app, "SubtaskTemplatesDialog", Picked)
    monkeypatch.setattr(window, "wait_window", lambda _dialog: None)
    window.tree.selection_set(str(parent.id))
    window.subtasks_from_template()

    added = [t for t in parent.subtasks if t.name in ("Write tests", "Review")]
    assert [(t.name, t.priority, t.urgency, t.description) for t in added] == [
        ("Write tests", Priority.Important, Urgency.High, "Unit and GUI"),
        ("Review", Priority.Normal, Urgency.Medium, None),
    ]
    first_stage = parent_stage.workflow.stages[0]
    assert all(t.stage is first_stage and t.assignee_id == parent.assignee_id for t in added)
    assert window.tree.selection() == (str(added[-1].id),)  # shown and selected
