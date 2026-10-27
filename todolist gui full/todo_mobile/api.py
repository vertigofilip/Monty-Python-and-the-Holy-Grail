"""The application server's HTTP API, for the phone app.

Only the standard library is used (urllib), so nothing has to be compiled for
Android apart from Python itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from todo_db.i18n import tr

TIMEOUT = 10.0


class RemoteError(ValueError):
    """The server refused a request or could not be reached (message for the user)."""


class NotLoggedIn(RemoteError):
    """The login expired or was ended on the server; the user must log in again."""


class Api:
    """A connection to the server, logged in once `token` is set."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        base_url = base_url.strip().rstrip("/")
        if base_url and "://" not in base_url:
            base_url = "http://" + base_url
        self.base_url = base_url
        self.token = token
        # Whether the last request reached the server (any answer); None before the first.
        self.connected: bool | None = None

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Send a request; returns the JSON answer or raises RemoteError."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                content = response.read()
            self.connected = True
        except urllib.error.HTTPError as error:
            self.connected = True  # the server answered, with an error
            content = error.read()
            if error.code == 401 and self.token:
                raise NotLoggedIn(tr("Login expired. Please log in again.")) from error
            raise RemoteError(_error_message(error.code, content)) from error
        except (OSError, ValueError) as error:  # URLError, timeouts, bad addresses
            self.connected = False
            message = tr("Cannot reach the server at {url}.").format(url=self.base_url)
            raise RemoteError(f"{message} ({error})") from error
        return json.loads(content) if content else None

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Log in; keeps the token and returns the logged-in user."""
        answer = self.request("POST", "/auth/login", {"email": email, "password": password})
        self.token = answer["token"]
        return answer["user"]

    def logout(self) -> None:
        """End the login on the server; errors are ignored (the token is forgotten anyway)."""
        try:
            self.request("POST", "/auth/logout")
        except RemoteError:
            pass
        self.token = None

    def load_all(self) -> dict[str, Any]:
        """Everything the task list needs, in one go."""
        return {
            "users": self.request("GET", "/users"),
            "workflows": self.request("GET", "/workflows"),
            "repeat_rules": self.request("GET", "/repeat-rules"),
            "tags": self.request("GET", "/tags"),
            "tasks": self.request("GET", "/tasks"),
        }


def _error_message(code: int, content: bytes) -> str:
    """The server's explanation of an error, as plain text."""
    try:
        detail = json.loads(content).get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # validation errors: [{"loc": [...], "msg": ...}, ...]
        return "; ".join(f"{item['loc'][-1]}: {item['msg']}" for item in detail)
    if detail:
        return tr(str(detail))
    return tr("Server error {code}").format(code=code)


# -- remembered login (in the app's private storage) ---------------------------------


def save_login(path: Path, base_url: str, token: str) -> None:
    path.write_text(json.dumps({"server_url": base_url, "token": token}), encoding="utf-8")
    path.chmod(0o600)


def load_login(path: Path) -> tuple[str, str] | None:
    """(server address, token) of a remembered login, or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["server_url"], data["token"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def forget_login(path: Path) -> None:
    path.unlink(missing_ok=True)
