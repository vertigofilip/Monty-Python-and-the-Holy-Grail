"""Where the phone app keeps its database in the mode without a server (no Kivy here).

Android lets an app write freely only in its own folders: the private one
(the default; hidden, removed with the app) and its folder on the shared
storage (Android/data/<package>/files; visible over USB, also removed with
the app). Anywhere else, such as Documents, SQLite needs the "All files
access" permission, which the user grants in Android's settings.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from todo_db import settings

DB_NAME = "todo.db"
SETTING = "local_database"  # settings.json: the database file chosen by the user
# On Android (the app or its background service); no Kivy here, the service has none.
ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


@dataclass(frozen=True)
class Place:
    """A suggested place for the database."""

    label: str  # untranslated, for tr()
    path: Path
    needs_permission: bool


def local_database(private: Path) -> Path:
    """The database of the mode without a server: the file chosen, or todo.db in private."""
    saved = settings.load_setting(SETTING)
    if isinstance(saved, str) and saved.strip():
        return Path(saved)
    return private / DB_NAME


def database_file(text: str, base: Path) -> Path:
    """The file meant by what the user typed: ~ expanded, relative to base, folder -> todo.db."""
    path = Path(text.strip()).expanduser()
    if not path.is_absolute():
        path = base / path
    if path.is_dir() or text.strip().endswith("/"):
        path = path / DB_NAME
    return path


def inside(path: Path, folders: list[Path]) -> bool:
    """Whether the path is in one of the folders (the app's own, which need no permission)."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(folder.resolve()) for folder in folders)


def move_database(old: Path, new: Path, copy: bool) -> None:
    """Prepare the new file: a copy of the old one's tasks, or nothing (it starts empty).

    The old file is kept; its connections must be closed first (LocalApi.close).
    """
    new.parent.mkdir(parents=True, exist_ok=True)
    if copy and old.exists():
        if new.exists():
            raise FileExistsError(new)
        shutil.copy2(old, new)


# -- Android ----------------------------------------------------------------------------


def _activity():  # type: ignore[no-untyped-def]
    from jnius import autoclass

    return autoclass("org.kivy.android.PythonActivity").mActivity


def own_folders(private: Path) -> list[Path]:
    """The app's folders, writable without any permission."""
    folders = [private]
    if ANDROID:
        try:
            shared = _activity().getExternalFilesDir(None)
            if shared is not None:
                folders.append(Path(shared.getAbsolutePath()))
        except Exception:  # noqa: BLE001 - no shared storage: only the private folder
            pass
    return folders


def places(private: Path) -> list[Place]:
    """Suggested places: private, the app's folder on the shared storage, Documents."""
    suggested = [Place("App storage (private)", private / DB_NAME, False)]
    folders = own_folders(private)
    if len(folders) > 1:
        suggested.append(Place("App folder on the phone storage", folders[1] / DB_NAME, False))
    if ANDROID:
        try:
            from jnius import autoclass

            environment = autoclass("android.os.Environment")
            documents = environment.getExternalStoragePublicDirectory(
                environment.DIRECTORY_DOCUMENTS
            ).getAbsolutePath()
            suggested.append(Place("Documents", Path(documents) / "todo" / DB_NAME, True))
        except Exception:  # noqa: BLE001
            pass
    else:
        suggested.append(Place("Documents", Path.home() / "Documents" / DB_NAME, False))
    return suggested


def has_all_files_access() -> bool:
    """Whether the app may use files anywhere on the shared storage (always on a computer)."""
    if not ANDROID:
        return True
    try:
        from jnius import autoclass

        return bool(autoclass("android.os.Environment").isExternalStorageManager())
    except Exception:  # noqa: BLE001 - Android before 11: the old storage rules apply
        return True


def ask_all_files_access() -> None:
    """Open Android's settings page where the user allows "All files access" for this app."""
    from jnius import autoclass

    intent_class = autoclass("android.content.Intent")
    settings = autoclass("android.provider.Settings")
    uri = autoclass("android.net.Uri")
    activity = _activity()
    intent = intent_class(settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                          uri.parse("package:" + activity.getPackageName()))
    activity.startActivity(intent)
