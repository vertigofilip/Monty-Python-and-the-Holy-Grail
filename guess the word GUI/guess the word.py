#!/usr/bin/env python3

import os
import random
import tkinter as tk
from tkinter import ttk, messagebox

class AdvancedLetterGrid:
    def __init__(self):
        self.root = tk.Tk()
        self.root.geometry("800x500")
        self.root.title("guess the word game")
        
        # Initialize variables
        self.attempt = 0
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.file_path = os.path.join(self.script_dir, 'dictionary.txt')  # Fixed: self.script_dir
        self.words = []
        self.guessed_letters = ""  # Fixed typo: guesed -> guessed
        self.letters = "abcdefghijklmnopqrstuvwxyz"
        
        # Create UI elements
        self.grid_control()
        
        # mainloop should be at the END
        self.root.mainloop()
    
    def grid_control(self):
        input_frame = ttk.Frame(self.root, padding="10")
        input_frame.pack(pady=10)

        # First number with default value between "2" and "8"
        ttk.Label(input_frame, text="Word length(2 - 15)").pack(side="left", padx=5)
        self.word_length = tk.StringVar(value=random.randint(2, 8))  # Default value here
        self.word_length_entry = ttk.Entry(input_frame, textvariable=self.word_length, width=10, state="normal")
        self.word_length_entry.pack(side="left", padx=5)

        # Second number with default value "10"
        ttk.Label(input_frame, text="Number of atempts").pack(side="left", padx=5)
        self.max_attempts = tk.StringVar(value="10")  # Default value here
        self.max_attempts_entry = ttk.Entry(input_frame, textvariable=self.max_attempts, width=10, state="normal")
        self.max_attempts_entry.pack(side="left", padx=5)

        self.submit_btn = ttk.Button(input_frame, text="Start", command=self.on_button_click, state="normal")
        self.submit_btn.pack(side="left", padx=10)

        self.result_label = ttk.Label(input_frame, text="Result: ")
        self.result_label.pack(side="left", padx=5)
    
    def validate_single_char(self, new_value):
        return len(new_value) <= 1

    def on_button_click(self):
        self.max_attempts_entry.config(state="readonly")
        self.word_length_entry.config(state="readonly")
        self.submit_btn.config(state="disabled")
        self.vcmd = (self.root.register(self.validate_single_char), '%P')
        try:
            self.word_length_number = int(self.word_length.get())
            self.max_attempts_number = int(self.max_attempts.get())
            
            # Validate inputs
            if self.word_length_number < 2:
                self.word_length_number = 2
            if self.word_length_number > 15:
                self.word_length_number = 15

            if self.max_attempts_number < 1:
                self.max_attempts_number = 1
            
        except ValueError:
            self.word_length_number = random.randint(2, 8)
            self.max_attempts_number = 10
        
        with open(self.file_path, 'r') as file:
            for line in file:
                word = line.strip()
                if len(word) == self.word_length_number:
                    self.words.append(word)
        
        self.correct = random.randint(0, len(self.words))

        self.grid_frame = tk.Frame(self.root, bg="lightgray", bd=2, relief="groove")
        self.grid_frame.pack(padx=10, pady=10)

        self.entries = []
        for i in range(self.max_attempts_number):
            self.row_entries = []
            for j in range(self.word_length_number + 1):
                if(i == 0):
                    if(j == self.word_length_number):
                        entry = tk.Label(self.grid_frame, text="abcdefghijklmnopqrstuvwxyz")
                    else:
                        entry = tk.Entry(self.grid_frame, width=3, justify="center", validate="key", validatecommand=self.vcmd, state="normal")
                else:
                    if(j == self.word_length_number):
                        entry = tk.Label(self.grid_frame, text="")
                    else:
                        entry = tk.Entry(self.grid_frame, width=3, justify="center", validate="key", validatecommand=self.vcmd, state="readonly")
                entry.grid(row=i, column=j, padx=2, pady=2)
                self.row_entries.append(entry)
            self.entries.append(self.row_entries)
        
        self.game_menu = tk.Frame(self.root, bg="lightgray", bd=2, relief="groove")
        self.grid_frame.pack(padx=10, pady=10)
        self.submit_btn = ttk.Button(self.root, text="Submit aswer", command=self.submit_aswer).pack(side="left", padx=5)
        self.win_indicator = ttk.Label(self.root, text=self.words[self.correct])
        self.win_indicator.pack(side="left", padx=5)
    

    def submit_aswer(self):
        resault = True
        correct_word = self.words[self.correct]
        answer = ""
        for i in range(self.word_length_number):
            answer += self.entries[self.attempt][i].get().upper()
        for i in range(self.word_length_number):
            if(self.entries[self.attempt][i].get().upper() != correct_word[i]):
                resault = False
            else:
                self.letters = self.letters[:self.letters.upper().find(self.entries[self.attempt][i].get())] + self.entries[self.attempt][i].get().upper() + self.letters[self.letters.upper().find(self.entries[self.attempt][i].get())+1:]
            correct_word = correct_word[:i] + '|' + correct_word[i+1:]
        if(resault):
            self.win_indicator.config(text="You won")
            self.submit_btn.config(state="disabled")
        self.attempt = self.attempt + 1
        if(self.attempt >= self.word_length_number):
            self.win_indicator.config(text="You lost")
        for i in range(self.word_length_number):
            self.entries[self.attempt][i].config(state="normal")
            self.entries[self.attempt-1][i].config(state="disabled")
        



if __name__ == "__main__":
    app = AdvancedLetterGrid()


"""


print("write a correct word and press enter \n")
menu = ""
win_condition = False
for i in range(word_length):
    menu += "-"
menu += " "
for j in range(word_length):
    menu += "|"
menu += " "
menu += letters
#print(words[correct])  # testing cheat uncoment to enable. coment to disable
print(menu)

for i in range(number_of_gueses):
    temp = words[correct]
    guess = input("").upper()
    if(len(guess) != word_length):
        print("wrong length")
    elif(guess == temp):
        win_condition = True
        break
    elif((guess in words) == False):
        print("this word does'nt exist")
    else:
        menu = ""
        for j in range(word_length):
            menu += "|"
        for j in range(word_length):
            if(guess[j] == temp[j]):
                menu = menu[:j] + '+' + menu[j+1:]
                temp = temp[:j] + '|' + temp[j+1:]
                guesed_letters = guesed_letters[:j] + guess[j] + guesed_letters[j+1:]
                if( guess in letters.upper()):
                    letters = letters[:letters.upper().find(guess[j])] + guess[j].upper() + letters[letters.upper().find(guess[j])+1:]
        print("")
        for j in range(word_length):
            if(guess[j] in temp ):
                menu = menu[:j] + '~' + menu[j+1:]
                #temp = temp[:j] + '|' + temp[j+1:]
                if( guess in letters.upper()):
                    letters = letters[:letters.upper().find(guess[j])] + guess[j].upper() + letters[letters.upper().find(guess[j])+1:]
                while(guess[j] in temp):
                    temp = temp[:temp.find(guess[j])] + '|' + temp[temp.find(guess[j])+1:]
            else:
                if(guess[j] in letters.upper()):
                    letters = letters[:letters.upper().find(guess[j])] + '|' + letters[letters.upper().find(guess[j])+1:]
                if(menu[j] == '|'):
                    menu = menu[:j] + '-' + menu[j+1:]
        menu += " "
        menu += guesed_letters
        menu += " "
        menu += letters
        print(menu)

if(win_condition):
    print("correct word")
    print("you won")
else:
    print("you lost")
    print("correct word:")
    print(words[correct])


"""
