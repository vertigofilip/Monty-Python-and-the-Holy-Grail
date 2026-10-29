"""Draw a random task to do next, favouring the important and urgent ones.

Shared by the desktop program and the phone app. Only unfinished tasks
without subtasks take part (a parent is done by doing its subtasks). Each one
gets a weight from its priority and urgency; the higher the weight, the more
likely it is drawn, but every candidate has a chance.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

# (priority, urgency) from the most to the least preferred: urgency first among
# the Normal and Important tasks, the Maybe tasks last.
LEVEL_ORDER = (
    ("Important", "High"),
    ("Normal", "High"),
    ("Important", "Medium"),
    ("Normal", "Medium"),
    ("Important", "Low"),
    ("Normal", "Low"),
    ("Maybe", "High"),
    ("Maybe", "Medium"),
    ("Maybe", "Low"),
)
# The weight of each place in LEVEL_ORDER: 9 for the first down to 1 for the last,
# so an "Important, High" task is 9 times as likely as a "Maybe, Low" one.
WEIGHTS = {levels: len(LEVEL_ORDER) - place for place, levels in enumerate(LEVEL_ORDER)}


def weight(priority: str, urgency: str) -> int:
    """How strongly a task with these levels (by name) is favoured; 1 if unknown."""
    return WEIGHTS.get((priority, urgency), 1)


def pick_task(
    candidates: Sequence[T], levels: Callable[[T], tuple[str, str]],
    rng: random.Random | None = None,
) -> T | None:
    """One of the candidates at random, by weight; None if there are none.

    levels(task) gives its (priority, urgency) names; the caller passes only the
    tasks that take part (unfinished, without subtasks).
    """
    if not candidates:
        return None
    weights = [weight(*levels(task)) for task in candidates]
    return (rng or random).choices(list(candidates), weights=weights)[0]
