import os
sizex = 40
sizey = 20
# Build a proper 2D grid, filled with a default character
playspace = [["." for _ in range(sizex)] for _ in range(sizey)]
swap = ""

for i in range(sizey):
    for j in range(sizex):
        if i == 0 or i == sizey - 1 or j == 0 or j == sizex - 1:
            if (i % 2 == 0 and j % 2 == 0) or (i % 2 != 0 and j % 2 != 0):
                playspace[i][j] = "#"
            else:
                playspace[i][j] = "□"


while True:
    os.system('cls' if os.name == 'nt' else 'clear')
    for row in playspace:
        print("".join(row))
    swap = playspace[0][0]
    playspace[1][0] = swap

        
            



# ◧◨◩◪▣▧