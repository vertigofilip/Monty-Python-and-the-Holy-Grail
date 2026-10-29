# Android build of the phone app (todo_mobile). Build with ../build_android.sh,
# which copies the sources into src/ first.

[app]
title = To-do
package.name = todolist
package.domain = org.todolist
source.dir = src
source.include_exts = py
# The program's logo (todo_db/logo.png, copied here by build_android.sh).
icon.filename = logo.png
version = 1.2
# sqlite3 and sqlalchemy: the mode without a server keeps the tasks in a database on the phone.
# filetype (for Kivy) and typing_extensions (for SQLAlchemy) are pure Python and copied into
# src/ by build_android.sh: installing them with pip here breaks the build venv that the
# sqlalchemy recipe shares.
requirements = python3,kivy==2.3.1,sqlite3,sqlalchemy
orientation = portrait
fullscreen = 0

# MANAGE_EXTERNAL_STORAGE ("All files access"): only asked for when the user keeps the
# database outside the app's own folders (Menu -> Database location...).
# FOREGROUND_SERVICE*, POST_NOTIFICATIONS: the reminders' background service and its notifications.
android.permissions = android.permission.INTERNET, android.permission.MANAGE_EXTERNAL_STORAGE, android.permission.FOREGROUND_SERVICE, android.permission.FOREGROUND_SERVICE_SPECIAL_USE, android.permission.POST_NOTIFICATIONS
# Reminders with the app closed (todo_mobile/reminder_service.py): a foreground service, so
# Android keeps it running; it shows a small "Reminders are on" notification.
services = Reminders:reminder_service.py:foreground:sticky:foregroundServiceType=specialUse
android.api = 35
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = False
# Our own version of the kivy recipe (see recipes/kivy/__init__.py).
p4a.local_recipes = ./recipes
# Lets the app talk to a server over plain http:// (e.g. in the home network).
# (Passed straight to python-for-android: buildozer's own
# android.extra_manifest_application_arguments breaks the quoting.)
p4a.extra_args = --extra-manifest-application-arguments='android:usesCleartextTraffic="true"'

[buildozer]
log_level = 2
warn_on_root = 1
