from basegame import *

print("Welcome to Valeria Card Kingdoms: Online")
playerCount = 2 #int(input("How many players? (2-5):\n"))
citizenSet = "shuffled" #input("What set do you want to play? (base1, base2, shadowvale, flamesandfrost, crimsonseas, shuffled):\n")
#gameBoard = Board(playerCount, citizenSet)
gameBoard = Board(playerCount, citizenSet)
#have players select dukes
for player in gameBoard.playerList:
        player.display()
        for duke in player.ownedDukes:
          duke.display()
        dukeChoice = 2#int(input("Enter Duke number:\n"))
        player.duke = player.ownedDukes[dukeChoice - 1]
        #player.duke.display()
#gameBoard.display()
#while not gameBoard.end_check():
gameBoard.play_turn()
