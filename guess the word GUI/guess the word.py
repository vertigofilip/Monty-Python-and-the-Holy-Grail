#!/usr/bin/env python3

import os
import random
import tkinter as tk
from tkinter import ttk, messagebox

class AdvancedLetterGrid:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Advanced Letter Grid")
        
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
        self.word_length_entry = ttk.Entry(input_frame, textvariable=self.word_length, width=10)
        self.word_length_entry.pack(side="left", padx=5)

        # Second number with default value "10"
        ttk.Label(input_frame, text="Number of atempts").pack(side="left", padx=5)
        self.max_attempts = tk.StringVar(value="10")  # Default value here
        self.max_attempts_entry = ttk.Entry(input_frame, textvariable=self.max_attempts, width=10)
        self.max_attempts_entry.pack(side="left", padx=5)

        self.submit_btn = ttk.Button(input_frame, text="Start", command=self.on_button_click)
        self.submit_btn.pack(side="left", padx=10)

        self.result_label = ttk.Label(input_frame, text="Result: ")
        self.result_label.pack(side="left", padx=5)

    def on_button_click(self):
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
        
        


if __name__ == "__main__":
    app = AdvancedLetterGrid()


"""


with open(file_path, 'r') as file:
    for line in file:
        word = line.strip()
        if len(word) == word_length:
            words.append(word)

correct = random.randint(0, len(words))

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
