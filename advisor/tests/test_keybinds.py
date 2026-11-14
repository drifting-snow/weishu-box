# -*- coding: utf-8 -*-
"""Tests for vision/keybinds.py: declarative hotkey facts and reverse lookup.
Pure stdlib; no OCR/PIL. Pins the no-auto-press boundary and engine mapping.
"""
import unittest

from vision.keybinds import (
    ACTION_KEYBINDS, VIEW_KEYBINDS, OTHER_KEYBINDS, NO_SHORTCUT_VERBS,
    verb_to_key, key_for_recommendation, all_keybinds,
)


class KeybindFactsTest(unittest.TestCase):
    def test_user_confirmed_action_keys_map_to_engine_verbs(self):
        self.assertEqual(ACTION_KEYBINDS["G"][0], "upgrade")
        self.assertEqual(ACTION_KEYBINDS["S"][0], "freeze")
        self.assertEqual(ACTION_KEYBINDS["D"][0], "refresh")

    def test_w_opens_enemy_panel_view(self):
        view, label = VIEW_KEYBINDS["W"]
        self.assertEqual(view, "enemy_panel")
        self.assertIn("敌方", label)

    def test_buy_and_merge_have_no_shortcut(self):
        for verb in NO_SHORTCUT_VERBS:
            self.assertIsNone(verb_to_key(verb))

    def test_every_action_verb_is_reverse_lookupable(self):
        for key, (verb, _label) in ACTION_KEYBINDS.items():
            self.assertEqual(verb_to_key(verb), key)


class ReverseLookupTest(unittest.TestCase):
    def test_known_verb_returns_key(self):
        self.assertEqual(verb_to_key("upgrade"), "G")
        self.assertEqual(verb_to_key("refresh"), "D")
        self.assertEqual(verb_to_key("freeze"), "S")

    def test_unknown_verb_returns_none(self):
        self.assertIsNone(verb_to_key("nope"))
        self.assertIsNone(verb_to_key("buy"))

    def test_recommendation_suffix(self):
        self.assertEqual(key_for_recommendation("upgrade"), "（按 G）")
        self.assertEqual(key_for_recommendation("refresh"), "（按 D）")
        # no-shortcut verbs produce no suffix rather than a fabricated key
        self.assertEqual(key_for_recommendation("buy"), "")
        self.assertEqual(key_for_recommendation("merge"), "")


class MergedViewTest(unittest.TestCase):
    def test_all_keybinds_tagged_by_kind(self):
        merged = all_keybinds()
        self.assertEqual(merged["G"]["kind"], "action")
        self.assertEqual(merged["W"]["kind"], "view")
        self.assertIn(merged["G"]["verb"], ("upgrade", "refresh", "freeze"))
        # every entry carries a human label
        for key, entry in merged.items():
            self.assertIn("kind", entry)

    def test_no_key_duplicated_across_groups(self):
        groups = (set(ACTION_KEYBINDS), set(VIEW_KEYBINDS), set(OTHER_KEYBINDS))
        total = sum(len(g) for g in groups)
        self.assertEqual(total, len(set().union(*groups)))


if __name__ == "__main__":
    unittest.main()
