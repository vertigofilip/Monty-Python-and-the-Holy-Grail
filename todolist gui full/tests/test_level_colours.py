"""Colours of the priority and urgency: coloured cells on the computer, coloured text on the phone."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from todo_mobile.tasks import task_details

tk = pytest.importorskip("tkinter")

from sqlalchemy import select  # noqa: E402

from todo_db import settings  # noqa: E402
from todo_db.app import LEVEL_COLOURS, TodoApp  # noqa: E402
from todo_db.database import create_all, make_engine, make_session_factory  # noqa: E402
from todo_db.models import Priority, Task, Urgency  # noqa: E402
from todo_db.seed import seed  # noqa: E402

GREEN, YELLOW, RED = LEVEL_COLOURS[0], LEVEL_COLOURS[1], LEVEL_COLOURS[2]


def phone_task(**changes: object) -> dict[str, object]:
    task = {
        "stage": "To do", "due_date": None, "priority": "Normal", "urgency": "Medium",
        "assignee": None, "location": None, "tags": [], "progress_percent": 0, "done": False,
        "repeat_rule_id": None,
    }
    return {**task, **changes}


def test_phone_colours_the_priority_and_urgency_and_escapes_the_rest() -> None:
    task = phone_task(priority="Important", urgency="Low", stage="[x] & co")
    assert task_details(task, markup=True) == (
        "&bl;x&br; &amp; co · [color=ff6b5e]Priority: Important[/color]"
        " · [color=6fdc7a]Urgency: Low[/color]"
    )
    assert task_details(phone_task(), markup=True) == (
        "To do · [color=ffd54f]Priority: Normal[/color] · [color=ffd54f]Urgency: Medium[/color]"
    )
    assert task_details(task) == "[x] & co · Priority: Important · Urgency: Low"
    done = phone_task(priority="Important", done=True)
    assert task_details(done, markup=True) == (  # done tasks stay grey
        "To do · Priority: Important · Urgency: Medium"
    )


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TodoApp]:
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
    app.geometry("1100x500")
    app.update()
    yield app
    app.destroy()


def cells(app: TodoApp, task: Task) -> dict[str, tuple[str, str]]:
    """The coloured cells shown in the task's row: column -> (text, colour)."""
    app.update()
    shown = {}
    for cell in app._level_cells:
        if cell.winfo_ismapped() and cell.iid == str(task.id):
            name = next(
                column for column in ("Priority", "Urgency")
                if app.tree.bbox(cell.iid, column)[0] + 1 == cell.winfo_x()
            )
            shown[name] = (cell.cget("text"), cell.cget("background").upper())
    return shown


def test_desktop_colours_the_priority_and_urgency_cells(window: TodoApp) -> None:
    tasks = list(window.session.scalars(select(Task)))
    open_tasks = [task for task in tasks if not task.stage.is_final]
    first, second = open_tasks[0], open_tasks[1]
    first.priority, first.urgency = Priority.Important, Urgency.Low
    second.priority, second.urgency = Priority.Normal, Urgency.High
    window.session.commit()
    window.refresh()

    assert cells(window, first) == {"Priority": ("Important", RED), "Urgency": ("Low", GREEN)}
    assert cells(window, second) == {"Priority": ("Normal", YELLOW), "Urgency": ("High", RED)}
    # The cell lies over the row's own cell.
    cell = next(c for c in window._level_cells if c.iid == str(first.id) and c.winfo_ismapped())
    assert window.tree.identify_row(cell.winfo_y() + 2) == str(first.id)

    # Done tasks stay grey.
    first.stage = next(stage for stage in first.stage.workflow.stages if stage.is_final)
    window.session.commit()
    window.refresh()
    assert window.tree.exists(str(first.id)) and cells(window, first) == {}

    # Rows scrolled out of view have no cells; scrolling brings them back in place.
    window.tree.yview_moveto(1.0)
    window.update()
    for cell in window._level_cells:
        if cell.winfo_ismapped():
            assert window.tree.bbox(cell.iid)  # its row is visible


def test_clicking_a_coloured_cell_selects_its_task(window: TodoApp) -> None:
    window.refresh()
    window.update()
    cell = next(c for c in window._level_cells if c.winfo_ismapped())
    cell.event_generate("<Button-1>", x=2, y=2)
    window.update()
    assert window.tree.selection() == (cell.iid,)


def test_phone_marks_tasks_due_today() -> None:
    from datetime import date

    from todo_mobile.tasks import is_due_today, is_overdue

    today = date(2026, 10, 29)
    due = phone_task(due_date="2026-10-29")
    assert is_due_today(due, today) and not is_overdue(due, today)
    assert "Due date: 2026-10-29 (today)" in task_details(due, today)
    assert not is_due_today(phone_task(due_date="2026-10-30"), today)
    assert not is_due_today(phone_task(due_date="2026-10-29", done=True), today)  # done: grey
    assert not is_due_today(phone_task(), today)  # no due date


def test_desktop_shows_tasks_due_today_in_green(window: TodoApp) -> None:
    from datetime import date, timedelta

    from todo_db.app import DUE_TODAY_COLOUR

    tasks = [task for task in window.session.scalars(select(Task)) if not task.stage.is_final]
    today, yesterday, tomorrow = tasks[0], tasks[1], tasks[2]
    today.due_date = date.today()
    yesterday.due_date = date.today() - timedelta(days=1)
    tomorrow.due_date = date.today() + timedelta(days=1)
    done = next(task for task in window.session.scalars(select(Task)) if task.stage.is_final)
    done.due_date = date.today()
    window.session.commit()
    window.refresh()

    tags = {task.id: window.tree.item(str(task.id), "tags") for task in (today, yesterday,
                                                                       tomorrow, done)}
    assert "today" in tags[today.id] and "overdue" in tags[yesterday.id]
    assert "today" not in tags[tomorrow.id] and "overdue" not in tags[tomorrow.id]
    assert "done" in tags[done.id] and "today" not in tags[done.id]
    assert str(window.tree.tag_configure("today", "foreground")) == DUE_TODAY_COLOUR
