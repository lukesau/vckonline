from common import *
from server import load_game_data
player1 = Player(shortuuid.uuid(), "Player 1")
player2 = Player(shortuuid.uuid(), "Player 2")
player_list = [player1, player2]
base1_new_game_state = load_game_data(str(uuid.uuid4()), "base1", player_list)
game_board = Game(base1_new_game_state)
game_board.play_turn()
game_json = json.dumps(game_board, cls=GameObjectEncoder, indent=2)
with open("gamestate.txt", "w") as dump:
    dump.write(game_json)