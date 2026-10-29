"""SQLAlchemy models and enums for the to-do list database."""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class RepeatUnit(enum.Enum):
    """Unit of a repeat interval."""

    Day = "Day"
    Week = "Week"
    Month = "Month"
    Year = "Year"


class Priority(enum.IntEnum):
    """Task priority, stored as an integer so it sorts naturally."""

    Maybe = 0
    Normal = 1
    Important = 2


class Urgency(enum.IntEnum):
    """How soon a task needs doing (independent of how important it is)."""

    Low = 0
    Medium = 1
    High = 2


class ChangeType(enum.Enum):
    """Kind of entry in the task history."""

    Created = "Created"
    Updated = "Updated"
    StageChanged = "StageChanged"
    Completed = "Completed"
    Moved = "Moved"
    Deleted = "Deleted"
    # Several old rows merged into one summary (see todo_db/compression.py).
    Compressed = "Compressed"


class UserRole(enum.Enum):
    """What a user may do on the application server."""

    User = "User"  # work with tasks
    Admin = "Admin"  # also manage users, settings and the database


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator[datetime]):
    """DateTime that is always timezone-aware UTC (SQLite drops the tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class IntEnumType(TypeDecorator[enum.IntEnum]):
    """Stores an IntEnum (Priority, Urgency) as its integer value."""

    impl = Integer
    cache_ok = True

    def __init__(self, enum_class: type[enum.IntEnum]) -> None:
        super().__init__()
        self.enum_class = enum_class

    def process_bind_param(self, value: enum.IntEnum | None, dialect: Any) -> int | None:
        return None if value is None else int(self.enum_class(value))

    def process_result_value(self, value: int | None, dialect: Any) -> enum.IntEnum | None:
        return None if value is None else self.enum_class(value)


class Base(DeclarativeBase):
    """Base class for all models."""


class User(Base):
    """A person who creates or is assigned tasks. Deactivated, never deleted."""

    __tablename__ = "User"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name")
    email: Mapped[str | None] = mapped_column("Email", unique=True)
    is_active: Mapped[bool] = mapped_column("IsActive", default=True)
    # Only the application server uses these. No password = cannot log in.
    password_hash: Mapped[str | None] = mapped_column("PasswordHash")
    role: Mapped[UserRole] = mapped_column(
        "Role", default=UserRole.User, server_default=UserRole.User.name
    )


class Workflow(Base):
    """A named set of stages."""

    __tablename__ = "Workflow"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name", unique=True)

    stages: Mapped[list[Stage]] = relationship(
        back_populates="workflow", order_by="Stage.order"
    )


class Stage(Base):
    """One step of a workflow; IsFinal marks the "Done" stage."""

    __tablename__ = "Stage"
    __table_args__ = (UniqueConstraint("WorkflowId", "Order"),)

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    workflow_id: Mapped[int] = mapped_column("WorkflowId", ForeignKey("Workflow.Id"))
    name: Mapped[str] = mapped_column("Name")
    order: Mapped[int] = mapped_column("Order")
    is_final: Mapped[bool] = mapped_column("IsFinal", default=False)

    workflow: Mapped[Workflow] = relationship(back_populates="stages")


class RepeatRule(Base):
    """How often a repeating task comes back."""

    __tablename__ = "RepeatRule"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name")
    interval: Mapped[int] = mapped_column("Interval")
    unit: Mapped[RepeatUnit] = mapped_column("Unit")


class Tag(Base):
    """A label that can be attached to many tasks."""

    __tablename__ = "Tag"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name", unique=True)


class TaskTag(Base):
    """Association row between Task and Tag."""

    __tablename__ = "TaskTag"

    task_id: Mapped[int] = mapped_column(
        "TaskId", ForeignKey("Task.Id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column("TagId", ForeignKey("Tag.Id"), primary_key=True)


class Task(Base):
    """A to-do item. Subtasks are the tasks whose ParentId points here."""

    __tablename__ = "Task"
    # AUTOINCREMENT: ids of deleted tasks are never reused, so their history
    # can never be mistaken for the history of a newer task.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name")
    description: Mapped[str | None] = mapped_column("Description", Text)
    stage_id: Mapped[int] = mapped_column("StageId", ForeignKey("Stage.Id"))
    repeat_rule_id: Mapped[int | None] = mapped_column(
        "RepeatRuleId", ForeignKey("RepeatRule.Id")
    )
    repeat_count: Mapped[int] = mapped_column("RepeatCount", default=0)
    repeat_done: Mapped[int] = mapped_column("RepeatDone", default=0)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", UtcDateTime, default=utcnow)
    # When a completed repeating task goes back to its first stage: local
    # midnight after the interval, stored in UTC. None = no reset waiting.
    next_reset_at: Mapped[datetime | None] = mapped_column("NextResetAt", UtcDateTime)
    # The day the task should be done by (a local date, no time). None = no deadline.
    due_date: Mapped[date | None] = mapped_column("DueDate", Date)
    # Where the task is done ("Gym", "Office, room 12"); free text, None = not given.
    location: Mapped[str | None] = mapped_column("Location")
    priority: Mapped[Priority] = mapped_column(
        "Priority", IntEnumType(Priority), default=Priority.Normal
    )
    urgency: Mapped[Urgency] = mapped_column(
        "Urgency", IntEnumType(Urgency), default=Urgency.Medium
    )
    parent_id: Mapped[int | None] = mapped_column("ParentId", ForeignKey("Task.Id"))
    order: Mapped[int] = mapped_column("Order")
    assignee_id: Mapped[int | None] = mapped_column("AssigneeId", ForeignKey("User.Id"))
    created_by_id: Mapped[int] = mapped_column("CreatedById", ForeignKey("User.Id"))

    stage: Mapped[Stage] = relationship()
    repeat_rule: Mapped[RepeatRule | None] = relationship()
    parent: Mapped[Task | None] = relationship(
        back_populates="subtasks", remote_side=[id]
    )
    subtasks: Mapped[list[Task]] = relationship(
        back_populates="parent", order_by="Task.order"
    )
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    tags: Mapped[list[Tag]] = relationship(secondary="TaskTag")


class SubtaskTemplate(Base):
    """A ready-made subtask ("Write tests", "Pack the car") to add to any task.

    Shared by all users of a database (or server); adding one creates an
    ordinary subtask with these fields, in the parent's workflow.
    """

    __tablename__ = "SubtaskTemplate"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    name: Mapped[str] = mapped_column("Name", unique=True)
    description: Mapped[str | None] = mapped_column("Description", Text)
    priority: Mapped[Priority] = mapped_column(
        "Priority", IntEnumType(Priority), default=Priority.Normal
    )
    urgency: Mapped[Urgency] = mapped_column(
        "Urgency", IntEnumType(Urgency), default=Urgency.Medium
    )


class TaskChange(Base):
    """One entry of the task history / audit log."""

    __tablename__ = "TaskChange"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    # Deliberately no database-level foreign key: the history must survive the
    # deletion of its task (see README, "Choices").
    task_id: Mapped[int] = mapped_column("TaskId", index=True)
    changed_at: Mapped[datetime] = mapped_column("ChangedAt", UtcDateTime, default=utcnow)
    changed_by_id: Mapped[int | None] = mapped_column("ChangedById", ForeignKey("User.Id"))
    change_type: Mapped[ChangeType] = mapped_column("ChangeType")
    field_name: Mapped[str | None] = mapped_column("FieldName")
    old_value: Mapped[str | None] = mapped_column("OldValue", Text)
    new_value: Mapped[str | None] = mapped_column("NewValue", Text)

    changed_by: Mapped[User | None] = relationship()


class ApiToken(Base):
    """A login session of the application server. Only a hash of the token is stored."""

    __tablename__ = "ApiToken"

    id: Mapped[int] = mapped_column("Id", primary_key=True)
    user_id: Mapped[int] = mapped_column("UserId", ForeignKey("User.Id"), index=True)
    token_hash: Mapped[str] = mapped_column("TokenHash", unique=True)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column("ExpiresAt", UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column("RevokedAt", UtcDateTime)

    user: Mapped[User] = relationship()


class ServerSetting(Base):
    """One setting of the application server, e.g. how old history gets compressed."""

    __tablename__ = "ServerSetting"

    key: Mapped[str] = mapped_column("Key", primary_key=True)
    value: Mapped[str] = mapped_column("Value", Text)
