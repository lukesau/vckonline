import json
import shortuuid
import uuid
from game import *
player1_id = shortuuid.uuid()
player2_id = shortuuid.uuid()
player1 = Player(player1_id, "Player 1")
player2 = Player(player2_id, "Player 2")
player_list = [player1, player2]
game_id = str(uuid.uuid4())
try:
    base1_new_game_state = load_game_data(game_id, "base1", player_list)
    game = Game(base1_new_game_state)
    game.hire_citizen(player1_id, 2, 0, 0)
    game.hire_citizen(player2_id, 2, 0, 0)
    game.die_one = 2
    game.die_two = 5
    game.die_sum = 7
    game.harvest_phase()
    game.act_on_required_action(player1_id, "choose 1")
    game_json = json.dumps(game, cls=GameObjectEncoder, indent=2)
    with open("game_state.txt", "w") as dump:
        dump.write(game_json)
except ValueError:
    print("Error: Failed to load game data")
