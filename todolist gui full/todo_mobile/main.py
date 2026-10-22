"""The to-do list on a phone (Kivy), working against the application server.

Run on a computer for testing:  .venv/bin/python todo_mobile/main.py
Build the Android app:           ./build_android.sh
"""

from __future__ import annotations

import calendar
import sys
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # started as a script on a computer
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, DictProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.stacklayout import StackLayout
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import platform

from todo_db import i18n, reminder_core, settings
from todo_db.i18n import tr
from todo_db.reminder_core import DueTask, Reminders

from todo_mobile import api as remote
from todo_mobile import storage
from todo_mobile.reminder_service import MAX_LINES, find_due_tasks
from todo_mobile.tasks import (
    NONE, PRIORITIES, SHOW_CHOICES, SHOW_OPEN, URGENCIES, final_stage_id, history_lines,
    is_overdue, next_stage_id, parse_due, repeat_label, sorted_rules, task_details, task_rows,
)

SYNC_SECONDS = 30
MODE_SETTING, MODE_LOCAL, MODE_SERVER = "mode", "local", "server"
# The background service of the reminders (services in android/buildozer.spec).
REMINDER_SERVICE = "org.todolist.todolist.ServiceReminders"
ORANGE = (1, 0.55, 0, 1)  # the reminder window, as on the computer (#FF8C00)
# Longer texts of the database location window (translated in todo_db.i18n).
ACCESS_NOTE = ("Places outside the app's own folders, such as Documents, need the "
               "“All files access” permission; the app asks for it.")
ACCESS_ASK = ("Allow “All files access” for To-do in the settings that open now, "
              "then come back and tap Use again.")
COPY_OR_EMPTY = "{path} does not exist yet. Copy your tasks there, or start with an empty list?"
ROW = dp(48)
GREEN = (0.18, 0.62, 0.27, 1)  # the "Next stage" button and the chosen day, as on the computer
GREY = (0.6, 0.6, 0.6, 1)
RED = (1, 0.42, 0.42, 1)  # overdue tasks, Sundays
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

Builder.load_string("""
#:import dp kivy.metrics.dp

<TaskRow>:
    orientation: "vertical"
    size_hint_y: None
    height: dp(60)
    padding: [dp(12) + root.depth * dp(20), dp(6), dp(12), dp(6)]
    canvas.before:
        Color:
            rgba: (0.25, 0.35, 0.55, 1) if self.state == "down" else ((0.16, 0.16, 0.18, 1) if root.index % 2 else (0.12, 0.12, 0.14, 1))
        Rectangle:
            pos: self.pos
            size: self.size
    Label:
        text: root.name_text
        bold: root.matches
        font_size: "16sp"
        color: (0.6, 0.6, 0.6, 1) if root.done or not root.matches else (1, 1, 1, 1)
        text_size: self.width, None
        halign: "left"
        shorten: True
        shorten_from: "right"
    Label:
        text: root.details_text
        font_size: "13sp"
        color: (1, 0.42, 0.42, 1) if root.overdue else (0.6, 0.65, 0.75, 1)
        text_size: self.width, None
        halign: "left"
        shorten: True
        shorten_from: "right"

<TaskList>:
    viewclass: "TaskRow"
    RecycleBoxLayout:
        default_size: None, dp(60)
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height
        orientation: "vertical"
        spacing: dp(1)
""")


class TaskRow(ButtonBehavior, BoxLayout):
    """One line in the task list; tapping it opens the task."""

    name_text = StringProperty()
    details_text = StringProperty()
    depth = NumericProperty(0)
    done = BooleanProperty(False)
    matches = BooleanProperty(True)
    overdue = BooleanProperty(False)
    index = NumericProperty(0)
    task_id = NumericProperty(0)

    def on_release(self) -> None:
        App.get_running_app().open_task(int(self.task_id))


class TaskList(RecycleView):
    pass


# -- small building blocks ----------------------------------------------------------


def label(text: str, **kwargs: Any) -> Label:
    """A label that wraps its text and grows to fit it."""
    widget = Label(text=text, size_hint_y=None, halign="left", valign="top", **kwargs)
    widget.bind(width=lambda w, width: setattr(w, "text_size", (width, None)))
    widget.bind(texture_size=lambda w, size: setattr(w, "height", size[1] + dp(6)))
    return widget


def button(text: str, action: Callable[[], Any], **kwargs: Any) -> Button:
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", ROW)
    widget = Button(text=text, **kwargs)
    widget.bind(on_release=lambda _widget: action())
    return widget


def text_input(text: str = "", **kwargs: Any) -> TextInput:
    kwargs.setdefault("multiline", False)
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", ROW)
    kwargs.setdefault("write_tab", False)
    if not kwargs.get("multiline"):
        kwargs.setdefault("padding", [dp(10), dp(14)])
    return TextInput(text=text, **kwargs)


def top_bar(title: str, *buttons: Button) -> BoxLayout:
    bar = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(4), padding=dp(4))
    bar.add_widget(Label(text=title, bold=True, font_size="18sp", shorten=True,
                         text_size=(None, None)))
    for widget in buttons:
        widget.size_hint_x = None
        widget.width = max(dp(90), len(widget.text) * dp(10))
        bar.add_widget(widget)
    return bar


class Choice(Spinner):
    """A drop-down list of (text, value) pairs; .value is the chosen value."""

    def __init__(self, choices: list[tuple[str, Any]], value: Any = None) -> None:
        self._values = {text: item for text, item in choices}
        texts = [text for text, _item in choices]
        current = next((text for text, item in choices if item == value), texts[0])
        super().__init__(text=current, values=texts, size_hint_y=None, height=ROW)

    @property
    def value(self) -> Any:
        return self._values[self.text]


def form_row(caption: str, widget: Any) -> BoxLayout:
    row = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
    caption_label = label(caption, font_size="13sp", color=(0.7, 0.75, 0.85, 1))
    row.add_widget(caption_label)
    row.add_widget(widget)

    def fit(*_args: Any) -> None:
        row.height = caption_label.height + widget.height + dp(2)

    caption_label.bind(height=fit)
    widget.bind(height=fit)
    fit()
    return row


def scrolling_column() -> tuple[ScrollView, GridLayout]:
    scroll = ScrollView(do_scroll_x=False)
    column = GridLayout(cols=1, size_hint_y=None, spacing=dp(8), padding=dp(12))
    column.bind(minimum_height=column.setter("height"))
    scroll.add_widget(column)
    return scroll, column


def system_bar_insets() -> tuple[int, int, int, int]:
    """(left, top, right, bottom) pixels covered by Android's status and navigation bars.

    From Android 15 an app draws under those bars, so it has to keep its
    buttons out of them itself. 0s on a computer or when Android does not say.
    """
    if platform != "android":
        return 0, 0, 0, 0
    try:
        from jnius import autoclass

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        insets = activity.getWindow().getDecorView().getRootWindowInsets()
        if insets is None:
            return 0, 0, 0, 0
        if autoclass("android.os.Build$VERSION").SDK_INT >= 30:
            types = autoclass("android.view.WindowInsets$Type")
            bars = insets.getInsets(types.systemBars() | types.displayCutout())
            return bars.left, bars.top, bars.right, bars.bottom
        return (insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom())
    except Exception:  # noqa: BLE001 - better a slightly hidden edge than no app
        return 0, 0, 0, 0


# -- screens ----------------------------------------------------------------------


class LoginScreen(Screen):
    def __init__(self, app: TodoMobileApp) -> None:
        super().__init__(name="login")
        self.app = app
        scroll, column = scrolling_column()
        column.padding = [dp(20), dp(30), dp(20), dp(20)]
        column.add_widget(label(tr("To-do list"), font_size="26sp", bold=True))
        self.url = text_input(settings.load_setting("server_url") or "",
                              hint_text="http://192.168.1.10:8000")
        self.email = text_input(settings.load_setting("email") or "")
        self.password = text_input(password=True)
        self.password.bind(on_text_validate=lambda _w: self.log_in())
        for caption, widget in ((tr("Server address"), self.url), (tr("Email"), self.email),
                                (tr("Password"), self.password)):
            column.add_widget(form_row(caption, widget))
        remember = BoxLayout(size_hint_y=None, height=ROW)
        self.remember = CheckBox(active=True, size_hint_x=None, width=ROW)
        remember.add_widget(self.remember)
        remember_label = Label(text=tr("Remember me on this phone"), halign="left",
                               valign="middle")
        remember_label.bind(size=lambda w, size: setattr(w, "text_size", size))
        remember.add_widget(remember_label)
        column.add_widget(remember)
        column.add_widget(button(tr("Log in"), self.log_in))
        self.message = label("", color=(1, 0.55, 0.5, 1))
        column.add_widget(self.message)
        column.add_widget(label(tr("No server? Keep the tasks on this phone only."),
                                color=(0.7, 0.75, 0.85, 1)))
        column.add_widget(button(tr("Without a server"), app.use_local))
        column.add_widget(button(tr("Database location…"), app.show_database_place))
        column.add_widget(form_row(tr("Language"), app.language_choice()))
        self.add_widget(scroll)

    def log_in(self) -> None:
        url, email, password = self.url.text.strip(), self.email.text.strip(), self.password.text
        if not (url and email and password):
            self.message.text = tr("Enter server address, email and password.")
            return
        self.message.text = ""
        api = remote.Api(url)

        def done(user: dict[str, Any]) -> None:
            settings.save_setting(MODE_SETTING, MODE_SERVER)
            settings.save_setting("server_url", api.base_url)
            settings.save_setting("email", email)
            if self.remember.active:
                remote.save_login(self.app.login_file, api.base_url, api.token or "")
            self.password.text = ""
            self.app.logged_in(api, user)

        self.app.work(lambda: api.login(email, password), done,
                      on_error=lambda error: setattr(self.message, "text", str(error)))


class ListScreen(Screen):
    def __init__(self, app: TodoMobileApp) -> None:
        super().__init__(name="list")
        self.app = app
        layout = BoxLayout(orientation="vertical")
        self.title = Label(text="", bold=True, font_size="17sp", halign="left", shorten=True)
        self.title.bind(size=lambda w, size: setattr(w, "text_size", size))
        self.title.valign = "middle"
        bar = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(4), padding=dp(4))
        bar.add_widget(self.title)
        bar.add_widget(button(tr("Refresh"), app.refresh, size_hint=(None, 1), width=dp(100)))
        bar.add_widget(button(tr("Menu"), app.show_menu, size_hint=(None, 1), width=dp(90)))
        layout.add_widget(bar)

        filters = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(4), padding=[dp(4), 0])
        self.search = text_input(hint_text=tr("Search"))
        self.search.bind(text=lambda *_a: self.show())
        self.show_choice = Choice([(tr(choice), choice) for choice in SHOW_CHOICES], SHOW_OPEN)
        self.show_choice.size_hint_x = 0.45
        self.show_choice.bind(text=lambda *_a: self.show())
        filters.add_widget(self.search)
        filters.add_widget(self.show_choice)
        layout.add_widget(filters)

        self.list = TaskList()
        layout.add_widget(self.list)
        self.empty = Label(text="", size_hint_y=None, height=0, color=(0.6, 0.6, 0.6, 1))
        layout.add_widget(self.empty)
        layout.add_widget(button(tr("New task"), lambda: app.open_task(None), height=dp(56)))
        self.add_widget(layout)

    def show(self) -> None:
        """Fill the list from the app's latest data."""
        user = self.app.user or {}
        self.title.text = f"{tr('To-do list')} · {user.get('name', '')}"
        tasks = self.app.data["tasks"] if self.app.data else []
        rows = task_rows(tasks, self.search.text, self.show_choice.value)
        today = date.today()
        self.list.data = [
            {
                "name_text": row.task["name"],
                "details_text": task_details(row.task, today),
                "overdue": is_overdue(row.task, today),
                "depth": row.depth,
                "done": row.task["done"],
                "matches": row.matches,
                "index": index,
                "task_id": row.task["id"],
            }
            for index, row in enumerate(rows)
        ]
        self.empty.text = "" if rows else tr("No tasks to show.")
        self.empty.height = 0 if rows else dp(40)


class TaskScreen(Screen):
    """A task's form: view and change it, or create a new one."""

    def __init__(self, app: TodoMobileApp, task: dict[str, Any] | None,
                 parent: dict[str, Any] | None = None) -> None:
        super().__init__(name="task")
        self.app, self.task, self.parent_task = app, task, parent
        data = app.data
        layout = BoxLayout(orientation="vertical")
        title = task["name"] if task else tr("New subtask") if parent else tr("New task")
        layout.add_widget(top_bar(title, button(tr("Back"), app.go_back)))
        scroll, column = scrolling_column()

        if parent:
            column.add_widget(label(tr("Subtask of: {name}").format(name=parent["name"]),
                                    color=(0.7, 0.75, 0.85, 1)))
        self.name_input = text_input(task["name"] if task else "")
        self.description = text_input(task["description"] or "" if task else "",
                                      multiline=True, height=dp(110))
        stages = []
        for workflow in data["workflows"]:
            if task and workflow["id"] != task["workflow_id"]:
                continue
            for stage in sorted(workflow["stages"], key=lambda s: s["order"]):
                text = stage["name"] if task else f"{workflow['name']}: {stage['name']}"
                stages.append((text, stage["id"]))
        self.stage = Choice(stages, task["stage_id"] if task else None)
        self.priority = Choice([(tr(p), p) for p in PRIORITIES], task["priority"] if task else "Normal")
        self.urgency = Choice([(tr(u), u) for u in URGENCIES], task["urgency"] if task else "Medium")
        users = [(tr(NONE), None)] + [
            (u["name"], u["id"]) for u in data["users"]
            if u["is_active"] or (task and u["id"] == task["assignee_id"])
        ]
        # A new task is assigned to whoever adds it; the form lets them change that.
        me = (app.user or {}).get("id")
        self.assignee = Choice(users, task["assignee_id"] if task else me)
        rules = [(tr(NONE), None)] + [(repeat_label(r), r["id"])
                                      for r in sorted_rules(data["repeat_rules"])]
        self.repeat = Choice(rules, task["repeat_rule_id"] if task else None)
        self.repeat_count = text_input(str(task["repeat_count"]) if task else "0",
                                       input_filter="int")
        self.due_date = text_input(task.get("due_date") or "" if task else "",
                                   hint_text=tr("YYYY-MM-DD, empty = none"))
        due_row = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(6))
        due_row.add_widget(self.due_date)
        due_row.add_widget(button(tr("Calendar"), self.pick_due_date, size_hint_x=None,
                                  width=dp(110)))
        self.location = text_input(task.get("location") or "" if task else "")
        for caption, widget in (
            ("Name", self.name_input), ("Description", self.description), ("Stage", self.stage),
            ("Due date", due_row), ("Location", self.location),
            ("Priority", self.priority), ("Urgency", self.urgency), ("Assignee", self.assignee),
            ("Repeats", self.repeat), ("Repeat count (0 = forever)", self.repeat_count),
        ):
            column.add_widget(form_row(tr(caption), widget))

        chosen = {tag["id"] for tag in task["tags"]} if task else set()
        self.tags: dict[int, ToggleButton] = {}
        tag_box = StackLayout(size_hint_y=None, spacing=dp(4))
        tag_box.bind(minimum_height=tag_box.setter("height"))
        for tag in sorted(data["tags"], key=lambda t: t["name"].casefold()):
            toggle = ToggleButton(text=tag["name"], size_hint=(None, None), height=dp(40),
                                  state="down" if tag["id"] in chosen else "normal")
            toggle.width = max(dp(70), len(tag["name"]) * dp(10) + dp(24))
            self.tags[tag["id"]] = toggle
            tag_box.add_widget(toggle)
        if self.tags:
            column.add_widget(form_row(tr("Tags"), tag_box))

        if task:
            info = [f"{tr('Progress')}: {task['progress_percent']:.0f}%"]
            if task["repeat_rule_id"] is not None:
                info.append(f"{tr('RepeatDone')}: {task['repeat_done']}")
            column.add_widget(label(" · ".join(info), color=(0.7, 0.75, 0.85, 1)))
            actions = GridLayout(cols=2, size_hint_y=None, spacing=dp(6))
            actions.bind(minimum_height=actions.setter("height"))
            actions.add_widget(button(tr("Next stage"), self.next_stage, background_normal="",
                                      background_color=GREEN))
            for text, action in (
                (tr("Complete"), self.complete),
                (tr("New subtask"), lambda: app.open_task(None, parent=task)),
                (tr("History"), lambda: app.open_history(task)),
                (tr("Delete"), self.delete),
            ):
                actions.add_widget(button(text, action))
            column.add_widget(actions)

        layout.add_widget(scroll)
        layout.add_widget(button(tr("Save"), self.save, height=dp(56)))
        self.add_widget(layout)

    def _fields(self) -> dict[str, Any] | None:
        name = self.name_input.text.strip()
        if not name:
            self.app.message(tr("The task needs a name."))
            return None
        try:
            due = parse_due(self.due_date.text)
        except ValueError:
            self.app.message(tr("Enter the due date as YYYY-MM-DD, e.g. 2026-10-31."))
            return None
        return {
            "name": name,
            "description": self.description.text.strip() or None,
            "stage_id": self.stage.value,
            "due_date": due.isoformat() if due else None,
            "location": self.location.text.strip() or None,
            "priority": self.priority.value,
            "urgency": self.urgency.value,
            "assignee_id": self.assignee.value,
            "repeat_rule_id": self.repeat.value,
            "repeat_count": int(self.repeat_count.text or 0),
            "tag_ids": sorted(tag_id for tag_id, toggle in self.tags.items()
                              if toggle.state == "down"),
        }

    def save(self) -> None:
        fields = self._fields()
        if fields is None:
            return
        if self.task is None:
            if self.parent_task:
                fields["parent_id"] = self.parent_task["id"]
            self.app.change("POST", "/tasks", fields)
        else:
            changed = {key: value for key, value in fields.items()
                       if value != self._current(key)}
            if changed:
                self.app.change("PATCH", f"/tasks/{self.task['id']}", changed)
            else:
                self.app.go_back()

    def _current(self, key: str) -> Any:
        if key == "tag_ids":
            return sorted(tag["id"] for tag in self.task["tags"])
        return self.task.get(key)

    def pick_due_date(self) -> None:
        try:
            current = parse_due(self.due_date.text)
        except ValueError:
            current = None
        self.app.open_popup(DatePopup(current, self._set_due_date))

    def _set_due_date(self, day: date | None) -> None:
        self.due_date.text = day.isoformat() if day else ""

    def next_stage(self) -> None:
        stage_id = next_stage_id(self.task, self.app.data["workflows"])
        if stage_id is None:
            self.app.message(tr("The task is already at the last stage."))
        else:
            self.app.change("PATCH", f"/tasks/{self.task['id']}", {"stage_id": stage_id})

    def complete(self) -> None:
        stage_id = final_stage_id(self.task, self.app.data["workflows"])
        if stage_id is None or stage_id == self.task["stage_id"]:
            self.app.message(tr("The task is already done."))
        else:
            self.app.change("PATCH", f"/tasks/{self.task['id']}", {"stage_id": stage_id})

    def delete(self) -> None:
        if any(t["parent_id"] == self.task["id"] for t in self.app.data["tasks"]):
            self.app.message(tr("This task has subtasks and cannot be deleted."))
            return
        self.app.confirm(
            tr('Delete "{name}"?').format(name=self.task["name"]),
            lambda: self.app.change("DELETE", f"/tasks/{self.task['id']}"),
        )


class DatePopup(Popup):
    """A month calendar; picking a day (or "Today", "No date") calls on_pick with it."""

    def __init__(self, current: date | None, on_pick: Callable[[date | None], Any]) -> None:
        self.today = date.today()
        self.current, self.on_pick = current, on_pick
        shown = current or self.today
        self.year, self.month = shown.year, shown.month
        content = BoxLayout(orientation="vertical", spacing=dp(6))
        header = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(6))
        header.add_widget(button("<", lambda: self.turn(-1), size_hint_x=None, width=dp(56)))
        self.heading = Label(bold=True, font_size="17sp")
        header.add_widget(self.heading)
        header.add_widget(button(">", lambda: self.turn(1), size_hint_x=None, width=dp(56)))
        content.add_widget(header)
        self.days = GridLayout(cols=7, spacing=dp(2))
        content.add_widget(self.days)
        bottom = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(6))
        bottom.add_widget(button(tr("Today"), lambda: self.pick(self.today)))
        bottom.add_widget(button(tr("No date"), lambda: self.pick(None)))
        bottom.add_widget(button(tr("Cancel"), self.dismiss))
        content.add_widget(bottom)
        super().__init__(title=tr("Due date"), content=content, size_hint=(0.95, None),
                         height=dp(500))
        self.show()

    def turn(self, months: int) -> None:
        """Show an earlier or later month."""
        self.year, month = divmod(self.year * 12 + self.month - 1 + months, 12)
        self.month = month + 1
        self.show()

    def show(self) -> None:
        """The month in weeks from Monday; today framed in bold, the chosen day green."""
        self.heading.text = f"{tr(MONTHS[self.month - 1])} {self.year}"
        self.days.clear_widgets()
        for column, name in enumerate(WEEKDAYS):
            self.days.add_widget(Label(text=tr(name), font_size="13sp",
                                       color=RED if column == 6 else GREY))
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(self.year, self.month):
            for column, day in enumerate(week):
                text = f"[b][u]{day.day}[/u][/b]" if day == self.today else str(day.day)
                widget = button(text, lambda d=day: self.pick(d), markup=True,
                                size_hint_y=1, height=0)
                if day.month != self.month:
                    widget.color = GREY  # the neighbouring months' days
                elif column == 6:
                    widget.color = RED
                if day == self.current:
                    widget.background_normal = ""
                    widget.background_color = GREEN
                    widget.color = (1, 1, 1, 1)
                self.days.add_widget(widget)

    def pick(self, day: date | None) -> None:
        self.dismiss()
        self.on_pick(day)


class HistoryScreen(Screen):
    def __init__(self, app: TodoMobileApp, task: dict[str, Any],
                 changes: list[dict[str, Any]]) -> None:
        super().__init__(name="history")
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(top_bar(f"{tr('History')}: {task['name']}",
                                  button(tr("Back"), app.go_back)))
        scroll, column = scrolling_column()
        for heading, text in history_lines(changes):
            column.add_widget(label(heading, bold=True, font_size="13sp",
                                    color=(0.7, 0.75, 0.85, 1)))
            if text:
                column.add_widget(label(text))
        layout.add_widget(scroll)
        self.add_widget(layout)


# -- the app ----------------------------------------------------------------------


class TodoMobileApp(App):
    title = "To-do"
    data = DictProperty()

    def build(self) -> BoxLayout:
        storage = Path(self.user_data_dir)
        settings.SETTINGS_FILE = storage / "settings.json"
        self.login_file = storage / "login.json"
        i18n.set_language(i18n.load_language())
        self.api: remote.Api | None = None
        self.user: dict[str, Any] | None = None
        self._busy = 0
        self._open_popup: Popup | None = None
        self._shown = 0
        self._list: ListScreen | None = None
        self._history_task_id = 0
        self._reminders: Reminders | None = None  # on a computer; on Android: the service
        self._reminder_popup: Popup | None = None
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self._on_key)
        self.screens = ScreenManager(transition=SlideTransition(duration=0.15))
        self.screens.add_widget(Screen(name="start"))
        # The screens sit inside a frame that keeps them clear of the system bars.
        self.frame = BoxLayout()
        self.frame.add_widget(self.screens)
        Window.bind(on_resize=lambda *_a: Clock.schedule_once(self._fit_system_bars, 0.2))
        Clock.schedule_once(self._fit_system_bars, 0)
        Clock.schedule_once(self._fit_system_bars, 1)  # Android may know the bars only later
        Clock.schedule_once(lambda _dt: self._start())
        Clock.schedule_interval(lambda _dt: self._sync(), SYNC_SECONDS)
        return self.frame

    def _fit_system_bars(self, *_args: Any) -> None:
        left, top, right, bottom = system_bar_insets()
        # A gap so the top buttons do not touch the status bar or the screen's edge.
        gap = dp(12) if platform == "android" else 0
        self.frame.padding = [left, top + gap, right, bottom]

    # -- navigation --------------------------------------------------------------

    def _show(self, screen: Screen, forward: bool = True) -> None:
        """Slide to a screen; screens other than the task list are thrown away afterwards."""
        self._shown += 1
        screen.name = f"{screen.name}-{self._shown}"
        self.screens.add_widget(screen)
        self.screens.transition.direction = "left" if forward else "right"
        self.screens.current = screen.name
        Clock.schedule_once(lambda _dt: self._drop_hidden(), 0.5)

    def _drop_hidden(self) -> None:
        for screen in list(self.screens.screens):
            if screen is not self.screens.current_screen and screen is not self._list:
                self.screens.remove_widget(screen)

    def _on(self, kind: type) -> bool:
        return isinstance(self.screens.current_screen, kind)

    def show_list(self, forward: bool = False) -> None:
        if self._list is None:
            self._list = ListScreen(self)
            self.screens.add_widget(self._list)
        self._list.show()
        self.screens.transition.direction = "left" if forward else "right"
        self.screens.current = self._list.name
        Clock.schedule_once(lambda _dt: self._drop_hidden(), 0.5)

    def go_back(self) -> None:
        if self._on(HistoryScreen):
            task = self._task(self._history_task_id)
            if task is not None:
                self._show(TaskScreen(self, task), forward=False)
                return
        self.show_list()

    def _on_key(self, _window: Any, key: int, *_args: Any) -> bool:
        """Android's back button (Escape on a computer) goes back instead of quitting."""
        if key != 27:
            return False
        if self._open_popup is not None:
            self._open_popup.dismiss()
            return True
        if self._on(TaskScreen) or self._on(HistoryScreen):
            self.go_back()
            return True
        return False

    def open_task(self, task_id: int | None, parent: dict[str, Any] | None = None) -> None:
        task = self._task(task_id) if task_id is not None else None
        if not self.data.get("workflows"):
            return
        self._show(TaskScreen(self, task, parent))

    def open_history(self, task: dict[str, Any]) -> None:
        self._history_task_id = task["id"]
        self.work(lambda: self.api.request("GET", f"/tasks/{task['id']}/history"),
                  lambda changes: self._show(HistoryScreen(self, task, changes)))

    def _task(self, task_id: int | None) -> dict[str, Any] | None:
        return next((t for t in self.data.get("tasks", []) if t["id"] == task_id), None)

    # -- login ---------------------------------------------------------------------

    def _start(self) -> None:
        if settings.load_setting(MODE_SETTING) == MODE_LOCAL:
            self.use_local()
            return
        remembered = remote.load_login(self.login_file)
        if remembered is None:
            self.show_login()
            return
        api = remote.Api(*remembered)

        def failed(error: Exception) -> None:
            if isinstance(error, remote.NotLoggedIn):
                remote.forget_login(self.login_file)
            self.show_login(str(error))

        self.work(lambda: api.request("GET", "/auth/me"),
                  lambda user: self.logged_in(api, user), on_error=failed)

    def show_login(self, message: str = "") -> None:
        screen = LoginScreen(self)
        screen.message.text = message
        self._list = None
        self._show(screen, forward=False)

    @property
    def local(self) -> bool:
        """Working without a server, on the phone's own database."""
        return self.api is not None and not self.api.base_url

    def use_local(self) -> None:
        """Work without a server from now on (also at the next start)."""
        from todo_mobile.local import LocalApi  # imported here: SQLAlchemy takes a moment

        settings.save_setting(MODE_SETTING, MODE_LOCAL)
        path = self.local_database()
        self.work(lambda: LocalApi(path), lambda api: self.logged_in(api, api.user),
                  on_error=lambda error: self.show_login(str(error)))

    # -- where the tasks without a server are kept ------------------------------------

    def local_database(self) -> Path:
        """The database file of the mode without a server (the one chosen, or the default)."""
        return storage.local_database(Path(self.user_data_dir))

    def show_database_place(self, typed: str | None = None) -> None:
        """Choose where the tasks without a server are kept."""
        private = Path(self.user_data_dir)
        path_input = text_input(typed or str(self.local_database()))
        suggestions = [
            button(tr(place.label), lambda p=place: setattr(path_input, "text", str(p.path)))
            for place in storage.places(private)
        ]

        def use() -> None:
            popup.dismiss()
            self._use_database(storage.database_file(path_input.text, private))

        buttons = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(8))
        buttons.add_widget(button(tr("Cancel"), lambda: popup.dismiss()))
        buttons.add_widget(button(tr("Use"), use))
        popup = self._popup(
            tr("Database location"),
            label(tr("Where the tasks without a server are kept (a file):")),
            path_input,
            *suggestions,
            label(tr(ACCESS_NOTE), font_size="13sp", color=(0.7, 0.75, 0.85, 1)),
            buttons,
        )

    def _use_database(self, target: Path) -> None:
        """Switch to the file: ask for access if needed, offer to copy the tasks if it is new."""
        current = self.local_database()
        if target == current and self.local:
            return
        folders = storage.own_folders(Path(self.user_data_dir))
        if not storage.inside(target, folders) and not storage.has_all_files_access():
            self.message(tr(ACCESS_ASK))
            self._open_popup.bind(on_dismiss=lambda _p: self.show_database_place(str(target)))
            storage.ask_all_files_access()
            return
        if target.exists() or not current.exists() or target == current:
            self._switch_database(target, copy=False)
            return

        def choose(copy: bool) -> None:
            popup.dismiss()
            self._switch_database(target, copy)

        popup = self._popup(
            tr("Database location"),
            label(tr(COPY_OR_EMPTY).format(path=target)),
            button(tr("Copy my tasks"), lambda: choose(True)),
            button(tr("Start empty"), lambda: choose(False)),
            button(tr("Cancel"), lambda: popup.dismiss()),
        )

    def _switch_database(self, target: Path, copy: bool) -> None:
        from todo_mobile.local import LocalApi

        old = self.api if self.local else None
        current = self.local_database()

        def job() -> Any:
            if old is not None:
                old.close()  # the old file stays usable if the new one fails
            try:
                storage.move_database(current, target, copy)
            except OSError as error:
                raise remote.RemoteError(
                    tr("Cannot open the database {path}.").format(path=target) + f" ({error})"
                ) from error
            return LocalApi(target)

        def done(api: Any) -> None:
            default = Path(self.user_data_dir) / storage.DB_NAME
            settings.save_setting(storage.SETTING, None if target == default else str(target))
            settings.save_setting(MODE_SETTING, MODE_LOCAL)
            self.logged_in(api, api.user)

        self.work(job, done)

    def logged_in(self, api: remote.Api, user: dict[str, Any]) -> None:
        self.api, self.user = api, user
        self.work(api.load_all, self._loaded_first)
        self.start_reminders()

    # -- reminders ---------------------------------------------------------------------

    @staticmethod
    def reminders_on() -> bool:
        return settings.flag_setting("reminders_enabled", reminder_core.ENABLED)

    def set_reminders(self, on: bool) -> None:
        """Switch reminders on or off (also for the next start)."""
        settings.save_setting("reminders_enabled", on)
        if on:
            self.start_reminders()
        else:
            self.stop_reminders()

    def start_reminders(self) -> None:
        """On Android the background service (notifications, also with the app closed);
        on a computer a checker in the app (the orange window)."""
        if not self.reminders_on():
            return
        private = Path(self.user_data_dir)
        if platform == "android":
            try:
                self._allow_notifications()
                from jnius import autoclass

                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                autoclass(REMINDER_SERVICE).start(
                    activity, "", tr("To-do list"), tr("Reminders are on"), str(private)
                )
            except Exception as error:  # noqa: BLE001 - the app works without reminders
                self.message(f"{tr('Reminders')}: {error}")
        elif self._reminders is None:
            self._reminders = Reminders(
                find_due_tasks(private),
                show=lambda due, popup: Clock.schedule_once(
                    lambda _dt: self.show_reminder(due, popup)),
            )
            self._reminders.start()

    def stop_reminders(self) -> None:
        if platform == "android":
            try:
                from jnius import autoclass

                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                autoclass(REMINDER_SERVICE).stop(activity)
            except Exception:  # noqa: BLE001, S110 - not running
                pass
        elif self._reminders is not None:
            self._reminders.stop()
            self._reminders = None
        self.show_reminder([], False)

    @staticmethod
    def _allow_notifications() -> None:
        """Android 13+: ask once for permission to show notifications."""
        from jnius import autoclass

        if autoclass("android.os.Build$VERSION").SDK_INT < 33:
            return
        from android.permissions import Permission, check_permission, request_permissions

        if not check_permission(Permission.POST_NOTIFICATIONS):
            request_permissions([Permission.POST_NOTIFICATIONS])

    def show_reminder(self, due: list[DueTask], popup: bool) -> None:
        """The orange reminder window (on a computer): opens when it is time, else only
        keeps an open one up to date; closes when nothing is due any more."""
        if not due or (self._reminder_popup is None and not popup):
            if self._reminder_popup is not None and not due:
                self._reminder_popup.dismiss()
            return
        today = date.today()
        content = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=dp(4))
        content.bind(minimum_height=content.setter("height"))
        for task in due[:MAX_LINES]:
            text = task.name
            if task.due_date < today:
                text += " " + tr("(overdue since {date})").format(date=task.due_date.isoformat())
            content.add_widget(label(text, font_size="20sp", bold=True, color=(0, 0, 0, 1)))
        if len(due) > MAX_LINES:
            content.add_widget(label(tr("…and {n} more").format(n=len(due) - MAX_LINES),
                                     font_size="18sp", color=(0, 0, 0, 1)))
        content.add_widget(button(tr("OK"), lambda: popup_window.dismiss()))
        if self._reminder_popup is not None:
            self._reminder_popup.dismiss()  # replaced by the new list
        popup_window = Popup(
            title=tr("Task reminder"), content=content, size_hint=(0.92, None),
            background="", background_color=ORANGE, title_color=(0, 0, 0, 1),
            title_size="18sp", separator_color=(0, 0, 0, 1),
        )
        content.bind(height=lambda _w, height: setattr(popup_window, "height", height + dp(80)))
        popup_window.height = content.height + dp(80)

        def closed(_popup: Popup) -> None:
            if self._reminder_popup is popup_window:
                self._reminder_popup = None

        popup_window.bind(on_dismiss=closed)
        self._reminder_popup = popup_window
        popup_window.open()

    def _loaded_first(self, data: dict[str, Any]) -> None:
        self.data = data
        self.show_list(forward=True)

    def log_out(self) -> None:
        """End the login, or leave the mode without a server; shows the login screen."""
        api = self.api
        settings.save_setting(MODE_SETTING, MODE_SERVER)
        self.stop_reminders()  # nobody to remind until the next login
        self.api, self.user, self.data = None, None, {}
        remote.forget_login(self.login_file)
        self.show_login()
        if api is not None:
            threading.Thread(target=api.logout, daemon=True).start()

    # -- talking to the server -------------------------------------------------------

    def work(self, job: Callable[[], Any], done: Callable[[Any], Any] | None = None,
             on_error: Callable[[Exception], Any] | None = None) -> None:
        """Run a server call in the background, then `done(result)` in the app."""
        self._busy += 1
        self._show_busy()

        def run() -> None:
            try:
                result, error = job(), None
            except Exception as exc:  # noqa: BLE001 - shown to the user
                result, error = None, exc
            Clock.schedule_once(lambda _dt: finish(result, error))

        def finish(result: Any, error: Exception | None) -> None:
            self._busy -= 1
            self._show_busy()
            if error is None:
                if done is not None:
                    done(result)
            elif on_error is not None:
                on_error(error)
            elif isinstance(error, remote.NotLoggedIn):
                self.log_out()
                self.message(str(error))
            else:
                self.message(str(error))

        threading.Thread(target=run, daemon=True).start()

    def _show_busy(self) -> None:
        self.title = "To-do…" if self._busy else "To-do"
        if self._list is not None:
            user = (self.user or {}).get("name", "")
            dots = " …" if self._busy else ""
            self._list.title.text = f"{tr('To-do list')} · {user}{dots}"

    def change(self, method: str, path: str, body: Any = None) -> None:
        """Send a change, download everything again and go back to the list."""
        api = self.api

        def job() -> dict[str, Any]:
            api.request(method, path, body)
            return api.load_all()

        def done(data: dict[str, Any]) -> None:
            self.data = data
            self.show_list()

        self.work(job, done)

    def refresh(self, quiet: bool = False) -> None:
        """Download everything again (quietly: errors are not shown)."""
        api = self.api
        if api is None:
            return

        def done(data: dict[str, Any]) -> None:
            if self.api is api:  # not logged out in the meantime
                self.data = data
                if self._list is not None:
                    self._list.show()

        self.work(api.load_all, done, on_error=(lambda _error: None) if quiet else None)

    def _sync(self) -> None:
        """Every half minute, on the list only, fetch what others changed."""
        if self._on(ListScreen) and not self._busy and self._open_popup is None:
            self.refresh(quiet=True)

    # -- messages and the menu -------------------------------------------------------

    def _popup(self, title: str, *widgets: Any) -> Popup:
        """A window over the app with the widgets one under another, as tall as they need."""
        content = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        content.bind(minimum_height=content.setter("height"))
        for widget in widgets:
            content.add_widget(widget)
        popup = Popup(title=title, content=content, size_hint=(0.9, None))
        content.bind(height=lambda _w, height: setattr(popup, "height", height + dp(90)))
        return self.open_popup(popup)

    def open_popup(self, popup: Popup) -> Popup:
        """Show a popup; the back button closes it, and syncing waits until it is closed."""
        popup.bind(on_dismiss=lambda _p: setattr(self, "_open_popup", None))
        self._open_popup = popup
        popup.open()
        return popup

    def message(self, text: str) -> None:
        close = button(tr("OK"), lambda: popup.dismiss())
        popup = self._popup(tr("To-do list"), label(text), close)

    def confirm(self, question: str, action: Callable[[], Any]) -> None:
        def yes() -> None:
            popup.dismiss()
            action()

        buttons = BoxLayout(size_hint_y=None, height=ROW, spacing=dp(8))
        buttons.add_widget(button(tr("Cancel"), lambda: popup.dismiss()))
        buttons.add_widget(button(tr("Delete"), yes))
        popup = self._popup(tr("To-do list"), label(question), buttons)

    def show_menu(self) -> None:
        def log_out() -> None:
            popup.dismiss()
            self.log_out()

        user = self.user or {}
        def place() -> None:
            popup.dismiss()
            self.show_database_place()

        extra = []
        if self.local:
            where = (f"{tr('Tasks on this phone only, without a server.')}\n"
                     f"{self.local_database()}")
            leave = tr("Log in to a server…")
            extra.append(button(tr("Database location…"), place))
        else:
            where = f"{tr('Logged in:')} {user.get('name', '')}\n{self.api.base_url if self.api else ''}"
            leave = tr("Log out")
        reminders = BoxLayout(size_hint_y=None, height=ROW)
        switch = CheckBox(active=self.reminders_on(), size_hint_x=None, width=ROW)
        switch.bind(active=lambda _box, on: self.set_reminders(on))
        reminders.add_widget(switch)
        reminders_label = Label(text=tr("Reminders on"), halign="left", valign="middle")
        reminders_label.bind(size=lambda w, size: setattr(w, "text_size", size))
        reminders.add_widget(reminders_label)
        popup = self._popup(
            tr("Menu"),
            label(where),
            form_row(tr("Language"), self.language_choice()),
            reminders,
            *extra,
            button(leave, log_out),
            button(tr("Close"), lambda: popup.dismiss()),
        )

    def language_choice(self) -> Choice:
        choice = Choice([(name, code) for code, name in i18n.LANGUAGES.items()],
                        i18n.get_language())
        choice.bind(text=lambda *_a: self._set_language(choice.value))
        return choice

    def _set_language(self, code: str) -> None:
        if code == i18n.get_language():
            return
        i18n.set_language(code)
        i18n.save_language(code)
        if self._open_popup is not None:
            self._open_popup.dismiss()
        if self.api is None:
            self.show_login()
        else:  # rebuild the list in the new language
            old, self._list = self._list, None
            self.show_list()
            if old is not None:
                self.screens.remove_widget(old)


def main() -> None:
    TodoMobileApp().run()


if __name__ == "__main__":
    main()
