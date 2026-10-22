"""The icon in the system tray, so the program can keep running with its window closed.

Its menu opens the window, checks for due tasks at once, switches reminders
on or off and quits the program. Built on pystray; on Linux its menu needs
the AppIndicator library through PyGObject ("gi"), which usually comes with
the system (python3-gi) rather than from pip, so the system's copy is used
when the virtual environment has none. Without it there is no icon (pystray
could show one, but with no menu, so no way to quit a hidden program).

The menu's actions run in the tray's own thread; the callbacks given here
must hand the work over to the window's thread (TodoApp.call_soon).
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .i18n import tr

log = logging.getLogger("todo_db.tray")

ICON_COLOUR = "#FF8C00"  # orange, like the reminder window (the picture if the logo is missing)
LOGO_FILE = Path(__file__).with_name("logo.png")  # the program's logo, also the phone app's icon
# Where Debian/Ubuntu/Mint keep python3-gi.
SYSTEM_PACKAGES = (Path("/usr/lib/python3/dist-packages"),)


def _use_system_gi() -> None:
    """Make the system's PyGObject importable if the virtual environment lacks it."""
    try:
        import gi  # noqa: F401
    except ImportError:
        for path in SYSTEM_PACKAGES:
            if (path / "gi").is_dir() and str(path) not in sys.path:
                sys.path.append(str(path))  # last: packages of the venv still come first
                break


def icon_image(size: int = 64) -> Any:
    """The tray icon: the program's logo (a white tick on an orange circle if it is missing)."""
    from PIL import Image, ImageDraw

    try:
        with Image.open(LOGO_FILE) as logo:
            return logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    except OSError:
        log.warning("Cannot read %s; drawing a plain icon instead", LOGO_FILE)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size - 3, size - 3), fill=ICON_COLOUR)
    tick = [(size * 0.27, size * 0.52), (size * 0.44, size * 0.69), (size * 0.74, size * 0.34)]
    draw.line(tick, fill="white", width=max(3, size // 9), joint="curve")
    return image


class Tray:
    """The tray icon and its menu; start() says whether it could be shown."""

    def __init__(
        self,
        *,
        open_window: Callable[[], None],
        check_now: Callable[[], None],
        reminders_on: Callable[[], bool],
        toggle_reminders: Callable[[], None],
        quit_program: Callable[[], None],
    ) -> None:
        self._actions = (open_window, check_now, reminders_on, toggle_reminders, quit_program)
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Show the icon (in a background thread); False if there is no tray support."""
        open_window, check_now, reminders_on, toggle_reminders, quit_program = self._actions
        try:
            _use_system_gi()
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem(tr("Open the to-do list"), lambda: open_window(), default=True),
                pystray.MenuItem(tr("Check reminders now"), lambda: check_now()),
                pystray.MenuItem(
                    tr("Reminders on"), lambda: toggle_reminders(),
                    checked=lambda _item: reminders_on(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(tr("Quit"), lambda: quit_program()),
            )
            icon = pystray.Icon("todolist", icon_image(), tr("To-do list"), menu)
        except Exception:
            log.exception("No tray icon: pystray or Pillow cannot be used here")
            return False
        if not icon.HAS_MENU:
            # Without a menu there would be no way to quit a hidden program.
            log.warning("No tray icon: %s has no menus (install python3-gi)", type(icon).__module__)
            return False
        self._icon = icon
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        log.info("Tray icon shown (%s)", type(self._icon).__module__)
        return True

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:
            log.exception("The tray icon stopped")

    def refresh_menu(self) -> None:
        """Show changed check marks (e.g. reminders switched off in the window)."""
        if self._icon is not None:
            self._icon.update_menu()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                log.exception("Cannot remove the tray icon")
        if self._thread is not None:
            self._thread.join(timeout=2)
