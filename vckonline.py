from common import *
from server import *

print("Welcome to Valeria Card Kingdoms: Online")
playerCount = 2 # int(input("How many players? (2-5):\n"))
citizenSet = "na" # input("What set do you want to play? (base1, base2, shadowvale, flamesandfrost, crimsonseas, shuffled):\n")
# gameBoard = Board(playerCount, citizenSet)
gameBoard = Board(playerCount, citizenSet)
gameBoard.play_turn()
