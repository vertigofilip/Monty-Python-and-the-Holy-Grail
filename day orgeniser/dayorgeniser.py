#!/usr/bin/env python3

import os
import random
import tkinter as tk
from tkinter import ttk, messagebox
from enum import Enum
import datetime

class Status(Enum):
    TODO
    IM_PROGRESS
    DONE_FOR_NOW
    TESTING
    ASSESMENT
    DONE

class task:
    def __init__(self, new_name, new_description, new_repetition_number, new_do_verification, new_parent = None, new_due_date = None, new_repeat_time = 0):
        self.name = new_name
        #string
        self.description = new_description
        #string
        self.creation_date = datetime.datetime.now()
        #date
        self.repetition_number = new_repetition_number
        #unsigned int 16
        self.stage = Status.TODO
        #Status
        self.do_verification = new_do_verification
        #bool
        self.repeat_time = new_repeat_time
        #unsigned int 16
        self.parent = new_parent
        #task
        self.due_date = new_due_date
        #date
        self.subtasks = []
        #task
    def Progress():
        match (stage):
            case (Status.TODO):
                stage = Status.IM_PROGRESS
            case (Status.IM_PROGRESS):
                if (self.repetition_number > 0):
                    stage = Status.DONE_FOR_NOW
                elif (self.do_verification):
                    stage = Status.TESTING
                else:
                    stage = Status.DONE
            case (Status.DONE_FOR_NOW):
                stage = Status.IM_PROGRESS
            case (Status.TESTING):
                stage = Status.ASSESMENT
            case (Status.ASSESMENT):
                stage = Status.DONE
            case (Status.DONE):
                stage = Status.DONE
    def Regress():
        match (stage):
            case (Status.DONE):
                if (self.do_verification):
                    stage = Status.ASSESMENT
                else:
                    stage = Status.IM_PROGRESS
            case (Status.ASSESMENT):
                stage = Status.TESTING
            case (Status.TESTING):
                stage = Status.IM_PROGRESS
            case (Status.DONE_FOR_NOW):
                stage = Status.IM_PROGRESS
            case (Status.IM_PROGRESS):
                stage = Status.TODO
            case (Status.TODO):
                stage = Status.TODO
    def Eddit(self, new_name = None, new_description = None, new_repetition_number = None, new_do_verification = None, new_parent = None, new_due_date = None, new_repeat_time = None):
        if (new_name != None):
            self.name = new_name
        #string
        if (new_description != None):
            self.description = new_description
        #string
        self.creation_date = datetime.datetime.now()
        #date
        if (new_repetition_number != None):
            self.repetition_number = new_repetition_number
        #unsigned int 16
        if (new_do_verification != None):
            self.do_verification = new_do_verification
        #bool
        if (new_repeat_time != None):
            self.repeat_time = new_repeat_time
        #unsigned int 16
        if (new_parent != None):
            self.parent = new_parent
        #task
        if (new_due_date != None):
            self.due_date = new_due_date
        #date
    