#!/usr/bin/env bash
# Build the phone app as an Android package (.apk).
#
#   ./build_android.sh            build android/bin/todolist-1.0-*-debug.apk
#   ./build_android.sh deploy     build and install on a phone connected by USB
#   ./build_android.sh clean      remove the build (the next one starts over)
#
# Needs: Java 17 (JAVA_HOME), git, zip, unzip, autoconf, automake, libtool,
# pkg-config, cmake, a C compiler. The first build downloads the Android SDK and
# NDK (several GB, into ~/.buildozer) and takes a long time; later builds are quick.
# The build itself runs in $TODO_ANDROID_BUILD (default ~/Android/todolist-build),
# because the Android tools break on folder names with spaces.
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi

BUILDOZER_VENV=${BUILDOZER_VENV:-$HOME/.buildozer-venv}
if [[ ! -x $BUILDOZER_VENV/bin/buildozer ]]; then
    echo "Installing buildozer into $BUILDOZER_VENV ..."
    python3 -m venv --system-site-packages "$BUILDOZER_VENV"  # buildozer pip-installs with --user
    "$BUILDOZER_VENV/bin/pip" install --quiet buildozer "cython<3.1" setuptools
fi
export PATH="$BUILDOZER_VENV/bin:$HOME/.local/bin:$PATH"
# buildozer installs its helpers with "pip --user": keep them inside its venv.
export PYTHONUSERBASE="$BUILDOZER_VENV/user"

if [[ -z ${JAVA_HOME:-} ]]; then
    for candidate in "$HOME"/java/17* /usr/lib/jvm/java-17-openjdk*; do
        [[ -x $candidate/bin/java ]] && { export JAVA_HOME=$candidate; break; }
    done
fi
if [[ -z ${JAVA_HOME:-} ]]; then
    echo "Java 17 not found; install it and set JAVA_HOME." >&2
    exit 1
fi
export PATH="$JAVA_HOME/bin:$PATH"

for tool in git zip unzip autoconf automake libtoolize pkg-config cmake cc; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done

BUILD=${TODO_ANDROID_BUILD:-$HOME/Android/todolist-build}
if [[ $BUILD == *" "* || $BUILD == */.* ]]; then
    # Spaces break the Android tools; buildozer skips sources under hidden folders.
    echo "TODO_ANDROID_BUILD must have no spaces and no hidden (.name) folders: $BUILD" >&2
    exit 1
fi

# A libtool installed in ~/.local (no root needed) keeps its autoconf macros there.
# python-for-android passes only PATH to the builds, not ACLOCAL_PATH, so an
# aclocal wrapper early in PATH adds the folder itself.
if [[ -f $HOME/.local/share/aclocal/libtool.m4 && ! -f /usr/share/aclocal/libtool.m4 ]]; then
    mkdir -p "$BUILD/tools"
    cat > "$BUILD/tools/aclocal" <<WRAPPER
#!/bin/sh
ACLOCAL_PATH="$HOME/.local/share/aclocal\${ACLOCAL_PATH:+:\$ACLOCAL_PATH}" exec /usr/bin/aclocal "\$@"
WRAPPER
    chmod +x "$BUILD/tools/aclocal"
    export PATH="$BUILD/tools:$PATH"
fi

# python-for-android first builds a Python for this computer ("hostpython") and
# uses its pip to fetch packages, which needs the ssl module, i.e. OpenSSL
# headers (libssl-dev). Without them, build a private static OpenSSL once.
if ! pkg-config --exists openssl 2>/dev/null; then
    OPENSSL_VERSION=3.3.1
    HOST_SSL=$BUILD/host-openssl
    if [[ ! -f $HOST_SSL/lib64/pkgconfig/openssl.pc && ! -f $HOST_SSL/lib/pkgconfig/openssl.pc ]]; then
        echo "Building OpenSSL $OPENSSL_VERSION for this computer (no libssl-dev) ..."
        mkdir -p "$BUILD/host-openssl-src"
        curl -fsSL --retry 5 -o "$BUILD/host-openssl-src/openssl.tar.gz" \
            "https://www.openssl.org/source/openssl-$OPENSSL_VERSION.tar.gz"
        tar xzf "$BUILD/host-openssl-src/openssl.tar.gz" -C "$BUILD/host-openssl-src"
        (cd "$BUILD/host-openssl-src/openssl-$OPENSSL_VERSION" &&
            ./Configure --prefix="$HOST_SSL" --openssldir="$HOST_SSL/ssl" no-shared no-tests -fPIC \
                >/dev/null &&
            make -j"$(nproc)" >/dev/null && make install_sw >/dev/null)
    fi
    export PKG_CONFIG_PATH="$HOST_SSL/lib64/pkgconfig:$HOST_SSL/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi

# The app's sources: the phone app plus the translations it shares with the desktop.
mkdir -p "$BUILD"
rm -rf "$BUILD/src"
mkdir -p "$BUILD/src/todo_mobile" "$BUILD/src/todo_db"
cp android/buildozer.spec "$BUILD/"
rm -rf "$BUILD/recipes"
cp -r android/recipes "$BUILD/"
cp android/{main,reminder_service}.py "$BUILD/src/"
cp todo_mobile/{__init__,api,tasks,local,storage,reminder_service,main}.py "$BUILD/src/todo_mobile/"
cp todo_db/{__init__,i18n,settings,models,database,services,seed,compression,api_data,reminder_core,presets,management}.py "$BUILD/src/todo_db/"
cp todo_db/logo.png "$BUILD/"  # the app's icon (icon.filename in buildozer.spec)
# Pure-Python libraries the app needs, from this project's .venv (see buildozer.spec).
if ! .venv/bin/python -c "import filetype, typing_extensions" 2>/dev/null; then
    echo "Run ./run_client.sh once first: the build takes filetype and typing_extensions from .venv." >&2
    exit 1
fi
.venv/bin/python - "$BUILD/src" <<'PY'
import shutil, sys
from pathlib import Path

import filetype, typing_extensions

target = Path(sys.argv[1])
shutil.copy(typing_extensions.__file__, target)
shutil.copytree(Path(filetype.__file__).parent, target / "filetype",
                ignore=shutil.ignore_patterns("__pycache__"))
PY

# python-for-android re-creates its helper venv on top of the old one, which
# mixes two pip versions and breaks pip; start each build with a fresh one.
rm -rf "$BUILD"/.buildozer/android/platform/build-*/build/venv

# The build's own Python writes the folder it was built in into its scripts
# (pip3, cython, ...); after the build folder moved, point them at this one.
for bin in "$BUILD"/.buildozer/android/platform/build-*/build/other_builds/hostpython3/desktop/hostpython3/native-build/root/usr/local/bin; do
    [[ -d $bin ]] || continue
    grep -lI -- "/.buildozer/android/platform/" "$bin"/* 2>/dev/null | while read -r script; do
        sed -i "s|[^ '\"]*/\.buildozer/android/platform/|$BUILD/.buildozer/android/platform/|g" "$script"
    done
done

case ${1:-debug} in
    debug) (cd "$BUILD" && buildozer android debug) ;;
    deploy) (cd "$BUILD" && buildozer android debug deploy run) ;;
    clean) (cd "$BUILD" && buildozer android clean); exit 0 ;;
    *) echo "Unknown command: $1 (debug, deploy or clean)" >&2; exit 1 ;;
esac
mkdir -p android/bin
cp "$BUILD"/bin/*.apk android/bin/
echo "Ready:"
ls -1 android/bin/*.apk
