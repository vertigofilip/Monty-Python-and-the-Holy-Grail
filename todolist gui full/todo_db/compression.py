"""History compression: many old TaskChange rows of a task become one summary row.

The summary is lossy on purpose. It keeps, per field, the value before the
first change and after the last one, how many changes of each type there were,
who made them and the time span. Intermediate values are gone for good.

The summary row has ChangeType Compressed, ChangedById null (made by the
system), ChangedAt equal to the newest row it replaces (so it keeps its place
in the history), and the summary as JSON in NewValue. Compressing again merges
an existing summary with newer old rows, so it never builds up more than one
summary per task.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ChangeType, TaskChange, utcnow

SYSTEM = "system"


@dataclass
class CompressionResult:
    """What a compression run did."""

    tasks: int = 0  # tasks whose history was compressed
    rows_removed: int = 0  # old rows replaced by summaries (net, summaries subtracted)


def parse_summary(change: TaskChange) -> dict[str, Any] | None:
    """The summary stored in a Compressed row, or None for other rows."""
    if change.change_type is not ChangeType.Compressed or not change.new_value:
        return None
    return json.loads(change.new_value)


def _summarize(rows: list[TaskChange]) -> dict[str, Any]:
    """Merge rows (oldest first, possibly including an earlier summary) into one summary."""
    count = 0
    types: Counter[str] = Counter()
    users: list[str] = []
    fields: dict[str, list[str | None]] = {}  # field -> [value before, value after]
    start: str | None = None

    for row in rows:
        summary = parse_summary(row)
        if summary is not None:
            count += summary["count"]
            types.update(summary["types"])
            changes = summary["fields"].items()
            row_users = summary["users"]
            row_start = summary["from"]
        else:
            count += 1
            types[row.change_type.name] += 1
            changes = [(row.field_name, [row.old_value, row.new_value])] if row.field_name else []
            row_users = [row.changed_by.name if row.changed_by else SYSTEM]
            row_start = row.changed_at.isoformat()
        start = start or row_start
        for user in row_users:
            if user not in users:
                users.append(user)
        for field, (old, new) in changes:
            if field in fields:
                fields[field][1] = new
            else:
                fields[field] = [old, new]

    return {
        "count": count,
        "from": start,
        "to": rows[-1].changed_at.isoformat(),
        "types": dict(types),
        "users": users,
        # A field that ended where it started is left out; its changes are still counted.
        "fields": {field: values for field, values in fields.items() if values[0] != values[1]},
    }


def compress_task_history(
    session: Session, task_id: int, older_than: datetime | None = None
) -> int:
    """Merge the task's history rows (all, or only those before `older_than`) into one row.

    Works for deleted tasks too. Returns how many rows were removed (0 if there
    were fewer than two rows to merge). Does not commit.
    """
    query = select(TaskChange).where(TaskChange.task_id == task_id)
    if older_than is not None:
        query = query.where(TaskChange.changed_at < older_than)
    rows = list(session.scalars(query.order_by(TaskChange.changed_at, TaskChange.id)))
    if len(rows) < 2:
        return 0
    summary = _summarize(rows)
    for row in rows:
        session.delete(row)
    session.add(
        TaskChange(
            task_id=task_id,
            changed_at=rows[-1].changed_at,
            changed_by_id=None,
            change_type=ChangeType.Compressed,
            new_value=json.dumps(summary, ensure_ascii=False),
        )
    )
    session.flush()
    return len(rows) - 1


def compress_old_history(
    session: Session, older_than_days: int, now: datetime | None = None
) -> CompressionResult:
    """Compress, for every task, all history rows older than the given number of days.

    Only tasks with at least two such rows are touched. Commits; rolls back
    everything if anything fails.
    """
    if older_than_days < 0:
        raise ValueError("older_than_days cannot be negative")
    cutoff = (now or utcnow()) - timedelta(days=older_than_days)
    task_ids = session.scalars(
        select(TaskChange.task_id)
        .where(TaskChange.changed_at < cutoff)
        .group_by(TaskChange.task_id)
        .having(func.count() >= 2)
    ).all()
    result = CompressionResult()
    try:
        for task_id in task_ids:
            removed = compress_task_history(session, task_id, older_than=cutoff)
            if removed:
                result.tasks += 1
                result.rows_removed += removed
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result
