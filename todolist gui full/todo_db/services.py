"""TaskService: every write to a task goes through here, together with its history."""

from __future__ import annotations

import calendar
import enum
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Base,
    ChangeType,
    Priority,
    RepeatRule,
    RepeatUnit,
    Stage,
    Tag,
    Task,
    TaskChange,
    Urgency,
    User,
    utcnow,
)

NONE = "(none)"

# Fields accepted by update_task, mapped to the name written to FieldName.
# Automatic fields (Id, CreatedAt, CreatedById, RepeatDone) are not listed.
UPDATABLE: dict[str, str] = {
    "name": "Name",
    "description": "Description",
    "priority": "Priority",
    "urgency": "Urgency",
    "due_date": "DueDate",
    "location": "Location",
    "stage_id": "StageId",
    "assignee_id": "AssigneeId",
    "repeat_rule_id": "RepeatRuleId",
    "repeat_count": "RepeatCount",
    "tag_ids": "Tags",
    "parent_id": "ParentId",
    "order": "Order",
}

# Fields that completing a task depends on; set before the stage when sent together.
BEFORE_STAGE = {"due_date", "repeat_rule_id", "repeat_count"}

# Foreign-key fields whose history shows the referenced row's name.
NAMED: dict[str, type[Base]] = {
    "stage_id": Stage,
    "assignee_id": User,
    "repeat_rule_id": RepeatRule,
    "parent_id": Task,
}

# Fields holding an IntEnum; plain ints are accepted and converted.
ENUMS: dict[str, type[enum.IntEnum]] = {"priority": Priority, "urgency": Urgency}

M = TypeVar("M", bound=Base)


def add_interval(day: date, interval: int, unit: RepeatUnit) -> date:
    """The date `interval` units after `day`; month ends are clamped (Jan 31 + 1 month = Feb 28/29)."""
    if unit is RepeatUnit.Day:
        return day + timedelta(days=interval)
    if unit is RepeatUnit.Week:
        return day + timedelta(weeks=interval)
    months = day.month - 1 + (interval if unit is RepeatUnit.Month else 12 * interval)
    year, month = day.year + months // 12, months % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def next_reset(completed_at: datetime, rule: RepeatRule) -> datetime:
    """Local midnight starting the day the task is due again, in UTC.

    A daily task completed at any time today comes back at midnight tonight,
    a weekly one at midnight a week from today, and so on. "Local" is the time
    zone of the computer running the program.
    """
    completed_day = completed_at.astimezone().date()
    due_day = add_interval(completed_day, rule.interval, rule.unit)
    return datetime.combine(due_day, time()).astimezone().astimezone(timezone.utc)


def next_due_date(due: date, rule: RepeatRule, today: date, completed: bool) -> date:
    """The next due date of a repeating task, in its cycle (due, due + interval, ...).

    completed: it was just done, so the next date after today (at least one
    interval on). Otherwise its date has passed undone: the first date of the
    cycle that is today or later. Dates are counted from `due` (k intervals at
    once), so month ends do not drift: Jan 31 -> Feb 28 -> Mar 31.
    """
    steps = 1 if completed else 0
    while True:
        candidate = add_interval(due, steps * rule.interval, rule.unit)
        if candidate > today or (candidate == today and not completed):
            return candidate
        steps += 1


class TaskService:
    """Creates, changes and deletes tasks, logging every change."""

    def __init__(self, session: Session, clock: Callable[[], datetime] = utcnow) -> None:
        """clock returns the current UTC time; tests pass a fake one."""
        self.session = session
        self.clock = clock

    # -- public API ---------------------------------------------------------

    def create_task(
        self,
        name: str,
        stage_id: int,
        created_by_id: int,
        *,
        description: str | None = None,
        priority: Priority = Priority.Normal,
        urgency: Urgency = Urgency.Medium,
        due_date: date | None = None,
        location: str | None = None,
        parent_id: int | None = None,
        assignee_id: int | None = None,
        repeat_rule_id: int | None = None,
        repeat_count: int = 0,
        tag_ids: Sequence[int] = (),
    ) -> Task:
        """Create a task at the end of its siblings and log a Created row."""
        with self._transaction():
            task = Task(
                name=name,
                description=description,
                stage_id=stage_id,
                priority=Priority(priority),
                urgency=Urgency(urgency),
                due_date=due_date,
                location=location,
                parent_id=parent_id,
                order=len(self._siblings(parent_id)) + 1,
                assignee_id=assignee_id,
                created_by_id=created_by_id,
                created_at=self.clock(),
                repeat_rule_id=repeat_rule_id,
                repeat_count=repeat_count,
                tags=[self._get(Tag, tag_id) for tag_id in tag_ids],
            )
            self.session.add(task)
            self.session.flush()
            self._log(task, created_by_id, ChangeType.Created, new=name)
        return task

    def update_task(self, task_id: int, changed_by_id: int | None, **fields: Any) -> Task:
        """Change the given fields and log one row per field that really changed."""
        unknown = set(fields) - set(UPDATABLE)
        if unknown:
            raise ValueError(f"Cannot update fields: {', '.join(sorted(unknown))}")
        with self._transaction():
            task = self._get(Task, task_id)
            # Completing a repeating task moves its due date on, so a new date
            # or rule sent together with the stage is saved first.
            for field, value in sorted(fields.items(), key=lambda item: item[0] not in BEFORE_STAGE):
                if field == "stage_id":
                    self._set_stage(task, value, changed_by_id)
                elif field == "tag_ids":
                    self._set_tags(task, value, changed_by_id)
                elif field not in ("parent_id", "order"):
                    self._set_field(task, field, value, changed_by_id)
            if "parent_id" in fields or "order" in fields:
                self._move(
                    task,
                    fields.get("parent_id", task.parent_id),
                    fields.get("order"),
                    changed_by_id,
                )
        return task

    def move_task(
        self,
        task_id: int,
        new_parent_id: int | None,
        new_order: int | None,
        changed_by_id: int | None,
    ) -> Task:
        """Move a task to a parent and position (1-based; None = at the end)."""
        with self._transaction():
            task = self._get(Task, task_id)
            self._move(task, new_parent_id, new_order, changed_by_id)
        return task

    def delete_task(self, task_id: int, changed_by_id: int | None) -> None:
        """Log a Deleted row and delete the task. Refused if it has subtasks."""
        with self._transaction():
            task = self._get(Task, task_id)
            if self._siblings(task.id):
                raise ValueError(f"Task {task_id} has subtasks and cannot be deleted")
            self._log(task, changed_by_id, ChangeType.Deleted, old=task.name)
            parent_id = task.parent_id
            self.session.delete(task)
            self.session.flush()
            self._renumber(self._siblings(parent_id))

    def reset_due_tasks(self, now: datetime | None = None) -> int:
        """Send repeating tasks whose reset time has come back to their first stage.

        Run at program start and at midnight. Returns how many tasks were reset.
        A task reopened by hand or whose repeat rule was removed is skipped.
        """
        now = now or self.clock()
        reset = 0
        with self._transaction():
            query = select(Task).where(Task.next_reset_at.is_not(None), Task.next_reset_at <= now)
            for task in self.session.scalars(query).all():
                task.next_reset_at = None
                if task.repeat_rule_id is None or not task.stage.is_final:
                    continue
                first_stage = task.stage.workflow.stages[0]
                if first_stage.id == task.stage_id:
                    continue
                self._log(
                    task, None, ChangeType.StageChanged, "StageId",
                    task.stage.name, first_stage.name,
                )
                task.stage = first_stage
                reset += 1
        self.roll_missed_due_dates(now)
        return reset

    def roll_missed_due_dates(self, now: datetime | None = None) -> int:
        """Move repeating tasks whose due date passed undone to their next date in the cycle.

        Run with reset_due_tasks (program start and midnight; on the server at
        start and every midnight). Returns how many tasks got a new date.
        """
        today = (now or self.clock()).astimezone().date()
        moved = 0
        with self._transaction():
            query = select(Task).where(
                Task.repeat_rule_id.is_not(None), Task.due_date.is_not(None), Task.due_date < today
            )
            for task in self.session.scalars(query).all():
                finished = task.repeat_count and task.repeat_done >= task.repeat_count
                if task.stage.is_final or finished or task.repeat_rule is None:
                    continue
                assert task.due_date is not None
                self._move_due_date(task, next_due_date(task.due_date, task.repeat_rule, today, False))
                moved += 1
        return moved

    def get_history(self, task_id: int) -> list[TaskChange]:
        """Return the task's changes, oldest first."""
        query = (
            select(TaskChange)
            .where(TaskChange.task_id == task_id)
            .order_by(TaskChange.changed_at, TaskChange.id)
        )
        return list(self.session.scalars(query))

    def get_progress_percent(self, task_id: int) -> float:
        """Share of finished subtasks, or the stage position within the workflow."""
        task = self._get(Task, task_id)
        if task.subtasks:
            done = sum(1 for subtask in task.subtasks if subtask.stage.is_final)
            return 100 * done / len(task.subtasks)
        stages = task.stage.workflow.stages
        return 100 * (stages.index(task.stage) + 1) / len(stages)

    # -- helpers ------------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Commit on success, roll everything back on any error."""
        try:
            yield
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _get(self, model: type[M], row_id: int) -> M:
        """Load a row by id or raise ValueError."""
        row = self.session.get(model, row_id)
        if row is None:
            raise ValueError(f"{model.__name__} {row_id} does not exist")
        return row

    def _text(self, field: str, value: Any) -> str | None:
        """Turn a field value into the text stored in the history."""
        if field in NAMED:
            return NONE if value is None else self._get(NAMED[field], value).name
        if value is None:
            return None
        if isinstance(value, enum.Enum):
            return value.name
        return str(value)

    def _log(
        self,
        task: Task,
        changed_by_id: int | None,
        change_type: ChangeType,
        field: str | None = None,
        old: str | None = None,
        new: str | None = None,
    ) -> None:
        """Add a history row (changed_by_id None = automatic system change)."""
        self.session.add(
            TaskChange(
                task_id=task.id,
                changed_at=self.clock(),
                changed_by_id=changed_by_id,
                change_type=change_type,
                field_name=field,
                old_value=old,
                new_value=new,
            )
        )

    def _set_field(
        self, task: Task, field: str, value: Any, changed_by_id: int | None
    ) -> None:
        """Set a plain field and log it as Updated if it changed."""
        if field in ENUMS:
            value = ENUMS[field](value)
        old = getattr(task, field)
        if old == value:
            return
        old_text, new_text = self._text(field, old), self._text(field, value)
        setattr(task, field, value)
        self._log(task, changed_by_id, ChangeType.Updated, UPDATABLE[field], old_text, new_text)

    def _set_tags(
        self, task: Task, tag_ids: Sequence[int], changed_by_id: int | None
    ) -> None:
        """Replace the task's tags and log the change as one Updated row."""
        tags = [self._get(Tag, tag_id) for tag_id in set(tag_ids)]
        old_text = ", ".join(sorted(tag.name for tag in task.tags)) or NONE
        new_text = ", ".join(sorted(tag.name for tag in tags)) or NONE
        if old_text == new_text:
            return
        task.tags = tags
        self._log(task, changed_by_id, ChangeType.Updated, "Tags", old_text, new_text)

    def _set_stage(self, task: Task, stage_id: int, changed_by_id: int | None) -> None:
        """Change the stage; handle completion and the repeat cycle."""
        if stage_id == task.stage_id:
            return
        old_stage, new_stage = task.stage, self._get(Stage, stage_id)
        task.stage = new_stage
        self._log(
            task, changed_by_id, ChangeType.StageChanged, "StageId",
            old_stage.name, new_stage.name,
        )
        if not new_stage.is_final:
            task.next_reset_at = None  # reopened by hand: no reset needed any more
            return
        self._log(task, changed_by_id, ChangeType.Completed)
        if task.repeat_rule_id is None:
            return

        # The rest is done by the system, so it is logged with no user.
        task.repeat_done += 1
        self._log(
            task, None, ChangeType.Updated, "RepeatDone",
            str(task.repeat_done - 1), str(task.repeat_done),
        )
        if task.repeat_count == 0 or task.repeat_done < task.repeat_count:
            # It stays done until the next interval starts; reset_due_tasks()
            # then sends it back to the first stage.
            rule = self._get(RepeatRule, task.repeat_rule_id)
            task.next_reset_at = next_reset(self.clock(), rule)
            if task.due_date is not None:
                today = self.clock().astimezone().date()
                self._move_due_date(task, next_due_date(task.due_date, rule, today, True))

    def _move_due_date(self, task: Task, due_date: date) -> None:
        """Give a repeating task its next due date; logged as a system change."""
        self._log(
            task, None, ChangeType.Updated, "DueDate",
            self._text("due_date", task.due_date), self._text("due_date", due_date),
        )
        task.due_date = due_date

    def _siblings(self, parent_id: int | None, exclude_id: int | None = None) -> list[Task]:
        """Tasks with the given parent, in order, optionally without one task."""
        query = select(Task).order_by(Task.order, Task.id)
        if parent_id is None:
            query = query.where(Task.parent_id.is_(None))
        else:
            query = query.where(Task.parent_id == parent_id)
        if exclude_id is not None:
            query = query.where(Task.id != exclude_id)
        return list(self.session.scalars(query))

    @staticmethod
    def _renumber(tasks: list[Task]) -> None:
        """Make Order contiguous: 1, 2, 3, ..."""
        for position, task in enumerate(tasks, start=1):
            task.order = position

    def _move(
        self,
        task: Task,
        new_parent_id: int | None,
        new_order: int | None,
        changed_by_id: int | None,
    ) -> None:
        """Re-parent and/or reorder a task, keeping sibling orders contiguous."""
        ancestor = None if new_parent_id is None else self._get(Task, new_parent_id)
        while ancestor is not None:
            if ancestor.id == task.id:
                raise ValueError("A task cannot be its own ancestor")
            ancestor = ancestor.parent

        old_parent_id, old_order = task.parent_id, task.order
        old_parent_text = self._text("parent_id", old_parent_id)
        new_parent_text = self._text("parent_id", new_parent_id)

        if new_parent_id != old_parent_id:
            self._renumber(self._siblings(old_parent_id, exclude_id=task.id))
        siblings = self._siblings(new_parent_id, exclude_id=task.id)
        last = len(siblings) + 1
        position = last if new_order is None else max(1, min(new_order, last))
        siblings.insert(position - 1, task)
        task.parent_id = new_parent_id
        self._renumber(siblings)

        if new_parent_id != old_parent_id:
            self._log(
                task, changed_by_id, ChangeType.Moved, "ParentId",
                old_parent_text, new_parent_text,
            )
        if task.order != old_order:
            self._log(
                task, changed_by_id, ChangeType.Moved, "Order",
                str(old_order), str(task.order),
            )
