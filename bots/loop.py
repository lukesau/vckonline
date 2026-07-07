"""Bot play loop — poll state, enumerate moves, execute."""

import random
import time

from bots.client import IllegalActionError, VckoClient
from bots.legal_moves import enumerate_actions


def play_tick(client, game_id, player_id, state, strategy):
    """Try one action if it is this bot's turn. Returns updated state."""
    actions = enumerate_actions(state, player_id)
    if not actions:
        return state

    pool = list(actions)
    random.shuffle(pool)
    last_error = None
    while pool:
        move = strategy.pick(pool) if strategy else pool[0]
        try:
            return client.execute_move(game_id, move)
        except IllegalActionError as e:
            last_error = e
            pool = [candidate for candidate in pool if candidate is not move]
            continue

    if last_error:
        raise last_error
    return state


def play_until_over(client, game_id, player_id, strategy, poll_interval=1.5, log=None):
    """Run the bot until phase == game_over. Returns final state."""
    log = log or (lambda msg: None)
    state = client.get_state(game_id, player_id)
    while (state.get("phase") or "").strip() != "game_over":
        before_tick = state.get("tick_id")
        try:
            state = play_tick(client, game_id, player_id, state, strategy) or state
        except IllegalActionError as e:
            log(f"[{player_id[:8]}] illegal action after retries: {e}")
        if state.get("tick_id") == before_tick:
            time.sleep(poll_interval)
            state = client.get_state(game_id, player_id)
    return state


class BotRunner:
    def __init__(self, client=None, strategy=None, poll_interval=1.5, log=None):
        self.client = client or VckoClient()
        self.strategy = strategy
        self.poll_interval = poll_interval
        self.log = log or (lambda msg: None)

    def play_game(self, game_id, player_id):
        return play_until_over(
            self.client,
            game_id,
            player_id,
            self.strategy,
            poll_interval=self.poll_interval,
            log=self.log,
        )
