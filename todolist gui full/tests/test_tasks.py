"""Creating, moving, deleting tasks and the progress percentage."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from todo_db.models import ChangeType, Priority, Task
from todo_db.services import TaskService

from .conftest import World


def orders(session: Session, parent_id: int | None) -> list[str]:
    """Names of the tasks under a parent, in Order; asserts Order is 1..n."""
    query = select(Task).order_by(Task.order)
    if parent_id is None:
        query = query.where(Task.parent_id.is_(None))
    else:
        query = query.where(Task.parent_id == parent_id)
    tasks = list(session.scalars(query))
    assert [task.order for task in tasks] == list(range(1, len(tasks) + 1))
    return [task.name for task in tasks]


def test_create_task(service: TaskService, world: World) -> None:
    task = service.create_task(
        "Write report", world.todo, world.anna, assignee_id=world.piotr,
        tag_ids=[world.work],
    )

    assert task.id is not None
    assert task.priority is Priority.Normal
    assert task.repeat_done == 0
    assert task.order == 1
    assert task.parent_id is None
    assert task.created_at.utcoffset() == timedelta(0)
    assert task.assignee is not None and task.assignee.name == "Piotr Nowak"
    assert [tag.name for tag in task.tags] == ["work"]


def test_subtasks_are_ordered_children(service: TaskService, world: World) -> None:
    parent = service.create_task("Parent", world.todo, world.anna)
    service.create_task("A", world.todo, world.anna, parent_id=parent.id)
    service.create_task("B", world.todo, world.anna, parent_id=parent.id)

    assert [(sub.name, sub.order) for sub in parent.subtasks] == [("A", 1), ("B", 2)]


def test_move_reorders_siblings(
    service: TaskService, session: Session, world: World
) -> None:
    for name in "ABCD":
        service.create_task(name, world.todo, world.anna)
    d = session.scalars(select(Task).where(Task.name == "D")).one()

    service.move_task(d.id, None, 2, world.anna)

    assert orders(session, None) == ["A", "D", "B", "C"]
    (created, moved) = service.get_history(d.id)
    assert moved.change_type is ChangeType.Moved
    assert (moved.field_name, moved.old_value, moved.new_value) == ("Order", "4", "2")


def test_move_to_other_parent(
    service: TaskService, session: Session, world: World
) -> None:
    parent = service.create_task("Parent", world.todo, world.anna)
    a = service.create_task("A", world.todo, world.anna)
    service.create_task("B", world.todo, world.anna)
    service.create_task("X", world.todo, world.anna, parent_id=parent.id)

    service.move_task(a.id, parent.id, 1, world.anna)

    assert orders(session, None) == ["Parent", "B"]
    assert orders(session, parent.id) == ["A", "X"]
    moves = [
        (c.field_name, c.old_value, c.new_value)
        for c in service.get_history(a.id)
        if c.change_type is ChangeType.Moved
    ]
    assert moves == [("ParentId", "(none)", "Parent"), ("Order", "2", "1")]


def test_move_to_same_place_logs_nothing(service: TaskService, world: World) -> None:
    task = service.create_task("A", world.todo, world.anna)

    service.move_task(task.id, None, 1, world.anna)

    assert len(service.get_history(task.id)) == 1


def test_move_rejects_cycle(service: TaskService, world: World) -> None:
    grandparent = service.create_task("Grandparent", world.todo, world.anna)
    parent = service.create_task("Parent", world.todo, world.anna, parent_id=grandparent.id)
    child = service.create_task("Child", world.todo, world.anna, parent_id=parent.id)

    with pytest.raises(ValueError, match="ancestor"):
        service.move_task(grandparent.id, child.id, None, world.anna)
    with pytest.raises(ValueError, match="ancestor"):
        service.move_task(parent.id, parent.id, None, world.anna)
    with pytest.raises(ValueError, match="ancestor"):
        service.update_task(grandparent.id, world.anna, parent_id=child.id)

    assert grandparent.parent_id is None
    assert len(service.get_history(grandparent.id)) == 1


def test_delete_with_subtasks_is_refused(
    service: TaskService, session: Session, world: World
) -> None:
    parent = service.create_task("Parent", world.todo, world.anna)
    service.create_task("Child", world.todo, world.anna, parent_id=parent.id)

    with pytest.raises(ValueError, match="subtasks"):
        service.delete_task(parent.id, world.anna)

    assert session.get(Task, parent.id) is not None
    assert [c.change_type for c in service.get_history(parent.id)] == [ChangeType.Created]


def test_delete_keeps_history_and_closes_gap(
    service: TaskService, session: Session, world: World
) -> None:
    a = service.create_task("A", world.todo, world.anna, tag_ids=[world.work])
    service.create_task("B", world.todo, world.anna)
    a_id = a.id

    service.delete_task(a_id, world.piotr)

    assert session.get(Task, a_id) is None
    assert orders(session, None) == ["B"]
    history = service.get_history(a_id)
    assert [c.change_type for c in history] == [ChangeType.Created, ChangeType.Deleted]
    assert history[-1].old_value == "A"
    assert history[-1].changed_by_id == world.piotr


def test_progress_from_stage_position(service: TaskService, world: World) -> None:
    task = service.create_task("Feature", world.idea, world.anna)
    assert service.get_progress_percent(task.id) == 25

    service.update_task(task.id, world.anna, stage_id=world.in_progress)
    assert service.get_progress_percent(task.id) == 75

    service.update_task(task.id, world.anna, stage_id=world.soft_done)
    assert service.get_progress_percent(task.id) == 100


def test_progress_from_subtasks(service: TaskService, world: World) -> None:
    parent = service.create_task("Parent", world.idea, world.anna)
    subs = [
        service.create_task(name, world.todo, world.anna, parent_id=parent.id)
        for name in "ABCD"
    ]
    assert service.get_progress_percent(parent.id) == 0

    service.update_task(subs[0].id, world.anna, stage_id=world.done)
    assert service.get_progress_percent(parent.id) == 25

    for sub in subs[1:]:
        service.update_task(sub.id, world.anna, stage_id=world.done)
    assert service.get_progress_percent(parent.id) == 100


def test_location_is_kept_and_logged(service: TaskService, world: World) -> None:
    task = service.create_task("Trening kalisteniki", world.todo, world.anna, location="Siłownia")
    service.update_task(task.id, world.anna, location="Park")
    service.update_task(task.id, world.anna, location=None)
    rows = [(c.field_name, c.old_value, c.new_value) for c in service.get_history(task.id)[1:]]
    assert rows == [("Location", "Siłownia", "Park"), ("Location", "Park", None)]
