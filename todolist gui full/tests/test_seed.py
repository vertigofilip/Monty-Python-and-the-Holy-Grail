"""Reference data: the standard repeat intervals."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from todo_db.models import RepeatRule, RepeatUnit
from todo_db.seed import REPEAT_RULES, add_missing_repeat_rules, repeat_rule_name, seed


def rules(session: Session) -> list[tuple[str, int, RepeatUnit]]:
    """All rules as (name, interval, unit), in id order."""
    query = select(RepeatRule).order_by(RepeatRule.id)
    return [(rule.name, rule.interval, rule.unit) for rule in session.scalars(query)]


def test_rule_names() -> None:
    assert repeat_rule_name(1, RepeatUnit.Day) == "Daily"
    assert repeat_rule_name(4, RepeatUnit.Day) == "Every 4 days"
    assert repeat_rule_name(3, RepeatUnit.Week) == "Every 3 weeks"
    assert repeat_rule_name(1, RepeatUnit.Year) == "Yearly"


def test_seed_has_every_interval_once(session: Session) -> None:
    seed(session, with_tasks=False)

    found = rules(session)
    assert sorted((interval, unit.value) for _, interval, unit in found) == sorted(
        (interval, unit.value) for interval, unit in REPEAT_RULES
    )
    assert ("Every 10 days", 10, RepeatUnit.Day) in found
    assert ("Every 2 weeks", 2, RepeatUnit.Week) in found


def test_missing_rules_are_added_to_an_older_database(session: Session) -> None:
    session.add(RepeatRule(name="Weekly", interval=1, unit=RepeatUnit.Week))
    session.add(RepeatRule(name="Fortnightly", interval=2, unit=RepeatUnit.Week))
    session.commit()

    add_missing_repeat_rules(session)
    add_missing_repeat_rules(session)  # running it again adds nothing

    found = rules(session)
    assert len(found) == len(REPEAT_RULES)
    assert found[:2] == [
        ("Weekly", 1, RepeatUnit.Week),
        ("Fortnightly", 2, RepeatUnit.Week),  # existing rules are left as they are
    ]
