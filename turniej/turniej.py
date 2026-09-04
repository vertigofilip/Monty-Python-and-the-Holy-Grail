#lista graczy
#combinations -> generowanie par
#permutation -> kolejność graczy
#product -> przypisanie map
#chain ->połączenie z nagrodą
# -> numerowanie meczy

from itertools import combinations, permutations, product

gracze = ["Adam Małysz", "Magda Gesler", "Michał Tatarczyk"]

mapy = ["nukatown", "gorge", "2fort"]

pary = []

if "T" in input("Czy kolejność ma znaczenie? (T / N)").upper():
    for i in permutations(gracze, 2):
        para = i[0] + " -> " + i[1]
        print(para)
        pary.append(para)
else:
    for i in combinations(gracze, 2):
        para = i[0] + " - " + i[1]
        print(para)
        pary.append(para)

print(" ")

for i in product(mapy, pary):
    print(i[1] + " ->  " + i[0])