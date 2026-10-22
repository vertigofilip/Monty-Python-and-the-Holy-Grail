"""History compression into one summary row per task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from todo_db.compression import compress_old_history, compress_task_history, parse_summary
from todo_db.models import ChangeType, Priority, TaskChange
from todo_db.services import TaskService

from .conftest import World

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(START)


@pytest.fixture
def timed(session: Session, clock: Clock) -> TaskService:
    return TaskService(session, clock=clock)


def busy_task(timed: TaskService, clock: Clock, world: World) -> int:
    """A task with a history spread over five days (day 0 to day 4)."""
    task = timed.create_task("Draft", world.idea, world.anna)
    clock.now = START + timedelta(days=1)
    timed.update_task(task.id, world.piotr, name="Report", stage_id=world.planned)
    clock.now = START + timedelta(days=2)
    timed.update_task(task.id, world.anna, priority=Priority.Important, assignee_id=world.piotr)
    clock.now = START + timedelta(days=3)
    timed.update_task(task.id, world.anna, priority=Priority.Normal, stage_id=world.in_progress)
    clock.now = START + timedelta(days=4)
    timed.update_task(task.id, world.piotr, name="Final report")
    return task.id


def test_manual_compression_of_whole_history(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    task_id = busy_task(timed, clock, world)
    assert len(timed.get_history(task_id)) == 8

    removed = compress_task_history(session, task_id)
    session.commit()

    assert removed == 7
    (row,) = timed.get_history(task_id)
    assert row.change_type is ChangeType.Compressed
    assert row.changed_by_id is None
    assert row.changed_at == START + timedelta(days=4)
    assert parse_summary(row) == {
        "count": 8,
        "from": START.isoformat(),
        "to": (START + timedelta(days=4)).isoformat(),
        "types": {"Created": 1, "Updated": 5, "StageChanged": 2},
        "users": ["Anna Kowalska", "Piotr Nowak"],
        "fields": {
            "Name": ["Draft", "Final report"],
            "StageId": ["Idea", "In progress"],
            "AssigneeId": ["(none)", "Piotr Nowak"],
            # Priority went Normal -> Important -> Normal: no net change, left out.
        },
    }


def test_compression_keeps_newer_rows(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    task_id = busy_task(timed, clock, world)

    removed = compress_task_history(session, task_id, older_than=START + timedelta(days=2))
    session.commit()

    history = timed.get_history(task_id)
    assert removed == 2  # day 0 (1 row) + day 1 (2 rows) -> 1 summary
    assert [row.change_type for row in history] == [
        ChangeType.Compressed,
        ChangeType.Updated, ChangeType.Updated,
        ChangeType.Updated, ChangeType.StageChanged,
        ChangeType.Updated,
    ]
    assert parse_summary(history[0])["fields"] == {
        "Name": ["Draft", "Report"], "StageId": ["Idea", "Planned"],
    }


def test_compressing_again_merges_into_the_same_summary(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    task_id = busy_task(timed, clock, world)
    compress_task_history(session, task_id, older_than=START + timedelta(days=2))
    session.commit()

    compress_task_history(session, task_id, older_than=START + timedelta(days=4))
    session.commit()

    history = timed.get_history(task_id)
    assert [row.change_type for row in history] == [ChangeType.Compressed, ChangeType.Updated]
    summary = parse_summary(history[0])
    assert summary["count"] == 7
    assert summary["from"] == START.isoformat()
    assert summary["fields"]["Name"] == ["Draft", "Report"]
    assert summary["fields"]["StageId"] == ["Idea", "In progress"]


def test_nothing_to_merge(timed: TaskService, session: Session, world: World) -> None:
    task = timed.create_task("Single", world.todo, world.anna)

    assert compress_task_history(session, task.id) == 0
    assert timed.get_history(task.id)[0].change_type is ChangeType.Created


def test_automatic_compression_by_age(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    old_id = busy_task(timed, clock, world)  # days 0-4
    clock.now = START + timedelta(days=30)
    new = timed.create_task("Recent", world.todo, world.anna)
    timed.update_task(new.id, world.anna, name="Recent task")

    result = compress_old_history(session, older_than_days=10, now=START + timedelta(days=31))

    assert (result.tasks, result.rows_removed) == (1, 7)
    assert [r.change_type for r in timed.get_history(old_id)] == [ChangeType.Compressed]
    assert len(timed.get_history(new.id)) == 2  # newer than 10 days: untouched

    # Running it again changes nothing.
    again = compress_old_history(session, older_than_days=10, now=START + timedelta(days=31))
    assert (again.tasks, again.rows_removed) == (0, 0)


def test_deleted_task_history_is_compressed_too(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    task = timed.create_task("Temp", world.todo, world.anna)
    timed.update_task(task.id, world.anna, name="Temporary")
    timed.delete_task(task.id, world.anna)

    result = compress_old_history(session, older_than_days=1, now=START + timedelta(days=5))

    assert result.tasks == 1
    (row,) = timed.get_history(task.id)
    assert parse_summary(row)["types"] == {"Created": 1, "Updated": 1, "Deleted": 1}


def test_failed_run_saves_nothing(
    timed: TaskService, session: Session, clock: Clock, world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = busy_task(timed, clock, world)
    second = busy_task(timed, clock, world)
    calls = 0
    import todo_db.compression as compression

    original = compression.compress_task_history

    def fail_on_second(*args: object, **kwargs: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("disk full")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compression, "compress_task_history", fail_on_second)
    with pytest.raises(RuntimeError):
        compress_old_history(session, older_than_days=1, now=START + timedelta(days=30))

    assert len(timed.get_history(first)) == 8
    assert len(timed.get_history(second)) == 8
    assert session.scalars(
        select(TaskChange).where(TaskChange.change_type == ChangeType.Compressed)
    ).all() == []
