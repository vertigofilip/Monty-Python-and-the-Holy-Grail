# Code map

How the program is put together. Every function, file by file, is listed in
[FUNCTIONS.md](FUNCTIONS.md). GitHub draws the diagrams below; other Markdown
viewers may need a Mermaid plugin.

## The three programs

The desktop program, the phone app and the server share the code in `todo_db`.
Data lives in one SQLite file: on the computer, on the phone, or on the server.

```mermaid
flowchart TB
    subgraph computer["Computer"]
        desktop["Desktop program<br/>todo_db/app.py (Tkinter)"]
        localdb[("todo.db")]
    end
    subgraph phone["Phone"]
        mobile["Phone app<br/>todo_mobile/main.py (Kivy)"]
        localapi["LocalApi<br/>todo_mobile/local.py"]
        phonedb[("database on the phone")]
    end
    subgraph server["Server"]
        api["todo_server/api.py (FastAPI)"]
        serverdb[("todo_server.db")]
    end
    desktop -- "local mode" --> localdb
    desktop -- "server mode: HTTP" --> api
    mobile -- "server mode: HTTP" --> api
    mobile -- "without a server" --> localapi
    localapi --> phonedb
    api --> serverdb
```

## Which module uses which

An arrow means "imports"; the main links are shown, not every one. The shared
modules at the bottom know nothing about any window or about the server.

```mermaid
flowchart TB
    subgraph clients["Windows and screens"]
        app["todo_db/app.py"]
        mobile_main["todo_mobile/main.py"]
    end
    subgraph server["Server"]
        api["todo_server/api.py"]
        schemas["schemas.py"]
        security["security.py"]
        dbadmin["dbadmin.py"]
        maintenance["maintenance.py"]
    end
    subgraph phone["Phone helpers"]
        local["local.py"]
        phone_api["api.py"]
        tasks_mobile["tasks.py"]
        storage["storage.py"]
        reminder_service["reminder_service.py"]
    end
    subgraph desktop["Desktop helpers"]
        remote["remote.py"]
        reminders["reminders.py"]
        tray["tray.py"]
    end
    subgraph shared["Shared rules"]
        services["services.py"]
        management["management.py"]
        templates["templates.py"]
        presets["presets.py"]
        pick["pick.py"]
        reminder_core["reminder_core.py"]
        compression["compression.py"]
        api_data["api_data.py"]
        seed["seed.py"]
        database["database.py"]
    end
    models["models.py"]
    base["settings.py and i18n.py"]

    app --> remote & reminders & tray & services & management & templates & presets & pick
    mobile_main --> local & phone_api & tasks_mobile & storage & reminder_service
    mobile_main --> pick & templates & reminder_core
    api --> schemas & security & dbadmin & maintenance
    api --> services & management & templates & api_data & compression & seed & database
    local --> services & management & templates & api_data & seed & database
    remote --> services & management
    reminders --> reminder_core & remote
    reminder_service --> reminder_core
    tasks_mobile --> presets
    services --> models
    management --> models
    templates --> models
    compression --> models
    database --> models
    seed --> models
    api_data --> models
    reminder_core --> base
    presets --> base
    management --> base
```

## The database

`TaskChange.TaskId` has no foreign key on purpose: the history stays after a
task is deleted. `ServerSetting` stands alone.

```mermaid
erDiagram
    Workflow ||--|{ Stage : "has, in order"
    Stage ||--o{ Task : "holds"
    Task ||--o{ Task : "has subtasks"
    User |o--o{ Task : "is assigned"
    User ||--o{ Task : "created"
    RepeatRule |o--o{ Task : "repeats"
    Task ||--o{ TaskTag : ""
    Tag ||--o{ TaskTag : ""
    Task ||..o{ TaskChange : "history"
    User |o--o{ TaskChange : "changed by"
    User ||--o{ ApiToken : "logged in with"
    SubtaskTemplate {
        int Id
        string Name
        string Description
        int Priority
        int Urgency
    }
    ServerSetting {
        string Key
        string Value
    }
```

## The same window in both modes

The desktop windows always read from a SQLAlchemy session and call a service.
Only what stands behind those two differs, which is why the windows do not need
to know which mode they are in.

```mermaid
classDiagram
    class TodoApp {
        session
        service
        refresh()
        show_history()
    }
    class TaskService {
        create_task()
        update_task()
        move_task()
        delete_task()
        get_history()
        get_histories()
        get_progress_percent()
    }
    class RemoteTaskService {
        same methods, over HTTP
    }
    class LocalManagement {
        session
        add_workflow(), add_tag()...
    }
    class RemoteManagement {
        session
        same methods, over HTTP
    }
    class LocalTemplates {
        list(), add(), update(), delete()
    }
    class RemoteTemplates {
        same methods, over HTTP
    }
    class Mirror {
        session
        sync()
    }
    class ApiClient {
        request()
    }
    TodoApp ..> TaskService : local mode
    TodoApp ..> RemoteTaskService : server mode
    TodoApp ..> LocalManagement : local mode
    TodoApp ..> RemoteManagement : server mode
    TodoApp ..> LocalTemplates : local mode
    TodoApp ..> RemoteTemplates : server mode
    TodoApp ..> Mirror : reads the copy
    RemoteTaskService --> ApiClient
    RemoteManagement --> ApiClient
    RemoteTemplates --> ApiClient
    Mirror --> ApiClient
```

## What happens when a task changes

In server mode the desktop program keeps an in-memory copy of the server's data,
the *mirror*, and downloads it again after every change and every few seconds.

```mermaid
sequenceDiagram
    actor User
    participant Window as TodoApp
    participant Service as RemoteTaskService
    participant Server as todo_server/api.py
    participant Core as TaskService (server)
    participant Mirror
    User->>Window: Next stage
    Window->>Service: update_task(id, stage_id)
    Service->>Server: PATCH /tasks/{id}
    Server->>Core: update_task(), writes the history
    Core-->>Server: the task
    Server-->>Service: 200, the task
    Service->>Mirror: sync(), downloads everything
    Window->>Window: refresh(), redraws from the new copy
```

In local mode the same `update_task` runs in the program itself and the window
redraws from the database directly. On the phone, `LocalApi` answers the same
paths as the server, so the screens do not differ either.

## Drawing the task list

`refresh()` runs after every change and every filter or sort change.

```mermaid
flowchart TD
    refresh["refresh()"] --> options["_update_filter_options():<br/>new choices, ticks kept"]
    options --> progress["get_progress_percent()<br/>for every task"]
    progress --> sort["_sorted(): top-level tasks<br/>in the chosen order"]
    sort --> insert["_insert(): add a row, then its subtasks"]
    insert --> match{"Passes the filters?"}
    match -- "yes" --> keep["The row stays"]
    match -- "no, but a subtask does" --> grey["The row stays in grey italics"]
    match -- "no" --> drop["The row is removed"]
    keep --> cells["_tree_moved(): line up the filters<br/>and the coloured cells"]
    grey --> cells
    drop --> cells
    cells --> history["show_history()"]
    history --> selected{"A task selected?"}
    selected -- "yes" --> one["get_history(): that task"]
    selected -- "no" --> all["get_histories(): every task in the list"]
    one --> rows["_show_history_rows():<br/>history filters and sort"]
    all --> rows
```

## Reminders

`todo_db/reminder_core.py` holds the rules and the checking thread; the desktop
and the phone only add where the tasks come from and how they are shown.

```mermaid
flowchart TD
    thread["Reminders._run(): every reminder_check_minutes"] --> check["Reminders.check()"]
    check --> find{"Where from?"}
    find -- "desktop, local" --> localdue["local_due_tasks()"]
    find -- "desktop, server" --> remotedue["remote_due_tasks()"]
    find -- "phone, own database" --> phonelocal["find_due_tasks(): LocalApi"]
    find -- "phone, server" --> phonedue["find_due_tasks(): the server"]
    remotedue --> saved["with_saved_copy():<br/>the last tasks if the server is out of reach"]
    phonedue --> saved
    phonelocal --> rule
    localdue --> rule["is_due(): not done, and due today or earlier,<br/>or Important, or High urgency"]
    saved --> rule
    rule --> time{"New, or shown<br/>reminder_repeat_minutes ago?"}
    time -- "yes" --> popup["Remind of all of them"]
    time -- "no" --> update["Only update an open reminder"]
    popup --> show{"Shown how?"}
    show -- "desktop" --> window["ReminderWindow, or system notifications"]
    show -- "phone" --> android["AndroidNotification"]
```

## A request on the server

```mermaid
flowchart LR
    request["HTTP request"] --> token["current_token():<br/>401 without a valid login"]
    token --> admin{"/admin/... ?"}
    admin -- "yes" --> isadmin["admin_user():<br/>403 for other users"]
    admin -- "no" --> check
    isadmin --> check["schemas.py checks the data:<br/>422 if wrong"]
    check --> exists["get_task() / get_item():<br/>404 if missing"]
    exists --> write["write(): runs the change;<br/>400 refused, 409 conflict"]
    write --> answer["api_data.py builds the answer"]
```

A nightly job (`maintenance.py`) resets repeating tasks that are due and, when
that is switched on, compresses old history.

## The phone's screens

```mermaid
stateDiagram-v2
    [*] --> Login: no login remembered
    [*] --> List: remembered login, or own database
    Login --> List: logged in
    List --> Task: tap a task, or New task
    List --> Templates: Menu, Subtask templates
    Task --> Task: open a subtask
    Task --> History: History
    Task --> Templates: From template
    History --> Task: Back
    Templates --> Task: Back
    Templates --> List: subtasks added, or Back
    Task --> List: saved, or Back
    List --> Login: Log out
```
