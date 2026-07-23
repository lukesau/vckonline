"""Hint endpoint: bot recommendation for the requesting player's decision."""

import asyncio
import unittest

import db_config
import server
from agent import fake_db
from server import CreateLobbyRequest, ReadyRequest

_real_connect = db_config.connect


def setUpModule():
    fake_db.install()


def tearDownModule():
    db_config.connect = _real_connect


def _reset_server_state():
    server.lobbies.clear()
    server.games.clear()
    server.game_histories.clear()
    server._bot_policies.clear()
    server._hint_cache.clear()
    server.gamers.clear()


class HintEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_server_state()
        from agent import hints

        self._orig_iters = hints.HINT_ITERATIONS
        hints.HINT_ITERATIONS = 8  # keep unit tests fast

    def tearDown(self):
        from agent import hints

        hints.HINT_ITERATIONS = self._orig_iters

    def _start_two_human_game(self):
        async def _go():
            a = await server.create_lobby(CreateLobbyRequest(
                name="Alice", preset="base", min_players=2,
            ))
            from server import JoinLobbyRequest

            b = await server.join_lobby(JoinLobbyRequest(
                name="Bob", lobby_id=a["lobby_id"],
            ))
            await server.set_ready(ReadyRequest(player_id=a["player_id"]))
            await server.set_ready(ReadyRequest(player_id=b["player_id"]))
            return a["player_id"], b["player_id"]
        pid_a, pid_b = asyncio.run(_go())
        game_id, game = next(iter(server.games.items()))
        return game_id, game, pid_a, pid_b

    def test_hint_for_pending_player(self):
        from agent.hints import player_pending_moves

        game_id, game, pid_a, pid_b = self._start_two_human_game()
        # At game start both players owe the concurrent duke choice.
        pending_pid = next(
            pid for pid in (pid_a, pid_b) if player_pending_moves(game, pid) is not None
        )
        result = asyncio.run(server.get_game_hint(game_id, pending_pid))
        self.assertTrue(result.get("hint"))
        self.assertIsInstance(result["hint"], str)
        # Hints must not mutate the live game.
        self.assertTrue(player_pending_moves(game, pending_pid) is not None)

    def test_hint_rejected_for_player_without_decision(self):
        from agent.headless import legal_moves

        game_id, game, pid_a, pid_b = self._start_two_human_game()
        # Resolve the duke gate so exactly one player (the active one) owes
        # a standard action, then ask for a hint as the OTHER player.
        for pid in (pid_a, pid_b):
            moves = legal_moves(game, pid)
            if moves:
                from agent.bot_players import apply_bot_decision

                apply_bot_decision(game, pid, moves, {"chosen": moves[0], "candidates": []})
        active = game.action_required.get("id")
        other = pid_b if active == pid_a else pid_a
        with self.assertRaises(Exception):
            asyncio.run(server.get_game_hint(game_id, other))

    def test_hint_rejected_for_non_player(self):
        game_id, game, pid_a, pid_b = self._start_two_human_game()
        with self.assertRaises(Exception):
            asyncio.run(server.get_game_hint(game_id, "not-a-player"))

    def test_hints_disabled_lobby_option(self):
        from fastapi import HTTPException

        async def _go():
            a = await server.create_lobby(CreateLobbyRequest(
                name="Alice", preset="base", min_players=2, hints_enabled=False,
            ))
            from server import JoinLobbyRequest

            b = await server.join_lobby(JoinLobbyRequest(name="Bob", lobby_id=a["lobby_id"]))
            await server.set_ready(ReadyRequest(player_id=a["player_id"]))
            await server.set_ready(ReadyRequest(player_id=b["player_id"]))
            return a["player_id"]
        pid_a = asyncio.run(_go())
        game_id, game = next(iter(server.games.items()))
        self.assertFalse(game.hints_enabled)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.get_game_hint(game_id, pid_a))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_hints_enabled_by_default_and_in_state_payload(self):
        game_id, game, pid_a, pid_b = self._start_two_human_game()
        self.assertTrue(getattr(game, "hints_enabled", None))
        state = server._serialize_game_for_player(game, pid_a)
        self.assertTrue(state["hints_enabled"])
        game.hints_enabled = False
        state = server._serialize_game_for_player(game, pid_a)
        self.assertFalse(state["hints_enabled"])

    def test_hint_cache_reused_for_same_state(self):
        from agent.hints import player_pending_moves

        game_id, game, pid_a, pid_b = self._start_two_human_game()
        pending_pid = next(
            pid for pid in (pid_a, pid_b) if player_pending_moves(game, pid) is not None
        )

        async def _two_hints():
            first = await server.get_game_hint(game_id, pending_pid)
            cached_future = server._hint_cache[game_id]["future"]
            second = await server.get_game_hint(game_id, pending_pid)
            return first, second, cached_future is server._hint_cache[game_id]["future"]

        first, second, same_future = asyncio.run(_two_hints())
        self.assertEqual(first["hint"], second["hint"])
        self.assertTrue(same_future, "same-state hint should reuse the cached computation")


class HintLabelTests(unittest.TestCase):
    def test_pretty_label_capitalizes(self):
        from agent.hints import pretty_label

        move = {"player_id": "p1", "action_type": "take_resource", "resource": "m"}
        self.assertEqual(pretty_label(move), "Take magic")


if __name__ == "__main__":
    unittest.main()
