"""The phone app without a server: tasks in a database file on the phone itself.

LocalApi answers the same requests as the application server (the subset the
app uses) and returns the same data (todo_db.api_data), using the same task
logic as the desktop program (todo_db.services). So the app's screens work
unchanged; only where the data lives differs. These tasks are separate from
the server's and from the computer's todo.db – nothing is synchronised.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from todo_db.api_data import (
    change_data, public_user_data, repeat_rule_data, tag_data, task_data, workflow_data,
)
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.i18n import tr
from todo_db.models import Priority, RepeatRule, Tag, Task, Urgency, User, Workflow
from todo_db.seed import add_missing_repeat_rules, seed
from todo_db.services import TaskService

from .api import RemoteError

LOCAL_USER = "Me"  # the name of the phone's only user (translated when it is created)


def _json(data: Any) -> Any:
    """The data as it would arrive from the server: dates and times as ISO text."""
    return json.loads(json.dumps(data, default=lambda value: value.isoformat()))


def _task_fields(body: dict[str, Any]) -> dict[str, Any]:
    """Request fields converted to what TaskService takes (as the server's schemas do)."""
    fields = dict(body)
    if fields.get("priority") is not None:
        fields["priority"] = Priority[fields["priority"]]
    if fields.get("urgency") is not None:
        fields["urgency"] = Urgency[fields["urgency"]]
    if fields.get("due_date"):
        fields["due_date"] = date.fromisoformat(fields["due_date"])
    return fields


class LocalApi:
    """Works like todo_mobile.api.Api, but on a database file instead of a server."""

    base_url = ""
    token = None

    def __init__(self, path: Path) -> None:
        self.path = path
        engine = self._engine = make_engine(f"sqlite:///{path}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            create_all(engine)
        except (OSError, SQLAlchemyError) as error:  # not a database, or no access there
            engine.dispose()
            reason = getattr(error, "orig", None) or error
            raise RemoteError(
                tr("Cannot open the database {path}.").format(path=path) + f" ({reason})"
            ) from error
        self._sessions = make_session_factory(engine)
        self._lock = threading.Lock()  # the app sends requests from background threads
        with self._sessions() as session:
            if session.scalars(select(Workflow)).first() is None:
                seed(session, with_tasks=False, with_users=False)
            add_missing_repeat_rules(session)
            user = session.scalars(select(User).order_by(User.id)).first()
            if user is None:
                user = User(name=tr(LOCAL_USER))
                session.add(user)
            session.commit()
            self.user = {"id": user.id, "name": user.name, "email": None,
                         "is_active": True, "role": user.role.value}

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Answer one request like the server would; RemoteError if it is refused."""
        with self._lock, self._sessions() as session:
            try:
                return _json(self._answer(session, method, path, body or {}))
            except IntegrityError as error:  # e.g. a stage or user that no longer exists
                session.rollback()
                raise RemoteError(tr("Conflicts with existing data")) from error
            except (ValueError, KeyError) as error:
                session.rollback()
                if isinstance(error, RemoteError):
                    raise
                raise RemoteError(tr(str(error).strip("'"))) from error

    def _answer(self, session: Session, method: str, path: str, body: dict[str, Any]) -> Any:
        service = TaskService(session)
        user_id = self.user["id"]
        if (method, path) == ("GET", "/auth/me"):
            return self.user
        if (method, path) == ("GET", "/users"):
            return [public_user_data(u) for u in session.scalars(select(User).order_by(User.name))]
        if (method, path) == ("GET", "/workflows"):
            return [workflow_data(w) for w in session.scalars(select(Workflow).order_by(Workflow.name))]
        if (method, path) == ("GET", "/tags"):
            return [tag_data(t) for t in session.scalars(select(Tag).order_by(Tag.name))]
        if (method, path) == ("GET", "/repeat-rules"):
            return [repeat_rule_data(r)
                    for r in session.scalars(select(RepeatRule).order_by(RepeatRule.id))]
        if (method, path) == ("GET", "/tasks"):
            # The server does this at midnight; here whenever the list is loaded.
            service.reset_due_tasks()
            tasks = session.scalars(select(Task).order_by(Task.parent_id.is_not(None), Task.order))
            return [task_data(service, task) for task in tasks]
        if (method, path) == ("POST", "/tasks"):
            fields = _task_fields(body)
            fields.setdefault("assignee_id", user_id)  # not given: assigned to whoever adds it
            task = service.create_task(fields.pop("name"), fields.pop("stage_id"), user_id, **fields)
            return task_data(service, task)

        match = re.fullmatch(r"/tasks/(\d+)(/history)?", path)
        if match is None:
            raise RemoteError(tr("Server error {code}").format(code=404))
        task_id = int(match.group(1))
        if match.group(2):
            if method == "GET":
                return [change_data(c) for c in service.get_history(task_id)]
        elif session.get(Task, task_id) is None:
            raise RemoteError(f"Task {task_id} does not exist")
        elif method == "GET":
            return task_data(service, session.get(Task, task_id))
        elif method == "PATCH":
            fields = _task_fields(body)
            if fields.get("name", "") is None or ("stage_id" in fields and fields["stage_id"] is None):
                raise RemoteError("name and stage_id cannot be empty")
            return task_data(service, service.update_task(task_id, user_id, **fields))
        elif method == "DELETE":
            service.delete_task(task_id, user_id)
            return None
        raise RemoteError(tr("Server error {code}").format(code=405))

    def load_all(self) -> dict[str, Any]:
        """Everything the task list needs, in one go."""
        return {
            "users": self.request("GET", "/users"),
            "workflows": self.request("GET", "/workflows"),
            "repeat_rules": self.request("GET", "/repeat-rules"),
            "tags": self.request("GET", "/tags"),
            "tasks": self.request("GET", "/tasks"),
        }

    def logout(self) -> None:
        """Nothing to end: there is no login."""

    def close(self) -> None:
        """Let go of the file (before it is copied, or another one is used)."""
        with self._lock:
            self._engine.dispose()

