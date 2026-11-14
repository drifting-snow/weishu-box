# -*- coding: utf-8 -*-
import io, os, sys, unittest
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor.data import Dataset
from advisor.model import GameState, BoardUnit
from advisor import effdps
from advisor.battle import adapter
from advisor.battle.wave import SpawnSpec
from advisor.battle.constants import MOVE_SCALE

DS = Dataset()
METRICS = effdps.load_combat_metrics()
PROFILES = effdps.load_damage_profiles()
DOC = adapter.clear_margin.load_waves()


def _op_of_prof(prof):
    for name, rec in METRICS.items():
        op = DS.operator(name)
        if op and op.get("prof") == prof:
            return name
    raise RuntimeError("no operator of profession %s" % prof)


CASTER = _op_of_prof("术师")     # ranged arts
DEFENDER = _op_of_prof("重装")   # melee blocker
GUARD = _op_of_prof("近卫")      # melee damage


def base_state(**kw):
    st = GameState(round=1, regulation_level=1, enemy_types=["special"],
                   board=[BoardUnit(name=CASTER), BoardUnit(name=DEFENDER),
                          BoardUnit(name=GUARD)])
    for k, v in kw.items():
        setattr(st, k, v)
    return st


class SpawnMappingTest(unittest.TestCase):
    def test_spawn_row_to_spec(self):
        level = DOC["level_stems"]["level_act3autochess_01"]
        specs = adapter.spawns_to_specs(level)
        self.assertTrue(specs)
        self.assertIsInstance(specs[0], SpawnSpec)
        # every spawn row maps 1:1 and fields carry through
        self.assertEqual(len(specs), len(level["spawns"]))
        for spec, sp in zip(specs, level["spawns"]):
            self.assertEqual(spec.enemy_key, sp["enemy_id"])
            self.assertEqual(spec.start_time, sp["first_spawn_t"])
            self.assertEqual(spec.count, sp["count"])
            self.assertEqual(spec.interval, sp.get("interval", 0.0))


class BuildBattleTest(unittest.TestCase):
    def test_builds_real_battle_with_scaled_enemy_hp(self):
        st = base_state()
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        self.assertIsNotNone(assembled)
        b = assembled["battle"]
        # three board operators become three allies
        self.assertEqual(len(b.allies), 3)
        # total scheduled enemies equals the level's total_count
        level = DOC["level_stems"]["level_act3autochess_01"]
        self.assertEqual(b.scheduler.pending() + 0, level["total_count"])
        # L1 multiplier is exactly 1.0, so enemy HP equals level-0 base
        self.assertEqual(assembled["hp_multiplier"], 1.0)

    def test_regulation_level_scales_enemy_hp(self):
        # L8 = 10/3 on the closed-form HP curve.
        st = base_state(regulation_level=8)
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        level = DOC["level_stems"]["level_act3autochess_01"]
        factory = assembled["battle"]._spawn_factory
        from advisor.battle.wave import SpawnEvent
        sp0 = level["spawns"][0]
        ev = SpawnEvent(sp0["first_spawn_t"], sp0["enemy_id"], 0, 0)
        enemy = factory(sp0["enemy_id"], ev)
        self.assertAlmostEqual(enemy.base.max_hp,
                               sp0["level0_hp"] * (10.0 / 3.0), places=4)

    def test_flying_flag_from_motion(self):
        st = base_state()
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        level = DOC["level_stems"]["level_act3autochess_01"]
        factory = assembled["battle"]._spawn_factory
        from advisor.battle.wave import SpawnEvent
        for i, sp in enumerate(level["spawns"]):
            ev = SpawnEvent(sp["first_spawn_t"], sp["enemy_id"],
                            sp.get("route_index", 0), i)
            u = factory(sp["enemy_id"], ev)
            self.assertEqual(u.is_flying, sp.get("motion") == "FLY")

    def test_melee_blocks_ranged_does_not(self):
        st = base_state()
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        by_name = {u.name: u for u in assembled["battle"].allies}
        self.assertGreaterEqual(by_name[DEFENDER].base.block_cnt, 1)
        self.assertGreaterEqual(by_name[GUARD].base.block_cnt, 1)
        self.assertEqual(by_name[CASTER].base.block_cnt, 0)
        # ranged caster deals arts, melee defaults to physical
        from advisor.battle import damage as kd
        self.assertEqual(getattr(by_name[CASTER], "damage_family"), kd.ARTS_T)
        self.assertEqual(getattr(by_name[GUARD], "damage_family"), kd.PHYS)


class BuffApplicationTest(unittest.TestCase):
    def test_equipment_raises_ally_attack(self):
        plain = adapter.build_battle(base_state(), DS, PROFILES, METRICS, DOC)
        # known offensive item (also used by the stage-1 buffs E2E)
        item_name = "源石溶剂"
        if DS.item_structured(item_name) is None:
            self.skipTest("源石溶剂 not present in item data")
        geared = adapter.build_battle(
            base_state(equipment={CASTER: [item_name]}),
            DS, PROFILES, METRICS, DOC)
        a0 = {u.name: u for u in plain["battle"].allies}[CASTER]
        a1 = {u.name: u for u in geared["battle"].allies}[CASTER]
        self.assertGreater(a1.stats.atk, a0.stats.atk)


class SimulateTest(unittest.TestCase):
    def test_simulate_returns_inert_record(self):
        st = base_state()
        rec = adapter.simulate(st, DS, PROFILES, METRICS, DOC)
        self.assertIsNotNone(rec)
        result = rec["result"]
        level = DOC["level_stems"]["level_act3autochess_01"]
        self.assertEqual(result["total"], level["total_count"])
        # accounting invariant: nothing resolved exceeds the spawn total
        self.assertLessEqual(result["killed"] + result["leaked"], result["total"])
        self.assertIn(result["reason"], ("cleared", "timeout"))
        self.assertTrue(rec["approximations"])  # honest approximations present
        # one ally accounting entry per board operator
        self.assertEqual(len(rec["allies"]), 3)

    def test_inert_on_empty_board(self):
        st = GameState(round=1, regulation_level=1, enemy_types=["special"])
        self.assertIsNone(adapter.simulate(st, DS, PROFILES, METRICS, DOC))

    def test_inert_on_unresolved_mode(self):
        st = base_state(regulation_level=None, difficulty="nonsense")
        self.assertIsNone(adapter.simulate(st, DS, PROFILES, METRICS, DOC))


class ConstantGuardTest(unittest.TestCase):
    def test_move_scale_mismatch_is_flagged(self):
        st = base_state()
        doc = json_roundtrip(DOC)
        lvl = doc["level_stems"]["level_act3autochess_01"]
        lvl["move_multiplier"] = MOVE_SCALE + 0.123
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, doc)
        self.assertTrue(any("MOVE_SCALE" in a for a in assembled["approximations"]))


def json_roundtrip(obj):
    import json
    return json.loads(json.dumps(obj, ensure_ascii=False))


class GridRangeAcquisitionTest(unittest.TestCase):
    """Kernel tile-based targeting: range_cells membership beats Euclidean."""

    def _battle_with_grid_ally(self, cells):
        from advisor.battle.battle import Battle
        from advisor.battle.unit import Unit, BaseStats
        b = Battle(rows=12, cols=20)
        # radius deliberately huge: if range_cells is honoured, it must NOT
        # widen the reach beyond the explicit cell set.
        ally = Unit("a", "a", "ally", "op",
                    BaseStats(atk=100.0, base_bat=1.0, range_radius=99.0))
        ally.range_cells = set(cells)
        b.add_ally(ally, 5, 10)  # tile row 5, col 10
        return b, ally

    def _enemy(self, col, row=5):
        from advisor.battle.unit import Unit, BaseStats
        e = Unit("e", "e", "enemy", "enemy", BaseStats(max_hp=1000.0))
        e.deployed = True
        e.alive = True
        e.x = float(col)
        e.y = float(row)
        return e

    def test_enemy_inside_grid_cell_is_targeted(self):
        # world offset (0,-1) is a member: enemy one tile toward the red gate
        b, ally = self._battle_with_grid_ally({(0, 0), (0, -1)})
        e = self._enemy(col=9)  # col 9 vs ally col 10 -> offset (0,-1)
        b.enemies.append(e)
        self.assertIs(b._acquire_target(ally), e)

    def test_enemy_outside_grid_is_not_targeted_despite_huge_radius(self):
        b, ally = self._battle_with_grid_ally({(0, 0), (0, -1)})
        e = self._enemy(col=8)  # offset (0,-2), Euclidean radius 99 would hit
        b.enemies.append(e)
        self.assertIsNone(b._acquire_target(ally))

    def test_grid_is_facing_sensitive_not_a_symmetric_circle(self):
        # cell on the negative-col side only; an enemy on the +col side (behind)
        # must not be hit even at the same one-tile distance.
        b, ally = self._battle_with_grid_ally({(0, 0), (0, -1)})
        behind = self._enemy(col=11)  # offset (0,+1)
        b.enemies.append(behind)
        self.assertIsNone(b._acquire_target(ally))

    def test_blocked_enemy_always_hittable_even_outside_grid(self):
        b, ally = self._battle_with_grid_ally({(0, 0)})  # self tile only
        e = self._enemy(col=0)  # far away, outside the grid
        e.blocked_by = ally
        ally.blocking.append(e)
        b.enemies.append(e)
        self.assertIs(b._acquire_target(ally), e)

    def test_legacy_euclidean_fallback_when_range_cells_none(self):
        from advisor.battle.battle import Battle
        from advisor.battle.unit import Unit, BaseStats
        b = Battle(rows=12, cols=20)
        ally = Unit("a", "a", "ally", "op",
                    BaseStats(atk=100.0, base_bat=1.0, range_radius=2.0))
        self.assertIsNone(ally.range_cells)  # default keeps legacy rule
        b.add_ally(ally, 5, 10)
        near = self._enemy(col=9)   # distance 1 <= 2
        far = self._enemy(col=7)    # distance 3 > 2
        b.enemies.append(near)
        self.assertIs(b._acquire_target(ally), near)
        b.enemies = [far]
        self.assertIsNone(b._acquire_target(ally))


class AdapterRealRangeInjectionTest(unittest.TestCase):
    def test_allies_carry_real_mirrored_grid(self):
        st = base_state()
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        self.assertIsNotNone(assembled)
        for u in assembled["battle"].allies:
            # every advisor operator has a real derived range (141/141 coverage)
            self.assertIsInstance(u.range_cells, set)
            self.assertTrue(u.range_cells)

    def test_puppeteer_grid_mirrors_to_negative_world_col(self):
        # 矩's official grid starts at col>=2; after red-gate mirroring every
        # world offset must be on the negative-col side.
        st = GameState(round=1, regulation_level=1, enemy_types=["special"],
                       board=[BoardUnit(name="矩")])
        assembled = adapter.build_battle(st, DS, PROFILES, METRICS, DOC)
        if assembled is None:
            self.skipTest("矩 battle not assembled")
        ju = next(u for u in assembled["battle"].allies if u.name == "矩")
        self.assertTrue(ju.range_cells)
        for _r, dc in ju.range_cells:
            self.assertLessEqual(dc, -2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
