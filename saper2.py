import torch
import random
#generating map
def genmap(minescount):
  disp = [['X','1','2','3','4','5','6','7','8','9','10','X'],
          ['1','#','#','#','#','#','#','#','#','#','#','1'],
          ['2','#','#','#','#','#','#','#','#','#','#','2'],
          ['3','#','#','#','#','#','#','#','#','#','#','3'],
          ['4','#','#','#','#','#','#','#','#','#','#','4'],
          ['5','#','#','#','#','#','#','#','#','#','#','5'],
          ['6','#','#','#','#','#','#','#','#','#','#','6'],
          ['7','#','#','#','#','#','#','#','#','#','#','7'],
          ['8','#','#','#','#','#','#','#','#','#','#','8'],
          ['9','#','#','#','#','#','#','#','#','#','#','9'],
          ['10','#','#','#','#','#','#','#','#','#','#','10'],
          ['X','1','2','3','4','5','6','7','8','9','10','X']]
  mines = [['@','@','@','@','@','@','@','@','@','@','@','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','#','#','#','#','#','#','#','#','#','#','@'],
          ['@','@','@','@','@','@','@','@','@','@','@','@']]
  for i in range(minescount):
    a=random.randrange(1,10)
    b=random.randrange(1,10)
    if mines[a][b] == '#':
      mines[a][b] = 'X'
    else:
      i = i - 1
  return disp, mines
#flag
def flag(x, y, minescount):
  if disp[x][y]=='#':
    disp[x][y]='F'
    minescount=minescount-1
  elif disp[x][y]=='F':
    disp[x][y]='#'
    minescount=minescount+1
  else:
    print('this place is allready uncovered')
  return minescount
def uncover(x, y, recurencynum, freespaces):
  m=0
  status=False
  if disp[x][y]=='F':
    print('this place is allready flaged')
  elif mines[x][y]=='X':
    print('you loose')
    status=True
  elif disp[x][y]=='#':
    freespaces=freespaces-1
    for a,b in ((-1,-1),(-1,0),(-1,+1),(0,-1),(0,+1),(+1,-1),(+1,0),(+1,+1)):
      if mines[x+a][y+b]=='X':m=m+1
    disp[x][y]=str(m)
    if m==0 and recurencynum<10:
      for a,b in ((-1,-1),(-1,0),(-1,+1),(0,-1),(0,+1),(+1,-1),(+1,0),(+1,+1)):
        if disp[x+a][y+b]=='#': status, freespaces = uncover(x+a, y+b, recurencynum+1, freespaces)
    if freespaces==0:
      print('you win')
      status=True
  elif 1<x<12 and 1<y<12:
    print('this place is allready uncovered')
  return status, freespaces
#game
while True:
  minescount = int(input('Select number of mines(5-10)'))
  if 1<=minescount<=10:
      break
disp, mines = genmap(minescount)
freespaces=100-minescount;
while True:
  print(f'{minescount} mineas remains, {freespaces} free spaces remains')
  for i in range(12):
    print(disp[i])
  action=input('Select acttion f - togle flag, u - uncovered, x - exit: ')
  if action.lower()=='x':
    break
  x=int(input('select x(vertical): '))
  y=int(input('select y(horisontal): '))
  if action.lower()=='f':
    minescount=flag(x, y, minescount)
  elif action.lower()=='u':
    status, freespaces = uncover(x, y, 0, freespaces)
    if status:
      break
  else:
    print("this option doesn't exist") 