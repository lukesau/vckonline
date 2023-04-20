import socket
import time
import threading
from common import *

class ServerVCKO:
    def __init__(self):
        self.host = socket.gethostname()
        self.port = 8328 
        self.header_size = 1024
        self.format = "utf-8"
        self.disconnect_message = "!DISCONNECT"
        self.server_socket = socket.socket()  
        self.server_socket.bind((self.host, self.port))
        self.game_list = []

    def handle_client(self, conn, addr):
        print(f"Connection from: {addr}")
        connected = True
        while connected:
            msg_length = conn.recv(self.header_size).decode(self.format)
            if msg_length:
                msg_length = int(msg_length)
                msg = conn.recv(msg_length).decode(self.format)
                if msg == self.disconnect_message:
                    connected = False
                print(f"[{addr}] {msg}")
                conn.send("msg received".encode(self.format))
        conn.close()
    def start(self):
        self.server_socket.listen()
        print(f"server is listening on {socket.gethostbyname(self.host)}")
        while True:
            conn, addr = self.server_socket.accept()
            thread = threading.Thread(target=self.handle_client, args=(conn, addr))
            thread.start()
            print(f"Active threads: {threading.active_count() - 1}")
 
if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()
