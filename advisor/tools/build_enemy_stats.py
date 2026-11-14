# -*- coding: utf-8 -*-
"""Build data/enemy_stats.json: REAL level-0 enemy stats from the official table.

Why this exists
---------------
advisor/effdps.py used to discount physical/arts dealers through three guessed
resistance BANDS per tactical category (BAND_DEF/BAND_RES). Those bands are not
measured: the official unpacked enemy_database.json carries an exact level-0
def / magicResistance for every enemy, and a 179-id join showed the guesses are
wrong in both directions (e.g. special Dor-1 has def=0 not the "high" 600 band;
refraction 假想敌:镜波 has def=450/res=0, the reverse of its low-def/high-res
band). This builder extracts the real level-0 stats so the advisor can use them.

Data flow (all inputs git-ignored and rebuildable, NO third-party/GPL data):
  enemy_database.json -> level-0 attributes (maxHp/atk/def/magicResistance)
  enemy_catalog.json  -> canonical Chinese name, enemy_ids, trait_keys, rank

Level choice
------------
Every catalog id has a level-0 entry (verified across all 179). The autochess
level files reference enemies with enemyDbRefs level=0 / overwrittenData=null,
so level 0 is the in-mode base. The handful of ids that also carry a level-1
entry use it as an elite-upgrade ladder, not the autochess spawn; we read only
level 0 and record whether a higher level exists for review. No per-level DEF/
RES multiplier is applied (none is published; DEF/RES stay static while HP is
scaled separately by advisor/regulation_hp.py).

Stdlib only. Output is numeric facts keyed by the same canonical names as the
catalog; the catalog itself stays purely qualitative.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "enemy_stats.json")


def mv(field, default=None):
    """Unwrap the official {m_defined, m_value} envelope."""
    if isinstance(field, dict) and "m_value" in field:
        return field["m_value"]
    return default if field is None else field


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def level0_index(ed_rows):
    """enemy id -> level-0 enemyData (the autochess base entry)."""
    out = {}
    has_higher = set()
    for rec in ed_rows:
        eid = rec["Key"]
        entries = rec.get("Value") or []
        for entry in entries:
            lvl = entry.get("level", 0)
            if lvl == 0 and eid not in out:
                out[eid] = entry["enemyData"]
            elif lvl and lvl > 0:
                has_higher.add(eid)
    return out, has_higher


def stats_of(enemy_data):
    a = enemy_data.get("attributes", {})
    return {
        "hp": mv(a.get("maxHp")),
        "atk": mv(a.get("atk")),
        "def": mv(a.get("def")),
        "res": mv(a.get("magicResistance")),
    }


def build():
    catalog = load(os.path.join(ROOT, "data", "enemy_catalog.json"))
    ed_rows = load(os.path.join(GD, "enemy_database.json"))["enemies"]
    base, has_higher = level0_index(ed_rows)

    enemies = {}
    missing = []
    for name, entry in catalog["enemies"].items():
        ids = entry.get("enemy_ids", [])
        per_id = {}
        for eid in ids:
            ed = base.get(eid)
            if ed is None:
                missing.append(eid)
                continue
            st = stats_of(ed)
            # res is a 0..100 percentage; keep int def, round res for storage.
            per_id[eid] = {
                "hp": int(st["hp"]) if st["hp"] is not None else None,
                "atk": int(st["atk"]) if st["atk"] is not None else None,
                "def": int(st["def"]) if st["def"] is not None else None,
                "res": round(float(st["res"]), 3) if st["res"] is not None else None,
                "has_higher_level": eid in has_higher,
            }
        if not per_id:
            continue
        # Name-level view: stats are identical across same-name ids in practice;
        # expose every id and a representative (first) for convenient lookup.
        first = next(iter(per_id.values()))
        enemies[name] = {
            "trait_keys": entry.get("trait_keys", []),
            "rank": entry.get("rank"),
            "is_flying": entry.get("is_flying", False),
            "enemy_ids": ids,
            "stats": {k: first[k] for k in ("hp", "atk", "def", "res")},
            "by_id": per_id,
        }

    if missing:
        raise ValueError("enemy ids missing a level-0 database entry: %s"
                         % sorted(set(missing)))

    # Category worst-case aggregation: the armor-fit score must hold against the
    # tankiest enemy that can appear under each trait key (mirrors the old
    # "worst band wins" rule, but now from REAL stats instead of guessed bands).
    by_trait = {}
    for name, e in enemies.items():
        for trait in e["trait_keys"]:
            slot = by_trait.setdefault(trait, {"def": [], "res": [],
                                               "names": []})
            slot["def"].append(e["stats"]["def"])
            slot["res"].append(e["stats"]["res"])
            slot["names"].append(name)
    category_worst = {}
    for trait, slot in sorted(by_trait.items()):
        category_worst[trait] = {
            "worst_def": max(slot["def"]),
            "worst_res": max(slot["res"]),
            "median_def": sorted(slot["def"])[len(slot["def"]) // 2],
            "median_res": sorted(slot["res"])[len(slot["res"]) // 2],
            "enemy_count": len(slot["names"]),
        }

    out = {
        "_meta": {
            "description": "卫戍协议敌人真实 level-0 数值（def/res/hp/atk），由官方解包表 "
                           "enemy_database.json 经 tools/build_enemy_stats.py 自有解析生成；"
                           "不含第三方/GPL 数据。名录 enemy_catalog.json 保持纯定性，数值独立存放。",
            "generated_by": "tools/build_enemy_stats.py",
            "source_table": "data/source/gamedata/enemy_database.json (gitignored)",
            "level_used": 0,
            "level_note": "autochess enemyDbRefs use level=0; level-1 entries are elite "
                          "ladders, not the spawn base. DEF/RES static across regulation "
                          "levels; HP scaled separately via advisor/regulation_hp.py.",
            "res_unit": "percent 0..100 (magicResistance)",
            "enemy_count": len(enemies),
        },
        "category_worst": category_worst,
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
    print("wrote %s : %d enemies, %d trait categories"
          % (args.out, out["_meta"]["enemy_count"],
             len(out["category_worst"])))
    for trait, c in out["category_worst"].items():
        print("  %-11s n=%3d worst_def=%4d worst_res=%4s"
              % (trait, c["enemy_count"], c["worst_def"], c["worst_res"]))


if __name__ == "__main__":
    main()
