"""Rows of the database as the plain data the HTTP API sends (dicts, no pydantic).

The application server wraps these in its response models; the phone app's
local mode (todo_mobile/local.py) uses them directly, so both give the phone
exactly the same data.
"""

from __future__ import annotations

from typing import Any

from .compression import parse_summary
from .models import RepeatRule, Tag, Task, TaskChange, User, Workflow
from .services import TaskService


def public_user_data(user: User) -> dict[str, Any]:
    """What every logged-in user may see about colleagues (e.g. to assign tasks)."""
    return {"id": user.id, "name": user.name, "is_active": user.is_active}


def workflow_data(workflow: Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "stages": [
            {"id": s.id, "name": s.name, "order": s.order, "is_final": s.is_final}
            for s in workflow.stages
        ],
    }


def tag_data(tag: Tag) -> dict[str, Any]:
    return {"id": tag.id, "name": tag.name}


def repeat_rule_data(rule: RepeatRule) -> dict[str, Any]:
    return {"id": rule.id, "name": rule.name, "interval": rule.interval, "unit": rule.unit.value}


def task_data(service: TaskService, task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "stage_id": task.stage_id,
        "stage": task.stage.name,
        "workflow_id": task.stage.workflow_id,
        "done": task.stage.is_final,
        "priority": task.priority.name,
        "urgency": task.urgency.name,
        "parent_id": task.parent_id,
        "order": task.order,
        "assignee_id": task.assignee_id,
        "assignee": task.assignee.name if task.assignee else None,
        "created_by_id": task.created_by_id,
        "created_at": task.created_at,
        "repeat_rule_id": task.repeat_rule_id,
        "repeat_count": task.repeat_count,
        "repeat_done": task.repeat_done,
        "next_reset_at": task.next_reset_at,
        "due_date": task.due_date,
        "location": task.location,
        "tags": [tag_data(tag) for tag in task.tags],
        "progress_percent": service.get_progress_percent(task.id),
    }


def change_data(change: TaskChange) -> dict[str, Any]:
    return {
        "id": change.id,
        "task_id": change.task_id,
        "changed_at": change.changed_at,
        "changed_by_id": change.changed_by_id,
        "changed_by": change.changed_by.name if change.changed_by else None,
        "change_type": change.change_type.name,
        "field_name": change.field_name,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "summary": parse_summary(change),
    }
