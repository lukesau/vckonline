"""Host ControlBot in a lobby and wait for a human opponent."""

import time

from bots.client import DEFAULT_BASE_URL, VckoClient
from bots.control_bot import ControlBot


def _lobby_members(client, player_id, lobby_id):
    status = client.lobby_status(player_id)
    for lob in status.get("lobbies") or []:
        if lob.get("lobby_id") == lobby_id:
            return lob.get("members") or []
    return []


def _other_members(members, bot_player_id):
    return [m for m in members if m.get("player_id") != bot_player_id]


class ControlBotHost:
    def __init__(self, client=None, preset="base", poll_interval=1.5, debug_mode=False, log=None):
        self.client = client or VckoClient()
        self.preset = preset
        self.poll_interval = poll_interval
        self.debug_mode = debug_mode
        self.log = log or (lambda msg: print(msg, flush=True))

    def run(self):
        bot_id, lobby_id = self.client.create_lobby(
            "ControlBot",
            preset=self.preset,
            min_players=2,
        )
        base = self.client.base_url
        self.log("")
        self.log("ControlBot is hosting a lobby. Join from your browser:")
        self.log(f"  {base}/")
        self.log("")
        self.log(f"  Lobby id: {lobby_id}")
        self.log(f"  Preset:   {self.preset}")
        self.log("")
        self.log("Enter your name, pick the ControlBot lobby from the list, then click Ready.")
        self.log("Waiting for an opponent to join…")

        seen_opponents = set()
        while True:
            members = _lobby_members(self.client, bot_id, lobby_id)
            opponents = _other_members(members, bot_id)
            for m in opponents:
                pid = m.get("player_id")
                if pid and pid not in seen_opponents:
                    seen_opponents.add(pid)
                    self.log(f"Opponent joined: {m.get('name', '?')}")
            if len(members) >= 2:
                break
            time.sleep(self.poll_interval)

        self.log("Opponent in lobby — ControlBot readying up. Click Ready in the browser when you are.")

        game_id = None
        while not game_id:
            status = self.client.lobby_status(bot_id)
            if status.get("in_game") and status.get("game_id"):
                game_id = status["game_id"]
                break
            try:
                resp = self.client.ready(bot_id, debug_mode=self.debug_mode)
                game_id = resp
            except Exception as e:
                # Game may have started while we were waiting (human readied first).
                status = self.client.lobby_status(bot_id)
                if status.get("in_game") and status.get("game_id"):
                    game_id = status["game_id"]
                    break
                raise e
            if not game_id:
                status = self.client.lobby_status(bot_id)
                game_id = status.get("game_id")
            if not game_id:
                time.sleep(self.poll_interval)

        self.log(f"Game started: {game_id}")
        self.log("ControlBot is playing. Use the browser to take your turns.")

        bot = ControlBot(client=self.client, poll_interval=self.poll_interval, log=self.log)
        final = bot.play_game(game_id, bot_id)
        self.log(f"Game over: {game_id}")
        return game_id, final
