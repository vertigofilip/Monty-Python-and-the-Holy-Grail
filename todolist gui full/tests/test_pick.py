"""Drawing a random task: unfinished, without subtasks, favouring important and urgent ones."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from todo_db import pick, settings
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.models import Priority, Task, Urgency
from todo_db.seed import seed


def test_the_order_of_the_levels() -> None:
    order = sorted(pick.WEIGHTS, key=pick.WEIGHTS.get, reverse=True)
    assert order == [
        ("Important", "High"), ("Normal", "High"), ("Important", "Medium"),
        ("Normal", "Medium"), ("Important", "Low"), ("Normal", "Low"),
        ("Maybe", "High"), ("Maybe", "Medium"), ("Maybe", "Low"),
    ]
    assert pick.weight("Important", "High") == 9 and pick.weight("Maybe", "Low") == 1
    # Every level of Priority and Urgency has a place.
    assert set(pick.WEIGHTS) == {(p.name, u.name) for p in Priority for u in Urgency}


def test_more_important_and_urgent_tasks_come_up_more_often() -> None:
    tasks = [("top", "Important", "High"), ("mid", "Normal", "Medium"),
             ("low", "Maybe", "Low")]
    rng = random.Random(1)
    drawn = Counter(
        pick.pick_task(tasks, lambda t: (t[1], t[2]), rng)[0] for _ in range(14000)
    )
    # Weights 9, 6 and 1 out of 16.
    assert drawn["top"] == pytest.approx(14000 * 9 / 16, rel=0.05)
    assert drawn["mid"] == pytest.approx(14000 * 6 / 16, rel=0.05)
    assert drawn["low"] == pytest.approx(14000 * 1 / 16, rel=0.15)
    assert pick.pick_task([], lambda t: ("Normal", "Medium")) is None


# -- the desktop program ---------------------------------------------------------------


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


def test_desktop_draws_only_unfinished_tasks_without_subtasks(window: Any) -> None:
    from todo_db.app import RandomTaskWindow

    tasks = list(window.session.scalars(select(Task)))
    candidates = window.random_candidates()
    assert candidates and all(not t.stage.is_final and not t.subtasks for t in candidates)
    expected = {t.id for t in tasks if not t.stage.is_final and not t.subtasks}
    assert {t.id for t in candidates} == expected
    assert any(t.subtasks for t in tasks)  # the seed has a parent, left out

    shown = RandomTaskWindow(window)
    window.update()
    first = shown.task
    assert first.id in expected and shown._name.cget("text") == first.name
    if len(expected) > 1:
        shown.draw()
        assert shown.task.id != first.id  # "Another" draws a different one
    drawn = shown.task.id
    window._pick_filter("Stage", "done")  # the drawn task is hidden...
    window.refresh()
    assert not window.tree.exists(str(drawn))
    shown.show_in_list()  # ...so the filters are cleared to show it
    assert window.tree.selection() == (str(drawn),)


def test_desktop_says_so_when_there_is_nothing_to_draw(
    window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tkinter import messagebox

    for task in window.session.scalars(select(Task)):
        task.stage = next(s for s in task.stage.workflow.stages if s.is_final)
    window.session.commit()
    said: list[str] = []
    monkeypatch.setattr(messagebox, "showinfo", lambda _title, text, **_kw: said.append(text))
    window.random_task()
    assert said == ["There are no unfinished tasks without subtasks."]
