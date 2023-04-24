from common import *

print("Welcome to Valeria Card Kingdoms: Online")
player_count = 4
citizen_set = "base2"  # base1, base2, shadowvale, flamesandfrost, crimsonseas, shuffled
game_board = Game(player_count, citizen_set)
game_board.play_turn()
