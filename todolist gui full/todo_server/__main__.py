"""Command line: run the server and manage accounts.

    python -m todo_server run [--db todo_server.db] [--host 127.0.0.1] [--port 8000]
    python -m todo_server create-admin --name "Anna Kowalska" --email anna@example.com
    python -m todo_server set-password --email anna@example.com

--db (before or after the command; default todo_server.db, or TODO_SERVER_DB)
chooses the database file; a new one is set up empty, its folder created.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from todo_db.database import make_session_factory
from todo_db.models import User, UserRole

from .api import ServerConfig, create_app, open_database
from .security import MIN_PASSWORD_LENGTH, hash_password


def ask_password() -> str:
    """Read a new password twice without showing it (or two lines piped in, for scripts)."""
    if not sys.stdin.isatty():
        password, repeated = sys.stdin.readline().rstrip("\n"), sys.stdin.readline().rstrip("\n")
        if len(password) < MIN_PASSWORD_LENGTH or password != repeated:
            raise SystemExit(f"Give the password twice, at least {MIN_PASSWORD_LENGTH} characters.")
        return password
    while True:
        password = getpass.getpass("New password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"At least {MIN_PASSWORD_LENGTH} characters, please.")
        elif password != getpass.getpass("Repeat it: "):
            print("The passwords differ, try again.")
        else:
            return password


def open_session(db_path: Path) -> Session:
    """A session on the server database (created and upgraded if needed)."""
    return make_session_factory(open_database(db_path))()


def by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def create_admin(db_path: Path, name: str, email: str) -> int:
    with open_session(db_path) as session:
        if by_email(session, email) is not None:
            print(f"{email} already exists; use set-password, or change its role via the API.")
            return 1
        password_hash = hash_password(ask_password())
        session.add(
            User(name=name, email=email.strip(), role=UserRole.Admin, password_hash=password_hash)
        )
        session.commit()
    print(f"Administrator {email} created in {db_path}.")
    return 0


def set_password(db_path: Path, email: str) -> int:
    with open_session(db_path) as session:
        user = by_email(session, email)
        if user is None:
            print(f"No user with email {email}.")
            return 1
        user.password_hash = hash_password(ask_password())
        session.commit()
    print(f"Password of {email} changed. Existing logins stay valid until they expire.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        # Installed (an executable, a Nix package) it is called by its own name.
        prog="python -m todo_server" if sys.argv[0].endswith("__main__.py") else Path(sys.argv[0]).stem,
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_db = Path(os.environ.get("TODO_SERVER_DB") or "todo_server.db")
    parser.add_argument("--db", type=Path, default=default_db,
                        help=f"database file (default: {default_db})")
    # Also accepted after the command; SUPPRESS keeps the value given before it.
    db_after = argparse.ArgumentParser(add_help=False)
    db_after.add_argument("--db", type=Path, default=argparse.SUPPRESS, help="database file")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="start the server", parents=[db_after])
    run.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this computer only")
    run.add_argument("--port", type=int, default=8000)
    run.add_argument("--token-days", type=int, default=30, help="how long a login lasts")
    admin = commands.add_parser("create-admin", help="create an administrator account",
                                parents=[db_after])
    admin.add_argument("--name", required=True)
    admin.add_argument("--email", required=True)
    password = commands.add_parser("set-password", help="set a user's password",
                                   parents=[db_after])
    password.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    args.db = args.db.expanduser()

    if args.command == "create-admin":
        return create_admin(args.db, args.name, args.email)
    if args.command == "set-password":
        return set_password(args.db, args.email)

    import uvicorn

    logging.basicConfig(level=logging.INFO)
    app = create_app(ServerConfig(db_path=args.db, token_days=args.token_days))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
