#!/usr/bin/env python3

import os
import random
import tkinter as tk
from tkinter import ttk, messagebox
from enum import Enum
import datetime

class Repeat_interval(Enum):
    ANY_TIME = "ANY_TIME"
    EVERY_DAY = "EVERY_DAY"
    EVERY_OTHER_DAY = "EVERY_OTHER_DAY"
    EVERY_THIRD_DAY = "EVERY_THIRD_DAY"
    EVERY_WEEK = "EVERY_WEEK"
    EVERY_MONTH = "EVERY_MONTH"
    EVERY_YEAR = "EVERY_YEAR"


class Status(Enum):
    TODO_NORMAL = "□ todo"
    IN_PROGRESs_NORMAL = "▣ in progerss"
    DONE_NORMAL = "■ done"
    TODO_EXPAND = "□ todo"
    IN_PROGRESS_EXPAND = "◩ in progerss"
    TESTING = "◩ testing"
    REVIEW = "▩ review"
    DONE_EXPAND = "■ done"
    TODO_REPETED = "□ todo"
    DONE_REPETED = "■ done for now"
    CANSELED = "X canseled"
    STRUSTURAL = "┌ "

class task:
    def __init__(self, root_new, name_new, description_new, status_new, repeat_new, repetition_number_new = 0, due_date_new = None):
        self.root = root_new
        self.name = name_new
        self.description = description_new
        self.status = status_new
        self.creation_date = datetime.datetime.now()
        self.repeat = repeat_new
        self.repetition_number = repetition_number_new      #65,535 = no limit
        self.due_date = due_date_new
        self.subtasks = []
        self.parent
    def display(self):
        task_frame = ttk.Frame(self.root, padding="10", relief="groove", borderwidth=2)
        task_frame.pack(pady=5, padx=10, fill="x")

        status_label = ttk.Label(task_frame, text=f"{self.status.value}", font=("Arial", 8))
        status_label.pack(anchor="w")
        
        name_label = ttk.Label(task_frame, text=self.name, font=("Arial", 12, "bold"))
        name_label.pack(anchor="w")

        desc_label = ttk.Label(task_frame, text=f"Desc: {self.description}")
        desc_label.pack(anchor="w")

        creation_date_label = ttk.Label(task_frame, text=f"Created at: {self.creation_date}")
        creation_date_label.pack(anchor="w")

        if(self.due_date == None):
            due_date_label = ttk.Label(task_frame, text=f"No duedate")
        else:
            due_date_label = ttk.Label(task_frame, text=f"Due date: {self.due_date}")
        due_date_label.pack(anchor="w")

        if(self.status == Status.TODO_REPETED or self.status == Status.DONE_REPETED):
            repeat_label = ttk.Label(task_frame, text=f"Repeat {self.due_date}")
            repeat_label.pack(anchor="w")
        
        if(self.status != Status.STRUSTURAL):
            eddit_button = ttk.Button(task_frame, text="Eddit task")
            eddit_button.pack(anchor="e")
            progress_button = ttk.Button(task_frame, text="Progress task")
            progress_button.pack(anchor="e")
    def display_recursive(self, root, level):
        task_frame = ttk.Frame(root, padding="10", relief="groove", borderwidth=2)
        task_frame.pack(pady=5, padx=10, fill="x")

        status_label = ttk.Label(task_frame, text=f"{self.status.value}")
        status_label.pack(side="left")

        name_label = ttk.Label(task_frame, text=self.name, font=("Arial", 12, "bold"))
        name_label.pack(side="left")

        creation_date_label = ttk.Label(task_frame, text=f"Created at: {self.creation_date}")
        creation_date_label.pack(side="left")

        if(self.due_date == None):
            due_date_label = ttk.Label(task_frame, text=f"No duedate")
        else:
            due_date_label = ttk.Label(task_frame, text=f"Due date: {self.due_date}")
        due_date_label.pack(side="left")

        if(self.status == Status.TODO_REPETED or self.status == Status.DONE_REPETED):
            repeat_label = ttk.Label(task_frame, text=f"Repeat {self.due_date}")
            repeat_label.pack(side="left")
        if(self.status != Status.STRUSTURAL):
            eddit_button = ttk.Button(task_frame, text="Eddit task")
            eddit_button.pack(side="right")
            progress_button = ttk.Button(task_frame, text="Progress task")
            progress_button.pack(side="right")
        
        for i in self.subtasks:
            i.display_recursive(task_frame, level+1)
    
    def create_popup_window(self, parent, title, message):
        # Create the window
        window = tk.Toplevel(parent)
        window.title(title)
        window.geometry("250x150")

        # Add content
        ttk.Label(window, text=message, padding=20).pack()
        ttk.Button(window, text="OK", command=window.destroy).pack()

        # Return it in case the caller needs to modify it later
        return window


class task_tracker:
    def __init__(self):
        self.root = tk.Tk()
        self.root.geometry("800x500")
        self.root.title("task tracker")
        self.tasks = task(self.root, "ToDo List", "This is a list todo", Status.STRUSTURAL, Repeat_interval.EVERY_DAY)
        self.tasks.display_recursive(self.root, 0)
        self.tasks.create_popup_window(self.root, "Error", "Something went wrong!")

if __name__ == "__main__":
    app = task_tracker()
    app.root.mainloop()