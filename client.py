import wx
import socket
import threading
from constants import *
import json


class ClientVCKO(wx.App):
    def OnInit(self):
        self.frame = MyFrame(self)
        self.frame.Show()
        self.connection_status = False
        self.in_lobby = False
        self.player_id = False
        self.frame.set_connection_status()
        return True

    def parse_response(self, response):
        print(f"{response}")
        first_word = response.split()[0]
        match first_word:
            case "lobby":
                full_command = response.split()
                if full_command[1] == "joined" and len(full_command) == 3:
                    self.player_id = full_command[2]
                    self.in_lobby = True
                    print(self.player_id)
                    print(self.frame)
                    self.frame.show_list_view(None)
                    print("did it work")
                else:
                    print("Couldn't understand that response")
            case _:
                print(response)


class MyFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online', size=Constants.default_window_size)
        self.app = app
        self.panel = wx.Panel(self)
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.message_field = wx.TextCtrl(self.panel, style=wx.TE_PROCESS_ENTER)
        self.connection_status_indicator = wx.StaticText(self.panel, label="Connection Status")
        self.my_btn = wx.Button(self.panel, label="Send call")
        self.my_btn.Bind(wx.EVT_BUTTON, self.on_press)
        self.message_field.Bind(wx.EVT_TEXT_ENTER, self.on_text_enter)
        # Create a horizontal sizer to hold the connection_status StaticText
        self.status_sizer.AddStretchSpacer()
        self.status_sizer.Add(wx.StaticText(self.panel), 0, wx.EXPAND | wx.RIGHT, 5)
        self.status_sizer.Add(self.connection_status_indicator, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.status_sizer.Add(wx.StaticText(self.panel), 0, wx.EXPAND | wx.LEFT, 5)
        # Add the text field, button, and status sizer to the vertical sizer
        self.vertical_sizer.Add(self.message_field, 0, wx.ALL | wx.EXPAND, 5)
        self.vertical_sizer.Add(self.my_btn, 0, wx.ALL | wx.CENTER, 5)
        self.vertical_sizer.AddStretchSpacer()
        self.vertical_sizer.Add(self.status_sizer, 0, wx.ALIGN_LEFT | wx.BOTTOM, 5)
        self.panel.SetSizer(self.vertical_sizer)
        self.SetMinSize(Constants.minimum_window_size)
        self.Show()
        # Create a timer to call the connection_check method every 2 seconds
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.set_connection_status, self.timer)
        self.timer.Start(5000)

    def show_list_view(self, event):
        print("show list view")
        # create a list view with a ready up button
        list_ctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        list_ctrl.InsertColumn(0, "Player ID")
        list_ctrl.InsertColumn(1, "Ready Status")
        list_ctrl.InsertItem(0, self.app.player_id)
        list_ctrl.SetItem(0, 1, "Not Ready")

        ready_button = wx.Button(self.panel, label="Ready Up")
        ready_button.Bind(wx.EVT_BUTTON, self.on_ready_up)

        # Add the list view and button to the vertical sizer
        self.vertical_sizer.Insert(0, list_ctrl, 0, wx.ALL | wx.EXPAND, 5)
        self.vertical_sizer.Add(ready_button, 0, wx.ALL | wx.CENTER, 5)
        self.panel.Layout()

    def on_ready_up(self, event):
        # implement ready up functionality here
        print("Ready Up button pressed!")

    def set_connection_status(self, event=None):
        if connection_check():
            self.connection_status_indicator.SetLabel("Connected")
            self.connection_status_indicator.SetForegroundColour(Constants.green)
        else:
            self.connection_status_indicator.SetLabel("Not Connected")
            self.connection_status_indicator.SetForegroundColour(Constants.red)

    def on_press(self, event):
        message = self.message_field.GetValue()
        if not message:
            print("You didn't enter anything!")
        else:
            self.api_call(message)

    def on_text_enter(self, event):
        message = self.message_field.GetValue()
        if not message:
            print("You didn't enter anything!")
        else:
            self.api_call(message)

    def api_call(self, message):
        if connection_check():
            self.app.parse_response(send(message))
            self.message_field.SetValue("")


def connection_check():
    try:
        response = send("connection_check")
        if response == "received":
            return True
    except ConnectionRefusedError:
        return False
    except BrokenPipeError:
        return False


def _send(msg, input_socket):
    message = msg.encode(Constants.text_format)
    msg_length = len(message)
    send_length = str(msg_length).encode(Constants.text_format)
    send_length += b' ' * (Constants.header_size - len(send_length))
    input_socket.send(send_length)
    input_socket.send(message)
    return input_socket.recv(2048).decode(Constants.text_format)


def send(message):
    client_socket = socket.socket()
    client_socket.connect((Constants.host, Constants.port))
    response = _send(message, client_socket)
    return response


if __name__ == '__main__':
    the_app = ClientVCKO()
    the_app.MainLoop()
