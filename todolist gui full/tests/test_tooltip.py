"""The task's description shown when the mouse rests over it in the list."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from sqlalchemy import select  # noqa: E402

from todo_db import settings  # noqa: E402
from todo_db.app import TodoApp, TreeTooltip  # noqa: E402
from todo_db.database import create_all, make_engine, make_session_factory  # noqa: E402
from todo_db.models import Task  # noqa: E402
from todo_db.seed import seed  # noqa: E402


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TodoApp]:
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(TreeTooltip, "DELAY_MS", 10)
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


def rest_over(app: TodoApp, task: Task) -> None:
    """Move the mouse over the task's row and wait longer than the delay."""
    app.tree.see(str(task.id))
    app.update()
    _x, y, _width, height = app.tree.bbox(str(task.id))
    app.tree.event_generate("<Motion>", x=50, y=y + height // 2)
    app.tree.after(50)  # sleeps 50 ms
    app.update()


def shown_text(app: TodoApp) -> str | None:
    window = app._tooltip._window
    return None if window is None else window.winfo_children()[0].cget("text")


def test_description_shows_after_a_moment_and_goes_on_leaving(window: TodoApp) -> None:
    tasks = list(window.session.scalars(select(Task)))
    described, plain = tasks[0], tasks[1]
    described.description, plain.description = "Buy milk\nand bread", None
    window.session.commit()
    window.refresh()

    rest_over(window, described)
    assert shown_text(window) == "Buy milk\nand bread"
    window.tree.event_generate("<Leave>")
    assert shown_text(window) is None

    rest_over(window, plain)
    assert shown_text(window) is None  # no description: nothing shown

    rest_over(window, described)
    window.refresh()  # the rows are made again
    assert shown_text(window) is None


def test_description_shows_over_the_coloured_cells_too(window: TodoApp) -> None:
    task = next(t for t in window.session.scalars(select(Task)) if not t.stage.is_final)
    task.description = "Over the colours"
    window.session.commit()
    window.refresh()
    window.update()
    cell = next(c for c in window._level_cells if c.winfo_ismapped() and c.iid == str(task.id))
    window.update()  # pending window events first (a real mouse leaving the window hides it)
    cell.event_generate("<Motion>", x=3, y=3)
    window.tree.after(50)  # sleeps 50 ms
    window.update()
    assert shown_text(window) == "Over the colours"
