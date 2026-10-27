"""The task form: a new task repeats once until a repeat rule is chosen, then forever."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from sqlalchemy.orm import Session  # noqa: E402

from todo_db import settings  # noqa: E402
from todo_db.app import TaskDialog  # noqa: E402
from todo_db.database import create_all, make_engine, make_session_factory  # noqa: E402
from todo_db.seed import seed  # noqa: E402


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    engine = make_engine("sqlite://")
    create_all(engine)
    with make_session_factory(engine)() as session:
        seed(session)
        yield session


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield root
    root.destroy()


def choose_rule(dialog: TaskDialog, index: int) -> None:
    dialog._rule.current(index)
    dialog._rule.event_generate("<<ComboboxSelected>>")
    dialog.update()


def test_new_task_repeats_once_and_forever_once_a_rule_is_chosen(
    root: tk.Tk, session: Session
) -> None:
    dialog = TaskDialog(root, session, None)
    assert dialog._rule.value() is None
    assert dialog._count.get() == "1"
    choose_rule(dialog, 1)
    assert dialog._rule.value() is not None
    assert dialog._count.get() == "0"  # forever
    choose_rule(dialog, 0)
    assert dialog._count.get() == "1"  # no repeating: once again
    dialog.destroy()


def test_a_count_typed_by_hand_is_kept(root: tk.Tk, session: Session) -> None:
    dialog = TaskDialog(root, session, None)
    dialog._count.set(5)
    choose_rule(dialog, 1)
    assert dialog._count.get() == "5"
    dialog.destroy()
