# -*- coding: utf-8 -*-
"""Tests for vision/match_text.py: default shop matching vs the conservative
mode used for the large (~1.8k) enemy-name index. Pure stdlib (difflib only),
no OCR model or PIL needed. Self-contained dictionaries keep these stable.
"""
import unittest

from vision.match_text import (
    match_one, match_ranked, normalize,
    SIM_THRESHOLD, CONSERVATIVE_THRESHOLD, CONSERVATIVE_GAP,
)

# A small dictionary with the shapes that cause cross-firing at scale:
# a base name, an elite 组长 variant, near names, and a short name.
DICT = ["寻险水手", "历险水手", "源石虫", "高能源石虫", "冰爆源石虫",
        "弧光镜卫", "弧光镜卫长", "士兵", "拳师囚犯", "技师囚犯",
        "萨卡兹大剑手", "萨卡兹大剑组长"]


class DefaultModeTest(unittest.TestCase):
    """The proven shop-OCR behaviour must stay unchanged."""

    def test_exact_match(self):
        self.assertEqual(match_one("寻险水手", DICT), "寻险水手")

    def test_substring_short_circuit(self):
        # default mode snaps aggressively on containment
        self.assertEqual(match_one("寻险水手α", DICT), "寻险水手")

    def test_similarity_fallback(self):
        # one-char OCR substitution within length diff 1
        self.assertEqual(match_one("寻险水乎", DICT), "寻险水手")

    def test_no_match_returns_none(self):
        self.assertIsNone(match_one("完全无关的东西xyz", DICT))

    def test_correction_map_applied(self):
        self.assertEqual(normalize("铜", {"铜": "锏"}), "锏")


class ConservativeModeTest(unittest.TestCase):
    """Enemy index: high threshold + uniqueness gap, refuse rather than mis-snap."""

    def test_full_name_exact_always_wins(self):
        for n in DICT:
            self.assertEqual(match_one(n, DICT, conservative=True), n,
                             "full name %r must resolve to itself" % n)

    def test_single_glyph_refused(self):
        # never infer a multi-char enemy name from one glyph
        self.assertIsNone(match_one("兵", DICT, conservative=True))
        self.assertIsNone(match_one("虫", DICT, conservative=True))

    def test_empty_refused(self):
        self.assertIsNone(match_one("  ", DICT, conservative=True))

    def test_dominant_unambiguous_truncation_accepted(self):
        # '源石' only matches 源石虫-family but the exact-length base is the
        # sole high-score candidate; a clear leader is accepted.
        got = match_one("源石虫", DICT, conservative=True)
        self.assertEqual(got, "源石虫")

    def test_crowded_near_name_race_refused(self):
        # '险水手' ties 历险水手 / 寻险水手 (same similarity, no clear leader)
        self.assertIsNone(match_one("险水手", DICT, conservative=True))
        # '师囚犯' is a crowded race between 拳师囚犯 / 技师囚犯
        self.assertIsNone(match_one("师囚犯", DICT, conservative=True))

    def test_low_similarity_refused_even_if_best(self):
        # below CONSERVATIVE_THRESHOLD -> None even when it is the top candidate
        self.assertIsNone(
            match_one("石虫", ["源石虫", "高能源石虫", "冰爆源石虫"],
                      conservative=True))

    def test_elite_base_collision_resolves_only_when_dominant(self):
        # exact full names still distinguish base vs 组长
        self.assertEqual(match_one("弧光镜卫长", DICT, conservative=True),
                         "弧光镜卫长")
        self.assertEqual(match_one("弧光镜卫", DICT, conservative=True),
                         "弧光镜卫")

    def test_threshold_constants_sane(self):
        self.assertGreater(CONSERVATIVE_THRESHOLD, SIM_THRESHOLD)
        self.assertGreaterEqual(CONSERVATIVE_GAP, 0.0)
        self.assertLess(CONSERVATIVE_THRESHOLD, 1.0)


class MatchRankedTest(unittest.TestCase):
    def test_exact_match_short_circuits_at_score_one(self):
        ranked = match_ranked("寻险水手", DICT)
        self.assertEqual(ranked[0], (1.0, "寻险水手", 0))

    def test_returns_empty_for_single_glyph(self):
        self.assertEqual(match_ranked("兵", DICT), [])

    def test_threshold_filters_low_scores(self):
        ranked = match_ranked("石虫", DICT, threshold=0.95)
        self.assertEqual(ranked, [])

    def test_exact_length_preferred_in_ordering(self):
        # ties in similarity: same-length (len_diff 0) candidate sorts first
        ranked = match_ranked("拳师囚犯", DICT, threshold=0.6)
        self.assertEqual(ranked[0][1], "拳师囚犯")


if __name__ == "__main__":
    unittest.main()
