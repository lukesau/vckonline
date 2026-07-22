"""Play on a VCK Online server with any agent policy (random / greedy / mcts).

Host a lobby and wait for a human opponent:
  python -m agent.server_bot --policy mcts --host --preset base1 --name "MCTS Bot"

Join an existing lobby:
  python -m agent.server_bot --policy mcts --join <LOBBY_ID> --name "MCTS Bot"

Point at a local server with --base-url http://127.0.0.1:8000.

The loop mirrors bots/loop.py but uses agent.moves.enumerate_moves (engine-exact
costs and prompt verbs) and, for greedy/mcts, reconstructs a playable Game from
each wire snapshot via agent.reconstruct so the policy can search it.
"""

import argparse
import time

from bots.client import DEFAULT_BASE_URL, GameNotFoundError, IllegalActionError, VckoClient

from agent.moves import enumerate_moves
from agent.reconstruct import game_from_wire


def _make_policy(name, iterations):
    from agent.policies import GreedyPolicy, RandomPolicy

    if name == "random":
        return RandomPolicy()
    if name == "greedy":
        return GreedyPolicy()
    if name == "mcts":
        from agent.mcts import MCTSPolicy

        return MCTSPolicy(iterations=iterations)
    if name == "mcts-nn":
        from agent.mcts import MCTSPolicy
        from agent.value_net import DEFAULT_MODEL_PATH

        policy = MCTSPolicy(iterations=iterations, value_path=DEFAULT_MODEL_PATH)
        policy.name = "mcts-nn"
        return policy
    raise ValueError(f"unknown policy {name!r}")


def _needs_game_object(policy):
    return policy.name in ("greedy", "mcts", "mcts-nn")


def play_tick(client, game_id, player_id, state, policy, log):
    """Take one action if any is available. Returns (new_state, acted)."""
    moves = enumerate_moves(state, player_id)
    if not moves:
        return state, False
    game = game_from_wire(state, player_id) if _needs_game_object(policy) else None
    remaining = list(moves)
    while remaining:
        move = policy.choose(game, None, player_id, remaining) if game is not None \
            else policy.choose(None, None, player_id, remaining)
        if move is None:
            return state, False
        remaining.remove(move)
        try:
            new_state = client.execute_move(game_id, move)
            slim = {k: v for k, v in move.items() if k not in ("player_id",) and not k.startswith("_")}
            log(f"played {slim}")
            return new_state, True
        except IllegalActionError as e:
            log(f"rejected {move.get('action_type')}: {e}")
            continue
    return state, False


def play_until_over(client, game_id, player_id, policy, poll_interval=1.5, log=print):
    state = client.get_state(game_id, player_id)
    while (state.get("phase") or "").strip() != "game_over":
        tick_before = state.get("tick_id")
        try:
            state, acted = play_tick(client, game_id, player_id, state, policy, log)
        except GameNotFoundError:
            log("game disappeared (server shutdown or cleanup)")
            return state
        if not acted and state.get("tick_id") == tick_before:
            time.sleep(poll_interval)
            state = client.get_state(game_id, player_id)
    log("game over")
    for row in (state.get("final_scores") or []):
        log(f"  #{row.get('rank')} {row.get('name')}: {row.get('total_vp')} VP")
    return state


def host_and_play(client, policy, preset, name, poll_interval, log):
    bot_id, lobby_id = client.create_lobby(name, preset=preset, min_players=2)
    log(f"Hosting lobby {lobby_id} (preset {preset}) at {client.base_url}")
    log("Join from your browser, then click Ready. Waiting for an opponent…")
    while True:
        status = client.lobby_status(bot_id)
        members = []
        for lob in status.get("lobbies") or []:
            if lob.get("lobby_id") == lobby_id:
                members = lob.get("members") or []
        if len(members) >= 2:
            break
        if status.get("in_game") and status.get("game_id"):
            return play_until_over(client, status["game_id"], bot_id, policy, poll_interval, log)
        time.sleep(poll_interval)
    log("Opponent joined — readying up.")
    game_id = None
    while not game_id:
        status = client.lobby_status(bot_id)
        if status.get("in_game") and status.get("game_id"):
            game_id = status["game_id"]
            break
        try:
            game_id = client.ready(bot_id)
        except Exception:
            status = client.lobby_status(bot_id)
            game_id = status.get("game_id")
        if not game_id:
            time.sleep(poll_interval)
    log(f"Game started: {game_id}")
    return play_until_over(client, game_id, bot_id, policy, poll_interval, log)


def join_and_play(client, policy, lobby_id, name, poll_interval, log):
    bot_id, _ = client.join_lobby(name, lobby_id)
    log(f"Joined lobby {lobby_id} as {name}; readying up.")
    game_id = None
    while not game_id:
        status = client.lobby_status(bot_id)
        if status.get("in_game") and status.get("game_id"):
            game_id = status["game_id"]
            break
        try:
            game_id = client.ready(bot_id)
        except Exception:
            status = client.lobby_status(bot_id)
            game_id = status.get("game_id")
        if not game_id:
            time.sleep(poll_interval)
    log(f"Game started: {game_id}")
    return play_until_over(client, game_id, bot_id, policy, poll_interval, log)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="mcts",
                        choices=("random", "greedy", "mcts", "mcts-nn"))
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--preset", default="base1")
    parser.add_argument("--name", default=None)
    parser.add_argument("--poll-interval", type=float, default=1.5)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", action="store_true", help="host a lobby and wait for an opponent")
    group.add_argument("--join", metavar="LOBBY_ID", help="join an existing lobby")
    args = parser.parse_args()

    client = VckoClient(base_url=args.base_url)
    policy = _make_policy(args.policy, args.iterations)
    name = args.name or f"{args.policy.upper()} Bot"
    log = lambda msg: print(msg, flush=True)

    if args.host:
        host_and_play(client, policy, args.preset, name, args.poll_interval, log)
    else:
        join_and_play(client, policy, args.join, name, args.poll_interval, log)


if __name__ == "__main__":
    main()
