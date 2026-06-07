import unittest

from cards import Monster
from game import Game
from game_models import Player


def make_scaling_monster(
    monster_id,
    name,
    strength_cost=0,
    magic_cost=0,
    vp_reward=0,
    special_cost="",
    special_reward="",
):
    monster = Monster(
        monster_id,
        name,
        "Cutthroats",
        "Orc",
        1,
        strength_cost,
        magic_cost,
        vp_reward,
        0,
        0,
        0,
        bool(special_reward),
        special_reward,
        bool(special_cost),
        special_cost,
        False,
        "crimsonseas",
    )
    monster.toggle_visibility(True)
    monster.toggle_accessibility(True)
    return monster


def make_game(player, monster, preset="crimsonseas"):
    return Game({
        "game_id": "test-game",
        "preset": preset,
        "player_list": [player],
        "monster_grid": [[monster]],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 1,
        "die_sum": 2,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
    })


class ScalingMonsterCostTests(unittest.TestCase):
    def test_goblin_pirates_second_slay_costs_more_strength(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 10
        owned = make_scaling_monster(
            900,
            "Goblin Pirates",
            strength_cost=3,
            special_cost='count owned_monster_name "Goblin Pirates" s 1',
        )
        player.owned_monsters.append(owned)
        top = make_scaling_monster(
            901,
            "Goblin Pirates",
            strength_cost=3,
            special_cost='count owned_monster_name "Goblin Pirates" s 1',
        )
        game = make_game(player, top)

        with self.assertRaises(ValueError):
            game.slay_monster(player.player_id, top.monster_id, sp=3, mp=0)

        game.slay_monster(player.player_id, top.monster_id, sp=4, mp=0)
        self.assertEqual(player.strength_score, 6)
        self.assertEqual(len(player.owned_monsters), 2)

    def test_araby_brigands_second_slay_costs_more_magic_and_strength(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 10
        owned = make_scaling_monster(
            902,
            "Araby Brigands",
            strength_cost=2,
            magic_cost=1,
            special_cost=(
                'count owned_monster_name "Araby Brigands" s 1 + '
                'count owned_monster_name "Araby Brigands" m 1'
            ),
        )
        player.owned_monsters.append(owned)
        top = make_scaling_monster(
            903,
            "Araby Brigands",
            strength_cost=2,
            magic_cost=1,
            special_cost=(
                'count owned_monster_name "Araby Brigands" s 1 + '
                'count owned_monster_name "Araby Brigands" m 1'
            ),
        )
        game = make_game(player, top)

        with self.assertRaises(ValueError):
            game.slay_monster(player.player_id, top.monster_id, sp=2, mp=1)

        game.slay_monster(player.player_id, top.monster_id, sp=3, mp=2)
        self.assertEqual(player.strength_score, 7)
        self.assertEqual(player.magic_score, 8)

    def test_immediate_slay_options_include_scaling_cost(self):
        player = Player("p1", "Player 1")
        owned = make_scaling_monster(
            904,
            "Sea Drake",
            magic_cost=2,
            special_cost='count owned_monster_name "Sea Drake" m 1',
        )
        player.owned_monsters.append(owned)
        top = make_scaling_monster(
            905,
            "Sea Drake",
            magic_cost=2,
            special_cost='count owned_monster_name "Sea Drake" m 1',
        )
        game = make_game(player, top)

        opts = game.slay._immediate_slay_monster_options(player.player_id)
        self.assertEqual(opts[0]["magic_cost"], 3)


class ScalingMonsterRewardTests(unittest.TestCase):
    def test_araby_brigands_flat_and_scaling_vp_are_separate(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 10
        top = make_scaling_monster(
            906,
            "Araby Brigands",
            strength_cost=2,
            magic_cost=1,
            vp_reward=1,
            special_cost=(
                'count owned_monster_name "Araby Brigands" s 1 + '
                'count owned_monster_name "Araby Brigands" m 1'
            ),
            special_reward='count owned_monster_name "Araby Brigands" v 1',
        )
        game = make_game(player, top)

        game.slay_monster(player.player_id, top.monster_id, sp=2, mp=1)
        self.assertEqual(player.victory_score, 2)

        player.strength_score = 10
        player.magic_score = 10
        top2 = make_scaling_monster(
            907,
            "Araby Brigands",
            strength_cost=2,
            magic_cost=1,
            vp_reward=1,
            special_cost=(
                'count owned_monster_name "Araby Brigands" s 1 + '
                'count owned_monster_name "Araby Brigands" m 1'
            ),
            special_reward='count owned_monster_name "Araby Brigands" v 1',
        )
        game.monster_grid[0].append(top2)
        game.slay_monster(player.player_id, top2.monster_id, sp=3, mp=2)
        self.assertEqual(player.victory_score, 5)

    def test_goblin_pirates_scaling_gold_reward(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 0
        top = make_scaling_monster(
            908,
            "Goblin Pirates",
            strength_cost=3,
            vp_reward=1,
            special_cost='count owned_monster_name "Goblin Pirates" s 1',
            special_reward='count owned_monster_name "Goblin Pirates" g 3',
        )
        game = make_game(player, top)

        game.slay_monster(player.player_id, top.monster_id, sp=3, mp=0)
        self.assertEqual(player.gold_score, 5)
        self.assertEqual(player.victory_score, 1)

    def test_sea_drake_scaling_strength_reward(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 10
        top = make_scaling_monster(
            909,
            "Sea Drake",
            strength_cost=1,
            magic_cost=2,
            vp_reward=2,
            special_cost='count owned_monster_name "Sea Drake" m 1',
            special_reward='count owned_monster_name "Sea Drake" s 3',
        )
        game = make_game(player, top)

        game.slay_monster(player.player_id, top.monster_id, sp=1, mp=2)
        self.assertEqual(player.strength_score, 12)
        self.assertEqual(player.victory_score, 2)


class HarpiesChooseRewardTests(unittest.TestCase):
    def test_harpies_choose_options_scale_with_owned_count(self):
        player = Player("p1", "Player 1")
        player.strength_score = 10
        player.magic_score = 10
        owned = make_scaling_monster(
            910,
            "Harpies",
            strength_cost=3,
            magic_cost=1,
            special_cost='count owned_monster_name "Harpies" m 1',
        )
        player.owned_monsters.append(owned)
        top = make_scaling_monster(
            911,
            "Harpies",
            strength_cost=3,
            magic_cost=1,
            vp_reward=2,
            special_cost='count owned_monster_name "Harpies" m 1',
            special_reward=(
                'choose <count owned_monster_name "Harpies" g 2> '
                '<count owned_monster_name "Harpies" s 2> '
                '<count owned_monster_name "Harpies" m 2>'
            ),
        )
        game = make_game(player, top)

        game.slay_monster(player.player_id, top.monster_id, sp=3, mp=2)
        self.assertTrue(str(game.action_required.get("action", "")).startswith("choose"))
        prc = game.pending_required_choice or {}
        options = prc.get("options") or []
        self.assertEqual(len(options), 3)
        self.assertTrue(all(o.get("token") == "count_monster_name" for o in options))

        game.act_on_required_action(player.player_id, "choose 2")
        self.assertEqual(player.strength_score, 11)
        self.assertEqual(player.victory_score, 2)


class BryneMapFilterTests(unittest.TestCase):
    def test_bryne_map_option_dropped_outside_crimson_seas(self):
        player = Player("p1", "Player 1")
        top = make_scaling_monster(
            912,
            "Bryne",
            strength_cost=1,
            magic_cost=1,
            special_cost='count owned_monster_name "Bryne" s 1',
            special_reward="choose g 2 p 1",
        )
        game = make_game(player, top, preset="base1")

        normalized, options = game.choose._normalize_choose_command("choose g 2 p 1")
        filtered = game.choose._filter_unavailable_choose_options(options)
        tokens = [o.get("token") for o in filtered]
        self.assertEqual(tokens, ["g"])
        self.assertEqual(normalized, "choose g 2 p 1")


if __name__ == "__main__":
    unittest.main()
