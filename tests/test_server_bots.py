"""Server-side lobby bots: validation, lobby seating, and the turn driver."""

import asyncio
import unittest

import db_config
import server
from agent import fake_db
from server import CreateLobbyRequest, ReadyRequest

# Patch the DB connector only for THIS module's tests; a module-level install
# would leak into unittest discovery and un-skip the live-DB test classes.
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
    server.gamers.clear()


class ValidateBotsTests(unittest.TestCase):
    def test_valid_levels_normalized(self):
        self.assertEqual(server._validate_bots(["Hard", " easy "], "base"), ["hard", "easy"])

    def test_empty_and_none_ok(self):
        self.assertEqual(server._validate_bots(None, "base"), [])
        self.assertEqual(server._validate_bots([], "base"), [])
        self.assertEqual(server._validate_bots(["", None], "base"), [])

    def test_unknown_level_rejected(self):
        with self.assertRaises(Exception):
            server._validate_bots(["impossible"], "base")

    def test_draft_rejected(self):
        with self.assertRaises(Exception):
            server._validate_bots(["easy"], "draft")

    def test_cap(self):
        with self.assertRaises(Exception):
            server._validate_bots(["easy"] * 5, "base")


class LobbyBotSeatingTests(unittest.TestCase):
    def setUp(self):
        _reset_server_state()

    def _create(self, bots):
        return asyncio.run(server.create_lobby(CreateLobbyRequest(
            name="Human", preset="base", min_players=2, bots=bots,
        )))

    def test_bots_join_ready_and_flagged(self):
        payload = self._create(["hard", "easy"])
        lb = server.lobbies[payload["lobby_id"]]
        self.assertEqual(len(lb.members), 3)
        bots = [m for m in lb.members if getattr(m, "is_bot", False)]
        self.assertEqual({m.name for m in bots}, {"Hard Bot", "Easy Bot"})
        self.assertTrue(all(m.is_ready for m in bots))
        self.assertEqual(sorted(lb.bot_levels.values()), ["easy", "hard"])
        serialized = server._serialize_lobby(lb)
        self.assertEqual(
            sorted(m["is_bot"] for m in serialized["members"]), [False, True, True]
        )

    def test_duplicate_levels_get_distinct_names(self):
        payload = self._create(["easy", "easy"])
        lb = server.lobbies[payload["lobby_id"]]
        names = sorted(m.name for m in lb.members if getattr(m, "is_bot", False))
        self.assertEqual(names, ["Easy Bot", "Easy Bot 2"])

    def test_prune_keeps_bots_while_human_active(self):
        payload = self._create(["easy"])
        lb = server.lobbies[payload["lobby_id"]]
        for m in lb.members:
            if getattr(m, "is_bot", False):
                m.last_active_time = 0  # bots never ping
        server._prune_stale_lobbies()
        self.assertIn(payload["lobby_id"], server.lobbies)
        self.assertEqual(len(server.lobbies[payload["lobby_id"]].members), 2)

    def test_prune_deletes_bot_only_lobby(self):
        payload = self._create(["easy"])
        lb = server.lobbies[payload["lobby_id"]]
        for m in lb.members:
            m.last_active_time = 0 if not getattr(m, "is_bot", False) else m.last_active_time
        server._prune_stale_lobbies()
        self.assertNotIn(payload["lobby_id"], server.lobbies)


class BotTurnDriverTests(unittest.TestCase):
    def setUp(self):
        _reset_server_state()

    def _start_game_with_bot(self, level):
        async def _go():
            payload = await server.create_lobby(CreateLobbyRequest(
                name="Human", preset="base", min_players=2, bots=[level],
            ))
            await server.set_ready(ReadyRequest(player_id=payload["player_id"]))
            return payload["player_id"]
        human_id = asyncio.run(_go())
        self.assertEqual(len(server.games), 1)
        game_id, game = next(iter(server.games.items()))
        self.assertTrue(getattr(game, "bot_levels", None))
        return game_id, game, human_id

    def test_easy_bot_plays_full_game_with_random_human(self):
        import random

        from agent import bot_players
        from agent.headless import acting_player_ids, advance, legal_moves
        from agent.policies import RandomPolicy

        random.seed(7)
        game_id, game, human_id = self._start_game_with_bot("easy")
        human = RandomPolicy()

        async def _play():
            stuck = 0
            for _ in range(4000):
                if game.phase == "game_over":
                    return
                await server._run_bot_turns(game_id)
                if game.phase == "game_over":
                    return
                pending = None
                for pid in acting_player_ids(game):
                    if pid == human_id:
                        moves = legal_moves(game, pid)
                        if moves:
                            pending = (pid, moves)
                            break
                if pending is None:
                    if not game.advance_tick():
                        stuck += 1
                        if stuck > 10:
                            self.fail(
                                f"game stalled: phase={game.phase!r} "
                                f"required={game.action_required!r}"
                            )
                        continue
                    advance(game)
                    continue
                stuck = 0
                pid, moves = pending
                decision = {"chosen": human.choose(game, None, pid, moves), "candidates": []}
                bot_players.apply_bot_decision(game, pid, moves, decision)
            self.fail("game did not finish in step budget")

        asyncio.run(_play())
        self.assertEqual(game.phase, "game_over")
        self.assertIsNotNone(game.final_scores)

    def test_hard_bot_takes_a_decision(self):
        from agent import bot_players

        original = bot_players.HARD_BOT_ITERATIONS
        original_workers = bot_players.HARD_BOT_WORKERS
        bot_players.HARD_BOT_ITERATIONS = 8  # keep the unit test fast
        bot_players.HARD_BOT_WORKERS = 1  # no process pool in unit tests
        try:
            game_id, game, human_id = self._start_game_with_bot("hard")
            log_before = len(game.game_log or [])
            asyncio.run(server._run_bot_turns(game_id))
            bot_pid = next(iter(game.bot_levels))
            pending = bot_players.pending_bot_decision(game, game.bot_levels)
            self.assertTrue(
                pending is None or pending[0] != bot_pid or len(game.game_log or []) > log_before,
                "hard bot neither acted nor cleared its pending decision",
            )
        finally:
            bot_players.HARD_BOT_ITERATIONS = original
            bot_players.HARD_BOT_WORKERS = original_workers


if __name__ == "__main__":
    unittest.main()
