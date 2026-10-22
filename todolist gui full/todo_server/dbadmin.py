"""Database management: server settings, statistics, backups and VACUUM."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from todo_db.models import ApiToken, ChangeType, ServerSetting, Task, TaskChange, User, utcnow

BACKUP_NAME = re.compile(r"^todo-\d{8}-\d{6}(-\d+)?\.db$")


@dataclass
class ServerSettings:
    """Settings an administrator can change while the server runs."""

    auto_compress_enabled: bool = False  # off until an admin decides: compression is lossy
    compress_after_days: int = 90


def load_settings(session: Session) -> ServerSettings:
    """Current settings; anything never saved keeps its default."""
    saved = {row.key: json.loads(row.value) for row in session.scalars(select(ServerSetting))}
    defaults = asdict(ServerSettings())
    return ServerSettings(**{key: saved.get(key, value) for key, value in defaults.items()})


def save_settings(session: Session, settings: ServerSettings) -> None:
    """Store all settings and commit."""
    for key, value in asdict(settings).items():
        session.merge(ServerSetting(key=key, value=json.dumps(value)))
    session.commit()


def save_last_maintenance(session: Session, report: dict[str, Any]) -> None:
    """Remember what the last maintenance run did; commits."""
    session.merge(ServerSetting(key="last_maintenance", value=json.dumps(report)))
    session.commit()


def load_last_maintenance(session: Session) -> dict[str, Any] | None:
    """What the last maintenance run did, or None."""
    row = session.get(ServerSetting, "last_maintenance")
    return json.loads(row.value) if row else None


def statistics(session: Session, db_path: Path) -> dict[str, Any]:
    """Size and contents of the database."""

    def count(*where: Any, model: Any = TaskChange) -> int:
        return session.scalar(select(func.count()).select_from(model).where(*where)) or 0

    oldest = session.scalar(select(func.min(TaskChange.changed_at)))
    return {
        "file": str(db_path),
        "size_bytes": db_path.stat().st_size,
        "users": count(model=User),
        "active_users": count(User.is_active, model=User),
        "tasks": count(model=Task),
        "history_rows": count(),
        "compressed_rows": count(TaskChange.change_type == ChangeType.Compressed),
        "oldest_history": oldest.isoformat() if oldest else None,
        "active_logins": count(
            ApiToken.revoked_at.is_(None), ApiToken.expires_at > utcnow(), model=ApiToken
        ),
        "settings": asdict(load_settings(session)),
        "last_maintenance": load_last_maintenance(session),
    }


def backup(db_path: Path, backup_dir: Path) -> Path:
    """Copy the live database into backup_dir with SQLite's online backup.

    Safe while the server is working: SQLite copies a consistent snapshot.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"todo-{stamp}.db"
    number = 1
    while target.exists():
        number += 1
        target = backup_dir / f"todo-{stamp}-{number}.db"
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def list_backups(backup_dir: Path) -> list[dict[str, Any]]:
    """Backups, newest first."""
    if not backup_dir.exists():
        return []
    files = sorted(
        (path for path in backup_dir.iterdir() if BACKUP_NAME.match(path.name)), reverse=True
    )
    return [{"name": path.name, "size_bytes": path.stat().st_size} for path in files]


def backup_file(backup_dir: Path, name: str) -> Path | None:
    """The path of a backup by name, or None (names are checked, so no "../" tricks)."""
    path = backup_dir / name
    return path if BACKUP_NAME.match(name) and path.is_file() else None


def vacuum(engine: Engine, db_path: Path) -> dict[str, int]:
    """Rebuild the database file so space freed by deletes is given back."""
    before = db_path.stat().st_size
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("VACUUM")
    return {"size_before": before, "size_after": db_path.stat().st_size}
