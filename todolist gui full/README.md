# todo_db

Database layer for a to-do list application: SQLite + SQLAlchemy 2.0, with a
full change history for every task.

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Start scripts

Two bash scripts start the parts separately. They work from any directory,
create `.venv` and install `requirements.txt` on first use (and again when it
changes), so no manual setup is needed:

```bash
./run_client.sh                 # desktop program on todo.db
./run_client.sh --db ~/Documents/tasks.db   # ... on another database file (this run)
./run_server.sh                 # application server on todo_server.db, open to the network
./run_server.sh --db /srv/todo/server.db    # ... on another database file (any command)
./run_server.sh create-admin --name "Anna Kowalska" --email anna@example.com
./run_server.sh set-password --email anna@example.com
./run_server.sh run --port 9000 # extra options are passed to the server
```

`run_server.sh` reads `TODO_SERVER_DB`, `TODO_SERVER_HOST`,
`TODO_SERVER_PORT` and `TODO_TOKEN_DAYS` from the environment and warns when
the database has no administrator yet. The server listens on all networks
(`0.0.0.0`) and prints the addresses to connect to;
`TODO_SERVER_HOST=127.0.0.1` keeps it to this computer. `run_client.sh` checks that Tkinter and
a graphical display are available. `--help` on either shows its usage.

**Where the databases are.** By default `todo.db` (desktop program, local
mode) and `todo_server.db` (server) are in this folder.
- Server: `--db FILE` with any command (`./run_server.sh --db FILE
  create-admin …`, `python -m todo_server run --db FILE`), or
  `TODO_SERVER_DB=FILE`. It prints the file it uses at start; backups go to
  `backups/` next to it.
- Desktop program: the **Database file** field in the login window (with
  **Browse…**), or **Account → Database file…** while working locally – the
  window reopens on the chosen file. The choice is remembered in
  `settings.json` (`"database"`). `./run_client.sh --db FILE` or
  `TODO_DB=FILE` uses a file for one run only, in local mode.

Relative paths are taken from the folder you run the command in, `~` is your
home folder, and a missing folder is created. Choosing a file that does not
exist yet starts an empty database there (with workflows, tags and repeat
rules); choosing an existing one opens it. Nothing is copied or moved – to
move your tasks, move the file itself while the program is closed.

## Server mode of the desktop program

On first start the program asks where your tasks are:

- **On this computer** – works on a database file (`todo.db` unless you
  choose another, see above), with "Acting as".
- **On a server** – server address, email and password of an account on the
  application server. "Remember me" keeps the login for the next start in
  `client_login.json` (readable only by you, ignored by git); without it the
  login ends when the window closes.

The choice is remembered. **Account → Log out** (or the button next to your
name) ends the login and shows the login window again; in local mode
**Account → Log in to a server…** switches over. When the login expires or an
administrator ends it, the program says so and asks you to log in again.

In server mode the window looks and works the same: filters, sorting, history
and the task form are unchanged, and the history records the logged-in user.
Behind it, the program keeps an in-memory copy of the server's data, sends
every change to the server and then downloads the data again; every 30 seconds
(or with F5 / Account → Refresh) it picks up other people's changes. The
server resets repeating tasks at midnight, so the program only refreshes.

Administrators get **Manage → Users…** for server accounts: add, rename,
change email, set a new password, make administrator, deactivate.
Administrators also get the **Server** menu: **Server → Server settings…**
switches automatic history compression on or off and sets after how many days
history is compressed. For other users, and in local mode, the whole menu is
greyed out (the server refuses non-administrators anyway).
**Workflows and tags cannot be changed in server mode** (the server has no
API for that yet); those menu items are greyed out.

## Executables (no Python needed)

`build_desktop.py` makes standalone programs of the desktop program and the
server with PyInstaller (in its own environment, `build/venv-<system>`):

| System | Command | Result |
|---|---|---|
| Linux | `python3 build_desktop.py` | `dist/linux/todolist`, `dist/linux/todolist-server` |
| Windows | `py build_desktop.py` | `dist\windows\todolist.exe`, `dist\windows\todolist-server.exe` |
| Android | `./build_android.sh` | `android/bin/todolist-1.2-*-debug.apk` |
| Debian/Ubuntu/Mint | `./build_deb.sh` | `dist/todolist_<version>_amd64.deb` (both programs; `sudo apt install ./dist/todolist_*.deb`) |

PyInstaller builds only for the system it runs on. Without a Windows
computer, the GitHub Actions workflow `.github/workflows/todolist-build.yml`
(at the top of the repository) builds the `.exe` files: run it from the
Actions tab, then download the artifact `todolist-windows`.

`todolist` takes the same options as `run_client.sh` (`--db`), and
`todolist-server` the same commands as `python -m todo_server` (`run`,
`create-admin`, `set-password`, `--db`). Like the scripts, they keep
`settings.json`, the databases and the log in the folder they are started
from. Note that `todolist-server run` listens on 127.0.0.1 unless given
`--host 0.0.0.0` (`run_server.sh` adds that itself). On Linux the tray icon
uses the system's PyGObject (python3-gi), as the scripts do.

## NixOS

`flake.nix` has both programs as Nix packages and a NixOS module that runs
the server as a system service. In the system's flake (`/etc/nixos/flake.nix`):

```nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.todolist = {
    # Or a local copy: "path:/home/me/todolist%20gui%20full" (%20 for the spaces).
    url = "github:vertigofilip/Monty-Python-and-the-Holy-Grail?dir=todolist%20gui%20full";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, todolist, ... }: {
    nixosConfigurations.my-computer = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ./configuration.nix
        todolist.nixosModules.default
        {
          # The desktop program: "To-do list" in the menu, or `todolist`.
          environment.systemPackages = [ todolist.packages.x86_64-linux.client ];

          # The server, if this computer is to be one.
          services.todolist-server = {
            enable = true;
            openFirewall = true;  # for phones and other computers
            # port = 8000; host = "0.0.0.0"; tokenDays = 30;
            # dataDir = "/var/lib/todolist-server";
          };
        }
      ];
    };
  };
}
```

After `sudo nixos-rebuild switch`:

- The server runs as the systemd service `todolist-server` (user
  `todolist-server`). Its database and `backups/` are in `dataDir`; its log
  is shown by `journalctl -u todolist-server`. It is started at boot and
  restarted if it fails.
- Create the first administrator with
  `sudo todolist-server-admin create-admin --name "Anna Kowalska" --email anna@example.com`
  (also `set-password`). It works on the service's database as its user.
- The desktop program keeps its files (`settings.json`, `todo.db`, the log,
  the login) in `~/.local/share/todolist`; `TODO_HOME=...` chooses another
  folder. A relative `--db` is still taken from where it is started. Its tray
  icon and notifications work without anything else installed.

**Updating** to a newer version: the system's flake pins the to-do list at the
commit it last fetched (in `/etc/nixos/flake.lock`), so fetch the latest
pushed version and switch to it:

```bash
cd /etc/nixos
sudo nix flake update todolist      # newer Nix; older: sudo nix flake lock --update-input todolist
sudo nixos-rebuild switch           # restarts todolist-server with the new version
```

Only what is committed and pushed to GitHub arrives this way (with a local
`path:` input, the current files). The server's database is kept and gets
any new tables (e.g. the subtask templates of 1.1) when it starts.

Without installing, from this folder: `nix run path:.` (the desktop program)
and `nix run path:.#server -- run`. Use `path:`: without it the flake would
only see files committed to git. `flake.lock` pins the nixpkgs version.

## Phone app (Android, `todo_mobile`)

The desktop program uses Tkinter, which phones do not have, so the phone app
is a separate client written with Kivy. It works against the application
server, or without one on the phone's own database:

- **Login** – server address, email, password, "Remember me on this phone"
  (the token is kept in the app's private storage).
- **Without a server** (button under the login) – the tasks are kept in
  `todo.db` in the app's private storage, with the same task logic as the
  desktop program (`todo_db`; `todo_mobile/local.py` answers the app's
  requests the way the server would). There is one user, "Me". The choice
  is remembered; **Menu → Log in to a server…** goes back to the login. These
  tasks are separate from the server's and from the computer's `todo.db` –
  nothing is synchronised.
- **Database location…** (Menu in that mode, or under the login) chooses the
  file: type a path or pick **App storage (private)** (the default, removed
  with the app), **App folder on the phone storage**
  (`Android/data/org.todolist.todolist/files`, visible over USB, also removed
  with the app) or **Documents** (`Documents/todo/todo.db`, kept when the app
  is removed). Places outside the app's own folders need Android's
  "All files access" permission: the app opens the settings page to allow it,
  then tap **Use** again. When the chosen file does not exist yet, the app asks
  whether to copy your tasks there or start with an empty list; the old file
  is left as it was. The choice is remembered (`local_database` in the app's
  settings).
- **Task list** – the task tree with subtasks indented; search box and
  not done / all / done filter (the search also finds the location); a second
  line with stage, due date, priority, urgency, assignee, location, tags,
  progress and repeats – red for an overdue task. Refreshes every 30 seconds.
- **Task form** – tap a task: name, description, stage, due date (typed as
  YYYY-MM-DD or picked with **Calendar**: month by month, weeks from Monday,
  Today / No date / Cancel), location, priority, urgency, assignee, repeat,
  repeat count, tags; Next stage (green), Complete, New subtask, History,
  Delete. **New task** at the bottom of the list; it is assigned to you.
- **Menu** – who is logged in, language (English / Polski), **Reminders on**,
  Log out.
- **Reminders** – unfinished tasks due today or overdue, with the same rules as
  the desktop program (`todo_db/reminder_core.py`): when a task becomes due,
  and again every 60 minutes while it is (`reminder_check_minutes`,
  `reminder_repeat_minutes`, `reminder_only_mine` in the app's settings). On
  Android a background service (`todo_mobile/reminder_service.py`) checks
  every 15 minutes, also with the app closed, and shows one notification
  listing the due tasks; tapping it opens the app, it updates in between and
  disappears when nothing is due. Android keeps the service running only
  with a small permanent "Reminders are on" notification; on Android 13+ the
  app asks once for permission to show notifications. It starts when you log
  in (or open the tasks without a server) and stops when you log out or
  switch reminders off; after the phone restarts, open the app once to start
  it again. While the server cannot be reached, it reminds of the tasks it
  sent at the last check (kept in the app's private folder). Run on a
  computer, the app shows the desktop's orange reminder window instead.
- The phone's Back button goes back from the task form and the history.

Not on the phone: sorting, saved filters, moving tasks, users,
workflows, tags and server settings – use the desktop program for those.

Try it on a computer (needs `pip install kivy`):

```bash
.venv/bin/python todo_mobile/main.py --size=420x820
```

Build the Android package (needs Java 17 and the usual build tools; the first
build downloads the Android SDK/NDK, several GB, into `~/.buildozer` and
builds in `~/Android/todolist-build` – it takes a while, later builds take a
minute or two):

```bash
./build_android.sh              # -> android/bin/todolist-1.2-*-debug.apk
./build_android.sh deploy       # build and install on a USB-connected phone
```

The build takes the pure-Python libraries `filetype` and `typing_extensions`
from `.venv` (run `./run_client.sh` once first); SQLAlchemy and SQLite for the
mode without a server come from python-for-android's recipes.

Copy the `.apk` to the phone and open it (allow installing from this source),
or use `deploy` with USB debugging switched on. With a server, it must be reachable
from the phone: `./run_server.sh` listens on the network and prints the
address to enter, e.g. `http://192.168.1.10:8000` (if the phone cannot connect,
allow the port in the firewall: `sudo ufw allow 8000/tcp`).
The app allows plain `http://` for that; over the internet put the server
behind HTTPS, because otherwise passwords and tokens travel unencrypted.

iPhone: Kivy apps can be built for iOS only on a Mac with Xcode.

## Run the tests

```bash
python -m pytest
```

## Run the demo

```bash
python -m todo_db.main
```

This rebuilds `demo.db` from scratch in the current directory, seeds it, and
prints the tasks and their history. It does not touch `todo.db`.

## Run the to-do program

```bash
python -m todo_db.app
```

A Tkinter window (standard library; on Debian/Ubuntu install `python3-tk` if
it is missing) working on `todo.db` in the current directory (or another
file: `--db`, see "Where the databases are"). The file is
created on first start with the sample users, workflows, repeat rules and tags
but no tasks.

- The task tree shows stage, due date, priority, urgency, assignee, location, tags, progress
  and repeat. Location is free text ("Gym", "Office, room 12"), set in the task form.
  Unfinished tasks past their due date are shown in red.
- **New task / New subtask / Edit** open a form; double-click or Enter edits.
  A new task is assigned to the person adding it ("Acting as", or the logged-in
  user); pick another assignee or "(none)" in the form to change that.
- **Next stage** and **Complete** move the selected task through its workflow
  (repeating tasks come back at midnight after their interval, see below).
- **Up / Down / Indent / Outdent** reorder and re-parent; **Delete** removes a
  task without subtasks.
- The bottom panel shows the selected task's description and history.
- **Acting as** (top right) is the user recorded in the history; new tasks are
  created by that user.
- **Filters:** the row under the column headings filters the list by every
  column: a text box for the task name, and a drop-down for stage (including
  "(not done)" / "(done)"), due date ("(overdue)", "(today)", "(later)"),
  priority, urgency, assignee, location, tag, progress (0 %, 1–99 %, 100 %) and
  repeat. Each drop-down takes several choices: click it and tick them in the
  list (it stays open; Escape, Enter or a click elsewhere closes it, "All"
  unticks everything). A task passes a column if it matches any of its ticked
  choices, so "To do" + "In progress" shows tasks at either stage. Filters of
  different columns combine; ✕ clears them all. A parent that
  does not match itself is still shown, in grey italics, when one of its
  subtasks matches, and while filtering all shown tasks are expanded.
- **Filters menu (saved filter presets):** "Save current filters…" stores the
  filters now set under a name; each saved preset is then one click in the
  menu. "Filter presets…" lists them to apply, add, edit (name, task-name text
  and every column's choices), delete and reorder. Presets are kept only on this
  computer, in `settings.json` (`filter_presets`), and work in both modes. They
  remember users, tags and repeat rules by id, so renaming one or switching the
  language does not break them; a choice that no longer exists is set to "All"
  with a warning.
- **Sorting menu (saved sort orders):** the same for sorting. "Save current
  sort…" opens the Sort window with a name field; each saved order is one click
  in the menu, and "Sort presets…" applies, adds, edits, deletes and reorders
  them. "Clear sort" returns to the manual order. Kept in `settings.json`
  (`sort_presets`), on this computer only.
- **Sort…** opens a window where you build the sort order: move fields from
  "Available fields" to the sort list, arrange them with Up / Down (the first
  one matters most), and switch each between ascending and descending. Fields:
  every column plus "Created at". Sorting applies within each level of the
  tree; ties keep the manual order, and empty values always go last. The
  sorted columns show ▲/▼ with their level in the heading. Text is sorted
  alphabetically including Polish letters (c < ć < d). The order is saved in
  `settings.json`. While sorting is on, Up / Down are disabled; "Clear" in the
  window returns to the manual order.
- **Narrow windows:** the toolbar buttons wrap onto extra rows, the
  description wraps to the window width, and the task list and history scroll
  sideways (scrollbar under each list) instead of squeezing the columns. The
  filters scroll together with their columns.
- **Manage → Users…** adds, renames and deactivates/reactivates users. Users
  are never deleted; a deactivated user can no longer be picked as assignee or
  in "Acting as", but stays on existing tasks. At least one user must stay
  active.
- **Manage → Workflows…** manages the progression types: add, rename and
  delete workflows, and add, rename, reorder and delete their stages. "Toggle
  final" marks whether a stage counts as done. A new workflow starts with
  "To do" and "Done". Stages and workflows that tasks still use cannot be
  deleted.
- **Manage → Tags…** adds, renames and deletes tags and shows how many tasks
  use each one. A tag still used by tasks cannot be deleted; remove it from
  those tasks first. Renaming does not rewrite history.
- **Random task** draws a task to do next and shows it (name, parent tasks,
  priority, urgency, stage, due date, description). Only unfinished tasks
  without subtasks take part. More important and urgent tasks come up more
  often; from the most to the least favoured: Important+High, Normal+High,
  Important+Medium, Normal+Medium, Important+Low, Normal+Low, Maybe+High,
  Maybe+Medium, Maybe+Low (weights 9 down to 1, `todo_db/pick.py`). "Another"
  draws a different one; "Show in list" selects it (clearing the filters if
  they hide it). The phone has the same button under the task list.
- **Subtask templates:** ready-made subtasks (name, description, priority,
  urgency). **From template…** (toolbar) opens the list for the selected task:
  choose one or several (Ctrl/Shift+click) and press "Add as subtasks", or
  double-click one. Each becomes an ordinary subtask at the first stage of the
  parent's workflow, assigned to the parent's assignee. The same window edits
  the list (Add / Save / Delete / Clear); **Manage → Subtask templates…** opens
  it just for editing. Templates are kept in the database (the local file, or
  the server, where every user shares and may change them); deleting one
  leaves the subtasks made from it. On the phone: "From template…" on a task,
  and "Subtask templates…" in the menu.

- **Language** switches the interface between English and Polish at once. The
  choice is saved in `settings.json` in the current directory; without it the
  program starts in the system language if that is Polish, else in English.

Every change goes through `TaskService`, so the history is always written.

### Reminders

A task can have a **due date** (the "Due date" field in the task form, typed
as `YYYY-MM-DD` or picked with the 📅 button from a calendar, which starts on
Monday and has "Today" and "No date"; empty = no deadline). While the program is open, a background
thread looks every 15 minutes for unfinished tasks due today or earlier. When
one is newly due, or an hour has passed since the last reminder, a window
"Task reminder" ("Przypomnienie o zadaniu") appears above other programs: an
orange background, large text, and every due task one under another (overdue
ones with their date). It stays until you close it and keeps its list up to
date: a task you complete disappears from it, and when none is left it closes
by itself. A task done, deleted or moved to a later day is no longer reminded.
In server mode only tasks assigned to you or to nobody are reminded.

With `"reminder_window": false` the reminders are system notifications instead
(through [plyer](https://github.com/kivy/plyer); on Linux `notify-send`), one
per task; their look is up to the system.

The defaults are constants at the top of `todo_db/reminders.py`. Every
setting can also be changed in `settings.json` without touching the code; at
start the program writes the ones missing there with their default values, so
the file always shows what can be set (your own values are kept):

| Key | Default | Meaning |
| --- | --- | --- |
| `reminders_enabled` | `true` | `false` switches reminders off |
| `reminder_check_minutes` | `15` | how often to look for due tasks |
| `reminder_repeat_minutes` | `60` | least time before the same task is shown again |
| `reminder_window` | `true` | the program's own window; `false` = system notifications |
| `reminder_background` | `"#FF8C00"` | the window's colour (orange); a name like `"gold"` works too |
| `reminder_font_size` | `16` | the window's text size in points |
| `reminder_notification_seconds` | `10` | system notifications: how long they stay (if the system allows) |
| `close_to_tray` | `true` | closing the window keeps the program in the tray; `false` = quit |
| `reminder_only_mine` | `true` | server mode: only tasks assigned to you or to nobody; `false` = all |
| `sync_seconds` | `30` | server mode: how often the window fetches other people's changes |

Other keys in the file are saved by the program itself: `language`,
`client_mode`, `server_url`, `server_email` and `sort`. A wrong value (e.g.
text instead of a number) is ignored and noted in the log.

If the server cannot be reached or a reminder cannot be shown, the
program carries on; the problem is written to `todo_client.log` in the current
directory, together with a line for every reminder shown.

Reminders also work while the server cannot be reached: every check that
reaches it keeps the unfinished tasks in `reminder_tasks.json` (current
directory, readable only by you, ignored by git), and offline the due tasks
are found among those. Changes made elsewhere in the meantime (a task done on
the phone) count once the server is back. Logging out deletes the file. The
phone app does the same with its own copy.

To try it quickly: put `"reminder_check_minutes": 0.1, "reminder_repeat_minutes": 0.5`
in `settings.json` (a check every 6 seconds, a repeat after 30 seconds), start
`./run_client.sh`, add a task with today's date as its due date, and wait a few
seconds. Mark it done (Complete) and the reminders stop. Set them back to
15 and 60 afterwards.

### Running in the background (tray icon)

While the program runs, its logo sits in
the system tray, next to the clock and the icons of other background
programs. Closing the window only hides it: the program keeps running and
reminders keep appearing. The icon's menu:

- **Open the to-do list** (also a click on the icon on most desktops)
- **Check reminders now** - shows every due task at once
- **Reminders on** - switches reminders off and on (saved as `reminders_enabled`)
- **Quit** - really ends the program (a login that is not remembered ends too)

Account → Quit (Ctrl+Q) in the window does the same.

The first time the window is closed, a message says where the program went.
`"close_to_tray": false` in `settings.json` makes closing the window quit the
program as before. The icon uses [pystray](https://github.com/moses-palmer/pystray)
and Pillow (in `requirements.txt`). On Linux its menu needs PyGObject with
AppIndicator, which comes from the system rather than from pip
(`sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1`, already
installed on Linux Mint/Ubuntu); the program uses the system's copy. Without
it there is no icon, and closing the window quits the program. The
icon's menu keeps the language the program started in.

### Logo

`todo_db/logo.png` (512×512) is the program's logo: the tray icon, the icon of
the desktop windows, and the phone app's icon (`icon.filename` in
`android/buildozer.spec`; `build_android.sh` copies it). It is the default Kivy
logo the phone app had from the start. To change the logo, replace this one
file (a square PNG) and rebuild the APK.

### Languages

Only the interface is translated: buttons, menus, column titles, messages,
priority names, and the change types and field names in the history. Your own
data (task, stage, workflow, user, tag and repeat-rule names) is shown as
entered, so the seeded "To do" / "Done" stages stay English until renamed in
Manage → Workflows. A workflow created while the program is in Polish gets
"Do zrobienia" / "Gotowe" as its starting stages.

The texts live in `todo_db/i18n.py`, keyed by the English text. To add a
language, add it to `LANGUAGES` and add its dictionary to `_TRANSLATIONS`;
`tests/test_i18n.py` checks that no interface text is left untranslated.

## Layout

| File | Contents |
| --- | --- |
| `todo_db/models.py` | Models and enums |
| `todo_db/database.py` | Engine (foreign keys ON), session factory, `create_all()` |
| `todo_db/services.py` | `TaskService` — all task writes and their history |
| `todo_db/templates.py` | Subtask templates (shared by the program, the server and the phone) |
| `todo_db/seed.py` | Sample data |
| `todo_db/main.py` | Demo |
| `todo_db/app.py` | The to-do program (Tkinter GUI) |
| `todo_db/i18n.py` | Interface translations (English, Polish) |
| `todo_db/reminders.py` | Due-date reminders (background thread; the window itself is in `app.py`) |
| `todo_db/tray.py` | The tray icon and its menu |
| `todo_db/logo.png` | The program's logo (tray, windows, phone app) |
| `tests/` | pytest tests, run against an in-memory database |

## Usage

```python
from todo_db.database import create_all, make_engine, make_session_factory
from todo_db.services import TaskService

engine = make_engine("sqlite:///todo.db")
create_all(engine)
with make_session_factory(engine)() as session:
    service = TaskService(session)
    task = service.create_task("Write report", stage_id=1, created_by_id=1)
    service.update_task(task.id, changed_by_id=1, name="Write the report", stage_id=2)
    for change in service.get_history(task.id):
        print(change.change_type.name, change.field_name, change.old_value, change.new_value)
```

Each public write method of `TaskService` is one transaction: it commits at
the end and rolls everything back (task change and log rows) on any error.
Invalid input raises `ValueError`; database constraint failures raise
SQLAlchemy's `IntegrityError`.

## Choices

Where the spec was ambiguous, the simplest option was picked.

**One deviation from the spec: `TaskChange.TaskId` has no database-level
foreign key.** The spec asks for an FK without cascade *and* for history that
survives deleting the task. With SQLite foreign keys ON those conflict: a
non-cascading FK blocks the delete. `TaskId` is therefore a plain indexed
integer, so `get_history(task_id)` still works after the task is gone. The
`Task` table uses `AUTOINCREMENT` so a deleted id is never reused.

Naming
- Python attributes are snake_case (`stage_id`); tables and columns use the
  spec's names (`Task.StageId`). `FieldName` in the history uses the column
  name.
- `Priority` and `Urgency` are stored as integers (0/1/2); the other enums are stored as
  their names.

Ordering
- `Order` is 1-based, for both stages and tasks. A new task goes to the end of
  its siblings.
- `move_task`: `new_order` is clamped to the valid range; `None` means "at the
  end".
- Only the moved task gets `Moved` rows. Siblings that shift to keep `Order`
  contiguous are not logged.
- Deleting a task also closes the gap in its siblings' `Order`.

History
- `Created` row: `NewValue` is the task name. `Deleted` row: `OldValue` is the
  task name. `Completed` row: no field or values.
- `Urgency` (Low=0, Medium=1, High=2, default Medium) was added after the
  spec, next to `Priority`: priority is how important a task is, urgency how
  soon it is needed. It is stored as an integer and logged like Priority.
  `create_all()` adds the column to databases created before it existed.
- Names (not ids) are also stored for `RepeatRuleId` and `ParentId`, as for
  `StageId` and `AssigneeId`.
- Tags can be changed with `update_task(..., tag_ids=[...])`; this is logged
  as one `Updated` row for `Tags` with the sorted tag names.
- `update_task` accepts only: `name`, `description`, `priority`, `stage_id`,
  `assignee_id`, `due_date`, `location`, `repeat_rule_id`, `repeat_count`, `tag_ids`,
  `parent_id`, `order`. Anything else (including `repeat_done`, `created_at`) is rejected.
- `get_history` orders by `ChangedAt`, then `Id`, since rows written in one
  transaction can share a timestamp.
- Creating a task directly in a final stage writes only the `Created` row.

Repeating tasks
- The `StageChanged` and `Completed` rows carry the user who made the change.
  The `RepeatDone` increase and the reset to the first stage are logged with
  `ChangedById = null`.
- "First stage" means the lowest `Order` in the workflow of the stage the task
  was just completed in.
- **Changed from the original spec (item 7), on request:** the reset no longer
  happens in the same transaction. Completing a repeating task counts it at
  once (`RepeatDone` + 1) and stores in `Task.NextResetAt` when it is due
  again: local midnight at the start of the day that is one interval after
  the completion day. A daily task done at any time today comes back at
  midnight tonight, a weekly one a week from today at midnight, "every 3
  days" three days later. Months and years keep the day of the month and
  clamp at month ends (31 Jan + 1 month = 28/29 Feb).
- The interval counts from the day the task was completed, not from the
  previous due date.
- `TaskService.reset_due_tasks()` sends every due task back to the first
  stage (logged with `ChangedById = null`). The program runs it at start
  (catching up on anything that fell due while it was closed) and just after
  every local midnight while it is open.
- Reopening a waiting task by hand, or removing its repeat rule, cancels the
  reset. With a limited `RepeatCount`, the last completion schedules nothing
  and the task stays done.
- The task list shows a waiting reset in the Repeat column as `⟳ YYYY-MM-DD`.
- **Due dates of repeating tasks** follow the cycle due date, + interval,
  + 2 intervals… (counted from the due date, so month ends do not drift).
  - Completing the task moves its due date to the next one after today: a
    weekly task due today gets next week's date; one completed early gets the
    one after its current date; one completed late skips the missed dates.
  - A due date that passes with the task not done moves, at midnight, to the
    first date of the cycle that is today or later, so a repeating task is
    never shown as overdue (`TaskService.roll_missed_due_dates()`, run with
    `reset_due_tasks()`; on the server at start-up and every midnight).
  - Both are logged as `Updated DueDate` rows with `ChangedById = null`. A
    task whose limited `RepeatCount` is used up keeps its last date. Tasks
    without a repeat rule keep their date and show as overdue.
- "Local" is the time zone of the computer running the program.
- The standard intervals are every 1–10 days, 1–3 weeks, monthly and yearly
  (`REPEAT_RULES` in `seed.py`). The program adds any that are missing each
  time it starts, so older databases get them too; existing rules are kept.
  The program shows interval names in the chosen language, built from the
  interval and unit; the stored `Name` stays English.

Progress
- Without subtasks: 1-based stage position / number of stages. So the first
  stage of "Simple" is 50 % and a final stage is always 100 %.
- With subtasks: only direct subtasks count.

Other
- A task may be moved to a stage of a different workflow; this is not checked.
- Assigning a task to a deactivated user is not checked.
- Seed: "Weekly review" reaches `RepeatDone = 3` by being completed three times
  through the service, and "Buy groceries" is created in "To do" and then moved
  to "Done", so both have real history.

## Application server (`todo_server`)

An HTTP API on top of the same `todo_db` package, for running the to-do list
on your own server with logins. It uses its own database file
(`todo_server.db` by default), separate from the desktop program's `todo.db`.
The desktop program can work on it too (see "Server mode of the desktop program").

### Start

```bash
pip install -r requirements.txt
python -m todo_server create-admin --name "Anna Kowalska" --email anna@example.com
python -m todo_server run                 # http://127.0.0.1:8000, docs at /docs
```

Options: `--db PATH` (before the command) chooses the database file;
`run --host 0.0.0.0 --port 8000` listens on the network, `--token-days 30`
sets how long a login lasts. `set-password --email ...` changes a password.
The interactive API documentation is at `http://127.0.0.1:8000/docs`.

**On a real server, put it behind HTTPS** (e.g. Caddy or nginx with a Let's
Encrypt certificate) and keep `--host 127.0.0.1`, so passwords and tokens never
travel unencrypted.

### Logins

- `POST /auth/login` with `{"email", "password"}` returns a token; send it as
  `Authorization: Bearer <token>` with every request. `POST /auth/logout` ends
  the login at once.
- Passwords are stored as salted scrypt hashes; tokens only as SHA-256 hashes,
  so a stolen database file contains neither.
- After 5 wrong passwords for the same email and address within 15 minutes,
  logins are refused for a while (HTTP 429).
- Roles: `User` works with tasks; `Admin` also manages users, settings and the
  database. Deactivating a user, changing their password or taking away admin
  rights ends their logins. The last active admin cannot be removed.
- The history records the logged-in user; there is no "Acting as".
- Simpler than the access/refresh token pair described earlier: one random
  token per login, checked against the database on every request, so it can
  be revoked immediately.

### Endpoints

| Who | Endpoints |
| --- | --- |
| Everyone | `POST /auth/login` |
| Logged in | `GET /auth/me`, `POST /auth/logout`, `GET /users`, `GET /workflows`, `GET /tags`, `GET /repeat-rules` |
| Logged in | `GET/POST /tasks`, `GET/PATCH/DELETE /tasks/{id}`, `POST /tasks/{id}/move`, `GET /tasks/{id}/history` |
| Logged in | `GET/POST /subtask-templates`, `PATCH/DELETE /subtask-templates/{id}` |
| Admin | `GET/POST /admin/users`, `PATCH /admin/users/{id}` |
| Admin | `GET/PUT /admin/settings`, `POST /admin/history/compress`, `POST /admin/tasks/{id}/history/compress`, `POST /admin/maintenance/run` |
| Admin | `GET /admin/database`, `POST /admin/database/backup`, `GET /admin/database/backups`, `GET /admin/database/backups/{name}`, `POST /admin/database/vacuum` |

Priority and urgency can be sent by name (`"Important"`) or number (`2`).

### History compression

Compression merges a task's old history rows into **one** row of type
`Compressed`. It is lossy on purpose: per field it keeps only the value before
the first change and after the last one (fields that ended where they started
are left out), plus the number of changes of each type, who made them and the
time span. Intermediate values are gone for good, so make a backup first if
they might matter. The summary is stored as JSON in `NewValue`; the API
returns it parsed as `summary`, and the desktop program shows it as e.g.
"13 changes, 2026-01-01 – 2026-03-01 | Name: Draft → Final report".

- **Manual, one task:** `POST /admin/tasks/{id}/history/compress` with `{}`
  compresses its whole history, or with `{"older_than_days": 30}` only rows
  older than 30 days. Works for deleted tasks too.
- **Manual, everything:** `POST /admin/history/compress` with
  `{"older_than_days": 90}` (or `{}` for the saved setting) compresses, for
  every task, all rows older than that.
- **Automatic:** `PUT /admin/settings` with
  `{"auto_compress_enabled": true, "compress_after_days": 90}`. It is **off by
  default**, because it deletes detail. When on, it runs with the nightly
  maintenance.
- Compressing again merges into the existing summary, so each task has at most
  one `Compressed` row, always before its newer rows.
- Compression only deletes rows; run `POST /admin/database/vacuum` afterwards
  to make the file itself smaller.

### Nightly maintenance

At start-up and just after every local midnight the server resets repeating
tasks that are due (as the desktop program does) and, if enabled, compresses
old history. `POST /admin/maintenance/run` runs it immediately;
`GET /admin/database` shows what the last run did.

### Database management

`GET /admin/database` shows the file size, row counts, the oldest history
entry, active logins, the settings and the last maintenance run.
`POST /admin/database/backup` makes a consistent copy while the server runs
(into `backups/` next to the database); backups can be listed and downloaded.
Restoring is manual: stop the server and replace the database file with a
backup.

### Not done yet

- Workflows, stages and tags can be read through the API but not changed; that
  is still done in the desktop program (or would need more endpoints).
