#!/usr/bin/env python3

import os
import random
import tkinter as tk
from tkinter import ttk, messagebox

class task:
    def __init__(self, name_new, description_new):
        self.name = name_new
        self.description = description_new

class task_tracker:
    def __init__(self):
        self.root = tk.Tk()
        self.root.geometry("800x500")
        self.root.title("task tracker")
        self.tasks = []

        # (add your widgets here)

if __name__ == "__main__":
    app = task_tracker()
    app.root.mainloop()               # <-- start the event loop