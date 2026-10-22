"""What the phone app shows, worked out from the server's data (no Kivy here)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from todo_db.i18n import tr, tr_n

NONE = "(none)"  # how the server's history writes an empty value
PRIORITIES = ("Maybe", "Normal", "Important")
URGENCIES = ("Low", "Medium", "High")
UNITS = ("Day", "Week", "Month", "Year")

SHOW_OPEN, SHOW_ALL, SHOW_DONE = "(not done)", "All", "(done)"
SHOW_CHOICES = (SHOW_OPEN, SHOW_ALL, SHOW_DONE)


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


def task_rows(tasks: list[dict[str, Any]], text: str = "", show: str = SHOW_OPEN) -> list[Row]:
    """The task tree flattened into rows, filtered.

    A task is shown when it matches the filters, or when one of its subtasks
    does (then as context, so the subtask keeps its place in the tree).
    """
    children: dict[int | None, list[dict[str, Any]]] = {}
    for task in tasks:
        children.setdefault(task["parent_id"], []).append(task)
    for group in children.values():
        group.sort(key=lambda t: (t["order"], t["id"]))
    needle = text.strip().casefold()

    def matches(task: dict[str, Any]) -> bool:
        if show == SHOW_OPEN and task["done"] or show == SHOW_DONE and not task["done"]:
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


def parse_due(text: str) -> date | None:
    """A due date typed as YYYY-MM-DD (None if empty); ValueError if it is not one."""
    text = text.strip()
    return date.fromisoformat(text) if text else None


def is_overdue(task: dict[str, Any], today: date) -> bool:
    """An unfinished task whose due date has passed."""
    due = task.get("due_date")
    return bool(due) and not task["done"] and date.fromisoformat(due) < today


def task_details(task: dict[str, Any], today: date | None = None) -> str:
    """The small second line under a task's name."""
    parts = [task["stage"]]
    if task.get("due_date"):
        due = f"{tr('Due date')}: {task['due_date']}"
        if is_overdue(task, today or date.today()):
            due += f" {tr('(overdue)')}"
        parts.append(due)
    if task["priority"] != "Normal":
        parts.append(tr(task["priority"]))
    if task["urgency"] != "Medium":
        parts.append(f"{tr('Urgency')}: {tr(task['urgency'])}")
    if task["assignee"]:
        parts.append(task["assignee"])
    if task.get("location"):
        parts.append(task["location"])
    if task["tags"]:
        parts.append(", ".join(f"#{tag['name']}" for tag in task["tags"]))
    if task["progress_percent"] and not task["done"]:
        parts.append(f"{task['progress_percent']:.0f}%")
    if task["repeat_rule_id"] is not None and task["repeat_count"]:
        parts.append(f"{task['repeat_done']}/{task['repeat_count']}")
    return " · ".join(parts)


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
