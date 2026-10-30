"""The HTTP API of the to-do application server (FastAPI).

Every task change still goes through TaskService, so the history is written
exactly as in the desktop program; the difference is that the user recorded in
the history is the one logged in, not one picked from a list.
"""

# No "from __future__ import annotations" here: FastAPI must see the real types
# of the dependency aliases defined inside create_app().
import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from todo_db.api_data import (
    change_data, public_user_data, repeat_rule_data, tag_data, task_data, workflow_data,
)
from todo_db.compression import compress_old_history, compress_task_history
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.models import (
    ApiToken,
    RepeatRule,
    SubtaskTemplate,
    Tag,
    Task,
    TaskChange,
    User,
    UserRole,
    Stage,
    Workflow,
    utcnow,
)
from todo_db.seed import add_missing_repeat_rules, seed
from todo_db.services import TaskService
from todo_db import management, templates

from . import dbadmin
from .maintenance import run_maintenance, scheduler
from .schemas import (
    ChangeOut,
    CompressAllIn,
    CompressionOut,
    CompressTaskIn,
    HistoryQuery,
    LoginIn,
    NameIn,
    PublicUserOut,
    RepeatRuleOut,
    SettingsIO,
    StageMove,
    StageUpdate,
    SubtaskTemplateIn,
    SubtaskTemplateOut,
    SubtaskTemplateUpdate,
    TagOut,
    TagUsageOut,
    TaskCreate,
    TaskMove,
    TaskOut,
    TaskUpdate,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
    WorkflowOut,
)
from .security import LoginLimiter, hash_password, new_token, token_hash, verify_password


@dataclass
class ServerConfig:
    """Where the server keeps its data and how it behaves."""

    db_path: Path = Path("todo_server.db")
    backup_dir: Path | None = None  # default: "backups" next to the database
    token_days: int = 30  # how long a login stays valid
    run_scheduler: bool = True  # nightly maintenance; tests switch it off
    login_limiter: LoginLimiter = field(default_factory=LoginLimiter)

    @property
    def backups(self) -> Path:
        return self.backup_dir or self.db_path.parent / "backups"


def open_database(db_path: Path) -> Any:
    """Engine for the server: usable from several threads, waits when the file is busy."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30}
    )
    create_all(engine)
    with make_session_factory(engine)() as session:
        if session.scalars(select(Workflow)).first() is None:
            seed(session, with_tasks=False, with_users=False)
        add_missing_repeat_rules(session)
    return engine


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Build the application (one per database)."""
    config = config or ServerConfig()
    engine = open_database(config.db_path)
    session_factory = make_session_factory(engine)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        job = asyncio.create_task(scheduler(session_factory)) if config.run_scheduler else None
        yield
        if job:
            job.cancel()
        engine.dispose()

    app = FastAPI(title="To-do application server", lifespan=lifespan)
    app.state.config = config
    app.state.engine = engine

    # -- dependencies -----------------------------------------------------------

    def get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    Db = Annotated[Session, Depends(get_db)]

    def current_token(db: Db, authorization: Annotated[str | None, Header()] = None) -> ApiToken:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "Not logged in", headers={"WWW-Authenticate": "Bearer"})
        row = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash(token)))
        if (
            row is None
            or row.revoked_at is not None
            or row.expires_at <= utcnow()
            or not row.user.is_active
        ):
            raise HTTPException(401, "Login expired", headers={"WWW-Authenticate": "Bearer"})
        return row

    def current_user(token: Annotated[ApiToken, Depends(current_token)]) -> User:
        return token.user

    def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role is not UserRole.Admin:
            raise HTTPException(403, "Administrators only")
        return user

    Me = Annotated[User, Depends(current_user)]
    Admin = Annotated[User, Depends(admin_user)]

    # -- helpers ----------------------------------------------------------------

    def get_task(db: Session, task_id: int) -> Task:
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(404, f"Task {task_id} does not exist")
        return task

    def task_out(service: TaskService, task: Task) -> TaskOut:
        return TaskOut(**task_data(service, task))

    def user_out(user: User) -> UserOut:
        return UserOut(
            id=user.id, name=user.name, email=user.email, is_active=user.is_active, role=user.role
        )

    def write(action: Any) -> Any:
        """Run a service call; its errors become 400 (bad input) or 409 (conflict)."""
        try:
            return action()
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except IntegrityError as error:
            raise HTTPException(409, "Conflicts with existing data") from error

    # -- auth -------------------------------------------------------------------

    @app.post("/auth/login")
    def login(body: LoginIn, request: Request, db: Db) -> TokenOut:
        """Log in with email and password; returns a token for the Authorization header."""
        key = f"{body.email.strip().lower()}|{request.client.host if request.client else ''}"
        if config.login_limiter.blocked(key):
            raise HTTPException(429, "Too many failed logins, try again later")
        user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
        if (
            not verify_password(body.password, user.password_hash if user else None)
            or user is None
            or not user.is_active
        ):
            config.login_limiter.failed(key)
            raise HTTPException(401, "Wrong email or password")
        config.login_limiter.succeeded(key)
        token = new_token()
        row = ApiToken(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=utcnow() + timedelta(days=config.token_days),
        )
        db.add(row)
        db.commit()
        return TokenOut(token=token, expires_at=row.expires_at, user=user_out(user))

    @app.post("/auth/logout", status_code=204)
    def logout(token: Annotated[ApiToken, Depends(current_token)], db: Db) -> Response:
        """End this login; the token stops working at once."""
        token.revoked_at = utcnow()
        db.commit()
        return Response(status_code=204)

    @app.get("/auth/me")
    def me(user: Me) -> UserOut:
        return user_out(user)

    # -- reference data -----------------------------------------------------------

    @app.get("/users")
    def list_users(_: Me, db: Db) -> list[PublicUserOut]:
        users = db.scalars(select(User).order_by(User.name))
        return [PublicUserOut(**public_user_data(u)) for u in users]

    @app.get("/workflows")
    def list_workflows(_: Me, db: Db) -> list[WorkflowOut]:
        return [
            WorkflowOut(**workflow_data(workflow))
            for workflow in db.scalars(select(Workflow).order_by(Workflow.name))
        ]

    @app.get("/tags")
    def list_tags(_: Me, db: Db) -> list[TagOut]:
        return [TagOut(**tag_data(t)) for t in db.scalars(select(Tag).order_by(Tag.name))]

    @app.get("/repeat-rules")
    def list_repeat_rules(_: Me, db: Db) -> list[RepeatRuleOut]:
        return [
            RepeatRuleOut(**repeat_rule_data(r))
            for r in db.scalars(select(RepeatRule).order_by(RepeatRule.id))
        ]

    # -- workflows, stages and tags (shared by everyone; any user may change them) ----

    def get_item(db: Session, model: type, item_id: int) -> Any:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(404, f"{model.__name__} {item_id} does not exist")
        return item

    def workflow_out(workflow: Workflow) -> WorkflowOut:
        return WorkflowOut(**workflow_data(workflow))

    @app.post("/workflows", status_code=201)
    def add_workflow(body: NameIn, _: Me, db: Db) -> WorkflowOut:
        return workflow_out(write(lambda: management.add_workflow(db, body.name)))

    @app.patch("/workflows/{workflow_id}")
    def rename_workflow(workflow_id: int, body: NameIn, _: Me, db: Db) -> WorkflowOut:
        get_item(db, Workflow, workflow_id)
        return workflow_out(write(lambda: management.rename_workflow(db, workflow_id, body.name)))

    @app.delete("/workflows/{workflow_id}", status_code=204)
    def delete_workflow(workflow_id: int, _: Me, db: Db) -> Response:
        get_item(db, Workflow, workflow_id)
        write(lambda: management.delete_workflow(db, workflow_id))
        return Response(status_code=204)

    @app.post("/workflows/{workflow_id}/stages", status_code=201)
    def add_stage(workflow_id: int, body: NameIn, _: Me, db: Db) -> WorkflowOut:
        get_item(db, Workflow, workflow_id)
        stage = write(lambda: management.add_stage(db, workflow_id, body.name))
        return workflow_out(stage.workflow)

    @app.patch("/stages/{stage_id}")
    def update_stage(stage_id: int, body: StageUpdate, _: Me, db: Db) -> WorkflowOut:
        stage: Stage = get_item(db, Stage, stage_id)
        if body.name is not None:
            write(lambda: management.rename_stage(db, stage_id, body.name))
        if body.is_final is not None:
            write(lambda: management.set_stage_final(db, stage_id, body.is_final))
        return workflow_out(stage.workflow)

    @app.post("/stages/{stage_id}/move")
    def move_stage(stage_id: int, body: StageMove, _: Me, db: Db) -> WorkflowOut:
        get_item(db, Stage, stage_id)
        return workflow_out(write(lambda: management.shift_stage(db, stage_id, body.delta)).workflow)

    @app.delete("/stages/{stage_id}", status_code=204)
    def delete_stage(stage_id: int, _: Me, db: Db) -> Response:
        get_item(db, Stage, stage_id)
        write(lambda: management.delete_stage(db, stage_id))
        return Response(status_code=204)

    @app.get("/tags/usage")
    def tag_usage(_: Me, db: Db) -> list[TagUsageOut]:
        return [TagUsageOut(**tag_data(tag), tasks=used) for tag, used in management.tag_usage(db)]

    @app.post("/tags", status_code=201)
    def add_tag(body: NameIn, _: Me, db: Db) -> TagOut:
        return TagOut(**tag_data(write(lambda: management.add_tag(db, body.name))))

    @app.patch("/tags/{tag_id}")
    def rename_tag(tag_id: int, body: NameIn, _: Me, db: Db) -> TagOut:
        get_item(db, Tag, tag_id)
        return TagOut(**tag_data(write(lambda: management.rename_tag(db, tag_id, body.name))))

    @app.delete("/tags/{tag_id}", status_code=204)
    def delete_tag(tag_id: int, _: Me, db: Db) -> Response:
        get_item(db, Tag, tag_id)
        write(lambda: management.delete_tag(db, tag_id))
        return Response(status_code=204)

    # -- subtask templates (shared by everyone; any user may change them) -----------

    def get_template(db: Session, template_id: int) -> None:
        if db.get(SubtaskTemplate, template_id) is None:
            raise HTTPException(404, f"Template {template_id} does not exist")

    @app.get("/subtask-templates")
    def list_templates(_: Me, db: Db) -> list[SubtaskTemplateOut]:
        return [
            SubtaskTemplateOut(**templates.template_data(t)) for t in templates.list_templates(db)
        ]

    @app.post("/subtask-templates", status_code=201)
    def add_template(body: SubtaskTemplateIn, _: Me, db: Db) -> SubtaskTemplateOut:
        template = write(lambda: templates.add_template(db, body.model_dump()))
        return SubtaskTemplateOut(**templates.template_data(template))

    @app.patch("/subtask-templates/{template_id}")
    def update_template(
        template_id: int, body: SubtaskTemplateUpdate, _: Me, db: Db
    ) -> SubtaskTemplateOut:
        get_template(db, template_id)
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"] is None:
            raise HTTPException(400, "name cannot be empty")
        template = write(lambda: templates.update_template(db, template_id, fields))
        return SubtaskTemplateOut(**templates.template_data(template))

    @app.delete("/subtask-templates/{template_id}", status_code=204)
    def delete_template(template_id: int, _: Me, db: Db) -> Response:
        get_template(db, template_id)
        write(lambda: templates.delete_template(db, template_id))
        return Response(status_code=204)

    # -- tasks ------------------------------------------------------------------

    @app.get("/tasks")
    def list_tasks(
        _: Me, db: Db, done: bool | None = None, assignee_id: int | None = None
    ) -> list[TaskOut]:
        """All tasks, parents before children, in their manual order."""
        service = TaskService(db)
        tasks = db.scalars(select(Task).order_by(Task.parent_id.is_not(None), Task.order))
        return [
            task_out(service, task)
            for task in tasks
            if (done is None or task.stage.is_final == done)
            and (assignee_id is None or task.assignee_id == assignee_id)
        ]

    @app.get("/tasks/{task_id}")
    def read_task(task_id: int, _: Me, db: Db) -> TaskOut:
        return task_out(TaskService(db), get_task(db, task_id))

    @app.post("/tasks", status_code=201)
    def create_task(body: TaskCreate, user: Me, db: Db) -> TaskOut:
        service = TaskService(db)
        fields = body.model_dump()
        if "assignee_id" not in body.model_fields_set:
            fields["assignee_id"] = user.id  # not given: assigned to whoever adds it
        task = write(
            lambda: service.create_task(fields.pop("name"), fields.pop("stage_id"), user.id, **fields)
        )
        return task_out(service, task)

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: int, body: TaskUpdate, user: Me, db: Db) -> TaskOut:
        """Change the fields sent; the history gets one row per real change."""
        get_task(db, task_id)
        service = TaskService(db)
        fields = body.model_dump(exclude_unset=True)
        if fields.get("name", "") is None or ("stage_id" in fields and fields["stage_id"] is None):
            raise HTTPException(400, "name and stage_id cannot be empty")
        task = write(lambda: service.update_task(task_id, user.id, **fields))
        return task_out(service, task)

    @app.post("/tasks/{task_id}/move")
    def move_task(task_id: int, body: TaskMove, user: Me, db: Db) -> TaskOut:
        get_task(db, task_id)
        service = TaskService(db)
        task = write(lambda: service.move_task(task_id, body.parent_id, body.order, user.id))
        return task_out(service, task)

    @app.delete("/tasks/{task_id}", status_code=204)
    def delete_task(task_id: int, user: Me, db: Db) -> Response:
        get_task(db, task_id)
        write(lambda: TaskService(db).delete_task(task_id, user.id))
        return Response(status_code=204)

    @app.post("/tasks/history")
    def tasks_history(body: HistoryQuery, _: Me, db: Db) -> list[ChangeOut]:
        """The changes of several tasks together, oldest first."""
        return [ChangeOut(**change_data(c)) for c in TaskService(db).get_histories(body.task_ids)]

    @app.get("/tasks/{task_id}/history")
    def task_history(task_id: int, _: Me, db: Db) -> list[ChangeOut]:
        """Oldest first; also works for deleted tasks."""
        return [ChangeOut(**change_data(c)) for c in TaskService(db).get_history(task_id)]

    # -- administration: users ----------------------------------------------------

    def active_admins(db: Session) -> int:
        query = select(func.count()).select_from(User).where(
            User.is_active, User.role == UserRole.Admin
        )
        return db.scalar(query) or 0

    @app.get("/admin/users")
    def admin_list_users(_: Admin, db: Db) -> list[UserOut]:
        return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]

    @app.post("/admin/users", status_code=201)
    def admin_create_user(body: UserCreate, _: Admin, db: Db) -> UserOut:
        user = User(
            name=body.name,
            email=body.email.strip(),
            role=body.role,
            password_hash=hash_password(body.password) if body.password else None,
        )
        db.add(user)
        write(db.commit)
        return user_out(user)

    @app.patch("/admin/users/{user_id}")
    def admin_update_user(user_id: int, body: UserUpdate, admin: Admin, db: Db) -> UserOut:
        """Change a user. Deactivating, demoting or a new password ends their logins."""
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(404, f"User {user_id} does not exist")
        fields = body.model_dump(exclude_unset=True)
        losing_admin = user.role is UserRole.Admin and user.is_active and (
            fields.get("role", UserRole.Admin) is not UserRole.Admin
            or fields.get("is_active", True) is False
        )
        if losing_admin and active_admins(db) == 1:
            raise HTTPException(400, "At least one active administrator must remain")
        for name in ("name", "email", "role", "is_active"):
            if fields.get(name) is not None:
                setattr(user, name, fields[name])
        if fields.get("password"):
            user.password_hash = hash_password(fields["password"])
        if fields.get("password") or fields.get("is_active") is False or losing_admin:
            for token in db.scalars(
                select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
            ):
                token.revoked_at = utcnow()
        write(db.commit)
        return user_out(user)

    # -- administration: compression ------------------------------------------------

    @app.get("/admin/settings")
    def read_settings(_: Admin, db: Db) -> SettingsIO:
        return SettingsIO(**asdict(dbadmin.load_settings(db)))

    @app.put("/admin/settings")
    def write_settings(body: SettingsIO, _: Admin, db: Db) -> SettingsIO:
        """Switch automatic compression on/off and set its age limit in days."""
        dbadmin.save_settings(db, dbadmin.ServerSettings(**body.model_dump()))
        return body

    @app.post("/admin/history/compress")
    def compress_all(body: CompressAllIn, _: Admin, db: Db) -> CompressionOut:
        """Compress now, for every task, all history older than the given number of days."""
        days = body.older_than_days
        if days is None:
            days = dbadmin.load_settings(db).compress_after_days
        return CompressionOut(**asdict(compress_old_history(db, days)))

    @app.post("/admin/tasks/{task_id}/history/compress")
    def compress_one(task_id: int, body: CompressTaskIn, _: Admin, db: Db) -> CompressionOut:
        """Compress one task's history (all of it, or only rows older than N days) into one row.

        Also works for a deleted task, as long as it has history.
        """
        history = select(func.count()).select_from(TaskChange).where(TaskChange.task_id == task_id)
        if db.scalar(history) == 0:
            raise HTTPException(404, f"Task {task_id} has no history")
        older_than = None
        if body.older_than_days is not None:
            older_than = utcnow() - timedelta(days=body.older_than_days)
        removed = compress_task_history(db, task_id, older_than=older_than)
        db.commit()
        return CompressionOut(tasks=1 if removed else 0, rows_removed=removed)

    @app.post("/admin/maintenance/run")
    def maintenance_now(_: Admin) -> dict[str, Any]:
        """Run the nightly jobs now (repeat resets, automatic compression if enabled)."""
        return run_maintenance(session_factory)

    # -- administration: database --------------------------------------------------

    @app.get("/admin/database")
    def database_info(_: Admin, db: Db) -> dict[str, Any]:
        return dbadmin.statistics(db, config.db_path)

    @app.post("/admin/database/backup", status_code=201)
    def make_backup(_: Admin) -> dict[str, Any]:
        path = dbadmin.backup(config.db_path, config.backups)
        return {"name": path.name, "size_bytes": path.stat().st_size}

    @app.get("/admin/database/backups")
    def backups(_: Admin) -> list[dict[str, Any]]:
        return dbadmin.list_backups(config.backups)

    @app.get("/admin/database/backups/{name}")
    def download_backup(name: str, _: Admin) -> FileResponse:
        path = dbadmin.backup_file(config.backups, name)
        if path is None:
            raise HTTPException(404, "No such backup")
        return FileResponse(path, media_type="application/vnd.sqlite3", filename=name)

    @app.post("/admin/database/vacuum")
    def vacuum(_: Admin) -> dict[str, int]:
        """Shrink the database file, e.g. after compression removed many rows."""
        return dbadmin.vacuum(engine, config.db_path)

    return app
