import itertools

out = ""
for i in itertools.count(0, 2):
    out += str(i)
    out += " "
    if i > 100:
        break
print(out)




out = ""
a = [1, 2, 3]
b = [4, 5, 6]
c = [7, 8, 9]
for i in itertools.chain(a, b, c):
    out += str(i)
    out += " "
print(out)




out = ""
lista = ['A', 'B', 'C']
for i in itertools.combinations(lista, 2):
    out += str(i)
    out += " "
print(out)
out = ""
for i in itertools.permutations(lista, 2):
    out += str(i)
    out += " "
print(out)




out = ""
koszule = ['czerwona', 'niebieska']
spodnie = ['jeansy', 'chinosy']
for i in itertools.product(koszule, spodnie):
    out += str(i)
    out += " "
print(out)




out = []
liczby = [1, 1, 2, 2, 2, 3, 1, 1]
for i, j in itertools.groupby(liczby):
    out.append(list(j))
print(out)




out = ""
for i in itertools.product('ab', repeat=3):
    out += ''.join(i) + " "
print(out)