"""Write docs/FUNCTIONS.md: every file with a diagram and what each function does.

Everything comes from the code itself (its classes, functions and descriptions),
so run this again after changing the code:  python docs/make_function_list.py
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "FUNCTIONS.md"
GROUPS = {
    "Shared code and the desktop program (`todo_db`)": "todo_db",
    "The application server (`todo_server`)": "todo_server",
    "The phone app (`todo_mobile`)": "todo_mobile",
}
DIAGRAM_NAMES = 14  # a diagram shows at most this many functions by name; the table has all
Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def first_line(node: ast.AST) -> str:
    """The first line of a description, ready for a table."""
    text = ast.get_docstring(node) or ""  # type: ignore[arg-type]
    return text.split("\n")[0].replace("|", "\\|")


def definitions(node: ast.AST) -> list[Definition]:
    """The classes and functions directly in this file or class."""
    return [c for c in node.body if isinstance(c, Definition)]  # type: ignore[attr-defined]


def methods(cls: ast.ClassDef) -> list[Definition]:
    """The class's methods; __init__ and the like only if they have a description."""
    return [
        c for c in definitions(cls)
        if not isinstance(c, ast.ClassDef) and (not c.name.startswith("__") or first_line(c))
    ]


def arguments(function: Definition) -> str:
    """The parameters' names, without self."""
    names = [a.arg for a in function.args.posonlyargs + function.args.args]  # type: ignore[union-attr]
    return ", ".join(name for name in names if name not in ("self", "cls"))


def diagram(path: Path, tree: ast.Module) -> list[str]:
    """A Mermaid diagram of the file: its classes and top-level functions."""
    lines = ["```mermaid", "flowchart LR", f'    file["{path.name}"]']
    items = definitions(tree)
    classes = [c for c in items if isinstance(c, ast.ClassDef)]
    functions = [c for c in items if not isinstance(c, ast.ClassDef)]
    for number, cls in enumerate(classes):
        count = len(methods(cls))
        lines.append(f'    file --> c{number}["class {cls.name}<br/>{count} methods"]')
    if functions:
        names = [f.name.strip("_") + "()" for f in functions[:DIAGRAM_NAMES]]
        if len(functions) > DIAGRAM_NAMES:
            names.append(f"and {len(functions) - DIAGRAM_NAMES} more")
        lines.append(f'    file --> functions["{"<br/>".join(names)}"]')
    return [*lines, "```", ""]


def table(rows: list[Definition]) -> list[str]:
    """What each function does, in a table."""
    lines = ["| Function | What it does |", "| --- | --- |"]
    for row in rows:
        lines.append(f"| `{row.name}({arguments(row)})` | {first_line(row)} |")
    return [*lines, ""]


def describe(path: Path) -> list[str]:
    """One file's section."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = [f"### `{path.relative_to(ROOT)}`", "", first_line(tree), ""]
    items = definitions(tree)
    if not items:
        return lines
    lines += diagram(path, tree)
    functions = [c for c in items if not isinstance(c, ast.ClassDef)]
    if functions:
        lines += ["**Functions**", "", *table(functions)]
    for cls in (c for c in items if isinstance(c, ast.ClassDef)):
        lines += [f"**class `{cls.name}`** – {first_line(cls)}", ""]
        if methods(cls):
            lines += table(methods(cls))
    return lines


def main() -> None:
    lines = [
        "# Every file and function",
        "",
        "Written by `docs/make_function_list.py` from the code; do not edit by hand.",
        "The overall diagrams are in [CODE_MAP.md](CODE_MAP.md).",
        "",
    ]
    for title, folder in GROUPS.items():
        lines += [f"## {title}", ""]
        for path in sorted((ROOT / folder).glob("*.py")):
            if path.name != "__init__.py":
                lines += describe(path)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
