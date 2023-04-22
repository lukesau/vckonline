from common import *

print("Welcome to Valeria Card Kingdoms: Online")
player_count = 4
citizen_set = "shadowvale"  # base1, base2, shadowvale, flamesandfrost, crimsonseas, shuffled
game_board = Board(player_count, citizen_set)
game_board.play_turn()
