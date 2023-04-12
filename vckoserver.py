import socket
import time
import threading

class ServerVCKO:
    def __init__(self):
        self.host = socket.gethostname()
        self.port = 5000 
        self.server_socket = socket.socket()  
        self.server_socket.bind((host, port))
        self.header_size = 1024
        self.format = "utf-8"
        
    def handle_client(conn, addr):
        print("Connection from: " + str(address))
        connected = True
        while connected:
            msg_length = conn.recv(self.header_size).decode(self.format)
            msg_length = int(msg_length)
            msg = conn.recv(msg_length).decode(self.format)
            print(f"[{addr
                
    def start(self):
        self.server.listen()
        while True:
            conn, address = server_socket.accept()
            thread = threading.Thread(target = handle_client, args = (conn, addr))
            thread.start
            print(f"Active threads: {threading.activeCount() - 1}")
            
if __name__ == '__main__':
    print("server starting")
    server = ServerVCKO()
    server.start()

