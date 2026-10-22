"""The audit log: what is written, what is not, and rollback."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from todo_db.models import ChangeType, Priority, Stage, Task, TaskChange, Urgency, User
from todo_db.services import TaskService

from .conftest import World


def count(session: Session, model: type) -> int:
    """Number of rows in a table."""
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_create_writes_created_row(service: TaskService, world: World) -> None:
    task = service.create_task("Write report", world.todo, world.anna)

    (change,) = service.get_history(task.id)
    assert change.change_type is ChangeType.Created
    assert change.changed_by_id == world.anna
    assert change.field_name is None
    assert change.new_value == "Write report"
    assert change.changed_at.utcoffset() == timedelta(0)


def test_one_row_per_changed_field(service: TaskService, world: World) -> None:
    task = service.create_task("Old name", world.idea, world.anna)

    service.update_task(
        task.id,
        world.piotr,
        name="New name",
        description="Details",
        priority=Priority.Important,
        stage_id=world.planned,
        tag_ids=[world.work, world.home],
    )

    changes = service.get_history(task.id)[1:]
    assert all(change.changed_by_id == world.piotr for change in changes)
    assert [
        (c.change_type, c.field_name, c.old_value, c.new_value) for c in changes
    ] == [
        (ChangeType.Updated, "Name", "Old name", "New name"),
        (ChangeType.Updated, "Description", None, "Details"),
        (ChangeType.Updated, "Priority", "Normal", "Important"),
        (ChangeType.StageChanged, "StageId", "Idea", "Planned"),
        (ChangeType.Updated, "Tags", "(none)", "home, work"),
    ]


def test_no_row_when_nothing_changed(service: TaskService, world: World) -> None:
    task = service.create_task(
        "Same", world.todo, world.anna, assignee_id=world.anna, tag_ids=[world.work]
    )

    service.update_task(
        task.id,
        world.piotr,
        name="Same",
        description=None,
        priority=Priority.Normal,
        stage_id=world.todo,
        assignee_id=world.anna,
        tag_ids=[world.work],
        parent_id=None,
        order=1,
    )

    assert len(service.get_history(task.id)) == 1


def test_only_changed_fields_are_logged(service: TaskService, world: World) -> None:
    task = service.create_task("Name", world.todo, world.anna)

    service.update_task(task.id, world.anna, name="Name", description="New")

    assert [c.field_name for c in service.get_history(task.id)[1:]] == ["Description"]


def test_names_stored_for_stage_and_assignee(
    service: TaskService, session: Session, world: World
) -> None:
    task = service.create_task("Feature", world.idea, world.anna)

    service.update_task(task.id, world.anna, stage_id=world.planned, assignee_id=world.piotr)
    service.update_task(task.id, world.anna, assignee_id=None)

    # Renaming afterwards must not change what the history says.
    session.get(Stage, world.planned).name = "Scheduled"
    session.get(User, world.piotr).name = "P. Nowak"
    session.commit()

    stage, assigned, unassigned = service.get_history(task.id)[1:]
    assert (stage.field_name, stage.old_value, stage.new_value) == (
        "StageId", "Idea", "Planned",
    )
    assert (assigned.field_name, assigned.old_value, assigned.new_value) == (
        "AssigneeId", "(none)", "Piotr Nowak",
    )
    assert (unassigned.old_value, unassigned.new_value) == ("Piotr Nowak", "(none)")


def test_completed_row_on_final_stage(service: TaskService, world: World) -> None:
    task = service.create_task("Feature", world.idea, world.anna)

    service.update_task(task.id, world.piotr, stage_id=world.planned)
    service.update_task(task.id, world.piotr, stage_id=world.soft_done)

    assert [c.change_type for c in service.get_history(task.id)] == [
        ChangeType.Created,
        ChangeType.StageChanged,
        ChangeType.StageChanged,
        ChangeType.Completed,
    ]


def test_automatic_and_unknown_fields_are_rejected(
    service: TaskService, world: World
) -> None:
    task = service.create_task("Name", world.todo, world.anna)

    for field in ("id", "created_at", "created_by_id", "repeat_done", "nonsense"):
        with pytest.raises(ValueError, match="Cannot update"):
            service.update_task(task.id, world.anna, **{field: 1})

    assert len(service.get_history(task.id)) == 1


def test_update_rolls_back_when_a_later_field_fails(
    service: TaskService, session: Session, world: World
) -> None:
    task = service.create_task("Original", world.todo, world.anna)

    with pytest.raises(ValueError, match="does not exist"):
        service.update_task(
            task.id, world.anna, name="Changed", description="Changed", stage_id=9999
        )

    session.expire_all()
    assert task.name == "Original"
    assert task.description is None
    assert len(service.get_history(task.id)) == 1


def test_update_rolls_back_when_log_write_fails(
    service: TaskService, session: Session, world: World
) -> None:
    """The task change itself is valid, but its log row breaks a foreign key."""
    task = service.create_task("Original", world.todo, world.anna)

    with pytest.raises(IntegrityError):
        service.update_task(task.id, 9999, name="Changed")

    assert task.name == "Original"
    assert len(service.get_history(task.id)) == 1


def test_create_rolls_back_on_database_error(
    service: TaskService, session: Session, world: World
) -> None:
    with pytest.raises(IntegrityError):
        service.create_task("Orphan", world.todo, created_by_id=9999)

    assert count(session, Task) == 0
    assert count(session, TaskChange) == 0


def test_history_is_ordered_by_time(service: TaskService, world: World) -> None:
    task = service.create_task("Name", world.todo, world.anna)
    for name in ("B", "C", "D"):
        service.update_task(task.id, world.anna, name=name)

    history = service.get_history(task.id)
    times = [change.changed_at for change in history]
    assert times == sorted(times)
    assert [change.new_value for change in history] == ["Name", "B", "C", "D"]


def test_urgency_defaults_and_is_logged(service: TaskService, world: World) -> None:
    task = service.create_task("Pay bills", world.todo, world.anna)
    assert task.urgency is Urgency.Medium

    service.update_task(task.id, world.anna, urgency=Urgency.High)
    service.update_task(task.id, world.anna, urgency=2)  # same value: no row

    changes = service.get_history(task.id)[1:]
    assert [(c.change_type, c.field_name, c.old_value, c.new_value) for c in changes] == [
        (ChangeType.Updated, "Urgency", "Medium", "High"),
    ]
