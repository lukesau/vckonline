import socket
import time
import threading
from common import *
import json
import mariadb


class ServerVCKO:
    def __init__(self):
        self.host = socket.gethostbyname(socket.gethostname())
        self.server_socket = socket.socket()
        self.server_socket.bind((self.host, Constants.port))
        self.game_dict = {}
        self.lobby = []
        self.gamers = []

        # Start the thread to remove inactive players
        self.inactive_player_thread = threading.Thread(target=self.remove_inactive, daemon=True)
        self.inactive_player_thread.start()

    def remove_inactive(self):
        while True:
            current_time = time.time()
            self.lobby = [player for player in self.lobby if current_time - player.last_active_time <= 60]
            inactive_games = [game_id for game_id, game in self.game_dict.items() if
                              current_time - game.last_active_time > 180]
            for game_id in inactive_games:
                del self.game_dict[game_id]
            time.sleep(10)

    def handle_client(self, conn, addr):
        print(f"Connection from: {addr}")
        connected = True
        while connected:
            msg_length = conn.recv(Constants.header_size).decode(Constants.text_format)
            if msg_length:
                msg_length = int(msg_length)
                msg = conn.recv(msg_length).decode(Constants.text_format)
                first_word = msg.split()[0]
                full_command = msg.split()
                match first_word:
                    case "connection_check":
                        connected = False
                        send_data(conn, "received".encode(Constants.encoding))
                    case "lobby":
                        connected = False
                        if full_command[1] == "join" and len(full_command) > 2:
                            joining_player_name = ' '.join(full_command[2:])
                            joining_player_id = str(shortuuid.uuid())
                            joining_player = LobbyMember(joining_player_name, joining_player_id)
                            self.lobby.append(joining_player)
                            message = f"lobby joined {joining_player_id}"
                            send_data(conn, message.encode(Constants.encoding))
                        elif full_command[1] == "rename" and len(full_command) > 3:
                            for player in self.lobby:
                                if player.player_id == full_command[2]:
                                    player.name = ' '.join(full_command[3:])
                                    message = f"lobby renamed {player.player_id}"
                                    send_data(conn, message.encode(Constants.encoding))
                                else:
                                    send_data(conn, "invalid message".encode(Constants.encoding))
                        elif full_command[1] == "leave" and len(full_command) > 2:
                            temp_lobby = []
                            for player in self.lobby:
                                if player.player_id != full_command[2]:
                                    temp_lobby.append(player)
                            self.lobby = temp_lobby
                            self.send_lobby_state(conn)
                        elif full_command[1] == "get_status" and len(full_command) >= 2:
                            found = False
                            if len(full_command) == 3:
                                for player in self.lobby:
                                    if full_command[2] == player.player_id:
                                        player.last_active_time = time.time()  # update last active time
                                        self.send_lobby_state(conn)
                                for player in self.gamers:
                                    if full_command[2] == player.player_id:
                                        message = f"game joined {player.game_id}"
                                        send_data(conn, message.encode(Constants.encoding))
                            else:
                                self.send_lobby_state(conn)
                        elif full_command[1] == "ready" and len(full_command) > 2:
                            ready_check = 0
                            for player in self.lobby:
                                if player.player_id == full_command[2]:
                                    player.is_ready = True
                                if player.is_ready:
                                    ready_check += 1
                            print(f"ready check: {ready_check}")
                            if ready_check == len(self.lobby):
                                new_game_id = str(uuid.uuid4())
                                for player in self.lobby:
                                    print(f"lobby player: {player.name}")
                                players_to_remove = []
                                for player in self.lobby:
                                    if player.is_ready:
                                        new_gamer = GameMember(player.player_id, player.name, new_game_id)
                                        self.gamers.append(new_gamer)
                                        players_to_remove.append(player)
                                for player in players_to_remove:
                                    self.lobby.remove(player)
                                # START GAME
                                new_game = Game(load_game_data(new_game_id, "base1", self.gamers))
                                self.game_dict[new_game.game_id] = new_game
                                print(f"size of game dict: {len(self.game_dict)}")
                                message = f"game joined {new_game_id}"
                                send_data(conn, message.encode(Constants.encoding))
                            else:
                                self.send_lobby_state(conn)
                        elif full_command[1] == "unready" and len(full_command) > 2:
                            for player in self.lobby:
                                if player.player_id == full_command[2]:
                                    player.is_ready = False
                            self.send_lobby_state(conn)
                        else:
                            send_data(conn, "invalid message".encode(Constants.encoding))
                    case "game":
                        connected = False
                        if full_command[1] == "get_status" and len(full_command) == 3:
                            print(full_command[2])
                            print(len(self.game_dict))
                            for game in self.game_dict:
                                print(f"game id: {game}")
                            game_id = full_command[2]
                            game = self.game_dict.get(game_id)
                            if not game:
                                message = "game state error: game not found"
                                send_data(conn, message.encode(Constants.encoding))
                            else:
                                game.last_active_time = time.time()
                                self.send_game_state(conn, full_command[2])
                    case _:
                        connected = False
                        send_data(conn, "invalid message".encode(Constants.encoding))
                print(f"[{addr}] {msg}")
        conn.close()

    def start(self):
        self.server_socket.listen()
        print(f"server is listening on {socket.gethostbyname(socket.gethostname())}")
        while True:
            conn, addr = self.server_socket.accept()
            thread = threading.Thread(target=self.handle_client, args=(conn, addr))
            thread.start()
            print(f"\nActive threads: {threading.active_count() - 1}")

    def send_lobby_state(self, conn):
        lobby_data = []
        for lobby_member in self.lobby:
            player_dict = {
                "name": lobby_member.name,
                "player_id": lobby_member.player_id,
                "is_ready": lobby_member.is_ready
            }
            lobby_data.append(player_dict)
        lobby_data.append({'game_count': len(self.game_dict)})
        response = f"lobby state {json.dumps(lobby_data)}"
        print(response)
        send_data(conn, response.encode(Constants.encoding))

    def send_game_state(self, conn, game_id):
        game = self.game_dict.get(game_id)
        if not game:
            response = "game state error: game not found"
        else:
            game_json = json.dumps(game, cls=GameObjectEncoder, indent=2)
            response = f"game state {game_json}"
        send_data(conn, response.encode(Constants.encoding))


def load_game_data(game_id, preset, player_list_from_lobby):
    monster_query = ""
    monster_stack = []
    citizen_query = ""
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    starter_query = "SELECT * FROM starters"
    starter_stack = []
    player_list = []
    citizen_grid: List[List[Citizen]] = [[] for _ in range(10)]
    domain_grid: List[List[Domain]] = [[] for _ in range(5)]
    monster_grid: List[List[Monster]] = [[] for _ in range(5)]
    die_one = 0
    die_two = 0
    die_sum = 0
    exhausted_count = 0
    effects = {
        "roll_phase": [],
        "harvest_phase": [],
        "action_phase": []
    }
    action_required = {
        "player_id": "",
        "action": ""
    }
    match preset:
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
    try:
        my_connect = mariadb.connect(user='vckonline', password='vckonline', host='127.0.0.1',
                                     database='vckonline')
        my_cursor = my_connect.cursor(dictionary=True)

        my_cursor.callproc(monster_query)

        results = my_cursor.fetchall()
        for row in results:
            my_monster = Monster(row['id_monsters'], row['name'], row['area'], row['monster_type'],
                                 row['monster_order'], row['strength_cost'], row['magic_cost'], row['vp_reward'],
                                 row['gold_reward'], row['strength_reward'], row['magic_reward'],
                                 row['has_special_reward'], row['special_reward'], row['has_special_cost'],
                                 row['special_cost'], row['is_extra'], row['expansion'])
            monster_stack.append(my_monster)

        my_cursor.callproc(citizen_query)
        citizen_count = 5
        if len(player_list_from_lobby) == 5:
            citizen_count = 6
        results = my_cursor.fetchall()
        for row in results:
            for i in range(citizen_count):
                my_citizen = Citizen(row['id_citizens'], row['name'], row['gold_cost'], row['roll_match1'],
                                     row['roll_match2'], row['shadow_count'], row['holy_count'], row['soldier_count'],
                                     row['worker_count'], row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                     row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                     row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                     row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                     row['special_payout_on_turn'], row['special_payout_off_turn'],
                                     row['special_citizen'],
                                     row['expansion'])
                citizen_stack.append(my_citizen)

        my_cursor.callproc(domain_query)
        results = my_cursor.fetchall()
        for row in results:
            my_domain = Domain(row['id_domains'], row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'],
                               row['soldier_count'], row['worker_count'], row['vp_reward'],
                               row['has_activation_effect'], row['has_passive_effect'], row['passive_effect'],
                               row['activation_effect'], row['text'], row['expansion'])
            domain_stack.append(my_domain)

        my_cursor.callproc(duke_query)
        results = my_cursor.fetchall()
        for row in results:
            my_duke = Duke(row['id_dukes'], row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'],
                           row['shadow_mult'], row['holy_mult'], row['soldier_mult'], row['worker_mult'],
                           row['monster_mult'], row['citizen_mult'], row['domain_mult'], row['boss_mult'],
                           row['minion_mult'], row['beast_mult'], row['titan_mult'], row['expansion'])
            duke_stack.append(my_duke)

        my_cursor.execute(starter_query)
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(row['id_starters'], row['name'], row['roll_match1'], row['roll_match2'],
                                 row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                 row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                 row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                 row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                 row['special_payout_on_turn'], row['special_payout_off_turn'], row['expansion'])
            starter_stack.append(my_starter)
        my_cursor.close()
        my_connect.close()
    except Exception as e:
        print(f"Error: {e}")
    # print(f"size of monster stack: {len(monster_stack)}")
    # print(f"size of citizen stack: {len(citizen_stack)}")
    # print(f"size of domain stack: {len(domain_stack)}")
    # print(f"size of duke stack: {len(duke_stack)}")
    # print(f"size of starter stack: {len(starter_stack)}")
    # create players and determine order
    if not all([player_list_from_lobby, starter_query, monster_stack, citizen_stack, domain_stack, duke_stack]):
        raise ValueError("One or more required lists are empty.")
    else:
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            player_list.append(my_player)
        random.shuffle(player_list)
        player_list[0].is_first = True
        # give players starters and dukes
        for player in player_list:
            player.owned_starters.append(starter_stack[0])
            player.owned_starters.append(starter_stack[1])
            for i in range(2):
                player.owned_dukes.append(duke_stack.pop())
        # deal monsters onto the board
        grouped_monsters = {}
        for monster in monster_stack:
            area = monster.area
            if area in grouped_monsters:
                grouped_monsters[area].append(monster)
            else:
                grouped_monsters[area] = [monster]
        # Reverse the order of each group by monster_order
        for area, monsters in grouped_monsters.items():
            monsters.sort(key=lambda item: item.order, reverse=True)
        areas = list(grouped_monsters.keys())
        chosen_areas = random.sample(areas, 5)
        for i, area in enumerate(chosen_areas):
            monsters = grouped_monsters[area]
            monster_grid[i].extend(monsters)
        for i, stack in enumerate(monster_grid):
            for monster in stack:
                monster.toggle_visibility(True)
            # Make the last monster in the stack accessible
            stack[-1].toggle_accessibility(True)
        monster_stack = []
        # deal citizens onto the board
        # Create a dictionary to store citizen lists with roll numbers as keys
        citizens_by_roll = {roll: [] for roll in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]}
        # Group citizens by roll number
        for citizen in citizen_stack:
            citizen.toggle_visibility()
            citizens_by_roll[citizen.roll_match1].append(citizen)
        for roll in citizens_by_roll:
            # Map 11 roll to index 9
            index = roll - 1 if roll < 11 else 9
            citizens = citizens_by_roll[roll]
            citizen_grid[index].extend(list(citizens))
            # Make the first citizen in each list accessible
            citizen_grid[index][-1].toggle_accessibility(True)
        citizen_stack = []
        # Deal the domains into the stacks
        for i in range(5):
            stack = domain_grid[i]
            for j in range(3):
                if j == 2:  # top domain is visible and accessible
                    domain = domain_stack.pop()
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                    stack.append(domain)
                else:  # other domains are not visible or accessible
                    domain = domain_stack.pop()
                    stack.append(domain)

        # Create a dictionary to store all the stacks
        game_state = {'game_id': game_id,
                      'player_list': player_list,
                      'monster_grid': monster_grid,
                      'citizen_grid': citizen_grid,
                      'domain_grid': domain_grid,
                      'die_one': die_one,
                      'die_two': die_two,
                      'die_sum': die_sum,
                      'exhausted_count': exhausted_count,
                      'effects': effects,
                      'action_required': action_required}
    # Return the dictionary
        return game_state


if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()
