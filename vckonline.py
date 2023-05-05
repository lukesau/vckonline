from common import *
from server import load_game_data
player1_id = shortuuid.uuid()
player2_id = shortuuid.uuid()
player1 = Player(player1_id, "Player 1")
player2 = Player(player2_id, "Player 2")
player_list = [player1, player2]
try:
    base1_new_game_state = load_game_data(str(uuid.uuid4()), "base1", player_list)
    game = Game(base1_new_game_state)
    game.play_turn()
    game_json = json.dumps(game, cls=GameObjectEncoder, indent=2)
    with open("game_state.txt", "w") as dump:
        dump.write(game_json)
except ValueError:
    print("Error: Failed to load game data")
