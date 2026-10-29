"""Interface translations: switching, fallback, completeness and the saved choice."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from todo_db import i18n, settings
from todo_db.models import ChangeType, Priority, RepeatUnit, Urgency
from todo_db.seed import repeat_rule_name
from todo_db.services import NONE, UPDATABLE

APP_SOURCE = "".join(
    Path(i18n.__file__).with_name(name).read_text(encoding="utf-8")
    for name in ("app.py", "management.py", "presets.py", "templates.py", "pick.py", "remote.py", "reminders.py", "tray.py")
) + "".join(
    path.read_text(encoding="utf-8")
    for path in sorted((Path(i18n.__file__).parent.parent / "todo_mobile").glob("*.py"))
)


@pytest.fixture(autouse=True)
def english_afterwards() -> Iterator[None]:
    """Leave the global language as the other tests expect it."""
    yield
    i18n.set_language("en")


def test_english_is_returned_unchanged() -> None:
    i18n.set_language("en")
    assert i18n.tr("New task") == "New task"


def test_polish_translation_and_fallback() -> None:
    i18n.set_language("pl")
    assert i18n.tr("New task") == "Nowe zadanie"
    assert i18n.tr("Priority") == "Priorytet"
    assert i18n.tr("some user data") == "some user data"


def test_unknown_language_falls_back_to_english() -> None:
    i18n.set_language("xx")
    assert i18n.get_language() == "en"


def test_every_interface_text_has_a_polish_translation() -> None:
    texts = set(re.findall(r"""(?:\btr|_commit|_ask_name)\(\s*"([^"]+)\"""", APP_SOURCE))
    texts |= set(re.findall(r"""\btr\(\s*'([^']+)'""", APP_SOURCE))
    # Texts that reach tr() through a variable rather than a literal.
    texts |= set(re.findall(r'"([^"]+)"', re.search(r"TASK_COLUMNS = \(([^)]+)\)", APP_SOURCE)[1]))
    texts |= set(re.findall(r'"([^"]+)"', re.search(r"HISTORY_COLUMNS = (.+)", APP_SOURCE)[1]))
    for name in ("MONTHS", "WEEKDAYS"):
        texts |= set(re.findall(r'"([^"]+)"', re.search(rf"{name} = \(([^)]+)\)", APP_SOURCE)[1]))
    texts |= {priority.name for priority in Priority}
    texts |= {urgency.name for urgency in Urgency}
    texts |= {repeat_rule_name(1, unit) for unit in RepeatUnit}
    texts |= {f"Every {{n}} {unit.value.lower()}s" for unit in RepeatUnit}
    texts |= {change_type.name for change_type in ChangeType}
    texts |= set(UPDATABLE.values()) | {"RepeatDone", NONE, "Email", "Active", "Created at"}
    texts |= {"Role", "Admin", "User"}  # remote users window (column names and role values)
    from todo_db.app import COMPRESSION_NOTE

    texts.add(COMPRESSION_NOTE)
    # The phone app: texts kept in constants (main.py is not imported: that opens a window).
    phone = ast.parse((Path(i18n.__file__).parent.parent / "todo_mobile" / "main.py").read_text())
    texts |= {
        ast.literal_eval(node.value) for node in phone.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in ("ACCESS_NOTE", "ACCESS_ASK", "COPY_OR_EMPTY")
    }
    texts |= set(re.findall(r'Place\(\s*"([^"]+)"', APP_SOURCE))  # todo_mobile/storage.py
    assert len(texts) > 80  # the scan really found the interface texts

    i18n.set_language("pl")
    missing = sorted(text for text in texts if text not in i18n._POLISH)
    assert missing == []


def test_placeholders_survive_translation() -> None:
    for english, polish in i18n._POLISH.items():
        assert set(re.findall(r"{\w+}", english)) == set(re.findall(r"{\w+}", polish))


def test_language_choice_is_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("en_US", "UTF-8"))
    assert i18n.load_language() == "en"

    i18n.save_language("pl")
    assert i18n.load_language() == "pl"


def test_system_language_is_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("pl_PL", "UTF-8"))
    assert i18n.load_language() == "pl"

    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("de_DE", "UTF-8"))
    assert i18n.load_language() == "en"


def test_polish_plural_forms() -> None:
    i18n.set_language("pl")
    assert i18n.tr_n("Every {n} days", 7) == "Co 7 dni"
    assert i18n.tr_n("Every {n} weeks", 2) == "Co 2 tygodnie"
    assert i18n.tr_n("Every {n} weeks", 5) == "Co 5 tygodni"
    assert i18n.tr_n("Every {n} weeks", 12) == "Co 12 tygodni"
    assert i18n.tr_n("Every {n} weeks", 22) == "Co 22 tygodnie"

    i18n.set_language("en")
    assert i18n.tr_n("Every {n} weeks", 3) == "Every 3 weeks"


def test_settings_keep_each_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")

    i18n.save_language("pl")
    settings.save_setting("sort", [["Priority", True]])
    i18n.save_language("en")

    assert settings.load_setting("sort") == [["Priority", True]]
    assert i18n.load_language() == "en"
