import unittest

from preset_registry import (
    all_preset_ids,
    get_preset_config,
    include_agents_mode,
    include_relics_mode,
    lobby_selectable_presets,
    preset_label,
    preset_short_label,
)

_DEAL_KEYS = (
    "monster_query",
    "citizen_query",
    "choose_one_citizen_per_roll",
    "domain_query",
    "duke_query",
    "event_query",
    "monster_expansion_filters",
    "citizen_expansion_filters",
    "domain_expansion_filters",
    "duke_expansion_filters",
    "event_expansion_filters",
    "exclude_domain_expansions",
    "guaranteed_domain_expansion",
    "fixed_citizen_ids",
    "fixed_monster_areas",
    "optional_starter_expansion",
    "apply_implemented_image_filter",
    "draft",
    "include_agents",
    "include_relics",
)


class PresetRegistryTests(unittest.TestCase):
    def test_all_json_files_load(self):
        ids = all_preset_ids()
        self.assertIn("base", ids)
        self.assertIn("june2026", ids)
        self.assertIn("current", ids)
        self.assertIn("random", ids)
        self.assertIn("draft", ids)
        self.assertEqual(len(ids), 10)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            get_preset_config("not-a-preset")

    def test_current_resolves_to_june2026_deal(self):
        current = get_preset_config("current")
        june = get_preset_config("june2026")
        for key in _DEAL_KEYS:
            self.assertEqual(current[key], june[key], msg=key)
        self.assertEqual(current["id"], "current")
        self.assertEqual(current["alias"], "june2026")

    def test_june2026_includes_agents_and_relics(self):
        self.assertEqual(include_agents_mode("june2026"), "always")
        self.assertEqual(include_relics_mode("june2026"), "never")
        self.assertEqual(include_agents_mode("current"), "always")
        self.assertEqual(include_relics_mode("current"), "never")

    def test_random_and_draft_modes(self):
        self.assertEqual(include_agents_mode("random"), "random")
        self.assertEqual(include_relics_mode("random"), "random")
        self.assertEqual(include_agents_mode("draft"), "draft")
        self.assertEqual(include_relics_mode("draft"), "draft")

    def test_base_excludes_optional_modules(self):
        self.assertEqual(include_agents_mode("base"), "never")
        self.assertEqual(include_relics_mode("base"), "never")

    def test_lobby_selectable_presets(self):
        selectable = lobby_selectable_presets()
        self.assertIn("current", selectable)
        self.assertIn("june2026", selectable)
        self.assertIn("base", selectable)
        self.assertNotIn("base1", selectable)
        self.assertNotIn("base2", selectable)

    def test_labels(self):
        self.assertEqual(preset_label("current"), "Rotating Set")
        self.assertEqual(preset_short_label("current"), "Rotating")
        self.assertEqual(preset_label("base"), "Base Set")

    def test_expansion_only_overrides_base(self):
        cfg = get_preset_config("base", expansion_only=True)
        self.assertEqual(cfg["domain_query"], "select_base_domains")
        self.assertEqual(cfg["duke_expansion_filters"], ["base"])
        self.assertEqual(cfg["event_expansion_filters"], ["base"])
        self.assertEqual(cfg["exclude_domain_expansions"], [])

    def test_expansion_only_overrides_crimsonseas(self):
        cfg = get_preset_config("crimsonseas", expansion_only=True)
        self.assertEqual(cfg["domain_expansion_filters"], ["crimsonseas", "base"])
        self.assertEqual(cfg["event_expansion_filters"], ["crimsonseas"])
        self.assertEqual(cfg["guaranteed_domain_expansion"], "crimsonseas")

    def test_june2026_fixed_board(self):
        cfg = get_preset_config("june2026")
        self.assertEqual(
            cfg["fixed_monster_areas"],
            ["Barrens", "Gloom Gyre", "Forest", "Skerry", "Fire Temple"],
        )
        self.assertEqual(
            cfg["fixed_citizen_ids"],
            [19, 2, 41, 14, 33, 34, 35, 36, 9, 48],
        )
        self.assertEqual(cfg["optional_starter_expansion"], "margraves")

    def test_deal_keys_present_for_every_preset(self):
        for pid in all_preset_ids():
            cfg = get_preset_config(pid)
            for key in _DEAL_KEYS:
                self.assertIn(key, cfg, msg=f"{pid}.{key}")


if __name__ == "__main__":
    unittest.main()
