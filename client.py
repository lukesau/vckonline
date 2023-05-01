import wx
import socket
from common import *


class ClientVCKO(wx.App):
    def OnInit(self):
        self.connection_status = False
        self.player_id = ""
        self.player_name = ""
        self.lobby = []
        self.in_lobby = False
        self.in_game = False
        self.game_id = ""
        self.game = None
        self.debug_frame = DebugFrame(self)
        self.start_frame = StartFrame(self)
        self.lobby_frame = LobbyFrame(self)
        self.game_frame = GameFrame(self)
        self.last_lobby_state = ""
        self.last_game_state = ""
        self.debug_frame.set_connection_status()
        return True

    def parse_response(self, response):
        if len(response) > 1000:
            print(f"{response[:1000]}...")
        else:
            print(response)
        first_word = response.split()[0]
        full_command = response.split()
        match first_word:
            case "lobby":
                if full_command[1] == "joined" and len(full_command) == 3:
                    self.player_id = full_command[2]
                    self.in_lobby = True
                    self.start_frame.enter_lobby(None)
                elif full_command[1] == "state":
                    json_response = ' '.join(full_command[2:])
                    new_lobby_state = json.loads(json_response)
                    if new_lobby_state != self.lobby:
                        self.lobby = new_lobby_state
                        self.lobby_frame.get_lobby_status()
                else:
                    print("Couldn't understand that response")
            case "game":
                if full_command[1] == "joined" and len(full_command) == 3:
                    self.game_id = full_command[2]
                    self.in_game = True
                    self.in_lobby = False
                    self.lobby_frame.enter_game()
                elif full_command[1] == "state":
                    json_response = ' '.join(full_command[2:])
                    new_game_state = json.loads(json_response)
                    if new_game_state == self.last_game_state:
                        return
                    self.last_game_state = new_game_state

    def update_lobby_status(self):
        return self.in_lobby


class GameFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online', size=Constants.large_window_size)
        self.app = app
        self.panel = wx.Panel(self)

        # Create a static box sizer with padding
        vbox = wx.StaticBoxSizer(wx.StaticBox(self.panel, label=""), wx.VERTICAL)
        vbox.AddSpacer(10)  # Add a bit of padding at the top

        # Wrap the list control widget inside a scrolled window
        sw = wx.ScrolledWindow(vbox.GetStaticBox(), style=wx.VSCROLL)
        sw.SetScrollbars(1, 1, 1, 1)  # Show the scrollbars
        self.game_state_list = wx.ListCtrl(sw, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        sw.SetSizer(wx.BoxSizer(wx.VERTICAL))
        sw.GetSizer().Add(self.game_state_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        vbox.Add(sw, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)  # Add the scrolled window to the sizer

        vbox.AddSpacer(10)  # Add a bit of padding at the bottom

        # Set the sizer for the panel
        self.panel.SetSizer(vbox)

        self.SetMinSize(Constants.medium_window_size)
        self.last_game_state = ""
        self.timer_interval = 500
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.get_game_status, self.timer)
        self.timer.Start(self.timer_interval)

    def get_game_status(self, event=None):
        if self.app.in_game and connection_check():
            self.app.parse_response(send(f"game get_status {self.app.game_id}"))
            if self.last_game_state == self.app.last_game_state:
                if self.timer_interval < 9500:
                    self.timer_interval += 500
                    self.timer.Start(self.timer_interval)
                # If the current game state is the same as the last one, don't update the list control
                return
            pretty_json_str = json.dumps(self.app.last_game_state, indent=4, sort_keys=False)
            self.game_state_list.ClearAll()
            self.game_state_list.InsertColumn(0, "Game State")
            for idx, state in enumerate(pretty_json_str.split('\n')):
                self.game_state_list.InsertItem(idx, state.strip())
            self.game_state_list.SetColumnWidth(0, wx.LIST_AUTOSIZE)
            # Save the new game state
            self.last_game_state = self.app.last_game_state


class LobbyFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online Lobby', size=Constants.medium_window_size)
        self.app = app
        self.panel = wx.Panel(self)
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.last_lobby_state = []
        self.current_player_index = None
        # Create the list control and columns
        self.list_ctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        self.list_ctrl.InsertColumn(0, "Player Name")
        self.list_ctrl.InsertColumn(1, "Ready Status", format=wx.LIST_FORMAT_RIGHT)
        self.get_lobby_status()
        # Create the ready button
        ready_button = wx.Button(self.panel, label="Ready Up")
        ready_button.Bind(wx.EVT_BUTTON, self.on_ready_up)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.highlight_current_player)
        # Add the list control and ready button to the vertical sizer
        self.vertical_sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 5)
        self.vertical_sizer.Add(ready_button, 0, wx.ALL | wx.CENTER, 5)
        self.panel.SetSizer(self.vertical_sizer)
        self.SetMinSize(Constants.small_window_size)

        # Bind the size event to adjust the column widths
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.timer_interval = 500
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.get_lobby_status, self.timer)
        self.timer.Start(self.timer_interval)

    def on_size(self, event):
        # Calculate the width of each column based on the width of the list control
        width = self.list_ctrl.GetSize()[0]
        col_width = width // 2
        self.list_ctrl.SetColumnWidth(0, col_width)
        self.list_ctrl.SetColumnWidth(1, col_width)
        event.Skip()

    def get_lobby_status(self, event=None):
        if self.app.in_lobby and connection_check():
            self.app.parse_response(send(f"lobby get_status {self.app.player_id}"))
            if self.app.lobby == self.last_lobby_state:
                # If the current lobby state is the same as the last one, don't update the list control
                if self.timer_interval < 9500:
                    self.timer_interval += 500
                    self.timer.Start(self.timer_interval)
                return
            self.list_ctrl.DeleteAllItems()
            for index, player in enumerate(self.app.lobby):
                self.list_ctrl.InsertItem(index, player['name'])
                self.list_ctrl.SetItem(index, 1, "Ready" if player['is_ready'] else "Not Ready")
                if player['player_id'] == self.app.player_id:
                    self.current_player_index = index
                    self.list_ctrl.SetItemState(index, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                else:
                    self.list_ctrl.SetItemState(index, 0, wx.LIST_STATE_SELECTED)
            # Save the new lobby state
            self.last_lobby_state = self.app.lobby

    def highlight_current_player(self, event=None):
        if self.current_player_index is not None:
            self.list_ctrl.Select(self.current_player_index)
        else:
            self.list_ctrl.Select(-1)

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

    def enter_game(self, event=None):
        self.app.game_frame.Show()
        self.Hide()

    def on_close(self, event):
        self.app.parse_response(send(f"lobby leave {self.app.player_id}"))
        self.Destroy()


class StartFrame(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent=None, title='Enter Name', size=Constants.small_window_size)
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

    def enter_lobby(self, event):
        self.app.lobby_frame.Show()
        self.Hide()

    def api_call(self, message):
        if connection_check():
            self.app.parse_response(send(message))
            self.name_field.SetValue("")


class DebugFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCKO Debug Console', size=Constants.small_window_size)
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
        self.SetMinSize(Constants.small_window_size)
        self.Show()
        # Create a timer to call the connection_check method every 2 seconds
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.set_connection_status, self.timer)
        self.timer.Start(10000)

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


def connection_check():
    try:
        response = send("connection_check")
        if response == "received":
            return True
    except ConnectionRefusedError:
        return False
    except BrokenPipeError:
        return False


def send(message):
    client_socket = socket.socket()
    client_socket.connect((Constants.host, Constants.port))
    message_bytes = message.encode(Constants.encoding)
    send_data(client_socket, message_bytes)
    response = receive_data(client_socket)
    client_socket.close()
    return response.decode(Constants.encoding)


if __name__ == '__main__':
    the_app = ClientVCKO()
    the_app.MainLoop()
