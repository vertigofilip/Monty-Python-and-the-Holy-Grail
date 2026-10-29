"""The desktop program's server mode, against a real server running in a thread."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402

from todo_db import remote  # noqa: E402
from todo_db.database import make_session_factory  # noqa: E402
from todo_db.models import (  # noqa: E402
    ChangeType, Priority, Stage, Task, Urgency, User, UserRole, Workflow,
)
from todo_db.remote import NotLoggedIn, RemoteError, RemoteTaskService, log_in  # noqa: E402
from todo_server.api import ServerConfig, create_app  # noqa: E402
from todo_server.security import hash_password  # noqa: E402

PASSWORD = "correct horse"


@pytest.fixture
def server(tmp_path: Path) -> Iterator[str]:
    """A real server on a free port with an admin (Ada) and a user (Ola); yields its address."""
    app = create_app(ServerConfig(db_path=tmp_path / "server.db", run_scheduler=False))
    with make_session_factory(app.state.engine)() as session:
        session.add_all([
            User(name="Ada", email="ada@example.com", role=UserRole.Admin,
                 password_hash=hash_password(PASSWORD)),
            User(name="Ola", email="ola@example.com", password_hash=hash_password(PASSWORD)),
        ])
        session.commit()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    while not uv.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(5)


@pytest.fixture(autouse=True)
def login_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "client_login.json"
    monkeypatch.setattr(remote, "LOGIN_FILE", path)
    return path


def stage_id(account: remote.RemoteAccount, workflow: str, stage: str) -> int:
    session = account.mirror.session
    return session.scalar(
        select(Stage.id).join(Workflow).where(Workflow.name == workflow, Stage.name == stage)
    )


def test_login_and_mirror(server: str) -> None:
    account = log_in(server, "OLA@example.com", PASSWORD, remember=False)

    assert account.user["name"] == "Ola" and not account.is_admin
    session = account.mirror.session
    assert {u.name for u in session.scalars(select(User))} == {"Ada", "Ola"}
    assert {w.name for w in session.scalars(select(Workflow))} == {"Simple", "Software"}


def test_wrong_password_and_unreachable_server(server: str) -> None:
    with pytest.raises(RemoteError, match="Wrong email or password"):
        log_in(server, "ola@example.com", "nope", remember=False)
    with pytest.raises(RemoteError, match="Cannot reach the server"):
        log_in("http://127.0.0.1:9", "ola@example.com", PASSWORD, remember=False)


def test_task_changes_go_through_the_server(server: str) -> None:
    account = log_in(server, "ola@example.com", PASSWORD, remember=False)
    service = RemoteTaskService(account)
    idea = stage_id(account, "Software", "Idea")

    parent = service.create_task("Report", idea, created_by_id=999, priority=Priority.Important)
    child = service.create_task("Draft", idea, 999, parent_id=parent.id, tag_ids=[])
    service.update_task(parent.id, None, name="Final report",
                        stage_id=stage_id(account, "Software", "Planned"))

    session = account.mirror.session  # a fresh copy after each change
    report = session.get(Task, parent.id)
    assert (report.name, report.stage.name, report.priority) == ("Final report", "Planned", Priority.Important)
    assert [sub.name for sub in report.subtasks] == ["Draft"]
    assert report.created_by.name == "Ola"  # the server records the logged-in user
    assert service.get_progress_percent(parent.id) == 0

    history = service.get_history(parent.id)
    assert [(h.change_type, h.field_name, h.changed_by.name) for h in history] == [
        (ChangeType.Created, None, "Ola"),
        (ChangeType.Updated, "Name", "Ola"),
        (ChangeType.StageChanged, "StageId", "Ola"),
    ]

    with pytest.raises(RemoteError, match="subtasks"):
        service.delete_task(parent.id, None)
    service.move_task(child.id, None, 1, None)
    assert [t.name for t in account.mirror.session.scalars(
        select(Task).where(Task.parent_id.is_(None)).order_by(Task.order))] == ["Draft", "Final report"]
    service.delete_task(child.id, None)
    assert account.mirror.session.get(Task, child.id) is None


def test_other_peoples_changes_arrive_on_sync(server: str) -> None:
    ada = log_in(server, "ada@example.com", PASSWORD, remember=False)
    ola = log_in(server, "ola@example.com", PASSWORD, remember=False)
    RemoteTaskService(ada).create_task("From Ada", stage_id(ada, "Simple", "To do"), 0)

    assert ola.mirror.session.scalars(select(Task)).all() == []
    ola.mirror.sync()
    assert [t.name for t in ola.mirror.session.scalars(select(Task))] == ["From Ada"]


def test_logout_ends_the_login(server: str) -> None:
    account = log_in(server, "ola@example.com", PASSWORD, remember=False)
    token = account.api.token

    account.logout()

    stale = remote.ApiClient(server, token)
    with pytest.raises(NotLoggedIn):
        stale.request("GET", "/auth/me")


def test_remembered_login(server: str, login_file: Path) -> None:
    log_in(server, "ola@example.com", PASSWORD, remember=True)
    assert login_file.exists()
    assert oct(login_file.stat().st_mode & 0o777) == "0o600"

    resumed = remote.resume_login()
    assert resumed is not None and resumed.user["name"] == "Ola"

    resumed.logout()  # also forgets the file
    assert not login_file.exists()
    assert remote.resume_login() is None


def test_not_remembered_login_leaves_no_file(server: str, login_file: Path) -> None:
    log_in(server, "ola@example.com", PASSWORD, remember=False)
    assert not login_file.exists()


def test_admin_manages_users_remotely(server: str) -> None:
    ada = log_in(server, "ada@example.com", PASSWORD, remember=False)
    assert ada.is_admin

    jan = ada.create_user({"name": "Jan", "email": "jan@example.com", "password": PASSWORD,
                           "role": "User"})
    assert {u["name"] for u in ada.list_users()} == {"Ada", "Ola", "Jan"}
    log_in(server, "jan@example.com", PASSWORD, remember=False)

    ada.update_user(jan["id"], {"is_active": False})
    with pytest.raises(RemoteError, match="Wrong email or password"):
        log_in(server, "jan@example.com", PASSWORD, remember=False)

    ola = log_in(server, "ola@example.com", PASSWORD, remember=False)
    with pytest.raises(RemoteError, match="Administrators only"):
        ola.list_users()


def test_admin_changes_server_settings(server: str) -> None:
    ada = log_in(server, "ada@example.com", PASSWORD, remember=False)
    assert ada.get_settings() == {"auto_compress_enabled": False, "compress_after_days": 90}

    ada.save_settings({"auto_compress_enabled": True, "compress_after_days": 30})
    assert ada.get_settings() == {"auto_compress_enabled": True, "compress_after_days": 30}

    ola = log_in(server, "ola@example.com", PASSWORD, remember=False)
    with pytest.raises(RemoteError, match="Administrators only"):
        ola.get_settings()


def test_window_shows_whether_the_server_is_reached(server: str) -> None:
    tk = pytest.importorskip("tkinter")
    import httpx

    from todo_db.app import TodoApp

    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    account = log_in(server, "ola@example.com", PASSWORD, remember=False)
    assert account.api.connected is True
    app = TodoApp(account=account)
    try:
        address = server.split("://", 1)[1]
        assert app._connection.cget("text") == f"● Connected to {address}"
        reached = account.api._http
        account.api._http = httpx.Client(base_url="http://127.0.0.1:9", timeout=2)  # nobody there
        app._sync_tick()
        assert account.api.connected is False
        assert app._connection.cget("text") == f"● No connection to {address}"
        account.api._http.close()
        account.api._http = reached
        app._sync_tick()
        assert app._connection.cget("text") == f"● Connected to {address}"
    finally:
        app.destroy()


def test_window_adds_subtasks_from_the_servers_templates(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tk = pytest.importorskip("tkinter")

    from todo_db import app as todo_app

    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    account = log_in(server, "ola@example.com", PASSWORD, remember=False)
    store = todo_app.RemoteTemplates(account.api)
    pack = store.add({"name": "Pack", "priority": "Important"})
    assert store.update(pack["id"], {"urgency": "High"})["urgency"] == "High"
    assert [t["name"] for t in store.list()] == ["Pack"]

    service = RemoteTaskService(account)
    parent = service.create_task("Trip", stage_id(account, "Software", "Review"), 0)
    app = todo_app.TodoApp(account=account)
    try:
        class Picked:  # the templates window, with "Pack" chosen
            def __init__(self, _master: object, chosen_from: object, parent_name: str) -> None:
                assert isinstance(chosen_from, todo_app.RemoteTemplates)
                self.chosen = chosen_from.list()

        monkeypatch.setattr(todo_app, "SubtaskTemplatesDialog", Picked)
        monkeypatch.setattr(app, "wait_window", lambda _dialog: None)
        app.tree.selection_set(str(parent.id))
        app.subtasks_from_template()
        trip = account.mirror.session.get(Task, parent.id)
        (subtask,) = trip.subtasks
        assert (subtask.name, subtask.priority, subtask.urgency, subtask.stage.name) == (
            "Pack", Priority.Important, Urgency.High, "Idea"  # the first stage of Software
        )
        assert subtask.assignee_id == trip.assignee_id == account.user["id"]
    finally:
        app.destroy()
    store.delete(pack["id"])
    assert store.list() == []
