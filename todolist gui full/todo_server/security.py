"""Passwords, login tokens and a simple brake on password guessing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import deque

# scrypt cost: about 50 ms per check on a normal computer, which is cheap for
# one login but expensive for someone trying millions of passwords.
_N, _R, _P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Salted scrypt hash, stored as "scrypt$n$r$p$salt$hash"."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    encode = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Whether the password matches the stored hash (False if there is none)."""
    if not stored:
        hash_password(password)  # same cost either way, so timing reveals nothing
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_token() -> str:
    """A random login token for the client (shown once, never stored as is)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What the database stores for a token."""
    return hashlib.sha256(token.encode()).hexdigest()


class LoginLimiter:
    """Blocks a login name + address for a while after too many wrong passwords."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 15 * 60) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        while failures and failures[0] < time.monotonic() - self.window:
            failures.popleft()
        return failures

    def blocked(self, key: str) -> bool:
        """Whether this key has used up its attempts."""
        return len(self._recent(key)) >= self.max_failures

    def failed(self, key: str) -> None:
        """Record a wrong password."""
        self._recent(key).append(time.monotonic())

    def succeeded(self, key: str) -> None:
        """Forget earlier failures after a correct password."""
        self._failures.pop(key, None)
