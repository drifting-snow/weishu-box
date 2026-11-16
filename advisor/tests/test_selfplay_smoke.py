# -*- coding: utf-8 -*-
"""Smoke tests for self-play scaffold (ASSUMED odds + income)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor import shop_odds
from advisor.data import Dataset
from advisor.selfplay import income as income_mod
from advisor.selfplay.episode import run_episode
from advisor.selfplay.hillclimb import hillclimb_step
from advisor.selfplay.params import apply_params, snapshot_params
from advisor.model import BoardUnit, GameState, ShopCard
from advisor.selfplay.shop_roll import odds_disclaimer, roll_shop


class ShopOddsAssumedTest(unittest.TestCase):
    def test_tier_probs_assumed_guicheng(self):
        doc = shop_odds.load_shop_roll_odds()
        self.assertTrue(doc.get("assumed"))
        self.assertFalse(doc.get("official"))
        probs = shop_odds.tier_probs(3, season="guicheng")
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)
        self.assertIn("ASSUMED", odds_disclaimer())


class ShopRollTest(unittest.TestCase):
    def test_roll_shop_length_matches_slots(self):
        import random
        ds = Dataset()
        cards = roll_shop(ds, 2, "standard", rng=random.Random(0),
                          include_items=False)
        self.assertEqual(len(cards), int(ds.slots(2, "standard")))
        self.assertTrue(all(c.kind == "operator" and c.name for c in cards))

    def test_dedicated_item_slot_confirmed(self):
        import random
        from advisor.selfplay.shop_roll import (
            item_mix_model, item_slots_per_shop, item_slot_rate)
        ds = Dataset()
        doc = shop_odds.load_shop_roll_odds()
        mix = doc.get("item_mix") or {}
        self.assertEqual(item_mix_model(doc), "dedicated_item_slots")
        self.assertEqual(item_slots_per_shop(doc), 1)
        self.assertFalse(mix.get("assumed"))  # slot count confirmed
        self.assertTrue(mix.get("within_item_assumed"))
        self.assertEqual(item_slot_rate(doc), 0.0)
        n_ops = int(ds.slots(3, "standard"))
        cards = roll_shop(ds, 3, "standard", rng=random.Random(1))
        self.assertEqual(len(cards), n_ops + 1)
        items = [c for c in cards if c.kind == "item"]
        self.assertEqual(len(items), 1)
        self.assertLessEqual(int(items[0].tier or 1), 3)
        self.assertIn("item_mix", odds_disclaimer().lower())
        self.assertIn("dedicated", odds_disclaimer().lower())

    def test_legacy_bernoulli_item_mix_override(self):
        import random
        ds = Dataset()
        doc = shop_odds.load_shop_roll_odds()
        forced = dict(doc)
        forced["item_mix"] = {
            "model": "bernoulli",
            "assumed": True, "official": False,
            "per_slot_item_rate": 1.0,
            "within_item_model": "uniform_all_items",
        }
        cards = roll_shop(ds, 3, "standard", rng=random.Random(1),
                          odds_doc=forced)
        self.assertTrue(cards)
        self.assertTrue(all(c.kind == "item" for c in cards))


class FreezePersistTest(unittest.TestCase):
    def test_freeze_carries_shop_into_next_rest(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        st = GameState(
            round=1, gold=4, dispatch_level=1, difficulty="standard",
            board=[BoardUnit(name=ds.operators[0]["name"])],
            shop=[ShopCard(kind="operator", name="冻结牌A", tier=1, price=2),
                  ShopCard(kind="operator", name="冻结牌B", tier=1, price=2),
                  ShopCard(kind="item", name="冻结道具", tier=1, price=1)],
            frozen=True,
        )
        meta = ep._rest_start_shop(ds, st, season="guicheng",
                                   rng=random.Random(0))
        self.assertTrue(meta["shop_carry_frozen"])
        self.assertGreaterEqual(meta["frozen_kept"], 3)
        self.assertEqual(st.shop[0].name, "冻结牌A")
        self.assertTrue(any(c.kind == "item" and c.name == "冻结道具"
                            for c in st.shop))
        # L1: 3 ops + 1 item
        self.assertEqual(len(st.shop), 4)
        self.assertEqual(sum(1 for c in st.shop if c.kind == "item"), 1)
        self.assertFalse(st.frozen)  # one-round lock consumed

    def test_freeze_action_sets_flag(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        st = GameState(round=1, gold=4, dispatch_level=1, shop=[], board=[])
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{"verb": "freeze", "target": "x", "cost": 0}]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "freeze")
        self.assertTrue(st.frozen)

    def test_buy_item_uses_item_path(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        item = ds.items[0]
        carrier = ds.operators[0]["name"]
        st = GameState(
            round=1, gold=20, dispatch_level=3,
            board=[BoardUnit(name=carrier)],
            shop=[ShopCard(kind="item", name=item["name"],
                           tier=int(item.get("tier") or 1),
                           price=int(item.get("price") or 1))],
            equipment={},
        )
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{
                "verb": "buy", "target": item["name"],
                "cost": int(item.get("price") or 1),
            }]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "buy_item")
        self.assertIn(item["name"], st.equipment.get(carrier) or [])
        self.assertEqual(st.shop, [])

    def test_sell_returns_default_gold(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        name = ds.operators[0]["name"]
        st = GameState(
            round=1, gold=0, dispatch_level=1,
            board=[BoardUnit(name=name), BoardUnit(name=ds.operators[1]["name"])],
            shop=[],
        )
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{"verb": "sell", "target": name, "cost": 0}]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "sell")
        self.assertGreaterEqual(st.gold, 1)
        self.assertEqual(len(st.board), 1)


class IncomeAssumedTest(unittest.TestCase):
    def test_income_marked_assumed_formula(self):
        # Community ASSUMED: min(3+r, 12); R1–R3 verified 4/5/6.
        doc = income_mod.load_gold_income()
        self.assertTrue(doc.get("assumed"))
        self.assertFalse(doc.get("official"))
        self.assertEqual(doc.get("income_cap"), 12)
        self.assertIn("ASSUMED", income_mod.ASSUMED_INCOME_NOTE)
        self.assertEqual(income_mod.gold_for_round(1), 4)
        self.assertEqual(income_mod.gold_for_round(2), 5)
        self.assertEqual(income_mod.gold_for_round(3), 6)
        self.assertEqual(income_mod.gold_for_round(9), 12)
        self.assertEqual(income_mod.gold_for_round(15), 12)
        self.assertEqual(income_mod.gold_for_round(1, flat=7), 7)
        table = income_mod.table_for_mode(doc)
        for r in range(1, 16):
            self.assertEqual(table[r], income_mod.income_formula(r, doc))

    def test_episode_clears_unspent_each_rest(self):
        out = run_episode(seed=0, max_rounds=3, actions_per_round=2,
                          use_battle=False)
        self.assertTrue(out["log"])
        for i, row in enumerate(out["log"]):
            self.assertEqual(row["gold_granted"], income_mod.gold_for_round(i + 1))
            self.assertTrue(row["gold_unspent_cleared"])
            self.assertFalse(row["gold_interest"])
            self.assertTrue(row["gold_assumed"])


class EpisodeSmokeTest(unittest.TestCase):
    def test_episode_returns_max_round(self):
        # Keep cheap: few rounds; battle may be slow but one/two waves OK.
        out = run_episode(seed=1, max_rounds=2, actions_per_round=4,
                          regulation_level=1, use_battle=True)
        self.assertIn("max_round_cleared", out)
        self.assertGreaterEqual(out["max_round_cleared"], 0)
        self.assertIn("assumed", out["shop_odds"].lower())
        self.assertTrue(out["log"])


class ParamsAndHillclimbSmokeTest(unittest.TestCase):
    def test_apply_restore_invest_weight(self):
        from advisor import economy
        before = economy.INVEST_WEIGHT["free_refresh"]
        prev = apply_params({"invest.free_refresh": before + 2})
        self.assertEqual(economy.INVEST_WEIGHT["free_refresh"], before + 2)
        apply_params(prev)
        self.assertEqual(economy.INVEST_WEIGHT["free_refresh"], before)

    def test_p6_knob_surface_covers_families(self):
        from advisor.selfplay.params import PARAMS, clamp_pair, snapshot_params
        keys = {p.key for p in PARAMS}
        # P6 expanded families (beyond baseline effdps.full-only nudge).
        for prefix in (
            "invest.", "gap.", "refresh.", "effdps.", "margin.",
            "compass.", "item.", "star.",
        ):
            self.assertTrue(any(k.startswith(prefix) for k in keys), prefix)
        self.assertGreaterEqual(len(PARAMS), 25)
        snap = snapshot_params()
        self.assertEqual(len(snap), len(PARAMS))
        # Nested dict knobs + refresh hunt constant apply/restore.
        from advisor import clear_margin, economy, engine
        before_sell = economy.INVEST_WEIGHT["special_sell_price"]
        before_hunt = engine.REFRESH_HUNT_PER_TIER
        before_tight = clear_margin.DAMAGE_BONUS["tight"]
        prev = apply_params({
            "invest.special_sell_price": before_sell + 1,
            "refresh.hunt_per_tier": before_hunt + 0.5,
            "margin.dmg_tight": before_tight + 1,
        })
        self.assertEqual(economy.INVEST_WEIGHT["special_sell_price"], before_sell + 1)
        self.assertAlmostEqual(engine.REFRESH_HUNT_PER_TIER, before_hunt + 0.5)
        self.assertEqual(clear_margin.DAMAGE_BONUS["tight"], before_tight + 1)
        apply_params(prev)
        self.assertEqual(economy.INVEST_WEIGHT["special_sell_price"], before_sell)
        self.assertAlmostEqual(engine.REFRESH_HUNT_PER_TIER, before_hunt)
        self.assertEqual(clear_margin.DAMAGE_BONUS["tight"], before_tight)
        clamped = clamp_pair({
            "refresh.soft_ceiling": 80, "refresh.critical_floor": 70,
            "margin.critical_at": 1.5, "margin.comfortable_at": 1.2,
            "margin.dmg_critical": 8, "margin.dmg_tight": 12,
        })
        self.assertLess(clamped["refresh.soft_ceiling"], clamped["refresh.critical_floor"])
        self.assertLess(clamped["margin.critical_at"], clamped["margin.comfortable_at"])
        self.assertLessEqual(clamped["margin.dmg_tight"], clamped["margin.dmg_critical"])

    def test_hillclimb_step_runs(self):
        # Short seed sweep (suite=None): 1 episode × 2 rounds × base+cand
        out = hillclimb_step(
            episodes=1, seed0=2, max_rounds=2,
            param_key="gap.cap",
            suite=None,
        )
        self.assertEqual(out["param"], "gap.cap")
        self.assertIn("improved", out)
        self.assertIn("mean_max_round", out["base"])
        self.assertIn("fitness", out["base"])

    def test_hillclimb_can_nudge_refresh_hunt(self):
        out = hillclimb_step(
            episodes=1, seed0=3, max_rounds=2,
            param_key="refresh.hunt_per_tier",
            suite=None,
        )
        self.assertEqual(out["param"], "refresh.hunt_per_tier")
        self.assertIn("fitness", out["base"])



class P4ActionsPlacementTest(unittest.TestCase):
    def test_ordered_picks_epsilon_can_reorder(self):
        from advisor.selfplay import episode as ep
        import random
        rec = {
            "recommendations": [
                {"verb": "buy", "target": "A", "score": 100, "cost": 2},
                {"verb": "buy", "target": "B", "score": 50, "cost": 2},
                {"verb": "refresh", "target": "调度中心", "score": 40, "cost": 1},
            ]
        }
        # epsilon=1 forces sample among top-k
        seen = set()
        for seed in range(40):
            picks = ep._ordered_picks(
                rec, random.Random(seed), epsilon=1.0, top_k=3)
            seen.add(picks[0]["target"])
        self.assertGreaterEqual(len(seen), 2)

    def test_merge_reward_rolls_three_operators(self):
        from advisor.selfplay.shop_roll import roll_merge_reward, merge_reward_config
        import random
        ds = Dataset()
        cfg = merge_reward_config()
        self.assertTrue(cfg.get("assumed"))  # which-ops still ASSUMED
        self.assertTrue(cfg.get("structure_confirmed"))
        self.assertEqual(int(cfg.get("picks") or 0), 3)
        cards = roll_merge_reward(ds, 2, rng=random.Random(0))
        self.assertEqual(len(cards), 3)
        self.assertTrue(all(c.kind == "operator" for c in cards))

    def test_buy_third_copy_grants_merge_reward_shop(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        # Pick an operator that exists
        name = None
        for op in ds.operators:
            if int(op.get("shop_tier") or 0) == 1:
                name = op["name"]
                break
        self.assertIsNotNone(name)
        st = GameState(
            round=1, gold=10, dispatch_level=2,
            board=[BoardUnit(name=name, count=2, elite=False,
                             tier=1, bonds=list(ds.operator(name).get("bonds") or []))],
            shop=[ShopCard(kind="operator", name=name, tier=1, price=2)],
        )
        ctx = {"free_buys": 0, "merge_rewards": 0}
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{"verb": "buy", "target": name, "cost": 2, "score": 90}]},
            random.Random(0), "guicheng", ctx=ctx, epsilon=0.0)
        self.assertEqual(verb, "buy_merge_reward")
        self.assertEqual(ctx["merge_rewards"], 1)
        self.assertEqual(ctx["free_buys"], 1)
        self.assertEqual(len(st.shop), 3)
        self.assertTrue(any(u.elite for u in st.board if u.name == name))

    def test_placement_sorts_high_block_front(self):
        from advisor.battle.adapter import placement_sort_key_melee
        from advisor.battle.unit import Unit, BaseStats
        def mk(name, block, atk):
            return Unit(
                "id_%s" % name, name, "ally", "op",
                BaseStats(atk=atk, defense=0, max_hp=1, res=0,
                          base_bat=1.0, block_cnt=block, range_radius=1.0))
        a = mk("tank", 3, 100)
        b = mk("dps", 1, 500)
        ordered = sorted([b, a], key=placement_sort_key_melee)
        self.assertEqual(ordered[0].name, "tank")


class ObjectiveAndEvalHarnessTest(unittest.TestCase):
    def test_score_episode_penalizes_leaks(self):
        from advisor.selfplay.objective import score_episode
        clean = score_episode({
            "max_round_cleared": 2,
            "log": [
                {"ok": True, "leaked": 0, "gold_end": 0},
                {"ok": True, "leaked": 0, "gold_end": 1},
            ],
        })
        leaky = score_episode({
            "max_round_cleared": 2,
            "log": [
                {"ok": True, "leaked": 0, "gold_end": 0},
                {"ok": False, "leaked": 5, "gold_end": 0},
            ],
        })
        self.assertGreater(clean["fitness"], leaky["fitness"])
        self.assertEqual(clean["max_round_cleared"], 2)

    def test_score_episode_penalizes_overflow_and_clear_miss(self):
        from advisor.selfplay.objective import score_episode
        clean = score_episode({
            "max_round_cleared": 1,
            "log": [{
                "ok": True, "leaked": 0, "gold_end": 0,
                "clear_frac": 1.0, "max_overflow_s": 0.0,
            }],
        })
        pressured = score_episode({
            "max_round_cleared": 1,
            "log": [{
                "ok": True, "leaked": 0, "gold_end": 0,
                "clear_frac": 0.5, "max_overflow_s": 2.0,
            }],
        })
        self.assertGreater(clean["fitness"], pressured["fitness"])
        self.assertGreater(pressured["overflow_s"], 0)
        self.assertGreater(pressured["clear_miss"], 0)
        self.assertIn("overflow", pressured["weights"])
        self.assertIn("clear_miss", pressured["weights"])
        # Also accept signals nested under battle_sim.result.pressure.
        nested = score_episode({
            "max_round_cleared": 0,
            "log": [{
                "ok": False,
                "battle_sim": {
                    "result": {
                        "killed": 2, "leaked": 2, "total": 4,
                        "pressure": {"front": {"overflow_seconds": 1.5}},
                    }
                },
            }],
        })
        self.assertAlmostEqual(nested["overflow_s"], 1.5)
        self.assertAlmostEqual(nested["clear_miss"], 0.5)

    def test_eval_cards_suite_smoke_runs(self):
        from advisor.selfplay.eval_harness import evaluate_on_cards, list_cards
        cards = list_cards(suite="smoke")
        self.assertGreaterEqual(len(cards), 2)
        # Run only first two cards for CI speed.
        out = evaluate_on_cards(cards=cards[:2])
        self.assertIn("fitness", out)
        self.assertIn("mean_max_round", out)
        self.assertEqual(out["n"], 2)
        self.assertTrue(out.get("assumed_env"))
        self.assertEqual(len(out["cards"]), 2)

    def test_aggregate_variance_penalty(self):
        from advisor.selfplay.objective import aggregate_scores, better
        stable = aggregate_scores([
            {"fitness": 10, "max_round_cleared": 1, "total_leaked": 0},
            {"fitness": 10, "max_round_cleared": 1, "total_leaked": 0},
        ], variance_weight=0.35)
        noisy = aggregate_scores([
            {"fitness": 20, "max_round_cleared": 2, "total_leaked": 0},
            {"fitness": 0, "max_round_cleared": 0, "total_leaked": 0},
        ], variance_weight=0.35)
        self.assertEqual(stable["mean_fitness"], 10.0)
        self.assertGreater(noisy["std_fitness"], stable["std_fitness"])
        # Same mean (10) but noisy has std>0 → lower fitness after penalty.
        self.assertGreater(stable["fitness"], noisy["fitness"])
        self.assertTrue(better(stable, noisy))


if __name__ == "__main__":
    unittest.main(verbosity=2)
