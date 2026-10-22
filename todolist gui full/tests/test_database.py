"""Upgrading a database created before a column existed."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.models import Task, Urgency


def test_create_all_adds_urgency_to_an_old_database(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    create_all(engine)
    with engine.begin() as connection:  # turn it into a pre-urgency database
        connection.execute(text('ALTER TABLE "Task" DROP COLUMN "Urgency"'))
        connection.execute(text("""INSERT INTO "User" ("Id", "Name", "IsActive") VALUES (1, 'Anna', 1)"""))
        connection.execute(text("""INSERT INTO "Workflow" ("Id", "Name") VALUES (1, 'Simple')"""))
        connection.execute(text(
            """INSERT INTO "Stage" ("Id", "WorkflowId", "Name", "Order", "IsFinal") VALUES (1, 1, 'To do', 1, 0)"""
        ))
        connection.execute(text(
            """INSERT INTO "Task" ("Id", "Name", "StageId", "RepeatCount", "RepeatDone", "CreatedAt",
               "Priority", "Order", "CreatedById") VALUES (1, 'Old task', 1, 0, 0, '2026-01-01 00:00:00', 1, 1, 1)"""
        ))

    create_all(engine)
    create_all(engine)  # running it again changes nothing

    with make_session_factory(engine)() as session:
        assert session.get(Task, 1).urgency is Urgency.Medium


def test_create_all_adds_next_reset_at_to_an_old_database(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE "Task" DROP COLUMN "NextResetAt"'))

    create_all(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("Task")}
    assert "NextResetAt" in columns


def test_create_all_adds_due_date_and_location_to_an_old_database(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE "Task" DROP COLUMN "DueDate"'))
        connection.execute(text('ALTER TABLE "Task" DROP COLUMN "Location"'))

    create_all(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("Task")}
    assert {"DueDate", "Location"} <= columns
