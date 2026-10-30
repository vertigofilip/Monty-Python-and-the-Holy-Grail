"""The history panel's filters and sort order in the desktop program."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from todo_db import settings
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.models import ChangeType, Task, TaskChange, User
from todo_db.seed import seed

tk = pytest.importorskip("tkinter")


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
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


@pytest.fixture
def task(window: Any) -> Task:
    """A selected task with three changes of its own: only they are in its history."""
    session = window.session
    task = session.scalars(select(Task)).first()
    session.query(TaskChange).filter(TaskChange.task_id == task.id).delete()
    user = session.scalars(select(User)).first()
    now = datetime.now(timezone.utc)
    session.add_all([
        TaskChange(task_id=task.id, changed_at=now - timedelta(days=40), changed_by_id=user.id,
                   change_type=ChangeType.Created),
        TaskChange(task_id=task.id, changed_at=now - timedelta(days=3), changed_by_id=None,
                   change_type=ChangeType.Updated, field_name="Name", old_value="Alpha",
                   new_value="Beta"),
        TaskChange(task_id=task.id, changed_at=now, changed_by_id=user.id,
                   change_type=ChangeType.Updated, field_name="Location", old_value="Gym",
                   new_value="Zoo"),
    ])
    session.commit()
    window.tree.selection_set(str(task.id))
    window.update()
    return task


def shown(window: Any, column: str = "New value") -> list[str]:
    return [window.history.set(iid, column) for iid in window.history.get_children()]


def test_no_filters_show_every_change_oldest_first(window: Any, task: Task) -> None:
    assert shown(window) == ["", "Beta", "Zoo"]


def test_drop_down_filters(window: Any, task: Task) -> None:
    filters = window._history_filters
    filters["Who"].set_keys(["system"])
    window._show_history_rows()
    assert shown(window) == ["Beta"]
    filters["Who"].set_keys([])
    filters["When"].set_keys(["today", "older"])  # several choices: either
    window._show_history_rows()
    assert shown(window) == ["", "Zoo"]
    filters["When"].set_keys(["week"])
    filters["Change"].set_keys(["Updated"])
    filters["Field"].set_keys(["name:Location"])  # all columns together
    window._show_history_rows()
    assert shown(window) == ["Zoo"]
    window.clear_history_filters()
    assert shown(window) == ["", "Beta", "Zoo"]


def test_text_filters_search_the_values(window: Any, task: Task) -> None:
    window._history_texts["Old value"].set("gy")
    assert shown(window) == ["Zoo"]
    window._history_texts["Old value"].set("")
    window._history_texts["New value"].set("BET")
    assert shown(window) == ["Beta"]


def test_filters_stay_when_another_task_is_selected(window: Any, task: Task) -> None:
    window._history_filters["Field"].set_keys(["name:Location"])
    other = next(t for t in window.session.scalars(select(Task)) if t.id != task.id)
    window.tree.selection_set(str(other.id))
    window.update()
    assert window._history_filters["Field"].chosen_keys() == ["name:Location"]
    assert shown(window) == []
    window.tree.selection_set(str(task.id))
    window.update()
    assert shown(window) == ["Zoo"]


def test_sort_order_is_shown_and_remembered(
    window: Any, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    from todo_db import app as todo_app

    class Sorted:
        def __init__(self, _master: Any, sort: Any, title: str, fields: tuple[str, ...]) -> None:
            assert fields == todo_app.HISTORY_COLUMNS
            self.result = [("When", True)]

    monkeypatch.setattr(todo_app, "SortDialog", Sorted)
    monkeypatch.setattr(window, "wait_window", lambda _dialog: None)
    window.open_history_sort()
    assert shown(window) == ["Zoo", "Beta", ""]
    assert window.history.heading("When", "text") == "When ▼"
    assert settings.load_setting("history_sort") == [["When", True]]

    window._history_sort = [("New value", False)]  # empty values last
    window._show_history_rows()
    assert shown(window) == ["Beta", "Zoo", ""]
    window._history_sort = [("New value", True)]
    window._show_history_rows()
    assert shown(window) == ["Zoo", "Beta", ""]


def click(window: Any, x: int, y: int) -> None:
    """A single click: far enough in time from the last one not to be a double click."""
    window.clicks = getattr(window, "clicks", 0) + 10_000
    window.tree.event_generate("<Button-1>", x=x, y=y, time=window.clicks)
    window.tree.event_generate("<ButtonRelease-1>", x=x, y=y, time=window.clicks + 10)
    window.update()


def test_a_task_can_be_unselected(window: Any, task: Task) -> None:
    iid = str(task.id)
    x, y, width, height = window.tree.bbox(iid, "Task")
    click(window, x + 30, y + 2)
    assert window.tree.selection() == ()  # it was selected
    click(window, x + 30, y + 2)
    assert window.tree.selection() == (iid,)
    window.unselect()
    assert window.tree.selection() == ()
    window.tree.selection_set(iid)
    window.update()
    click(window, x + 30, window.tree.winfo_height() - 5)  # below the tasks
    assert window.tree.selection() == ()
    window.tree.selection_set(iid)
    window.update()
    click(window, x + 30, 5)  # a heading leaves it
    assert window.tree.selection() == (iid,)


def test_double_click_on_the_selected_task_still_edits_it(
    window: Any, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited: list[Any] = []
    monkeypatch.setattr(window, "edit_task", lambda: edited.append(window.tree.selection()))
    x, y, _width, _height = window.tree.bbox(str(task.id), "Task")
    window.tree.event_generate("<Button-1>", x=x + 30, y=y + 2, time=1000)  # unselects it
    window.tree.event_generate("<ButtonRelease-1>", x=x + 30, y=y + 2, time=1010)
    window.tree.event_generate("<Button-1>", x=x + 30, y=y + 2, time=1020)  # now a double click
    window.update()
    assert edited == [(str(task.id),)]


def test_with_no_selection_the_history_covers_the_tasks_in_the_list(
    window: Any, task: Task
) -> None:
    window.unselect()
    window.update()
    everything = {window.history.set(iid, "Task") for iid in window.history.get_children()}
    assert everything == {t.name for t in window.session.scalars(select(Task))}

    window._history_texts["Task"].set(task.name[:5].upper())  # the history's own filter
    assert {window.history.set(iid, "Task") for iid in window.history.get_children()} == {task.name}
    window._history_texts["Task"].set("")

    window._name_filter.set(task.name)  # only what the task list shows
    window.update()
    names = {window.history.set(iid, "Task") for iid in window.history.get_children()}
    assert task.name in names and names == {
        t.name for t in window.session.scalars(select(Task))
        if window.tree.exists(str(t.id))
    }
