#!/usr/bin/env python3

import os
import random

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Build full path to dictionary.txt
file_path = os.path.join(script_dir, 'slownik.txt')

words = []
guesed_letters = ""
letters = "abcdefghijklmnopqrstuvwxyz"
os.system('cls' if os.name == 'nt' else 'clear')
print("Witamy w grze zgadnij słowo.")
print("wytłumaczenie:")
print("napisz słowo i naciśnij enter, gra. Gra da informację zwrotną.")
print("+ = poprawna litera na poprawnym miejscu")
print("~ = poprawna litera na niepoprawnym miejscu")
print("- = niepoprawna litera")

try:
    print("wybierzdługość słowa, wartość pomiędzy 2, a 15, domyślnia wartość, to losowa wartość od 2 do 8")
    word_length = int(input(""))
except ValueError:
    word_length = random.randint(2, 8)

if(word_length < 2):
    word_length = 2
if(word_length > 15):
    word_length = 15

for i in range(word_length):
    guesed_letters += "|"

try:
    print("Wybierz ilość prób (dowolną liczbę), domyślnia wartość to 10")
    number_of_gueses = int(input(""))
except ValueError:
    number_of_gueses = 10

if(number_of_gueses < 1):
    number_of_gueses = 1


with open(file_path, 'r') as file:
    for line in file:
        word = line.strip()
        if len(word) == word_length:
            words.append(word)

correct = random.randint(0, len(words))

print("napisz poprawne słowo i naciśnij enter \n")
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
print("twoje słowo/wskaźnik poprawnych liter ; poprawne litery ; dostępne litery")
print(menu)

for i in range(number_of_gueses):
    temp = words[correct]
    guess = input("").upper()
    if(len(guess) != word_length):
        print("zła długość")
        print("próba nr: " + str(i+1) + " z " + str(number_of_gueses))
        print("===============================================")
    elif(guess == temp):
        win_condition = True
        break
    elif((guess in words) == False):
        print("to słowo nie istnieje")
        print("próba nr: " + str(i+1) + " z " + str(number_of_gueses))
        print("===============================================")
    else:
        menu = ""
        for j in range(word_length):
            menu += "|"
        for j in range(word_length):
            if(guess[j] == temp[j]):
                menu = menu[:j] + '+' + menu[j+1:]
                temp = temp[:j] + '|' + temp[j+1:]
                guesed_letters = guesed_letters[:j] + guess[j] + guesed_letters[j+1:]
                if( guess[j] in letters.upper()):
                    letters = letters[:letters.upper().find(guess[j])] + guess[j].upper() + letters[letters.upper().find(guess[j])+1:]
        #print("")
        for j in range(word_length):
            if(guess[j] in temp ):
                menu = menu[:j] + '~' + menu[j+1:]
                #temp = temp[:j] + '|' + temp[j+1:]
                if( guess[j] in letters.upper()):
                    letters = letters[:letters.upper().find(guess[j])] + guess[j].upper() + letters[letters.upper().find(guess[j])+1:]
                while(guess[j] in temp):
                    temp = temp[:temp.find(guess[j])] + '|' + temp[temp.find(guess[j])+1:]
            else:
                if(guess[j] in letters.upper()):
                    if(letters[letters.upper().find(guess[j])] == letters[letters.upper().find(guess[j])].lower()):
                        letters = letters[:letters.upper().find(guess[j])] + '|' + letters[letters.upper().find(guess[j])+1:]
                if(menu[j] == '|'):
                    menu = menu[:j] + '-' + menu[j+1:]
        menu += " "
        menu += guesed_letters
        menu += " "
        menu += letters
        menu += " próba nr: "
        print(menu + str(i+1) + " z " + str(number_of_gueses))
        print("===============================================")

if(win_condition):
    print("poprawne słowo")
    print("wygrałeś")
else:
    print("przegrałeś")
    print("poprawne słowo:")
    print(words[correct])

