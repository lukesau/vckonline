import wx
import socket

class MyFrame(wx.Frame):    
    def __init__(self):
        super().__init__(parent=None, title='VCK Online')
        panel = wx.Panel(self)        
        my_sizer = wx.BoxSizer(wx.VERTICAL)        
        self.text_ctrl = wx.TextCtrl(panel)
        my_sizer.Add(self.text_ctrl, 0, wx.ALL | wx.EXPAND, 5)        
        my_btn = wx.Button(panel, label='Press Me')
        my_btn.Bind(wx.EVT_BUTTON, self.on_press)
        my_sizer.Add(my_btn, 0, wx.ALL | wx.CENTER, 5)        
        panel.SetSizer(my_sizer)
        self.host = "lukesau.com"
        self.port = 5000  # socket server port number   
        self.header_size = 1024
        self.format = "utf-8"
        self.disconnect_message = "!DISCONNECT"
        self.Show()
        self.client_socket = socket.socket()
        self.client_socket.connect((self.host, self.port))  # connect to the server

    def on_press(self, event):
        message = self.text_ctrl.GetValue()
        if not message:
            print("You didn't enter anything!")
        else:
            self.send(message)
            self.text_ctrl.SetValue("")
    def sync_with_server(self):
        client_socket = socket.socket()  # instantiate
        client_socket.connect((self.host, self.port))  # connect to the server
    def send(self, msg):
        message = msg.encode(self.format)
        msg_length = len(message)
        print(msg_length)
        send_length = str(msg_length).encode(self.format)
        send_length += b' ' * (self.header_size - len(send_length))
        self.client_socket.send(send_length)
        self.client_socket.send(message)
        print("done sending")

        
        
if __name__ == '__main__':
    app = wx.App()
    frame = MyFrame()
    app.MainLoop()
    



