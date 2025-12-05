#!/usr/bin/env python3

import tkinter as tk
import os
import random

class SimplePaintApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calculator")
        # Get the directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Build full path to dictionary.txt
        file_path = os.path.join(script_dir, 'dictionary.txt')
        words = []
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        word_length = 5
        number_of_gueses = 10
        for row in range(number_of_gueses):
            for col in range(word_length + 2):
                # Get letter (or empty if not enough letters)
                index = row * word_length + col
                letter = ""
                # Create label (square with letter)
                if(col>=word_length):
                    label = tk.Label(
                        root,
                        text=letter,
                        font=("Arial", 24, "bold"),
                        width=2,
                        height=1,
                        relief="solid",      # Border style
                        borderwidth=2,
                        bg="white"
                    )
                    label.grid(row=row, column=col, padx=2, pady=2)
                else:
                    label = tk.Label(
                        root,
                        text=letter,
                        font=("Arial", 24, "bold"),
                        width=2,
                        height=1,
                        relief="solid",      # Border style
                        borderwidth=2,
                        bg="white"
                    )
                    label.grid(row=row, column=col, padx=2, pady=2)

# Run the app
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("300x400") # Set a default size
    
    # 4. FIX: actually instantiate the class!
    app = SimplePaintApp(root)
    
    root.mainloop()


"""


print("Welcome to guess the word game.")
print("explanation:")
print("Write a guess, and press enter. The game will give feedback.")
print("+ = correct letter at correct place")
print("~ = correct letter at incorrect place")
print("- = incorrect letter")

try:
    word_length = int(input("Select word length, the default is randon 2 to 5 \n"))
except ValueError:
    word_length = random.randint(2, 5)


try:
    number_of_gueses = int(input("Select number of gueses, the default is 10 \n"))
except ValueError:
    number_of_gueses = 10


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
menu += "    "
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
                temp = temp[:j] + '-' + temp[j+1:]
        for j in range(word_length):
            if(guess[j] in temp):
                menu = menu[:j] + '~' + menu[j+1:]
                temp = temp[:j] + '|' + temp[j+1:]
                while(guess[j] in temp):
                    temp = temp[:temp.find(guess[j])] + '|' + temp[temp.find(guess[j])+1:]
            else:
                if(guess[j] in letters):
                    letters = letters[:letters.find(guess[j])] + '|' + letters[letters.find(guess[j])+1:]
                if(menu[j] == '|'):
                    menu = menu[:j] + '-' + menu[j+1:]
        menu += "    "
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
