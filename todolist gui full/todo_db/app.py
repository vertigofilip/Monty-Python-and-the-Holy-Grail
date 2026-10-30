"""The to-do program: a Tkinter window on top of TaskService.

Run with:  python -m todo_db.app
"""

from __future__ import annotations

import argparse
import calendar
import logging
import os
import queue
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import i18n, management, pick, settings, templates
from .database import create_all, make_engine, make_session_factory
from .management import LocalManagement, ManagementError
from .compression import COMPRESSION_NOTE, parse_summary
from .remote import (
    ApiClient, NotLoggedIn, RemoteAccount, RemoteError, RemoteManagement, RemoteTaskService, log_in,
    resume_login,
)
from . import reminders
from .reminders import (
    DueTask, Reminders, local_due_tasks, only_mine, remote_due_tasks, setup_logging,
    system_notifications,
)
from .i18n import tr, tr_n
from .models import (
    ChangeType,
    Priority,
    RepeatRule,
    RepeatUnit,
    Stage,
    Tag,
    Task,
    TaskChange,
    Urgency,
    User,
    Workflow,
)
from .presets import (  # noqa: F401 - also this module's names, as before
    DESCENDING_FIRST, SORT_FIELDS, TASK_COLUMNS, FilterPreset, SortPreset, filter_keys,
    filter_value, load_presets, load_sort, load_sort_presets, name_taken, parse_sort,
    save_presets, save_sort, save_sort_presets, sorted_by, text_sort_key,
)
from .tray import Tray
from .seed import add_missing_repeat_rules, repeat_rule_name, seed
from .services import NONE, TaskService

# A filter test for one column; a task is shown when every active test passes.
Predicate = Callable[[Task], bool]

log = logging.getLogger("todo_db.app")

# Closing the window keeps the program running in the system tray (reminders go on);
# "close_to_tray" in settings.json overrides it.
CLOSE_TO_TRAY = True
DB_FILE = Path("todo.db")  # local mode's database: in the folder the program starts in
DB_SETTING = "database"  # settings.json: another database file chosen by the user
DB_ENV = "TODO_DB"  # environment variable: the database file for one run (like --db)
# The folder for settings.json, todo.db, the log and the login (default: where it starts).
HOME_ENV = "TODO_HOME"

# How often the window fetches other people's changes in server mode
# ("sync_seconds" in settings.json overrides it).
SYNC_SECONDS = 30
CONNECTION_OK, CONNECTION_LOST = "#2E7D32", "#C62828"  # green, red: the server indicator

# Unfinished tasks due today, in the task list (overdue ones are red).
DUE_TODAY_COLOUR = "#1E8C3A"

# Colours of the "Next stage" button: normal, and under the mouse / pressed.
NEXT_STAGE_COLOUR = "#2E9E44"
NEXT_STAGE_ACTIVE = "#23803A"

# Background of the Priority and Urgency cells in the task list, by level (the value
# of Priority and Urgency): low (Maybe, Low) green, middle (Normal, Medium) yellow,
# high (Important, High) red.
LEVEL_COLOURS = {0: "#B9E4BC", 1: "#FFE98A", 2: "#F8B4B4"}
LEVEL_COLUMNS = ("Priority", "Urgency")

# The task list's columns from left to right. A Treeview always draws its tree column
# (#0, with the subtask indentation and the ▸ arrows) first, so the stage goes there and
# the name is an ordinary column, its subtasks indented by hand (NAME_INDENT per level).
LIST_COLUMNS = (TASK_COLUMNS[0], "Task", *TASK_COLUMNS[1:])
LIST_WIDTHS = {
    "Stage": 150, "Task": 320, "Progress": 70, "Repeat": 120, "Due date": 90, "Priority": 80,
    "Urgency": 80, "Assignee": 130, "Location": 120, "Tags": 120,
}
NAME_INDENT = "    "


def column_id(field: str) -> str:
    """The Treeview's name for a task list column: #0 for the first."""
    return "#0" if field == LIST_COLUMNS[0] else field


HISTORY_COLUMNS = ("When", "Task", "Who", "Change", "Field", "Old value", "New value")
HISTORY_TEXT_FILTERS = ("Task", "Old value", "New value")  # the others have drop-downs


def repeat_label(rule: RepeatRule) -> str:
    """A repeat rule as shown to the user, in the current language."""
    if rule.interval == 1:
        return tr(repeat_rule_name(1, rule.unit))
    return tr_n(f"Every {{n}} {rule.unit.value.lower()}s", rule.interval)


def repeat_sort_key(rule: RepeatRule) -> tuple[int, int]:
    """Order rules by unit (days first), then by interval."""
    return list(RepeatUnit).index(rule.unit), rule.interval


class TreeTooltip:
    """A small window with a row's text, shown when the mouse rests over a row of a Treeview.

    text(iid) gives the text of a row; nothing is shown when it is empty. The
    window goes when the mouse moves to another row, leaves the list, or clicks.
    """

    DELAY_MS = 700  # how long the mouse must rest over a row
    WIDTH = 400  # pixels: longer lines wrap

    def __init__(self, tree: ttk.Treeview, text: Callable[[str], str]) -> None:
        self._tree, self._text = tree, text
        self._row = ""  # the row under the mouse
        self._pending: str | None = None  # the after() job that will show the window
        self._window: tk.Toplevel | None = None
        tree.bind("<Motion>", self._moved, add="+")
        for sequence in ("<Leave>", "<ButtonPress>", "<KeyPress>", "<MouseWheel>"):
            tree.bind(sequence, lambda _event: self.hide(), add="+")

    def _moved(self, event: tk.Event) -> None:
        row = self._tree.identify_row(event.y)
        if row == self._row:
            return
        self.hide()
        self._row = row
        if row:
            self._pending = self._tree.after(self.DELAY_MS, self._show)

    def _show(self) -> None:
        self._pending = None
        if not self._tree.exists(self._row):
            return
        text = self._text(self._row).strip()
        if not text:
            return
        self._window = window = tk.Toplevel(self._tree)
        window.wm_overrideredirect(True)
        tk.Label(
            window, text=text, justify="left", wraplength=self.WIDTH, background="#FFFFE0",
            foreground="black", relief="solid", borderwidth=1, padx=6, pady=4,
        ).pack()
        x, y = self._tree.winfo_pointerxy()
        window.update_idletasks()
        # Below and right of the mouse, but kept on the screen.
        x = min(x + 12, window.winfo_screenwidth() - window.winfo_reqwidth())
        if y + 20 + window.winfo_reqheight() > window.winfo_screenheight():
            y -= window.winfo_reqheight() + 8
        else:
            y += 20
        window.wm_geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def hide(self) -> None:
        """Remove the window, or stop it from coming; the next row starts afresh."""
        if self._pending is not None:
            self._tree.after_cancel(self._pending)
            self._pending = None
        if self._window is not None:
            self._window.destroy()
            self._window = None
        self._row = ""


class WrapFrame(ttk.Frame):
    """Frame that lays out its children left to right and wraps to a new row when full."""

    def __init__(self, master: tk.Misc, gap: int = 4) -> None:
        super().__init__(master, height=1)
        self._gap = gap
        self.bind("<Configure>", lambda _event: self.relayout())

    def relayout(self) -> None:
        """Place the children in rows that fit the current width."""
        width = self.winfo_width()
        if width <= 1:
            return  # not shown yet
        x = y = row_height = 0
        for child in self.winfo_children():
            child_width, child_height = child.winfo_reqwidth(), child.winfo_reqheight()
            if x > 0 and x + child_width > width:
                x, y, row_height = 0, y + row_height + self._gap, 0
            child.place(x=x, y=y)
            x += child_width + self._gap
            row_height = max(row_height, child_height)
        if int(self.cget("height")) != y + row_height:
            self.configure(height=y + row_height)


class Choice(ttk.Combobox):
    """Read-only combobox that maps the shown labels to values."""

    def __init__(self, master: tk.Misc, options: list[tuple[str, Any]], value: Any) -> None:
        super().__init__(master, state="readonly")
        self.set_options(options, value)

    def set_options(self, options: list[tuple[str, Any]], value: Any) -> None:
        """Replace the options and select the given value (or the first one)."""
        self._choices = options
        self.configure(values=[label for label, _ in options])
        values = [option_value for _, option_value in options]
        self.current(values.index(value) if value in values else 0)

    def value(self) -> Any:
        """The value behind the selected label."""
        return self._choices[self.current()][1]


class TaskDialog(tk.Toplevel):
    """Modal form for a new or existing task; `result` holds the fields on OK."""

    def __init__(
        self, master: tk.Misc, session: Session, task: Task | None,
        default_assignee_id: int | None = None,
    ) -> None:
        """default_assignee_id: who a new task is assigned to at first (the person adding it)."""
        super().__init__(master)
        self.title(tr("Edit task") if task else tr("New task"))
        self.result: dict[str, Any] | None = None
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)

        stages = [
            (f"{workflow.name}: {stage.name}", stage.id)
            for workflow in session.scalars(select(Workflow).order_by(Workflow.name))
            for stage in workflow.stages
        ]
        users: list[tuple[str, Any]] = [(tr(NONE), None)] + [
            (user.name, user.id)
            for user in session.scalars(select(User).order_by(User.name))
            if user.is_active or (task and task.assignee_id == user.id)
        ]
        rules: list[tuple[str, Any]] = [(tr(NONE), None)] + [
            (repeat_label(rule), rule.id)
            for rule in sorted(session.scalars(select(RepeatRule)), key=repeat_sort_key)
        ]
        self._tags = list(session.scalars(select(Tag).order_by(Tag.name)))

        form = ttk.Frame(self, padding=12)
        form.grid()
        form.columnconfigure(1, weight=1)

        self._name = ttk.Entry(form, width=44)
        self._name.insert(0, task.name if task else "")
        self._description = tk.Text(form, width=44, height=4, wrap="word")
        self._description.insert("1.0", (task.description or "") if task else "")
        self._stage = Choice(form, stages, task.stage_id if task else None)
        self._priority = Choice(
            form,
            [(tr(priority.name), priority) for priority in Priority],
            task.priority if task else Priority.Normal,
        )
        self._urgency = Choice(
            form,
            [(tr(urgency.name), urgency) for urgency in Urgency],
            task.urgency if task else Urgency.Medium,
        )
        due = ttk.Frame(form)
        self._due = ttk.Entry(due, width=12)
        self._due.insert(0, task.due_date.isoformat() if task and task.due_date else "")
        self._due.pack(side="left")
        ttk.Button(due, text="📅", width=3, command=self._pick_due_date).pack(
            side="left", padx=(4, 0)
        )
        ttk.Label(due, text=tr("YYYY-MM-DD, empty = none"), foreground="gray45").pack(
            side="left", padx=(8, 0)
        )
        self._location = ttk.Entry(form, width=44)
        self._location.insert(0, (task.location or "") if task else "")
        self._assignee = Choice(
            form, users, task.assignee_id if task else default_assignee_id
        )
        self._rule = Choice(form, rules, task.repeat_rule_id if task else None)
        self._count = ttk.Spinbox(form, from_=0, to=9999, width=6)
        self._count.set(task.repeat_count if task else 1)  # a new task: once
        self._rule.bind("<<ComboboxSelected>>", lambda _event: self._rule_changed())
        self._tag_list = tk.Listbox(
            form, selectmode="multiple", height=min(6, max(2, len(self._tags))),
            exportselection=False,
        )
        task_tag_ids = {tag.id for tag in task.tags} if task else set()
        for index, tag in enumerate(self._tags):
            self._tag_list.insert("end", tag.name)
            if tag.id in task_tag_ids:
                self._tag_list.selection_set(index)

        rows: list[tuple[str, tk.Widget]] = [
            (tr("Name"), self._name),
            (tr("Description"), self._description),
            (tr("Stage"), self._stage),
            (tr("Priority"), self._priority),
            (tr("Urgency"), self._urgency),
            (tr("Due date"), due),
            (tr("Assignee"), self._assignee),
            (tr("Location"), self._location),
            (tr("Repeats"), self._rule),
            (tr("Repeat count (0 = forever)"), self._count),
            (tr("Tags"), self._tag_list),
        ]
        for row, (label, widget) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=3)
            sticky = "w" if widget is self._count else "ew"
            widget.grid(row=row, column=1, sticky=sticky, pady=3)

        buttons = ttk.Frame(form)
        buttons.grid(row=len(rows), column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=tr("OK"), command=self._ok).pack(side="right", padx=6)

        self.bind("<Escape>", lambda _event: self.destroy())
        self._name.bind("<Return>", lambda _event: self._ok())
        self._name.focus_set()
        self.wait_visibility()
        self.grab_set()

    def _rule_changed(self) -> None:
        """Choosing how often makes the task repeat forever; "none" makes it once again.

        A count typed in by hand (other than 0 or 1) is kept.
        """
        count = self._count.get().strip()
        if self._rule.value() is None:
            if count == "0":
                self._count.set(1)
        elif count == "1":
            self._count.set(0)

    def _pick_due_date(self) -> None:
        """Choose the due date from a calendar; it starts at the date typed in, if any."""
        try:
            current = date.fromisoformat(self._due.get().strip())
        except ValueError:
            current = None
        picker = DatePicker(self, current)
        self.wait_window(picker)
        self.grab_set()  # the calendar took the grab; the form is modal again
        if picker.result is not None:
            self._due.delete(0, "end")
            self._due.insert(0, picker.result.isoformat() if picker.result else "")

    def _ok(self) -> None:
        """Validate the form and close it with a result."""
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning(tr("Task"), tr("The task needs a name."), parent=self)
            return
        try:
            repeat_count = int(self._count.get())
        except ValueError:
            repeat_count = -1
        if repeat_count < 0:
            messagebox.showwarning(
                tr("Task"), tr("Repeat count must be a whole number, 0 or more."), parent=self
            )
            return
        due_text = self._due.get().strip()
        try:
            due_date = date.fromisoformat(due_text) if due_text else None
        except ValueError:
            messagebox.showwarning(
                tr("Task"), tr("Enter the due date as YYYY-MM-DD, e.g. 2026-10-31."), parent=self
            )
            return
        self.result = {
            "name": name,
            "description": self._description.get("1.0", "end").strip() or None,
            "stage_id": self._stage.value(),
            "priority": self._priority.value(),
            "urgency": self._urgency.value(),
            "due_date": due_date,
            "location": self._location.get().strip() or None,
            "assignee_id": self._assignee.value(),
            "repeat_rule_id": self._rule.value(),
            "repeat_count": repeat_count,
            "tag_ids": [self._tags[index].id for index in self._tag_list.curselection()],
        }
        self.destroy()


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class DatePicker(tk.Toplevel):
    """A month calendar to pick a date from.

    `result` is the date picked, "" for "No date", or None if closed without a choice.
    """

    def __init__(self, master: tk.Misc, current: date | None) -> None:
        super().__init__(master)
        self.title(tr("Due date"))
        self.result: date | str | None = None
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)
        self._today = date.today()
        self._current = current
        shown = current or self._today
        self._year, self._month = shown.year, shown.month

        body = ttk.Frame(self, padding=10)
        body.pack()
        header = ttk.Frame(body)
        header.pack(fill="x")
        ttk.Button(header, text="◀", width=3, command=lambda: self._turn(-1)).pack(side="left")
        self._title = ttk.Label(header, anchor="center", font=("TkDefaultFont", 11, "bold"))
        self._title.pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="▶", width=3, command=lambda: self._turn(1)).pack(side="right")
        self._days = ttk.Frame(body)
        self._days.pack(pady=(8, 8))
        bottom = ttk.Frame(body)
        bottom.pack(fill="x")
        ttk.Button(bottom, text=tr("Today"), command=lambda: self._pick(self._today)).pack(
            side="left"
        )
        ttk.Button(bottom, text=tr("No date"), command=lambda: self._pick("")).pack(
            side="left", padx=6
        )
        ttk.Button(bottom, text=tr("Cancel"), command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Prior>", lambda _event: self._turn(-1))  # Page Up
        self.bind("<Next>", lambda _event: self._turn(1))  # Page Down
        self._show()
        self.wait_visibility()
        self.grab_set()

    def _turn(self, months: int) -> None:
        """Show an earlier or later month."""
        index = self._year * 12 + self._month - 1 + months
        self._year, self._month = divmod(index, 12)
        self._month += 1
        self._show()

    def _show(self) -> None:
        """Draw the month: weekday names, then the days in weeks starting on Monday."""
        self._title.configure(text=f"{tr(MONTHS[self._month - 1])} {self._year}")
        for child in self._days.winfo_children():
            child.destroy()
        for column, name in enumerate(WEEKDAYS):
            ttk.Label(self._days, text=tr(name), anchor="center", width=4,
                      foreground="red3" if column == 6 else "").grid(row=0, column=column)
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self._year, self._month)
        for row, week in enumerate(weeks, start=1):
            for column, day in enumerate(week):
                button = tk.Button(
                    self._days, text=str(day.day), width=3, relief="flat",
                    command=lambda d=day: self._pick(d),
                )
                if day.month != self._month:
                    button.configure(foreground="gray60")  # the neighbouring months' days
                if day == self._today:
                    button.configure(relief="solid", borderwidth=1)
                if day == self._current:
                    button.configure(background=NEXT_STAGE_COLOUR, foreground="white")
                button.grid(row=row, column=column, padx=1, pady=1)

    def _pick(self, day: date | str) -> None:
        self.result = day
        self.destroy()


class NameDialog(tk.Toplevel):
    """Modal prompt for one name; `result` stays None if cancelled or empty."""

    def __init__(self, master: tk.Misc, title: str, initial: str = "") -> None:
        super().__init__(master)
        self.title(title)
        self.result: str | None = None
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)

        body = ttk.Frame(self, padding=12)
        body.pack()
        ttk.Label(body, text=tr("Name:")).pack(anchor="w")
        self._name = ttk.Entry(body, width=36)
        self._name.insert(0, initial)
        self._name.select_range(0, "end")
        self._name.pack(pady=(4, 10))
        ttk.Button(body, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(body, text=tr("OK"), command=self._ok).pack(side="right", padx=6)

        self.bind("<Return>", lambda _event: self._ok())
        self.bind("<Escape>", lambda _event: self.destroy())
        self._name.focus_set()
        self.wait_visibility()
        self.grab_set()

    def _ok(self) -> None:
        """Close with the entered name."""
        self.result = self._name.get().strip() or None
        self.destroy()


class UsersDialog(tk.Toplevel):
    """Modal window to add, edit and (de)activate users. Users are never deleted."""

    def __init__(self, master: tk.Misc, session: Session) -> None:
        super().__init__(master)
        self.title(tr("Users"))
        self.session = session
        self.transient(master)  # type: ignore[arg-type]

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.users = ttk.Treeview(
            body, columns=("Name", "Email", "Active"), show="headings",
            selectmode="browse", height=8,
        )
        for column, width in (("Name", 180), ("Email", 220), ("Active", 60)):
            self.users.heading(column, text=tr(column))
            self.users.column(column, width=width)
        self.users.tag_configure("inactive", foreground="gray55")
        self.users.pack(fill="both", expand=True)
        self.users.bind("<<TreeviewSelect>>", lambda _event: self._show_selected())

        form = ttk.Frame(body)
        form.pack(fill="x", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        self._name = ttk.Entry(form)
        self._email = ttk.Entry(form)
        for row, (label, entry) in enumerate(((tr("Name"), self._name), (tr("Email"), self._email))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            entry.grid(row=row, column=1, sticky="ew", pady=3)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text=tr("Add as new"), command=self.add).pack(side="left")
        ttk.Button(buttons, text=tr("Save changes"), command=self.save).pack(side="left", padx=6)
        self._toggle = ttk.Button(buttons, text=tr("Deactivate"), command=self.toggle_active)
        self._toggle.pack(side="left")
        ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.reload()
        self._name.focus_set()
        self.wait_visibility()
        self.grab_set()

    def reload(self, select_id: int | None = None) -> None:
        """Reload the user list and optionally select one user."""
        self.users.delete(*self.users.get_children())
        for user in self.session.scalars(select(User).order_by(User.name)):
            self.users.insert(
                "",
                "end",
                iid=str(user.id),
                values=(user.name, user.email or "", tr("yes") if user.is_active else tr("no")),
                tags=() if user.is_active else ("inactive",),
            )
        if select_id is not None:
            self.users.selection_set(str(select_id))
        self._show_selected()

    def _selected(self) -> User | None:
        """The selected user, or None."""
        selection = self.users.selection()
        return self.session.get(User, int(selection[0])) if selection else None

    def _show_selected(self) -> None:
        """Copy the selected user into the form."""
        user = self._selected()
        self._toggle.configure(text=tr("Activate") if user and not user.is_active else tr("Deactivate"))
        if user is None:
            return
        for entry, text in ((self._name, user.name), (self._email, user.email or "")):
            entry.delete(0, "end")
            entry.insert(0, text)

    def _change(self, action: Callable[[], User]) -> None:
        """Make a change (management module); show why if it is refused."""
        try:
            user = action()
        except ManagementError as error:
            messagebox.showwarning(tr("Users"), str(error), parent=self)
            self.reload()
        else:
            self.reload(user.id)

    def add(self) -> None:
        """Create a new user from the form."""
        self._change(lambda: management.add_user(self.session, self._name.get(), self._email.get()))

    def save(self) -> None:
        """Write the form to the selected user."""
        user = self._selected()
        if user is None:
            messagebox.showinfo(tr("Users"), tr("Select a user first."), parent=self)
            return
        self._change(lambda: management.update_user(
            self.session, user.id, self._name.get(), self._email.get()
        ))

    def toggle_active(self) -> None:
        """Deactivate or reactivate the selected user."""
        user = self._selected()
        if user is None:
            messagebox.showinfo(tr("Users"), tr("Select a user first."), parent=self)
            return
        self._change(lambda: management.set_user_active(self.session, user.id, not user.is_active))


class WorkflowsDialog(tk.Toplevel):
    """Modal window to manage workflows (progression types) and their stages."""

    @property
    def session(self) -> Session:
        """Where to read from; in server mode a fresh copy after every change."""
        return self.manage.session

    def __init__(self, master: tk.Misc, manage: LocalManagement | RemoteManagement) -> None:
        super().__init__(master)
        self.title(tr("Workflows"))
        self.manage = manage  # on the local database or on the server
        self.transient(master)  # type: ignore[arg-type]

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self.workflows = self._make_list(body, 0, ("Workflow",), (180,))
        self.stages = self._make_list(body, 1, ("Stage", "Final (done)"), (200, 90))
        self.workflows.bind("<<TreeviewSelect>>", lambda _event: self._show_stages())

        workflow_actions: list[tuple[str, Callable[[], None]]] = [
            (tr("Add"), self.add_workflow),
            (tr("Rename"), self.rename_workflow),
            (tr("Delete"), self.delete_workflow),
        ]
        stage_actions: list[tuple[str, Callable[[], None]]] = [
            (tr("Add"), self.add_stage),
            (tr("Rename"), self.rename_stage),
            (tr("Up"), lambda: self.shift_stage(-1)),
            (tr("Down"), lambda: self.shift_stage(1)),
            (tr("Toggle final"), self.toggle_final),
            (tr("Delete"), self.delete_stage),
        ]
        for column, actions in enumerate((workflow_actions, stage_actions)):
            buttons = ttk.Frame(body)
            buttons.grid(row=1, column=column, sticky="w", pady=(8, 0), padx=(0, 12))
            for label, command in actions:
                ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 4))
        ttk.Button(body, text=tr("Close"), command=self.destroy).grid(
            row=2, column=1, sticky="e", pady=(12, 0)
        )

        self.bind("<Escape>", lambda _event: self.destroy())
        self.reload()
        self.wait_visibility()
        self.grab_set()

    @staticmethod
    def _make_list(
        body: ttk.Frame, column: int, columns: tuple[str, ...], widths: tuple[int, ...]
    ) -> ttk.Treeview:
        """Create one of the two lists."""
        tree = ttk.Treeview(
            body, columns=columns, show="headings", selectmode="browse", height=8
        )
        for name, width in zip(columns, widths):
            tree.heading(name, text=tr(name))
            tree.column(name, width=width)
        tree.grid(row=0, column=column, sticky="nsew", padx=(0, 12))
        return tree

    # -- display ------------------------------------------------------------

    def reload(self, workflow_id: int | None = None, stage_id: int | None = None) -> None:
        """Reload both lists, selecting the given workflow (or the first) and stage."""
        self.workflows.delete(*self.workflows.get_children())
        for workflow in self.session.scalars(select(Workflow).order_by(Workflow.name)):
            self.workflows.insert("", "end", iid=str(workflow.id), values=(workflow.name,))
        items = self.workflows.get_children()
        if workflow_id is not None and str(workflow_id) in items:
            self.workflows.selection_set(str(workflow_id))
        elif items:
            self.workflows.selection_set(items[0])
        self._show_stages()
        if stage_id is not None and self.stages.exists(str(stage_id)):
            self.stages.selection_set(str(stage_id))

    def _show_stages(self) -> None:
        """List the stages of the selected workflow."""
        self.stages.delete(*self.stages.get_children())
        workflow = self._workflow(warn=False)
        for stage in workflow.stages if workflow else []:
            self.stages.insert(
                "", "end", iid=str(stage.id),
                values=(stage.name, tr("yes") if stage.is_final else ""),
            )

    # -- helpers ------------------------------------------------------------

    def _workflow(self, warn: bool = True) -> Workflow | None:
        """The selected workflow, or None."""
        selection = self.workflows.selection()
        workflow = self.session.get(Workflow, int(selection[0])) if selection else None
        if workflow is None and warn:
            messagebox.showinfo(tr("Workflows"), tr("Select a workflow first."), parent=self)
        return workflow

    def _stage(self) -> Stage | None:
        """The selected stage, or None."""
        selection = self.stages.selection()
        stage = self.session.get(Stage, int(selection[0])) if selection else None
        if stage is None:
            messagebox.showinfo(tr("Workflows"), tr("Select a stage first."), parent=self)
        return stage

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        """Ask for a name; None if cancelled or empty."""
        dialog = NameDialog(self, tr(title), initial)
        self.wait_window(dialog)
        return dialog.result

    def _change(self, action: Callable[[], Any]) -> Any:
        """Make a change (management module); show why and return None if it is refused."""
        try:
            return action()
        except ManagementError as error:
            messagebox.showwarning(tr("Workflows"), str(error), parent=self)
            return None

    # -- workflow actions ---------------------------------------------------

    def add_workflow(self) -> None:
        """Create a workflow with a starting "To do" and a final "Done" stage."""
        name = self._ask_name("New workflow")
        if name is not None:
            workflow = self._change(lambda: self.manage.add_workflow(name))
            self.reload(workflow.id if workflow else None)

    def rename_workflow(self) -> None:
        """Rename the selected workflow."""
        workflow = self._workflow()
        if workflow is None:
            return
        name = self._ask_name("Rename workflow", workflow.name)
        if name is not None:
            workflow_id = workflow.id
            self._change(lambda: self.manage.rename_workflow(workflow_id, name))
            self.reload(workflow_id)

    def delete_workflow(self) -> None:
        """Delete the selected workflow and its stages, if no task uses them."""
        workflow = self._workflow()
        if workflow is None:
            return
        if self._change(lambda: self.manage.check_delete_workflow(workflow.id)) is None:
            return
        question = tr('Delete workflow "{name}"?').format(name=workflow.name)
        if not messagebox.askyesno(tr("Delete"), question, parent=self):
            return
        workflow_id = workflow.id
        self._change(lambda: self.manage.delete_workflow(workflow_id))
        self.reload()

    # -- stage actions ------------------------------------------------------

    def add_stage(self) -> None:
        """Add a stage at the end of the selected workflow."""
        workflow = self._workflow()
        if workflow is None:
            return
        name = self._ask_name("New stage")
        if name is None:
            return
        workflow_id = workflow.id
        stage = self._change(lambda: self.manage.add_stage(workflow_id, name))
        self.reload(workflow_id, stage.id if stage else None)

    def rename_stage(self) -> None:
        """Rename the selected stage."""
        stage = self._stage()
        if stage is None:
            return
        name = self._ask_name("Rename stage", stage.name)
        if name is not None:
            stage_id, workflow_id = stage.id, stage.workflow_id
            self._change(lambda: self.manage.rename_stage(stage_id, name))
            self.reload(workflow_id, stage_id)

    def shift_stage(self, delta: int) -> None:
        """Move the selected stage up or down."""
        stage = self._stage()
        if stage is None:
            return
        stage_id, workflow_id = stage.id, stage.workflow_id
        self._change(lambda: self.manage.shift_stage(stage_id, delta))
        self.reload(workflow_id, stage_id)

    def toggle_final(self) -> None:
        """Switch whether tasks in the selected stage count as done."""
        stage = self._stage()
        if stage is not None:
            stage_id, workflow_id, final = stage.id, stage.workflow_id, not stage.is_final
            self._change(lambda: self.manage.set_stage_final(stage_id, final))
            self.reload(workflow_id, stage_id)

    def delete_stage(self) -> None:
        """Delete the selected stage, if no task is in it."""
        stage = self._stage()
        if stage is None:
            return
        if self._change(lambda: self.manage.check_delete_stage(stage.id)) is None:
            return
        question = tr('Delete stage "{name}"?').format(name=stage.name)
        if not messagebox.askyesno(tr("Delete"), question, parent=self):
            return
        stage_id, workflow_id = stage.id, stage.workflow_id
        self._change(lambda: self.manage.delete_stage(stage_id))
        self.reload(workflow_id)


class TagsDialog(tk.Toplevel):
    """Modal window to add, rename and delete tags."""

    @property
    def session(self) -> Session:
        """Where to read from; in server mode a fresh copy after every change."""
        return self.manage.session

    def __init__(self, master: tk.Misc, manage: LocalManagement | RemoteManagement) -> None:
        super().__init__(master)
        self.title(tr("Tags"))
        self.manage = manage  # on the local database or on the server
        self.transient(master)  # type: ignore[arg-type]

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.tags = ttk.Treeview(
            body, columns=("Tag", "Tasks"), show="headings", selectmode="browse", height=10
        )
        self.tags.heading("Tag", text=tr("Tag"))
        self.tags.heading("Tasks", text=tr("Tasks"))
        self.tags.column("Tag", width=200)
        self.tags.column("Tasks", width=70, anchor="e")
        self.tags.pack(fill="both", expand=True)
        self.tags.bind("<Double-1>", lambda _event: self.rename_tag())

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        actions: list[tuple[str, Callable[[], None]]] = [
            (tr("Add"), self.add_tag),
            (tr("Rename"), self.rename_tag),
            (tr("Delete"), self.delete_tag),
        ]
        for label, command in actions:
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 4))
        ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.reload()
        self.wait_visibility()
        self.grab_set()

    def reload(self, select_id: int | None = None) -> None:
        """Reload the tag list with the number of tasks using each tag."""
        self.tags.delete(*self.tags.get_children())
        for tag, used in self.manage.tag_usage():
            self.tags.insert("", "end", iid=str(tag.id), values=(tag.name, used))
        if select_id is not None and self.tags.exists(str(select_id)):
            self.tags.selection_set(str(select_id))

    def _selected(self) -> Tag | None:
        """The selected tag, or None (telling the user)."""
        selection = self.tags.selection()
        tag = self.session.get(Tag, int(selection[0])) if selection else None
        if tag is None:
            messagebox.showinfo(tr("Tags"), tr("Select a tag first."), parent=self)
        return tag

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        """Ask for a name; None if cancelled or empty."""
        dialog = NameDialog(self, tr(title), initial)
        self.wait_window(dialog)
        return dialog.result

    def _change(self, action: Callable[[], Any]) -> Any:
        """Make a change (management module); show why and return None if it is refused."""
        try:
            return action()
        except ManagementError as error:
            messagebox.showwarning(tr("Tags"), str(error), parent=self)
            return None

    def add_tag(self) -> None:
        """Create a new tag."""
        name = self._ask_name("New tag")
        if name is not None:
            tag = self._change(lambda: self.manage.add_tag(name))
            self.reload(tag.id if tag else None)

    def rename_tag(self) -> None:
        """Rename the selected tag; tasks keep it under the new name."""
        tag = self._selected()
        if tag is None:
            return
        name = self._ask_name("Rename tag", tag.name)
        if name is not None:
            tag_id = tag.id
            self._change(lambda: self.manage.rename_tag(tag_id, name))
            self.reload(tag_id)

    def delete_tag(self) -> None:
        """Delete the selected tag, if no task uses it."""
        tag = self._selected()
        if tag is None:
            return
        if self._change(lambda: self.manage.check_delete_tag(tag.id)) is None:
            return
        question = tr('Delete tag "{name}"?').format(name=tag.name)
        if not messagebox.askyesno(tr("Delete"), question, parent=self):
            return
        tag_id = tag.id
        self._change(lambda: self.manage.delete_tag(tag_id))
        self.reload()


class LocalTemplates:
    """The subtask templates of the local database (as plain data, like the server's)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[dict[str, Any]]:
        return [templates.template_data(t) for t in templates.list_templates(self.session)]

    def add(self, fields: dict[str, Any]) -> dict[str, Any]:
        return templates.template_data(templates.add_template(self.session, fields))

    def update(self, template_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        return templates.template_data(templates.update_template(self.session, template_id, fields))

    def delete(self, template_id: int) -> None:
        templates.delete_template(self.session, template_id)


class RemoteTemplates:
    """The subtask templates on the application server."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def list(self) -> list[dict[str, Any]]:
        return self.api.request("GET", "/subtask-templates")

    def add(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.api.request("POST", "/subtask-templates", fields)

    def update(self, template_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        return self.api.request("PATCH", f"/subtask-templates/{template_id}", fields)

    def delete(self, template_id: int) -> None:
        self.api.request("DELETE", f"/subtask-templates/{template_id}")


class SubtaskTemplatesDialog(tk.Toplevel):
    """Modal window with the editable list of subtask templates.

    With a parent task's name it also adds subtasks: `chosen` then holds the
    templates selected when "Add as subtasks" was pressed (several with Ctrl or
    Shift), or a double-clicked one.
    """

    def __init__(
        self, master: tk.Misc, store: LocalTemplates | RemoteTemplates,
        parent_name: str | None = None,
    ) -> None:
        super().__init__(master)
        self.title(tr("Subtask templates"))
        self.store = store
        self.chosen: list[dict[str, Any]] = []
        self._items: dict[str, dict[str, Any]] = {}
        self.transient(master)  # type: ignore[arg-type]

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        if parent_name is not None:
            ttk.Label(
                body, text=tr('Add subtasks to "{name}" (Ctrl+click chooses several):').format(
                    name=parent_name), wraplength=560, justify="left",
            ).pack(anchor="w", pady=(0, 6))

        panes = ttk.Frame(body)
        panes.pack(fill="both", expand=True)
        columns = ("Template", "Priority", "Urgency")
        self.list = ttk.Treeview(
            panes, columns=columns, show="headings", height=12,
            selectmode="extended" if parent_name is not None else "browse",
        )
        for column, width in zip(columns, (220, 90, 90)):
            self.list.heading(column, text=tr(column))
            self.list.column(column, width=width, stretch=column == "Template")
        self.list.pack(side="left", fill="both", expand=True)
        self.list.bind("<<TreeviewSelect>>", lambda _event: self._show_selected())
        if parent_name is not None:
            self.list.bind("<Double-1>", lambda _event: self.add_subtasks())

        form = ttk.Frame(panes, padding=(12, 0, 0, 0))
        form.pack(side="left", fill="y")
        ttk.Label(form, text=tr("Name")).grid(row=0, column=0, sticky="w")
        self._name = ttk.Entry(form, width=32)
        self._name.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(form, text=tr("Description")).grid(row=2, column=0, sticky="w")
        self._description = tk.Text(form, width=32, height=5, wrap="word")
        self._description.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(form, text=tr("Priority")).grid(row=4, column=0, sticky="w")
        ttk.Label(form, text=tr("Urgency")).grid(row=4, column=1, sticky="w", padx=(6, 0))
        self._priority = Choice(form, [(tr(p.name), p.name) for p in Priority], "Normal")
        self._priority.configure(width=12)
        self._priority.grid(row=5, column=0, sticky="w")
        self._urgency = Choice(form, [(tr(u.name), u.name) for u in Urgency], "Medium")
        self._urgency.configure(width=12)
        self._urgency.grid(row=5, column=1, sticky="w", padx=(6, 0))
        edit = ttk.Frame(form)
        edit.grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        for label, command in (
            (tr("Add"), self.add_template),
            (tr("Save"), self.save_template),
            (tr("Delete"), self.delete_template),
            (tr("Clear"), self.clear_form),
        ):
            ttk.Button(edit, text=label, command=command).pack(side="left", padx=(0, 4))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        if parent_name is not None:
            ttk.Button(buttons, text=tr("Cancel"), command=self.destroy).pack(side="right")
            ttk.Button(
                buttons, text=tr("Add as subtasks"), command=self.add_subtasks, default="active"
            ).pack(side="right", padx=(0, 4))
        else:
            ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        if self.reload() is None:
            self.after_idle(self.destroy)  # the list could not be loaded (already said why)
            return
        self.wait_visibility()
        self.grab_set()
        self.list.focus_set()

    def _change(self, action: Callable[[], Any]) -> Any:
        """Run a change; show why and return None if it is refused or fails."""
        try:
            return action()
        except ValueError as error:  # ManagementError, or RemoteError from the server
            messagebox.showwarning(tr("Subtask templates"), str(error), parent=self)
            return None

    def reload(self, select_id: int | None = None) -> list[dict[str, Any]] | None:
        """Fill the list again; None if the templates could not be loaded."""
        items = self._change(self.store.list)
        if items is None:
            return None
        self.list.delete(*self.list.get_children())
        self._items = {str(item["id"]): item for item in items}
        for iid, item in self._items.items():
            self.list.insert("", "end", iid=iid, values=(
                item["name"], tr(item["priority"]), tr(item["urgency"])
            ))
        if select_id is not None and self.list.exists(str(select_id)):
            self.list.selection_set(str(select_id))
            self.list.see(str(select_id))
        return items

    def _selected(self) -> list[dict[str, Any]]:
        return [self._items[iid] for iid in self.list.selection() if iid in self._items]

    def _show_selected(self) -> None:
        """Put the selected template in the form (the first, if several)."""
        selected = self._selected()
        if not selected:
            return
        item = selected[0]
        self._name.delete(0, "end")
        self._name.insert(0, item["name"])
        self._description.delete("1.0", "end")
        self._description.insert("1.0", item["description"] or "")
        self._priority.set_options(self._priority._choices, item["priority"])
        self._urgency.set_options(self._urgency._choices, item["urgency"])

    def _form(self) -> dict[str, Any]:
        return {
            "name": self._name.get().strip(),
            "description": self._description.get("1.0", "end").strip() or None,
            "priority": self._priority.value(),
            "urgency": self._urgency.value(),
        }

    def clear_form(self) -> None:
        """Empty the form for a new template."""
        self.list.selection_set(())
        self._name.delete(0, "end")
        self._description.delete("1.0", "end")
        self._priority.set_options(self._priority._choices, "Normal")
        self._urgency.set_options(self._urgency._choices, "Medium")
        self._name.focus_set()

    def add_template(self) -> None:
        """A new template from the form."""
        added = self._change(lambda: self.store.add(self._form()))
        if added is not None:
            self.reload(added["id"])

    def save_template(self) -> None:
        """Save the form into the selected template."""
        selected = self._selected()
        if len(selected) != 1:
            messagebox.showinfo(
                tr("Subtask templates"), tr("Select one template to change."), parent=self
            )
            return
        template_id = selected[0]["id"]
        if self._change(lambda: self.store.update(template_id, self._form())) is not None:
            self.reload(template_id)

    def delete_template(self) -> None:
        """Delete the selected templates (subtasks made from them stay)."""
        selected = self._selected()
        if not selected:
            messagebox.showinfo(tr("Subtask templates"), tr("Select a template first."), parent=self)
            return
        names = ", ".join(f'"{item["name"]}"' for item in selected)
        question = tr("Delete template(s) {names}?").format(names=names)
        if not messagebox.askyesno(tr("Delete"), question, parent=self):
            return
        for item in selected:
            if self._change(lambda item=item: self.store.delete(item["id"])) is None:
                break
        self.reload()

    def add_subtasks(self) -> None:
        """Close the window with the selected templates as the subtasks to add."""
        self.chosen = self._selected()
        if not self.chosen:
            messagebox.showinfo(tr("Subtask templates"), tr("Select a template first."), parent=self)
            return
        self.destroy()


class RandomTaskWindow(tk.Toplevel):
    """A task drawn at random (see todo_db.pick), with buttons to draw another or find it."""

    def __init__(self, master: TodoApp) -> None:
        super().__init__(master)
        self.app = master
        self.title(tr("Random task"))
        self.transient(master)
        self.resizable(False, False)
        self.task: Task | None = None

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        heading = tkfont.nametofont("TkDefaultFont").copy()
        heading.configure(size=heading.cget("size") + 4, weight="bold")
        self._font = heading  # keep a reference, or Tk drops the font
        self._name = ttk.Label(body, font=heading, wraplength=420, justify="left")
        self._name.pack(anchor="w")
        self._parent = ttk.Label(body, foreground="gray40", wraplength=420, justify="left")
        self._parent.pack(anchor="w")
        levels = ttk.Frame(body)
        levels.pack(anchor="w", pady=(8, 0))
        self._priority = tk.Label(levels, padx=6, pady=2, foreground="black")
        self._priority.pack(side="left")
        self._urgency = tk.Label(levels, padx=6, pady=2, foreground="black")
        self._urgency.pack(side="left", padx=(6, 0))
        self._details = ttk.Label(body, wraplength=420, justify="left")
        self._details.pack(anchor="w", pady=(8, 0))
        self._description = ttk.Label(body, wraplength=420, justify="left")

        self._buttons = buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=tr("Show in list"), command=self.show_in_list).pack(
            side="right", padx=(0, 4)
        )
        ttk.Button(buttons, text=tr("Another"), command=self.draw, default="active").pack(
            side="right", padx=(0, 4)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self.draw())
        self.draw()

    def draw(self) -> None:
        """Draw a task (another one than shown, if there is another)."""
        candidates = self.app.random_candidates()
        if self.task is not None and len(candidates) > 1:
            candidates = [task for task in candidates if task.id != self.task.id]
        self.task = task = pick.pick_task(
            candidates, lambda t: (t.priority.name, t.urgency.name)
        )
        if task is None:
            self.destroy()
            return
        self._name.configure(text=task.name)
        path = []
        parent = task.parent
        while parent is not None:
            path.insert(0, parent.name)
            parent = parent.parent
        self._parent.configure(text=" › ".join(path))
        for widget, caption, level in (
            (self._priority, "Priority", task.priority), (self._urgency, "Urgency", task.urgency)
        ):
            widget.configure(text=f"{tr(caption)}: {tr(level.name)}",
                             background=LEVEL_COLOURS[int(level)])
        details = [f"{tr('Stage')}: {task.stage.name}"]
        if task.due_date is not None:
            details.append(f"{tr('Due date')}: {task.due_date.isoformat()}")
        if task.assignee is not None:
            details.append(f"{tr('Assignee')}: {task.assignee.name}")
        if task.location:
            details.append(f"{tr('Location')}: {task.location}")
        self._details.configure(text=" · ".join(details))
        self._description.configure(text=task.description or "")
        if task.description:  # shown only when there is one
            self._description.pack(anchor="w", pady=(6, 0), before=self._buttons)
        else:
            self._description.pack_forget()

    def show_in_list(self) -> None:
        """Select the task in the list (clearing the filters if they hide it) and close."""
        task_id = self.task.id if self.task else None
        self.destroy()
        if task_id is not None:
            self.app.show_task(task_id)


class ReminderWindow(tk.Toplevel):
    """The reminder: every due task on an orange background, until the user closes it."""

    MAX_TASKS = 20  # more would not fit on the screen; the rest are counted

    def __init__(self, master: tk.Misc, background: str, font_size: int) -> None:
        super().__init__(master)
        try:
            self.configure(background=background)
        except tk.TclError:  # not a colour Tk knows
            background = reminders.BACKGROUND
            self.configure(background=background)
        self._colours = {"background": background, "foreground": "black"}
        self.title(tr("Task reminder"))
        self.resizable(False, False)
        self.attributes("-topmost", True)  # above other programs' windows
        self._font = tkfont.Font(self, size=font_size)
        heading = tkfont.Font(self, size=font_size + 4, weight="bold")

        tk.Label(self, text=tr("Task reminder"), font=heading, **self._colours).pack(
            anchor="w", padx=24, pady=(18, 10)
        )
        self._list = tk.Frame(self, background=background)
        self._list.pack(anchor="w", fill="x", padx=24)
        tk.Button(
            self, text=tr("Close"), font=self._font, command=self.destroy,
            activebackground="white", highlightthickness=0, **self._colours,
        ).pack(pady=(14, 18))
        self.bind("<Escape>", lambda _event: self.destroy())

    def show(self, tasks: list[DueTask]) -> None:
        """Put the tasks one under another, overdue ones with their date."""
        for child in self._list.winfo_children():
            child.destroy()
        today = date.today()
        for task in tasks[: self.MAX_TASKS]:
            text = f"•  {task.name}"
            if task.due_date < today:
                text += "  " + tr("(overdue since {date})").format(date=task.due_date.isoformat())
            tk.Label(
                self._list, text=text, font=self._font, anchor="w", justify="left",
                wraplength=self._font.measure("m") * 40, **self._colours,
            ).pack(anchor="w", pady=2)
        if len(tasks) > self.MAX_TASKS:
            more = tr("…and {n} more").format(n=len(tasks) - self.MAX_TASKS)
            tk.Label(self._list, text=more, font=self._font, **self._colours).pack(anchor="w")


def use_logo(window: tk.Tk) -> None:
    """Show the program's logo as the icon of this window and of all its dialogs."""
    from .tray import LOGO_FILE

    try:
        window._logo = tk.PhotoImage(master=window, file=str(LOGO_FILE))  # type: ignore[attr-defined]
        window.iconphoto(True, window._logo)  # type: ignore[attr-defined]
    except tk.TclError:  # missing or unreadable: Tk's own icon stays
        pass


_db_override: Path | None = None  # --db or TODO_DB: this run only, not saved


def database_path() -> Path:
    """Local mode's database file: --db / TODO_DB, else the one chosen last, else todo.db."""
    if _db_override is not None:
        return _db_override
    saved = settings.load_setting(DB_SETTING)
    return Path(saved).expanduser() if isinstance(saved, str) and saved.strip() else DB_FILE


def save_database_path(path: Path) -> None:
    """Use this database file from now on (also at the next start)."""
    global _db_override
    _db_override = None
    path = path.expanduser()
    settings.save_setting(DB_SETTING, None if path == DB_FILE else str(path.resolve()))


def choose_database_file(parent: tk.Misc, current: Path) -> Path | None:
    """Ask for a database file: an existing one, or a new name to start an empty one."""
    current = current.expanduser().resolve()
    chosen = filedialog.asksaveasfilename(
        parent=parent,
        title=tr("Database file"),
        initialdir=str(current.parent),
        initialfile=current.name,
        defaultextension=".db",
        filetypes=[(tr("Databases"), "*.db *.sqlite *.sqlite3"), (tr("All files"), "*")],
        confirmoverwrite=False,  # an existing file is opened, not replaced
    )
    return Path(chosen) if chosen else None


class LoginWindow(tk.Tk):
    """First window: work on this computer, or log in to a server.

    `result` is ("local", None), ("server", account) or None if cancelled.
    """

    def __init__(self) -> None:
        super().__init__()
        use_logo(self)
        self.title(tr("To-do list"))
        self.resizable(False, False)
        self.result: tuple[str, RemoteAccount | None] | None = None

        body = ttk.Frame(self, padding=16)
        body.pack()
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text=tr("Where are your tasks?")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self._mode = tk.StringVar(self, settings.load_setting("client_mode") or "local")
        for row, (text, value) in enumerate(
            ((tr("On this computer"), "local"), (tr("On a server"), "server")), start=1
        ):
            ttk.Radiobutton(
                body, text=text, value=value, variable=self._mode, command=self._update
            ).grid(row=row * 2 - 1, column=0, columnspan=2, sticky="w",
                   pady=(6 if row == 1 else 0, 0))

        # Local mode: which database file (row 2, under its button).
        db_label = ttk.Label(body, text=tr("Database file"))
        db_label.grid(row=2, column=0, sticky="w", padx=(18, 10), pady=3)
        db_row = ttk.Frame(body)
        db_row.grid(row=2, column=1, sticky="ew", pady=3)
        self._database = ttk.Entry(db_row, width=28)
        self._database.insert(0, str(database_path()))
        self._database.pack(side="left", fill="x", expand=True)
        browse = ttk.Button(db_row, text=tr("Browse…"), command=self._browse)
        browse.pack(side="left", padx=(4, 0))
        self._local_widgets: list[tk.Widget] = [db_label, self._database, browse]

        self._url = ttk.Entry(body, width=36)
        self._url.insert(0, settings.load_setting("server_url") or "http://127.0.0.1:8000")
        self._email = ttk.Entry(body, width=36)
        self._email.insert(0, settings.load_setting("server_email") or "")
        self._password = ttk.Entry(body, width=36, show="•")
        self._remember = tk.BooleanVar(self, True)
        self._server_widgets: list[tk.Widget] = []
        rows = ((tr("Server address"), self._url), (tr("Email"), self._email),
                (tr("Password"), self._password))
        for row, (label, entry) in enumerate(rows, start=4):
            text = ttk.Label(body, text=label)
            text.grid(row=row, column=0, sticky="w", padx=(18, 10), pady=3)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self._server_widgets += [text, entry]
        remember = ttk.Checkbutton(
            body, text=tr("Remember me on this computer"), variable=self._remember
        )
        remember.grid(row=7, column=1, sticky="w", pady=(2, 0))
        self._server_widgets.append(remember)

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=tr("OK"), command=self._ok).pack(side="right", padx=6)

        self.bind("<Return>", lambda _event: self._ok())
        self.bind("<Escape>", lambda _event: self.destroy())
        self._update()
        (self._password if self._email.get() else self._email).focus_set()

    def _update(self) -> None:
        """The server fields only matter in server mode."""
        server = self._mode.get() == "server"
        for widgets, on in ((self._server_widgets, server), (self._local_widgets, not server)):
            for widget in widgets:
                widget.configure(state="normal" if on else "disabled")  # type: ignore[call-arg]

    def _browse(self) -> None:
        chosen = choose_database_file(self, Path(self._database.get().strip() or DB_FILE))
        if chosen is not None:
            self._database.delete(0, "end")
            self._database.insert(0, str(chosen))

    def _ok(self) -> None:
        """Start local mode, or log in to the server."""
        mode = self._mode.get()
        if mode == "local":
            settings.save_setting("client_mode", mode)
            path = Path(self._database.get().strip() or DB_FILE).expanduser()
            if path != database_path():
                save_database_path(path)
            self.result = ("local", None)
            self.destroy()
            return
        url, email, password = self._url.get().strip(), self._email.get().strip(), self._password.get()
        if not url or not email or not password:
            messagebox.showwarning(tr("To-do list"), tr("Enter email and password."), parent=self)
            return
        self.configure(cursor="watch")
        self.update()
        try:
            account = log_in(url, email, password, self._remember.get())
        except RemoteError as error:
            self.configure(cursor="")
            messagebox.showerror(tr("To-do list"), str(error), parent=self)
            return
        for key, value in (("client_mode", mode), ("server_url", url), ("server_email", email)):
            settings.save_setting(key, value)
        self.result = ("server", account)
        self.destroy()


class ServerSettingsDialog(tk.Toplevel):
    """Server settings for administrators: automatic history compression."""

    def __init__(self, master: tk.Misc, account: RemoteAccount, current: dict[str, Any]) -> None:
        super().__init__(master)
        self.title(tr("Server settings"))
        self.account = account
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)

        body = ttk.Frame(self, padding=14)
        body.pack()
        self._enabled = tk.BooleanVar(self, current["auto_compress_enabled"])
        ttk.Checkbutton(
            body, text=tr("Compress old history automatically"), variable=self._enabled,
            command=self._update,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text=tr("Compress history older than (days)")).grid(
            row=1, column=0, sticky="w", padx=(18, 10), pady=(8, 0)
        )
        self._days = ttk.Spinbox(body, from_=0, to=36500, width=7)
        self._days.set(current["compress_after_days"])
        self._days.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(
            body,
            text=tr(COMPRESSION_NOTE),
            wraplength=360, justify="left", foreground="gray40",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=tr("OK"), command=self._ok).pack(side="right", padx=6)

        self.bind("<Escape>", lambda _event: self.destroy())
        self._update()
        self.wait_visibility()
        self.grab_set()

    def _update(self) -> None:
        """The number of days only matters when compression is on."""
        self._days.configure(state="normal" if self._enabled.get() else "disabled")

    def _ok(self) -> None:
        """Validate and save the settings on the server."""
        try:
            days = int(self._days.get())
        except ValueError:
            days = -1
        if not 0 <= days <= 36500:
            messagebox.showwarning(
                tr("Server settings"), tr("Days must be a whole number, 0 or more."), parent=self
            )
            return
        try:
            self.account.save_settings(
                {"auto_compress_enabled": self._enabled.get(), "compress_after_days": days}
            )
        except RemoteError as error:
            messagebox.showerror(tr("Server settings"), str(error), parent=self)
            return
        self.destroy()


class RemoteUsersDialog(tk.Toplevel):
    """Users window for administrators in server mode: accounts, passwords, roles."""

    def __init__(self, master: tk.Misc, account: RemoteAccount) -> None:
        super().__init__(master)
        self.title(tr("Users"))
        self.account = account
        self.transient(master)  # type: ignore[arg-type]
        self._users: dict[str, dict[str, Any]] = {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        columns = ("Name", "Email", "Role", "Active")
        self.users = ttk.Treeview(
            body, columns=columns, show="headings", selectmode="browse", height=8
        )
        for column, width in zip(columns, (170, 210, 110, 60)):
            self.users.heading(column, text=tr(column))
            self.users.column(column, width=width)
        self.users.tag_configure("inactive", foreground="gray55")
        self.users.pack(fill="both", expand=True)
        self.users.bind("<<TreeviewSelect>>", lambda _event: self._show_selected())

        form = ttk.Frame(body)
        form.pack(fill="x", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        self._name = ttk.Entry(form)
        self._email = ttk.Entry(form)
        self._password = ttk.Entry(form, show="•")
        self._admin = tk.BooleanVar(self, False)
        rows = (
            (tr("Name"), self._name),
            (tr("Email"), self._email),
            (tr("New password (empty = keep)"), self._password),
        )
        for row, (label, entry) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(form, text=tr("Administrator"), variable=self._admin).grid(
            row=3, column=1, sticky="w"
        )

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text=tr("Add as new"), command=self.add).pack(side="left")
        ttk.Button(buttons, text=tr("Save changes"), command=self.save).pack(side="left", padx=6)
        self._toggle = ttk.Button(buttons, text=tr("Deactivate"), command=self.toggle_active)
        self._toggle.pack(side="left")
        ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.reload()
        self.wait_visibility()
        self.grab_set()

    def _call(self, action: Callable[[], Any]) -> Any:
        """Run a server call; show its error and return None if it fails."""
        try:
            return action()
        except RemoteError as error:
            messagebox.showerror(tr("Users"), str(error), parent=self)
            return None

    def reload(self, select_id: int | None = None) -> None:
        """Fetch the accounts from the server."""
        users = self._call(self.account.list_users)
        if users is None:
            return
        self.users.delete(*self.users.get_children())
        self._users = {str(user["id"]): user for user in users}
        for user in users:
            self.users.insert(
                "", "end", iid=str(user["id"]),
                values=(
                    user["name"], user["email"] or "", tr(user["role"]),
                    tr("yes") if user["is_active"] else tr("no"),
                ),
                tags=() if user["is_active"] else ("inactive",),
            )
        if select_id is not None and self.users.exists(str(select_id)):
            self.users.selection_set(str(select_id))
        self._show_selected()

    def _selected(self) -> dict[str, Any] | None:
        """The selected account, or None."""
        selection = self.users.selection()
        return self._users.get(selection[0]) if selection else None

    def _show_selected(self) -> None:
        """Copy the selected account into the form."""
        user = self._selected()
        inactive = user is not None and not user["is_active"]
        self._toggle.configure(text=tr("Activate") if inactive else tr("Deactivate"))
        if user is None:
            return
        for entry, text in ((self._name, user["name"]), (self._email, user["email"] or "")):
            entry.delete(0, "end")
            entry.insert(0, text)
        self._password.delete(0, "end")
        self._admin.set(user["role"] == "Admin")

    def _form(self) -> dict[str, Any] | None:
        """The form as API fields, or None (with a message) if name or email is missing."""
        name, email = self._name.get().strip(), self._email.get().strip()
        if not name or not email:
            messagebox.showwarning(tr("Users"), tr("Enter name and email."), parent=self)
            return None
        fields = {"name": name, "email": email, "role": "Admin" if self._admin.get() else "User"}
        if self._password.get():
            fields["password"] = self._password.get()
        return fields

    def add(self) -> None:
        """Create a new account from the form."""
        fields = self._form()
        if fields is not None:
            user = self._call(lambda: self.account.create_user(fields))
            if user:
                self.reload(user["id"])

    def save(self) -> None:
        """Write the form to the selected account."""
        user = self._selected()
        if user is None:
            messagebox.showinfo(tr("Users"), tr("Select a user first."), parent=self)
            return
        fields = self._form()
        if fields is not None and self._call(lambda: self.account.update_user(user["id"], fields)):
            self.reload(user["id"])

    def toggle_active(self) -> None:
        """Deactivate or reactivate the selected account."""
        user = self._selected()
        if user is None:
            messagebox.showinfo(tr("Users"), tr("Select a user first."), parent=self)
            return
        change = {"is_active": not user["is_active"]}
        if self._call(lambda: self.account.update_user(user["id"], change)):
            self.reload(user["id"])


@dataclass(frozen=True)
class Filter:
    """One choice of a column filter: its test, and a key that names it in saved presets.

    Keys do not depend on the language or on names that can be changed:
    "not-done", "overdue", "Important", "id:3" (a user, tag or repeat rule).
    """

    key: str
    test: Predicate

    def __call__(self, task: Task) -> bool:
        return self.test(task)


class MultiChoice(ttk.Combobox):
    """A column filter where several choices can be ticked; a task passes if it matches any.

    Looks like the other drop-downs; clicking it opens a list in which each click
    ticks or unticks a choice (the list stays open; Escape, Enter or a click
    elsewhere closes it). "All" unticks everything. on_change is called after
    every change made in the list.
    """

    MAX_ROWS = 15  # a longer list scrolls

    def __init__(
        self, master: tk.Misc, options: list[tuple[str, Filter | None]],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, state="readonly")
        self._on_change = on_change
        self._filters: list[tuple[str, Filter]] = []
        self._chosen: list[str] = []  # the keys ticked
        self._popup: tk.Toplevel | None = None
        self.set_options(options)
        for sequence in ("<Button-1>", "<Down>", "<space>"):
            self.bind(sequence, self._open)
        self.bind("<MouseWheel>", lambda _event: "break")  # would step through the values
        self.bind("<Button-4>", lambda _event: "break")
        self.bind("<Button-5>", lambda _event: "break")

    def set_options(self, options: list[tuple[str, Filter | None]]) -> None:
        """Replace the choices ("All" = None is left out), keeping the ticks still possible."""
        self._filters = [(label, value) for label, value in options if value is not None]
        known = {value.key for _label, value in self._filters}
        self._chosen = [key for key in self._chosen if key in known]
        self._show()

    def chosen_keys(self) -> list[str]:
        """The keys ticked, in the order of the list."""
        return [value.key for _label, value in self._filters if value.key in self._chosen]

    def set_keys(self, keys: list[str]) -> bool:
        """Tick these keys (none = All); False if some of them are not choices (left out)."""
        known = {value.key for _label, value in self._filters}
        self._chosen = [key for key in keys if key in known]
        self._show()
        return len(self._chosen) == len(set(keys))

    def test(self) -> Predicate | None:
        """Whether a task passes: it matches one of the ticked choices (None = all pass)."""
        tests = [value for _label, value in self._filters if value.key in self._chosen]
        if not tests:
            return None
        return lambda task: any(test(task) for test in tests)

    def _show(self) -> None:
        labels = [label for label, value in self._filters if value.key in self._chosen]
        self.set(", ".join(labels) if labels else tr("All"))

    def _open(self, _event: tk.Event | None = None) -> str:
        if self._popup is not None:
            self._close()
            return "break"
        self._popup = popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        frame = tk.Frame(popup, borderwidth=1, relief="solid", background="white")
        frame.pack(fill="both", expand=True)
        ttk.Button(frame, text=tr("All"), command=self._clear).pack(fill="x")
        rows = ttk.Frame(frame)
        rows.pack(fill="both", expand=True)
        labels = [label for label, _value in self._filters]
        self._listbox = listbox = tk.Listbox(
            rows, selectmode="multiple", exportselection=False, activestyle="none",
            height=max(1, min(len(labels), self.MAX_ROWS)), borderwidth=0,
            selectbackground="#3B73B9", selectforeground="white",  # ticked: clearly marked
            width=max([len(label) for label in labels] + [10]) + 2,
        )
        listbox.pack(side="left", fill="both", expand=True)
        if len(labels) > self.MAX_ROWS:
            bar = ttk.Scrollbar(rows, orient="vertical", command=listbox.yview)
            bar.pack(side="right", fill="y")
            listbox.configure(yscrollcommand=bar.set)
        for index, (label, value) in enumerate(self._filters):
            listbox.insert("end", label)
            if value.key in self._chosen:
                listbox.selection_set(index)
        listbox.bind("<<ListboxSelect>>", lambda _event: self._ticked())
        for sequence in ("<Escape>", "<Return>"):
            popup.bind(sequence, lambda _event: self._close())
        popup.bind("<ButtonPress>", self._clicked)

        popup.update_idletasks()
        width = max(self.winfo_width(), popup.winfo_reqwidth())
        height = popup.winfo_reqheight()
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - width)
        y = self.winfo_rooty() + self.winfo_height()
        if y + height > self.winfo_screenheight():
            y = self.winfo_rooty() - height  # no room below: above the filter
        popup.wm_geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        popup.grab_set()  # clicks elsewhere come here, and close the list
        listbox.focus_set()
        return "break"

    def _clicked(self, event: tk.Event) -> None:
        popup = self._popup
        if popup is None:
            return
        inside = (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
                  and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty()
                  + popup.winfo_height())
        if not inside:
            self._close()

    def _ticked(self) -> None:
        self._chosen = [self._filters[index][1].key for index in self._listbox.curselection()]
        self._changed()

    def _clear(self) -> None:
        self._listbox.selection_clear(0, "end")
        self._chosen = []
        self._changed()

    def _changed(self) -> None:
        self._show()
        if self._on_change is not None:
            self._on_change()

    def _close(self) -> None:
        if self._popup is not None:
            self._popup.grab_release()
            self._popup.destroy()
            self._popup = None
            self.focus_set()


class PresetForm(tk.Toplevel):
    """Modal form for one filter preset: its name and filters; `result` holds it on OK."""

    def __init__(
        self, master: TodoApp, preset: FilterPreset, taken: set[str], title: str
    ) -> None:
        """taken: names of the other presets (case is ignored), which this one may not use."""
        super().__init__(master)
        self.title(title)
        self.result: FilterPreset | None = None
        self._taken = {name.casefold() for name in taken}
        self.transient(master)
        self.resizable(False, False)

        form = ttk.Frame(self, padding=12)
        form.grid()
        form.columnconfigure(1, weight=1)
        self._name = ttk.Entry(form, width=36)
        self._name.insert(0, preset.name)
        self._text = ttk.Entry(form, width=36)
        self._text.insert(0, preset.text)
        rows: list[tuple[str, tk.Widget]] = [
            (tr("Preset name"), self._name), (tr("Task name contains"), self._text)
        ]
        self._choices: dict[str, MultiChoice] = {}
        for column in TASK_COLUMNS:
            choice = MultiChoice(form, master._filter_options(column))
            choice.set_keys(filter_keys(preset.filters.get(column)))
            self._choices[column] = choice
            rows.append((tr(column), choice))
        for row, (label, widget) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            widget.grid(row=row, column=1, sticky="ew", pady=3)

        buttons = ttk.Frame(form)
        buttons.grid(row=len(rows), column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=tr("OK"), command=self._ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._ok())
        self._name.focus_set()
        self.wait_visibility()
        self.grab_set()

    def _ok(self) -> None:
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning(self.title(), tr("The preset needs a name."), parent=self)
            return
        if name.casefold() in self._taken:
            messagebox.showwarning(
                self.title(), tr('A preset named "{name}" already exists.').format(name=name),
                parent=self,
            )
            return
        filters = {
            column: value
            for column, choice in self._choices.items()
            if (value := filter_value(choice.chosen_keys())) is not None
        }
        self.result = FilterPreset(name, self._text.get().strip(), filters)
        self.destroy()


class PresetsDialog(tk.Toplevel):
    """A list of saved presets (filters or sort orders): apply, add, edit, delete, reorder.

    presets is the app's own list, changed in place; changed() saves it.
    add(parent) and edit(index, parent) open the preset's form and say whether it was saved.
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        presets: list[Any],
        apply: Callable[[int], None],
        add: Callable[[tk.Misc], bool],
        edit: Callable[[int, tk.Misc], bool],
        changed: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.presets, self._apply, self._add, self._edit, self._changed = (
            presets, apply, add, edit, changed
        )
        self.transient(master)  # type: ignore[arg-type]
        self.minsize(380, 260)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._list = tk.Listbox(body, height=10, exportselection=False, activestyle="none")
        self._list.grid(row=0, column=0, sticky="nsew")
        self._list.bind("<Double-1>", lambda _event: self.apply())
        self._list.bind("<Return>", lambda _event: self.apply())

        side = ttk.Frame(body)
        side.grid(row=0, column=1, sticky="n", padx=(10, 0))
        actions: list[tuple[str, Callable[[], None]]] = [
            (tr("Apply"), self.apply),
            (tr("Add…"), self.add),
            (tr("Edit…"), self.edit),
            (tr("Delete"), self.delete),
            (tr("Up"), lambda: self.shift(-1)),
            (tr("Down"), lambda: self.shift(1)),
        ]
        for label, command in actions:
            ttk.Button(side, text=label, command=command).pack(fill="x", pady=(0, 4))
        ttk.Button(body, text=tr("Close"), command=self.destroy).grid(
            row=1, column=1, sticky="e", pady=(10, 0)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        self.reload(0)
        self.wait_visibility()
        self.grab_set()

    def reload(self, select: int | None = None) -> None:
        self._list.delete(0, "end")
        for preset in self.presets:
            self._list.insert("end", preset.name)
        if select is not None and self.presets:
            select = max(0, min(select, len(self.presets) - 1))
            self._list.selection_set(select)
            self._list.see(select)

    def _selected(self) -> int | None:
        picked = self._list.curselection()
        if not picked:
            messagebox.showinfo(self.title(), tr("Select a preset first."), parent=self)
            return None
        return int(picked[0])

    def apply(self) -> None:
        index = self._selected()
        if index is not None:
            self._apply(index)

    def add(self) -> None:
        """A new preset, starting from what is now set in the main window."""
        if self._add(self):
            self.reload(len(self.presets) - 1)
        self.grab_set()  # the form took the grab; this window is modal again

    def edit(self) -> None:
        index = self._selected()
        if index is None:
            return
        if self._edit(index, self):
            self.reload(index)
        self.grab_set()

    def delete(self) -> None:
        index = self._selected()
        if index is None:
            return
        name = self.presets[index].name
        if messagebox.askyesno(
            tr("Delete"), tr('Delete preset "{name}"?').format(name=name), parent=self
        ):
            del self.presets[index]
            self._changed()
            self.reload(index)

    def shift(self, delta: int) -> None:
        index = self._selected()
        if index is None or not 0 <= index + delta < len(self.presets):
            return
        presets = self.presets
        presets[index], presets[index + delta] = presets[index + delta], presets[index]
        self._changed()
        self.reload(index + delta)


class SortDialog(tk.Toplevel):
    """Modal window to arrange a list's sort order; `result` holds it on OK."""

    def __init__(
        self,
        master: tk.Misc,
        sort: list[tuple[str, bool]],
        preset_name: str | None = None,
        taken: set[str] = frozenset(),  # type: ignore[assignment]
        title: str | None = None,
        fields: tuple[str, ...] = SORT_FIELDS,
    ) -> None:
        """With preset_name (even ""), it edits a sort preset: the name is asked too
        and may not be one of `taken` (case is ignored). `fields`: what can be sorted by."""
        super().__init__(master)
        self.title(title or tr("Sorting"))
        self.result: list[tuple[str, bool]] | None = None
        self.result_name = ""
        self._taken = {name.casefold() for name in taken}
        self._sort = list(sort)
        self._fields = fields
        self._free: list[str] = []
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)

        self._name: ttk.Entry | None = None
        if preset_name is not None:
            top = ttk.Frame(self, padding=(12, 12, 12, 0))
            top.pack(fill="x")
            ttk.Label(top, text=tr("Preset name")).pack(side="left")
            self._name = ttk.Entry(top, width=36)
            self._name.insert(0, preset_name)
            self._name.pack(side="left", padx=(10, 0))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr("Available fields")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, text=tr("Sort by (first = most important)")).grid(
            row=0, column=2, sticky="w"
        )

        self._available = tk.Listbox(body, height=10, width=22, exportselection=False)
        self._available.grid(row=1, column=0, sticky="nsew")
        self._available.bind("<Double-1>", lambda _event: self.add())

        middle = ttk.Frame(body)
        middle.grid(row=1, column=1, padx=8)
        ttk.Button(middle, text=tr("Add →"), command=self.add).pack(fill="x", pady=2)
        ttk.Button(middle, text=tr("← Remove"), command=self.remove).pack(fill="x", pady=2)

        self._chosen = ttk.Treeview(
            body, columns=("Field", "Direction"), show="headings", height=10,
            selectmode="browse",
        )
        self._chosen.heading("Field", text=tr("Field"))
        self._chosen.heading("Direction", text=tr("Direction"))
        self._chosen.column("Field", width=160)
        self._chosen.column("Direction", width=110)
        self._chosen.grid(row=1, column=2, sticky="nsew")
        self._chosen.bind("<Double-1>", lambda _event: self.toggle())

        right = ttk.Frame(body)
        right.grid(row=1, column=3, sticky="n", padx=(8, 0))
        ttk.Button(right, text=tr("Up"), command=lambda: self.shift(-1)).pack(fill="x", pady=2)
        ttk.Button(right, text=tr("Down"), command=lambda: self.shift(1)).pack(fill="x", pady=2)
        ttk.Button(right, text=tr("Reverse direction"), command=self.toggle).pack(
            fill="x", pady=2
        )

        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Button(bottom, text=tr("Clear"), command=self.clear).pack(side="left")
        ttk.Button(bottom, text=tr("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(bottom, text=tr("OK"), command=self._ok).pack(side="right", padx=6)

        self.bind("<Escape>", lambda _event: self.destroy())
        self._show()
        if self._name is not None:
            self._name.focus_set()
        self.wait_visibility()
        self.grab_set()

    def _show(self, select: str | None = None) -> None:
        """Redraw both lists, optionally selecting a chosen field."""
        chosen = [field for field, _ in self._sort]
        self._free = [field for field in self._fields if field not in chosen]
        self._available.delete(0, "end")
        for field in self._free:
            self._available.insert("end", tr(field))
        self._chosen.delete(*self._chosen.get_children())
        for field, descending in self._sort:
            direction = f"▼ {tr('descending')}" if descending else f"▲ {tr('ascending')}"
            self._chosen.insert("", "end", iid=field, values=(tr(field), direction))
        if select is not None:
            self._chosen.selection_set(select)

    def _picked(self) -> int | None:
        """Position of the selected field in the sort order, or None."""
        selection = self._chosen.selection()
        if not selection:
            return None
        return [field for field, _ in self._sort].index(selection[0])

    def add(self) -> None:
        """Add the selected available field as the last sort level."""
        selection = self._available.curselection()
        if selection:
            field = self._free[selection[0]]
            self._sort.append((field, field in DESCENDING_FIRST))
            self._show(field)

    def remove(self) -> None:
        """Take the selected field out of the sort order."""
        index = self._picked()
        if index is not None:
            del self._sort[index]
            self._show()

    def shift(self, delta: int) -> None:
        """Move the selected field one level up or down."""
        index = self._picked()
        if index is None:
            return
        target = index + delta
        if 0 <= target < len(self._sort):
            self._sort[index], self._sort[target] = self._sort[target], self._sort[index]
        self._show(self._sort[target if 0 <= target < len(self._sort) else index][0])

    def toggle(self) -> None:
        """Switch the selected field between ascending and descending."""
        index = self._picked()
        if index is not None:
            field, descending = self._sort[index]
            self._sort[index] = (field, not descending)
            self._show(field)

    def clear(self) -> None:
        """Remove every sort level (back to the manual order)."""
        self._sort = []
        self._show()

    def _ok(self) -> None:
        """Close with the arranged order (and, for a preset, a valid name)."""
        if self._name is not None:
            name = self._name.get().strip()
            if not name:
                messagebox.showwarning(self.title(), tr("The preset needs a name."), parent=self)
                return
            if name.casefold() in self._taken:
                messagebox.showwarning(
                    self.title(), tr('A preset named "{name}" already exists.').format(name=name),
                    parent=self,
                )
                return
            self.result_name = name
        self.result = self._sort
        self.destroy()


class TodoApp(tk.Tk):
    """Main window: task tree on top, history of the selected task below."""

    def __init__(
        self, session: Session | None = None, account: RemoteAccount | None = None,
        database: Path | None = None,
    ) -> None:
        """Work on a local database session, or (with account) on the server.

        database: the local session's file, shown in the title.
        """
        super().__init__()
        use_logo(self)
        self.geometry("1000x640")
        self._local_session = session
        self._account = account
        self._database = database
        self.next_database: Path | None = None  # main() reopens with this file when set
        self.service: TaskService | RemoteTaskService = (
            RemoteTaskService(account) if account else TaskService(session)  # type: ignore[arg-type]
        )
        self.logged_out = False  # main() shows the login window again when set
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._collapsed: set[str] = set()
        self._progress: dict[int, float] = {}
        self._sort = load_sort()
        self._history_sort = parse_sort(settings.load_setting("history_sort"), HISTORY_COLUMNS)
        self.presets = load_presets()
        self.sort_presets = load_sort_presets()
        # Reminders found by the background thread wait here for the window's own thread.
        self._reminders: queue.Queue[tuple[list[DueTask], bool]] = queue.Queue()
        self._reminder_window: ReminderWindow | None = None
        # Work handed over by other threads (the tray menu); Tk is used only from this one.
        self._calls: queue.Queue[Callable[[], object]] = queue.Queue()
        self.in_tray = False  # set when the tray icon is shown: closing then only hides
        self.after(500, self._poll_reminders)
        self.service.reset_due_tasks()  # resets that fell due while the program was closed
        self._schedule_midnight()
        self._sync_ms = int(settings.number_setting("sync_seconds", SYNC_SECONDS) * 1000)
        if account:
            self.after(self._sync_ms, self._sync_tick)
        self._build()

    @property
    def session(self) -> Session:
        """Where the window reads from: todo.db, or the current copy of the server's data."""
        if self._account:
            return self._account.mirror.session
        return self._local_session  # type: ignore[return-value]

    def _acting_user_id(self) -> int:
        """Who is recorded as making changes."""
        if self._account:
            return self._account.user["id"]
        return self._user.value()

    def _build(self) -> None:
        """(Re)create all widgets in the current language."""
        acting_as = self._user.value() if hasattr(self, "_user") else None
        for child in self.winfo_children():
            child.destroy()
        self._use_tk_language()
        title = tr("To-do list")
        if self._account:
            title += f" – {self._account.user['name']} @ {self._account.api.base_url}"
        elif self._database is not None:
            title += f" – {self._database}"
        self.title(title)

        toolbar = WrapFrame(self)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        actions: list[tuple[str, Callable[[], None]]] = [
            (tr("New task"), self.new_task),
            (tr("New subtask"), self.new_subtask),
            (tr("From template…"), self.subtasks_from_template),
            (tr("Edit"), self.edit_task),
            (tr("Next stage"), self.next_stage),
            (tr("Complete"), self.complete),
            (tr("Up"), lambda: self.shift(-1)),
            (tr("Down"), lambda: self.shift(1)),
            (tr("Indent"), self.indent),
            (tr("Outdent"), self.outdent),
            (tr("Sort…"), self.open_sort),
            (tr("Random task"), self.random_task),
            (tr("Delete"), self.delete),
        ]
        # "Next stage" is the everyday action, so it stands out in green.
        style = ttk.Style(self)
        style.configure("Next.TButton", background=NEXT_STAGE_COLOUR, foreground="white")
        style.map(
            "Next.TButton",
            background=[("pressed", NEXT_STAGE_ACTIVE), ("active", NEXT_STAGE_ACTIVE)],
            foreground=[("disabled", "gray80")],
        )
        for label, command in actions:
            button = ttk.Button(toolbar, text=label, command=command)
            if command == self.next_stage:
                button.configure(style="Next.TButton")

        menubar = tk.Menu(self)
        account = tk.Menu(menubar, tearoff=False)
        if self._account:
            account.add_command(label=tr("Refresh"), command=self.sync, accelerator="F5")
            account.add_command(label=tr("Log out"), command=self.log_out)
        else:
            account.add_command(label=tr("Database file…"), command=self.change_database)
            account.add_command(label=tr("Log in to a server…"), command=self.log_out)
        account.add_separator()
        account.add_command(label=tr("Quit"), command=self.quit_program, accelerator="Ctrl+Q")
        menubar.add_cascade(label=tr("Account"), menu=account)
        self.bind("<F5>", lambda _event: self.sync())
        self.bind("<Control-q>", lambda _event: self.quit_program())
        manage = tk.Menu(menubar, tearoff=False)
        if self._account:
            users_state = "normal" if self._account.is_admin else "disabled"
            manage.add_command(label=tr("Users…"), command=self.manage_users, state=users_state)
            manage.add_command(label=tr("Workflows…"), command=self.manage_workflows)
            manage.add_command(label=tr("Tags…"), command=self.manage_tags)
        else:
            manage.add_command(label=tr("Users…"), command=self.manage_users)
            manage.add_command(label=tr("Workflows…"), command=self.manage_workflows)
            manage.add_command(label=tr("Tags…"), command=self.manage_tags)
        manage.add_command(label=tr("Subtask templates…"), command=self.manage_templates)
        menubar.add_cascade(label=tr("Manage"), menu=manage)
        self._presets_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label=tr("Filters"), menu=self._presets_menu)
        self._fill_presets_menu()
        self._sort_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label=tr("Sorting"), menu=self._sort_menu)
        self._fill_sort_menu()
        # Server settings: only for administrators logged in to a server.
        is_admin = self._account is not None and self._account.is_admin
        server = tk.Menu(menubar, tearoff=False)
        server.add_command(
            label=tr("Server settings…"), command=self.server_settings,
            state="normal" if is_admin else "disabled",
        )
        menubar.add_cascade(
            label=tr("Server"), menu=server, state="normal" if is_admin else "disabled"
        )
        languages = tk.Menu(menubar, tearoff=False)
        self._language = tk.StringVar(self, i18n.get_language())
        for code, name in i18n.LANGUAGES.items():
            languages.add_radiobutton(
                label=name, value=code, variable=self._language,
                command=self.change_language,
            )
        menubar.add_cascade(label=tr("Language"), menu=languages)
        self.configure(menu=menubar)

        acting = ttk.Frame(toolbar)  # label and box stay together when wrapping
        if self._account:
            ttk.Label(acting, text=tr("Logged in:")).pack(side="left", padx=(12, 6))
            ttk.Label(acting, text=self._account.user["name"]).pack(side="left")
            ttk.Button(acting, text=tr("Log out"), command=self.log_out).pack(
                side="left", padx=(8, 0)
            )
            self._connection = ttk.Label(acting)
            self._connection.pack(side="left", padx=(12, 0))
            self._show_connection()
        else:
            ttk.Label(acting, text=tr("Acting as:")).pack(side="left", padx=(12, 6))
            self._user = Choice(acting, self._active_users(), acting_as)
            self._user.configure(width=18)
            self._user.pack(side="left")

        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tree = self._make_tree(
            panes, LIST_COLUMNS[1:], on_scroll=self._tree_moved, show="tree headings", height=14
        )
        self._build_filters()
        for field, width in LIST_WIDTHS.items():
            self.tree.column(column_id(field), width=width, stretch=False)
        # minwidth: narrow windows scroll sideways instead of squeezing the names.
        self.tree.column("Task", minwidth=200, stretch=True)
        self.tree.tag_configure("done", foreground="gray55")
        self.tree.tag_configure("overdue", foreground="red3")
        self.tree.tag_configure("today", foreground=DUE_TODAY_COLOUR)
        italic = tkfont.nametofont("TkDefaultFont").copy()
        italic.configure(slant="italic")
        self.tree.tag_configure("context", foreground="gray60", font=italic)
        self._italic = italic  # keep a reference, or Tk drops the font
        # The coloured Priority and Urgency cells: labels laid over the list, because
        # a Treeview can colour only whole rows. Rows of done tasks have none.
        self._levels: dict[str, tuple[Priority, Urgency]] = {}  # row -> its task's levels
        self._level_cells: list[tk.Label] = []
        self._level_cells_pending = False
        self.tree.bind("<<TreeviewOpen>>", lambda _event: self._remember_open(True))
        self.tree.bind("<<TreeviewClose>>", lambda _event: self._remember_open(False))
        for sequence in ("<Configure>", "<B1-Motion>", "<ButtonRelease-1>"):
            self.tree.bind(sequence, lambda _event: self.after_idle(self._tree_moved), add="+")
        for sequence in ("<<TreeviewOpen>>", "<<TreeviewClose>>"):
            self.tree.bind(sequence, lambda _event: self.after_idle(self._tree_moved), add="+")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_history())
        self.tree.bind("<Button-1>", self._tree_clicked)
        self.tree.bind("<Double-1>", lambda event: self._edit_row(self.tree.identify_row(event.y)))
        self.tree.bind("<Return>", lambda _event: self.edit_task())
        self.bind("<Escape>", lambda _event: self.unselect())
        self.tree.bind("<Delete>", lambda _event: self.delete())
        self._tooltip = TreeTooltip(self.tree, self._task_description)

        details = ttk.Frame(panes)
        self._description = ttk.Label(details, text="", justify="left")
        self._description.pack(fill="x", pady=(6, 4))
        details.bind(
            "<Configure>",
            lambda event: self._description.configure(wraplength=max(event.width - 4, 100)),
        )
        history_actions = ttk.Frame(details)
        history_actions.pack(fill="x", pady=(0, 4))
        ttk.Button(history_actions, text=tr("Sort history…"), command=self.open_history_sort).pack(
            side="left"
        )
        ttk.Button(
            history_actions, text=tr("Clear history filters"), command=self.clear_history_filters
        ).pack(side="left", padx=(4, 0))
        ttk.Button(history_actions, text=tr("Unselect task"), command=self.unselect).pack(
            side="left", padx=(4, 0)
        )
        self.history = self._make_tree(
            details, HISTORY_COLUMNS, on_scroll=self._place_history_filters, show="headings",
            height=8,
        )
        for column, width in zip(HISTORY_COLUMNS, (140, 200, 130, 100, 100, 200, 200)):
            self.history.column(column, width=width, minwidth=width)
        self._build_history_filters()
        panes.add(details, weight=1)

        self.refresh()

    @staticmethod
    def _make_tree(
        panes: ttk.Panedwindow | ttk.Frame,
        columns: tuple[str, ...],
        on_scroll: Callable[[], None] | None = None,
        **options: Any,
    ) -> ttk.Treeview:
        """Create a Treeview with vertical and horizontal scrollbars in its own frame.

        Row 0 of the frame is left free for a widget above the tree (the filters);
        on_scroll is called after every scroll, sideways or up and down.
        """
        frame = ttk.Frame(panes)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        tree = ttk.Treeview(frame, columns=columns, selectmode="browse", **options)
        for column in columns:
            tree.heading(column, text=tr(column))
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)

        def xscroll(first: str, last: str) -> None:
            horizontal.set(first, last)
            if on_scroll is not None:
                on_scroll()

        def yscroll(first: str, last: str) -> None:
            vertical.set(first, last)
            if on_scroll is not None:
                on_scroll()

        tree.configure(yscrollcommand=yscroll, xscrollcommand=xscroll)
        tree.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        if isinstance(panes, ttk.Panedwindow):
            panes.add(frame, weight=3)
        else:
            frame.pack(fill="both", expand=True)
        return tree

    def _schedule_midnight(self) -> None:
        """Run the repeat check just after the next local midnight."""
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        self.after(int((midnight - now).total_seconds() * 1000) + 1000, self._at_midnight)

    def _at_midnight(self) -> None:
        """Reset repeating tasks that are due today, then wait for the next midnight."""
        self._run(self.service.reset_due_tasks)
        self._schedule_midnight()

    def _use_tk_language(self) -> None:
        """Make Tk's own dialog buttons (Yes/No, OK) follow the language."""
        try:
            self.tk.eval(
                f"::msgcat::mclocale {i18n.get_language()}; "
                "::msgcat::mcload [file join $::tk_library msgs]"
            )
        except tk.TclError:
            pass  # buttons stay in the system language

    def change_language(self) -> None:
        """Switch to the language picked in the menu and remember it."""
        i18n.set_language(self._language.get())
        i18n.save_language(i18n.get_language())
        self._build()

    def _active_users(self) -> list[tuple[str, Any]]:
        """Options for the "Acting as" box."""
        query = select(User).where(User.is_active).order_by(User.name)
        return [(user.name, user.id) for user in self.session.scalars(query)]

    def manage_users(self) -> None:
        """Open the users window, then pick up whatever changed there."""
        if self._account:
            self.wait_window(RemoteUsersDialog(self, self._account))
            self.sync()  # download the changes (e.g. renamed users)
            return
        self.wait_window(UsersDialog(self, self.session))
        self._user.set_options(self._active_users(), self._user.value())
        self.refresh()

    def manage_workflows(self) -> None:
        """Open the workflows window, then pick up whatever changed there."""
        self.wait_window(WorkflowsDialog(self, self._management()))
        self.refresh()

    def server_settings(self) -> None:
        """Let an administrator change the server's settings."""
        if self._account is None or not self._account.is_admin:
            return
        try:
            current = self._account.get_settings()
        except NotLoggedIn as error:
            messagebox.showwarning(tr("To-do list"), str(error), parent=self)
            self.log_out()
            return
        except RemoteError as error:
            messagebox.showerror(tr("Server settings"), str(error), parent=self)
            return
        self.wait_window(ServerSettingsDialog(self, self._account, current))

    def manage_tags(self) -> None:
        """Open the tags window, then pick up whatever changed there."""
        self.wait_window(TagsDialog(self, self._management()))
        self.refresh()

    def _management(self) -> LocalManagement | RemoteManagement:
        """Changes to workflows and tags: on the server when logged in to one."""
        if self._account:
            return RemoteManagement(self._account)
        return LocalManagement(self.session)

    def _templates(self) -> LocalTemplates | RemoteTemplates:
        if self._account:
            return RemoteTemplates(self._account.api)
        return LocalTemplates(self.session)

    def manage_templates(self) -> None:
        """Open the subtask templates window, only to change the list."""
        self.wait_window(SubtaskTemplatesDialog(self, self._templates()))

    # -- filters ------------------------------------------------------------

    def _build_filters(self) -> None:
        """Create the filter row; its widgets sit right under the column headings."""
        self._filter_bar = ttk.Frame(self.tree.master, height=30)
        self._filter_bar.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        self._filter_bar.bind("<Configure>", lambda _event: self.after_idle(self._place_filters))

        name_box = ttk.Frame(self._filter_bar)
        self._name_filter = tk.StringVar(self)
        self._name_filter.trace_add("write", lambda *_args: self.refresh())
        ttk.Entry(name_box, textvariable=self._name_filter).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(name_box, text="✕", width=2, command=self.clear_filters).pack(
            side="left", padx=(2, 0)
        )
        self._filter_widgets: dict[str, tk.Widget] = {"Task": name_box}
        self._column_filters: dict[str, MultiChoice] = {}
        for column in TASK_COLUMNS:
            choice = MultiChoice(self._filter_bar, [], self.refresh)
            self._column_filters[column] = choice
            self._filter_widgets[column] = choice

    def _place_filters(self) -> None:
        """Line the filter widgets up with the current column positions and widths."""
        if not hasattr(self, "_filter_widgets") or not self.tree.winfo_ismapped():
            return
        widths = {field: int(self.tree.column(column_id(field), "width")) for field in LIST_COLUMNS}
        self._line_up(self.tree, self._filter_bar, self._filter_widgets, widths)

    @staticmethod
    def _line_up(
        tree: ttk.Treeview, bar: ttk.Frame, widgets: dict[str, tk.Widget], widths: dict[str, int]
    ) -> None:
        """Place each filter widget in the bar over its column, scrolled along with the list."""
        scrolled = round(float(tree.xview()[0]) * sum(widths.values()))
        x = tree.winfo_rootx() - bar.winfo_rootx() - scrolled
        for column, width in widths.items():
            widgets[column].place(x=x + 1, y=2, width=max(width - 2, 10), height=26)
            x += width

    def _filter_options(self, column: str) -> list[tuple[str, Filter | None]]:
        """The choices of one column's filter, each with its test."""
        options: list[tuple[str, Filter | None]] = [(tr("All"), None)]

        def add(label: str, key: str, test: Predicate) -> None:
            options.append((label, Filter(key, test)))

        if column == "Stage":
            add(tr("(not done)"), "not-done", lambda task: not task.stage.is_final)
            add(tr("(done)"), "done", lambda task: task.stage.is_final)
            for name in sorted({stage.name for stage in self.session.scalars(select(Stage))}):
                add(name, f"name:{name}", lambda task, n=name: task.stage.name == n)
        elif column == "Due date":
            today = date.today()
            add(tr(NONE), "none", lambda task: task.due_date is None)
            add(tr("(overdue)"), "overdue",
                lambda task: task.due_date is not None and task.due_date < today)
            add(tr("(today)"), "today", lambda task: task.due_date == today)
            add(tr("(later)"), "later",
                lambda task: task.due_date is not None and task.due_date > today)
        elif column == "Priority":
            for level in Priority:
                add(tr(level.name), level.name, lambda task, lv=level: task.priority is lv)
        elif column == "Urgency":
            for level in Urgency:
                add(tr(level.name), level.name, lambda task, lv=level: task.urgency is lv)
        elif column == "Assignee":
            add(tr(NONE), "none", lambda task: task.assignee_id is None)
            for user in self.session.scalars(select(User).order_by(User.name)):
                add(user.name, f"id:{user.id}", lambda task, i=user.id: task.assignee_id == i)
        elif column == "Location":
            add(tr(NONE), "none", lambda task: not task.location)
            places = {task.location for task in self.session.scalars(select(Task)) if task.location}
            for place in sorted(places, key=text_sort_key):
                add(place, f"name:{place}", lambda task, p=place: task.location == p)
        elif column == "Tags":
            for tag in self.session.scalars(select(Tag).order_by(Tag.name)):
                add(tag.name, f"id:{tag.id}",
                    lambda task, i=tag.id: any(t.id == i for t in task.tags))
        elif column == "Progress":
            add("0%", "0", lambda task: self._progress[task.id] == 0)
            add("1–99%", "1-99", lambda task: 0 < self._progress[task.id] < 100)
            add("100%", "100", lambda task: self._progress[task.id] >= 100)
        elif column == "Repeat":
            add(tr(NONE), "none", lambda task: task.repeat_rule_id is None)
            add(tr("(any)"), "any", lambda task: task.repeat_rule_id is not None)
            for rule in sorted(self.session.scalars(select(RepeatRule)), key=repeat_sort_key):
                add(repeat_label(rule), f"id:{rule.id}",
                    lambda task, i=rule.id: task.repeat_rule_id == i)
        return options

    def _update_filter_options(self) -> None:
        """Refresh the filter choices (users, tags... may have changed), keeping each pick."""
        for column, choice in self._column_filters.items():
            choice.set_options(self._filter_options(column))

    def _pick_filter(self, column: str, keys: str | list[str] | None) -> bool:
        """Set a column filter to these keys (None = All); False if some no longer exist."""
        return self._column_filters[column].set_keys(filter_keys(keys))

    def _current_filters(self) -> FilterPreset:
        """The filters now set, as an (unnamed) preset."""
        picked = {
            column: value
            for column, choice in self._column_filters.items()
            if (value := filter_value(choice.chosen_keys())) is not None
        }
        return FilterPreset("", self._name_filter.get().strip(), picked)

    def apply_preset(self, preset: FilterPreset) -> None:
        """Set the filters saved in a preset; choices that no longer exist are left at All."""
        missing = [
            tr(column) for column in TASK_COLUMNS
            if not self._pick_filter(column, preset.filters.get(column))
        ]
        if self._name_filter.get() != preset.text:
            self._name_filter.set(preset.text)  # triggers refresh
        else:
            self.refresh()
        if missing:
            messagebox.showwarning(
                tr("Filter presets"),
                tr("Some choices of this preset no longer exist and were set to All: {columns}")
                .format(columns=", ".join(missing)),
                parent=self,
            )

    # -- filter presets (kept in settings.json, on this computer only) ---------

    def _fill_presets_menu(self) -> None:
        """The Filters menu: every saved preset (click = apply), then the actions."""
        menu = self._presets_menu
        menu.delete(0, "end")
        for preset in self.presets:
            menu.add_command(label=preset.name, command=lambda p=preset: self.apply_preset(p))
        if not self.presets:
            menu.add_command(label=tr("(no saved presets)"), state="disabled")
        menu.add_separator()
        menu.add_command(label=tr("Save current filters…"), command=self.add_preset)
        menu.add_command(label=tr("Filter presets…"), command=self.manage_presets)
        menu.add_command(label=tr("Clear filters"), command=self.clear_filters)

    def presets_changed(self) -> None:
        """Save the presets and show them in the menu."""
        save_presets(self.presets)
        self._fill_presets_menu()

    def add_preset(self, parent: tk.Misc | None = None) -> bool:
        """Save the filters now set as a new preset (the form lets you name and change them)."""
        form = PresetForm(
            self, self._current_filters(), {p.name for p in self.presets}, tr("New preset")
        )
        (parent or self).wait_window(form)
        if form.result is None:
            return False
        self.presets.append(form.result)
        self.presets_changed()
        return True

    def edit_preset(self, index: int, parent: tk.Misc) -> bool:
        others = {p.name for i, p in enumerate(self.presets) if i != index}
        form = PresetForm(self, self.presets[index], others, tr("Edit preset"))
        parent.wait_window(form)
        if form.result is None:
            return False
        self.presets[index] = form.result
        self.presets_changed()
        return True

    def manage_presets(self) -> None:
        self.wait_window(PresetsDialog(
            self, tr("Filter presets"), self.presets,
            apply=lambda index: self.apply_preset(self.presets[index]),
            add=lambda parent: self.add_preset(parent),
            edit=self.edit_preset,
            changed=self.presets_changed,
        ))

    # -- sort presets (settings.json, this computer only) ------------------------

    def _fill_sort_menu(self) -> None:
        """The Sorting menu: every saved sort order (click = apply), then the actions."""
        menu = self._sort_menu
        menu.delete(0, "end")
        for preset in self.sort_presets:
            menu.add_command(label=preset.name, command=lambda p=preset: self.apply_sort(p.sort))
        if not self.sort_presets:
            menu.add_command(label=tr("(no saved presets)"), state="disabled")
        menu.add_separator()
        menu.add_command(label=tr("Sort…"), command=self.open_sort)
        menu.add_command(label=tr("Save current sort…"), command=self.add_sort_preset)
        menu.add_command(label=tr("Sort presets…"), command=self.manage_sort_presets)
        menu.add_command(label=tr("Clear sort"), command=lambda: self.apply_sort(()))

    def sort_presets_changed(self) -> None:
        save_sort_presets(self.sort_presets)
        self._fill_sort_menu()

    def apply_sort(self, sort: Any) -> None:
        """Sort the list this way and remember it, as the Sort… window does."""
        self._sort = [tuple(level) for level in sort]  # type: ignore[misc]
        save_sort(self._sort)
        self.refresh()

    def _sort_form(
        self, sort: Any, name: str, taken: set[str], title: str, parent: tk.Misc
    ) -> SortPreset | None:
        form = SortDialog(self, list(sort), preset_name=name, taken=taken, title=title)
        parent.wait_window(form)
        if form.result is None:
            return None
        return SortPreset(form.result_name, tuple(form.result))

    def add_sort_preset(self, parent: tk.Misc | None = None) -> bool:
        """Save the sort order now used as a new preset (the window lets you change it)."""
        taken = {p.name for p in self.sort_presets}
        preset = self._sort_form(self._sort, "", taken, tr("New sort preset"), parent or self)
        if preset is None:
            return False
        self.sort_presets.append(preset)
        self.sort_presets_changed()
        return True

    def edit_sort_preset(self, index: int, parent: tk.Misc) -> bool:
        old = self.sort_presets[index]
        taken = {p.name for i, p in enumerate(self.sort_presets) if i != index}
        preset = self._sort_form(old.sort, old.name, taken, tr("Edit sort preset"), parent)
        if preset is None:
            return False
        self.sort_presets[index] = preset
        self.sort_presets_changed()
        return True

    def manage_sort_presets(self) -> None:
        self.wait_window(PresetsDialog(
            self, tr("Sort presets"), self.sort_presets,
            apply=lambda index: self.apply_sort(self.sort_presets[index].sort),
            add=lambda parent: self.add_sort_preset(parent),
            edit=self.edit_sort_preset,
            changed=self.sort_presets_changed,
        ))

    def _matches(self, task: Task, tests: list[Predicate]) -> bool:
        """Whether the task passes the name filter and every column filter."""
        text = self._name_filter.get().strip().lower()
        if text and text not in task.name.lower():
            return False
        return all(test(task) for test in tests)

    def clear_filters(self) -> None:
        """Reset every filter to show all tasks."""
        for choice in self._column_filters.values():
            choice.set_keys([])
        self._name_filter.set("")  # triggers refresh

    def _remember_open(self, is_open: bool) -> None:
        """Keep track of collapsed tasks so a refresh does not reopen them."""
        iid = self.tree.focus()
        if is_open:
            self._collapsed.discard(iid)
        else:
            self._collapsed.add(iid)

    # -- sorting ------------------------------------------------------------

    def open_sort(self) -> None:
        """Let the user arrange the sort order, then apply and remember it."""
        dialog = SortDialog(self, self._sort)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.apply_sort(dialog.result)

    def _sort_value(self, field: str, task: Task) -> Any:
        """The value a task is sorted by for one field; None sorts last."""
        if field == "Task":
            return text_sort_key(task.name)
        if field == "Stage":
            return task.stage.order, text_sort_key(task.stage.name)
        if field == "Due date":
            return task.due_date
        if field == "Priority":
            return int(task.priority)
        if field == "Urgency":
            return int(task.urgency)
        if field == "Assignee":
            return text_sort_key(task.assignee.name) if task.assignee else None
        if field == "Location":
            return text_sort_key(task.location) if task.location else None
        if field == "Tags":
            return ", ".join(sorted(text_sort_key(tag.name) for tag in task.tags)) or None
        if field == "Progress":
            return self._progress[task.id]
        if field == "Repeat":
            return repeat_sort_key(task.repeat_rule) if task.repeat_rule else None
        return task.created_at

    def _sorted(self, tasks: list[Task]) -> list[Task]:
        """Siblings in the chosen sort order; ties keep the manual order."""
        return sorted_by(tasks, self._sort, self._sort_value)

    def _update_headings(self) -> None:
        """Show ▲/▼ (and the level, if several) on the columns being sorted by."""
        for field in ("Task", *TASK_COLUMNS):
            self.tree.heading(column_id(field), text=self._heading(field, self._sort))

    @staticmethod
    def _heading(field: str, sort: list[tuple[str, bool]]) -> str:
        """A column's title with its place in the sort order, if any."""
        levels = {name: (level, desc) for level, (name, desc) in enumerate(sort, 1)}
        if field not in levels:
            return tr(field)
        level, descending = levels[field]
        number = str(level) if len(sort) > 1 else ""
        return f"{tr(field)} {'▼' if descending else '▲'}{number}"

    # -- display ------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the task tree with the filters applied, keeping the selection."""
        self._tooltip.hide()  # its row may be gone
        self._levels.clear()
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self._update_filter_options()
        tests = [test for choice in self._column_filters.values() if (test := choice.test())]
        filtering = bool(tests or self._name_filter.get().strip())
        self._progress = {
            task.id: self.service.get_progress_percent(task.id)
            for task in self.session.scalars(select(Task))
        }
        self._update_headings()
        top_level = select(Task).where(Task.parent_id.is_(None)).order_by(Task.order)
        for task in self._sorted(list(self.session.scalars(top_level))):
            self._insert(task, "", tests, filtering)
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
            self.tree.see(selected[0])
        self._tree_moved()
        self.show_history()

    def _insert(
        self, task: Task, parent_iid: str, tests: list[Predicate], filtering: bool, depth: int = 0
    ) -> bool:
        """Add a task row and its subtasks; return whether anything was shown.

        A task that does not match is still shown (in grey italics) when one of
        its subtasks matches, so the match keeps its place in the tree.
        While filtering, every shown task is expanded.
        """
        repeat = ""
        if task.repeat_rule:
            repeat = f"{repeat_label(task.repeat_rule)} ({task.repeat_done}/{task.repeat_count or '∞'})"
            if task.next_reset_at is not None:
                repeat += f" ⟳ {task.next_reset_at.astimezone():%Y-%m-%d}"
        iid = str(task.id)
        if not task.stage.is_final:
            self._levels[iid] = (task.priority, task.urgency)
        if task.stage.is_final:
            row_tags: tuple[str, ...] = ("done",)
        elif task.due_date is not None and task.due_date < date.today():
            row_tags = ("overdue",)
        elif task.due_date == date.today():
            row_tags = ("today",)
        else:
            row_tags = ()
        self.tree.insert(
            parent_iid,
            "end",
            iid=iid,
            text=task.stage.name,
            open=filtering or iid not in self._collapsed,
            tags=row_tags,
            values=(  # in the order of LIST_COLUMNS[1:]
                NAME_INDENT * depth + task.name,
                f"{self._progress[task.id]:.0f}%",
                repeat,
                task.due_date.isoformat() if task.due_date else "",
                tr(task.priority.name),
                tr(task.urgency.name),
                task.assignee.name if task.assignee else "",
                task.location or "",
                ", ".join(sorted(tag.name for tag in task.tags)),
            ),
        )
        shown_subtasks = [
            self._insert(subtask, iid, tests, filtering, depth + 1)
            for subtask in self._sorted(list(task.subtasks))
        ]
        if self._matches(task, tests):
            return True
        if any(shown_subtasks):
            self.tree.item(iid, tags=("context",))
            return True
        self.tree.delete(iid)
        return False

    def _tree_moved(self) -> None:
        """The list scrolled, resized or changed: line up the filters and the coloured cells."""
        self._place_filters()
        if not self._level_cells_pending:
            self._level_cells_pending = True
            self.after_idle(self._place_level_cells)

    def _place_level_cells(self) -> None:
        """Lay a coloured label over the Priority and Urgency cell of every visible row."""
        self._level_cells_pending = False
        cells = [
            (iid, column, level)
            for iid, levels in self._levels.items()
            if self.tree.exists(iid)
            for column, level in zip(LEVEL_COLUMNS, levels)
        ]
        used = 0
        for iid, column, level in cells:
            box = self.tree.bbox(iid, column)
            if not box:
                continue  # scrolled out of view, or inside a closed task
            if used == len(self._level_cells):
                self._level_cells.append(self._make_level_cell())
            cell = self._level_cells[used]
            used += 1
            x, y, width, height = box
            cell.configure(text=tr(level.name), background=LEVEL_COLOURS[int(level)])
            cell.iid = iid  # type: ignore[attr-defined]
            cell.place(x=x + 1, y=y + 1, width=max(width - 2, 1), height=max(height - 2, 1))
        for cell in self._level_cells[used:]:
            cell.place_forget()

    def _make_level_cell(self) -> tk.Label:
        """A label for one coloured cell; clicks, scrolling and hovering act on its row."""
        cell = tk.Label(self.tree, anchor="w", padx=3, foreground="black", borderwidth=0)
        cell.iid = ""  # type: ignore[attr-defined]

        def choose(_event: tk.Event) -> None:
            self._tooltip.hide()
            self.tree.focus_set()
            if cell.iid in self.tree.selection():  # type: ignore[attr-defined]
                self.unselect()
                return
            self.tree.focus(cell.iid)  # type: ignore[attr-defined]
            self.tree.selection_set(cell.iid)  # type: ignore[attr-defined]

        def scroll(units: int) -> None:
            self._tooltip.hide()
            self.tree.yview_scroll(units, "units")

        def hover(event: tk.Event) -> None:  # the tooltip of the row, as over the list
            self.tree.event_generate(
                "<Motion>", x=cell.winfo_x() + event.x, y=cell.winfo_y() + event.y
            )

        cell.bind("<Button-1>", choose)
        cell.bind("<Double-1>", lambda _event: self._edit_row(cell.iid))  # type: ignore[attr-defined]
        cell.bind("<Button-4>", lambda _event: scroll(-3))
        cell.bind("<Button-5>", lambda _event: scroll(3))
        cell.bind("<MouseWheel>", lambda event: scroll(-3 if event.delta > 0 else 3))
        cell.bind("<Motion>", hover)
        cell.bind("<Leave>", lambda _event: self._tooltip.hide())
        return cell

    def _task_description(self, iid: str) -> str:
        """The description of the task in a row of the list ("" if none)."""
        task = self.session.get(Task, int(iid))
        return (task.description or "") if task else ""

    def show_history(self) -> None:
        """Show the description and history of the selected task, or with none selected
        the history of every task in the list."""
        task = self._selected(warn=False)
        self._description.configure(text=(task.description or "") if task else "")
        if task:
            self._history_changes = self.service.get_history(task.id)
        else:
            shown = self._shown_task_ids()
            self._history_changes = self.service.get_histories(shown) if shown else []
        self._history_fields |= {c.field_name for c in self._history_changes if c.field_name}
        for column, choice in self._history_filters.items():
            choice.set_options(self._history_filter_options(column))
        self._show_history_rows()

    def _shown_task_ids(self, parent: str = "") -> list[int]:
        """The tasks in the list, closed parents' subtasks included."""
        shown: list[int] = []
        for iid in self.tree.get_children(parent):
            shown.append(int(iid))
            shown += self._shown_task_ids(iid)
        return shown

    def _tree_clicked(self, event: tk.Event) -> str | None:
        """A click on the selected task or on the empty space below the tasks unselects."""
        if self.tree.identify_region(event.x, event.y) in ("heading", "separator"):
            return None
        iid = self.tree.identify_row(event.y)
        if "indicator" in self.tree.identify_element(event.x, event.y):
            return None  # opens or closes the subtasks
        if iid and iid not in self.tree.selection():
            return None  # selected as usual
        self.unselect()
        return "break"

    def _edit_row(self, iid: str) -> None:
        """Edit the double-clicked task (its first click may have unselected it)."""
        if iid:
            self.tree.selection_set(iid)
            self.edit_task()

    def unselect(self) -> None:
        """Select no task: the history then covers all the tasks in the list."""
        self.tree.selection_remove(*self.tree.selection())
        self.tree.focus("")

    def _show_history_rows(self) -> None:
        """List the selected task's changes with the history's filters and sort order."""
        self.history.delete(*self.history.get_children())
        for field in HISTORY_COLUMNS:
            self.history.heading(field, text=self._heading(field, self._history_sort))
        tests = [test for choice in self._history_filters.values() if (test := choice.test())]
        searches = {
            HISTORY_COLUMNS.index(column): text
            for column, variable in self._history_texts.items()
            if (text := variable.get().strip().casefold())
        }
        rows = [
            (change, values)
            for change in self._history_changes
            if all(test(change) for test in tests)
            for values in (self._history_row(change),)
            if all(text in values[index].casefold() for index, text in searches.items())
        ]
        for _change, values in sorted_by(rows, self._history_sort, self._history_sort_value):
            self.history.insert("", "end", values=values)

    def _history_row(self, change: TaskChange) -> tuple[str, ...]:
        """The texts of a change's row, in the order of HISTORY_COLUMNS."""
        summary = parse_summary(change)
        if summary is not None:
            old_text, new_text = self._summary_texts(summary)
        else:
            old_text = self._history_value(change.field_name, change.old_value)
            new_text = self._history_value(change.field_name, change.new_value)
        task = self.session.get(Task, change.task_id)
        return (
            f"{change.changed_at.astimezone():%Y-%m-%d %H:%M:%S}",
            task.name if task else "",
            change.changed_by.name if change.changed_by else tr("system"),
            tr(change.change_type.name),
            tr(change.field_name or ""),
            old_text,
            new_text,
        )

    @staticmethod
    def _history_sort_value(field: str, row: tuple[TaskChange, tuple[str, ...]]) -> Any:
        """The value a history row is sorted by for one field; None (empty) sorts last."""
        change, values = row
        if field == "When":
            return change.changed_at
        text = values[HISTORY_COLUMNS.index(field)]
        return text_sort_key(text) if text else None

    def _build_history_filters(self) -> None:
        """Create the history's filter row, above its column headings like the tasks' one."""
        self._history_bar = ttk.Frame(self.history.master, height=30)
        self._history_bar.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        self._history_changes: list[TaskChange] = []
        self._history_fields: set[str] = set()  # seen so far: choices stay when the task changes
        self._history_filters: dict[str, MultiChoice] = {}
        self._history_texts: dict[str, tk.StringVar] = {}
        self._history_widgets: dict[str, tk.Widget] = {}
        for column in HISTORY_COLUMNS:
            if column in HISTORY_TEXT_FILTERS:
                variable = tk.StringVar(self)
                variable.trace_add("write", lambda *_args: self._show_history_rows())
                self._history_texts[column] = variable
                self._history_widgets[column] = ttk.Entry(self._history_bar, textvariable=variable)
            else:
                choice = MultiChoice(self._history_bar, [], self._show_history_rows)
                self._history_filters[column] = choice
                self._history_widgets[column] = choice
        for widget in (self._history_bar, self.history):
            widget.bind(
                "<Configure>", lambda _event: self.after_idle(self._place_history_filters), add="+"
            )

    def _place_history_filters(self) -> None:
        """Line the history's filter widgets up with its columns."""
        if not hasattr(self, "_history_widgets") or not self.history.winfo_ismapped():
            return
        widths = {column: int(self.history.column(column, "width")) for column in HISTORY_COLUMNS}
        self._line_up(self.history, self._history_bar, self._history_widgets, widths)

    def _history_filter_options(self, column: str) -> list[tuple[str, Filter | None]]:
        """The choices of one history column's filter, each with its test."""
        options: list[tuple[str, Filter | None]] = [(tr("All"), None)]

        def add(label: str, key: str, test: Callable[[TaskChange], bool]) -> None:
            options.append((label, Filter(key, test)))

        def days_ago(change: TaskChange) -> int:
            return (date.today() - change.changed_at.astimezone().date()).days

        if column == "When":
            add(tr("(today)"), "today", lambda change: days_ago(change) == 0)
            add(tr("(last 7 days)"), "week", lambda change: days_ago(change) < 7)
            add(tr("(last 30 days)"), "month", lambda change: days_ago(change) < 30)
            add(tr("(older)"), "older", lambda change: days_ago(change) >= 30)
        elif column == "Who":
            add(tr("system"), "system", lambda change: change.changed_by is None)
            for user in self.session.scalars(select(User).order_by(User.name)):
                add(user.name, f"id:{user.id}",
                    lambda change, i=user.id: change.changed_by_id == i)
        elif column == "Change":
            for kind in ChangeType:
                add(tr(kind.name), kind.name, lambda change, k=kind: change.change_type is k)
        elif column == "Field":
            add(tr(NONE), "none", lambda change: not change.field_name)
            for name in sorted(self._history_fields, key=lambda field: text_sort_key(tr(field))):
                add(tr(name), f"name:{name}", lambda change, n=name: change.field_name == n)
        return options

    def clear_history_filters(self) -> None:
        """Reset the history's filters to show every change."""
        for choice in self._history_filters.values():
            choice.set_keys([])
        for variable in self._history_texts.values():
            variable.set("")
        self._show_history_rows()

    def open_history_sort(self) -> None:
        """Let the user arrange the history's sort order, then apply and remember it."""
        dialog = SortDialog(
            self, self._history_sort, title=tr("Sorting the history"), fields=HISTORY_COLUMNS
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self._history_sort = dialog.result
            settings.save_setting(
                "history_sort", [[field, descending] for field, descending in dialog.result]
            )
            self._show_history_rows()

    def _summary_texts(self, summary: dict[str, Any]) -> tuple[str, str]:
        """A compressed history row as (time span and count, net field changes)."""
        start = datetime.fromisoformat(summary["from"]).astimezone()
        end = datetime.fromisoformat(summary["to"]).astimezone()
        span = tr("{count} changes, {start} – {end}").format(
            count=summary["count"], start=f"{start:%Y-%m-%d}", end=f"{end:%Y-%m-%d}"
        )
        fields = "; ".join(
            f"{tr(field)}: {self._history_value(field, old)} → {self._history_value(field, new)}"
            for field, (old, new) in summary["fields"].items()
        )
        return span, fields

    @staticmethod
    def _history_value(field_name: str | None, value: str | None) -> str:
        """A stored history value, with "(none)" and priority/urgency names translated."""
        if value is None:
            return ""
        return tr(value) if value == NONE or field_name in ("Priority", "Urgency") else value

    # -- actions ------------------------------------------------------------

    def _selected(self, warn: bool = True) -> Task | None:
        """The selected task, or None (optionally telling the user)."""
        selection = self.tree.selection()
        task = self.session.get(Task, int(selection[0])) if selection else None
        if task is None and warn:
            messagebox.showinfo(tr("To-do list"), tr("Select a task first."), parent=self)
        return task

    def _run(self, action: Callable[[], object]) -> None:
        """Run a service call, show its error if it fails, then reload."""
        try:
            action()
        except NotLoggedIn as error:
            self._show_connection()
            messagebox.showwarning(tr("To-do list"), str(error), parent=self)
            self.log_out()
            return
        except (ValueError, SQLAlchemyError) as error:
            self.session.rollback()
            self._show_connection()
            messagebox.showerror(tr("To-do list"), str(error), parent=self)
        self._show_connection()
        self.refresh()

    # -- server connection --------------------------------------------------

    def sync(self) -> None:
        """Download the server's current data (other people's changes too)."""
        if self._account:
            self._run(self._account.mirror.sync)

    def _sync_tick(self) -> None:
        """Every few seconds: pick up other people's changes, unless a window is open."""
        if self._account is None or self.logged_out:
            return
        if self.grab_current() is None:
            try:
                self._account.mirror.sync()
                self.refresh()
            except NotLoggedIn:
                self._run(self._account.mirror.sync)  # shows the message and logs out
                return
            except RemoteError:
                pass  # server briefly unreachable: try again next time
            self._show_connection()
        self.after(self._sync_ms, self._sync_tick)

    def _show_connection(self) -> None:
        """Server mode: whether the server could be reached the last time it was asked."""
        if self._account is None:
            return
        address = self._account.api.base_url.split("://", 1)[-1]
        if self._account.api.connected is False:
            text, colour = tr("● No connection to {server}"), CONNECTION_LOST
        else:
            text, colour = tr("● Connected to {server}"), CONNECTION_OK
        self._connection.configure(text=text.format(server=address), foreground=colour)

    # -- reminders ----------------------------------------------------------

    def post_reminders(self, due: list[DueTask], popup: bool) -> None:
        """Called by the reminder thread; Tk may only be used from the window's thread."""
        self._reminders.put((due, popup))

    def call_soon(self, action: Callable[[], object]) -> None:
        """Run an action in the window's thread; safe to call from any thread."""
        self._calls.put(action)

    def _poll_reminders(self) -> None:
        """Run handed-over work; show (or update) the reminder window with what was found."""
        while not self._calls.empty():
            try:
                self._calls.get_nowait()()
            except Exception:
                reminders.log.exception("A background action failed")
            try:
                self.winfo_exists()
            except tk.TclError:
                return  # the action quit the program
        latest: list[DueTask] | None = None
        popup = False
        while not self._reminders.empty():
            latest, newest_popup = self._reminders.get_nowait()
            popup = popup or newest_popup
        window = self._reminder_window
        if window is not None and not window.winfo_exists():
            window = self._reminder_window = None  # closed by the user
        if latest is not None:
            if not latest:
                if window is not None:
                    window.destroy()  # everything done: nothing to remind of
            elif popup or window is not None:
                try:
                    if window is None:
                        window = self._reminder_window = ReminderWindow(
                            self,
                            settings.text_setting("reminder_background", reminders.BACKGROUND),
                            int(settings.number_setting("reminder_font_size", reminders.FONT_SIZE)),
                        )
                    window.show(latest)
                    if popup:
                        window.deiconify()
                        window.lift()
                except tk.TclError:
                    reminders.log.exception("Cannot show the reminder window")
        self.after(500, self._poll_reminders)

    def log_out(self) -> None:
        """End the server login (or leave local mode) and go back to the login window."""
        if self._account:
            self._account.logout()
        self.logged_out = True
        self.destroy()

    def change_database(self) -> None:
        """Local mode: work on another database file (an empty one is set up if new)."""
        current = self._database or database_path()
        chosen = choose_database_file(self, current)
        if chosen is None or chosen.resolve() == current.resolve():
            return
        save_database_path(chosen)
        self.next_database = chosen
        self.destroy()  # main() opens the window again on the new file

    def close(self) -> None:
        """Window closed: with a tray icon the program keeps running there, else it quits."""
        if not self.in_tray:
            self.quit_program()
            return
        if not settings.load_setting("tray_hint_shown"):
            messagebox.showinfo(
                tr("To-do list"),
                tr("The program keeps running in the system tray and goes on reminding you."),
                parent=self,
            )
            settings.save_setting("tray_hint_shown", True)
        self.withdraw()

    def show_window(self) -> None:
        """Bring the window back (from the tray)."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_program(self) -> None:
        """Really quit: a login that is not remembered ends here."""
        if self._account and not self._account.remember:
            self._account.logout()
        self.destroy()

    def _ask(self, task: Task | None) -> dict[str, Any] | None:
        """Show the task form and return its fields, or None if cancelled."""
        # A new task is assigned to whoever adds it; the form lets them change that.
        dialog = TaskDialog(self, self.session, task, default_assignee_id=self._acting_user_id())
        self.wait_window(dialog)
        return dialog.result

    def _create(self, parent_id: int | None) -> None:
        """Ask for a new task and create it under the given parent."""
        fields = self._ask(None)
        if fields is None:
            return
        user_id = self._acting_user_id()

        def create() -> None:
            task = self.service.create_task(
                fields.pop("name"), fields.pop("stage_id"), user_id,
                parent_id=parent_id, **fields,
            )
            self.refresh()
            self.tree.selection_set(str(task.id))

        self._run(create)

    def new_task(self) -> None:
        """Create a top-level task."""
        self._create(None)

    def new_subtask(self) -> None:
        """Create a subtask of the selected task."""
        task = self._selected()
        if task is not None:
            self._create(task.id)

    def subtasks_from_template(self) -> None:
        """Add subtasks to the selected task from templates chosen in the templates window."""
        task = self._selected()
        if task is None:
            return
        dialog = SubtaskTemplatesDialog(self, self._templates(), parent_name=task.name)
        self.wait_window(dialog)
        if not dialog.chosen:
            return
        parent = {
            "id": task.id,
            "first_stage_id": task.stage.workflow.stages[0].id,
            "assignee_id": task.assignee_id,
        }
        chosen, parent_id, user_id = dialog.chosen, task.id, self._acting_user_id()

        def create() -> None:
            created = None
            for template in chosen:
                fields = templates.subtask_fields(template, parent)
                fields["priority"] = Priority[fields["priority"]]
                fields["urgency"] = Urgency[fields["urgency"]]
                created = self.service.create_task(
                    fields.pop("name"), fields.pop("stage_id"), user_id, **fields
                )
            self._collapsed.discard(str(parent_id))  # show the new subtasks
            self.refresh()
            if created is not None:
                self.tree.selection_set(str(created.id))
                self.tree.see(str(created.id))

        self._run(create)

    def random_candidates(self) -> list[Task]:
        """The tasks a random draw picks from: unfinished and without subtasks."""
        return [
            task for task in self.session.scalars(select(Task).order_by(Task.id))
            if not task.stage.is_final and not task.subtasks
        ]

    def random_task(self) -> None:
        """Show a task drawn at random, favouring the important and urgent ones."""
        if not self.random_candidates():
            messagebox.showinfo(
                tr("Random task"), tr("There are no unfinished tasks without subtasks."),
                parent=self,
            )
            return
        RandomTaskWindow(self)

    def show_task(self, task_id: int) -> None:
        """Select a task in the list and scroll to it; clear the filters if they hide it."""
        iid = str(task_id)
        if not self.tree.exists(iid):
            self.clear_filters()
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)  # also opens its parents
            self.tree.focus_set()

    def edit_task(self) -> None:
        """Edit the selected task; only the changed fields are logged."""
        task = self._selected()
        if task is None:
            return
        fields = self._ask(task)
        if fields is not None:
            task_id, user_id = task.id, self._acting_user_id()
            self._run(lambda: self.service.update_task(task_id, user_id, **fields))

    def _set_stage(self, task: Task, stage: Stage) -> None:
        """Move the task to a stage."""
        task_id, stage_id, user_id = task.id, stage.id, self._acting_user_id()
        self._run(lambda: self.service.update_task(task_id, user_id, stage_id=stage_id))

    def next_stage(self) -> None:
        """Move the selected task to the next stage of its workflow."""
        task = self._selected()
        if task is None:
            return
        stages = task.stage.workflow.stages
        position = stages.index(task.stage)
        if position + 1 < len(stages):
            self._set_stage(task, stages[position + 1])

    def complete(self) -> None:
        """Move the selected task to the final stage of its workflow."""
        task = self._selected()
        if task is None:
            return
        final = [stage for stage in task.stage.workflow.stages if stage.is_final]
        if final:
            self._set_stage(task, final[-1])

    def shift(self, delta: int) -> None:
        """Move the selected task up or down among its siblings."""
        if self._sort:
            messagebox.showinfo(
                tr("To-do list"),
                tr("Manual order (Up / Down) works only when sorting is off."),
                parent=self,
            )
            return
        task = self._selected()
        if task is not None:
            task_id, parent_id, order = task.id, task.parent_id, task.order + delta
            user_id = self._acting_user_id()
            self._run(lambda: self.service.move_task(task_id, parent_id, order, user_id))

    def indent(self) -> None:
        """Make the selected task the last subtask of the task above it."""
        task = self._selected()
        if task is None:
            return
        previous = self.tree.prev(str(task.id))
        if previous:
            task_id, user_id = task.id, self._acting_user_id()
            self._run(lambda: self.service.move_task(task_id, int(previous), None, user_id))

    def outdent(self) -> None:
        """Move the selected subtask one level up, right after its parent."""
        task = self._selected()
        if task is None or task.parent is None:
            return
        task_id, user_id = task.id, self._acting_user_id()
        parent_id, order = task.parent.parent_id, task.parent.order + 1
        self._run(lambda: self.service.move_task(task_id, parent_id, order, user_id))

    def delete(self) -> None:
        """Delete the selected task after confirmation."""
        task = self._selected()
        if task is None:
            return
        if task.subtasks:
            messagebox.showwarning(
                tr("To-do list"), tr("This task has subtasks and cannot be deleted."),
                parent=self,
            )
            return
        question = tr('Delete "{name}"?').format(name=task.name)
        if messagebox.askyesno(tr("Delete"), question, parent=self):
            task_id, user_id = task.id, self._acting_user_id()
            self._run(lambda: self.service.delete_task(task_id, user_id))


def reminder_display(app: TodoApp) -> Callable[[list[DueTask], bool], None]:
    """The orange reminder window, or system notifications if "reminder_window" is false."""
    if settings.flag_setting("reminder_window", reminders.WINDOW):
        return app.post_reminders
    return system_notifications


def run_with_reminders(app: TodoApp, find_due: Callable[[date], list[DueTask]]) -> None:
    """Run the window with the reminder thread and the tray icon until the program ends."""
    checker = Reminders(find_due, show=reminder_display(app))
    tray = Tray(
        open_window=lambda: app.call_soon(app.show_window),
        check_now=checker.check_now,
        reminders_on=lambda: checker.enabled,
        toggle_reminders=lambda: checker.set_enabled(not checker.enabled),
        quit_program=lambda: app.call_soon(app.quit_program),
    )
    checker.start()
    if settings.flag_setting("close_to_tray", CLOSE_TO_TRAY):
        app.in_tray = tray.start()
    try:
        app.mainloop()
    finally:
        tray.stop()
        checker.stop()


def run_local(path: Path) -> str:
    """Open the database file (creating it with reference data if new) and run the window.

    Returns "quit", "login" (the user asked to log in to a server, or the file
    cannot be opened) or "reopen" (another database file was chosen).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(f"sqlite:///{path}")
        create_all(engine)
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            if session.scalars(select(Workflow)).first() is None:
                seed(session, with_tasks=False)
            add_missing_repeat_rules(session)
    except (OSError, SQLAlchemyError) as error:
        log.exception("Cannot open the database %s", path)
        reason = getattr(error, "orig", None) or error  # SQLite's own words, not the SQL
        show_error(tr("Cannot open the database {path}.").format(path=path) + f"\n\n{reason}")
        return "login"
    with session_factory() as session:
        app = TodoApp(session, database=path)
        run_with_reminders(app, lambda today: local_due_tasks(session_factory, today))
        if app.next_database is not None:
            return "reopen"
        return "login" if app.logged_out else "quit"


def show_error(text: str) -> None:
    """An error message when no window is open."""
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(tr("To-do list"), text, parent=root)
    root.destroy()


def run_remote(account: RemoteAccount) -> bool:
    """Run the window logged in to the server; True if the user logged out."""
    # The reminder thread gets its own connection: the window's is not shared between threads.
    api = ApiClient(account.api.base_url, account.api.token)
    user_id = account.user["id"]
    mine = only_mine()
    app = TodoApp(account=account)
    try:
        run_with_reminders(app, lambda today: remote_due_tasks(api, user_id, today, mine))
    finally:
        api.close()
    if app.logged_out:
        reminders.SAVED_TASKS.unlink(missing_ok=True)  # not to remind the next user of them
    return app.logged_out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m todo_db.app",
                                     description="The to-do list's desktop program.")
    parser.add_argument(
        "--db", type=Path, default=os.environ.get(DB_ENV) or None,
        help=f"local mode's database file for this run (default: the one chosen last, or "
             f"{DB_FILE}; also {DB_ENV}=...)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Start in the mode used last time; show the login window when needed."""
    global _db_override
    args = parse_args(argv)
    if args.db is not None:
        _db_override = args.db.expanduser().absolute()  # from where the user is, before chdir
    home = os.environ.get(HOME_ENV)
    if home:  # the program's own folder for its files, instead of where it was started
        Path(home).expanduser().mkdir(parents=True, exist_ok=True)
        os.chdir(Path(home).expanduser())
    setup_logging()
    settings.add_defaults(
        {**reminders.SETTINGS, "close_to_tray": CLOSE_TO_TRAY, "sync_seconds": SYNC_SECONDS}
    )
    i18n.set_language(i18n.load_language())
    mode = settings.load_setting("client_mode")
    if _db_override is not None:
        mode = "local"  # a database file given: work on it, whatever was used last
    show_login = mode is None  # first start: let the user choose
    while True:
        account = None
        if mode == "server" and not show_login:
            account = resume_login()
            show_login = account is None
        if show_login:
            window = LoginWindow()
            window.mainloop()
            if window.result is None:
                return  # cancelled
            mode, account = window.result
        if mode == "local":
            outcome = run_local(database_path())
            if outcome == "quit":
                return
            show_login = outcome == "login"
            continue
        if not run_remote(account):  # type: ignore[arg-type]
            return
        show_login = True


if __name__ == "__main__":
    main()
