"""Sample data. Tasks are created through TaskService so the history is real."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Priority, RepeatRule, RepeatUnit, Stage, Tag, User, Workflow
from .services import TaskService


# Repeat intervals offered to the user, as (interval, unit).
REPEAT_RULES: list[tuple[int, RepeatUnit]] = [
    *[(days, RepeatUnit.Day) for days in range(1, 11)],
    (1, RepeatUnit.Week),
    (2, RepeatUnit.Week),
    (3, RepeatUnit.Week),
    (1, RepeatUnit.Month),
    (1, RepeatUnit.Year),
]

_EVERY_ONE = {
    RepeatUnit.Day: "Daily",
    RepeatUnit.Week: "Weekly",
    RepeatUnit.Month: "Monthly",
    RepeatUnit.Year: "Yearly",
}


def repeat_rule_name(interval: int, unit: RepeatUnit) -> str:
    """English name of a rule: "Daily", "Every 3 days", "Every 2 weeks", ..."""
    if interval == 1:
        return _EVERY_ONE[unit]
    return f"Every {interval} {unit.value.lower()}s"


def add_missing_repeat_rules(session: Session) -> None:
    """Add every rule from REPEAT_RULES that the database does not have yet."""
    existing = {(rule.interval, rule.unit) for rule in session.scalars(select(RepeatRule))}
    session.add_all(
        RepeatRule(name=repeat_rule_name(interval, unit), interval=interval, unit=unit)
        for interval, unit in REPEAT_RULES
        if (interval, unit) not in existing
    )
    session.commit()


def _workflow(name: str, stage_names: list[str]) -> Workflow:
    """Build a workflow whose last stage is the final one."""
    stages = [
        Stage(name=stage, order=position, is_final=position == len(stage_names))
        for position, stage in enumerate(stage_names, start=1)
    ]
    return Workflow(name=name, stages=stages)


def seed(session: Session, with_tasks: bool = True, with_users: bool = True) -> None:
    """Fill an empty database with sample users, workflows, tags and tasks.

    With with_tasks=False only the reference data is added, no tasks; with
    with_users=False also no sample users (the application server creates its
    own accounts).
    """
    if with_tasks and not with_users:
        raise ValueError("The sample tasks need the sample users")
    anna = User(name="Anna Kowalska", email="anna@example.com")
    piotr = User(name="Piotr Nowak", email="piotr@example.com")
    simple = _workflow("Simple", ["To do", "Done"])
    software = _workflow("Software", ["Idea", "Planned", "In progress", "Review", "Done"])
    weekly = RepeatRule(name="Weekly", interval=1, unit=RepeatUnit.Week)
    work, home, career = Tag(name="work"), Tag(name="home"), Tag(name="career")
    if with_users:
        session.add_all([anna, piotr])
    session.add_all(
        [
            simple,
            software,
            RepeatRule(name="Daily", interval=1, unit=RepeatUnit.Day),
            weekly,
            RepeatRule(name="Every 2 weeks", interval=2, unit=RepeatUnit.Week),
            work,
            home,
            career,
        ]
    )
    session.commit()
    add_missing_repeat_rules(session)
    if not with_tasks:
        return

    todo, done = simple.stages
    idea, planned, in_progress, _review, _done = software.stages
    service = TaskService(session)

    portfolio = service.create_task(
        "Prepare portfolio project",
        in_progress.id,
        anna.id,
        priority=Priority.Important,
        assignee_id=anna.id,
        tag_ids=[work.id, career.id],
    )
    service.create_task(
        "Write README", planned.id, anna.id, parent_id=portfolio.id, assignee_id=piotr.id
    )
    service.create_task(
        "Add unit tests",
        idea.id,
        anna.id,
        parent_id=portfolio.id,
        priority=Priority.Maybe,
        assignee_id=anna.id,
    )

    # RepeatDone = 3: complete it three times; each time it is reset to "To do".
    review = service.create_task(
        "Weekly review", todo.id, anna.id, repeat_rule_id=weekly.id, repeat_count=0
    )
    for _ in range(3):
        service.update_task(review.id, anna.id, stage_id=done.id)
        # Jump to the moment it is due again, as if a week had passed.
        service.reset_due_tasks(now=review.next_reset_at)

    groceries = service.create_task("Buy groceries", todo.id, anna.id, tag_ids=[home.id])
    service.update_task(groceries.id, anna.id, stage_id=done.id)
