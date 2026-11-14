# -*- coding: utf-8 -*-
"""Tests for gate-0 team capability-gap detection (advisor/team_gaps).

Uses the real committed Dataset but selects operators dynamically by the very
boolean the module reads, so the tests do not hard-code names that could change.
The silence gap additionally exercises the committed enemy_special_cases.json.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor.data import Dataset
from advisor.model import GameState, BoardUnit
from advisor import team_gaps as tg


def first(ops, pred):
    for op in ops:
        if pred(op):
            return op["name"]
    raise AssertionError("no operator satisfies predicate")


class TeamGapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.ops = cls.ds.operators
        cls.aa = first(cls.ops, lambda o: o.get("anti_air"))
        cls.caster = first(cls.ops, lambda o: o.get("prof") == "术师")
        cls.silencer = first(cls.ops, lambda o: "silence" in (o.get("mechanic_tags") or []))
        cls.piercer = first(cls.ops, lambda o: "def_pierce" in (o.get("mechanic_tags") or [])
                            or "true_damage" in (o.get("mechanic_tags") or []))
        # a ground physical operator with no air/pierce/silence answer
        cls.ground = first(cls.ops, lambda o: not o.get("anti_air")
                           and o.get("prof") != "术师"
                           and "silence" not in (o.get("mechanic_tags") or [])
                           and "def_pierce" not in (o.get("mechanic_tags") or [])
                           and "true_damage" not in (o.get("mechanic_tags") or []))

    def _state(self, types=(), names=(), board=()):
        return GameState(enemy_types=list(types), enemy_names=list(names),
                         board=[BoardUnit(name=n) for n in board])

    # ---- inert / no-picture ----
    def test_no_enemy_picture_no_gap(self):
        st = self._state(board=[self.ground])
        self.assertEqual(tg.detect_team_gaps(self.ds, st), [])

    # ---- anti-air ----
    def test_flying_gap_open_then_closed(self):
        st = self._state(types=["flying"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        self.assertEqual(tg.open_gap_ids(gaps), {"anti_air"})
        # adding an air-capable operator closes it
        st2 = self._state(types=["flying"], board=[self.ground, self.aa])
        self.assertEqual(tg.detect_team_gaps(self.ds, st2), [])

    # ---- refraction ----
    def test_refraction_gap_open_with_ground_physical(self):
        st = self._state(types=["refraction"], board=[self.ground])
        self.assertEqual(tg.open_gap_ids(tg.detect_team_gaps(self.ds, st)),
                         {"refraction"})

    def test_refraction_closed_by_caster_or_piercer(self):
        for closer in (self.caster, self.piercer):
            st = self._state(types=["refraction"], board=[self.ground, closer])
            self.assertEqual(tg.detect_team_gaps(self.ds, st), [],
                             "closer=%s should cover refraction" % closer)

    # ---- silence (named special ability, not generic categories) ----
    def test_silence_gap_from_named_ice_enemy(self):
        st = self._state(names=["冰爆源石虫·α"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        self.assertEqual(tg.open_gap_ids(gaps), {"silence"})
        self.assertTrue(gaps[0]["enemy_reasons"])  # carries a human reason

    def test_silence_closed_by_silencer(self):
        st = self._state(names=["冰爆源石虫·α"],
                         board=[self.ground, self.silencer])
        self.assertEqual(tg.detect_team_gaps(self.ds, st), [])

    def test_ordinary_enemy_names_open_no_silence_gap(self):
        # names that are not special cases must never demand silence
        st = self._state(names=["源石虫", "寻险水手"], board=[self.ground])
        self.assertEqual(tg.detect_team_gaps(self.ds, st), [])

    # ---- additive bonus wiring ----
    def test_operator_gap_bonus_only_when_open_and_filling(self):
        st = self._state(types=["flying"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        # the air-capable card closes the open gap -> bonus
        score, why = tg.operator_gap_bonus(self.ds, self.aa, gaps)
        self.assertEqual(score, tg.GAP_BONUS)
        self.assertTrue(any("对空" in w for w in why))
        # a ground card does not fill it -> nothing
        self.assertEqual(tg.operator_gap_bonus(self.ds, self.ground, gaps), (0.0, []))

    def test_no_gap_means_no_bonus(self):
        st = self._state(board=[self.aa])
        gaps = tg.detect_team_gaps(self.ds, st)
        self.assertEqual(tg.operator_gap_bonus(self.ds, self.aa, gaps), (0.0, []))

    def test_item_silence_gap_bonus(self):
        st = self._state(names=["冰爆源石虫·α"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        score, why = tg.item_gap_bonus(self.ds, "奥术法阵", gaps)
        self.assertEqual(score, tg.GAP_BONUS)
        self.assertTrue(why)
        # equipment cannot solve anti-air
        st2 = self._state(types=["flying"], board=[self.ground])
        self.assertEqual(
            tg.item_gap_bonus(self.ds, "奥术法阵",
                              tg.detect_team_gaps(self.ds, st2)), (0.0, []))

    def test_multiple_open_gaps_use_priority_and_cap(self):
        # a caster that also has anti_air can close both flying + refraction
        dual = first(self.ops, lambda o: o.get("anti_air")
                     and (o.get("prof") == "术师"
                          or "def_pierce" in (o.get("mechanic_tags") or [])))
        st = self._state(types=["flying", "refraction"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        self.assertEqual(tg.open_gap_ids(gaps), {"anti_air", "refraction"})
        score, why = tg.operator_gap_bonus(self.ds, dual, gaps)
        # priority + secondary bump, NOT raw GAP_BONUS * N
        expected = min(
            tg.GAP_BONUS_PRIMARY + tg.GAP_BONUS_SECONDARY,
            tg.GAP_BONUS_CAP,
        )
        self.assertEqual(score, expected)
        self.assertLess(score, tg.GAP_BONUS * 2)  # strictly below old stack
        self.assertLessEqual(score, tg.GAP_BONUS_CAP)
        self.assertLess(score, 60)  # below bond-one-away magnitude
        self.assertEqual(len(why), 2)
        # higher-priority gap (refraction) listed before anti_air
        self.assertTrue(why[0].startswith("补缺·"))
        self.assertIn("折射", why[0])

    def test_three_gaps_hard_capped_below_bond(self):
        # operator that can fill anti_air + refraction + silence
        triple = first(self.ops, lambda o: o.get("anti_air")
                       and (o.get("prof") == "术师"
                            or "def_pierce" in (o.get("mechanic_tags") or [])
                            or "true_damage" in (o.get("mechanic_tags") or []))
                       and "silence" in (o.get("mechanic_tags") or []))
        st = self._state(types=["flying", "refraction"],
                         names=["冰爆源石虫·α"], board=[self.ground])
        gaps = tg.detect_team_gaps(self.ds, st)
        self.assertEqual(tg.open_gap_ids(gaps),
                         {"anti_air", "refraction", "silence"})
        score, why = tg.operator_gap_bonus(self.ds, triple, gaps)
        uncapped = tg.GAP_BONUS_PRIMARY + tg.GAP_BONUS_SECONDARY * 2
        self.assertEqual(score, min(uncapped, tg.GAP_BONUS_CAP))
        self.assertLessEqual(score, tg.GAP_BONUS_CAP)
        self.assertLess(score, 60)
        self.assertEqual(len(why), 3)
        # silence is highest priority among the three
        self.assertIn("沉默", why[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
