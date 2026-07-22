"""Read-only move advisor for a live human game on the VCK Online server.

Polls your seat's wire state, runs greedy + MCTS analysis, and prints ranked
recommendations — never submits actions.

  python -m agent.recommend \\
    --url 'https://vcko.lukesau.com/?game_id=...&player_id=...'

Or pass ids directly (optionally overriding the server host):

  python -m agent.recommend --game-id ... --player-id ... --base-url http://127.0.0.1:8000
"""

import argparse
import time

from agent.client import DEFAULT_BASE_URL, GameNotFoundError, VckoClient
from agent.game_url import parse_game_url
from agent.move_summary import analyze_compare, format_recommendation_block, move_key
from agent.mcts import MCTSPolicy
from agent.reconstruct import game_from_wire
from engines.available_actions import enumerate_actions


def _player_row(state, player_id):
    for row in state.get("player_list") or []:
        if row.get("player_id") == player_id:
            return row
    return {}


def _context_line(state, player_id):
    phase = (state.get("phase") or "?").strip()
    turn = state.get("turn_number") or "?"
    row = _player_row(state, player_id)
    name = row.get("name") or player_id
    vp = row.get("victory_score")
    actions = state.get("actions_remaining")
    req = state.get("action_required") or {}
    prompt = (req.get("action") or "").strip()
    bits = [f"turn {turn}", f"phase {phase}", name]
    if vp is not None:
        bits.append(f"{vp} VP")
    if actions is not None and phase == "action":
        bits.append(f"{actions} action(s) left")
    if prompt:
        bits.append(f"prompt={prompt}")
    return "context: " + ", ".join(bits)


def _decision_fingerprint(state, moves):
    tick = state.get("tick_id")
    keys = tuple(sorted(move_key(m) for m in moves))
    req = state.get("action_required") or {}
    return (tick, keys, (req.get("action") or "").strip())


def recommend_once(client, game_id, player_id, mcts_policy, log, top_n=5):
    """Fetch state, analyze if we have moves, print recommendations. Returns True if printed."""
    state = client.get_state(game_id, player_id)
    phase = (state.get("phase") or "").strip()
    if phase == "game_over":
        log("game over")
        for row in (state.get("final_scores") or []):
            log(f"  #{row.get('rank')} {row.get('name')}: {row.get('total_vp')} VP")
        return False

    moves = enumerate_actions(state, player_id)
    if not moves:
        return False

    game = game_from_wire(state, player_id)
    greedy_decision, mcts_decision = analyze_compare(game, player_id, moves, mcts_policy)
    log("")
    log(_context_line(state, player_id))
    log(f"legal moves: {len(moves)}")
    for line in format_recommendation_block(greedy_decision, mcts_decision, game, top_n=top_n):
        log(line)
    return True


def run_advisor(client, game_id, player_id, mcts_policy, poll_interval, log, top_n=5, once=False):
    log(f"advising game {game_id} as {player_id} at {client.base_url}")
    log("read-only — will not submit moves (Ctrl-C to stop)")
    last_fp = None
    try:
        while True:
            try:
                state = client.get_state(game_id, player_id)
            except GameNotFoundError:
                log("game not found on server")
                return

            phase = (state.get("phase") or "").strip()
            if phase == "game_over":
                log("game over")
                for row in (state.get("final_scores") or []):
                    log(f"  #{row.get('rank')} {row.get('name')}: {row.get('total_vp')} VP")
                return

            moves = enumerate_actions(state, player_id)
            if not moves:
                last_fp = None
                time.sleep(poll_interval)
                continue

            fp = _decision_fingerprint(state, moves)
            if fp == last_fp:
                time.sleep(poll_interval)
                continue
            last_fp = fp

            game = game_from_wire(state, player_id)
            greedy_decision, mcts_decision = analyze_compare(game, player_id, moves, mcts_policy)
            log("")
            log(_context_line(state, player_id))
            log(f"legal moves: {len(moves)}")
            for line in format_recommendation_block(
                greedy_decision, mcts_decision, game, top_n=top_n
            ):
                log(line)

            if once:
                return
            time.sleep(poll_interval)
    finally:
        close = getattr(mcts_policy, "close", None)
        if callable(close):
            close()


def main():
    parser = argparse.ArgumentParser(
        description="Read-only move advisor for a live VCK Online game",
    )
    parser.add_argument(
        "--url",
        help="browser game URL with game_id and player_id query params",
    )
    parser.add_argument("--game-id", help="game id (alternative to --url)")
    parser.add_argument("--player-id", help="your player id (alternative to --url)")
    parser.add_argument("--base-url", default=None, help=f"API host (default: from --url or {DEFAULT_BASE_URL})")
    parser.add_argument("--iterations", type=int, default=200, help="MCTS iterations per recommendation")
    parser.add_argument("--workers", type=int, default=1, help="MCTS root-parallel workers")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="seconds between state polls")
    parser.add_argument("--top", type=int, default=5, help="number of ranked moves to show per policy")
    parser.add_argument(
        "--once",
        action="store_true",
        help="analyze the current decision once and exit (no polling loop)",
    )
    args = parser.parse_args()

    base_url = args.base_url
    game_id = args.game_id
    player_id = args.player_id

    if args.url:
        url_base, url_game_id, url_player_id = parse_game_url(args.url)
        base_url = base_url or url_base
        game_id = game_id or url_game_id
        player_id = player_id or url_player_id
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    if not game_id or not player_id:
        parser.error("provide --url or both --game-id and --player-id")

    log = lambda msg: print(msg, flush=True)
    if args.workers > 1:
        log(f"MCTS: {args.iterations} iterations × {args.workers} workers")

    client = VckoClient(base_url=base_url)
    mcts_policy = MCTSPolicy(iterations=args.iterations, workers=args.workers)

    if args.once:
        try:
            printed = recommend_once(
                client, game_id, player_id, mcts_policy, log, top_n=args.top
            )
            if not printed:
                log("no decision available for your seat right now")
        finally:
            close = getattr(mcts_policy, "close", None)
            if callable(close):
                close()
        return

    run_advisor(
        client,
        game_id,
        player_id,
        mcts_policy,
        args.poll_interval,
        log,
        top_n=args.top,
        once=False,
    )


if __name__ == "__main__":
    main()
