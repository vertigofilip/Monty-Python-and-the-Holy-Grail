"""Working against the application server instead of the local todo.db.

The desktop program keeps reading from a SQLAlchemy session, so it works the
same in both modes. In server mode that session is an in-memory copy (the
"mirror") of the server's data, rebuilt after every change and every few
seconds; every change itself is sent to the server through its HTTP API, so
the server's TaskService writes the history with the logged-in user.
"""

from __future__ import annotations

import enum
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Base,
    ChangeType,
    Priority,
    RepeatRule,
    RepeatUnit,
    Stage,
    Tag,
    Task,
    TaskChange,
    Urgency,
    User,
    Workflow,
)
from .i18n import tr
from .services import TaskService

# Where a remembered login is kept: readable only by the owner, never in git.
LOGIN_FILE = Path("client_login.json")
TIMEOUT = 10.0


class RemoteError(ValueError):
    """The server refused a request or could not be reached (message for the user)."""


class NotLoggedIn(RemoteError):
    """The login expired or was ended on the server; the user must log in again."""


class ApiClient:
    """Thin wrapper around the server's HTTP API."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.Client(base_url=self.base_url, timeout=TIMEOUT)
        # Whether the last request reached the server (any answer); None before the first.
        self.connected: bool | None = None

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Send a request; returns the JSON answer or raises RemoteError."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = self._http.request(method, path, json=body, headers=headers)
        except httpx.HTTPError as error:
            self.connected = False
            message = tr("Cannot reach the server at {url}.").format(url=self.base_url)
            raise RemoteError(f"{message} ({error})") from error
        self.connected = True
        if response.status_code == 401 and self.token:
            raise NotLoggedIn(tr("Login expired. Please log in again."))
        if response.is_error:
            raise RemoteError(_error_message(response))
        return response.json() if response.content else None

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Log in; keeps the token and returns the server's answer (token, user...)."""
        answer = self.request("POST", "/auth/login", {"email": email, "password": password})
        self.token = answer["token"]
        return answer

    def logout(self) -> None:
        """End the login on the server; errors are ignored (we forget the token anyway)."""
        try:
            self.request("POST", "/auth/logout")
        except RemoteError:
            pass
        self.token = None

    def close(self) -> None:
        self._http.close()


def _error_message(response: httpx.Response) -> str:
    """The server's explanation of an error, as plain text."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, list):  # validation errors: [{"loc": [...], "msg": ...}, ...]
        return "; ".join(f"{item['loc'][-1]}: {item['msg']}" for item in detail)
    if detail:
        return tr(str(detail))
    return tr("Server error {code}").format(code=response.status_code)


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Mirror:
    """An in-memory copy of the server's users, workflows, tags, rules and tasks."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.session: Session = self._build()

    def sync(self) -> None:
        """Download everything again into a fresh in-memory database.

        A fresh database each time is simplest and fast for a to-do list; the
        previous session stays open (and its objects readable) for any window
        that still holds them.
        """
        self.session = self._build()

    def _build(self) -> Session:
        users = self.api.request("GET", "/users")
        workflows = self.api.request("GET", "/workflows")
        rules = self.api.request("GET", "/repeat-rules")
        tags = self.api.request("GET", "/tags")
        tasks = self.api.request("GET", "/tasks")

        engine = create_engine("sqlite://")  # no foreign keys needed: the server checks them
        Base.metadata.create_all(engine)
        session = sessionmaker(engine, expire_on_commit=False)()
        session.add_all(User(id=u["id"], name=u["name"], is_active=u["is_active"]) for u in users)
        for workflow in workflows:
            session.add(Workflow(id=workflow["id"], name=workflow["name"]))
            session.add_all(
                Stage(id=s["id"], workflow_id=workflow["id"], name=s["name"], order=s["order"],
                      is_final=s["is_final"])
                for s in workflow["stages"]
            )
        session.add_all(
            RepeatRule(id=r["id"], name=r["name"], interval=r["interval"], unit=RepeatUnit(r["unit"]))
            for r in rules
        )
        session.add_all(Tag(id=t["id"], name=t["name"]) for t in tags)
        session.flush()
        for t in tasks:
            session.add(
                Task(
                    id=t["id"],
                    name=t["name"],
                    description=t["description"],
                    stage_id=t["stage_id"],
                    priority=Priority[t["priority"]],
                    urgency=Urgency[t["urgency"]],
                    parent_id=t["parent_id"],
                    order=t["order"],
                    assignee_id=t["assignee_id"],
                    created_by_id=t["created_by_id"],
                    created_at=_when(t["created_at"]),
                    repeat_rule_id=t["repeat_rule_id"],
                    repeat_count=t["repeat_count"],
                    repeat_done=t["repeat_done"],
                    next_reset_at=_when(t["next_reset_at"]),
                    due_date=_day(t.get("due_date")),  # older servers do not send it
                    location=t.get("location"),
                    tags=[session.get(Tag, tag["id"]) for tag in t["tags"]],
                )
            )
        session.commit()
        return session


def _api_value(value: Any) -> Any:
    """Enums travel by name ("Important"), dates as "2026-10-14", everything else as is."""
    if isinstance(value, enum.Enum):
        return value.name
    return value.isoformat() if isinstance(value, date) else value


class RemoteTaskService:
    """Does what TaskService does, but on the server; the desktop program can't tell."""

    def __init__(self, account: RemoteAccount) -> None:
        self.account = account

    @property
    def _api(self) -> ApiClient:
        return self.account.api

    def _after_change(self, task_id: int | None) -> Task | None:
        self.account.mirror.sync()
        return self.account.mirror.session.get(Task, task_id) if task_id else None

    def create_task(
        self, name: str, stage_id: int, created_by_id: int, **fields: Any
    ) -> Task | None:
        """created_by_id is ignored: the server records the logged-in user."""
        body = {"name": name, "stage_id": stage_id}
        body |= {key: _api_value(value) for key, value in fields.items()}
        if "tag_ids" in body:
            body["tag_ids"] = list(body["tag_ids"])
        created = self._api.request("POST", "/tasks", body)
        return self._after_change(created["id"])

    def update_task(self, task_id: int, changed_by_id: int | None, **fields: Any) -> Task | None:
        body = {key: _api_value(value) for key, value in fields.items()}
        if "tag_ids" in body:
            body["tag_ids"] = list(body["tag_ids"])
        self._api.request("PATCH", f"/tasks/{task_id}", body)
        return self._after_change(task_id)

    def move_task(
        self, task_id: int, new_parent_id: int | None, new_order: int | None,
        changed_by_id: int | None,
    ) -> Task | None:
        self._api.request(
            "POST", f"/tasks/{task_id}/move", {"parent_id": new_parent_id, "order": new_order}
        )
        return self._after_change(task_id)

    def delete_task(self, task_id: int, changed_by_id: int | None) -> None:
        self._api.request("DELETE", f"/tasks/{task_id}")
        self._after_change(None)

    def get_history(self, task_id: int) -> list[TaskChange]:
        """The task's history from the server, as (unsaved) TaskChange objects."""
        return [
            TaskChange(
                id=row["id"],
                task_id=row["task_id"],
                changed_at=_when(row["changed_at"]),
                changed_by_id=row["changed_by_id"],
                changed_by=User(id=row["changed_by_id"], name=row["changed_by"])
                if row["changed_by"] else None,
                change_type=ChangeType[row["change_type"]],
                field_name=row["field_name"],
                old_value=row["old_value"],
                new_value=row["new_value"],
            )
            for row in self._api.request("GET", f"/tasks/{task_id}/history")
        ]

    def get_progress_percent(self, task_id: int) -> float:
        """Calculated from the mirror, exactly as the server would."""
        return TaskService(self.account.mirror.session).get_progress_percent(task_id)

    def reset_due_tasks(self, now: datetime | None = None) -> int:
        """The server resets repeating tasks itself; here we only fetch the result."""
        self.account.mirror.sync()
        return 0


@dataclass
class RemoteAccount:
    """A logged-in connection to the server."""

    api: ApiClient
    user: dict[str, Any]  # id, name, email, role, is_active
    remember: bool
    mirror: Mirror = field(init=False)

    def __post_init__(self) -> None:
        self.mirror = Mirror(self.api)

    @property
    def is_admin(self) -> bool:
        return self.user["role"] == "Admin"

    # -- users (administrators only) -------------------------------------------

    def list_users(self) -> list[dict[str, Any]]:
        return self.api.request("GET", "/admin/users")

    def create_user(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.api.request("POST", "/admin/users", fields)

    def update_user(self, user_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        return self.api.request("PATCH", f"/admin/users/{user_id}", fields)

    # -- server settings (administrators only) -----------------------------------

    def get_settings(self) -> dict[str, Any]:
        """{"auto_compress_enabled": bool, "compress_after_days": int}"""
        return self.api.request("GET", "/admin/settings")

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        return self.api.request("PUT", "/admin/settings", values)

    def logout(self) -> None:
        """End the login on the server and forget a remembered one."""
        self.api.logout()
        forget_login()
        self.api.close()


# -- remembered login ------------------------------------------------------------------


def save_login(base_url: str, token: str) -> None:
    """Remember the login for the next start, in a file only the owner can read."""
    LOGIN_FILE.write_text(json.dumps({"server_url": base_url, "token": token}), encoding="utf-8")
    os.chmod(LOGIN_FILE, 0o600)


def load_login() -> tuple[str, str] | None:
    """(server address, token) of a remembered login, or None."""
    try:
        data = json.loads(LOGIN_FILE.read_text(encoding="utf-8"))
        return data["server_url"], data["token"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def forget_login() -> None:
    LOGIN_FILE.unlink(missing_ok=True)


def resume_login() -> RemoteAccount | None:
    """Log in again with a remembered token, if it is still valid."""
    remembered = load_login()
    if remembered is None:
        return None
    api = ApiClient(*remembered)
    try:
        user = api.request("GET", "/auth/me")
        return RemoteAccount(api, user, remember=True)
    except NotLoggedIn:
        forget_login()
    except RemoteError:
        pass  # server unreachable: ask again, keep the token for later
    api.close()
    return None


def log_in(base_url: str, email: str, password: str, remember: bool) -> RemoteAccount:
    """Log in with email and password; raises RemoteError with a message for the user."""
    api = ApiClient(base_url)
    try:
        answer = api.login(email, password)
        account = RemoteAccount(api, answer["user"], remember=remember)
    except Exception:
        api.close()
        raise
    if remember:
        save_login(api.base_url, answer["token"])
    return account
