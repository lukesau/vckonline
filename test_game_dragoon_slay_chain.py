"""End-to-end interaction test for Citizen #37 Dragoon's on-turn "slay" payout.

Dragoon's `special_payout_on_turn = "slay"` queues a may-slay prompt during
harvest. This test drives the engine through a 3-deep chain of triggered
slays + activations, each opening a prompt that the player resolves:

  1. Player rolls 9; Dragoon's on-turn payout fires (+2 magic) and queues a
     may-slay prompt at end of harvest. Source label: "Dragoon".
  2. Player slays Monster #84 Snow Queen. Special reward `<domains>` opens a
     "grant_domain_reward" prompt (free domain from the center).
  3. Player picks Domain #11 Eye of Asteraten. Its activation effect is
     `s 5 + slay`: applies +5 strength immediately AND queues a fresh may-slay
     prompt (the bare `slay` leg routes through `pending_harvest_slays`
     because we're in harvest phase). Source label: "Eye of Asteraten".
  4. Player slays Monster #101 Gnolls. Special reward `choose <citizens>`
     opens a "special_payout_choose" prompt over the accessible board
     citizens. Player picks one citizen and acquires it.
  5. After the citizen pick, the engine drains the remaining post-slay
     resume and finalizes harvest, transitioning into the action phase.

Card data is read live from the DB (vckonline@127.0.0.1:3306, SSH-tunneled —
see `docs/database.md`) so the test exercises whatever the canonical
special_reward / activation_effect strings are right now. If any of the four
cards change shape, the test loud-fails at fixture load and the regression
is unambiguous.

The test loads ONLY the four cards it needs into the grids (single-card
stacks). Citizen rows on the board are also DB-driven so the gnolls-choice
prompt sees real candidates.
"""

import os
import sys
import unittest

import mariadb

from cards import Citizen, Domain, Monster
from game import Game
from game_models import Player


DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

DRAGOON_ID = 37
SNOW_QUEEN_ID = 84
EYE_OF_ASTERATEN_ID = 11
GNOLLS_ID = 101


def _fetch_one(cur, sql, params):
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"DB row not found: {sql} {params}")
    return row


def _build_citizen_from_row(row):
    c = Citizen(
        citizen_id=row["id_citizens"],
        name=row["name"],
        gold_cost=row["gold_cost"],
        roll_match1=row["roll_match1"],
        roll_match2=row["roll_match2"],
        shadow_count=row["shadow_count"],
        holy_count=row["holy_count"],
        soldier_count=row["soldier_count"],
        worker_count=row["worker_count"],
        gold_payout_on_turn=row["gold_payout_on_turn"],
        gold_payout_off_turn=row["gold_payout_off_turn"],
        strength_payout_on_turn=row["strength_payout_on_turn"],
        strength_payout_off_turn=row["strength_payout_off_turn"],
        magic_payout_on_turn=row["magic_payout_on_turn"],
        magic_payout_off_turn=row["magic_payout_off_turn"],
        vp_payout_on_turn=row["vp_payout_on_turn"],
        vp_payout_off_turn=row["vp_payout_off_turn"],
        has_special_payout_on_turn=bool(row["has_special_payout_on_turn"]),
        has_special_payout_off_turn=bool(row["has_special_payout_off_turn"]),
        special_payout_on_turn=row["special_payout_on_turn"] or "",
        special_payout_off_turn=row["special_payout_off_turn"] or "",
        special_citizen=bool(row["special_citizen"]),
        expansion=row["expansion"],
    )
    c.toggle_visibility(True)
    c.toggle_accessibility(True)
    return c


def _build_monster_from_row(row):
    m = Monster(
        monster_id=row["id_monsters"],
        name=row["name"],
        area=row["area"],
        monster_type=row["monster_type"],
        order=row["monster_order"],
        strength_cost=row["strength_cost"],
        magic_cost=row["magic_cost"],
        vp_reward=row["vp_reward"],
        gold_reward=row["gold_reward"],
        strength_reward=row["strength_reward"],
        magic_reward=row["magic_reward"],
        has_special_reward=bool(row["has_special_reward"]),
        special_reward=row["special_reward"] or "",
        has_special_cost=bool(row["has_special_cost"]) if row["has_special_cost"] is not None else False,
        special_cost=row["special_cost"] or "",
        is_extra=bool(row["is_extra"]) if row["is_extra"] is not None else False,
        expansion=row["expansion"],
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def _build_domain_from_row(row):
    d = Domain(
        domain_id=row["id_domains"],
        name=row["name"],
        gold_cost=row["gold_cost"],
        shadow_count=row["shadow_count"],
        holy_count=row["holy_count"],
        soldier_count=row["soldier_count"],
        worker_count=row["worker_count"],
        vp_reward=row["vp_reward"],
        has_activation_effect=bool(row["has_activation_effect"]),
        has_passive_effect=bool(row["has_passive_effect"]),
        passive_effect=row["passive_effect"] or "",
        activation_effect=row["activation_effect"] or "",
        text=row["effect_text"] or "",
        expansion=row["expansion"],
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def _db_available():
    """Quick connect attempt to decide whether to skip vs hard-fail."""
    try:
        conn = mariadb.connect(**DB_CONFIG, connect_timeout=2)
        conn.close()
        return True
    except mariadb.Error:
        return False


@unittest.skipUnless(
    _db_available(),
    "DB at 127.0.0.1:3306 (vckonline) is required. Start the SSH tunnel: "
    "ssh -L 3306:localhost:3306 lukesau.com",
)
class DragoonSlayChainInteractionTests(unittest.TestCase):
    """Drive the Dragoon -> Snow Queen -> Eye of Asteraten -> Gnolls chain.

    The single test method walks the whole sequence and asserts state at
    every prompt boundary. We keep it one test rather than splitting per
    stage because the chain is stateful: tearing it apart would force every
    smaller test to re-walk the prior stages, and any divergence inside
    those re-walks would mislead about where the real break is.
    """

    @classmethod
    def setUpClass(cls):
        cls.conn = mariadb.connect(**DB_CONFIG)
        cur = cls.conn.cursor(dictionary=True)
        cls.dragoon_row = _fetch_one(
            cur, "SELECT * FROM citizens WHERE id_citizens = ?", (DRAGOON_ID,)
        )
        cls.snow_queen_row = _fetch_one(
            cur, "SELECT * FROM monsters WHERE id_monsters = ?", (SNOW_QUEEN_ID,)
        )
        cls.eye_of_asteraten_row = _fetch_one(
            cur, "SELECT * FROM domains WHERE id_domains = ?", (EYE_OF_ASTERATEN_ID,)
        )
        cls.gnolls_row = _fetch_one(
            cur, "SELECT * FROM monsters WHERE id_monsters = ?", (GNOLLS_ID,)
        )
        # A handful of buildable citizens for the gnolls-choice prompt to
        # range over. Filtering out the Dragoon row keeps the choose-citizens
        # list distinct from the citizen the player already owns.
        cur.execute(
            "SELECT * FROM citizens WHERE id_citizens != ? "
            "AND (special_citizen IS NULL OR special_citizen = 0) "
            "ORDER BY id_citizens LIMIT 4",
            (DRAGOON_ID,),
        )
        cls.board_citizen_rows = cur.fetchall()
        cur.close()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        except Exception:
            pass

    def _fresh_dragoon(self):
        return _build_citizen_from_row(self.dragoon_row)

    def _fresh_snow_queen(self):
        return _build_monster_from_row(self.snow_queen_row)

    def _fresh_eye_of_asteraten(self):
        return _build_domain_from_row(self.eye_of_asteraten_row)

    def _fresh_gnolls(self):
        return _build_monster_from_row(self.gnolls_row)

    def _fresh_board_citizens(self):
        return [_build_citizen_from_row(r) for r in self.board_citizen_rows]

    def _make_game(self):
        """Build the smallest game state that exercises the full chain.

        - 1 player with the Dragoon already on their tableau and plenty of
          resources to pay every cost in the chain (Snow Queen 12s+5m,
          Gnolls 9s).
        - Two single-card monster stacks (Snow Queen + Gnolls), one domain
          stack (Eye of Asteraten), and four citizen stacks (real DB rows
          so the gnolls-choice prompt has real options to render).
        - Phase=harvest with harvest bookkeeping reset so the first
          advance_tick fires the harvest scan and Dragoon's payouts.
        """
        p1 = Player("p1", "Player 1")
        p1.gold_score = 0
        p1.strength_score = 21      # 12 (Snow Queen) + 9 (Gnolls)
        p1.magic_score = 5          # 5 (Snow Queen)
        p1.victory_score = 0
        p1.owned_citizens.append(self._fresh_dragoon())

        monster_grid = [
            [self._fresh_snow_queen()],
            [self._fresh_gnolls()],
        ]
        citizen_grid = [[c] for c in self._fresh_board_citizens()]
        domain_grid = [[self._fresh_eye_of_asteraten()]]

        game = Game({
            "game_id": "test-game",
            "player_list": [p1],
            "monster_grid": monster_grid,
            "monster_stack_areas": [
                self.snow_queen_row["area"],
                self.gnolls_row["area"],
            ],
            "citizen_grid": citizen_grid,
            "domain_grid": domain_grid,
            "die_one": 4,
            "die_two": 5,
            "die_sum": 9,
            "exhausted_count": 0,
            "exhausted_stack": [],
            "effects": {},
            "action_required": {"id": "test-game", "action": ""},
            "game_log": [],
            "turn_index": 0,
            "phase": "harvest",
        })
        return game, p1

    def _option_index_by(self, options, key, value):
        """Return the 1-based prompt index whose option dict has options[i][key]==value.

        The engine's choose / choose_monster_slay / grant_domain prompts all
        emit options as ordered lists; the player picks "<verb> N" with N as
        the 1-based position. We never want to assume an ordering — every
        stage looks up by stable ID.
        """
        for i, opt in enumerate(options):
            if opt.get(key) == value:
                return i + 1
        raise AssertionError(
            f"No option with {key}={value!r} in options={options}"
        )

    def test_dragoon_slay_chain_through_three_prompts(self):
        game, player = self._make_game()
        self.assertEqual(game.phase, "harvest")
        self.assertFalse(game.harvest_processed)

        # ----- Stage 0: kick off harvest -----
        # advance_tick should: pay Dragoon's flat magic (+2), queue the
        # `slay` special, then drain the queue into a `choose_monster_slay`
        # prompt labelled "Dragoon".
        progressed = game.advance_tick()
        self.assertTrue(progressed)
        self.assertEqual(game.phase, "harvest")
        self.assertEqual(game.action_required["action"], "choose_monster_slay",
            f"expected may-slay prompt after Dragoon's slay queued; got {game.action_required!r}")
        self.assertEqual(game.action_required["id"], player.player_id)
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "immediate_slay")
        self.assertEqual(prc.get("stage"), "pick_monster")
        self.assertEqual(prc.get("source_label"), "Dragoon",
            "may-slay prompt must be tagged with the Dragoon source label")
        self.assertEqual(prc.get("resume_kind"), "harvest_pending_slay",
            "harvest-queued slays must resume into _drain_pending_harvest_slays")
        # Dragoon paid its flat +2 magic before queuing the slay.
        self.assertEqual(player.magic_score, 5 + 2,
            "Dragoon's on-turn magic_payout=2 should have applied before the slay queued")
        # No resources were deducted yet — slay payment is collected at
        # stage 2 (pay_for_slay).
        self.assertEqual(player.strength_score, 21)
        self.assertEqual(player.gold_score, 0)

        # Options should contain both monsters (Snow Queen, Gnolls).
        options = list(prc.get("options") or [])
        monster_ids = {opt.get("monster_id") for opt in options}
        self.assertEqual(monster_ids, {SNOW_QUEEN_ID, GNOLLS_ID})

        # ----- Stage 1: pick Snow Queen -----
        idx = self._option_index_by(options, "monster_id", SNOW_QUEEN_ID)
        game.act_on_required_action(player.player_id, f"choose_monster_slay {idx}")
        self.assertEqual(game.action_required["action"], "slay_monster_payment",
            "picking the monster must advance to the pay_for_slay stage")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("monster_id"), SNOW_QUEEN_ID)
        self.assertEqual(prc.get("strength_cost"), 12)
        self.assertEqual(prc.get("magic_cost"), 5)
        self.assertEqual(prc.get("gold_cost"), 0)

        # ----- Stage 2: pay & slay Snow Queen -----
        # Snow Queen's special_reward is `<domains>` -> grants one free
        # domain from the center, opening choose_domain_reward.
        magic_before = player.magic_score
        strength_before = player.strength_score
        vp_before = player.victory_score
        game.act_on_required_action(player.player_id, "slay_pay 0 12 5")
        self.assertEqual(game.action_required["action"], "choose_domain_reward",
            "Snow Queen's <domains> special_reward must open the grant-domain prompt")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "grant_domain_reward")
        self.assertEqual(prc.get("source_name"), "Snow Queen",
            "grant-domain prompt should attribute itself to the slain Snow Queen")

        # Snow Queen costs got paid and her VP reward (5) was applied; the
        # may-slay resume was stashed for after the domain pick finishes
        # its chain.
        self.assertEqual(player.strength_score, strength_before - 12)
        self.assertEqual(player.magic_score, magic_before - 5)
        self.assertEqual(player.victory_score, vp_before + 5,
            "Snow Queen's flat vp_reward=5 must apply during slay_monster")
        self.assertIn(self.snow_queen_row["name"],
                      [m.name for m in player.owned_monsters],
                      "Snow Queen must be in the player's owned_monsters after the slay")
        cont = getattr(game, "pending_post_slay_resume", None)
        self.assertIsNotNone(cont, "may-slay resume continuation should be stashed for after the followup chain")
        self.assertEqual(cont.get("player_id"), player.player_id)
        self.assertEqual(cont.get("resume_kind"), "harvest_pending_slay")

        # Domain grid options should include Eye of Asteraten.
        options = list(prc.get("options") or [])
        domain_ids = {opt.get("domain_id") for opt in options}
        self.assertIn(EYE_OF_ASTERATEN_ID, domain_ids)

        # ----- Stage 3: pick Eye of Asteraten (free domain) -----
        # Its activation effect `s 5 + slay`:
        #   * +5 strength immediately
        #   * `slay` re-queues a may-slay prompt (we're still in harvest
        #     phase, so it appends to pending_harvest_slays instead of
        #     opening a prompt inline).
        # After _resume_after_domain_activation_follow_up clears
        # action_required, the next advance_tick re-enters harvest
        # automation and drains the new slay into choose_monster_slay.
        strength_before = player.strength_score
        vp_before = player.victory_score
        idx = self._option_index_by(options, "domain_id", EYE_OF_ASTERATEN_ID)
        game.act_on_required_action(player.player_id, f"grant_domain {idx}")
        # Acquired domain went onto the player's tableau and granted its
        # base vp_reward (1).
        self.assertIn(self.eye_of_asteraten_row["name"],
                      [d.name for d in player.owned_domains],
                      "Eye of Asteraten must be owned after the grant_domain pick")
        self.assertEqual(player.victory_score, vp_before + int(self.eye_of_asteraten_row["vp_reward"] or 0),
            "Eye of Asteraten's vp_reward should apply at acquisition")
        # `s 5` leg of the activation applied.
        self.assertEqual(player.strength_score, strength_before + 5,
            "Eye of Asteraten activation must apply +5 strength before the `slay` queue")

        # advance_tick should now drain the queued slay -> next may-slay
        # prompt opens, this time tagged "Eye of Asteraten".
        game.advance_tick()
        self.assertEqual(game.action_required["action"], "choose_monster_slay",
            "Eye of Asteraten's `slay` activation leg should open a second may-slay prompt via harvest drain")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "immediate_slay")
        self.assertEqual(prc.get("source_label"), "Eye of Asteraten",
            "second may-slay prompt should be tagged with the activating domain")
        self.assertEqual(prc.get("resume_kind"), "harvest_pending_slay")
        options = list(prc.get("options") or [])
        # Only Gnolls remains on the monster grid (Snow Queen was slain).
        monster_ids = {opt.get("monster_id") for opt in options}
        self.assertEqual(monster_ids, {GNOLLS_ID},
            "only Gnolls should remain after Snow Queen was slain")

        # ----- Stage 4: pick & pay for Gnolls -----
        # Gnolls' special_reward is `choose <citizens>` -> opens a
        # special_payout_choose prompt listing every accessible board
        # citizen as a citizens.choice option.
        idx = self._option_index_by(options, "monster_id", GNOLLS_ID)
        game.act_on_required_action(player.player_id, f"choose_monster_slay {idx}")
        self.assertEqual(game.action_required["action"], "slay_monster_payment")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("monster_id"), GNOLLS_ID)
        self.assertEqual(prc.get("strength_cost"), 9)
        self.assertEqual(prc.get("magic_cost"), 0)

        strength_before = player.strength_score
        vp_before = player.victory_score
        owned_citizens_before = len(player.owned_citizens)
        game.act_on_required_action(player.player_id, "slay_pay 0 9 0")
        self.assertEqual(
            game.action_required["action"].lower().split()[0], "choose",
            "Gnolls' `choose <citizens>` must open a choose prompt over the citizen grid",
        )
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "special_payout_choose")
        # Strength was deducted; VP from Gnolls (3) applied.
        self.assertEqual(player.strength_score, strength_before - 9)
        self.assertEqual(player.victory_score, vp_before + 3)
        self.assertIn(self.gnolls_row["name"],
                      [m.name for m in player.owned_monsters],
                      "Gnolls must be in owned_monsters after the slay")
        # The chain stashed (and overwrote) the post-slay resume for the
        # new outer slay; either way it must resolve cleanly at the end.
        cont = getattr(game, "pending_post_slay_resume", None)
        self.assertIsNotNone(cont, "post-slay resume must be stashed while the citizen-choose prompt is open")

        # ----- Stage 5: pick a citizen -----
        # All options here are citizens.choice — pick the first one and
        # confirm the player gained that exact citizen.
        opts = list(prc.get("options") or [])
        self.assertGreater(len(opts), 0)
        for o in opts:
            self.assertEqual(o.get("token"), "citizens.choice",
                f"choose options must be citizens.choice, got {o!r}")
        wanted_citizen_id = int(opts[0]["citizen_id"])
        wanted_citizen_name = opts[0]["name"]
        game.act_on_required_action(player.player_id, "choose 1")

        # After the citizen pick:
        #  * one new citizen on the player's tableau (the one we picked)
        #  * pending_post_slay_resume drained
        #  * harvest finalized (no more queue entries, automation cleared)
        self.assertEqual(len(player.owned_citizens), owned_citizens_before + 1)
        new_citizen = player.owned_citizens[-1]
        self.assertEqual(new_citizen.citizen_id, wanted_citizen_id)
        self.assertEqual(new_citizen.name, wanted_citizen_name)
        self.assertIsNone(getattr(game, "pending_post_slay_resume", None),
            "post-slay resume must drain once the citizen pick clears all prompts")
        self.assertEqual(getattr(game, "pending_harvest_slays", []), [],
            "all queued may-slay prompts must be drained by end of harvest")
        # Engine should be idle (no per-player prompt outstanding) after
        # the chain resolves; harvest finalize fires from the drain, so
        # the next advance_tick moves us to the action phase.
        self.assertEqual(game.action_required.get("action", ""), "")
        self.assertTrue(getattr(game, "harvest_processed", False),
            "harvest must be marked processed once the slay drain empties")

        # ----- Stage 6: drain into action phase -----
        game.advance_tick()
        self.assertEqual(game.phase, "action",
            "after the slay chain finalizes harvest, the next tick should land us in action phase")
        self.assertEqual(game.action_required.get("action"), "standard_action")
        self.assertEqual(game.action_required.get("id"), player.player_id)


if __name__ == "__main__":
    # Bail out with a clear hint if the tunnel isn't running, instead of a
    # cryptic mariadb stack trace mid-test.
    if not _db_available():
        sys.stderr.write(
            "DB at 127.0.0.1:3306 (vckonline) is not reachable.\n"
            "Start the SSH tunnel first: ssh -L 3306:localhost:3306 lukesau.com\n"
            "See docs/database.md for details.\n"
        )
        sys.exit(2)
    unittest.main()
