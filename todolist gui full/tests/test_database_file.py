"""Choosing where the database file is: desktop program (local mode) and server."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from todo_db import app as todo_app  # noqa: E402
from todo_db import settings  # noqa: E402
from todo_db.app import DB_FILE, database_path, save_database_path  # noqa: E402


@pytest.fixture(autouse=True)
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", path)
    monkeypatch.setattr(todo_app, "_db_override", None)
    yield path


def test_default_saved_and_one_run_database(tmp_path: Path, settings_file: Path) -> None:
    assert database_path() == DB_FILE  # todo.db where the program starts

    save_database_path(tmp_path / "work" / "tasks.db")
    assert database_path() == tmp_path / "work" / "tasks.db"
    assert json.loads(settings_file.read_text())["database"] == str(tmp_path / "work" / "tasks.db")

    todo_app._db_override = tmp_path / "once.db"  # --db / TODO_DB: this run only
    assert database_path() == tmp_path / "once.db"
    save_database_path(DB_FILE)  # back to the default (and the override is dropped)
    assert database_path() == DB_FILE
    assert json.loads(settings_file.read_text())["database"] is None


def test_db_option_starts_local_mode_on_that_file(
    tmp_path: Path, settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_file.write_text(json.dumps({"client_mode": "server"}))  # the server was used last
    opened: list[Path] = []
    monkeypatch.setattr(todo_app, "setup_logging", lambda: None)
    monkeypatch.setattr(todo_app, "run_local", lambda path: opened.append(path) or "quit")
    monkeypatch.setattr(todo_app, "resume_login", lambda: pytest.fail("asked the server"))
    todo_app.main(["--db", str(tmp_path / "mine.db")])
    assert opened == [tmp_path / "mine.db"]


def test_db_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TODO_DB", str(tmp_path / "env.db"))
    assert todo_app.parse_args([]).db == tmp_path / "env.db"
    assert todo_app.parse_args(["--db", "x.db"]).db == Path("x.db")  # the option wins


def test_a_file_that_is_not_a_database_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(todo_app, "show_error", errors.append)
    junk = tmp_path / "notes.db"
    junk.write_text("not a database " * 100)
    assert todo_app.run_local(junk) == "login"  # back to the login window
    assert errors and str(junk) in errors[0]


def test_a_new_file_is_set_up_and_switching_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    first, second = tmp_path / "a" / "first.db", tmp_path / "second.db"
    windows: list[todo_app.TodoApp] = []

    def run(app: todo_app.TodoApp, _find_due: object) -> None:
        windows.append(app)
        assert str(first) in app.title()
        monkeypatch.setattr(todo_app, "choose_database_file", lambda *_args: second)
        app.change_database()  # Account -> Database file…

    monkeypatch.setattr(todo_app, "run_with_reminders", run)
    assert todo_app.run_local(first) == "reopen"  # the folder was created, the file set up
    assert first.exists() and windows[0].next_database == second
    assert database_path() == second  # also for the next start


def test_server_takes_db_before_or_after_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fastapi")
    from todo_server import __main__ as server_cli

    monkeypatch.setattr(server_cli, "ask_password", lambda: "long enough secret")
    after = tmp_path / "new" / "folder" / "server.db"
    assert server_cli.main(["create-admin", "--db", str(after), "--name", "A",
                            "--email", "a@example.com"]) == 0
    assert after.exists()  # the folders were created
    before = tmp_path / "other.db"
    assert server_cli.main(["--db", str(before), "set-password",
                            "--email", "a@example.com"]) == 1  # a different file: no such user
    monkeypatch.setenv("TODO_SERVER_DB", str(after))
    assert server_cli.main(["set-password", "--email", "a@example.com"]) == 0


def test_todo_home_keeps_the_files_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As the Nix package starts it: TODO_HOME=~/.local/share/todolist.
    monkeypatch.chdir(tmp_path)  # where the user is; restored after the test
    monkeypatch.setenv("TODO_HOME", str(tmp_path / "home" / "todolist"))
    monkeypatch.setattr(settings, "SETTINGS_FILE", Path("settings.json"))  # relative, as normally
    opened: list[Path] = []
    monkeypatch.setattr(todo_app, "setup_logging", lambda: None)
    monkeypatch.setattr(todo_app, "run_local", lambda path: opened.append(path) or "quit")
    todo_app.main(["--db", "mine.db"])
    assert opened == [tmp_path / "mine.db"]  # relative to where the user was
    assert (tmp_path / "home" / "todolist" / "settings.json").exists()
