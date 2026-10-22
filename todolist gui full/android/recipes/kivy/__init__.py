"""Kivy without its optional pure-Python extras (requests, chardet, ...).

The phone app talks to the server with urllib, so it does not need requests.
Leaving it out also avoids a python-for-android problem: for requests'
dependency charset_normalizer it picks an Android wheel and then tries to
install it with the computer's pip, which refuses it.
"""

from pythonforandroid.recipes.kivy import KivyRecipe


class TodoKivyRecipe(KivyRecipe):
    python_depends = ["filetype"]


recipe = TodoKivyRecipe()
