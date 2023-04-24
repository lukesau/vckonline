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
                            conn.send(joining_player_id.encode(Constants.text_format))
                        elif full_command[1] == "get_status":
                            lobby_data = []
                            for lobby_member in self.lobby:
                                player_dict = {
                                    "name": lobby_member.name,
                                    "player_id": lobby_member.player_id,
                                    "is_ready": lobby_member.is_ready
                                }
                                lobby_data.append(player_dict)
                            json_data = json.dumps(lobby_data)
                            print(json_data)
                            conn.send(json_data.encode(Constants.text_format))
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
            print(f"Active threads: {threading.active_count() - 1}")


class LobbyMember:
    def __init__(self, player_name, player_id):
        self.name = player_name
        self.player_id = player_id
        self.is_ready = False


if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()
