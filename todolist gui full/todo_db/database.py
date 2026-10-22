"""Engine and session setup for SQLite."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_URL = "sqlite:///todo.db"


def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    """SQLite ignores foreign keys unless asked on every connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str = DEFAULT_URL, **options: Any) -> Engine:
    """Create an engine with foreign key enforcement switched on."""
    engine = create_engine(url, **options)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to the engine."""
    return sessionmaker(engine)


def create_all(engine: Engine) -> None:
    """Create all tables that do not exist yet and upgrade older databases."""
    Base.metadata.create_all(engine)
    _upgrade(engine)


# Columns added after the first version, as (table, column): how to add them.
_NEW_COLUMNS: dict[tuple[str, str], str] = {
    ("Task", "Urgency"): 'ALTER TABLE "Task" ADD COLUMN "Urgency" INTEGER NOT NULL DEFAULT 1',
    ("Task", "NextResetAt"): 'ALTER TABLE "Task" ADD COLUMN "NextResetAt" DATETIME',
    ("Task", "DueDate"): 'ALTER TABLE "Task" ADD COLUMN "DueDate" DATE',
    ("Task", "Location"): 'ALTER TABLE "Task" ADD COLUMN "Location" VARCHAR',
    ("User", "PasswordHash"): 'ALTER TABLE "User" ADD COLUMN "PasswordHash" VARCHAR',
    ("User", "Role"): 'ALTER TABLE "User" ADD COLUMN "Role" VARCHAR(5) NOT NULL DEFAULT \'User\'',
}


def _upgrade(engine: Engine) -> None:
    """Add columns introduced after a database was first created."""
    inspector = inspect(engine)
    existing = {
        (table, column["name"])
        for table in {table for table, _ in _NEW_COLUMNS}
        for column in inspector.get_columns(table)
    }
    missing = [ddl for key, ddl in _NEW_COLUMNS.items() if key not in existing]
    if missing:
        with engine.begin() as connection:
            for ddl in missing:
                connection.execute(text(ddl))
