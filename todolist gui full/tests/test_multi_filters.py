"""Column filters with several choices: a task passes if it matches any of them."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from todo_db import settings
from todo_db.presets import FilterPreset, filter_keys, filter_value, load_presets, save_presets
from todo_mobile.tasks import missing_filters, task_rows


@pytest.fixture(autouse=True)
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", path)
    return path


def test_one_key_is_saved_as_before_and_several_as_a_list(settings_file: Path) -> None:
    assert filter_value([]) is None
    assert filter_value(["done"]) == "done"
    assert filter_value(["name:To do", "name:In progress"]) == ["name:To do", "name:In progress"]
    assert filter_keys("done") == ["done"] and filter_keys(None) == []
    assert filter_keys(["a", 3, "b"]) == ["a", "b"]

    preset = FilterPreset("Started", filters={"Stage": ["name:To do", "name:In progress"],
                                              "Priority": "Important"})
    save_presets([preset])
    saved = json.loads(settings_file.read_text())["filter_presets"][0]["filters"]
    assert saved == {"Stage": ["name:To do", "name:In progress"], "Priority": "Important"}
    assert load_presets() == [preset]

    # Broken lists are cleaned up; an empty one means no filter.
    data = json.loads(settings_file.read_text())
    data["filter_presets"][0]["filters"] = {"Stage": ["name:To do", 7], "Tags": []}
    settings_file.write_text(json.dumps(data))
    assert load_presets()[0].filters == {"Stage": "name:To do"}


def phone_task(task_id: int, stage: str, **changes: object) -> dict[str, object]:
    task = {
        "id": task_id, "name": f"Task {task_id}", "description": None, "stage": stage,
        "stage_id": task_id, "done": stage == "Done", "priority": "Normal", "urgency": "Medium",
        "assignee": None, "assignee_id": None, "location": None, "tags": [], "parent_id": None,
        "order": task_id, "due_date": None, "progress_percent": 0, "repeat_rule_id": None,
    }
    return {**task, **changes}


def test_phone_shows_tasks_matching_any_chosen_stage() -> None:
    tasks = [phone_task(1, "To do"), phone_task(2, "In progress"), phone_task(3, "Review"),
             phone_task(4, "Done")]
    rows = task_rows(tasks, filters={"Stage": ["name:To do", "name:In progress"]})
    assert [row.task["stage"] for row in rows] == ["To do", "In progress"]
    # Columns still combine: the stage is one of them AND the priority is Important.
    tasks[1]["priority"] = "Important"
    rows = task_rows(tasks, filters={"Stage": ["name:To do", "name:In progress"],
                                     "Priority": "Important"})
    assert [row.task["id"] for row in rows] == [2]

    data = {"tasks": tasks, "workflows": [{"id": 1, "stages": [{"name": "To do"}]}]}
    assert missing_filters({"Stage": ["name:To do", "name:Gone"]}, data) == ["Stage"]
    assert missing_filters({"Stage": ["name:To do"]}, data) == []


# -- the desktop program ---------------------------------------------------------------


@pytest.fixture
def window() -> Iterator[object]:
    tk = pytest.importorskip("tkinter")
    from todo_db.app import TodoApp
    from todo_db.database import create_all, make_engine, make_session_factory
    from todo_db.seed import seed

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


def matching_stages(window: object) -> set[str]:
    """The stages of the tasks the list shows as matching (not as greyed context)."""
    tree = window.tree  # type: ignore[attr-defined]
    stages = set()

    def walk(parent: str) -> None:
        for iid in tree.get_children(parent):
            if "context" not in tree.item(iid, "tags"):
                stages.add(tree.set(iid, "Stage"))
            walk(iid)

    walk("")
    return stages


def test_desktop_filter_with_two_stages_shows_both(window: object) -> None:
    window._pick_filter("Stage", ["name:To do", "name:In progress"])  # type: ignore[attr-defined]
    window.refresh()  # type: ignore[attr-defined]
    assert matching_stages(window) == {"To do", "In progress"}
    stage = window._column_filters["Stage"]  # type: ignore[attr-defined]
    assert stage.get() == "In progress, To do"  # in the order of the list
    preset = window._current_filters()  # type: ignore[attr-defined]
    assert preset.filters == {"Stage": ["name:In progress", "name:To do"]}

    window.clear_filters()  # type: ignore[attr-defined]
    assert stage.get() == "All" and len(matching_stages(window)) > 2


def test_desktop_ticking_in_the_list_filters_at_once(window: object) -> None:
    stage = window._column_filters["Stage"]  # type: ignore[attr-defined]
    stage.event_generate("<Button-1>")
    window.update()  # type: ignore[attr-defined]
    listbox = stage._listbox
    labels = list(listbox.get(0, "end"))
    for name in ("To do", "In progress"):
        listbox.selection_set(labels.index(name))
        listbox.event_generate("<<ListboxSelect>>")
        window.update()  # type: ignore[attr-defined]
    assert stage._popup is not None  # the list stays open for more ticks
    assert matching_stages(window) == {"To do", "In progress"}

    stage._clear()  # "All"
    window.update()  # type: ignore[attr-defined]
    assert stage.get() == "All" and len(matching_stages(window)) > 2
    stage._popup.event_generate("<Escape>")
    window.update()  # type: ignore[attr-defined]
    assert stage._popup is None
