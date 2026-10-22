"""The application server: logins, tasks over HTTP, compression and database management."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from todo_db.database import make_session_factory  # noqa: E402
from todo_db.models import TaskChange, User, UserRole, utcnow  # noqa: E402
from todo_server.api import ServerConfig, create_app  # noqa: E402
from todo_server.security import LoginLimiter, hash_password, verify_password  # noqa: E402

PASSWORD = "correct horse"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    config = ServerConfig(db_path=tmp_path / "server.db", run_scheduler=False)
    app = create_app(config)
    with make_session_factory(app.state.engine)() as session:
        session.add_all([
            User(name="Admin", email="admin@example.com", role=UserRole.Admin,
                 password_hash=hash_password(PASSWORD)),
            User(name="Ola", email="ola@example.com", password_hash=hash_password(PASSWORD)),
        ])
        session.commit()
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return login(client, "admin@example.com")


@pytest.fixture
def ola(client: TestClient) -> dict[str, str]:
    return login(client, "ola@example.com")


def first_stage(client: TestClient, auth: dict[str, str], workflow: str = "Software") -> int:
    workflows = client.get("/workflows", headers=auth).json()
    return next(w for w in workflows if w["name"] == workflow)["stages"][0]["id"]


# -- passwords and logins ---------------------------------------------------------


def test_password_hashing() -> None:
    stored = hash_password(PASSWORD)
    assert PASSWORD not in stored
    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong password", stored)
    assert not verify_password(PASSWORD, None)
    assert hash_password(PASSWORD) != stored  # salted


def test_login_logout_and_me(client: TestClient) -> None:
    auth = login(client, "OLA@example.com ")  # email is not case-sensitive
    assert client.get("/auth/me", headers=auth).json()["name"] == "Ola"

    assert client.post("/auth/logout", headers=auth).status_code == 204
    assert client.get("/auth/me", headers=auth).status_code == 401


def test_requests_need_a_valid_token(client: TestClient) -> None:
    assert client.get("/tasks").status_code == 401
    assert client.get("/tasks", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_wrong_password_and_lockout(client: TestClient) -> None:
    client.app.state.config.login_limiter = LoginLimiter(max_failures=3)
    for _ in range(3):
        bad = client.post("/auth/login", json={"email": "ola@example.com", "password": "nope"})
        assert bad.status_code == 401
    blocked = client.post("/auth/login", json={"email": "ola@example.com", "password": PASSWORD})
    assert blocked.status_code == 429


def test_unknown_user_gets_the_same_answer(client: TestClient) -> None:
    response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert (response.status_code, response.json()["detail"]) == (401, "Wrong email or password")


def test_expired_login(client: TestClient, ola: dict[str, str]) -> None:
    from todo_db.models import ApiToken

    with make_session_factory(client.app.state.engine)() as session:
        session.execute(update(ApiToken).values(expires_at=utcnow() - timedelta(seconds=1)))
        session.commit()
    assert client.get("/auth/me", headers=ola).status_code == 401


def test_admin_only_endpoints(client: TestClient, ola: dict[str, str]) -> None:
    settings = {"auto_compress_enabled": True, "compress_after_days": 1}
    for method, path, body in [
        ("GET", "/admin/users", None),
        ("GET", "/admin/database", None),
        ("POST", "/admin/database/backup", None),
        ("PUT", "/admin/settings", settings),
        ("POST", "/admin/history/compress", {}),
        ("POST", "/admin/tasks/1/history/compress", {}),
        ("POST", "/admin/maintenance/run", None),
    ]:
        assert client.request(method, path, headers=ola, json=body).status_code == 403, path


# -- tasks ------------------------------------------------------------------------


def test_task_lifecycle_records_the_logged_in_user(
    client: TestClient, ola: dict[str, str]
) -> None:
    stage = first_stage(client, ola)
    created = client.post(
        "/tasks", headers=ola,
        json={"name": "Report", "stage_id": stage, "priority": "Important", "urgency": 2},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert (task["priority"], task["urgency"], task["stage"]) == ("Important", "High", "Idea")

    changed = client.patch(f"/tasks/{task['id']}", headers=ola,
                           json={"name": "Final report", "description": None})
    assert changed.json()["name"] == "Final report"

    history = client.get(f"/tasks/{task['id']}/history", headers=ola).json()
    assert [(h["change_type"], h["field_name"], h["changed_by"]) for h in history] == [
        ("Created", None, "Ola"), ("Updated", "Name", "Ola"),
    ]

    assert client.delete(f"/tasks/{task['id']}", headers=ola).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=ola).status_code == 404
    assert client.get(f"/tasks/{task['id']}/history", headers=ola).json()[-1]["change_type"] == "Deleted"


def test_task_errors(client: TestClient, ola: dict[str, str]) -> None:
    stage = first_stage(client, ola)
    parent = client.post("/tasks", headers=ola, json={"name": "Parent", "stage_id": stage}).json()
    client.post("/tasks", headers=ola, json={"name": "Child", "stage_id": stage, "parent_id": parent["id"]})

    assert client.patch("/tasks/999", headers=ola, json={"name": "x"}).status_code == 404
    assert client.patch(f"/tasks/{parent['id']}", headers=ola, json={"stage_id": 999}).status_code == 400
    assert client.patch(f"/tasks/{parent['id']}", headers=ola, json={"name": None}).status_code == 400
    assert client.post("/tasks", headers=ola, json={"name": "", "stage_id": stage}).status_code == 422
    refused = client.delete(f"/tasks/{parent['id']}", headers=ola)
    assert (refused.status_code, "subtasks" in refused.json()["detail"]) == (400, True)
    cycle = client.post(f"/tasks/{parent['id']}/move", headers=ola, json={"parent_id": parent["id"]})
    assert cycle.status_code == 400


# -- users ------------------------------------------------------------------------


def test_admin_manages_users(client: TestClient, admin: dict[str, str]) -> None:
    created = client.post("/admin/users", headers=admin,
                          json={"name": "Jan", "email": "jan@example.com", "password": PASSWORD})
    assert created.status_code == 201
    jan = login(client, "jan@example.com")

    duplicate = client.post("/admin/users", headers=admin, json={"name": "X", "email": "jan@example.com"})
    assert duplicate.status_code == 409
    short = client.post("/admin/users", headers=admin,
                        json={"name": "Y", "email": "y@example.com", "password": "short"})
    assert short.status_code == 422

    client.patch(f"/admin/users/{created.json()['id']}", headers=admin, json={"is_active": False})
    assert client.get("/auth/me", headers=jan).status_code == 401  # logged out at once
    again = client.post("/auth/login", json={"email": "jan@example.com", "password": PASSWORD})
    assert again.status_code == 401


def test_last_admin_cannot_be_removed(client: TestClient, admin: dict[str, str]) -> None:
    me = client.get("/auth/me", headers=admin).json()
    for change in ({"is_active": False}, {"role": "User"}):
        response = client.patch(f"/admin/users/{me['id']}", headers=admin, json=change)
        assert response.status_code == 400


# -- compression and maintenance ---------------------------------------------------


def make_history(client: TestClient, auth: dict[str, str], name: str) -> int:
    stage = first_stage(client, auth)
    task = client.post("/tasks", headers=auth, json={"name": name, "stage_id": stage}).json()
    for new_name in ("Second", "Third", name + " final"):
        client.patch(f"/tasks/{task['id']}", headers=auth, json={"name": new_name})
    return task["id"]


def age_history(client: TestClient, days: int) -> None:
    """Pretend every history row was written `days` days ago."""
    with make_session_factory(client.app.state.engine)() as session:
        session.execute(update(TaskChange).values(changed_at=utcnow() - timedelta(days=days)))
        session.commit()


def test_manual_compression_of_one_task(client: TestClient, admin: dict[str, str]) -> None:
    task_id = make_history(client, admin, "Plan")
    other = make_history(client, admin, "Other")

    result = client.post(f"/admin/tasks/{task_id}/history/compress", headers=admin, json={})
    assert result.json() == {"tasks": 1, "rows_removed": 3}

    (row,) = client.get(f"/tasks/{task_id}/history", headers=admin).json()
    assert row["change_type"] == "Compressed"
    assert row["summary"]["count"] == 4
    assert row["summary"]["fields"] == {"Name": ["Plan", "Plan final"]}
    assert len(client.get(f"/tasks/{other}/history", headers=admin).json()) == 4  # untouched
    missing = client.post("/admin/tasks/999/history/compress", headers=admin, json={})
    assert missing.status_code == 404


def test_compress_all_older_than(client: TestClient, admin: dict[str, str]) -> None:
    old = make_history(client, admin, "Old")
    age_history(client, 40)
    new = make_history(client, admin, "New")

    result = client.post("/admin/history/compress", headers=admin, json={"older_than_days": 30})

    assert result.json() == {"tasks": 1, "rows_removed": 3}
    assert len(client.get(f"/tasks/{old}/history", headers=admin).json()) == 1
    assert len(client.get(f"/tasks/{new}/history", headers=admin).json()) == 4


def test_automatic_compression_follows_the_settings(
    client: TestClient, admin: dict[str, str]
) -> None:
    task_id = make_history(client, admin, "Task")
    age_history(client, 10)

    off = client.post("/admin/maintenance/run", headers=admin).json()
    assert off["compression"] is None  # off by default
    assert len(client.get(f"/tasks/{task_id}/history", headers=admin).json()) == 4

    settings = {"auto_compress_enabled": True, "compress_after_days": 7}
    assert client.put("/admin/settings", headers=admin, json=settings).json() == settings
    assert client.get("/admin/settings", headers=admin).json() == settings

    on = client.post("/admin/maintenance/run", headers=admin).json()
    assert on["compression"] == {"older_than_days": 7, "tasks": 1, "rows_removed": 3}
    assert len(client.get(f"/tasks/{task_id}/history", headers=admin).json()) == 1
    info = client.get("/admin/database", headers=admin).json()
    assert info["last_maintenance"]["ran_at"] == on["ran_at"]
    assert info["compressed_rows"] == 1


# -- database management -----------------------------------------------------------


def test_database_info_backup_and_vacuum(client: TestClient, admin: dict[str, str]) -> None:
    make_history(client, admin, "Data")
    info = client.get("/admin/database", headers=admin).json()
    assert (info["users"], info["tasks"], info["history_rows"], info["active_logins"]) == (2, 1, 4, 1)

    made = client.post("/admin/database/backup", headers=admin)
    assert made.status_code == 201
    name = made.json()["name"]
    assert [b["name"] for b in client.get("/admin/database/backups", headers=admin).json()] == [name]
    download = client.get(f"/admin/database/backups/{name}", headers=admin)
    assert download.status_code == 200 and download.content.startswith(b"SQLite format 3")
    assert client.get("/admin/database/backups/..%2Fserver.db", headers=admin).status_code == 404

    sizes = client.post("/admin/database/vacuum", headers=admin).json()
    assert sizes["size_after"] <= sizes["size_before"]


def test_repeating_task_reset_by_maintenance(client: TestClient, ola: dict[str, str],
                                             admin: dict[str, str]) -> None:
    rules = client.get("/repeat-rules", headers=ola).json()
    daily = next(r for r in rules if r["name"] == "Daily")
    workflows = client.get("/workflows", headers=ola).json()
    simple = next(w for w in workflows if w["name"] == "Simple")
    todo, done = (s["id"] for s in simple["stages"])
    task = client.post("/tasks", headers=ola,
                       json={"name": "Water plants", "stage_id": todo, "repeat_rule_id": daily["id"]}).json()

    done_task = client.patch(f"/tasks/{task['id']}", headers=ola, json={"stage_id": done}).json()
    assert done_task["done"] and done_task["next_reset_at"] is not None

    from datetime import datetime
    from todo_server.maintenance import run_maintenance
    due = datetime.fromisoformat(done_task["next_reset_at"])
    report = run_maintenance(make_session_factory(client.app.state.engine), now=due)
    assert report["reset_tasks"] == 1
    assert client.get(f"/tasks/{task['id']}", headers=ola).json()["stage"] == "To do"
