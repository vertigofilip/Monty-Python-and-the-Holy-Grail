"""build_android.sh packs every module the phone app imports (else the app crashes at start)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def packed(package: str) -> set[str]:
    """The modules of a package that build_android.sh copies into the app."""
    script = (ROOT / "build_android.sh").read_text(encoding="utf-8")
    names = re.search(rf"cp {package}/{{([^}}]+)}}\.py", script)
    assert names is not None, f"build_android.sh does not copy {package}"
    return {f"{package}.{name}" for name in names[1].split(",")}


def imported(module: str) -> set[str]:
    """todo_db / todo_mobile modules that the module imports (also inside functions)."""
    package, name = module.split(".")
    tree = ast.parse((ROOT / package / f"{name}.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # from . import x / from .x import y
                base = f"{package}.{base}" if base else package
            if base in ("todo_db", "todo_mobile"):
                found |= {f"{base}.{alias.name}" for alias in node.names}
            elif base.startswith(("todo_db.", "todo_mobile.")):
                found.add(base)
        elif isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.startswith(("todo_db.", "todo_mobile."))}
    return {m for m in found if (ROOT / m.replace(".", "/")).with_suffix(".py").exists()}


def test_every_module_the_phone_app_needs_is_packed() -> None:
    have = packed("todo_db") | packed("todo_mobile")
    needed, todo = set(), ["todo_mobile.main", "todo_mobile.reminder_service"]
    while todo:
        module = todo.pop()
        if module not in needed:
            needed.add(module)
            todo += sorted(imported(module))
    assert sorted(needed - have) == []
