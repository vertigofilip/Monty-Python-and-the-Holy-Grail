#!/usr/bin/env python3

import os
import random
import copy

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Build full path to dictionary.txt
file_path = os.path.join(script_dir, 'dictionary.txt')

words = []
correct_word = ""
correct_letters = ""
incorect_letters = ""
os.system('cls' if os.name == 'nt' else 'clear')
print("Welcome to guess the word solver.")
print("explanation:")
print("select the size of words, and type in word selected for you into the game you are playing, than fill in followup questions.")

try:
    input("Select word length between 2 and 15, the default is randon 2 to 8")
    word_length = int(input(""))
except ValueError:
    word_length = random.randint(2, 8)

if(word_length < 2):
    word_length = 2
if(word_length > 15):
    word_length = 15


with open(file_path, 'r') as file:
    for line in file:
        word = line.strip()
        if len(word) == word_length:
            words.append(word)

words2 = copy.deepcopy(words)
i = 0
while i <= len(words)-1:
    for j in words[i]:
        if(words[i].count(j) > 1):
            words.pop(i)
            i=i-1
            break
    i=i+1


for i in range(word_length):
    correct_word += "|"

print("===============================================")
print("Colecting corect letters")

while len(correct_letters) < word_length and len(words) > 0:
    proposal = random.randint(0, len(words)-1)
    print("===============================================")
    print("Type this into the game you are playing:")
    print(words[proposal])
    print("===============================================")
    print("Type correct letters in correct places, use '|' as spaces ror unknown letters.")
    inp = input("").upper()
    i = 0
    while i <= len(correct_word)-1 and i <= len(inp)-1:
        if(correct_word[i] == "|"):
            correct_word = correct_word[:i] + inp[i] + correct_word[i+1:]
        i = i+1
    print("===============================================")
    print("Type correct letters in incorrect places.")
    inp = input("").upper()
    for a in inp:
        if(a not in correct_letters):
            correct_letters += a
    print("===============================================")
    print("Type incorrect letters.")
    inp = input("").upper()
    for a in inp:
        if(a not in incorect_letters and a not in correct_letters):
            incorect_letters += a
    
    for i in correct_word:
        j = 0
        while j < len(words):
            if(i in words[j]):
                words.pop(j)
                j = j-1
            j = j+1
    for i in correct_letters:
        j = 0
        while j < len(words):
            if(i in words[j]):
                words.pop(j)
                j = j-1
            j = j+1
    for i in incorect_letters:
        j = 0
        while j < len(words):
            if(i in words[j]):
                words.pop(j)
                j = j-1
            j = j+1

print("===============================================")
print("Finding correct word")

while True:
    if(len(words2) == 0):
        print("===============================================")
        print("There are no such words")
        break
    if(len(words2) == 1):
        print("===============================================")
        print("Your word is: " + words2[0])
        break
    
    for i in range(len(correct_word)):
        if(correct_word[i] != "|"):
            j = 0
            while j < len(words2):
                if(words2[j][i] != correct_word[i]):
                    words2.pop(j)
                    j = j-1
                j = j+1
    for i in correct_letters:
        j = 0
        while j < len(words2):
            if(i not in words2[j]):
                words2.pop(j)
                j = j-1
            j = j+1
    for i in incorect_letters:
        j = 0
        while j < len(words2):
            if(i in words2[j]):
                words2.pop(j)
                j = j-1
            j = j+1
    if(len(words2) == 0):
        print("===============================================")
        print("There are no such words")
        break
    if(len(words2) == 1):
        print("===============================================")
        print("Your word is: " + words2[0])
        break
    proposal = random.randint(0, len(words2)-1)
    print("===============================================")
    print(words2[proposal])
    print("===============================================")
    print("Type correct letters in correct spots, ot '|' in place of empty once.")
    inp = input("").upper()
    i = 0
    while i <= len(correct_word)-1 and i <= len(inp)-1:
        if(correct_word[i] == "|"):
            correct_word = correct_word[:i] + inp[i] + correct_word[i+1:]
        i = i+1
    print("===============================================")
    print("Type correct letters in incorrect places.")
    inp = input("").upper()
    for a in inp:
        if(a not in correct_letters):
            correct_letters += a
    print("===============================================")
    print("Type incorrect letters.")
    inp = input("").upper()
    for a in inp:
        if(a not in incorect_letters and a not in correct_letters):
            incorect_letters += a
    
