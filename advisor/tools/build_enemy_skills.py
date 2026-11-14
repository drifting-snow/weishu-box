# -*- coding: utf-8 -*-
"""Build data/enemy_skills.json: deterministically drivable enemy skill bursts.

Enemy skills are far more heterogeneous than operator skills: of the 31 act3
enemies that carry a skill, most are summons, shields, control, DoT, attack-speed
auras or multi-phase boss scripts. Only a narrow subset can be driven by the
current kernel without inventing new damage systems.

First-cut scope (conservative, all must hold):
  * a periodic burst: cooldown finite and > 0 (cd == 0 skills are passives/state
    machines, not recurring bursts);
  * a pure ATK-scale hit: blackboard has combat_atk_scale / atk_scale > 0;
  * an explicit AoE reach: range_radius > 0 (hits every operator in radius);
  * NO elemental/arts/control/summon/shield keys: no ep_damage_ratio, no
    stun/dot_damage/damage_resistance/enemy_key/branch_id. The kernel's
    deal_hit trunk is physical-only, so anything arts/nerve/chain is parked.

Under those rules exactly one act3 enemy qualifies today: 矩兽 CombatAoe
(atk*2.0 every 2.0s over radius 1.6). The builder stays generic, so any future
enemy meeting the same clean shape is picked up automatically; everything else
is enumerated in _meta.parked with the reason instead of being guessed. Stdlib
only; reads the git-ignored official enemy_database through our own parser.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "enemy_skills.json")

# Keys that signal a mechanic the kernel cannot settle as a single phys/arts
# hit. ep_damage_ratio is deliberately NOT here: it is the ELEMENTAL (nerve)
# side-share, tracked separately and parked as a note while the arts/physical
# main hit (atk_scale) stays drivable through the matching damage trunk.
_BLOCKING_KEYS = (
    "stun", "special_stun_duration", "dot_damage",
    "dot_duration", "damage_resistance", "enemy_key", "branch_id",
    "chain.atk_scale", "summon.hp_ratio",
)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _bb(skill):
    return {b.get("key"): b.get("value") for b in (skill.get("blackboard") or [])}


def _mv(node, *path):
    cur = node
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur.get("m_value") if isinstance(cur, dict) and "m_value" in cur else cur


def build():
    ed = load(os.path.join(GD, "enemy_database.json"))
    idx = {}
    for rec in ed["enemies"]:
        if isinstance(rec, dict) and "Key" in rec:
            for entry in rec["Value"]:
                if entry.get("level", 0) == 0:
                    idx[rec["Key"]] = entry["enemyData"]
    waves = load(os.path.join(ROOT, "data", "act3_waves.json"))
    spawn_ids = sorted({sp["enemy_id"] for lvl in waves["level_stems"].values()
                        for sp in lvl.get("spawns", [])})

    enemies, parked = {}, []
    for eid in spawn_ids:
        d0 = idx.get(eid)
        if not d0:
            continue
        desc = str(_mv(d0, "description") or "")
        bursts = []
        for s in (d0.get("skills") or []):
            bb = _bb(s)
            prefab = s.get("prefabKey")
            cd = s.get("cooldown")
            scale = bb.get("combat_atk_scale", bb.get("atk_scale"))
            rng = bb.get("range_radius")
            reason = None
            if not isinstance(cd, (int, float)) or cd <= 0:
                reason = "non-periodic (cd=%r, passive/state)" % cd
            elif scale is None or float(scale) <= 0:
                reason = "no positive atk scale"
            elif rng is None or float(rng) <= 0:
                reason = "no AoE range_radius"
            elif any(k in bb for k in _BLOCKING_KEYS):
                reason = "mixed mechanic (control/summon/shield/chain)"
            if reason:
                if prefab is not None:
                    parked.append({"enemy_id": eid, "prefab": prefab, "reason": reason})
                continue
            # Damage family: the enemy table has no damage-type field, so the only
            # authoritative signal is the official description text. A skill whose
            # description says 法术伤害 settles through the ARTS trunk (operator RES),
            # everything else stays physical (operator DEF).
            family = "arts" if "法术伤害" in desc else "phys"
            burst = {
                "kind": "periodic_aoe",
                "damage_family": family,
                "prefab": prefab,
                "cooldown": float(cd),
                "initial_cooldown": float(s.get("initCooldown", 0.0) or 0.0),
                "atk_scale": float(scale),
                "range_radius": float(rng),
            }
            # Elemental (nerve/erosion/...) side-share is not modelled yet; keep
            # the ratio on the record and ledger it without blocking the main hit.
            ep = bb.get("ep_damage_ratio")
            if ep is not None:
                burst["elemental_ratio_parked"] = float(ep)
                parked.append({"enemy_id": eid, "prefab": prefab,
                               "reason": "elemental ep_damage_ratio=%.2f parked; %s main hit driven"
                                         % (float(ep), family)})
            bursts.append(burst)
        if bursts:
            enemies[eid] = {
                "enemy_name": _mv(d0, "name"),
                "base_atk": float(_mv(d0, "attributes", "atk") or 0.0),
                "bursts": bursts,
            }

    out = {
        "_meta": {
            "description": "卫戍协议敌人可确定性驱动的周期 AoE 技能爆发（物理/法术）；由 enemy_database 经 tools/build_enemy_skills.py 自有筛选生成，"
                           "仅收录攻击力倍率+范围+有限冷却且无控制/召唤/护盾/链式的技能；伤害类型由官方描述“法术伤害”字样裁决，不含第三方/GPL 数据。",
            "generated_by": "tools/build_enemy_skills.py",
            "source_tables": "enemy_database.json + act3_waves.json (gitignored source for the former)",
            "model": "every cooldown seconds the enemy hits EVERY deployed operator within Euclidean range_radius for "
                     "base_atk*atk_scale; damage_family=arts settles through the ARTS trunk (operator RES) and phys through "
                     "the physical trunk (operator DEF), both with the 5% minimum-damage floor. Elemental ep_damage_ratio is parked.",
            "enemy_count_with_burst": len(enemies),
            "parked_skill_count": len(parked),
            "parked": parked,
            "needs_review": [
                "driven: periodic single-hit phys/arts AoE whose family is proven by the description text; elemental nerve damage "
                "(ep_damage_ratio), chain, DoT, stun, shields, summons and multi-phase bosses are parked until modelled",
                "the enemy table has no damage-type field; arts family relies on the 法术伤害 description keyword, so an unlabelled skill defaults to physical",
                "AoE reach uses Euclidean tile radius; the official prefab may use a different shape",
                "burst uses the level-0 base ATK; any in-fight ATK state changes are not modelled",
            ],
        },
        "enemies": enemies,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    out = build()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
    m = out["_meta"]
    print("wrote %s : %d enemies with a drivable burst, %d skills parked"
          % (args.out, m["enemy_count_with_burst"], m["parked_skill_count"]))
    for eid, rec in out["enemies"].items():
        for b in rec["bursts"]:
            print("  %s %s %s scale=%.2f range=%.1f cd=%.1f"
                  % (eid, rec["enemy_name"], b["prefab"], b["atk_scale"],
                     b["range_radius"], b["cooldown"]))


if __name__ == "__main__":
    main()
