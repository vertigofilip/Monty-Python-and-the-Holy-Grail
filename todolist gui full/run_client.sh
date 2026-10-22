#!/usr/bin/env bash
# Start the to-do desktop program (Tkinter window).
#
#   ./run_client.sh
#   ./run_client.sh --db ~/Documents/tasks.db    work on another database file (this run)
#
# On first start it asks where your tasks are: on this computer (a database
# file, todo.db in this folder unless you choose another) or on an application
# server (address, email, password). The file chosen in the program (login
# window, or Account -> Database file...) is remembered; --db or TODO_DB=...
# overrides it for one run. Relative paths are taken from where you are.
set -euo pipefail
caller=$PWD
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

# A path as given by the user: ~ expanded, relative to the folder they ran this from.
absolute() {
    local path=$1
    [[ $path == "~" || $path == "~/"* ]] && path=$HOME${path:1}
    [[ $path == /* ]] && echo "$path" || echo "$caller/$path"
}

args=()
while (($#)); do
    case $1 in
        -h | --help)
            sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        --db)
            [[ $# -ge 2 ]] || { echo "--db needs a file name" >&2; exit 1; }
            args+=(--db "$(absolute "$2")")
            shift 2
            ;;
        --db=*)
            args+=(--db "$(absolute "${1#--db=}")")
            shift
            ;;
        *)
            echo "Unknown option: $1 (see --help)" >&2
            exit 1
            ;;
    esac
done
if [[ -n ${TODO_DB:-} ]]; then
    export TODO_DB=$(absolute "$TODO_DB")
fi

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

ensure_venv

if ! .venv/bin/python -c 'import tkinter' 2>/dev/null; then
    echo "Tkinter is missing. On Debian/Ubuntu: sudo apt install python3-tk" >&2
    exit 1
fi
if [[ -z ${DISPLAY:-} && -z ${WAYLAND_DISPLAY:-} ]]; then
    echo "No graphical display found; the program needs a desktop session." >&2
    exit 1
fi

exec .venv/bin/python -m todo_db.app "${args[@]+"${args[@]}"}"
