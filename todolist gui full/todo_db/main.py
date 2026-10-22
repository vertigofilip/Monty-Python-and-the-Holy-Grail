"""Demo: create the database, seed it, print the tasks and their history.

Run with:  python -m todo_db.main
"""

from __future__ import annotations

from sqlalchemy import select

from .database import create_all, make_engine, make_session_factory
from .models import Base, Task
from .seed import seed
from .services import TaskService


def print_task(service: TaskService, task: Task, indent: int = 0) -> None:
    """Print one task line and, below it, its subtasks."""
    assignee = task.assignee.name if task.assignee else "-"
    tags = ", ".join(tag.name for tag in task.tags) or "-"
    repeat = ""
    if task.repeat_rule:
        limit = task.repeat_count or "inf"
        repeat = f" | repeats {task.repeat_rule.name} ({task.repeat_done}/{limit})"
    print(
        f"{'    ' * indent}{task.id}. {task.name} [{task.stage.name}] "
        f"{task.priority.name}, urgency {task.urgency.name} | "
        f"assignee: {assignee} | tags: {tags} | "
        f"progress: {service.get_progress_percent(task.id):.0f}%{repeat}"
    )
    for subtask in task.subtasks:
        print_task(service, subtask, indent + 1)


def main() -> None:
    """Rebuild demo.db from scratch and show what is in it."""
    engine = make_engine("sqlite:///demo.db")
    Base.metadata.drop_all(engine)
    create_all(engine)

    with make_session_factory(engine)() as session:
        seed(session)
        service = TaskService(session)

        print("TASKS")
        top_level = select(Task).where(Task.parent_id.is_(None)).order_by(Task.order)
        for task in session.scalars(top_level):
            print_task(service, task)

        print("\nHISTORY")
        for task in session.scalars(select(Task).order_by(Task.id)):
            print(f"{task.id}. {task.name}")
            for change in service.get_history(task.id):
                who = change.changed_by.name if change.changed_by else "system"
                line = f"    {change.changed_at:%Y-%m-%d %H:%M:%S} UTC  {who:<14} {change.change_type.name:<13}"
                if change.field_name:
                    line += f" {change.field_name}: {change.old_value} -> {change.new_value}"
                elif change.new_value:
                    line += f" {change.new_value}"
                print(line.rstrip())


if __name__ == "__main__":
    main()
