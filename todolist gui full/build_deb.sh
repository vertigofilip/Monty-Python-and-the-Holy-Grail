#!/usr/bin/env bash
# Build a Debian/Ubuntu/Mint package (.deb) of the desktop program and the server.
#
#   ./build_deb.sh                build dist/todolist_<version>_<arch>.deb
#   sudo apt install ./dist/todolist_*.deb     install it (or upgrade an older one)
#
# It packs the standalone programs of build_desktop.py (built first, so they are
# up to date): "todolist" (in the menu as "To-do list") and "todolist-server".
# The installed desktop program keeps its files (settings.json, todo.db, the log,
# the login) in ~/.local/share/todolist (TODO_HOME), not where it is started.
# The server, as before, works in the folder it is started from (or --db).
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi
for tool in dpkg-deb fakeroot python3; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool (sudo apt install dpkg-dev fakeroot)" >&2; exit 1; }
done

# build_desktop.py starts dist/linux afresh: keep files a run from there left.
kept=$(mktemp -d)
trap 'rm -rf "$kept"' EXIT
for file in settings.json client_login.json reminder_tasks.json todo.db todo_server.db; do
    if [[ -f dist/linux/$file ]]; then cp -p "dist/linux/$file" "$kept/"; fi
done
python3 build_desktop.py
cp -rp "$kept"/. dist/linux/

# The project's version, and the build time so that each build upgrades the last.
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)+$(date +%Y%m%d%H%M)
arch=$(dpkg --print-architecture)
package=build/deb/todolist
rm -rf build/deb
mkdir -p "$package/DEBIAN" "$package/opt/todolist" "$package/usr/bin" \
    "$package/usr/share/applications" "$package/usr/share/icons/hicolor/256x256/apps"

install -m755 dist/linux/todolist dist/linux/todolist-server "$package/opt/todolist/"
install -m644 todo_db/logo.png "$package/usr/share/icons/hicolor/256x256/apps/todolist.png"
cat > "$package/usr/bin/todolist" <<'EOF'
#!/bin/sh
# The desktop program, with its files in one folder of the user's.
: "${TODO_HOME:=$HOME/.local/share/todolist}"
export TODO_HOME
exec /opt/todolist/todolist "$@"
EOF
cat > "$package/usr/bin/todolist-server" <<'EOF'
#!/bin/sh
exec /opt/todolist/todolist-server "$@"
EOF
chmod 755 "$package/usr/bin/todolist" "$package/usr/bin/todolist-server"
cat > "$package/usr/share/applications/todolist.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=To-do list
Name[pl]=Lista zadań
Comment=Tasks with stages, due dates and reminders
Comment[pl]=Zadania z etapami, terminami i przypomnieniami
Exec=todolist
Icon=todolist
Terminal=false
Categories=Office;ProjectManagement;
EOF

# The tray icon's menu uses the system's PyGObject and AppIndicator; plyer's
# notifications use notify-send. Without them the program still runs.
cat > "$package/DEBIAN/control" <<EOF
Package: todolist
Version: $version
Architecture: $arch
Maintainer: $(git config user.name 2>/dev/null || echo todolist) <$(git config user.email 2>/dev/null || echo root@localhost)>
Installed-Size: $(du -sk "$package" | cut -f1)
Depends: libc6
Recommends: python3-gi, gir1.2-ayatanaappindicator3-0.1, libnotify-bin
Section: utils
Priority: optional
Description: To-do list: desktop program and application server
 Tasks with workflows, stages, due dates, repeating and reminders, kept in a
 local database file or on the application server (todolist-server).
EOF

chmod -R go-w "$package"  # whatever the umask: only root may change the installed files
output=dist/todolist_${version}_${arch}.deb
fakeroot dpkg-deb --build --root-owner-group "$package" "$output" >/dev/null
echo "Ready: $output ($(du -h "$output" | cut -f1))"
echo "Install: sudo apt install ./$output"
