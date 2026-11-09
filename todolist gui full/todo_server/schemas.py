"""Request and response bodies of the HTTP API."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

from todo_db.models import Priority, Urgency, UserRole

from .security import MIN_PASSWORD_LENGTH


def _by_name(enum_class: type[enum.Enum]) -> BeforeValidator:
    """Accept an enum by name ("Important") as well as by value (2)."""

    def convert(value: Any) -> Any:
        """A level's name becomes the level; anything else is left to the check."""
        if isinstance(value, str) and value in enum_class.__members__:
            return enum_class[value]
        return value

    return BeforeValidator(convert)


PriorityIn = Annotated[Priority, _by_name(Priority)]
UrgencyIn = Annotated[Urgency, _by_name(Urgency)]
Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
Location = Annotated[str, Field(max_length=200)]


# -- auth and users -----------------------------------------------------------


class LoginIn(BaseModel):
    """What POST /auth/login receives."""
    email: str
    password: str


class UserOut(BaseModel):
    """An account, as administrators and its owner see it."""
    id: int
    name: str
    email: str | None
    is_active: bool
    role: UserRole


class PublicUserOut(BaseModel):
    """What every logged-in user may see about colleagues (e.g. to assign tasks)."""

    id: int
    name: str
    is_active: bool


class TokenOut(BaseModel):
    """The answer to a login: the token and who it is for."""
    token: str
    expires_at: datetime
    user: UserOut


class UserCreate(BaseModel):
    """A new account."""
    name: Name
    email: str
    password: Password | None = None
    role: UserRole = UserRole.User


class UserUpdate(BaseModel):
    """Changes to an account; only the fields sent are changed."""
    name: Name | None = None
    email: str | None = None
    password: Password | None = None
    role: UserRole | None = None
    is_active: bool | None = None


# -- reference data -------------------------------------------------------------


class StageOut(BaseModel):
    """One stage of a workflow."""
    id: int
    name: str
    order: int
    is_final: bool


class WorkflowOut(BaseModel):
    """A workflow with its stages in order."""
    id: int
    name: str
    stages: list[StageOut]


class TagOut(BaseModel):
    """A tag."""
    id: int
    name: str


class TagUsageOut(TagOut):
    """A tag with its number of tasks."""
    tasks: int  # how many tasks have the tag


class NameIn(BaseModel):
    """A new workflow, stage or tag, or a new name for one."""

    name: Name


class StageUpdate(BaseModel):
    """Only the fields sent are changed."""

    name: Name | None = None
    is_final: bool | None = None


class StageMove(BaseModel):
    """Which way to move a stage."""
    delta: Literal[-1, 1]  # up or down


class RepeatRuleOut(BaseModel):
    """A repeat rule."""
    id: int
    name: str
    interval: int
    unit: str


# -- subtask templates ------------------------------------------------------------

PriorityName = Literal["Maybe", "Normal", "Important"]
UrgencyName = Literal["Low", "Medium", "High"]


class SubtaskTemplateIn(BaseModel):
    """A new subtask template."""
    name: Name
    description: str | None = None
    priority: PriorityName = "Normal"
    urgency: UrgencyName = "Medium"


class SubtaskTemplateUpdate(BaseModel):
    """Only the fields sent are changed."""

    name: Name | None = None
    description: str | None = None
    priority: PriorityName | None = None
    urgency: UrgencyName | None = None


class SubtaskTemplateOut(BaseModel):
    """A subtask template."""
    id: int
    name: str
    description: str | None
    priority: str
    urgency: str


# -- tasks ----------------------------------------------------------------------


class TaskCreate(BaseModel):
    """A new task."""
    name: Name
    stage_id: int
    description: str | None = None
    priority: PriorityIn = Priority.Normal
    urgency: UrgencyIn = Urgency.Medium
    due_date: date | None = None
    location: Location | None = None
    parent_id: int | None = None
    assignee_id: int | None = None
    repeat_rule_id: int | None = None
    repeat_count: Annotated[int, Field(ge=0)] = 0
    tag_ids: list[int] = []


class TaskUpdate(BaseModel):
    """Only the fields sent are changed; send null to clear an optional field."""

    name: Name | None = None
    description: str | None = None
    priority: PriorityIn | None = None
    urgency: UrgencyIn | None = None
    due_date: date | None = None
    location: Location | None = None
    stage_id: int | None = None
    assignee_id: int | None = None
    repeat_rule_id: int | None = None
    repeat_count: Annotated[int, Field(ge=0)] | None = None
    tag_ids: list[int] | None = None
    parent_id: int | None = None
    order: Annotated[int, Field(ge=1)] | None = None


class TaskMove(BaseModel):
    """A task's new parent and place among its siblings."""
    parent_id: int | None = None
    order: Annotated[int, Field(ge=1)] | None = None  # None = at the end


class TaskOut(BaseModel):
    """A task with everything the clients show."""
    id: int
    name: str
    description: str | None
    stage_id: int
    stage: str
    workflow_id: int
    done: bool
    priority: str
    urgency: str
    parent_id: int | None
    order: int
    assignee_id: int | None
    assignee: str | None
    created_by_id: int
    created_at: datetime
    repeat_rule_id: int | None
    repeat_count: int
    repeat_done: int
    next_reset_at: datetime | None
    due_date: date | None = None
    location: str | None = None
    tags: list[TagOut]
    progress_percent: float


class HistoryQuery(BaseModel):
    """Which tasks' history is wanted together."""
    task_ids: list[int]


class ChangeOut(BaseModel):
    """One history entry."""
    id: int
    task_id: int
    changed_at: datetime
    changed_by_id: int | None
    changed_by: str | None  # None = the system
    change_type: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    summary: dict[str, Any] | None  # only for Compressed rows


# -- administration -------------------------------------------------------------


class SettingsIO(BaseModel):
    """The server's settings, read and written."""
    auto_compress_enabled: bool
    compress_after_days: Annotated[int, Field(ge=0, le=36500)]


class CompressAllIn(BaseModel):
    """How old history must be to compress it in all tasks."""
    older_than_days: Annotated[int, Field(ge=0)] | None = None  # None = the saved setting


class CompressTaskIn(BaseModel):
    """How old history must be to compress it in one task."""
    older_than_days: Annotated[int, Field(ge=0)] | None = None  # None = all of it


class CompressionOut(BaseModel):
    """What a compression did."""
    tasks: int
    rows_removed: int
