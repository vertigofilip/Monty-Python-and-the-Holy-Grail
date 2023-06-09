import torch
import random
#generating map function
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
          ['X','1','2','3','4','5','6','7','8','9','10','X']] #display memory, contains coverd, uncoverd tiles, and flags
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
          ['@','@','@','@','@','@','@','@','@','@','@','@']] #game memory, contauns posirion of bombs
  for i in range(minescount): #placing bombs
    a=random.randrange(1,10)
    b=random.randrange(1,10)
    if mines[a][b] == '#':
      mines[a][b] = 'X'
    else:
      i = i - 1
  return disp, mines
#flag function
def flag(x, y, minescount):
  if disp[x][y]=='#': #placing flag
    disp[x][y]='F'
    minescount=minescount-1
  elif disp[x][y]=='F': #removing flag
    disp[x][y]='#'
    minescount=minescount+1
  else:
    print('this place is allready uncovered') #failcheack and information
  return minescount
#recurent function uncovering tiles, that handles winning, and loosing
def uncover(x, y, recurencynum, freespaces):
  m=0 #counts mines nearby
  status=False
  if disp[x][y]=='F': #cheack if field is flaged, safety feacher
    print('this place is allready flaged')
  elif mines[x][y]=='X': #fail condition
    print('you loose')
    status=True
  elif disp[x][y]=='#': #uncover algiritm
    freespaces=freespaces-1
    for a,b in ((-1,-1),(-1,0),(-1,+1),(0,-1),(0,+1),(+1,-1),(+1,0),(+1,+1)): #counting mines around
      if mines[x+a][y+b]=='X':m=m+1
    disp[x][y]=str(m)
    if m==0 and recurencynum<10:
      for a,b in ((-1,-1),(-1,0),(-1,+1),(0,-1),(0,+1),(+1,-1),(+1,0),(+1,+1)): #recurency
        if disp[x+a][y+b]=='#': status, freespaces = uncover(x+a, y+b, recurencynum+1, freespaces)
    if freespaces==0: #win condition
      print('you win')
      status=True
  elif 1<x<12 and 1<y<12: #failcheack and information
    print('this place is allready uncovered')
  return status, freespaces
#game
while True: #mine count select
  minescount = input('Select number of mines(5-10)')
  if minescount.isdigit():
    minescount=int(minescount)
    if 1<=minescount<=10:
      break
  print('you need to tipe a number (5-10)')
disp, mines = genmap(minescount) #map generation
freespaces=100-minescount
roundcounter=0
while True: #game loop
  print(f'{minescount} mineas remains, {freespaces} free spaces remains your round number: {roundcounter}') #printing info7
  roundcounter=roundcounter+1
  for i in range(12): #map printing
    print(disp[i])
  action=input('Select acttion f - togle flag, u - uncovered, x - exit: ') #printing menu, and taking input from player
  if action.lower()=='x': #exit
    break
  while True:
    x=input('select x(vertical): ')
    if x.isdigit():
      x=int(x)
      if 1<=x<=10:
        break
    print('you need to tipe a number (1-10)')
  while True:
    y=input('select y(horisontal): ')
    if y.isdigit():
      y=int(y)
      if 1<=y<=10:
        break
    print('you need to tipe a number (1-10)')
  if action.lower()=='f': #flagging
    minescount=flag(x, y, minescount)
  elif action.lower()=='u': #uncovering tiles
    status, freespaces = uncover(x, y, 0, freespaces)
    if status: #endin of game in case of win or loose
      print(f'in {roundcounter} rounds')
      break
  else:
    print("this option doesn't exist") 