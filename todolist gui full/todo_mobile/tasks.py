"""What the phone app shows, worked out from the server's data (no Kivy here)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from todo_db.i18n import tr, tr_n
from todo_db.presets import TASK_COLUMNS, filter_keys, sorted_by, text_sort_key

NONE = "(none)"  # how the server's history writes an empty value
PRIORITIES = ("Maybe", "Normal", "Important")
URGENCIES = ("Low", "Medium", "High")
UNITS = ("Day", "Week", "Month", "Year")

SHOW_OPEN, SHOW_ALL, SHOW_DONE = "(not done)", "All", "(done)"
SHOW_CHOICES = (SHOW_OPEN, SHOW_ALL, SHOW_DONE)
# The Stage filter's key for each of the choices above (None: all tasks).
SHOW_FILTER = {SHOW_OPEN: "not-done", SHOW_ALL: None, SHOW_DONE: "done"}


@dataclass(frozen=True)
class Row:
    """One line of the task list."""

    task: dict[str, Any]
    depth: int
    matches: bool  # False: shown only because a subtask matches


def repeat_label(rule: dict[str, Any]) -> str:
    """A repeat rule as shown to the user, in the current language."""
    unit = rule["unit"]
    if rule["interval"] == 1:
        return tr({"Day": "Daily", "Week": "Weekly", "Month": "Monthly", "Year": "Yearly"}[unit])
    return tr_n(f"Every {{n}} {unit.lower()}s", rule["interval"])


def sorted_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Days first, then weeks, months, years; shorter intervals first."""
    return sorted(rules, key=lambda r: (UNITS.index(r["unit"]) if r["unit"] in UNITS else 9,
                                        r["interval"]))


def task_rows(
    tasks: list[dict[str, Any]], text: str = "", show: str = SHOW_OPEN,
    filters: dict[str, str] | None = None, sort: Any = (),
    data: dict[str, Any] | None = None, today: date | None = None,
) -> list[Row]:
    """The task tree flattened into rows, filtered and sorted.

    filters: column -> filter key, or a list of keys (any of them passes), as in
    the desktop program's column filters
    (a "Stage" filter replaces `show`); sort: (field, descending) pairs, applied
    to the subtasks of each task (data gives the stage order and repeat rules).
    A task is shown when it matches the filters, or when one of its subtasks
    does (then as context, so the subtask keeps its place in the tree).
    """
    children: dict[int | None, list[dict[str, Any]]] = {}
    for task in tasks:
        children.setdefault(task["parent_id"], []).append(task)
    for parent_id, group in children.items():
        group.sort(key=lambda t: (t["order"], t["id"]))
        if sort:
            children[parent_id] = sorted_by(group, sort, sort_value(data or {}))
    needle = text.strip().casefold()
    tests = dict(filters or {})
    if "Stage" not in tests and SHOW_FILTER.get(show):
        tests["Stage"] = SHOW_FILTER[show]  # type: ignore[assignment]
    today = today or date.today()

    def matches(task: dict[str, Any]) -> bool:
        if not all(
            any(filter_matches(column, key, task, today) for key in keys)
            for column, saved in tests.items() if (keys := filter_keys(saved))
        ):
            return False
        if not needle:
            return True
        haystack = " ".join(
            [task["name"], task["description"] or "", task["stage"], task["assignee"] or "",
             task.get("location") or "", *(tag["name"] for tag in task["tags"])]
        )
        return needle in haystack.casefold()

    def walk(parent_id: int | None, depth: int) -> list[Row]:
        rows: list[Row] = []
        for task in children.get(parent_id, []):
            below = walk(task["id"], depth + 1)
            if matches(task) or below:
                rows.append(Row(task, depth, matches(task)))
                rows.extend(below)
        return rows

    return walk(None, 0)


# -- column filters and sorting, as in the desktop program -----------------------------


def filter_options(column: str, data: dict[str, Any], today: date | None = None
                   ) -> list[tuple[str, str | None]]:
    """The choices of one column's filter as (label, key); the first is All (None).

    The keys are those of the desktop program, so saved presets mean the same.
    """
    options: list[tuple[str, str | None]] = [(tr("All"), None)]
    tasks = data.get("tasks", [])
    if column == "Stage":
        options += [(tr("(not done)"), "not-done"), (tr("(done)"), "done")]
        names = {stage["name"] for workflow in data.get("workflows", [])
                 for stage in workflow["stages"]}
        options += [(name, f"name:{name}") for name in sorted(names)]
    elif column == "Due date":
        options += [(tr(NONE), "none"), (tr("(overdue)"), "overdue"), (tr("(today)"), "today"),
                    (tr("(later)"), "later")]
    elif column == "Priority":
        options += [(tr(level), level) for level in PRIORITIES]
    elif column == "Urgency":
        options += [(tr(level), level) for level in URGENCIES]
    elif column == "Assignee":
        options.append((tr(NONE), "none"))
        options += [(user["name"], f"id:{user['id']}")
                    for user in sorted(data.get("users", []), key=lambda u: u["name"])]
    elif column == "Location":
        options.append((tr(NONE), "none"))
        places = {task["location"] for task in tasks if task.get("location")}
        options += [(place, f"name:{place}") for place in sorted(places, key=text_sort_key)]
    elif column == "Tags":
        options += [(tag["name"], f"id:{tag['id']}")
                    for tag in sorted(data.get("tags", []), key=lambda t: t["name"])]
    elif column == "Progress":
        options += [("0%", "0"), ("1–99%", "1-99"), ("100%", "100")]
    elif column == "Repeat":
        options += [(tr(NONE), "none"), (tr("(any)"), "any")]
        options += [(repeat_label(rule), f"id:{rule['id']}")
                    for rule in sorted_rules(data.get("repeat_rules", []))]
    return options


def _id(key: str) -> int | None:
    return int(key[3:]) if key.startswith("id:") and key[3:].isdigit() else None


def filter_matches(column: str, key: str | None, task: dict[str, Any], today: date) -> bool:
    """Whether the task passes one column's filter (a key from filter_options)."""
    if key is None:
        return True
    due = date.fromisoformat(task["due_date"]) if task.get("due_date") else None
    progress = task.get("progress_percent") or 0
    name = key[5:] if key.startswith("name:") else None
    tests = {
        "Stage": lambda: (not task["done"] if key == "not-done" else task["done"]
                          if key == "done" else task["stage"] == name),
        "Due date": lambda: {"none": due is None,
                             "overdue": due is not None and due < today,
                             "today": due == today,
                             "later": due is not None and due > today}.get(key, False),
        "Priority": lambda: task["priority"] == key,
        "Urgency": lambda: task["urgency"] == key,
        "Assignee": lambda: (task["assignee_id"] is None if key == "none"
                             else task["assignee_id"] == _id(key)),
        "Location": lambda: (not task.get("location") if key == "none"
                             else task.get("location") == name),
        "Tags": lambda: any(tag["id"] == _id(key) for tag in task["tags"]),
        "Progress": lambda: {"0": progress == 0, "1-99": 0 < progress < 100,
                             "100": progress >= 100}.get(key, False),
        "Repeat": lambda: (task["repeat_rule_id"] is None if key == "none"
                           else task["repeat_rule_id"] is not None if key == "any"
                           else task["repeat_rule_id"] == _id(key)),
    }
    return tests[column]() if column in tests else True


def sort_value(data: dict[str, Any]) -> Any:
    """value(field, task): what the task list is sorted by, as in the desktop program."""
    stage_order = {stage["id"]: stage["order"] for workflow in data.get("workflows", [])
                   for stage in workflow["stages"]}
    rules = {rule["id"]: rule for rule in data.get("repeat_rules", [])}

    def value(field_name: str, task: dict[str, Any]) -> Any:
        if field_name == "Task":
            return text_sort_key(task["name"])
        if field_name == "Stage":
            return stage_order.get(task["stage_id"], 0), text_sort_key(task["stage"])
        if field_name == "Due date":
            return task.get("due_date")
        if field_name == "Priority":
            return PRIORITIES.index(task["priority"])
        if field_name == "Urgency":
            return URGENCIES.index(task["urgency"])
        if field_name == "Assignee":
            return text_sort_key(task["assignee"]) if task["assignee"] else None
        if field_name == "Location":
            return text_sort_key(task["location"]) if task.get("location") else None
        if field_name == "Tags":
            return ", ".join(sorted(text_sort_key(tag["name"]) for tag in task["tags"])) or None
        if field_name == "Progress":
            return task.get("progress_percent") or 0
        if field_name == "Repeat":
            rule = rules.get(task["repeat_rule_id"])
            return (UNITS.index(rule["unit"]), rule["interval"]) if rule else None
        return task.get("created_at")

    return value


def missing_filters(filters: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Columns with a saved choice that no longer exists (e.g. a deleted tag), translated."""
    return [
        tr(column) for column, saved in filters.items()
        if column in TASK_COLUMNS
        and not set(filter_keys(saved)) <= {k for _l, k in filter_options(column, data)}
    ]


def parse_due(text: str) -> date | None:
    """A due date typed as YYYY-MM-DD (None if empty); ValueError if it is not one."""
    text = text.strip()
    return date.fromisoformat(text) if text else None


def is_overdue(task: dict[str, Any], today: date) -> bool:
    """An unfinished task whose due date has passed."""
    due = task.get("due_date")
    return bool(due) and not task["done"] and date.fromisoformat(due) < today


def is_due_today(task: dict[str, Any], today: date) -> bool:
    """An unfinished task that is due today."""
    due = task.get("due_date")
    return bool(due) and not task["done"] and date.fromisoformat(due) == today


# Colours of the priority and urgency levels on the phone's dark background, as on
# the computer: low (Maybe, Low) green, middle (Normal, Medium) yellow, high red.
LEVEL_COLOURS = {
    "Maybe": "6fdc7a", "Normal": "ffd54f", "Important": "ff6b5e",
    "Low": "6fdc7a", "Medium": "ffd54f", "High": "ff6b5e",
}


def _markup_text(text: str) -> str:
    """Text shown as itself in a Kivy label with markup on."""
    return text.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def task_details(task: dict[str, Any], today: date | None = None,
                 rules: list[dict[str, Any]] | None = None, markup: bool = False) -> str:
    """The small second line under a task's name (rules: the repeat rules, to name them).

    markup: for a Kivy label with markup on; the priority and urgency are coloured
    (unless the task is done) and the rest is escaped.
    """
    coloured: dict[int, str] = {}  # index in parts -> colour
    parts = [task["stage"]]
    if task.get("due_date"):
        due = f"{tr('Due date')}: {task['due_date']}"
        if is_overdue(task, today or date.today()):
            due += f" {tr('(overdue)')}"
        elif is_due_today(task, today or date.today()):
            due += f" {tr('(today)')}"
        parts.append(due)
    coloured[len(parts)] = LEVEL_COLOURS.get(task["priority"], "")
    parts.append(f"{tr('Priority')}: {tr(task['priority'])}")
    coloured[len(parts)] = LEVEL_COLOURS.get(task["urgency"], "")
    parts.append(f"{tr('Urgency')}: {tr(task['urgency'])}")
    if task["assignee"]:
        parts.append(task["assignee"])
    if task.get("location"):
        parts.append(task["location"])
    if task["tags"]:
        parts.append(", ".join(f"#{tag['name']}" for tag in task["tags"]))
    if task["progress_percent"] and not task["done"]:
        parts.append(f"{task['progress_percent']:.0f}%")
    if task["repeat_rule_id"] is not None:
        rule = next((r for r in rules or [] if r["id"] == task["repeat_rule_id"]), None)
        repeat = f"{repeat_label(rule)} " if rule else ""
        repeat += f"({task['repeat_done']}/{task['repeat_count'] or '∞'})"
        if task.get("next_reset_at"):
            reset = datetime.fromisoformat(task["next_reset_at"]).astimezone()
            repeat += f" ⟳ {reset:%Y-%m-%d}"
        parts.append(repeat)
    if not markup:
        return " · ".join(parts)
    return " · ".join(
        f"[color={coloured[index]}]{_markup_text(part)}[/color]"
        if coloured.get(index) and not task["done"] else _markup_text(part)
        for index, part in enumerate(parts)
    )


def next_stage_id(task: dict[str, Any], workflows: list[dict[str, Any]]) -> int | None:
    """The stage after the task's current one, or None at the last stage."""
    for workflow in workflows:
        if workflow["id"] == task["workflow_id"]:
            stages = sorted(workflow["stages"], key=lambda s: s["order"])
            ids = [stage["id"] for stage in stages]
            position = ids.index(task["stage_id"])
            return ids[position + 1] if position + 1 < len(ids) else None
    return None


def final_stage_id(task: dict[str, Any], workflows: list[dict[str, Any]]) -> int | None:
    """The first final ("done") stage of the task's workflow."""
    for workflow in workflows:
        if workflow["id"] == task["workflow_id"]:
            finals = sorted((s for s in workflow["stages"] if s["is_final"]), key=lambda s: s["order"])
            return finals[0]["id"] if finals else None
    return None


def _value(field_name: str | None, value: str | None) -> str:
    """A stored history value, with "(none)" and priority/urgency names translated."""
    if value is None:
        return ""
    return tr(value) if value == NONE or field_name in ("Priority", "Urgency") else value


def history_lines(changes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The task's history as (heading, text) pairs, newest first."""
    lines = []
    for change in sorted(changes, key=lambda c: (c["changed_at"], c["id"]), reverse=True):
        when = datetime.fromisoformat(change["changed_at"]).astimezone()
        who = change["changed_by"] or tr("system")
        heading = f"{when:%Y-%m-%d %H:%M} · {who} · {tr(change['change_type'])}"
        summary = change.get("summary")
        if summary:
            start = datetime.fromisoformat(summary["from"]).astimezone()
            end = datetime.fromisoformat(summary["to"]).astimezone()
            text = tr("{count} changes, {start} – {end}").format(
                count=summary["count"], start=f"{start:%Y-%m-%d}", end=f"{end:%Y-%m-%d}"
            )
            fields = [
                f"{tr(field)}: {_value(field, old)} → {_value(field, new)}"
                for field, (old, new) in summary["fields"].items()
            ]
            text = "\n".join([text, *fields])
        elif change["field_name"]:
            field = change["field_name"]
            text = (f"{tr(field)}: {_value(field, change['old_value'])}"
                    f" → {_value(field, change['new_value'])}")
        else:
            text = _value(None, change["new_value"])
        lines.append((heading, text))
    return lines
