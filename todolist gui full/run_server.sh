#!/usr/bin/env bash
# Start the to-do application server (todo_server), or manage its accounts.
#
#   ./run_server.sh                                   start it, reachable from the local network
#   ./run_server.sh run --port 9000                   start it with extra options
#   ./run_server.sh create-admin --name "Anna Kowalska" --email anna@example.com
#   ./run_server.sh set-password --email anna@example.com
#   ./run_server.sh --db /srv/todo/tasks.db           use another database file (any command)
#
# Settings (environment variables):
#   TODO_SERVER_DB     database file             (default: todo_server.db in this folder;
#                                                 --db overrides it; relative paths are
#                                                 taken from where you run this)
#   TODO_SERVER_HOST   address to listen on      (default: 0.0.0.0 = all networks;
#                                                 127.0.0.1 = this computer only)
#   TODO_SERVER_PORT   port                      (default: 8000)
#   TODO_TOKEN_DAYS    how long a login lasts    (default: 30)
set -euo pipefail
caller=$PWD
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

# A path as given by the user: ~ expanded, relative to the folder they ran this from.
absolute() {
    local path=$1
    [[ $path == "~" || $path == "~/"* ]] && path=$HOME${path:1}
    [[ $path == /* ]] && echo "$path" || echo "$caller/$path"
}

usage() {
    sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# Create .venv and install requirements.txt when missing or changed.
ensure_venv() {
    if [[ ! -x .venv/bin/python ]]; then
        if ! command -v python3 >/dev/null; then
            echo "python3 not found; install Python 3.11 or newer." >&2
            exit 1
        fi
        if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
            echo "Python 3.11 or newer is needed, found $(python3 --version)." >&2
            exit 1
        fi
        echo "Creating .venv ..."
        python3 -m venv .venv
    fi
    local marker=.venv/.requirements-installed
    if [[ ! -f $marker || requirements.txt -nt $marker ]]; then
        echo "Installing requirements ..."
        .venv/bin/pip install --quiet -r requirements.txt
        touch "$marker"
    fi
}

db=todo_server.db
[[ -n ${TODO_SERVER_DB:-} ]] && db=$(absolute "$TODO_SERVER_DB")
# --db FILE may come anywhere; the rest goes on to the server.
args=()
while (($#)); do
    case $1 in
        --db)
            [[ $# -ge 2 ]] || { echo "--db needs a file name" >&2; exit 1; }
            db=$(absolute "$2")
            shift 2
            ;;
        --db=*)
            db=$(absolute "${1#--db=}")
            shift
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done
set -- "${args[@]+"${args[@]}"}"
if [[ -d $db ]]; then
    echo "--db must name a file, not a folder: $db" >&2
    exit 1
fi
command=${1:-run}

case $command in
    -h | --help)
        usage
        exit 0
        ;;
    create-admin | set-password)
        ensure_venv
        exec .venv/bin/python -m todo_server --db "$db" "$@"
        ;;
    run)
        [[ $# -gt 0 ]] && shift
        ;;
    *)
        echo "Unknown command: $command" >&2
        usage >&2
        exit 1
        ;;
esac

ensure_venv

# Nobody can log in without an administrator; say so instead of failing silently.
admins=$(.venv/bin/python - "$db" <<'PY'
import sqlite3, sys
try:
    connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    query = "SELECT COUNT(*) FROM User WHERE Role = 'Admin' AND IsActive AND PasswordHash IS NOT NULL"
    print(connection.execute(query).fetchone()[0])
except sqlite3.Error:
    print(0)
PY
)
if [[ $admins == 0 ]]; then
    echo "Note: $db has no administrator yet, so nobody can log in. Create one with:"
    db_option=""
    [[ $db != todo_server.db ]] && db_option=" --db \"$db\""
    echo "  ./run_server.sh$db_option create-admin --name \"Your Name\" --email you@example.com"
    echo
fi

host=${TODO_SERVER_HOST:-0.0.0.0}
port=${TODO_SERVER_PORT:-8000}
if [[ $host == 0.0.0.0 ]]; then
    # Uvicorn would print http://0.0.0.0:..., which is not an address to type in.
    echo "Starting the server. Connect to it (from a phone or another computer on the"
    echo "same network) at:"
    # IPv4 addresses of the real network cards (not Docker's or VMs' bridges).
    ip -4 -o addr show scope global 2>/dev/null | while read -r _ device _ address _; do
        case $device in docker* | br-* | virbr* | veth*) continue ;; esac
        echo "  http://${address%/*}:$port"
    done || true
    echo "  http://127.0.0.1:$port   (this computer)"
    echo "If other devices cannot connect, allow the port in the firewall:"
    echo "  sudo ufw allow $port/tcp"
else
    echo "Starting the server at http://$host:$port"
fi
echo "Database: $db"
echo "API documentation at /docs on that address. Stop with Ctrl+C."
exec .venv/bin/python -m todo_server --db "$db" run \
    --host "$host" --port "$port" --token-days "${TODO_TOKEN_DAYS:-30}" "$@"
