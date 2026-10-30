# The to-do list for Nix: the desktop program ("client") or the application server ("server").
#
#   pkgs.callPackage ./package.nix { component = "client"; }   bin/todolist + a menu entry
#   pkgs.callPackage ./package.nix { component = "server"; }   bin/todolist-server
{
  lib,
  python3Packages,
  component ? "client",
  # client only
  gobject-introspection,
  gtk3,
  libayatana-appindicator,
  libnotify,
  wrapGAppsHook3,
  makeDesktopItem,
  copyDesktopItems,
}:

let
  client = component == "client";
  py = python3Packages;
in
assert lib.assertOneOf "component" component [ "client" "server" ];
py.buildPythonApplication {
  pname = if client then "todolist" else "todolist-server";
  version = "1.5";
  pyproject = true;

  # Only the code: never the databases, settings or logins in the project folder.
  src = lib.fileset.toSource {
    root = ./..;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      (lib.fileset.fileFilter (f: f.hasExt "py" || f.name == "logo.png") ../todo_db)
      (lib.fileset.fileFilter (f: f.hasExt "py") ../todo_server)
    ];
  };

  build-system = [ py.setuptools ];

  dependencies =
    [ py.sqlalchemy ]
    ++ lib.optionals client [
      py.tkinter
      py.httpx
      py.plyer
      py.pystray
      py.pillow
      py.pygobject3 # the tray icon's menu (AppIndicator)
    ]
    ++ lib.optionals (!client) [
      py.fastapi
      py.uvicorn
    ];

  nativeBuildInputs = lib.optionals client [
    gobject-introspection
    wrapGAppsHook3
    copyDesktopItems
  ];
  buildInputs = lib.optionals client [
    gtk3
    libayatana-appindicator
  ];

  # Each package has one of the two commands.
  postInstall = ''
    rm $out/bin/${if client then "todolist-server" else "todolist"}
  ''
  + lib.optionalString client ''
    install -Dm644 todo_db/logo.png $out/share/icons/hicolor/256x256/apps/todolist.png
  '';

  # One wrapper with the GTK settings, notify-send (plyer's way to notify) and
  # TODO_HOME: its files (settings.json, todo.db, the log, the login) in one
  # folder, not wherever it is started.
  dontWrapGApps = true;
  preFixup = lib.optionalString client ''
    makeWrapperArgs+=(
      "''${gappsWrapperArgs[@]}"
      --prefix PATH : ${lib.makeBinPath [ libnotify ]}
      --set-default TODO_HOME '~/.local/share/todolist'
    )
  '';

  desktopItems = lib.optionals client [
    (makeDesktopItem {
      name = "todolist";
      desktopName = "To-do list";
      comment = "Tasks with stages, due dates and reminders";
      exec = "todolist";
      icon = "todolist";
      categories = [ "Office" "ProjectManagement" ];
    })
  ];

  pythonImportsCheck = if client then [ "todo_db.app" ] else [ "todo_server.api" ];

  meta = {
    description =
      if client then "To-do list desktop program" else "To-do list application server";
    mainProgram = if client then "todolist" else "todolist-server";
    platforms = lib.platforms.linux;
  };
}
