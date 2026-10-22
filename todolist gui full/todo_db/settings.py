"""Per-user program settings, kept in settings.json in the current directory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

SETTINGS_FILE = Path("settings.json")

log = logging.getLogger("todo_db.settings")


def _load_all() -> dict[str, Any]:
    """All saved settings; empty if the file is missing or broken."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_setting(key: str, default: Any = None) -> Any:
    """One saved setting, or the default."""
    return _load_all().get(key, default)


def save_setting(key: str, value: Any) -> None:
    """Save one setting, keeping the others."""
    data = _load_all()
    data[key] = value
    _save_all(data)


def _save_all(data: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_defaults(defaults: dict[str, Any]) -> None:
    """Write the settings missing from the file with their defaults; others stay as set.

    So settings.json always shows what can be changed by hand.
    """
    data = _load_all()
    missing = {key: value for key, value in defaults.items() if key not in data}
    if missing:
        try:
            _save_all(data | missing)
        except OSError as error:
            log.warning("Cannot write the default settings to %s: %s", SETTINGS_FILE, error)


def number_setting(key: str, default: float) -> float:
    """A positive number from the file, or the default (a wrong value is logged)."""
    value = load_setting(key, default)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return value
    log.warning("Ignoring %s=%r in %s (need a positive number)", key, value, SETTINGS_FILE)
    return default


def text_setting(key: str, default: str) -> str:
    """A non-empty text from the file, or the default (a wrong value is logged)."""
    value = load_setting(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    log.warning("Ignoring %s=%r in %s (need a text)", key, value, SETTINGS_FILE)
    return default


def flag_setting(key: str, default: bool) -> bool:
    """true/false from the file, or the default (a wrong value is logged)."""
    value = load_setting(key, default)
    if isinstance(value, bool):
        return value
    log.warning("Ignoring %s=%r in %s (need true or false)", key, value, SETTINGS_FILE)
    return default
