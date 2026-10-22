"""Shared fixtures: an in-memory database with a little reference data."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session

from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.models import RepeatRule, RepeatUnit, Stage, Tag, User, Workflow
from todo_db.services import TaskService


@dataclass
class World:
    """Ids of the reference rows the tests need."""

    anna: int
    piotr: int
    todo: int
    done: int
    idea: int
    planned: int
    in_progress: int
    soft_done: int
    weekly: int
    work: int
    home: int


@pytest.fixture
def session() -> Iterator[Session]:
    """A session on a fresh in-memory database."""
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def service(session: Session) -> TaskService:
    """The service under test."""
    return TaskService(session)


@pytest.fixture
def world(session: Session) -> World:
    """Two users, two workflows, one repeat rule and two tags."""
    anna = User(name="Anna Kowalska", email="anna@example.com")
    piotr = User(name="Piotr Nowak", email="piotr@example.com")
    simple = [Stage(name="To do", order=1), Stage(name="Done", order=2, is_final=True)]
    software = [
        Stage(name="Idea", order=1),
        Stage(name="Planned", order=2),
        Stage(name="In progress", order=3),
        Stage(name="Done", order=4, is_final=True),
    ]
    weekly = RepeatRule(name="Weekly", interval=1, unit=RepeatUnit.Week)
    work, home = Tag(name="work"), Tag(name="home")
    session.add_all(
        [
            anna,
            piotr,
            Workflow(name="Simple", stages=simple),
            Workflow(name="Software", stages=software),
            weekly,
            work,
            home,
        ]
    )
    session.commit()
    return World(
        anna=anna.id,
        piotr=piotr.id,
        todo=simple[0].id,
        done=simple[1].id,
        idea=software[0].id,
        planned=software[1].id,
        in_progress=software[2].id,
        soft_done=software[3].id,
        weekly=weekly.id,
        work=work.id,
        home=home.id,
    )
