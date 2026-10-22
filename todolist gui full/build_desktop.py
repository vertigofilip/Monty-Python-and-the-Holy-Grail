"""Build the desktop program and the server as standalone executables (PyInstaller).

    python3 build_desktop.py          (Linux)     dist/linux/todolist, dist/linux/todolist-server
    py build_desktop.py               (Windows)   dist\\windows\\todolist.exe, todolist-server.exe

They run without Python installed. PyInstaller builds only for the system it
runs on: build the Windows ones on Windows (or by the GitHub Actions workflow
.github/workflows/todolist-build.yml). The phone app is built by build_android.sh.

The build uses its own virtual environment (build/venv-<system>) with
requirements.txt and PyInstaller; the project's .venv is left alone. Like the
scripts, the executables keep settings.json, todo.db, todo_server.db and the
log in the folder they are started from.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM = "windows" if os.name == "nt" else platform.system().lower()
BUILD = HERE / "build"
VENV = BUILD / f"venv-{SYSTEM}"
DIST = HERE / "dist" / SYSTEM
PYINSTALLER = "pyinstaller>=6.10"

# Modules imported by name at run time, which PyInstaller cannot see.
HIDDEN = {
    "windows": ["plyer.platforms.win.notification"],
    "linux": ["plyer.platforms.linux.notification"],
    "darwin": ["plyer.platforms.macosx.notification"],
}


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv() -> None:
    """Re-run this script in the build environment, creating it first if needed."""
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    marker = VENV / ".requirements-installed"
    if not venv_python().exists():
        print(f"Creating {VENV} ...")
        venv.create(VENV, with_pip=True)
    if not marker.exists() or (HERE / "requirements.txt").stat().st_mtime > marker.stat().st_mtime:
        print("Installing requirements and PyInstaller ...")
        subprocess.run([venv_python(), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
        subprocess.run([venv_python(), "-m", "pip", "install", "--quiet",
                        "-r", HERE / "requirements.txt", PYINSTALLER], check=True)
        marker.touch()
    sys.exit(subprocess.run([venv_python(), __file__, *sys.argv[1:]]).returncode)


def build(name: str, script: str, windowed: bool, extra: list[str]) -> Path:
    import PyInstaller.__main__

    logo = HERE / "todo_db" / "logo.png"
    data = f"{logo}{os.pathsep}todo_db"
    # The file's icon: Windows and macOS only (Pillow makes the .ico from the PNG).
    icon = ["--icon", str(logo)] if SYSTEM in ("windows", "darwin") else []
    PyInstaller.__main__.run([
        str(HERE / "packaging" / script),
        "--name", name,
        "--onefile",
        "--noconfirm",
        "--clean",
        "--windowed" if windowed else "--console",
        "--add-data", data,
        "--paths", str(HERE),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / f"pyinstaller-{SYSTEM}"),
        "--specpath", str(BUILD / f"pyinstaller-{SYSTEM}"),
        "--log-level", "WARN",
        *icon,
        *extra,
    ])
    return DIST / (name + (".exe" if os.name == "nt" else ""))


def tray_backends() -> list[str]:
    """Linux: pystray's GTK backends, which the tray icon's menu needs.

    Their PyGObject (gi) is not bundled - with GTK it would add some 450 MB;
    the program takes the system's (python3-gi), as todo_db/tray.py does
    when run from the scripts. Without it there is no tray icon.
    """
    if SYSTEM != "linux":
        return []
    # The standard modules that gi imports, which nothing else in the program does.
    modules = ["pystray._appindicator", "pystray._gtk", "optparse", "gettext", "pkgutil",
               "textwrap", "selectors", "socket", "array", "asyncio"]
    return [*(arg for module in modules for arg in ("--hidden-import", module)),
            "--exclude-module", "gi"]


def main() -> None:
    ensure_venv()
    hidden = [arg for module in HIDDEN.get(SYSTEM, []) for arg in ("--hidden-import", module)]
    hidden += tray_backends()
    shutil.rmtree(DIST, ignore_errors=True)
    built = [
        build("todolist", "desktop.py", windowed=True,
              extra=[*hidden, "--collect-submodules", "pystray"]),
        build("todolist-server", "server.py", windowed=False,
              extra=["--collect-submodules", "uvicorn"]),
    ]
    print("Ready:")
    for path in built:
        print(f"  {path}  ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
