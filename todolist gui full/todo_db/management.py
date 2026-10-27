"""Users, workflows (with their stages) and tags of a local database: add, change, delete.

Shared by the desktop program's windows and the phone app's database without a
server (todo_mobile.local). Every function commits its change; a change that
is not allowed or cannot be saved is undone and raises ManagementError with a
message for the user, already translated.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .i18n import tr
from .models import Stage, Tag, Task, TaskTag, User, Workflow


class ManagementError(ValueError):
    """A change that is refused or could not be saved (message for the user)."""


def _commit(session: Session, error: str) -> None:
    """Save the pending change; on failure undo it and raise with the (translated) message."""
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise ManagementError(error) from exc


def _get(session: Session, model: type, item_id: int) -> object:
    item = session.get(model, item_id)
    if item is None:
        raise ManagementError(f"{model.__name__} {item_id} does not exist")
    return item


def _in_use(name: str, used: int) -> ManagementError:
    return ManagementError(
        tr('"{name}" is used by {used} task(s) and cannot be deleted.').format(name=name, used=used)
    )


# -- users ---------------------------------------------------------------------


def _user_fields(name: str, email: str | None) -> tuple[str, str | None]:
    name = name.strip()
    if not name:
        raise ManagementError(tr("The user needs a name."))
    return name, (email or "").strip() or None


def add_user(session: Session, name: str, email: str | None = None) -> User:
    name, email = _user_fields(name, email)
    user = User(name=name, email=email)
    session.add(user)
    _commit(session, tr("Could not save. Another user already has this email."))
    return user


def update_user(session: Session, user_id: int, name: str, email: str | None) -> User:
    user = _get(session, User, user_id)
    user.name, user.email = _user_fields(name, email)  # type: ignore[attr-defined]
    _commit(session, tr("Could not save. Another user already has this email."))
    return user  # type: ignore[return-value]


def set_user_active(session: Session, user_id: int, active: bool) -> User:
    """Deactivate or reactivate a user (users are never deleted); one must stay active."""
    user: User = _get(session, User, user_id)  # type: ignore[assignment]
    if user.is_active and not active:
        others = session.scalar(
            select(func.count()).select_from(User).where(User.is_active, User.id != user.id)
        )
        if not others:
            raise ManagementError(tr("At least one user must stay active."))
    user.is_active = active
    _commit(session, tr("Could not save."))
    return user


# -- workflows and stages ----------------------------------------------------------


def _tasks_using(session: Session, stage_ids: list[int]) -> int:
    """Number of tasks in one of the stages."""
    query = select(func.count()).select_from(Task).where(Task.stage_id.in_(stage_ids))
    return session.scalar(query) or 0


def _reorder(session: Session, stages: list[Stage]) -> None:
    """Give the stages Order 1..n in list order.

    Goes through negative numbers first, because (WorkflowId, Order) is unique
    and two stages must never share a number, even for a moment.
    """
    for position, stage in enumerate(stages, start=1):
        stage.order = -position
    session.flush()
    for position, stage in enumerate(stages, start=1):
        stage.order = position


def _name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ManagementError(tr("Enter a name."))
    return name


def add_workflow(session: Session, name: str) -> Workflow:
    """A workflow with a starting "To do" and a final "Done" stage."""
    workflow = Workflow(
        name=_name(name),
        stages=[Stage(name=tr("To do"), order=1), Stage(name=tr("Done"), order=2, is_final=True)],
    )
    session.add(workflow)
    _commit(session, tr("A workflow with this name already exists."))
    return workflow


def rename_workflow(session: Session, workflow_id: int, name: str) -> Workflow:
    workflow: Workflow = _get(session, Workflow, workflow_id)  # type: ignore[assignment]
    workflow.name = _name(name)
    _commit(session, tr("A workflow with this name already exists."))
    return workflow


def check_delete_workflow(session: Session, workflow_id: int) -> Workflow:
    """The workflow, if it may be deleted (another one remains, no task uses it)."""
    workflow: Workflow = _get(session, Workflow, workflow_id)  # type: ignore[assignment]
    if (session.scalar(select(func.count()).select_from(Workflow)) or 0) <= 1:
        raise ManagementError(tr("At least one workflow must remain."))
    used = _tasks_using(session, [stage.id for stage in workflow.stages])
    if used:
        raise _in_use(workflow.name, used)
    return workflow


def delete_workflow(session: Session, workflow_id: int) -> None:
    """Delete a workflow and its stages, if no task uses them."""
    workflow = check_delete_workflow(session, workflow_id)
    for stage in list(workflow.stages):
        session.delete(stage)
    session.flush()
    session.delete(workflow)
    _commit(session, tr("Could not delete the workflow."))


def add_stage(session: Session, workflow_id: int, name: str) -> Stage:
    """A stage at the end of the workflow."""
    workflow: Workflow = _get(session, Workflow, workflow_id)  # type: ignore[assignment]
    stage = Stage(workflow_id=workflow.id, name=_name(name), order=len(workflow.stages) + 1)
    session.add(stage)
    _commit(session, tr("Could not add the stage."))
    return stage


def rename_stage(session: Session, stage_id: int, name: str) -> Stage:
    stage: Stage = _get(session, Stage, stage_id)  # type: ignore[assignment]
    stage.name = _name(name)
    _commit(session, tr("Could not rename the stage."))
    return stage


def shift_stage(session: Session, stage_id: int, delta: int) -> Stage:
    """Move a stage up (-1) or down (+1) in its workflow; at either end nothing happens."""
    stage: Stage = _get(session, Stage, stage_id)  # type: ignore[assignment]
    stages = list(stage.workflow.stages)
    index = stages.index(stage)
    target = index + delta
    if 0 <= target < len(stages):
        stages[index], stages[target] = stages[target], stages[index]
        _reorder(session, stages)
        _commit(session, tr("Could not reorder the stages."))
    return stage


def set_stage_final(session: Session, stage_id: int, is_final: bool) -> Stage:
    """Whether tasks in the stage count as done."""
    stage: Stage = _get(session, Stage, stage_id)  # type: ignore[assignment]
    stage.is_final = is_final
    _commit(session, tr("Could not change the stage."))
    return stage


def check_delete_stage(session: Session, stage_id: int) -> Stage:
    """The stage, if it may be deleted (not the last of its workflow, no task in it)."""
    stage: Stage = _get(session, Stage, stage_id)  # type: ignore[assignment]
    if len(stage.workflow.stages) <= 1:
        raise ManagementError(tr("A workflow needs at least one stage."))
    used = _tasks_using(session, [stage.id])
    if used:
        raise _in_use(stage.name, used)
    return stage


def delete_stage(session: Session, stage_id: int) -> None:
    """Delete a stage, if no task is in it; the others are numbered again."""
    stage = check_delete_stage(session, stage_id)
    remaining = [other for other in stage.workflow.stages if other is not stage]
    session.delete(stage)
    session.flush()
    _reorder(session, remaining)
    _commit(session, tr("Could not delete the stage."))


# -- tags --------------------------------------------------------------------------


def tag_usage(session: Session) -> list[tuple[Tag, int]]:
    """Every tag (by name) with the number of tasks that have it."""
    query = (
        select(Tag, func.count(TaskTag.task_id))
        .outerjoin(TaskTag, TaskTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    )
    return [(tag, used) for tag, used in session.execute(query)]


def add_tag(session: Session, name: str) -> Tag:
    tag = Tag(name=_name(name))
    session.add(tag)
    _commit(session, tr("A tag with this name already exists."))
    return tag


def rename_tag(session: Session, tag_id: int, name: str) -> Tag:
    """Rename a tag; tasks keep it under the new name."""
    tag: Tag = _get(session, Tag, tag_id)  # type: ignore[assignment]
    tag.name = _name(name)
    _commit(session, tr("A tag with this name already exists."))
    return tag


def check_delete_tag(session: Session, tag_id: int) -> Tag:
    """The tag, if no task uses it."""
    tag: Tag = _get(session, Tag, tag_id)  # type: ignore[assignment]
    used = session.scalar(select(func.count()).select_from(TaskTag).where(TaskTag.tag_id == tag.id))
    if used:
        raise _in_use(tag.name, used)
    return tag


def delete_tag(session: Session, tag_id: int) -> None:
    session.delete(check_delete_tag(session, tag_id))
    _commit(session, tr("Could not delete the tag."))
