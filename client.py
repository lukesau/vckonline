import wx
import socket
from common import *
import glob


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
        self.lobby_frame = LobbyFrame(self)
        self.game_frame = GameFrame(self)
        self.last_lobby_state = ""
        self.last_game_state = ""
        self.game_count = 0
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
                elif full_command[1] == "state":
                    json_response = ' '.join(full_command[2:])
                    new_lobby_state = json.loads(json_response)
                    last_dict = new_lobby_state[-1] if new_lobby_state else None
                    if last_dict and last_dict in new_lobby_state:
                        new_lobby_state.remove(last_dict)
                    self.lobby = new_lobby_state
                    self.game_count = last_dict['game_count']
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
                    with open("game_state.txt", "w") as dump:
                        dump.write(json.dumps(new_game_state, indent=4))
                    if new_game_state == self.last_game_state:
                        return
                    self.last_game_state = new_game_state
                    self.game_frame.update_board(self.last_game_state)
    def update_lobby_status(self):
        return self.in_lobby
class TiledImages(wx.Window):
    def __init__(self, parent, image_path, rows=3, cols=3, overlap=10):
        super().__init__(parent)
        self.image = wx.Image(image_path)
        self.rows = rows
        self.cols = cols
        self.overlap = overlap
        self.SetMinSize(wx.Size(self.image.GetWidth() * self.cols - self.overlap, self.image.GetHeight() * self.rows - self.overlap))

    def OnPaint(self, event):
        dc = wx.PaintDC(self)
        for row in range(self.rows):
            for col in range(self.cols):
                x = col * (self.image.GetWidth() - self.overlap)
                y = row * (self.image.GetHeight() - self.overlap)
                dc.DrawBitmap(wx.Bitmap(self.image), x, y)


class MonsterCard(wx.StaticBitmap):
    def __init__(self, parent, card_id):
        img_path = None
        for file in glob.glob(f"images/monster_{card_id:02d}*.jpg"):
            img_path = file
            break  # Stop searching after the first matching file
        if not img_path:
            raise ValueError(f"No image found for card ID {card_id:02d}")

        self.parent = parent
        self.card_id = card_id
        self.bitmap = None

        super().__init__(parent, -1)

        self.Bind(wx.EVT_SIZE, self.on_size)
        self.update_bitmap()

    def update_bitmap(self):
        img_path = glob.glob(f"images/monster_{self.card_id:02d}*.jpg")[0]
        img = wx.Image(img_path, wx.BITMAP_TYPE_ANY)
        width, height = self.parent.GetSize()
        width = int(width * 0.15)  # Set the width to 15% of the parent width
        height = int(width * img.GetHeight() / img.GetWidth())  # Scale height to maintain aspect ratio
        img = img.Scale(width, height, wx.IMAGE_QUALITY_HIGH)
        self.bitmap = wx.Bitmap(img)
        self.SetBitmap(self.bitmap)

    def on_size(self, event):
        self.update_bitmap()
        event.Skip()


class GameFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online', size=Constants.large_window_size)
        self.app = app
        self.panel = wx.Panel(self)

        # Create a static box sizer with padding
        self.vbox = wx.StaticBoxSizer(wx.StaticBox(self.panel, label=""), wx.VERTICAL)
        self.vbox.AddSpacer(10)  # Add a bit of padding at the top
        self.monster_grid = wx.BoxSizer(wx.HORIZONTAL)
        # Create the game state list box
        self.game_state_list = wx.ListCtrl(self.panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.vbox.Add(self.game_state_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.vbox.AddSpacer(10)  # Add a bit of padding at the bottom

        # Set the sizer for the panel
        self.panel.SetSizer(self.vbox)

        self.SetMinSize(Constants.medium_window_size)
        self.last_game_state = ""
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.get_game_status, self.timer)
        self.timer.Start(500)
        self.panel.Layout()

    def get_game_status(self, event=None):
        if self.app.in_game and connection_check():
            self.app.parse_response(send(f"game get_status {self.app.game_id}"))
            if self.last_game_state == self.app.last_game_state:
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

    def update_board(self, game_state):
        game = Game(game_state)
        monster_ids = []
        for index, monster_stack in enumerate(game.monster_grid):
            monster_stack_sizer = wx.BoxSizer(wx.VERTICAL)  # Create a vertical sizer for the monster stack
            for monster in monster_stack:
                if monster['is_accessible']:
                    card_id = monster['monster_id']
                    try:
                        img_path = glob.glob(f"images/monster_{card_id:02}*.jpg")[0]
                    except IndexError:
                        raise ValueError(f"No image found for card ID {card_id:02}")
                    bitmap = wx.Bitmap(img_path, wx.BITMAP_TYPE_ANY)
                    card = MonsterCard(self.panel, card_id)
                    card.SetBitmap(bitmap)
                    monster_stack_sizer.Add(card, 0, wx.BOTTOM, 10)  # Add the card to the monster stack sizer
                    monster_ids.append(monster['monster_id'])
            # Add the monster stack sizer to the monster grid sizer
            self.monster_grid.Add(monster_stack_sizer, 0, wx.LEFT | wx.RIGHT, 10)
        self.vbox.Add(self.monster_grid, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        self.panel.Layout()
        self.panel.Refresh()
        self.Fit()

class LobbyFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(parent=None, title='VCK Online Lobby', size=Constants.medium_window_size)
        self.app = app
        self.panel = wx.Panel(self)
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)

        splitter = wx.SplitterWindow(self.panel)

        left_panel = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        text = wx.StaticText(left_panel, label='Enter name:')
        self.name_field = wx.TextCtrl(left_panel, style=wx.TE_PROCESS_ENTER, value='')
        self.connection_status_indicator = wx.StaticText(left_panel, label="Connection Status")
        submit_button = wx.Button(left_panel, label='Submit')
        submit_button.Bind(wx.EVT_BUTTON, self.on_submit)
        self.name_field.Bind(wx.EVT_TEXT_ENTER, self.on_text_enter)
        status_sizer.Add(wx.StaticText(left_panel), 0, wx.EXPAND | wx.RIGHT, 5)
        status_sizer.Add(self.connection_status_indicator, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        status_sizer.Add(wx.StaticText(left_panel), 0, wx.EXPAND | wx.LEFT, 5)
        left_sizer.Add(text, 0, wx.ALL, 5)
        left_sizer.Add(self.name_field, 0, wx.EXPAND | wx.ALL, 5)
        left_sizer.Add(submit_button, 0, wx.ALL | wx.CENTER, 5)
        left_sizer.AddStretchSpacer()
        left_sizer.Add(status_sizer, 0, wx.ALIGN_LEFT | wx.BOTTOM, 5)
        left_panel.SetSizer(left_sizer)
        self.last_lobby_state = []
        self.current_player_index = None

        # Create the list control and columns
        right_panel = wx.Panel(splitter)
        self.list_ctrl = wx.ListCtrl(right_panel, style=wx.LC_REPORT)
        self.list_ctrl.InsertColumn(0, "Player Name")
        self.list_ctrl.InsertColumn(1, "Ready Status", format=wx.LIST_FORMAT_RIGHT)
        self.set_connection_status()
        self.get_lobby_status()
        self.set_game_count()

        # Create the ready button
        ready_button = wx.Button(right_panel, label="Ready Up")
        ready_button.Bind(wx.EVT_BUTTON, self.on_ready_up)

        # Create the static text
        self.active_games_text = wx.StaticText(right_panel, label="Active games: 42069")

        # Add the static text and ready button to a horizontal box sizer
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.Add(self.active_games_text, 0, wx.ALIGN_BOTTOM | wx.LEFT | wx.BOTTOM, 5)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(ready_button, 0, wx.ALIGN_BOTTOM | wx.RIGHT | wx.BOTTOM, 5)

        # Add the list control and the button sizer to the vertical sizer
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 5)
        right_sizer.Add(button_sizer, 0, wx.EXPAND, 5)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(left_panel, right_panel)
        splitter.SetMinimumPaneSize(250)
        splitter.SetSashGravity(0.0)

        self.vertical_sizer.Add(splitter, 1, wx.EXPAND)
        self.panel.SetSizer(self.vertical_sizer)

        self.SetMinSize(Constants.small_window_size)

        # Bind the size event to adjust the column widths
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.lobby_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.get_lobby_status, self.lobby_check_timer)
        self.lobby_check_timer.Start(1000)
        # Create a timer to call the connection_check method every 2 seconds
        self.connection_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.set_connection_status, self.connection_check_timer)
        self.connection_check_timer.Start(10000)
        self.Show()

    def set_connection_status(self, event=None):
        if connection_check():
            self.connection_status_indicator.SetLabel("Connected")
            self.connection_status_indicator.SetForegroundColour(Constants.green)
        else:
            self.connection_status_indicator.SetLabel("Not Connected")
            self.connection_status_indicator.SetForegroundColour(Constants.red)

    def set_game_count(self):
        try:
            self.active_games_text.SetLabel(f"Active games: {self.app.game_count}")
        except AttributeError:
            print("Can't set game count. Maybe window hasn't loaded yet")

    def on_size(self, event):
        # Calculate the width of each column based on the width of the list control
        width = self.list_ctrl.GetSize()[0]
        col_width = width // 2
        self.list_ctrl.SetColumnWidth(0, col_width)
        self.list_ctrl.SetColumnWidth(1, col_width)
        event.Skip()

    def on_submit(self, event):
        name = self.name_field.GetValue()
        if not name:
            print("You didn't enter anything!")
        else:
            # Check if the player has already joined the lobby
            player_exists = False
            for player in self.last_lobby_state:
                if player['player_id'] == self.app.player_id:
                    player_exists = True
                    break
            if player_exists:
                # If the player already exists, rename them
                self.app.parse_response(send(f"lobby rename {self.app.player_id} {name}"))
            else:
                # If the player doesn't exist, join the lobby
                self.app.parse_response(send(f"lobby join {name}"))
            self.name_field.SetValue("")

    def on_text_enter(self, event):
        self.on_submit(event)

    def api_call(self, message):
        if connection_check():
            self.app.parse_response(send(message))
            self.name_field.SetValue("")

    def get_lobby_status(self, event=None):
        if not self.app.in_game and connection_check():
            self.app.parse_response(send(f"lobby get_status {self.app.player_id}"))
            if self.app.lobby == self.last_lobby_state:
                # If the current lobby state is the same as the last one, don't update the list control
                self.set_game_count()
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
            self.set_game_count()

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
        try:
            self.app.parse_response(send(f"lobby leave {self.app.player_id}"))
        except ConnectionRefusedError:
            print("Server may be down. Exiting anyway.")
        self.Destroy()


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
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.set_connection_status, self.timer)
        self.timer.Start(10000)
        self.set_connection_status()

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
        else:
            return False
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
