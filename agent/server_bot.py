"""Play on a VCK Online server with any agent policy (random / greedy / mcts).

Host a lobby and wait for a human opponent:
  python -m agent.server_bot --policy mcts --host --preset base --name "MCTS Bot"

Join an existing lobby:
  python -m agent.server_bot --policy mcts --join <LOBBY_ID> --name "MCTS Bot"

Resume after restarting mid-game (session file written automatically):
  python -m agent.server_bot --policy mcts --resume
  python -m agent.server_bot --policy mcts --game-id <ID> --player-id <ID>
  python -m agent.server_bot --policy mcts --game-id <ID> --rejoin-code BLUE-FOX-42

Point at a local server with --base-url http://127.0.0.1:8000.

The loop uses engines.available_actions for move enumeration and, for greedy/mcts,
reconstructs a playable Game from each wire snapshot via agent.reconstruct so the
policy can search it.
"""

import argparse
import json
import time
from pathlib import Path

from agent.client import DEFAULT_BASE_URL, GameNotFoundError, IllegalActionError, VckoClient
from agent.move_summary import analyze_compare, format_compare_block, format_decision
from engines.available_actions import enumerate_actions
from agent.reconstruct import game_from_wire

DEFAULT_SESSION_PATH = Path("agent_session.json")


def _make_policy(name, iterations, workers=1):
    from agent.policies import GreedyPolicy, RandomPolicy

    if name == "random":
        return RandomPolicy()
    if name == "greedy":
        return GreedyPolicy()
    if name == "mcts":
        from agent.mcts import MCTSPolicy

        return MCTSPolicy(iterations=iterations, workers=workers)
    raise ValueError(f"unknown policy {name!r}")


def _needs_game_object(policy):
    return policy.name in ("greedy", "mcts")


def save_session(path, game_id, player_id, base_url, rejoin_code=None, extra=None):
    """Persist enough identity to resume after a process restart."""
    if not path:
        return
    path = Path(path)
    payload = {
        "game_id": game_id,
        "player_id": player_id,
        "base_url": base_url,
        "rejoin_code": rejoin_code,
        "saved_at": time.time(),
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_session(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no session file at {path}")
    data = json.loads(path.read_text())
    if not data.get("game_id") or not data.get("player_id"):
        raise ValueError(f"session file {path} missing game_id/player_id")
    return data


def clear_session(path):
    if not path:
        return
    path = Path(path)
    if path.is_file():
        path.unlink()


def _update_session_from_state(session_path, client, game_id, player_id, state, log):
    if not session_path:
        return
    code = state.get("my_rejoin_code")
    save_session(
        session_path,
        game_id,
        player_id,
        client.base_url,
        rejoin_code=code,
    )
    if code:
        log(f"session saved → {session_path} (rejoin code {code})")
    else:
        log(f"session saved → {session_path}")


def _choose_move(game, player_id, moves, policy, log, compare_greedy=False):
    """Pick a move and log a policy-specific decision summary."""
    if policy.name == "random":
        return policy.choose(game, None, player_id, moves)

    if compare_greedy and policy.name == "mcts":
        greedy_decision, mcts_decision = analyze_compare(game, player_id, moves, policy)
        for line in format_compare_block(greedy_decision, mcts_decision, game):
            log(line)
        return mcts_decision["chosen"]

    if hasattr(policy, "analyze"):
        decision = policy.analyze(game, player_id, moves)
        for line in format_decision(decision, game):
            log(line)
        return decision["chosen"]

    return policy.choose(game, None, player_id, moves)


def play_tick(client, game_id, player_id, state, policy, log, compare_greedy=False):
    """Take one action if any is available. Returns (new_state, acted)."""
    moves = enumerate_actions(state, player_id)
    if not moves:
        return state, False
    game = game_from_wire(state, player_id) if _needs_game_object(policy) else None
    remaining = list(moves)
    while remaining:
        move = _choose_move(game, player_id, remaining, policy, log, compare_greedy=compare_greedy) \
            if game is not None else policy.choose(None, None, player_id, remaining)
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


def play_until_over(client, game_id, player_id, policy, poll_interval=1.5, log=print,
                    session_path=None, compare_greedy=False):
    state = client.get_state(game_id, player_id)
    _update_session_from_state(session_path, client, game_id, player_id, state, log)
    log(f"playing game {game_id} as {player_id}")
    log(f"resume: python -m agent.server_bot --resume --session-file {session_path or DEFAULT_SESSION_PATH}")
    while (state.get("phase") or "").strip() != "game_over":
        tick_before = state.get("tick_id")
        try:
            state, acted = play_tick(
                client, game_id, player_id, state, policy, log,
                compare_greedy=compare_greedy,
            )
        except GameNotFoundError:
            log("game disappeared (server shutdown or cleanup)")
            clear_session(session_path)
            return state
        if session_path and state.get("my_rejoin_code"):
            save_session(
                session_path, game_id, player_id, client.base_url,
                rejoin_code=state.get("my_rejoin_code"),
            )
        if not acted and state.get("tick_id") == tick_before:
            time.sleep(poll_interval)
            state = client.get_state(game_id, player_id)
    log("game over")
    for row in (state.get("final_scores") or []):
        log(f"  #{row.get('rank')} {row.get('name')}: {row.get('total_vp')} VP")
    clear_session(session_path)
    return state


def host_and_play(client, policy, preset, name, poll_interval, log, session_path=None,
                  compare_greedy=False):
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
            return play_until_over(
                client, status["game_id"], bot_id, policy, poll_interval, log,
                session_path=session_path, compare_greedy=compare_greedy,
            )
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
    return play_until_over(
        client, game_id, bot_id, policy, poll_interval, log, session_path=session_path,
        compare_greedy=compare_greedy,
    )


def join_and_play(client, policy, lobby_id, name, poll_interval, log, session_path=None,
                  compare_greedy=False):
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
    return play_until_over(
        client, game_id, bot_id, policy, poll_interval, log, session_path=session_path,
        compare_greedy=compare_greedy,
    )


def resume_and_play(client, policy, game_id, player_id, poll_interval, log,
                    session_path=None, rejoin_code=None, compare_greedy=False):
    if rejoin_code and not player_id:
        game_id, player_id = client.rejoin(game_id, rejoin_code)
        log(f"rejoined via code → player_id={player_id}")
    if not game_id or not player_id:
        raise SystemExit("resume needs game_id and player_id (or rejoin_code)")
    try:
        return play_until_over(
            client, game_id, player_id, policy, poll_interval, log,
            session_path=session_path, compare_greedy=compare_greedy,
        )
    except GameNotFoundError:
        log(f"game {game_id} not found on server — clearing session")
        clear_session(session_path)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="mcts", choices=("random", "greedy", "mcts"))
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="MCTS root-parallel worker processes (1 = single-process search)",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--preset", default="base")
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--compare-greedy",
        action="store_true",
        help="MCTS only: rank with greedy too, show overlap/divergence, still play MCTS",
    )
    parser.add_argument("--poll-interval", type=float, default=1.5)
    parser.add_argument(
        "--session-file",
        default=str(DEFAULT_SESSION_PATH),
        help=f"where to save/load mid-game identity (default: {DEFAULT_SESSION_PATH})",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", action="store_true", help="host a lobby and wait for an opponent")
    group.add_argument("--join", metavar="LOBBY_ID", help="join an existing lobby")
    group.add_argument(
        "--resume",
        action="store_true",
        help="resume from --session-file after a mid-game restart",
    )
    group.add_argument(
        "--game-id",
        help="resume a specific game (requires --player-id and/or --rejoin-code)",
    )
    parser.add_argument("--player-id", default=None, help="with --game-id or --resume override")
    parser.add_argument("--rejoin-code", default=None, help="optional; recovers player_id via API")
    args = parser.parse_args()

    if args.game_id and not (args.player_id or args.rejoin_code):
        parser.error("--game-id requires --player-id and/or --rejoin-code")

    if args.compare_greedy and args.policy != "mcts":
        parser.error("--compare-greedy requires --policy mcts")

    client = VckoClient(base_url=args.base_url)
    policy = _make_policy(args.policy, args.iterations, workers=args.workers)
    name = args.name or f"{args.policy.upper()} Bot"
    log = lambda msg: print(msg, flush=True)
    session_path = args.session_file
    compare_greedy = args.compare_greedy
    if args.policy == "mcts" and args.workers > 1:
        log(f"MCTS: {args.iterations} iterations across {args.workers} workers")
    if compare_greedy:
        log("compare-greedy: running greedy analysis alongside MCTS (playing MCTS)")

    try:
        if args.host:
            host_and_play(
                client, policy, args.preset, name, args.poll_interval, log,
                session_path=session_path, compare_greedy=compare_greedy,
            )
        elif args.join:
            join_and_play(
                client, policy, args.join, name, args.poll_interval, log,
                session_path=session_path, compare_greedy=compare_greedy,
            )
        elif args.resume:
            try:
                sess = load_session(session_path)
            except (OSError, ValueError, json.JSONDecodeError) as e:
                raise SystemExit(f"cannot resume: {e}") from e
            if sess.get("base_url") and sess["base_url"].rstrip("/") != client.base_url:
                log(
                    f"warning: session base_url={sess['base_url']} "
                    f"but --base-url={client.base_url}"
                )
            resume_and_play(
                client,
                policy,
                args.game_id or sess["game_id"],
                args.player_id or sess["player_id"],
                args.poll_interval,
                log,
                session_path=session_path,
                rejoin_code=args.rejoin_code or sess.get("rejoin_code"),
                compare_greedy=compare_greedy,
            )
        else:
            resume_and_play(
                client,
                policy,
                args.game_id,
                args.player_id,
                args.poll_interval,
                log,
                session_path=session_path,
                rejoin_code=args.rejoin_code,
                compare_greedy=compare_greedy,
            )
    finally:
        close = getattr(policy, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
