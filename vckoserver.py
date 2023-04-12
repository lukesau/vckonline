import socket
import time
import threading

class ServerVCKO:
    def __init__(self):
        self.host = socket.gethostname()
        self.port = 5000 
        self.server_socket = socket.socket()  
        self.server_socket.bind((self.host, self.port))
        self.header_size = 1024
        self.format = "utf-8"
        self.disconnect_message = "!DISCONNECT"

    def handle_client(conn, addr):
        print("Connection from: " + str(address))
        connected = True
        while connected:
            msg_length = conn.recv(self.header_size).decode(self.format)
            if msg_length:
                msg_length = int(msg_length)
                msg = conn.recv(msg_length).decode(self.format)
                if msg == disconnect_message:
                    connected = False
            print(f"[{addr}] {msg}")
        conn.close()
    def start(self):
        self.server_socket.listen()
        print(f"server is listening on {socket.gethostbyname(self.host)}")
        while True:
            conn, address = self.server_socket.accept()
            thread = threading.Thread(target = self.handle_client, args = (conn, address))
            thread.start
            print(f"Active threads: {threading.active_count() - 1}")
 
if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()

