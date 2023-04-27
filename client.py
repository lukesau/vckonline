import wx
import socket
import threading
from constants import *
import json


class ClientVCKO(wx.App):
    def OnInit(self):
        self.debug_frame = DebugFrame(self)
        self.debug_frame.Show()
        self.start_frame = StartFrame(self)
        self.debug_frame.Show()
        self.connection_status = False
        self.in_lobby = False
        self.player_id = ""
        self.debug_frame.set_connection_status()
        self.lobby = []
        return True

    def parse_response(self, response):
        print(f"{response}")
        first_word = response.split()[0]
        full_command = response.split()
        match first_word:
            case "lobby":
                full_command = response.split()
                if full_command[1] == "joined" and len(full_command) == 3:
                    self.player_id = full_command[2]
                    self.in_lobby = True
                    self.start_frame.show_list_view(None)
                elif full_command[1] == "state":
                    json_response = ' '.join(full_command[2:])
                    print(json_response)
                    self.lobby = json.loads(json_response)
                else:
                    print("Couldn't understand that response")
            case _:
                print(full_command[1])


class DebugFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCKO Debug Console', size=Constants.default_window_size)
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
        self.on_press(event)

    def api_call(self, message):
        if connection_check():
            self.app.parse_response(send(message))
            self.message_field.SetValue("")


class StartFrame(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent=None, title='Enter Name', size=Constants.minimum_window_size)
        self.panel = wx.Panel(self)
        self.app = parent
        # Create text field with suggestion text
        text = wx.StaticText(self.panel, label='Enter name:')
        self.name_field = wx.TextCtrl(self.panel, style=wx.TE_PROCESS_ENTER, value='')

        # Create submit button
        submit_button = wx.Button(self.panel, label='Submit')
        submit_button.Bind(wx.EVT_BUTTON, self.on_submit)
        self.name_field.Bind(wx.EVT_TEXT_ENTER, self.on_text_enter)

        # Add text field and submit button to vertical sizer
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        vertical_sizer.Add(text, 0, wx.ALL, 5)
        vertical_sizer.Add(self.name_field, 0, wx.EXPAND | wx.ALL, 5)
        vertical_sizer.Add(submit_button, 0, wx.ALL | wx.CENTER, 5)

        self.panel.SetSizer(vertical_sizer)
        self.Show()

    def on_submit(self, event):
        message = self.name_field.GetValue()
        if not message:
            print("You didn't enter anything!")
        else:
            self.api_call(f"lobby join {message}")

    def on_text_enter(self, event):
        self.on_submit(event)

    def show_list_view(self, event):
        list_frame = LobbyFrame(self.app)
        list_frame.Show()

        # Refresh the layout of the original panel
        self.Hide()

    def api_call(self, message):
        if connection_check():
            self.app.parse_response(send(message))
            self.name_field.SetValue("")

class LobbyFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online Lobby', size=(250, 300))
        self.app = app
        self.panel = wx.Panel(self)
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)

        # Create the list control and columns
        self.list_ctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        self.list_ctrl.InsertColumn(0, "Player Name")
        self.list_ctrl.InsertColumn(1, "Ready Status", format=wx.LIST_FORMAT_RIGHT)
        self.get_lobby_status()
        # Create the ready button
        ready_button = wx.Button(self.panel, label="Ready Up")
        ready_button.Bind(wx.EVT_BUTTON, self.on_ready_up)

        # Add the list control and ready button to the vertical sizer
        self.vertical_sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 5)
        self.vertical_sizer.Add(ready_button, 0, wx.ALL | wx.CENTER, 5)
        self.panel.SetSizer(self.vertical_sizer)
        self.SetMinSize(Constants.minimum_window_size)

        # Bind the size event to adjust the column widths
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.Show()
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.get_lobby_status, self.timer)
        self.timer.Start(1000)

    def on_size(self, event):
        # Calculate the width of each column based on the width of the list control
        width = self.list_ctrl.GetSize()[0]
        col_width = width // 2
        self.list_ctrl.SetColumnWidth(0, col_width)
        self.list_ctrl.SetColumnWidth(1, col_width)

        event.Skip()

    def get_lobby_status(self, event=None):
        if connection_check():
            self.app.parse_response(send("lobby get_status"))
        # Clear the list control
        self.list_ctrl.DeleteAllItems()

        # Populate the list control with the contents of the lobby
        for index, player in enumerate(self.app.lobby):
            self.list_ctrl.InsertItem(index, player['name'])
            self.list_ctrl.SetItem(index, 1, "Ready" if player['is_ready'] else "Not Ready")

    def on_ready_up(self, event):
        for player in self.app.lobby:
            if player['player_id'] == self.app.player_id:
                if player['is_ready']:
                    if connection_check():
                        self.app.parse_response(send(f"lobby unready {self.app.player_id}"))
                else:
                    if connection_check():
                        self.app.parse_response(send(f"lobby ready {self.app.player_id}"))
                break

    def on_close(self, event):
        self.app.parse_response(send(f"lobby leave {self.app.player_id}"))
        self.Destroy()



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
