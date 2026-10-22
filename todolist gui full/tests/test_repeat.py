"""Repeating tasks: completing counts at once, the reset waits for the next interval."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from todo_db.models import ChangeType, RepeatRule, RepeatUnit, Task
from todo_db.services import TaskService, add_interval, next_due_date

from .conftest import World

# Noon UTC is the same calendar day in every time zone from UTC-11 to UTC+11,
# so these tests do not depend on the computer's time zone.
START = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def local_midnight(day: date) -> datetime:
    """The start of a local calendar day, in UTC."""
    return datetime.combine(day, time()).astimezone().astimezone(timezone.utc)


@pytest.fixture
def clock() -> Clock:
    return Clock(START)


@pytest.fixture
def timed(session: Session, clock: Clock) -> TaskService:
    """A service that reads the time from the test clock."""
    return TaskService(session, clock=clock)


def make_rule(session: Session, interval: int, unit: RepeatUnit) -> int:
    rule = RepeatRule(name=f"{interval} {unit.value}", interval=interval, unit=unit)
    session.add(rule)
    session.commit()
    return rule.id


def test_daily_task_stays_done_until_midnight(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Water plants", world.todo, world.anna, repeat_rule_id=daily)

    timed.update_task(task.id, world.piotr, stage_id=world.done)

    assert (task.stage_id, task.repeat_done) == (world.done, 1)
    midnight = local_midnight(START.astimezone().date() + timedelta(days=1))
    assert task.next_reset_at == midnight

    # Still today: nothing happens.
    assert timed.reset_due_tasks(now=midnight - timedelta(seconds=1)) == 0
    assert task.stage_id == world.done

    # Midnight: back to the first stage.
    clock.now = midnight
    assert timed.reset_due_tasks() == 1
    assert (task.stage_id, task.repeat_done, task.next_reset_at) == (world.todo, 1, None)
    assert timed.reset_due_tasks() == 0  # only once


def test_history_of_one_cycle(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    task = timed.create_task("Review", world.todo, world.anna, repeat_rule_id=weekly)

    timed.update_task(task.id, world.piotr, stage_id=world.done)
    clock.now = task.next_reset_at
    timed.reset_due_tasks()

    assert [
        (c.change_type, c.changed_by_id, c.field_name, c.old_value, c.new_value)
        for c in timed.get_history(task.id)[1:]
    ] == [
        (ChangeType.StageChanged, world.piotr, "StageId", "To do", "Done"),
        (ChangeType.Completed, world.piotr, None, None, None),
        (ChangeType.Updated, None, "RepeatDone", "0", "1"),
        (ChangeType.StageChanged, None, "StageId", "Done", "To do"),
    ]
    assert timed.get_history(task.id)[-1].changed_at == clock.now


@pytest.mark.parametrize(
    ("interval", "unit", "days_later"),
    [
        (1, RepeatUnit.Day, 1),
        (2, RepeatUnit.Day, 2),
        (7, RepeatUnit.Day, 7),
        (10, RepeatUnit.Day, 10),
        (1, RepeatUnit.Week, 7),
        (2, RepeatUnit.Week, 14),
        (3, RepeatUnit.Week, 21),
        (1, RepeatUnit.Month, 31),  # 10 March -> 10 April
        (1, RepeatUnit.Year, 365),  # 10 March 2026 -> 10 March 2027
    ],
)
def test_every_interval_waits_the_right_time(
    timed: TaskService,
    session: Session,
    world: World,
    interval: int,
    unit: RepeatUnit,
    days_later: int,
) -> None:
    rule = make_rule(session, interval, unit)
    task = timed.create_task("Task", world.todo, world.anna, repeat_rule_id=rule)

    timed.update_task(task.id, world.anna, stage_id=world.done)

    due = local_midnight(START.astimezone().date() + timedelta(days=days_later))
    assert task.next_reset_at == due
    assert timed.reset_due_tasks(now=due - timedelta(minutes=1)) == 0
    assert timed.reset_due_tasks(now=due) == 1
    assert task.stage_id == world.todo


@pytest.mark.parametrize(
    ("start", "interval", "unit", "expected"),
    [
        (date(2026, 1, 31), 1, RepeatUnit.Month, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, RepeatUnit.Month, date(2028, 2, 29)),
        (date(2026, 12, 15), 1, RepeatUnit.Month, date(2027, 1, 15)),
        (date(2026, 11, 30), 3, RepeatUnit.Month, date(2027, 2, 28)),
        (date(2028, 2, 29), 1, RepeatUnit.Year, date(2029, 2, 28)),
        (date(2026, 12, 31), 1, RepeatUnit.Day, date(2027, 1, 1)),
        (date(2026, 12, 28), 1, RepeatUnit.Week, date(2027, 1, 4)),
    ],
)
def test_add_interval_calendar_edges(
    start: date, interval: int, unit: RepeatUnit, expected: date
) -> None:
    assert add_interval(start, interval, unit) == expected


def test_completed_late_in_the_evening_still_resets_at_the_next_midnight(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Late", world.todo, world.anna, repeat_rule_id=daily)
    today = START.astimezone().date()
    clock.now = local_midnight(today + timedelta(days=1)) - timedelta(minutes=5)  # 23:55 local

    timed.update_task(task.id, world.anna, stage_id=world.done)

    assert task.next_reset_at == local_midnight(today + timedelta(days=1))


def test_program_closed_for_days_resets_on_next_start(
    timed: TaskService, session: Session, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Daily", world.todo, world.anna, repeat_rule_id=daily)
    timed.update_task(task.id, world.anna, stage_id=world.done)

    assert timed.reset_due_tasks(now=START + timedelta(days=5)) == 1
    assert (task.stage_id, task.repeat_done) == (world.todo, 1)


def test_limited_repeat_stays_completed_at_the_end(
    timed: TaskService, session: Session, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    task = timed.create_task(
        "Twice", world.idea, world.anna, repeat_rule_id=weekly, repeat_count=2
    )

    timed.update_task(task.id, world.anna, stage_id=world.soft_done)
    assert task.repeat_done == 1
    timed.reset_due_tasks(now=task.next_reset_at)
    assert task.stage_id == world.idea

    timed.update_task(task.id, world.anna, stage_id=world.soft_done)
    assert (task.repeat_done, task.stage_id, task.next_reset_at) == (2, world.soft_done, None)
    assert timed.reset_due_tasks(now=START + timedelta(days=365)) == 0
    assert task.stage_id == world.soft_done


def test_reopened_by_hand_cancels_the_reset(
    timed: TaskService, session: Session, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Daily", world.todo, world.anna, repeat_rule_id=daily)
    timed.update_task(task.id, world.anna, stage_id=world.done)
    due = task.next_reset_at

    timed.update_task(task.id, world.anna, stage_id=world.todo)

    assert task.next_reset_at is None
    assert timed.reset_due_tasks(now=due) == 0
    assert len(timed.get_history(task.id)) == 5  # no automatic row


def test_removed_rule_cancels_the_reset(
    timed: TaskService, session: Session, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Daily", world.todo, world.anna, repeat_rule_id=daily)
    timed.update_task(task.id, world.anna, stage_id=world.done)
    due = task.next_reset_at

    timed.update_task(task.id, world.anna, repeat_rule_id=None)

    assert timed.reset_due_tasks(now=due) == 0
    assert (task.stage_id, task.next_reset_at) == (world.done, None)


def test_non_final_stage_does_not_count_as_repeat(
    timed: TaskService, session: Session, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    task = timed.create_task("Feature", world.idea, world.anna, repeat_rule_id=weekly)

    timed.update_task(task.id, world.anna, stage_id=world.planned)

    assert (task.repeat_done, task.stage_id, task.next_reset_at) == (0, world.planned, None)


def test_task_without_rule_stays_completed(timed: TaskService, world: World) -> None:
    task = timed.create_task("Once", world.todo, world.anna)

    timed.update_task(task.id, world.anna, stage_id=world.done)

    assert (task.repeat_done, task.stage_id, task.next_reset_at) == (0, world.done, None)
    assert timed.reset_due_tasks(now=START + timedelta(days=365)) == 0


def test_seeded_weekly_review(session: Session) -> None:
    from todo_db.seed import seed

    seed(session)
    review = session.query(Task).filter_by(name="Weekly review").one()
    assert (review.stage.name, review.repeat_done, review.next_reset_at) == ("To do", 3, None)


# -- due dates of repeating tasks ------------------------------------------------

TODAY = START.astimezone().date()  # 2026-03-10 in every time zone, see START


def test_completing_moves_the_due_date_to_the_next_one(
    timed: TaskService, session: Session, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    on_time = timed.create_task("Review", world.todo, world.anna, repeat_rule_id=weekly,
                                due_date=TODAY)
    early = timed.create_task("Report", world.todo, world.anna, repeat_rule_id=weekly,
                              due_date=TODAY + timedelta(days=3))
    late = timed.create_task("Bills", world.todo, world.anna, repeat_rule_id=weekly,
                             due_date=TODAY - timedelta(days=10))
    for task in (on_time, early, late):
        timed.update_task(task.id, world.anna, stage_id=world.done)

    assert on_time.due_date == TODAY + timedelta(days=7)
    assert early.due_date == TODAY + timedelta(days=10)  # the next one after the current
    assert late.due_date == TODAY + timedelta(days=4)  # missed ones are skipped
    change = timed.get_history(on_time.id)[-1]
    assert (change.changed_by_id, change.field_name, change.old_value, change.new_value) == (
        None, "DueDate", "2026-03-10", "2026-03-17"
    )


def test_a_date_saved_together_with_completing_is_the_one_moved_on(
    timed: TaskService, session: Session, world: World
) -> None:
    daily = make_rule(session, 1, RepeatUnit.Day)
    task = timed.create_task("Run", world.todo, world.anna, repeat_rule_id=daily,
                             due_date=TODAY - timedelta(days=5))
    # The task form sends every field; the stage comes before the date in it.
    timed.update_task(task.id, world.anna, stage_id=world.done, due_date=TODAY)
    assert task.due_date == TODAY + timedelta(days=1)


def test_missed_due_date_moves_on_at_midnight(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    task = timed.create_task("Review", world.todo, world.anna, repeat_rule_id=weekly,
                             due_date=TODAY)
    once = timed.create_task("Dentist", world.todo, world.anna, due_date=TODAY)

    timed.reset_due_tasks()
    assert task.due_date == TODAY  # due today: not missed yet

    clock.now = local_midnight(TODAY + timedelta(days=1))
    timed.reset_due_tasks()  # what the program and the server run at midnight
    assert task.due_date == TODAY + timedelta(days=7)
    assert once.due_date == TODAY  # not repeating: stays overdue
    assert timed.get_history(task.id)[-1].changed_by_id is None

    clock.now = local_midnight(TODAY + timedelta(days=30))  # closed for weeks
    assert timed.roll_missed_due_dates() == 1
    assert task.due_date == TODAY + timedelta(days=35)


def test_finished_repeat_keeps_its_date(
    timed: TaskService, session: Session, clock: Clock, world: World
) -> None:
    weekly = make_rule(session, 1, RepeatUnit.Week)
    task = timed.create_task("Course", world.todo, world.anna, repeat_rule_id=weekly,
                             repeat_count=1, due_date=TODAY)
    timed.update_task(task.id, world.anna, stage_id=world.done)  # the last time
    assert task.due_date == TODAY
    clock.now = local_midnight(TODAY + timedelta(days=10))
    assert timed.roll_missed_due_dates() == 0


def test_next_due_date_keeps_month_ends() -> None:
    monthly = RepeatRule(name="Monthly", interval=1, unit=RepeatUnit.Month)
    assert next_due_date(date(2026, 1, 31), monthly, date(2026, 1, 31), True) == date(2026, 2, 28)
    assert next_due_date(date(2026, 1, 31), monthly, date(2026, 3, 1), True) == date(2026, 3, 31)
    assert next_due_date(date(2026, 1, 31), monthly, date(2026, 3, 31), False) == date(2026, 3, 31)
