from basegame import *

print("Welcome to Valeria Card Kingdoms: Online")
gameBoard = Board(5, "shuffled")
while not gameBoard.end_check():
    gameBoard.play_turn()
