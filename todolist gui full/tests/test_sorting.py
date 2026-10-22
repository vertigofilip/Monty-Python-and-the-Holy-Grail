"""Alphabetical sort key used by the task list."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

from todo_db.app import text_sort_key  # noqa: E402


def test_polish_alphabet_order() -> None:
    words = ["Żaba", "zebra", "Ćwiczenia", "cytryna", "dom", "Łódź", "lis", "mapa", "źrebak", "Alpha"]
    assert sorted(words, key=text_sort_key) == [
        "Alpha", "cytryna", "Ćwiczenia", "dom", "lis", "Łódź", "mapa", "zebra", "źrebak", "Żaba",
    ]


def test_other_accents_sort_as_base_letter() -> None:
    assert sorted(["étude", "fable", "eagle"], key=text_sort_key) == ["eagle", "étude", "fable"]
