# -*- coding: utf-8 -*-
"""Tests for native PRTS profiles merged into the operator dataset.

Covers the data the BWiki weishu source lacked: profession branch (角色分支),
native talents (e.g. silence), and anti-air inference. Runs offline against
the built JSON; regenerate via tools/fetch_prts_wiki.py + parse_prts.py +
build_data.py.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class PrtsProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DATA, "operators.json"), encoding="utf-8") as f:
            cls.ops = {o["name"]: o for o in json.load(f)}
        with open(os.path.join(DATA, "operator_profiles.json"), encoding="utf-8") as f:
            cls.profiles = {p["name"]: p for p in json.load(f)}

    def test_all_operators_have_branch_and_talents(self):
        self.assertEqual(len(self.profiles), 141)
        for name, p in self.profiles.items():
            self.assertTrue(p["branch"], "%s missing branch" % name)
            self.assertTrue(p["profession"], "%s missing profession" % name)
            self.assertIsInstance(p["talents"], list)

    def test_native_fields_merged_into_operators(self):
        lp = self.ops["拉普兰德"]
        for k in ("branch", "native_trait", "position", "anti_air",
                  "native_tags", "native_talents"):
            self.assertIn(k, lp)
        self.assertEqual(lp["branch"], "领主")

    def test_medics_never_anti_air(self):
        for name, o in self.ops.items():
            if o["prof"] == "医疗":
                self.assertFalse(o["anti_air"], "medic %s cannot damage air" % name)

    def test_ranged_damage_dealers_are_anti_air(self):
        for name in ("灰喉", "卡达", "安洁莉娜"):  # 狙击 / 术师 / 辅助(凝滞师)
            self.assertTrue(self.ops[name]["anti_air"], name)

    def test_melee_lord_branch_grants_anti_air(self):
        # 领主 guards have ranged attack trait -> can hit air despite melee position
        for name in ("拉普兰德", "棘刺", "仇白"):
            o = self.ops[name]
            self.assertEqual(o["branch"], "领主")
            self.assertTrue(o["anti_air"], name)

    def test_silence_talents_captured(self):
        silent = [name for name, p in self.profiles.items()
                  if any("特殊能力失效" in t["effect"] for t in p["talents"])]
        self.assertIn("拉普兰德", silent)
        self.assertIn("霍尔海雅", silent)
        # and the merged operator record carries it
        lp = self.ops["拉普兰德"]
        self.assertTrue(any("特殊能力失效" in t["effect"] for t in lp["native_talents"]))

    def test_no_unresolved_templates(self):
        for name, p in self.profiles.items():
            self.assertEqual(p["needs_review"], [], name)
            self.assertNotIn("{{", p["trait"])
            for t in p["talents"]:
                self.assertNotIn("{{", t["effect"])
            for s in p["skills"]:
                self.assertNotIn("{{", s["effect"])
                self.assertNotIn("}}", s["sp_cost"] + s["duration"])

    # ---- skills ----
    def test_skill_count_two_or_three(self):
        for name, p in self.profiles.items():
            self.assertIn(len(p["skills"]), (2, 3), "%s has %d skills" %
                          (name, len(p["skills"])))
            for s in p["skills"]:
                self.assertTrue(s["name"])
                self.assertTrue(s["effect"], s["name"])
                for k in ("sp_cost", "initial_sp", "duration"):
                    self.assertIn(k, s)

    def test_skill_uses_highest_level_effect(self):
        # mastery-3 top-level effect is stored (卡达 ATK skill ends at +80%)
        kada = self.ops["卡达"]
        atk_skill = next(s for s in kada["skills"] if "攻击力强化" in s["name"])
        self.assertIn("+80%", atk_skill["effect"])
        self.assertTrue(atk_skill["sp_cost"].isdigit())

    # ---- mechanic tags (counters) ----
    def test_anti_stealth_comes_from_skills(self):
        # native talents had zero anti-stealth; it lives in skills (真言 S3)
        for name in ("真言", "凛御银灰"):
            self.assertIn("anti_stealth", self.profiles[name]["mechanic_tags"], name)
            self.assertIn("anti_stealth", self.ops[name]["mechanic_tags"], name)

    def test_silence_tag(self):
        for name in ("拉普兰德", "霍尔海雅"):
            self.assertIn("silence", self.ops[name]["mechanic_tags"], name)

    def test_mechanic_tags_are_known(self):
        known = {"anti_stealth", "silence", "true_damage", "dot", "cc",
                 "def_pierce", "shield_heal", "revive", "crit_burst",
                 "anti_air_bonus"}
        for name, p in self.profiles.items():
            self.assertTrue(set(p["mechanic_tags"]) <= known, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
