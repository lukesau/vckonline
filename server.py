import socket
import time
import threading
from common import *
from constants import *
import json


class ServerVCKO:
    def __init__(self):
        self.host = socket.gethostname()
        self.server_socket = socket.socket()
        self.server_socket.bind((self.host, Constants.port))
        self.game_list = []
        self.lobby = []
        self.gamers = []

    def handle_client(self, conn, addr):
        print(f"Connection from: {addr}")
        connected = True
        while connected:
            msg_length = conn.recv(Constants.header_size).decode(Constants.text_format)
            if msg_length:
                msg_length = int(msg_length)
                msg = conn.recv(msg_length).decode(Constants.text_format)
                first_word = msg.split()[0]
                match first_word:
                    case "connection_check":
                        connected = False
                        conn.send("received".encode(Constants.text_format))
                    case "lobby":
                        connected = False
                        full_command = msg.split()
                        if full_command[1] == "join" and len(full_command) > 2:
                            joining_player_name = ' '.join(full_command[2:])
                            joining_player_id = shortuuid.uuid()
                            joining_player = LobbyMember(joining_player_name, joining_player_id)
                            self.lobby.append(joining_player)
                            message = f"lobby joined {joining_player_id}"
                            conn.send(message.encode(Constants.text_format))
                        elif full_command[1] == "leave" and len(full_command) > 2:
                            temp_lobby = []
                            for player in self.lobby:
                                if player.player_id != full_command[2]:
                                    temp_lobby.append(player)
                            self.lobby = temp_lobby
                            self.send_lobby_state(conn)
                        elif full_command[1] == "get_status" and len(full_command) == 3:
                            found = False
                            for player in self.lobby:
                                if full_command[2] == player.player_id:
                                    self.send_lobby_state(conn)
                                    found = True
                            for player in self.gamers:
                                if full_command[2] == player.player_id:
                                    message = f"game joined {player.game_id}"
                                    conn.send(message.encode(Constants.text_format))
                                    found = True
                            # this only runs if we somehow receive an invalid player id
                            if not found:
                                message = f"Unable to find any player with player id: {full_command[2]}"
                                conn.send(message.encode(Constants.text_format))
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
                                message = f"game joined {new_game_id}"
                                conn.send(message.encode(Constants.text_format))
                            else:
                                self.send_lobby_state(conn)
                        elif full_command[1] == "unready" and len(full_command) > 2:
                            for player in self.lobby:
                                if player.player_id == full_command[2]:
                                    player.is_ready = False
                            self.send_lobby_state(conn)
                        else:
                            conn.send("invalid message".encode(Constants.text_format))
                    case _:
                        connected = False
                        conn.send("invalid message".encode(Constants.text_format))
                print(f"[{addr}] {msg}")
        conn.close()

    def start(self):
        self.server_socket.listen()
        print(f"server is listening on {socket.gethostbyname(self.host)}")
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
        response = f"lobby state {json.dumps(lobby_data)}"
        conn.send(response.encode(Constants.text_format))


class LobbyMember:
    def __init__(self, player_name, player_id):
        self.name = player_name
        self.player_id = player_id
        self.is_ready = False


class GameMember:
    def __init__(self, player_id, player_name, game_id):
        self.name = player_name
        self.player_id = player_id
        self.game_id = game_id


if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()
