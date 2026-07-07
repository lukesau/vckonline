"""Orchestrate a two-bot match on the hosted VCKO server."""

import threading
import time

from bots.client import VckoClient
from bots.control_bot import ControlBot
from bots.game_logic_bot import GameLogicBot


def _winner_line(state):
    players = state.get("player_list") or []
    if not players:
        return "Game over (no players in state)."
    ranked = sorted(
        players,
        key=lambda p: (
            -(int(p.get("victory_score") or 0)),
            -(int(p.get("gold_score") or 0) + int(p.get("strength_score") or 0) + int(p.get("magic_score") or 0)),
        ),
    )
    lines = []
    for p in ranked:
        lines.append(
            f"  {p.get('name', '?')}: {int(p.get('victory_score') or 0)} VP "
            f"(G{int(p.get('gold_score') or 0)} S{int(p.get('strength_score') or 0)} "
            f"M{int(p.get('magic_score') or 0)})"
        )
    return "Final scores:\n" + "\n".join(lines)


class MatchRunner:
    def __init__(self, client=None, preset="base", poll_interval=1.5, debug_mode=True, log=None):
        self.client = client or VckoClient()
        self.preset = preset
        self.poll_interval = poll_interval
        self.debug_mode = debug_mode
        self.log = log or (lambda msg: print(msg, flush=True))

    def run(self):
        control_id, lobby_id = self.client.create_lobby(
            "ControlBot",
            preset=self.preset,
            min_players=2,
        )
        logic_id, _ = self.client.join_lobby("GameLogicBot", lobby_id)
        self.log(f"Lobby {lobby_id}: control={control_id[:8]}… logic={logic_id[:8]}…")

        game_id = None
        while not game_id:
            self.client.ready(control_id, debug_mode=self.debug_mode)
            resp = self.client.ready(logic_id, debug_mode=self.debug_mode)
            game_id = resp
            if not game_id:
                status = self.client.lobby_status(control_id)
                game_id = status.get("game_id")
            if not game_id:
                time.sleep(self.poll_interval)

        self.log(f"Game started: {game_id}")

        results = {}
        errors = {}

        def _run_bot(name, bot_cls, player_id):
            try:
                bot = bot_cls(client=self.client, poll_interval=self.poll_interval, log=self.log)
                results[player_id] = bot.play_game(game_id, player_id)
            except Exception as e:
                errors[player_id] = e
                self.log(f"[{name}] error: {e}")

        threads = [
            threading.Thread(target=_run_bot, args=("ControlBot", ControlBot, control_id), daemon=True),
            threading.Thread(target=_run_bot, args=("GameLogicBot", GameLogicBot, logic_id), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            raise RuntimeError(f"Bot errors: {errors}")

        final = results.get(control_id) or results.get(logic_id) or self.client.get_state(game_id, control_id)
        self.log(_winner_line(final))
        return game_id, final
