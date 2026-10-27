"""The task list's columns, sorting and saved presets, shared by the computer and the phone.

No user interface here, so the phone app (Kivy) and the desktop program
(Tkinter) keep filters and sort orders in the same form in their
settings.json: a preset saved on one works the same way on the other.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import settings

TASK_COLUMNS = (
    "Stage", "Due date", "Priority", "Urgency", "Assignee", "Location", "Tags", "Progress",
    "Repeat",
)
# Fields the task list can be sorted by: the columns plus the creation time.
SORT_FIELDS = ("Task", *TASK_COLUMNS, "Created at")
# Fields that start out descending when added to the sort (most important first).
DESCENDING_FIRST = {"Priority", "Urgency"}


@dataclass(frozen=True)
class FilterPreset:
    """Saved filters: the search text and the chosen key of each column filter.

    Keys do not depend on the language or on names that can be changed:
    "not-done", "overdue", "Important", "id:3" (a user, tag or repeat rule).
    """

    name: str
    text: str = ""
    filters: dict[str, str] = field(default_factory=dict)  # column -> filter key

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "text": self.text, "filters": self.filters}


def load_presets() -> list[FilterPreset]:
    """The saved filter presets from settings.json; broken entries are skipped."""
    saved = settings.load_setting("filter_presets")
    presets: list[FilterPreset] = []
    for item in saved if isinstance(saved, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        filters = item.get("filters")
        presets.append(FilterPreset(
            item["name"],
            item["text"] if isinstance(item.get("text"), str) else "",
            {
                column: key for column, key in filters.items()
                if column in TASK_COLUMNS and isinstance(key, str)
            } if isinstance(filters, dict) else {},
        ))
    return presets


def save_presets(presets: list[FilterPreset]) -> None:
    settings.save_setting("filter_presets", [preset.as_json() for preset in presets])


@dataclass(frozen=True)
class SortPreset:
    """A saved sort order: (field, descending) pairs, most important first."""

    name: str
    sort: tuple[tuple[str, bool], ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "sort": [[field, descending] for field, descending in self.sort]}


def load_sort_presets() -> list[SortPreset]:
    """The saved sort presets from settings.json; broken entries are skipped."""
    saved = settings.load_setting("sort_presets")
    return [
        SortPreset(item["name"], tuple(parse_sort(item.get("sort"))))
        for item in (saved if isinstance(saved, list) else [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


def save_sort_presets(presets: list[SortPreset]) -> None:
    settings.save_setting("sort_presets", [preset.as_json() for preset in presets])


def load_sort() -> list[tuple[str, bool]]:
    """The saved sort order as (field, descending) pairs; [] if none or invalid."""
    return parse_sort(settings.load_setting("sort"))


def save_sort(sort: list[tuple[str, bool]] | tuple[tuple[str, bool], ...]) -> None:
    settings.save_setting("sort", [[field, descending] for field, descending in sort])


def parse_sort(saved: Any) -> list[tuple[str, bool]]:
    """[[field, descending], ...] from settings.json, without unknown or repeated fields."""
    if not isinstance(saved, list):
        return []
    sort: list[tuple[str, bool]] = []
    for item in saved:
        if (
            isinstance(item, list) and len(item) == 2 and item[0] in SORT_FIELDS
            and item[0] not in [field for field, _ in sort]
        ):
            sort.append((item[0], bool(item[1])))
    return sort


def name_taken(name: str, others: set[str]) -> bool:
    """Whether a preset name is already used by another preset (case is ignored)."""
    return name.casefold() in {other.casefold() for other in others}


def sorted_by(items: list[Any], sort: list[tuple[str, bool]] | tuple[tuple[str, bool], ...],
              value: Any) -> list[Any]:
    """Items in the sort order (value(field, item) is what is compared; None sorts last).

    Ties keep the order they had (the manual one): sorts once per field, least
    important first, and Python's sort is stable.
    """
    for field_name, descending in reversed(sort):

        def key(item: Any, field_name: str = field_name, descending: bool = descending) -> Any:
            found = value(field_name, item)
            missing = found is None
            # The first item puts entries without a value last in both directions.
            return (not missing if descending else missing), (0 if missing else found)

        items = sorted(items, key=key, reverse=descending)
    return items


# Polish letters with diacritics come right after their base letter (c < ć < d).
_POLISH_LETTERS = str.maketrans(
    {"ą": "a~", "ć": "c~", "ę": "e~", "ł": "l~", "ń": "n~", "ó": "o~", "ś": "s~", "ź": "z~", "ż": "z~~"}
)


def text_sort_key(text: str) -> str:
    """Case-insensitive key that orders text alphabetically, Polish letters included."""
    text = text.casefold().translate(_POLISH_LETTERS)
    # Other accented letters (é, ü, ...) sort as their base letter.
    return "".join(
        char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char)
    )
