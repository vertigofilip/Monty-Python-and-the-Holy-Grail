"""Subtask templates: a list of ready-made subtasks to add to any task.

Shared by the desktop program (local database), the application server and
the phone app's database without a server (todo_mobile.local), so a template
means the same everywhere. Templates travel as plain data: {"id", "name",
"description", "priority", "urgency"}, the levels by name ("Important").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .i18n import tr
from .management import ManagementError, _commit, _get
from .models import Priority, SubtaskTemplate, Urgency


def template_data(template: SubtaskTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "priority": template.priority.name,
        "urgency": template.urgency.name,
    }


def list_templates(session: Session) -> list[SubtaskTemplate]:
    """All templates, by name."""
    return list(session.scalars(select(SubtaskTemplate).order_by(SubtaskTemplate.name)))


def _apply(template: SubtaskTemplate, fields: dict[str, Any]) -> None:
    """Set the fields given (levels by name); a name must not be empty."""
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise ManagementError(tr("Enter a name."))
        template.name = name
    if "description" in fields:
        template.description = (fields["description"] or "").strip() or None
    try:
        if fields.get("priority") is not None:
            template.priority = Priority[fields["priority"]]
        if fields.get("urgency") is not None:
            template.urgency = Urgency[fields["urgency"]]
    except KeyError as error:
        raise ManagementError(f"Unknown level {error}") from error


def add_template(session: Session, fields: dict[str, Any]) -> SubtaskTemplate:
    template = SubtaskTemplate(priority=Priority.Normal, urgency=Urgency.Medium)
    _apply(template, {"name": "", **fields})
    session.add(template)
    _commit(session, tr("A template with this name already exists."))
    return template


def update_template(
    session: Session, template_id: int, fields: dict[str, Any]
) -> SubtaskTemplate:
    template: SubtaskTemplate = _get(session, SubtaskTemplate, template_id)  # type: ignore[assignment]
    _apply(template, fields)
    _commit(session, tr("A template with this name already exists."))
    return template


def delete_template(session: Session, template_id: int) -> None:
    """Delete a template; subtasks made from it stay as they are."""
    session.delete(_get(session, SubtaskTemplate, template_id))
    _commit(session, tr("Could not delete the template."))


def subtask_fields(template: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    """The new subtask's fields (as POST /tasks takes them) for a template and a parent.

    parent: {"id", "first_stage_id", "assignee_id"}. The subtask starts at the
    first stage of the parent's workflow and goes to the parent's assignee.
    """
    return {
        "name": template["name"],
        "stage_id": parent["first_stage_id"],
        "parent_id": parent["id"],
        "description": template["description"],
        "priority": template["priority"],
        "urgency": template["urgency"],
        "assignee_id": parent["assignee_id"],
    }
