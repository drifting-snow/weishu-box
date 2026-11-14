# -*- coding: utf-8 -*-
"""Build data/enemy_attack.json: real attack fields for act3 spawn enemies.

Why a separate file from enemy_stats.json
-----------------------------------------
enemy_stats.json is keyed by the 179-id qualitative enemy CATALOG and only keeps
hp/atk/def/res. The act3 levels actually spawn 49 enemy ids, several of which
are not in that catalog subset (slime variants, the lr*萨卡兹 wave, ac*假想敌).
The full official enemy_database.json (2234 enemies) covers all 49, so this
builder is keyed directly by the spawn ids seen in data/act3_waves.json and
extracts the attack-relevant fields the battle kernel needs to let enemies hit
back:

  atk / baseAttackTime / attackSpeed / applyWay / rangeRadius / motion

Damage-type caveat (honest limitation): the unpacked table has NO physical vs
arts damage-type field on normal attacks (applyWay only distinguishes
MELEE/RANGED/ALL/NONE, i.e. reach, not element). The kernel therefore treats
enemy normal attacks as physical by default and records the assumption in
_meta.needs_review; arts attackers can be overridden later from curated data.

Stdlib only. Inputs are git-ignored and rebuildable; only derived facts are
committed. Coverage is asserted for every spawn id so a data change fails loudly.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "enemy_attack.json")
WAVES_PATH = os.path.join(ROOT, "data", "act3_waves.json")


def mv(field, default=None):
    if isinstance(field, dict) and "m_value" in field:
        return field["m_value"]
    return default if field is None else field


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def level0_index(ed_rows):
    """enemy id -> level-0 enemyData (the autochess base entry)."""
    out = {}
    for rec in ed_rows:
        eid = rec["Key"]
        for entry in (rec.get("Value") or []):
            if entry.get("level", 0) == 0 and eid not in out:
                out[eid] = entry["enemyData"]
    return out


def build():
    waves = load(WAVES_PATH)
    spawn_ids = sorted({sp["enemy_id"]
                        for lvl in waves["level_stems"].values()
                        for sp in lvl.get("spawns", [])})
    ed_rows = load(os.path.join(GD, "enemy_database.json"))["enemies"]
    base = level0_index(ed_rows)

    enemies, missing = {}, []
    for eid in spawn_ids:
        d0 = base.get(eid)
        if d0 is None:
            missing.append(eid)
            continue
        a = d0.get("attributes", {})
        atk = mv(a.get("atk"), 0) or 0
        enemies[eid] = {
            "name": mv(d0.get("name")),
            "atk": float(atk),
            "base_attack_time": float(mv(a.get("baseAttackTime"), 1.0) or 1.0),
            "attack_speed": float(mv(a.get("attackSpeed"), 100.0) or 100.0),
            "apply_way": mv(d0.get("applyWay"), "NONE"),
            "range_radius": float(mv(d0.get("rangeRadius"), 0.0) or 0.0),
            "motion": mv(d0.get("motion"), "WALK"),
            "deals_damage": float(atk) > 0 and mv(d0.get("applyWay")) != "NONE",
            "damage_family_assumed": "phys",
        }

    if missing:
        raise ValueError("act3 spawn ids missing a level-0 entry: %s" % missing)

    dealers = sum(1 for e in enemies.values() if e["deals_damage"])
    out = {
        "_meta": {
            "description": "卫戍协议 act3 出怪敌人的真实攻击字段（atk/攻击间隔/攻速/攻击方式/射程），由官方解包 "
                           "enemy_database.json 按 act3_waves 的出怪 id 自有解析生成；不含第三方/GPL 数据。",
            "generated_by": "tools/build_enemy_attack.py",
            "source_table": "data/source/gamedata/enemy_database.json (gitignored)",
            "keyed_by": "act3 spawn enemy_id (49 ids from data/act3_waves.json)",
            "level_used": 0,
            "enemy_count": len(enemies),
            "damage_dealers": dealers,
            "non_attackers": len(enemies) - dealers,
            "needs_review": [
                "enemy normal-attack damage family (phys vs arts) is not in the unpacked "
                "table; all enemy attacks are modelled as physical until curated overrides land.",
                "rangeRadius -1 means contact/melee reach; the kernel maps <=0 to blocked-target-only.",
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
    print("wrote %s : %d enemies (%d damage dealers, %d non-attackers)"
          % (args.out, m["enemy_count"], m["damage_dealers"], m["non_attackers"]))


if __name__ == "__main__":
    main()
