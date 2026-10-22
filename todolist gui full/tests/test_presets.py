"""Saved filter presets: storage in settings.json and applying them in the window."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from sqlalchemy import select  # noqa: E402

from todo_db import app as todo_app  # noqa: E402
from todo_db import i18n, settings  # noqa: E402
from todo_db.app import (  # noqa: E402
    FilterPreset, SortPreset, TodoApp, load_presets, load_sort, load_sort_presets, save_presets,
    save_sort_presets,
)
from todo_db.database import create_all, make_engine, make_session_factory  # noqa: E402
from todo_db.models import Tag, User  # noqa: E402
from todo_db.seed import seed  # noqa: E402


@pytest.fixture(autouse=True)
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", path)
    yield path
    i18n.set_language("en")


@pytest.fixture
def window() -> Iterator[TodoApp]:
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


def test_presets_are_saved_and_broken_entries_skipped(settings_file: Path) -> None:
    presets = [FilterPreset("Mine, open", "report", {"Stage": "not-done", "Assignee": "id:1"})]
    save_presets(presets)
    assert load_presets() == presets

    data = json.loads(settings_file.read_text())
    data["filter_presets"] += ["junk", {"text": "no name"},
                               {"name": "Odd", "filters": {"Nope": "x", "Priority": 3}}]
    settings_file.write_text(json.dumps(data))
    assert load_presets() == presets + [FilterPreset("Odd")]


def test_current_filters_round_trip_in_any_language(window: TodoApp) -> None:
    anna = window.session.scalars(select(User).order_by(User.id)).first()
    window._pick_filter("Stage", "not-done")
    window._pick_filter("Assignee", f"id:{anna.id}")
    window._pick_filter("Priority", "Important")
    window._name_filter.set("plan")
    preset = window._current_filters()
    assert preset.text == "plan"
    assert preset.filters == {"Stage": "not-done", "Assignee": f"id:{anna.id}", "Priority": "Important"}

    window.clear_filters()
    i18n.set_language("pl")
    window._build()  # what switching the language does
    window.apply_preset(preset)
    assert window._column_filters["Stage"].get() == "(niezakończone)"
    assert window._column_filters["Assignee"].get() == anna.name
    assert window._column_filters["Priority"].get() == "Ważny"
    assert window._name_filter.get() == "plan"


def test_a_choice_that_no_longer_exists_is_set_to_all(
    window: TodoApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(todo_app.messagebox, "showwarning",
                        lambda _title, text, **_kw: warnings.append(text))
    tag = window.session.scalars(select(Tag)).first()
    window.apply_preset(FilterPreset("Old", filters={"Tags": "id:999", "Stage": "done"}))
    assert window._column_filters["Tags"].get() == "All"
    assert window._column_filters["Stage"].get() == "(done)"
    assert len(warnings) == 1 and "Tags" in warnings[0]
    assert tag is not None  # the real tags are still offered


def test_sort_presets_are_saved_and_broken_entries_skipped(settings_file: Path) -> None:
    presets = [SortPreset("Most important", (("Priority", True), ("Task", False)))]
    save_sort_presets(presets)
    assert load_sort_presets() == presets

    data = json.loads(settings_file.read_text())
    data["sort_presets"] += [{"sort": []}, {"name": "Odd", "sort": [["Nope", True], ["Task"]]}]
    settings_file.write_text(json.dumps(data))
    assert load_sort_presets() == presets + [SortPreset("Odd")]


def test_applying_a_sort_preset_sorts_and_remembers_it(window: TodoApp) -> None:
    window.sort_presets = [SortPreset("By name", (("Task", False),))]
    window.sort_presets_changed()
    window._sort_menu.invoke(0)  # the preset's menu entry
    assert window._sort == [("Task", False)]
    assert load_sort() == [("Task", False)]  # kept for the next start, like Sort… does
    names = [window.tree.item(iid, "text") for iid in window.tree.get_children()]
    assert names == sorted(names, key=todo_app.text_sort_key)
